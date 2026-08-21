import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.features.current_event import build_current_event_features
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.schemas import CURRENT_EVENT_FEATURES_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_inputs(tmp_path):
    processed_dir = tmp_path / "processed"
    field_path = tmp_path / "field.csv"
    normalize_file(FIXTURE, processed_dir)
    field_path.write_text(
        "\n".join(
            [
                "player_name,entry_status",
                "Scottie Scheffler (USA),confirmed",
                "Jordan Spieth,confirmed",
                "New Player,confirmed",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return processed_dir, field_path


def test_current_event_features_include_latest_completed_start(tmp_path):
    processed_dir, field_path = prepare_inputs(tmp_path)
    output = tmp_path / "current_features.csv"

    result = build_current_event_features(
        processed_dir,
        field_path,
        output,
        event_name="Current Invitational",
        event_date="2025-05-01",
        course_name="Augusta National Golf Club",
    )
    rows = read_csv(output)
    scottie = next(row for row in rows if row["player_name"].startswith("Scottie"))

    assert len(result["rows"]) == 3
    assert list(rows[0]) == CURRENT_EVENT_FEATURES_COLUMNS
    assert scottie["player_match_status"] == "matched_player_name"
    assert scottie["prior_starts"] == "2"
    assert scottie["history_through_date"] == "2025-04-13"
    assert scottie["course_starts"] == "1"
    assert scottie["major_starts"] == "1"
    assert float(scottie["recent_avg_finish"]) == 3.5
    assert scottie["target_make_cut"] == ""
    assert scottie["target_top20"] == ""


def test_current_event_features_exclude_events_not_completed_before_cutoff(tmp_path):
    processed_dir, field_path = prepare_inputs(tmp_path)
    output = tmp_path / "current_features.csv"

    build_current_event_features(
        processed_dir,
        field_path,
        output,
        event_name="Mid-Masters Snapshot",
        event_date="2025-04-12",
    )
    rows = read_csv(output)
    scottie = next(row for row in rows if row["player_name"].startswith("Scottie"))

    assert scottie["prior_starts"] == "1"
    assert scottie["history_through_date"] == "2025-03-16"
    assert scottie["major_starts"] == "0"


def test_current_event_features_warn_for_unmatched_field_players(tmp_path):
    processed_dir, field_path = prepare_inputs(tmp_path)
    output = tmp_path / "current_features.csv"
    report = tmp_path / "report.md"

    build_current_event_features(
        processed_dir,
        field_path,
        output,
        event_name="Current Invitational",
        event_date="2025-05-01",
        report_path=report,
    )
    rows = read_csv(output)
    new_player = next(row for row in rows if row["player_name"] == "New Player")
    report_text = report.read_text(encoding="utf-8")

    assert new_player["player_match_status"] == "unmatched_player_name"
    assert new_player["prior_starts"] == "0"
    assert "warning_rows: 1" in report_text
    assert "New Player: unmatched_player_name" in report_text


def test_cli_build_current_event_features(tmp_path):
    processed_dir, field_path = prepare_inputs(tmp_path)
    output = tmp_path / "current_features.csv"
    report = tmp_path / "current_features.report.md"

    exit_code = main(
        [
            "build-current-event-features",
            "--input-dir",
            str(processed_dir),
            "--field",
            str(field_path),
            "--output",
            str(output),
            "--report-output",
            str(report),
            "--event-name",
            "Current Invitational",
            "--event-date",
            "2025-05-01",
            "--course-name",
            "Augusta National Golf Club",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert report.exists()
