# Golf Props: local recovery and check-in

Local development: `/Users/colemason/Predictions/golf_props`. Production: `azureuser@130.131.0.6:/home/azureuser/golf_props`.

The deployed working tree, ignored research data, outputs, logs and Git object store were copied. Uncommitted production changes are preserved. Recorded production HEAD: `7cbe7bb0f2c0b6417e331740b21e7b8d65b209ae`. Source manifests and checksums are in `../../_recovery/inventory/` and `../../_recovery/evidence/`.

Production timers continue on Azure. Local setup does not launch a forecast, collection run, publisher or scheduled job. Secrets remain on their source machines. Existing older Mac folders were left in place.

## First check-in

- Open the local dashboard at `http://127.0.0.1:8790/p/golf_props` after using `../../Open Dashboard.command`.
- Read [the full recovered diary](RECOVERED_DIARY.md), then the current project contract and operations notes linked by the dashboard.
- Latest recorded summary (2026-11-03T12:34:14+00:00): Deployed reviewed 12-file display/price-readiness patch 2026-11-03 (~12:58Z): real-price display, coverage/unpriced reasons, settlement disclosure. Live suite 365 passed + 5 pre-existing environment failures (proven identical on baseline: durable activation state holds legacy grades by design). Cold-start rejected/disabled. Next observation WWT board due 11-04.
- Watching for: WWT board 11-04; recap fingerprint reconciliation before any re-post
- Next action: Observe WWT board; reconcile recap fingerprint before re-posting corrected disclosure
- Current check-back: `{"kind": "calendar", "label": "Display patch deployed; watch WWT board", "target": 3, "baseline": "2026-11-03T12:34:14+00:00", "events": [], "target_date": null, "monitoring": false}`. Recovery did not restart this observation window.
- Inspect actual dated artifacts and logs before claiming the latest scientific or operational result. Diary claims and test passes do not prove natural production output.

## Local Python and tests

A private macOS Python 3.10 runtime lives under `../../_recovery/python/`. This project's `.venv` uses captured production package versions, with native Mac wheels. Exact install input: `../../_recovery/environments/golf_props.local.txt`; original Linux package inventory: `../../_recovery/environments/golf_props.production.txt`.

From this project directory:

```sh
source .venv/bin/activate
PYTHONPATH=src:. python -m pytest tests -q
```

The completed recovery test run disabled outbound connections and removed credential variables from its environment. See `../../_recovery/evidence/tests-golf_props.log` and the local test summary in `../../VERIFICATION.md`. No new scientific changes were made to resolve inherited test failures.

## Production services observed

Timers: `sports-golf-bovada.timer`, `sports-golf-forecast.timer`.

Services: `sports-golf-bovada.service`, `sports-golf-forecast.service`.

Retained unit definitions and the full available sports systemd journal are in `../../_recovery/archives/azure-operations.tar.gz`. That archive also contains sanitized environment configuration and consistent SQLite snapshots. Do not install the unit files on this Mac.

## Credentials

[Captured production environment](PRODUCTION_ENVIRONMENT.md) preserves non-secret runtime flags for comparison; no credential value or auto-loading was added.

Create local credentials only if a future task actually needs them. Use this project's documented environment-variable interface, a local ignored file and private permissions; do not copy production credentials from Azure. Local tests and dashboard observation require no provider credentials. Azure observation uses the existing SSH identity.

Environment variable names found on production (values intentionally not copied here):

- `env`: `GOLF_PROPS_DISCORD_WEBHOOK_URL`

## Recovered desktop work

[Project-specific history index](WINDOWS_HISTORY.md) lists matching desktop investigations.

Desktop code, worktrees, investigations, notes and test/deployment receipts are retained in compressed archives under `../../_recovery/archives/`. Their contents are indexed in `../../_recovery/inventory/`. See `../../RECOVERY.md` for browsing and extracting one historical file. Historical worktrees are evidence, not an automatic replacement for the deployed version.

## Maintaining the diary

Keep `.dashboard/journal.jsonl` append-only. Its last valid entry drives the board; `.dashboard/checkpoint.json` mirrors it. Existing legacy invalid entries are retained and described in `../../_recovery/evidence/diary-validation-details.json`. Do not silently delete history or reset an experiment baseline.

From `../../dashboard`, use `python3 -m dashboard checkpoint-update --no-sync ...` for a local-only authoring entry. Without `--no-sync`, that command writes diaries back to Azure; review the concrete entry and deployment state first.

Git historically tracks a Linux `.venv` in this repository. The rebuilt Mac environment therefore produces many runtime-only Git changes. Do not stage `.venv`; use named source paths. The migration preserves the historical Git index and makes no cleanup commit.
