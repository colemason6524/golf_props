from golf_props.cli import main
from golf_props.config import DATA_DIR, INTERIM_DIR, LOG_DIR, PROCESSED_DIR, RAW_DIR
from golf_props.schemas import CANONICAL_TABLES


def test_project_paths_exist():
    for path in [DATA_DIR, RAW_DIR, PROCESSED_DIR, INTERIM_DIR, LOG_DIR]:
        assert path.exists()


def test_canonical_schema_has_expected_tables():
    expected = {
        "events",
        "courses",
        "players",
        "event_courses",
        "player_event_results",
        "round_scores",
        "odds_snapshots",
    }
    assert expected.issubset(CANONICAL_TABLES)
    assert "event_id" in CANONICAL_TABLES["events"]
    assert "market_type" in CANONICAL_TABLES["odds_snapshots"]


def test_doctor_command_runs(capsys):
    exit_code = main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "project_root=" in captured.out
    assert "raw_dir=" in captured.out
