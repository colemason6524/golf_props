# Real live-capture fixtures for the grade-recap blocking regression

These are byte-for-byte copies of the preserved CBS leaderboard captures in the
live event directory (read-only read, no HTTP, no credentials):

    /home/azureuser/golf_props/data/raw/prospective_results/butterfield_bermuda_championship_2026/

| fixture file | live sha256 | what it is |
|---|---|---|
| `31000146_butterfield-bermuda-championship.html` | `e216d82a38ec0d77e14b374d79688f7cafe019af552840582134671b79211bfe` | the Butterfield Bermuda Championship final leaderboard the grade was computed from. Same hash as `grading_manifest.json:input_sha256.results_page`. HUD window `Oct 22-25, 2026`, 120 `GolfLeaderboard-bodyTr` rows, winner Austin Smotherman. |
| `31000071_the-sentry.html` | `8a51893619f6bd33d20af9cfeee8f64db99d36b83d6b7269e9fbb43723fc5b72` | the 2026 The Sentry capture (Jan 8-11, 2026). Alphabetically first `*.html` in the live directory, so the pre-fix `sorted(glob("*.html"))[0]` selection picked it. It has a `GolfLeaderboard-hudDateRange` HUD but no `<table>` and no `GolfLeaderboard-bodyTr` rows (finality `player_leaderboard_table_not_found`). |

`metadata.json` in that live directory lists 43 completed CBS pages for the
season, so the whole season is preserved under one event directory. The tests
reproduce that layout (several unrelated event pages beside the graded page) and
require the recap to bind to the graded page by its manifest sha256, never by
sort order or a generic "latest file".

Both files are real public CBS leaderboard HTML. They contain no session
cookies, tokens or account data; the only embedded identifiers are public CBS
player/event ids and image URLs.
