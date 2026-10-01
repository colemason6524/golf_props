# Research Narrative: How We Got Here

Last updated: 2026-09-16

This document is the human-readable story of the project: what we were trying
to learn, what worked, what failed, what the current theory is, and what a new
session must watch for. Operational detail and the exact next task live in
`docs/project_handoff.md`. Use both.

## What This Project Is Trying To Do

The north star is not “pick winners.” It is Bill Benter-style research
discipline applied to PGA props:

1. estimate golfer outcome probabilities from information available before the
   event starts;
2. archive sportsbook prices separately;
3. ask whether the market is miscalibrated relative to those probabilities;
4. only claim value after enough truly out-of-sample graded events.

The performance model and the odds layer are deliberately separated. Odds are
perishable, incomplete, and easy to overfit to. Performance intelligence can
improve even while sportsbook access remains messy.

## Progress Framing (Important)

Do **not** describe the project as literally “halfway through.” Roadmap phases
are not equal in size.

- We are **advanced** on the performance-model foundation: canonical history,
  leakage-safe features, round-relative strength, joint-field simulation,
  rolling validation, frozen incumbent, and a reproducible current-event
  forecast command.
- We are still **early** on prospective validation and market-edge research:
  one genuinely prospective frozen forecast has been graded, the next event has
  not produced an archive, odds history is incomplete, and the frozen simulator
  is not yet the value-report engine.

The binding current gap is **prospective evidence**, not more model complexity
and not sportsbook access.

## The Story So Far

### Phase A — Scaffold and historical bootstrap

We turned docs into a runnable Python research repo, ingested public historical
results (ESPN/Kaggle-style plus CBS 2026), and normalized them into canonical
tables. The lesson was boring and correct: source-local IDs and names must not
leak into modeling assumptions without explicit identity work.

### Phase B — Features and simple baselines

Leakage-safe player-event features and time-split baselines established that
rolling form has signal versus naive base rates. This was useful scaffolding,
not the final performance brain.

### Phase C — Odds reconnaissance

Bovada became the working no-browser odds source. DraftKings sportsbook routes
were discoverable but Akamai-blocked. DraftKings Predictions briefly worked,
then became unreliable. FanDuel still has no stable collector.

Lesson: do not wait on perfect multi-book coverage before building the
performance model. Also: an exploratory Bovada value report later looked
exciting and was scientifically worthless for edge claims because it used older
heuristic rankings, not the frozen simulator.

### Phase D — Round-relative performance and simulation

The core performance theory crystallized:

- public scores are noisy absolute numbers;
- same-event-round field-average relative score is a safer proxy for
  conditions-adjusted performance;
- player strength should be recency-weighted and shrunk;
- placement markets need a joint-field tournament simulator, not independent
  player logits that can sum to nonsense.

Early smoke tests and a single temporal split selected a 180-day / 8-round
configuration. That result was real for that experiment and later superseded.

### Phase E — Rolling freeze of the incumbent

Four rolling annual folds independently selected the same parameters:

- 365-day half-life
- 8-round mean prior
- 20-round variance prior

Across 182 evaluation tournaments, the model beat a structural field baseline
on make-cut through top-5 with bootstrap intervals excluding zero. Winner
improved only barely. Calibration looked decent but slopes > 1 suggested
compressed / under-dispersed probabilities.

This became the frozen incumbent. It is evidence that the performance engine
learns something versus a weak structural baseline. It is **not** evidence of a
betting edge.

### Phase F — Course identity and course challenger

Cross-source course identity initially failed for recent CBS venues: latest-
window matched-course coverage was 0%. A conservative reviewed crosswalk
(`config/course_aliases.csv`) raised that to 62.9886%. One venue,
`Pete Dye Stadium Course PGA West`, remains deliberately unresolved.

After identity repair, the same-course residual challenger was re-evaluated
under a paired rolling protocol. Result: very small, unstable gains; 2025 fold
selected zero effect; paired intervals crossed zero for top-20 through winner.
**Not promoted.** Phase 6 is therefore partially started and partially rejected:
identity + simple residual challenger happened; richer course profiles,
strokes-gained enrichment, and true course-fit modeling have **not** started.

### Phase G — Operational frozen forecasts

`predict-current-event` now hash-verifies frozen inputs, locks 365/8/20, enforces
prospective eligibility, and writes a reproducible forecast bundle.

