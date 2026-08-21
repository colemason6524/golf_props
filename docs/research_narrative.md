# Research Narrative: How We Got Here

Last updated: 2026-08-10

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
  zero genuinely prospective frozen forecasts have been graded, odds history is
  incomplete, and the frozen simulator is not yet the value-report engine.

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

## Current Theory

The working theory of the game, as of 2026-08-10:

1. Pre-tournament relative round form, properly shrunk and jointly simulated,
   is a useful performance prior for cut and placement markets.
2. Same-course residuals, as currently engineered, are too sparse/unstable to
   promote.
3. Sportsbook prices should enter only as a comparison layer after performance
   probabilities are frozen.
4. The scientific bottleneck is now repeated prospective scoring: archive
   forecasts before the event, grade after, and judge calibration/stability
   without retuning.
5. Until that prospective loop exists, additional model complexity is mostly
   entertainment.

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

## Failures and Near-Misses Worth Remembering

- Treating DraftKings endpoint discovery as a solved collector.
- Relying on DraftKings Predictions after it went stale.
- An exploratory Bovada value report that looked like edge and was not.
- Course identity breakage that zeroed recent same-course coverage.
- Promoting a course idea before identity repair, then discovering that repair
  alone still did not justify promotion.
- Nearly counting Wyndham as out-of-sample because we had not looked at it
  “enough.” The rule is date eligibility, not vibes.
- Describing progress as “halfway” when phases are unequal; that overstates
  prospective/market readiness.

## What We Are Testing Now

Primary test:

> Does the frozen 365/8/20 simulator produce well-calibrated, stable placement
> probabilities on genuinely prospective PGA events?

Required protocol:

1. identify an eligible event starting strictly after 2026-08-06;
2. preserve an authoritative independent field before the event;
3. resolve player identities safely;
4. run `predict-current-event` without `--allow-retrospective`;
5. archive the complete forecast bundle unchanged;
6. grade after the tournament without retuning;
7. repeat across multiple events.

Bovada timestamp collection may continue in parallel. Odds must not block this
loop. Legacy heuristic rankings/value reports remain exploratory only.

## Where We Are On The Calendar (2026-08-10)

- Prospective threshold: events must start **strictly after** 2026-08-06.
- Wyndham (start 2026-08-06): retrospective engineering replay only.
- Next PGA slate after Wyndham: FedExCup Playoffs.
  - FedEx St. Jude Championship: competitive dates **2026-08-13 to 2026-08-16**
    at TPC Southwind; top-70 qualifying field, about 69 starters after a
    withdrawal, **no cut**.
  - BMW Championship: 2026-08-20 to 2026-08-23; ~50 players; playoff structure.
  - TOUR Championship: 2026-08-24 to 2026-08-30; 30 players; special format.
- As of this handoff evening, no prospective forecast bundle has been archived
  yet. The St. Jude pre-tournament window is open only until Thursday tee times.

## Critical Watch-Outs For The Next Session

These are outward-looking concerns, not settled conclusions. The next agent
should question them before acting.

### 1. Event-structure mismatch on playoff events (highest priority)

The frozen simulator assumes ordinary 72-hole stroke play with a
**top-65-and-ties cut after two rounds**. FedEx St. Jude is a **no-cut**
~69-player field. BMW and the TOUR Championship also violate ordinary full-field
cut assumptions.

Blindly running `predict-current-event` with frozen `cut_size=65` on St. Jude
would invent a cut that does not exist and distort make-cut and placement
probabilities. Changing half-life/priors is retuning and forbidden. Encoding the
true event structure (no-cut / field-size cut) is a different question and must
be handled explicitly, documented in the run manifest, and not confused with
parameter hunting.

If no-cut support is not cleanly available, the honest first prospective event
may need to be the next ordinary full-field cut tournament after the playoffs,
not a forced playoff forecast.

### 2. Prospective window can be missed

St. Jude starts 2026-08-13. If the handoff is opened after Thursday tee times,
do not backfill a “prospective” forecast. Move to the next eligible event and
keep the eligibility rule strict.

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

There are still no Git commits. Code/docs are untracked; `data/` is ignored.
Multi-machine sync and backup are incomplete. Do not `git clean` or delete
ignored research artifacts.

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
