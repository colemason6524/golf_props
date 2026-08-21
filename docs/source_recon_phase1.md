# Phase 1 Source Reconnaissance

Date: 2026-07-16

Last updated: 2026-08-05

Current continuity note: the conclusions below remain valid. Bovada is working,
DraftKings sportsbook remains blocked for direct no-browser collection,
DraftKings Predictions is stale/unreliable, and FanDuel remains unsolved. See
`docs/project_handoff.md` for the complete implementation and modeling state.

## Goal

Identify practical source categories for a PGA golf props research database.
This pass is not a scraper implementation. It documents where historical
results, course context, player form, and odds data are likely to come from.

## Guiding Assumption

Start without paid or sportsbook API dependencies. We can use public datasets,
manual downloads, static pages, and raw HTML snapshots to build the research
engine. Paid data can be evaluated later if it fills a specific gap.

Current interpretation: avoid paid/proprietary APIs and avoid manual odds entry
as the normal workflow. A public, unauthenticated sportsbook JSON service route
is acceptable when it can be fetched without browser automation and raw
responses are archived.

## Source Categories

### 1. Public Historical Results Datasets

Potential uses:

- event results
- player finish positions
- round scores
- course names
- basic tournament metadata

Known candidates from reconnaissance:

- Kaggle PGA Tour results datasets, including ESPN-scraped results covering
  2001 through late 2025.
- Kaggle/Advanced Sports Analytics-style PGA datasets with player-level
  tournament rows through 2022.
- Academic datasets such as the Mendeley PGA Tour 1996-2006 dataset.

Pros:

- Good bootstrap path.
- Low engineering friction.
- Enough to create labels for make cut, top 20, top 10, and event results.

Risks:

- May not include strokes gained.
- May not include sportsbook odds.
- Course identity may be messy.
- Some datasets exclude alternate formats or contain ESPN/source errors.

### 2. Official PGA Tour / ShotLink-Facing Data

Potential uses:

- official scoreboards
- player stats
- round and scorecard data
- hole-level data
- live tournament context

Recon notes:

- PGA Tour and ShotLink are the authoritative live/statistical source family.
- Public pages expose rich stats and leaderboard context, but usage rights and
  technical structure need careful review before automation.
- Unofficial clients exist for PGA Tour data shapes, which can help us
  understand available fields, but we should avoid building the project around
  unstable private endpoints at the start.

Pros:

- Best alignment with official results and stats.
- Potentially rich hole/round information.

Risks:

- Terms and publishing restrictions.
- Dynamic pages and changing schemas.
- Some useful endpoints may be private or unofficial.

### 3. Data Golf

Potential uses:

- mature schema reference
- player IDs
- historical raw round data
- historical event stats
- historical odds for outrights and matchups
- model-style thinking around strokes gained, field strength, and course fit

Recon notes:

- Data Golf documents paid API access for historical raw data, event stats,
  historical odds, field updates, live predictions, and betting tools.
- Their public FAQ describes the general modeling idea: estimate player skill in
  strokes-gained units, adjust across fields/tours, then translate skill into
  event outcome probabilities.

Pros:

- Very close to the type of dataset we ultimately want.
- Historical odds support is especially valuable if we decide paid access is
  worth it.

Risks:

- Paid API dependency.
- The user preference for this project is to avoid API dependency at the start.

### 4. GolfStats / Export Services

Potential uses:

- downloadable CSVs
- tournament results
- round scores
- traditional stats
- par-3/par-4/par-5 scoring
- birdies/bogeys/greens/fairways

Recon notes:

- GolfStats advertises CSV exports for members, including recent or multi-year
  data depending on membership level.

Pros:

- CSV export shape would be ideal for a bootstrap.
- Traditional stat fields map directly to round/stat props.

Risks:

- Paid access.
- License restrictions.
- May not include sportsbook odds.

### 5. OWGR

Potential uses:

- current and historical world ranking
- player strength proxy
- field-strength context
- player ranking history

Recon notes:

- OWGR provides current and past rankings, including downloadable archive PDFs
  for historical top 300 rankings.

Pros:

- Useful feature source.
- Gives a stable external strength/rank signal.

Risks:

- PDF parsing if archive files are used.
- Ranking may lag true current form.

### 6. Sportsbook Odds

Original preferred order:

1. FanDuel
2. DraftKings
3. Other books only as fill-ins

Current practical order:

1. Bovada, because it has a working no-browser PGA JSON route.
2. DraftKings Predictions only as a fallback/stale placement-source parser.
3. FanDuel and DraftKings sportsbook pages as future targets.

Potential uses:

- live prop snapshots
- price movement
- market availability
- closing price proxy

Recon notes:

- FanDuel does not appear to offer a public official odds API for individual
  developers.
- DraftKings has broad golf markets and recently expanded golf SGP markets.
- Because historical prop odds are scarce, our own live collection archive is
  likely one of the highest-value assets we can build.
- DraftKings sportsbook bundle inspection revealed backend route families, but
  direct no-browser requests were blocked by Akamai. Endpoint discovery alone is
  not enough.
- Bovada's public route
  `https://www.bovada.lv/services/sports/event/coupon/events/A/description/golf/pga-tour`
  returned current PGA JSON with player names, markets, American prices, event
  links, and status fields.
- Bovada page HTML is mostly an app shell; the useful data is the JSON service
  route, not the rendered page.

Pros:

- Directly tied to the betting markets we care about.
- Snapshot collection can create our own history over time.

Risks:

- Dynamic pages.
- Market labels can change.
- State/location behavior can affect availability.
- Terms and responsible collection limits matter.

## Recommended First Source Stack

### Bootstrap Historical Layer

Use a public CSV-style PGA results dataset to build:

- events
- players
- player event results
- round scores where available
- make-cut and top-N labels
- course-history features

### Live Odds Layer

Build raw snapshot collectors around visible sportsbook pages, starting with:

- Bovada PGA JSON service responses
- FanDuel/DraftKings only after a reliable no-browser route is proven

The first working collector saves raw JSON and then writes canonical odds
snapshot rows. Browser screenshots are not part of the preferred flow.

### Validation / Enrichment Layer

Use official or public reference pages for:

- event schedule
- field lists
- withdrawals
- tee times
- final results
- weather/course condition context

## Source Evaluation Checklist

For every source, record:

- source name
- source URL
- data type
- tour coverage
- historical depth
- file/page/API shape
- login/paywall boundary
- terms/robots notes
- timestamp semantics
- player IDs available
- event/course IDs available
- market/odds coverage if any
- grading reliability
- parse difficulty
- recommended use

## Phase 1 Conclusion

Yes, we can find historical golf data much like the horses project, but not all
pieces will be equally available for free.

The most realistic path is:

1. Bootstrap historical performance from public datasets.
2. Build our own Bovada sportsbook snapshot archive immediately.
3. Add course, weather, and player-form enrichment incrementally.
4. Treat paid data sources as optional accelerators, not foundations.

Post-recon implementation note:

`src/golf_props/odds/bovada.py` now implements the first usable no-browser odds
collector. It normalizes `winner`, `top5`, `top10`, `top20`, `make_cut`,
`round_leader`, and `round_score_ou` when those markets appear. The latest
observed current PGA feed did not include round score O/U, so round O/U support
is parser-ready but not yet proven as consistently available week to week.
