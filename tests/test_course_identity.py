import csv
from pathlib import Path

from golf_props.normalization.course_identity import (
    audit_course_aliases,
    is_generic_course_name,
    normalize_course_name,
    propose_course_aliases,
)
from golf_props.normalization.merge_results import merge_directories
from golf_props.schemas import (
    COURSES_COLUMNS,
    COURSE_ALIASES_COLUMNS,
    EVENTS_COLUMNS,
    EVENT_COURSES_COLUMNS,
    PLAYERS_COLUMNS,
    PLAYER_EVENT_RESULTS_COLUMNS,
    ROUND_SCORES_COLUMNS,
)


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def empty_row(columns, **values):
    row = {column: "" for column in columns}
    row.update(values)
    return row


def write_canonical_directory(path, source, course, player_id, event_id):
    write_csv(
        path / "events.csv",
        EVENTS_COLUMNS,
        [
            empty_row(
                EVENTS_COLUMNS,
                event_id=event_id,
                source=source,
                source_event_id=event_id,
                event_name="John Deere Classic",
                date_start="2026-07-01",
                date_end="2026-07-04",
            )
        ],
    )
    write_csv(path / "courses.csv", COURSES_COLUMNS, [course])
    write_csv(
        path / "players.csv",
        PLAYERS_COLUMNS,
        [
            empty_row(
                PLAYERS_COLUMNS,
                player_id=player_id,
                source=source,
                source_player_id="Scottie Scheffler",
                player_name="Scottie Scheffler",
            )
        ],
    )
    write_csv(
        path / "event_courses.csv",
        EVENT_COURSES_COLUMNS,
        [
            empty_row(
                EVENT_COURSES_COLUMNS,
                event_id=event_id,
                course_id=course["course_id"],
                is_primary_course="True",
            )
        ],
    )
    write_csv(
        path / "player_event_results.csv",
        PLAYER_EVENT_RESULTS_COLUMNS,
        [
            empty_row(
                PLAYER_EVENT_RESULTS_COLUMNS,
                result_id=f"result_{event_id}",
                event_id=event_id,
                player_id=player_id,
                finish_position="1",
                made_cut="True",
            )
        ],
    )
    write_csv(
        path / "round_scores.csv",
        ROUND_SCORES_COLUMNS,
        [
            empty_row(
                ROUND_SCORES_COLUMNS,
                round_score_id=f"round_{event_id}",
                event_id=event_id,
                course_id=course["course_id"],
                player_id=player_id,
                round_number="1",
                score="68",
            )
        ],
    )


def test_course_name_normalization_handles_suffixes_abbreviations_and_html():
    assert normalize_course_name("TPC Deere Run") == normalize_course_name(
        "TPC Deere Run - Silvis, IL"
    )
    assert normalize_course_name("St. George&#039;s GC") == (
        "st george s golf club"
    )
    assert normalize_course_name("Dunes Golf &amp; Beach Club") == (
        "dunes golf and beach club"
    )


def test_proposals_map_safe_equivalents_and_block_generic_names():
    canonical = [
        {
            "course_id": "course_deere",
            "course_name": "TPC Deere Run - Silvis, IL",
        },
        {
            "course_id": "course_oaks",
            "course_name": "TPC San Antonio (Oaks Course) - San Antonio, TX",
        },
    ]
    sources = [
        {
            "source": "cbs_sports",
            "source_course_id": "TPC Deere Run",
            "course_name": "TPC Deere Run",
        },
        {
            "source": "cbs_sports",
            "source_course_id": "Oaks Course",
            "course_name": "Oaks Course",
        },
    ]

    proposals = propose_course_aliases(canonical, sources)

    assert proposals[0]["canonical_course_id"] == "course_deere"
    assert proposals[0]["match_method"] == "exact_normalized_name"
    assert proposals[0]["review_status"] == "proposed"
    assert proposals[1]["canonical_course_id"] == ""
    assert proposals[1]["match_method"] == "generic_name_blocked"
    assert proposals[1]["review_status"] == "review_required"
    assert is_generic_course_name("North Course")
    assert is_generic_course_name("Champion Course")


