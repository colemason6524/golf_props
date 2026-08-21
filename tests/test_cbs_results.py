import json
from pathlib import Path

from golf_props.cli import main
from golf_props.ingestion.cbs_results import extract_schedule_events
from golf_props.normalization.cbs_results import normalize_directory, parse_leaderboard_rows
from golf_props.normalization.merge_results import merge_directories


SCHEDULE_HTML = """
<script type="application/ld+json">
{
  "@context": "http://www.schema.org",
  "@type": "SportsEvent",
  "description": "John Deere Classic at TPC Deere Run on
    Jul 1, 2026",
  "endDate": "
    Jul 4, 2026",
  "location": {
    "@type": "Place",
    "name": "TPC Deere Run",
    "address": {
      "@type": "PostalAddress",
      "addressLocality": "Silvis",
      "addressRegion": "IL",
      "addressCountry": "USA"
    }
  },
  "name": "John Deere Classic",
  "sport": "golf",
  "startDate": "
    Jul 1, 2026",
  "url": "/golf/leaderboard/pga-tour/31000099/john-deere-classic/"
}
</script>
"""


LEADERBOARD_HTML = """
<table><tbody>
<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr GolfLeaderboard-toggleScorecard--open">
  <td></td><td>1</td><td></td>
  <td class="GolfLeaderboardTable-bodyTd--playerName">
    <span class="CellPlayerName--short"><a>C. Gotterup</a></span>
    <span class="CellPlayerName--long"><a>Chris Gotterup</a></span>
  </td>
  <td>-20</td><td>$1,584,000</td><td>66</td><td>68*</td><td>68</td><td>62</td><td>264</td>
</tr>
<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr GolfLeaderboard-toggleScorecard--open">
  <td></td><td>CUT</td><td></td>
  <td class="GolfLeaderboardTable-bodyTd--playerName">
    <span class="CellPlayerName--short"><a>B. Campbell</a></span>
    <span class="CellPlayerName--long"><a>Brian Campbell</a></span>
  </td>
  <td>E</td><td>-</td><td>70</td><td>72</td><td>-</td><td>-</td><td>142</td>
</tr>
</tbody></table>
"""


def read_csv(path):
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_extract_schedule_events_filters_completed_before_as_of_date():
    from datetime import date

    events = extract_schedule_events(SCHEDULE_HTML, as_of_date=date(2026, 7, 16))

    assert len(events) == 1
    assert events[0]["event_name"] == "John Deere Classic"
    assert events[0]["date_end"] == "2026-07-04"
    assert events[0]["status"] == "completed"
    assert events[0]["course_name"] == "TPC Deere Run"


def test_parse_leaderboard_rows_extracts_scores():
    rows = parse_leaderboard_rows(LEADERBOARD_HTML)

    assert len(rows) == 2
    assert rows[0]["player_name"] == "Chris Gotterup"
    assert rows[0]["position"] == "1"
    assert rows[0]["total_to_par"] == -20
    assert rows[0]["round_scores"] == [66, 68, 68, 62]
    assert rows[1]["position"] == "CUT"
    assert rows[1]["total_to_par"] == 0
    assert rows[1]["round_scores"] == [70, 72, None, None]


def test_normalize_cbs_directory_writes_canonical_tables(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    raw_dir.mkdir()
    event_path = raw_dir / "31000099_john-deere-classic.html"
    event_path.write_text(LEADERBOARD_HTML, encoding="utf-8")
    (raw_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source": "cbs_sports",
                "captured_at_utc": "2026-07-16T00:00:00Z",
                "events": [
                    {
                        "event_name": "John Deere Classic",
                        "date_start": "2026-07-01",
                        "date_end": "2026-07-04",
                        "url": "https://www.cbssports.com/golf/leaderboard/pga-tour/31000099/john-deere-classic/",
                        "course_name": "TPC Deere Run",
                        "location": "Silvis, IL, USA",
                        "raw_path": str(event_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    tables = normalize_directory(raw_dir, output_dir)
    results = read_csv(output_dir / "player_event_results.csv")
    rounds = read_csv(output_dir / "round_scores.csv")

    assert len(tables["events"]) == 1
    assert len(results) == 2
    assert len(rounds) == 6
    assert results[0]["finish_position"] == "1"
    assert results[1]["made_cut"] == "False"


def test_merge_results_maps_added_player_to_base_id(tmp_path):
    base = tmp_path / "base"
    add = tmp_path / "add"
    out = tmp_path / "merged"
    for path in [base, add]:
        path.mkdir()
    for path, source, player_id in [(base, "espn", "player_base"), (add, "cbs", "player_add")]:
        (path / "events.csv").write_text("event_id,source,source_event_id,tour,season,event_name,date_start,date_end,timezone,format,is_major,is_alternate_field,created_at_utc\n", encoding="utf-8")
        (path / "courses.csv").write_text("course_id,source,source_course_id,course_name,location,country,par,yardage,grass_type,latitude,longitude,created_at_utc\n", encoding="utf-8")
        (path / "event_courses.csv").write_text("event_id,course_id,round_number,is_primary_course,notes\n", encoding="utf-8")
        (path / "round_scores.csv").write_text("round_score_id,event_id,course_id,player_id,round_number,score,to_par,position_after_round,made_cut_status,started_at_utc,completed_at_utc,recorded_at_utc\n", encoding="utf-8")
        (path / "players.csv").write_text(
            "player_id,source,source_player_id,player_name,country,handedness,date_of_birth,created_at_utc\n"
            f"{player_id},{source},Scottie Scheffler,Scottie Scheffler,,,,\n",
            encoding="utf-8",
        )
    (base / "player_event_results.csv").write_text("result_id,event_id,player_id,finish_position,finish_text,made_cut,withdrawn,disqualified,total_score,total_to_par,rounds_played,earnings,recorded_at_utc\n", encoding="utf-8")
    (add / "player_event_results.csv").write_text(
        "result_id,event_id,player_id,finish_position,finish_text,made_cut,withdrawn,disqualified,total_score,total_to_par,rounds_played,earnings,recorded_at_utc\n"
        "result_add,event_add,player_add,1,1,True,False,False,270,-10,4,100,\n",
        encoding="utf-8",
    )

    merge_directories(base, add, out)
    results = read_csv(out / "player_event_results.csv")
    players = read_csv(out / "players.csv")

    assert results[0]["player_id"] == "player_base"
    assert len(players) == 1


def test_cli_cbs_commands(tmp_path):
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "out"
    raw_dir.mkdir()
    event_path = raw_dir / "event.html"
    event_path.write_text(LEADERBOARD_HTML, encoding="utf-8")
    (raw_dir / "metadata.json").write_text(
        json.dumps(
            {
                "captured_at_utc": "2026-07-16T00:00:00Z",
                "events": [
                    {
                        "event_name": "John Deere Classic",
                        "date_start": "2026-07-01",
                        "date_end": "2026-07-04",
                        "url": "https://www.cbssports.com/golf/leaderboard/pga-tour/31000099/john-deere-classic/",
                        "course_name": "TPC Deere Run",
                        "raw_path": str(event_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["normalize-cbs-results", "--input-dir", str(raw_dir), "--output-dir", str(out_dir)]) == 0
    assert (out_dir / "events.csv").exists()