The Wyndham Championship 2026 run was only possible with
`--allow-retrospective` because its start date equals
`prospective_holdout_after=2026-08-06`. It is permanently labeled
`retrospective_replay`. It proved the plumbing and exposed player-name matching
issues. It must **not** be counted as prospective evidence.

### Phase H — Explicit no-cut event-structure support

The playoff no-cut question was resolved by adding a narrow, explicit
`cut_rule` (`top_n_and_ties` default, `no_cut`) to the simulator and the frozen
workflow, plus a pre-start timestamp guard (`--event-start-at-utc`) so a
forecast cannot be classified prospective if it was created at or after the
first tee. This is a structural adaptation; the frozen 365/8/20 strength
parameters were not changed. Under `no_cut`, `make_cut_prob` is deterministic
(1.0) and is not an empirical target.

Timing reality: St. Jude (2026-08-13) and BMW (2026-08-20, Round 1 already
complete) both closed before this path was available, so neither can be a
prospective bundle. The next genuinely eligible event is the 2026 TOUR
Championship (competitive rounds 2026-08-27 to 2026-08-30), a 30-player no-cut
72-hole stroke-play event at East Lake with all players at even par. Its
official top-30 field is only final after BMW concludes on 2026-08-23.

### Phase I — Weekly forecast automation

The manual weekly loop was turned into a generic, idempotent, fail-closed
pipeline (`weekly-forecast`) so the TOUR Championship and every future event
follow the same discipline: discover from a preserved schedule (CBS is discovery
only), wait for reviewed **official** field and tee-time evidence, resolve
identities via reviewed aliases, run the frozen forecast at T-12 hours into a
staged directory, hash everything into an `archive_manifest.json`, and atomically
promote an immutable bundle. It blocks rather than guesses: unreviewed events,
sportsbook field sources, ambiguous/unmatched names, and missing tee times all
stop the loop with distinct exit codes. A live dry run on 2026-08-21 correctly
selected the TOUR Championship (skipping the in-progress BMW and the excluded
Presidents Cup) and waited for the field.

Deliberate boundary: the weekly loop does **not** refresh historical performance.
The frozen manifest's hashed inputs remain authoritative; an append-only refresh
is a separate scientific decision, not an operational one.

### Phase J — First prospective grade

The archived 2026 TOUR Championship forecast was graded on 2026-09-01 from a
preserved CBS final leaderboard, with no retuning and no `make_cut` score. J.J.
Spaun's zero-round `WD` was excluded under the established historical grading
rule, leaving 29 players per target. Scottie Scheffler was both the model's
highest-probability winner (17.065%) and the actual winner.

The model beat the event's structural baseline on Brier for top-20 (+0.0178),
top-10 (+0.0160), top-5 (+0.0246), and winner (+0.0086). Absolute Brier and log
loss were worse than historical rolling aggregates. A seven-way tie for fourth
created 10 top-5 outcomes, making this event unusually harsh for absolute
top-5 calibration despite the model beating baseline. One event is evidence
that the prospective loop works, not enough evidence to judge stable
calibration, retune, or claim a betting edge.

### Phase K — Private forecast board

The forecast-only Discord board is implemented and deployed to Azure. It accepts
only verified prospective archives, writes an exact payload and delivery receipt
outside the immutable archive, suppresses mentions, and refuses duplicate sends.
The webhook is configured and endpoint-verified. No historical TOUR board was
posted as a smoke test; the next newly archived prospective event will publish
automatically after archive creation.

### Phase L — Autonomous operation

The operator goal became explicit: after setup, do nothing and still receive a
pre-tee board every week. The loop was made autonomous for ordinary events:

- the scheduler advances on its own when an event's window passes (no more manual
  pointer clears; a blocked/finished event cannot pin the loop);
- ordinary stroke-play events are auto-included with a logged default structure,
  so `config/event_registry.csv` becomes an override/exception table rather than a
  required weekly input;
- team, Q-school, and pro-am formats are excluded, and FedExCup Playoff events are
  auto-included under the explicit `no_cut` rule rather than defaulted to a top-65
  cut, because the official schedule only reliably exposes a `PLAYOFF` flag, not
  per-event cut rules — guessing a top-65 cut onto a no-cut or staggered event is
  exactly the guardrail we refuse to cross;
- PGA TOUR field IDs are treated as a source namespace, not canonical IDs, so a
  full field no longer blocks on `unknown_player_id`; players resolve by canonical
  name;
