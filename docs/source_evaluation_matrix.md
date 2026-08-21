# Source Evaluation Matrix

Date: 2026-07-16

Last updated: 2026-08-05

Current continuity note: Bovada remains the only working automated no-browser
odds source. The performance incumbent and course-challenger findings are
documented in `docs/project_handoff.md`; this matrix remains the detailed
source-by-source reference.

## Evaluation Lens

The project needs sources that can support:

- historical player-event results
- round scores
- course history
- current/recent form
- course fit and hole/yardage tendencies
- field strength
- weather/tee-wave context
- sportsbook odds snapshots
- reliable grading for props

## Summary Verdict

The best starting stack is now:

1. Public PGA results dataset for historical labels and course history.
2. OWGR or similar ranking history for field/player strength.
3. Bovada no-browser odds snapshots collected by us.
4. PGA Tour/public stat pages for validation and enrichment.
5. Paid sources only if we want to accelerate strokes-gained, historical odds,
   or richer stat coverage.

No single free source appears to provide everything we need.

## Source Matrix

| Source | Fit | What It Gives | Missing / Risk | Recommendation |
| --- | --- | --- | --- | --- |
| Kaggle PGA Tour Results 2001-Dec 2025 | High bootstrap value | Event results scraped from ESPN, 1,000+ events, public-domain license note | May lack strokes gained, prop odds, deep hole data, and may inherit ESPN errors | Use first for event/result labels and course-history scaffold |
| Kaggle / Advanced Sports Analytics PGA 2015-2022 | Medium-high bootstrap value | Player-level tournament rows through 2022, public CC0 mirror, compact CSV-style dataset | Shorter date range than ESPN dataset; fields need local inspection | Use as second bootstrap candidate or feature supplement |
| GolfStats Data Export | High data value, paid | Tournament metadata, course, par, yardage, round scores, finish, money, fairways, driving distance, greens, putts, par-3/4/5 scoring, eagles/birdies/pars/bogeys | Membership/paywall and usage restrictions; no sportsbook odds | Strong paid/export candidate if we want traditional stat props sooner |
| Data Golf API | Very high data value, paid/API | Player IDs, schedules, fields, tee times, strokes gained, raw round data, historical event stats, historical odds, model probabilities, course fit | Paid Scratch Plus/API dependency; user preference is no API foundation | Treat as model/data-shape reference now; possible accelerator later |
| Data Golf public pages | Medium reference value | Course history, course fit, rankings, methodology, some public model context | Not a clean bulk data source; scraping may be brittle or inappropriate | Use for thinking and manual validation, not core ingestion |
| PGA Tour official stats/pages | High authority, medium ingestion value | Official stats, scoring, strokes gained categories, player/course stat pages | Dynamic pages, terms considerations, private-ish data shapes, possible rate/format instability | Use cautiously for validation and targeted enrichment |
| ShotLink | Highest theoretical value | Shot-level official data and real-time shot context | Not publicly available in bulk; licensing barrier | Not a starting source; important conceptual north star |
| OWGR archive | Medium-high feature value | Historical ranking archives, player strength and field-strength proxy | PDFs require parsing; rankings are not direct performance probabilities | Use for field/player strength features after results scaffold |
| Bovada sports JSON service | High current market value | Working PGA odds JSON for winner, top 5, top 10, top 20, first-round leader, make-cut subset, matchups/groups/specials depending on event | Unofficial/public service route, market availability varies, not guaranteed historical, not FanDuel/DK pricing | Current primary automated odds source |
| FanDuel sportsbook pages | High market value, not solved | Desired live odds and props if pages expose markets reliably | No public developer API; dynamic pages; market availability varies; historical props scarce; no stable no-browser collector in repo | Keep as future source target |
| DraftKings sportsbook/pages | High market taxonomy value, not solved | Broad golf markets: winner, top-N, tournament H2H, round matchups, round scores, birdies, GIR, fairways, pars, bogeys | Direct no-browser backend requests were blocked by Akamai; dynamic/state behavior; historical collection still ours to build | Use as market taxonomy/reference, not current automated source |
| DraftKings Predictions | Medium fallback value, currently unreliable | Previously yielded winner/top5/top10/top20-style placement rows for The Open | Current linked/static collection can fail with zero parsed rows; not round O/U; stale reports should not be treated as live source readiness | Keep parser/tests, but do not rely on it as the backbone |
| DraftKings rules/support | High grading value | Settlement/void/dead-heat rules, market definitions | Not odds data | Use to implement market grading correctly |
| FanDuel Research / numberFire content | Medium feature inspiration | Course key stats, simulations, course-history narrative, betting-market education | Editorial/model output, not raw data; historical consistency uncertain | Use for feature ideas and sanity checks, not training rows |
| BallDontLie PGA API | Very high exact prop fit, paid/API | Documented PGA player props including round score, birdies, pars, GIR, fairways, putts, finishing position, make cut, with FanDuel/DK vendors | Requires paid GOAT tier/API and violates the no-paid-API foundation | Useful reference for prop taxonomy only unless project constraints change |
| Kalshi / Polymarket | Low-main, possible supplemental | Free APIs may expose exchange markets for major golf outrights/event questions | Coverage for top-N and round O/U is not expected to be broad enough; prices are prediction-market contracts, not sportsbook lines | Supplemental only, not a replacement for sportsbook odds |