def test_audit_command_writes_reviewable_crosswalk_and_report(tmp_path):
    base = tmp_path / "base"
    add = tmp_path / "add"
    write_csv(
        base / "courses.csv",
        COURSES_COLUMNS,
        [
            empty_row(
                COURSES_COLUMNS,
                course_id="course_deere",
                source="espn_kaggle",
                source_course_id="TPC Deere Run - Silvis, IL",
                course_name="TPC Deere Run - Silvis, IL",
            )
        ],
    )
    write_csv(
        add / "courses.csv",
        COURSES_COLUMNS,
        [
            empty_row(
                COURSES_COLUMNS,
                course_id="course_cbs",
                source="cbs_sports",
                source_course_id="TPC Deere Run",
                course_name="TPC Deere Run",
            )
        ],
    )
    output = tmp_path / "course_aliases.csv"
    report = tmp_path / "report.md"

    result = audit_course_aliases(base, add, output, report)

    assert result["rows"][0]["review_status"] == "proposed"
    assert read_csv(output)[0]["canonical_course_id"] == "course_deere"
    assert "does not\naccept mappings" in report.read_text(encoding="utf-8")


def test_merge_applies_reviewed_course_mapping_to_rounds_and_event_courses(tmp_path):
    base = tmp_path / "base"
    add = tmp_path / "add"
    output = tmp_path / "output"
    base_course = empty_row(
        COURSES_COLUMNS,
        course_id="course_deere",
        source="espn_kaggle",
        source_course_id="TPC Deere Run - Silvis, IL",
        course_name="TPC Deere Run - Silvis, IL",
    )
    add_course = empty_row(
        COURSES_COLUMNS,
        course_id="course_cbs",
        source="cbs_sports",
        source_course_id="TPC Deere Run",
        course_name="TPC Deere Run",
    )
    write_canonical_directory(
        base,
        "espn_kaggle",
        base_course,
        "player_base",
        "event_base",
    )
    write_canonical_directory(
        add,
        "cbs_sports",
        add_course,
        "player_add",
        "event_add",
    )
    aliases = tmp_path / "accepted_course_aliases.csv"
    write_csv(
        aliases,
        COURSE_ALIASES_COLUMNS,
        [
            {
                "source": "cbs_sports",
                "source_course_id": "TPC Deere Run",
                "source_course_name": "TPC Deere Run",
                "canonical_course_id": "course_deere",
                "canonical_course_name": "TPC Deere Run - Silvis, IL",
                "match_method": "exact_normalized_name",
                "confidence": "high",
                "review_status": "accepted",
                "notes": "Reviewed fixture mapping.",
            }
        ],
    )

    merge_directories(base, add, output, course_aliases_path=aliases)

    event_courses = read_csv(output / "event_courses.csv")
    rounds = read_csv(output / "round_scores.csv")
    results = read_csv(output / "player_event_results.csv")
    players = read_csv(output / "players.csv")
    assert {row["course_id"] for row in event_courses} == {"course_deere"}
    assert {row["course_id"] for row in rounds} == {"course_deere"}
    assert len(read_csv(output / "courses.csv")) == 1
    assert read_csv(output / "course_aliases.csv")[0]["review_status"] == "accepted"
    assert {row["player_id"] for row in results} == {"player_base"}
    assert len(players) == 1


def test_repository_crosswalk_is_well_formed_and_keeps_unresolved_rows():
    path = Path(__file__).resolve().parents[1] / "config" / "course_aliases.csv"

    rows = read_csv(path)

    assert len(rows) == 32
    assert all(set(row) == set(COURSE_ALIASES_COLUMNS) for row in rows)
    assert sum(row["review_status"] == "accepted" for row in rows) == 31
    unresolved = [
        row for row in rows if row["source_course_name"] == "Pete Dye Stadium Course PGA West"
    ]
    assert unresolved[0]["review_status"] == "review_required"
    assert unresolved[0]["canonical_course_id"] == ""
