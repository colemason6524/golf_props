# Prototype Plan

Date: 2026-07-16

Last updated: 2026-08-05

## Guiding Idea

Bill Benter-style thinking is useful here, but golf should start as a
performance model rather than a winner-only model. Once we can estimate player
skill and event outcome distributions, we can translate those estimates into
probabilities for props such as make cut, top 20, matchups, and outrights.

The first edge will probably come from data discipline rather than model
complexity: collecting the right historical context, preserving timestamps, and
avoiding after-the-fact leakage.

## Initial Research Questions

1. Can we assemble a point-in-time-safe player-event dataset for PGA events?
2. Can recent form plus course fit improve on market-implied probabilities?
3. Can course history and hole-level tendencies add predictive signal without
   overfitting?
4. Can we collect Bovada props snapshots often enough to study line movement
   and closing-market behavior?
5. Which prop markets are easiest to grade reliably from public results?

## Starting Market Order

### Phase 1 Markets

- `make_cut`
- `top20`
- `top10`
- `top5`
- `winner`

These are good first targets because they connect cleanly to event-level
results and can be modeled from player strength, course fit, and field context.
Winner is included in the current pipeline because it is broadly posted and
useful for market comparison, but it should be interpreted cautiously.

### Phase 2 Markets

- round score over/under
- birdies or better
- bogeys
- greens in regulation
- fairways hit

These are more granular and appealing, but they require dependable round-level
or hole-level history and cleaner grading.

The Bovada parser already recognizes `round_score_ou` when a market is posted
with over/under score outcomes. The current latest PGA feed did not expose this
market, so the next validation step is collection across more tournament weeks
and between rounds.

### Later Markets

- outright winner
- first-round leader
- placement ladders beyond top 20
- same-game golf correlations

Outrights are closest to horse-race win modeling, but golf fields are large and
the event count is small, so they should not be the first validation target.

## Required Data

### Historical Performance

- event schedule
- event results
- player field
- round scores
- cut status
- finish position
- strokes gained when available
- traditional stats such as GIR, fairways, driving distance, scrambling,
  birdies, bogeys, par-3/par-4/par-5 scoring

### Course Context

- course name and stable course ID
- par and yardage
- location
- grass type if available
- hole pars and yardages
- historical scoring by hole
- event-course mapping when an event rotates courses

### Player Context

- player ID crosswalk across sources
- recent rounds
- weighted recent strokes or scoring form
- long-term baseline skill
- course history
- comp-course history
- current world ranking or field-strength proxy
- injury/withdrawal status when available

### Market Context

- sportsbook
- event
- player
- market
- line
- price
- captured timestamp
- market status if visible
- closing snapshot if available

### Weather / Conditions

- forecast and observed wind
- temperature
- precipitation
- tee-time wave
- round start time
- course/weather condition notes where available

## First Architecture

1. `raw` layer
   - Store fetched or manually downloaded pages/files exactly as collected.
   - Include URL/source, requested timestamp, status, content hash, and raw path.

2. `parsed` layer
   - Source-specific records with source IDs and source labels intact.
   - Avoid early assumptions about canonical player/course names.

3. `canonical` layer
   - Normalize events, courses, players, rounds, results, stats, and odds.

4. `feature` layer
   - Build only pre-event or pre-round features available at decision time.
   - Use rolling windows and exclude the current event from historical summaries.

5. `model` layer
   - Begin with simple baselines: market-only, player baseline skill, recent
     form, course history, and course-fit variants.

6. `backtest` layer
   - Evaluate calibration, Brier/log loss where appropriate, ROI-like value
     selection, and closing-line movement.

## Minimal Build Order

1. Create canonical schema and source contracts.
2. Bootstrap with a public historical PGA results dataset.
3. Add player/course/event normalization and ID crosswalks.
4. Build make-cut/top-20 labels.
5. Build recent-form and course-history features.
6. Add a market odds snapshot format using manually saved or scraped sportsbook
   pages.
7. Score a market baseline from captured prices.
8. Run the first time-split backtest.
9. Expand to round-level and hole-level features after the event-level pipeline
   proves itself.

Current implementation status:

1. Canonical schemas and source contracts exist in code and docs.
2. Historical PGA result normalization and 2026 CBS enrichment exist.
3. Player/course/event normalization and merge flows exist.
4. Make-cut/top-N/winner labels and features exist.
5. Recent-form, weighted recent-form, course-history, major/open-event features
   exist.
6. Bovada odds snapshots are automated; manual odds remain a test/backup path,
   not the intended workflow.
7. Current-event rankings and value reports exist.
8. Time-split baselines exist.
9. Event-round-relative strength and field-level tournament simulation exist;
   richer round-prop and hole-level modeling remains future work.
10. Simulator decay/shrinkage selection uses a validation-only grid and a
    disjoint later test window.
11. Rolling-origin validation spans four annual folds, uses whole-event
    bootstrap intervals, reports calibration diagnostics, and freezes a hashed
    future-model manifest.
12. A leakage-safe same-course residual challenger has been evaluated with
    paired seeds. Its incremental signal was too small and unstable for
    promotion; cross-source course identity must be repaired before the next
    course-fit attempt.

Current identity caveat: player mapping exists across the ESPN/CBS merge, but
course mapping does not. “Player/course/event normalization exists” elsewhere
in this plan should not be read as proof that cross-source course identity is
solved.

## Leakage Risks

1. Using final event stats as pre-tournament features.
2. Treating closing or post-start odds as if they were available at open.
3. Letting current-event rounds enter the player recent-form features.
4. Using course-history samples after the event date.
5. Mixing historical venue names without course identity checks.
6. Ignoring withdrawals, missed cuts, alternate-field events, and format
   differences.
7. Using weather that was observed after a round as if it was forecast before
   betting.

## Practical Starting Assumptions

- PGA first keeps the universe manageable.
- Bovada is the current working sportsbook source. FanDuel and DraftKings are
  still valuable targets, but they are not solved here.
- We should collect live sportsbook JSON snapshots heavily because historical
  prop odds are the scarcest free data.
- Data Golf is an important reference for what mature golf data looks like, but
  the initial scaffold should not depend on paid API access.
- Public datasets can bootstrap historical results and round scores, but they
  probably will not give us complete historical prop prices.

## Design Tradeoffs

- Pre-tournament prediction is the current priority. Live tournament state and
  in-progress round modeling are intentionally deferred.
- Raw sportsbook responses are archived before parsing. This costs storage but
  protects the research asset when parsers need to be fixed later.
- The model can rank outright winners, but value reports separate stronger
  placement/make-cut candidates from speculative winner longshots.
- Unmapped Bovada markets are excluded by default to keep the main value
  pipeline clean; use `--include-unmapped` when exploring new market types.