## What Each Key Source Can Support

### Historical Labels

Good candidates:

- Kaggle PGA Tour Results 2001-Dec 2025
- Kaggle / Advanced Sports Analytics PGA 2015-2022
- GolfStats export if paid
- Data Golf historical event stats if paid/API

Needed labels:

- `made_cut`
- `top20`
- `top10`
- `top5`
- `win`
- `finish_position`
- `round_score`
- `withdrawn`
- `disqualified`

### Recent Form

Good candidates:

- public results datasets for simple rolling finishes/scores
- GolfStats for richer traditional stat trends
- Data Golf for strokes-gained form if paid/API
- PGA Tour stat pages for targeted validation

Best first version:

- rolling average finish
- rolling score to par
- made-cut streak/rate
- top-20 rate
- recent round score average
- event-weighted recency decay

### Course History

Good candidates:

- public event-results datasets if course names are included
- GolfStats for course played, par, yardage, and player history
- Data Golf public pages/API for course history/fit reference

Important caveat:

Course history should not be over-weighted early. We need enough samples and
should separate course-history features from broader course-fit features.

### Course Fit / Hole Tendencies

Good candidates:

- GolfStats traditional stat exports
- Data Golf approach/strokes-gained/course tools if paid/API
- PGA Tour official stats pages if accessible and appropriate

Hard fields to get for free:

- hole-by-hole strokes gained
- shot-level approach buckets
- course-specific shot difficulty
- historical wind/wave-adjusted scoring

First approximation:

- course par and yardage
- par-3/par-4/par-5 scoring fit
- driving-distance/accuracy fit
- approach/GIR fit
- scrambling/putting fit

### Odds / Props

Good candidates:

- our own Bovada snapshots
- future FanDuel snapshots if a stable no-browser route is found
- future DraftKings snapshots if a stable no-browser route is found
- Data Golf historical odds if paid/API

Important market fields:

- sportsbook
- market type
- player/selection
- line
- American/decimal price
- captured timestamp
- source URL
- market status
- whether it is an opening, current, or closing proxy

Current Bovada market types normalized by code:

- `winner`
- `top5`
- `top10`
- `top20`
- `make_cut`
- `round_leader`
- `round_score_ou` when posted

### Grading Rules

Good candidates:

- DraftKings golf rules/support pages
- sportsbook house rules
- official final results

Grading needs:

- ties/dead heat handling
- withdrawal/WD void rules
- round incomplete rules
- playoff exclusion for stat props
- make-cut settlement quirks
- top-N including ties vs dead-heat markets

## First Practical Decision

Start with free historical results and build the database even if it is
stat-light. Do not wait for perfect strokes-gained or historical prop data.

The first useful model can be:

```text
player-event history
  + recent form
  + course history
  + field strength proxy
  + Bovada market price snapshot
  -> make_cut / top20 / top10 / top5 / winner probability
```

Then add richer stat/course/weather layers as they become available.

## Open Questions

1. Can the Kaggle ESPN results dataset be downloaded and inspected locally?
2. Does it include round scores and course names in stable columns?
3. Does the 2015-2022 dataset include enough traditional stats to build
   first-pass course-fit features?
4. Can Bovada's route expose round score O/U consistently during tournament
   week or only for some events/majors?
5. Can FanDuel golf pages be collected reliably from this machine without login
   or state/location blockers?
6. Should we buy/export GolfStats if public datasets lack round/stat detail?
7. Should paid Data Golf be considered later specifically for historical odds,
   not as the first project foundation?
