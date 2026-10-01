# Product Contract: Golf Forecast Board

Status: forecast-only private paper research.

## Product

The board publishes the frozen golf model's pre-tournament probabilities. It
does not recommend wagers, select positions, size stakes, or claim an edge.

Every published board must come from a verified prospective archive with an
official final field, safe player identity resolution, and
`pre_start_verified=true`. A field player with no canonical history is admitted
via the documented tour-prior fallback (never a silent guess); ambiguous names,
id/name conflicts, and unknown canonical IDs still block publication.

## Timing

Tee times are preferred but optional. When exact tee times are unavailable, the
forecast uses the official PGA TOUR event date with a conservative 22-hour
night-before offset. The timing source is recorded in the archive and displayed
on the Discord board. The pre-start guard still prevents any post-tee forecast.

- Exact tee times: derived from official PGA TOUR tee-time evidence
- Schedule-date fallback: official event date with 22-hour night-before offset
- The fallback is conservative and not an exact first-tee timestamp
- Timing provenance is self-documented in every archive

## Displayed Outcomes

- winner probability
- top-5 probability
- top-10 probability
- top-20 probability
- make-cut probability for events with a cut

The board is sorted by top-20 probability. Winner probability is a monitored
outcome, not the sole definition of success.

## Prices

Sportsbook prices are optional descriptive references only. They are never read
by the performance model and are not currently included in the Discord board.
Future price output must remain source-labelled, timestamped, and separate from
forecast accuracy and any closing-line evaluation.

## Records

The immutable forecast archive is the record of model output. Delivery artifacts
are stored separately and contain the archive hash, exact payload, timestamp, and
delivery result. Reposts require an explicit operator action.

Forecast accuracy is graded separately from all future market or price research.
Retrospective replays and prospective forecasts are never pooled.

## Language

Discord output must not use recommendation or staking language, including
`lock`, `play`, `wager`, `bet`, or `edge`.