- operational alerts were split onto a separate Discord channel so the board
  channel stays forecast-only, and a `health.json` snapshot exposes scheduler
  state.

The honest limit was the fail-closed identity gate: a field player with no
canonical name match still blocked an event. The operator approved admitting such
players through the documented tour-prior fallback (blank id), so a single longshot
no longer stalls an otherwise-clean ordinary event, while ambiguous or conflicting
identities still fail closed. The operator then removed the last human surface:
FedExCup Playoff events are auto-included under the explicit `no_cut` rule
(starting-stroke adjustments are not modelled) instead of waiting for a reviewed
structure row. Alerting was also simplified: urgent, actionable failures post to
the main channel with a `[URGENT]` prefix, and routine processing is silent, so no
weekly check-in is needed. Net: ordinary and playoff weekly events are now fully
hands-off.

## Current Theory

The working theory of the game, as of 2026-09-16:

1. Pre-tournament relative round form, properly shrunk and jointly simulated,
   is a useful performance prior for cut and placement markets.
2. Same-course residuals, as currently engineered, are too sparse/unstable to
   promote.
3. Sportsbook prices should enter only as a comparison layer after performance
   probabilities are frozen.
4. The scientific bottleneck remains repeated prospective scoring: archive
   forecasts before the event, grade after, and judge calibration/stability
   without retuning.
5. Until repeated prospective evidence accumulates, additional model complexity
   is lower priority than operating the archive, grade, and data-quality loop.

## Successes Worth Keeping

- Raw-source-first and canonical-table discipline.
- Strict point-in-time feature eligibility.
- Odds kept outside the performance model.
- Event-round-relative scoring proxy.
- Four-fold rolling selection converging on 365/8/20.
- Honest non-promotion of the course challenger.
- Hash-verified frozen current-event workflow.
- Explicit `retrospective_replay` labeling instead of quietly loosening the
  prospective rule for Wyndham.
- Adding explicit `no_cut` event-structure support and a pre-start timestamp
  guard rather than inventing cuts or backdating playoff forecasts.

## Failures and Near-Misses Worth Remembering

- Treating DraftKings endpoint discovery as a solved collector.
- Relying on DraftKings Predictions after it went stale.
- An exploratory Bovada value report that looked like edge and was not.
- Course identity breakage that zeroed recent same-course coverage.
- Promoting a course idea before identity repair, then discovering that repair
  alone still did not justify promotion.
- Nearly counting Wyndham as out-of-sample because we had not looked at it
  “enough.” The rule is date eligibility, not vibes.
- Losing the St. Jude and BMW prospective windows while the event-structure
  question was still open. Structure must be resolved before, not during, the
  week of a playoff event.
- Describing progress as “halfway” when phases are unequal; that overstates
  prospective/market readiness.

## What We Are Testing Now

Primary test:

> Does the frozen 365/8/20 simulator produce well-calibrated, stable placement
> probabilities on genuinely prospective PGA events?

Required protocol:

1. identify an eligible event starting strictly after 2026-08-06;
2. preserve an authoritative independent field before the event (official
   top-30 field is final after BMW concludes on 2026-08-23);
3. resolve player identities safely;
4. run `predict-current-event --cut-rule no_cut --event-start-at-utc <verified>`
   without `--allow-retrospective`;
5. archive the complete forecast bundle unchanged;
6. grade top-20/top-10/top-5/winner after the tournament without retuning;
   `make_cut` is structural (1.0) under no-cut and is not a substantive target;
7. repeat across multiple events.

Bovada timestamp collection may continue in parallel. Odds must not block this
loop. Legacy heuristic rankings/value reports remain exploratory only.

## Where We Are On The Calendar (2026-09-16)

- The 2026 TOUR Championship forecast was **archived before the first tee** by
  the now-retired Windows scheduler (2026-08-27T04:00:02Z vs a 15:00:00Z tee,
  `pre_start_verified`) and graded after the final round without retuning. It
  beat the structural baseline on all four placement Brier scores, but one
  event is not a stable calibration sample.
- A state lesson from the same week: after an archive, the loop advances to the
  next event and blocks with exit 10 until a human reviews it. Ten scheduled
  "failures" a day can look like breakage; it is the designed
  operator-review signal. The durable fix is procedural: review the next event
  in the registry promptly after each archive.
