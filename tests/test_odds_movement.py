import csv

from golf_props.cli import main
from golf_props.odds.movement import MOVEMENT_COLUMNS, build_odds_movement_report


HEADER = "odds_id,event_id,event_name,season,player_id,player_name,sportsbook,market_type,market_name,selection_name,line,price_american,price_decimal,implied_probability,captured_at_utc,source_url,market_status,is_closing_candidate"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_snapshot(path, captured_at, scheffler_price, scheffler_decimal, scheffler_prob, rory_price, rory_decimal, rory_prob):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                HEADER,
                f"odds_1,,The Open Championship,2026,,Scottie Scheffler,DraftKings,winner,winner,Scottie Scheffler,,{scheffler_price},{scheffler_decimal},{scheffler_prob},{captured_at},https://example.test,open,False",
                f"odds_2,,The Open Championship,2026,,Rory McIlroy,DraftKings,top20,top20,Rory McIlroy,,{rory_price},{rory_decimal},{rory_prob},{captured_at},https://example.test,open,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_odds_movement_report_compares_latest_two_snapshots(tmp_path):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "movement"
    previous = history_dir / "dk_golf_placement_20260717T120000Z.csv"
    current = history_dir / "dk_golf_placement_20260717T130000Z.csv"
    write_snapshot(previous, "2026-07-17T12:00:00Z", 600, 7.0, 0.142857, -120, 1.833333, 0.545455)
    write_snapshot(current, "2026-07-17T13:00:00Z", 500, 6.0, 0.166667, 110, 2.1, 0.47619)

    result = build_odds_movement_report(history_dir, output_dir, current_snapshot_path=current)
    rows = read_csv(output_dir / "odds_movement.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert result["previous_snapshot"] == previous
    assert result["current_snapshot"] == current
    assert list(rows[0].keys()) == MOVEMENT_COLUMNS
    assert {row["direction"] for row in rows} == {"steamed", "drifted"}
    scheffler = next(row for row in rows if row["player_name"] == "Scottie Scheffler")
    rory = next(row for row in rows if row["player_name"] == "Rory McIlroy")
    assert scheffler["direction"] == "steamed"
    assert rory["direction"] == "drifted"
    assert "# Odds Movement Report" in report
    assert "## Steam" in report
    assert "## Drift" in report


def test_cli_odds_movement(tmp_path):
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "movement"
    previous = history_dir / "dk_golf_placement_20260717T120000Z.csv"
    current = history_dir / "dk_golf_placement_20260717T130000Z.csv"
    write_snapshot(previous, "2026-07-17T12:00:00Z", 600, 7.0, 0.142857, -120, 1.833333, 0.545455)
    write_snapshot(current, "2026-07-17T13:00:00Z", 500, 6.0, 0.166667, 110, 2.1, 0.47619)

    exit_code = main(
        [
            "odds-movement",
            "--history-dir",
            str(history_dir),
            "--output-dir",
            str(output_dir),
            "--current-snapshot",
            str(current),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "odds_movement.csv").exists()
