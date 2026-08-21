import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.features.player_event import build_features, is_major, is_open_championship, safe_weighted_rate
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.schemas import FEATURES_PLAYER_EVENT_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_bootstrap(tmp_path):
    processed_dir = tmp_path / "processed"
    normalize_file(FIXTURE, processed_dir)
    return processed_dir


def test_build_features_writes_expected_columns_and_rows(tmp_path):
    processed_dir = prepare_bootstrap(tmp_path)
    output = tmp_path / "features" / "player_event_features.csv"

    rows = build_features(processed_dir, output)
    written = read_csv(output)

    assert output.exists()
    assert len(rows) == 6
    assert len(written) == 6
    assert list(written[0].keys()) == FEATURES_PLAYER_EVENT_COLUMNS


def test_weighted_rate_favors_recent_values():
    values = [
        (True, 3),
        (False, 3),
        (True, 2),
        (False, 1),
    ]

    assert safe_weighted_rate(values) == 0.555556


def test_major_and_open_event_classifiers():
    assert is_major("Masters Tournament")
    assert is_major("PGA Championship")
    assert is_major("U.S. Open")
    assert is_major("The Open Championship")
    assert is_open_championship("The Open Championship")
    assert not is_major("John Deere Classic")
    assert not is_open_championship("U.S. Open")


def test_features_exclude_current_event_from_prior_form(tmp_path):
    processed_dir = prepare_bootstrap(tmp_path)
    output = tmp_path / "features" / "player_event_features.csv"
    build_features(processed_dir, output)

    events = read_csv(processed_dir / "events.csv")
    players = read_csv(processed_dir / "players.csv")
    features = read_csv(output)

    players_event = next(row for row in events if row["event_name"] == "THE PLAYERS Championship")
    masters_event = next(row for row in events if row["event_name"] == "Masters Tournament")
    scheffler = next(row for row in players if row["player_name"] == "Scottie Scheffler")

    first_event_feature = next(
        row
        for row in features
        if row["event_id"] == players_event["event_id"] and row["player_id"] == scheffler["player_id"]
    )
    second_event_feature = next(
        row
        for row in features
        if row["event_id"] == masters_event["event_id"] and row["player_id"] == scheffler["player_id"]
    )

    assert first_event_feature["prior_starts"] == "0"
    assert first_event_feature["recent_made_cut_rate"] == ""
    assert first_event_feature["recent_avg_finish"] == ""

    assert second_event_feature["prior_starts"] == "1"
    assert second_event_feature["days_since_last_start"] == "28"
    assert float(second_event_feature["recent_made_cut_rate"]) == 1.0
    assert float(second_event_feature["recent_top20_rate"]) == 1.0
    assert float(second_event_feature["recent_top10_rate"]) == 1.0
    assert float(second_event_feature["recent_top5_rate"]) == 1.0
    assert float(second_event_feature["recent_win_rate"]) == 0.0
    assert float(second_event_feature["weighted_recent_made_cut_rate"]) == 1.0
    assert float(second_event_feature["weighted_recent_top20_rate"]) == 1.0
    assert float(second_event_feature["weighted_recent_top10_rate"]) == 1.0
    assert float(second_event_feature["weighted_recent_top5_rate"]) == 1.0
    assert float(second_event_feature["weighted_recent_win_rate"]) == 0.0
    assert float(second_event_feature["weighted_recent_avg_finish"]) == 5.0
    assert float(second_event_feature["weighted_recent_avg_score_to_par"]) == -10.0
    assert float(second_event_feature["recent_avg_finish"]) == 5.0
    assert float(second_event_feature["recent_avg_score_to_par"]) == -10.0
    assert second_event_feature["major_starts"] == "0"
    assert second_event_feature["open_starts"] == "0"


def test_course_history_uses_same_course_only(tmp_path):
    processed_dir = prepare_bootstrap(tmp_path)
    output = tmp_path / "features" / "player_event_features.csv"
    build_features(processed_dir, output)

    features = read_csv(output)
    assert {row["course_starts"] for row in features} == {"0"}
    assert all(row["course_made_cut_rate"] == "" for row in features)


def test_targets_are_attached_to_current_event(tmp_path):
    processed_dir = prepare_bootstrap(tmp_path)
    output = tmp_path / "features" / "player_event_features.csv"
    build_features(processed_dir, output)

    events = read_csv(processed_dir / "events.csv")
    players = read_csv(processed_dir / "players.csv")
    features = read_csv(output)
    masters_event = next(row for row in events if row["event_name"] == "Masters Tournament")
    spieth = next(row for row in players if row["player_name"] == "Jordan Spieth")
    spieth_masters = next(
        row
        for row in features
        if row["event_id"] == masters_event["event_id"] and row["player_id"] == spieth["player_id"]
    )

    assert spieth_masters["target_make_cut"] == "False"
    assert spieth_masters["target_top20"] == ""
    assert spieth_masters["target_top10"] == ""
    assert spieth_masters["target_top5"] == ""
    assert spieth_masters["target_win"] == ""


def test_cli_build_player_event_features(tmp_path):
    processed_dir = prepare_bootstrap(tmp_path)
    output = tmp_path / "features" / "player_event_features.csv"

    exit_code = main(
        [
            "build-player-event-features",
            "--input-dir",
            str(processed_dir),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.exists()
