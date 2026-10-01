# Azure Deployment

Last updated: 2026-09-16

The Mac is the durable research workspace and source of truth. The small Azure
VM is a Linux scheduler only: it runs the frozen weekly forecast workflow and
the limited Bovada collection through user-level systemd timers. It is not a
second research workstation and must not receive historical experiments or
large raw archives.

## Layout

- Mac workspace: `/Users/colemason/Documents/golf_props`
- Durable bulk data/archive: Mac and external drive
- Azure user: `azureuser`
- Azure checkout: `/home/azureuser/golf_props`
- Azure virtual environment: `/home/azureuser/golf_props/.venv`
- Azure systemd user units: `~/.config/systemd/user/`
- Azure connection: use the existing SSH identity and host configuration; do
  not put private-key paths or credentials in this repository.

## Required Azure Data

Keep only the frozen operational inputs and current operational state on Azure:

```text
data/processed/pga_2001_2026/
data/interim/features/pga_2001_2026_round_performance.csv
data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json
data/raw/current_events/
data/raw/fields/
data/interim/weekly/
data/interim/reports/forecast_delivery/
```

The first three items are required for hash-verified frozen forecasts. Preserve
the VM's generated odds snapshots, forecast archives, current-event evidence,
weekly state, and logs until they have been copied back to the Mac. Do not use
`rsync --delete` against either research-data copy.

## Installation

On Azure, after a code update and any required append-only operational-data
copy:

```bash
cd ~/golf_props
git pull --ff-only
.venv/bin/python -m pip install -e ".[dev]"
scripts/linux/install_systemd_timers.sh
loginctl enable-linger "$USER"
systemctl --user list-timers --all sports-golf-forecast.timer sports-golf-bovada.timer
```

`loginctl enable-linger` is required once so user timers continue while no SSH
session is open and resume after a VM reboot. The installer is idempotent and
updates only the two golf timers and services.

## Schedule

| Unit | Schedule | Purpose |
|---|---|---|
| `sports-golf-forecast.timer` | Every two hours at minute 17, America/Detroit | Run the fail-closed weekly frozen forecast loop |
| `sports-golf-bovada.timer` | Monday, Wednesday, Thursday at 08:56, America/Detroit | Preserve current Bovada PGA odds snapshot |

Both timers use `Persistent=true`: a VM restart or downtime causes one missed
activation to run when the user manager returns. The forecast code still
enforces the pre-start guard, so a late recovery cannot backfill a forecast.

Timing: the forecast uses exact tee times when available; otherwise it falls
back to the official event date with a conservative 22-hour night-before offset.
This removes the dependency on tee-time availability while preserving the
pre-start safety guard.

## Operations

```bash
systemctl --user status sports-golf-forecast.timer sports-golf-bovada.timer
systemctl --user list-timers --all sports-golf-forecast.timer sports-golf-bovada.timer
journalctl --user -u sports-golf-forecast.service -u sports-golf-bovada.service -n 100 --no-pager
cd ~/golf_props && .venv/bin/python -m golf_props.cli weekly-forecast-status
```

The weekly workflow exit codes are intentional: `0` is waiting or archived,
`10` is a hard configuration block, `11` is a missed deadline, `12` is an
identity block, and `20` is a hard error. Inspect the saved status and logs
before changing configuration. Do not make a timer retry override the forecast
pipeline's prospective or identity safeguards.

The loop is autonomous for ordinary and playoff events. When an event's window
passes without a forecast it is closed automatically and the scheduler advances to
the next eligible event, so a finished tournament does not require manually
clearing a pointer. Team, Q-school, and pro-am formats are recorded as skipped, and
FedExCup Playoff events are auto-included under the explicit `no_cut` rule (never
given a guessed top-65 cut). Routine processing is silent; only urgent,
actionable failures alert. The old Windows Task Scheduler host is retired; systemd
timers are the sole scheduler and the unused tmux helper scripts are not part of
the deployment.

## Autonomous Operation

No per-tournament human step is required: the loop discovers the event,
auto-classifies ordinary stroke-play structure, auto-includes FedExCup Playoff
events under the explicit `no_cut` rule, collects the official field, resolves
players by canonical name even when the source uses different IDs, forecasts on
exact tee times or the 22-hour night-before official-date fallback, verifies the
immutable archive, and publishes the forecast-only board. Operator review is
needed only if the loop emits an urgent alert about a genuinely ambiguous identity
or a hard failure.

## Private Forecast Board

After a verified prospective archive exists, the weekly forecast pipeline
publishes it automatically when the protected webhook is configured. Manual
publication is also available:

```bash
cd ~/golf_props
.venv/bin/python -m golf_props.cli publish-forecast-board \
  --archive-dir data/interim/reports/prospective_forecasts/<event_key>
```

Store `GOLF_PROPS_DISCORD_WEBHOOK_URL` only in
`~/.config/golf_props/env` with mode 600. Delivery artifacts are written under
`data/interim/reports/forecast_delivery/<event_key>/`; duplicate delivery is
refused unless `--resend` is explicit.

## Operational Alerts

Urgent operational alerts are posted to the same private channel as the forecast
board using the existing `GOLF_PROPS_DISCORD_WEBHOOK_URL`; each message is
prefixed with `[URGENT]`. No second webhook is required. Only actionable failures
alert: discovery/hard errors, missed deadlines, ambiguous or conflicting
identities, archive/forecast refusal, and Discord delivery failures. Routine
processing (ordinary events, auto playoff inclusion, exclusions, and no-history
tour-prior admissions) stays silent, so regular check-ins are unnecessary. If the
webhook is unset, alerts are suppressed and the loop still runs. Operator-facing
state is mirrored in `data/interim/weekly/health.json` (last success, current
event, last error, last delivery, skipped-this-run).