- Current event: **Biltmore Championship Asheville** (official R2026557, The
  Cliffs at Walnut Cove, 2026-09-17 to 2026-09-20), a FedExCup Fall main event.
  It is reviewed into the registry with ordinary top-65-and-ties structure and
  included. The Mac and Azure scheduler remain in `awaiting_field` because
  official final field and tee-time evidence have not been imported; no Biltmore
  forecast archive exists.
- The Windows host is retired. The Mac is the durable workspace and bulk-data
  location; the lightweight Azure VM is now the systemd-timer scheduler only.
- Official-vs-discovery timing differs (CBS says Sep 16-19; official says
  Sep 17-20). Discovery dates group weeks only; competitive timing still comes
  exclusively from reviewed tee-time evidence.
- Presidents Cup (2026-09-24 to 2026-09-27) remains excluded (team match play).

## Critical Watch-Outs For The Next Session

These are outward-looking concerns, not settled conclusions. The next agent
should question them before acting.

### 1. Event-structure mismatch on playoff events (resolved in code)

The frozen simulator originally assumed ordinary 72-hole stroke play with a
**top-65-and-ties cut after two rounds**. FedExCup Playoffs events are
**no-cut**. An explicit `cut_rule` (`no_cut`) is now implemented without
changing half-life/priors, and prospective runs require a pre-start timestamp.

The 2026 TOUR Championship was the first eligible no-cut prospective event and
was archived and graded. Future playoff events use the same explicit `no_cut`
rule. Do not backfill after tee time or invent a cut that does not exist.

### 2. Prospective window can be missed

St. Jude and BMW were missed while the event-structure question was still open.
Biltmore is currently waiting for reviewed evidence. If its pre-start window is
missed, do not force a late forecast; wait for the next eligible event.

### 3. Field authority

Prefer the official PGA Tour / FedExCup field, saved under `data/raw/fields/`,
over a sportsbook winner market as the field of record. Bovada can cross-check
availability but should not silently become the performance-model field source.

### 4. Stale performance history relative to the freeze

Canonical results currently run through early/mid July locally
(`source_data_through=2026-07-11` in the frozen manifest). Late-July and early-
August completed events may be missing from the strength history even though
the market has seen them. That is a real prospective-performance handicap.
Refreshing source data is useful, but refreshing must not quietly rewrite the
frozen incumbent parameters or pretend older inspected events became holdout.

### 5. Calibration compression

Rolling diagnostics already show calibration slopes above 1. Probabilities may
be too clustered toward the field mean. Prospective grading should watch this
directly rather than “fixing” it with new features immediately.

### 6. Name matching still silently degrades quality

Wyndham needed explicit IDs for amateur/pro collisions and still had unmatched
punctuation variants (CT Pan, JT Poston, etc.). Unmatched players fall back in
ways that can flatten or distort ranks. Resolve identities; do not bypass
safeguards.

### 7. Weak benchmark temptation

Beating a structural field baseline feels like progress and is necessary, but it
is easy to overclaim. Edge requires archived prices and graded market
comparison. Keep those claims locked until the prospective performance loop is
real.

### 8. Git and data durability

The repository has 11 commits on `main`, while current forecast-board and
grading work remains uncommitted. `data/` is ignored and contains essential
local research state. Multi-machine sync and backup are incomplete. Do not
`git clean` or delete ignored research artifacts.

### 9. Do not reopen settled scientific decisions casually

- Incumbent remains 365/8/20 until a challenger wins the documented paired
  protocol.
- Course residual challenger remains not promoted.
- Wyndham remains retrospective only.
- Legacy Bovada value report remains exploratory only.

## Latest Theory In One Paragraph

Public event-round-relative form, exponentially decayed and shrunk, then pushed
through a seeded joint-field tournament simulator, currently looks like a
credible pre-tournament performance engine versus a structural baseline. Course
identity repair was necessary and insufficient for promoting a same-course
residual. The next scientific step is not a richer model; it is honest
prospective forecasting and grading under correct event-structure assumptions,
with odds kept outside the performance brain.

## Related Documents

- `docs/project_handoff.md` — authoritative state, commands, next task
- `docs/continuation_prompt.md` — copy-ready new-session prompt
- `docs/implementation_roadmap.md` — phase roadmap
- `README.md` — operator overview
- `AGENTS.md` — mandatory pre-change checklist
