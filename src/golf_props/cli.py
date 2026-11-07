"""Command line entry points for the golf props research scaffold."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from golf_props.analysis.performance_data import write_performance_data_audit
from golf_props.analysis.history_freshness import assess_history_freshness
from golf_props.pipelines.history_refresh import RefreshPlan, build_history_refresh, prepare_refresh_raw
from golf_props.backtest.event_rankings import build_event_rankings
from golf_props.backtest.current_event_rankings import build_current_event_rankings
from golf_props.backtest.simulation_backtest import run_simulation_backtest
from golf_props.backtest.simulation_selection import (
    comma_separated_floats,
    run_simulation_model_selection,
)
from golf_props.backtest.rolling_simulation_validation import (
    parse_fold,
    run_rolling_simulation_validation,
)
from golf_props.backtest.course_challenger_validation import (
    run_course_challenger_validation,
)
from golf_props.backtest.forecast_archive import (
    ForecastArchiveError,
    verify_forecast_archive,
)
from golf_props.backtest.forecast_grading import (
    ForecastGradingError,
    grade_forecast,
)
from golf_props.backtest.prospective_event_review import (
    ProspectiveReviewError,
    load_event_bundle,
    review_events,
    write_review,
)
from golf_props.models.cold_start_uncertainty import (
    CHALLENGER_ID,
    DEFAULT_PRIOR_ROUNDS,
    FORMULA as COLD_START_FORMULA,
    ColdStartChallengerError,
    build_challenger_bundle,
    simulate_challenger,
)
from golf_props.backtest.value_report import build_value_report
from golf_props.config import PROJECT_ROOT, project_paths
from golf_props.features.current_event import build_current_event_features
from golf_props.features.player_event import build_features
from golf_props.features.round_performance import build_round_performance
from golf_props.ingestion.cbs_results import collect_cbs_results
from golf_props.ingestion.current_field import (
    FINALITY_FINAL,
    SOURCE_KIND_CROSS_CHECK,
    SOURCE_KIND_OFFICIAL,
    import_field_evidence,
)
from golf_props.ingestion.tee_times import import_tee_time_evidence
from golf_props.notifications.discord import DiscordBoardError, publish_board
from golf_props.notifications.price_addendum import (
    PriceAddendumError,
    build_price_addendum,
    write_price_addendum,
)
from golf_props.normalization.cbs_results import normalize_directory as normalize_cbs_directory
from golf_props.normalization.cbs_results import analyze_leaderboard_finality
from golf_props.normalization.course_identity import audit_course_aliases
from golf_props.normalization.merge_results import merge_directories
from golf_props.normalization.manual_odds import normalize_file as normalize_manual_odds_file
from golf_props.normalization.espn_results import normalize_file as normalize_espn_file
from golf_props.models.time_split_baseline import run_time_split_baseline
from golf_props.models.round_strength import build_round_strength_snapshot
from golf_props.models.tournament_simulator import (
    CUT_RULE_TOP_N_AND_TIES,
    SUPPORTED_CUT_RULES,
    run_tournament_simulation,
)
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.odds.draftkings_predictions import (
    DEFAULT_URL as DK_PREDICTIONS_URL,
    DEFAULT_MAX_LINKED_PAGES as DK_MAX_LINKED_PAGES,
    DraftKingsParseError,
    collect_and_parse as collect_parse_dk_placement,
    collect_raw_snapshot as collect_dk_placement,
    parse_raw_snapshot as parse_dk_placement,
)
from golf_props.odds.covers_inspect import inspect_covers_odds, inspect_odds_url_batch
from golf_props.odds.bovada import (
    DEFAULT_PGA_URL as BOVADA_PGA_URL,
    BovadaOddsError,
    collect_bovada_golf_odds,
)
from golf_props.notifications.grade_recap import (
    ActivationStateError,
    GradeRecapError,
    activation_state_path,
    build_recap,
    deliver_recap,
    demo_label_for,
    initialize_activation_state,
    preview as preview_grade_recap,
    preview_delivery_state,
    readback_message,
    recap_release_blockers,
    resolve_graded_results_page,
    results_page_evidence,
)
from golf_props.odds.movement import build_odds_movement_report
from golf_props.odds.source_audit import audit_sources, parse_candidate
from golf_props.pipelines.dk_current_value import run_dk_current_value
from golf_props.pipelines.current_event_simulation import (
    FrozenCurrentEventError,
    run_frozen_current_event,
)
from golf_props.pipelines.weekly_forecast import (
    WeeklyPaths,
    weekly_forecast,
    weekly_forecast_status,
)


def _graded_results_page(
    event_key: str, grading_manifest: dict
) -> tuple[Optional[Path], dict]:
    """The preserved page this grade was computed from, bound by content hash.

    The event directory holds a whole season of CBS leaderboard captures (43 in
    the live Bermuda directory), so "first html file" is a different event.  The
    grading manifest records the sha256 of the exact page that produced the
    grade; only that page may feed the recap.
    """
    results_dir = PROJECT_ROOT / "data/raw/prospective_results" / event_key
    return resolve_graded_results_page(results_dir, grading_manifest)


def _recap_event_context(
    event_key: str, results_page: Optional[Path]
) -> tuple[dict[str, str], dict[str, object]]:
    """Dates from existing event_control evidence, finality from the page."""
    dates = {"start": "", "end": "", "source": "not recorded"}
    control = PROJECT_ROOT / "data/interim/weekly" / event_key / "event_control.json"
    if control.exists():
        try:
            data = json.loads(control.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        start = str(data.get("competitive_start_date") or data.get("schedule_start_date") or "")
        dates = {
            "start": start,
            "end": str(data.get("schedule_end_date") or ""),
            "source": "event_control",
        }
    finality: dict[str, object] = {
        "state": "unknown",
        "reason": "no_preserved_results_page",
    }
    if results_page is not None and results_page.exists():
        analysis = analyze_leaderboard_finality(results_page.read_text(encoding="utf-8"))
        finality = {"state": analysis["state"], "reason": analysis["reason"]}
    return dates, finality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="golf-props")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "doctor",
        help="Print configured project paths and whether they exist.",
    )

    performance_audit_parser = subparsers.add_parser(
        "audit-performance-data",
        help="Audit canonical results for performance-model readiness.",
    )
    performance_audit_parser.add_argument("--input-dir", required=True, type=Path)
    performance_audit_parser.add_argument("--output-dir", required=True, type=Path)

    freshness_parser = subparsers.add_parser(
        "history-freshness",
        help="Report whether active performance history is stale.",
    )
    freshness_parser.add_argument("--canonical-dir", required=True, type=Path)
    freshness_parser.add_argument("--schedule", required=True, type=Path)
    freshness_parser.add_argument("--as-of-date", required=True)
    freshness_parser.add_argument("--frozen-manifest", type=Path)

    refresh_parser = subparsers.add_parser(
        "refresh-history",
        help="Build a versioned candidate performance-history refresh.",
    )
    refresh_parser.add_argument("--inventory", required=True, type=Path)
    refresh_parser.add_argument("--base-canonical", required=True, type=Path)
    refresh_parser.add_argument("--base-round-performance", required=True, type=Path)
    refresh_parser.add_argument("--output-root", required=True, type=Path)
    refresh_parser.add_argument("--version", required=True)
    refresh_parser.add_argument("--source-cutoff", required=True)
    refresh_parser.add_argument("--as-of-date", required=True)
    refresh_parser.add_argument("--course-aliases", required=True, type=Path)
    refresh_parser.add_argument("--parent-manifest", type=Path)

    normalize_parser = subparsers.add_parser(
        "normalize-bootstrap-results",
        help="Normalize a simple PGA results CSV into canonical tables.",
    )
    normalize_parser.add_argument("--input", required=True, type=Path)
    normalize_parser.add_argument("--output-dir", required=True, type=Path)

    espn_parser = subparsers.add_parser(
        "normalize-espn-results",
        help="Normalize the Kaggle/ESPN PGA results TSV into canonical tables.",
    )
    espn_parser.add_argument("--input", required=True, type=Path)
    espn_parser.add_argument("--output-dir", required=True, type=Path)

    cbs_collect_parser = subparsers.add_parser(
        "collect-cbs-results",
        help="Collect CBS PGA leaderboards for completed events before an as-of date.",
    )
    cbs_collect_parser.add_argument("--output-dir", required=True, type=Path)
    cbs_collect_parser.add_argument("--schedule-url", default="https://www.cbssports.com/golf/schedules/2026/")
    cbs_collect_parser.add_argument("--as-of-date")
    cbs_collect_parser.add_argument("--timeout-seconds", type=int, default=90)
    cbs_collect_parser.add_argument("--limit", type=int)

    cbs_normalize_parser = subparsers.add_parser(
        "normalize-cbs-results",
        help="Normalize collected CBS PGA leaderboards into canonical tables.",
    )
    cbs_normalize_parser.add_argument("--input-dir", required=True, type=Path)
    cbs_normalize_parser.add_argument("--output-dir", required=True, type=Path)

    merge_parser = subparsers.add_parser(
        "merge-results",
        help="Merge canonical result directories and map added players by name.",
    )
    merge_parser.add_argument("--base", required=True, type=Path)
    merge_parser.add_argument("--add", required=True, type=Path)
    merge_parser.add_argument("--output-dir", required=True, type=Path)
    merge_parser.add_argument("--course-aliases", type=Path)

    course_alias_parser = subparsers.add_parser(
        "audit-course-crosswalk",
        help="Propose conservative cross-source course identity matches for review.",
    )
    course_alias_parser.add_argument("--base", required=True, type=Path)
    course_alias_parser.add_argument("--add", required=True, type=Path)
    course_alias_parser.add_argument("--output", required=True, type=Path)
    course_alias_parser.add_argument("--report-output", type=Path)

    manual_odds_parser = subparsers.add_parser(
        "normalize-manual-odds",
        help="Normalize a manual sportsbook odds CSV into odds snapshots.",
    )
    manual_odds_parser.add_argument("--input", required=True, type=Path)
    manual_odds_parser.add_argument("--output", required=True, type=Path)

    features_parser = subparsers.add_parser(
        "build-player-event-features",
        help="Build leakage-safe player-event features from canonical tables.",
    )
    features_parser.add_argument("--input-dir", required=True, type=Path)
    features_parser.add_argument("--output", required=True, type=Path)

    current_features_parser = subparsers.add_parser(
        "build-current-event-features",
        help="Build point-in-time features for an independent current field.",
    )
    current_features_parser.add_argument("--input-dir", required=True, type=Path)
    current_features_parser.add_argument("--field", required=True, type=Path)
    current_features_parser.add_argument("--output", required=True, type=Path)
    current_features_parser.add_argument("--report-output", type=Path)
    current_features_parser.add_argument("--event-name", required=True)
    current_features_parser.add_argument("--event-date", required=True)
    current_features_parser.add_argument("--course-name", default="")
    current_features_parser.add_argument("--season", type=int)

    round_performance_parser = subparsers.add_parser(
        "build-round-performance",
        help="Build event-round-relative performance from canonical round scores.",
    )
    round_performance_parser.add_argument("--input-dir", required=True, type=Path)
    round_performance_parser.add_argument("--output", required=True, type=Path)
    round_performance_parser.add_argument("--report-output", type=Path)
    round_performance_parser.add_argument("--min-group-size", type=int, default=2)
    round_performance_parser.add_argument("--min-score", type=int, default=58)
    round_performance_parser.add_argument("--max-score", type=int, default=110)

    round_strength_parser = subparsers.add_parser(
        "build-round-strength",
        help="Estimate point-in-time player strength for a current field.",
    )
    round_strength_parser.add_argument(
        "--round-performance",
        required=True,
        type=Path,
    )
    round_strength_parser.add_argument("--field", required=True, type=Path)
    round_strength_parser.add_argument("--output", required=True, type=Path)
    round_strength_parser.add_argument("--report-output", type=Path)
    round_strength_parser.add_argument("--as-of-date", required=True)
    round_strength_parser.add_argument("--half-life-days", type=float, default=180.0)
    round_strength_parser.add_argument("--prior-rounds", type=float, default=20.0)
    round_strength_parser.add_argument(
        "--variance-prior-rounds",
        type=float,
        default=20.0,
    )

    simulation_parser = subparsers.add_parser(
        "simulate-tournament",
        help="Simulate a performance-only stroke-play tournament.",
    )
    simulation_parser.add_argument("--strengths", required=True, type=Path)
    simulation_parser.add_argument("--output-dir", required=True, type=Path)
    simulation_parser.add_argument("--event-name", required=True)
    simulation_parser.add_argument("--event-date", required=True)
    simulation_parser.add_argument("--simulations", type=int, default=20000)
    simulation_parser.add_argument("--seed", type=int, default=20260729)
    simulation_parser.add_argument("--cut-size", type=int, default=65)
    simulation_parser.add_argument(
        "--cut-rule",
        choices=sorted(SUPPORTED_CUT_RULES),
        default=CUT_RULE_TOP_N_AND_TIES,
    )
    simulation_parser.add_argument("--top-n", type=int, default=25)

    frozen_current_parser = subparsers.add_parser(
        "predict-current-event",
        help="Run the hash-verified frozen incumbent for an independent field.",
    )
    frozen_current_parser.add_argument("--manifest", required=True, type=Path)
    frozen_current_parser.add_argument("--field", required=True, type=Path)
    frozen_current_parser.add_argument("--output-dir", required=True, type=Path)
    frozen_current_parser.add_argument("--event-name", required=True)
    frozen_current_parser.add_argument("--event-date", required=True)
    frozen_current_parser.add_argument("--as-of-date")
    frozen_current_parser.add_argument("--simulations", type=int, default=20000)
    frozen_current_parser.add_argument("--seed", type=int)
    frozen_current_parser.add_argument("--top-n", type=int, default=25)
    frozen_current_parser.add_argument("--allow-retrospective", action="store_true")
    frozen_current_parser.add_argument(
        "--cut-rule",
        choices=sorted(SUPPORTED_CUT_RULES),
        default=CUT_RULE_TOP_N_AND_TIES,
    )
    frozen_current_parser.add_argument("--event-start-at-utc")

    weekly_parser = subparsers.add_parser(
        "weekly-forecast",
        help="Discover the next event, collect evidence, and archive the frozen forecast.",
    )
    weekly_parser.add_argument("--dry-run", action="store_true")
    weekly_parser.add_argument(
        "--forecast-due-hours-before",
        type=int,
        default=12,
    )
    weekly_parser.add_argument("--simulations", type=int, default=20000)
    weekly_parser.add_argument("--top-n", type=int, default=25)
    weekly_parser.add_argument(
        "--schedule-url",
        default="https://www.cbssports.com/golf/schedules/2026/",
    )

    weekly_status_parser = subparsers.add_parser(
        "weekly-forecast-status",
        help="Print the latest weekly-forecast status file.",
    )

    verify_archive_parser = subparsers.add_parser(
        "verify-forecast-archive",
        help="Verify a prospective forecast archive hash manifest.",
    )
    verify_archive_parser.add_argument("--archive-dir", required=True, type=Path)

    grade_forecast_parser = subparsers.add_parser(
        "grade-forecast",
        help="Grade an immutable prospective forecast from preserved CBS results.",
    )
    grade_forecast_parser.add_argument("--archive-dir", required=True, type=Path)
    grade_forecast_parser.add_argument("--results-page", required=True, type=Path)
    grade_forecast_parser.add_argument("--rolling-metrics", required=True, type=Path)
    grade_forecast_parser.add_argument("--output-dir", required=True, type=Path)
    grade_forecast_parser.add_argument("--results-url", default="")

    publish_board_parser = subparsers.add_parser(
        "publish-forecast-board",
        help="Publish a verified prospective forecast board to Discord.",
    )
    publish_board_parser.add_argument("--archive-dir", required=True, type=Path)
    publish_board_parser.add_argument("--output-dir", type=Path)
    publish_board_parser.add_argument("--dry-run", action="store_true")
    publish_board_parser.add_argument("--resend", action="store_true")

    price_addendum_parser = subparsers.add_parser(
        "price-addendum",
        help="Preview (default) or explicitly send a separate price addendum.",
    )
    price_addendum_parser.add_argument("--archive-dir", required=True, type=Path)
    price_addendum_parser.add_argument("--delivery-root", required=True, type=Path)
    price_addendum_parser.add_argument("--odds-snapshot", type=Path)
    price_addendum_parser.add_argument("--odds-latest-csv", type=Path)
    price_addendum_parser.add_argument("--weekly-dir", type=Path)
    price_addendum_parser.add_argument("--send", action="store_true")
    price_addendum_parser.add_argument("--resend", action="store_true")

    grade_recap_parser = subparsers.add_parser(
        "publish-grade-recap",
        help=(
            "Preview (default) or explicitly send the final recap for one "
            "verified grade."
        ),
    )
    grade_recap_parser.add_argument("--event-key", required=True)
    grade_recap_parser.add_argument(
        "--grading-dir",
        type=Path,
        help="Defaults to data/interim/reports/forecast_grading/<event-key>.",
    )
    grade_recap_parser.add_argument(
        "--delivery-dir",
        type=Path,
        help="Defaults to data/interim/reports/forecast_delivery/<event-key>.",
    )
    grade_recap_parser.add_argument("--results-page", type=Path)
    grade_recap_parser.add_argument(
        "--send",
        action="store_true",
        help="Actually deliver. Without this flag the command is a dry-run preview.",
    )
    grade_recap_parser.add_argument(
        "--allow-prior-grades",
        action="store_true",
        help="Permit an explicit one-event backfill of a grade older than the recap activation.",
    )
    grade_recap_parser.add_argument(
        "--weekly-dir",
        type=Path,
        help="Weekly state folder holding grade_recap_activation.json.",
    )
    grade_recap_parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Label this as the authorised end-to-end verification demo. Only "
            "the event named in DEMO_AUTHORIZATION.json is accepted."
        ),
    )
    grade_recap_parser.add_argument(
        "--readback",
        action="store_true",
        help="Read the delivered message back and print a sanitized digest.",
    )

    review_prospective_parser = subparsers.add_parser(
        "review-prospective-golf",
        help=(
            "Event-level review of genuinely prospective frozen forecasts "
            "(read-only)."
        ),
    )
    review_prospective_parser.add_argument(
        "--prospective-root",
        type=Path,
        required=True,
        help="Directory holding prospective_forecasts/<event_key>/ archives.",
    )
    review_prospective_parser.add_argument(
        "--grading-root",
        type=Path,
        required=True,
        help="Directory holding forecast_grading/<event_key>/ grades.",
    )
    review_prospective_parser.add_argument("--output-dir", required=True, type=Path)
    review_prospective_parser.add_argument("--bootstrap-samples", type=int, default=10000)
    review_prospective_parser.add_argument("--seed", type=int, default=20261103)
    review_prospective_parser.add_argument(
        "--cold-start-challenger",
        action="store_true",
        help="Include the disabled cold_start_variance_v1 paired comparison.",
    )
    review_prospective_parser.add_argument(
        "--prior-rounds", type=float, default=DEFAULT_PRIOR_ROUNDS
    )

    cold_start_parser = subparsers.add_parser(
        "cold-start-challenger",
        help=(
            "Build one disabled cold-start uncertainty challenger bundle from a "
            "verified forecast archive; never activates or sends."
        ),
    )
    cold_start_parser.add_argument("--archive-dir", required=True, type=Path)
    cold_start_parser.add_argument("--output-dir", required=True, type=Path)
    cold_start_parser.add_argument(
        "--prior-rounds", type=float, default=DEFAULT_PRIOR_ROUNDS
    )
    cold_start_parser.add_argument("--simulations", type=int)
    cold_start_parser.add_argument("--seed", type=int)

    activation_parser = subparsers.add_parser(
        "init-grade-recap-activation",
        help=(
            "Create the durable recap activation record once. Never posts, "
            "forecasts or regrades."
        ),
    )
    activation_parser.add_argument("--weekly-dir", type=Path)
    activation_parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional note stored in the activation record (repeatable).",
    )

    import_field_parser = subparsers.add_parser(
        "import-current-field-evidence",
        help="Preserve reviewed official field evidence for an event.",
    )
    import_field_parser.add_argument("--event-key", required=True)
    import_field_parser.add_argument("--event-name", required=True)
    import_field_parser.add_argument("--payload", required=True, type=Path)
    import_field_parser.add_argument(
        "--source-kind",
        choices=[SOURCE_KIND_OFFICIAL, SOURCE_KIND_CROSS_CHECK],
        default=SOURCE_KIND_OFFICIAL,
    )
    import_field_parser.add_argument("--org", required=True)
    import_field_parser.add_argument("--url", required=True)
    import_field_parser.add_argument("--captured-at-utc", required=True)
    import_field_parser.add_argument(
        "--finality",
        choices=["final", "preliminary", "unknown"],
        default=FINALITY_FINAL,
    )
    import_field_parser.add_argument("--expected-field-size", type=int)

    import_tee_parser = subparsers.add_parser(
        "import-current-tee-time-evidence",
        help="Preserve reviewed tee-time evidence and derive the first tee UTC.",
    )
    import_tee_parser.add_argument("--event-key", required=True)
    import_tee_parser.add_argument("--event-name", required=True)
    import_tee_parser.add_argument("--payload", required=True, type=Path)
    import_tee_parser.add_argument("--org", required=True)
    import_tee_parser.add_argument("--url", required=True)
    import_tee_parser.add_argument("--captured-at-utc", required=True)
    import_tee_parser.add_argument("--local-timezone", required=True)
    import_tee_parser.add_argument("--reviewed-by", required=True)

    simulation_backtest_parser = subparsers.add_parser(
        "simulation-backtest",
        help="Walk forward through historical events with the tournament simulator.",
    )
    simulation_backtest_parser.add_argument(
        "--canonical-dir",
        required=True,
        type=Path,
    )
    simulation_backtest_parser.add_argument(
        "--round-performance",
        required=True,
        type=Path,
    )
    simulation_backtest_parser.add_argument("--output-dir", required=True, type=Path)
    simulation_backtest_parser.add_argument("--date-from")
    simulation_backtest_parser.add_argument("--date-to")
    simulation_backtest_parser.add_argument("--max-events", type=int, default=10)
    simulation_backtest_parser.add_argument("--simulations", type=int, default=2000)
    simulation_backtest_parser.add_argument("--seed", type=int, default=20260729)
    simulation_backtest_parser.add_argument("--cut-size", type=int, default=65)
    simulation_backtest_parser.add_argument(
        "--half-life-days",
        type=float,
        default=180.0,
    )
    simulation_backtest_parser.add_argument("--prior-rounds", type=float, default=20.0)
    simulation_backtest_parser.add_argument(
        "--variance-prior-rounds",
        type=float,
        default=20.0,
    )

    simulation_selection_parser = subparsers.add_parser(
        "simulation-model-selection",
        help="Tune the simulator on validation and score an untouched later test window.",
    )
    simulation_selection_parser.add_argument(
        "--canonical-dir",
        required=True,
        type=Path,
    )
    simulation_selection_parser.add_argument(
        "--round-performance",
        required=True,
        type=Path,
    )
    simulation_selection_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    simulation_selection_parser.add_argument("--validation-date-from", required=True)
    simulation_selection_parser.add_argument("--validation-date-to", required=True)
    simulation_selection_parser.add_argument("--test-date-from", required=True)
    simulation_selection_parser.add_argument("--test-date-to", required=True)
    simulation_selection_parser.add_argument(
        "--half-life-grid",
        type=comma_separated_floats,
        default=[90, 180, 365],
    )
    simulation_selection_parser.add_argument(
        "--prior-rounds-grid",
        type=comma_separated_floats,
        default=[8, 20, 40],
    )
    simulation_selection_parser.add_argument(
        "--variance-prior-rounds-grid",
        type=comma_separated_floats,
        default=[20],
    )
    simulation_selection_parser.add_argument(
        "--max-validation-events",
        type=int,
        default=0,
    )
    simulation_selection_parser.add_argument("--max-test-events", type=int, default=0)
    simulation_selection_parser.add_argument(
        "--validation-simulations",
        type=int,
        default=500,
    )
    simulation_selection_parser.add_argument(
        "--test-simulations",
        type=int,
        default=2000,
    )
    simulation_selection_parser.add_argument("--seed", type=int, default=20260729)
    simulation_selection_parser.add_argument("--cut-size", type=int, default=65)

    rolling_validation_parser = subparsers.add_parser(
        "rolling-simulation-validation",
        help="Run frozen rolling-origin simulator folds with uncertainty reports.",
    )
    rolling_validation_parser.add_argument(
        "--canonical-dir",
        required=True,
        type=Path,
    )
    rolling_validation_parser.add_argument(
        "--round-performance",
        required=True,
        type=Path,
    )
    rolling_validation_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    rolling_validation_parser.add_argument(
        "--fold",
        action="append",
        required=True,
        type=parse_fold,
    )
    rolling_validation_parser.add_argument(
        "--half-life-grid",
        type=comma_separated_floats,
        default=[90, 180, 365],
    )
    rolling_validation_parser.add_argument(
        "--prior-rounds-grid",
        type=comma_separated_floats,
        default=[8, 20, 40],
    )
    rolling_validation_parser.add_argument(
        "--variance-prior-rounds-grid",
        type=comma_separated_floats,
        default=[20],
    )
    rolling_validation_parser.add_argument("--freeze-date-from", required=True)
    rolling_validation_parser.add_argument("--freeze-date-to", required=True)
    rolling_validation_parser.add_argument(
        "--max-selection-events",
        type=int,
        default=0,
    )
    rolling_validation_parser.add_argument(
        "--max-evaluation-events",
        type=int,
        default=0,
    )
    rolling_validation_parser.add_argument(
        "--selection-simulations",
        type=int,
        default=500,
    )
    rolling_validation_parser.add_argument(
        "--evaluation-simulations",
        type=int,
        default=2000,
    )
    rolling_validation_parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=5000,
    )
    rolling_validation_parser.add_argument(
        "--calibration-bins",
        type=int,
        default=10,
    )
    rolling_validation_parser.add_argument("--seed", type=int, default=20260729)
    rolling_validation_parser.add_argument("--cut-size", type=int, default=65)

    course_challenger_parser = subparsers.add_parser(
        "course-challenger-validation",
        help="Compare a leakage-safe same-course challenger with the incumbent.",
    )
    course_challenger_parser.add_argument("--canonical-dir", required=True, type=Path)
    course_challenger_parser.add_argument(
        "--round-performance",
        required=True,
        type=Path,
    )
    course_challenger_parser.add_argument("--output-dir", required=True, type=Path)
    course_challenger_parser.add_argument(
        "--fold",
        action="append",
        required=True,
        type=parse_fold,
    )
    course_challenger_parser.add_argument(
        "--half-life-grid",
        type=comma_separated_floats,
        default=[90, 180, 365],
    )
    course_challenger_parser.add_argument(
        "--prior-rounds-grid",
        type=comma_separated_floats,
        default=[8, 20, 40],
    )
    course_challenger_parser.add_argument(
        "--variance-prior-rounds-grid",
        type=comma_separated_floats,
        default=[20],
    )
    course_challenger_parser.add_argument(
        "--course-weight-grid",
        type=comma_separated_floats,
        default=[0, 0.5, 1],
    )
    course_challenger_parser.add_argument(
        "--course-prior-rounds-grid",
        type=comma_separated_floats,
        default=[8, 20, 40],
    )
    course_challenger_parser.add_argument("--freeze-date-from", required=True)
    course_challenger_parser.add_argument("--freeze-date-to", required=True)
    course_challenger_parser.add_argument(
        "--max-selection-events",
        type=int,
        default=20,
    )
    course_challenger_parser.add_argument(
        "--max-evaluation-events",
        type=int,
        default=0,
    )
    course_challenger_parser.add_argument(
        "--selection-simulations",
        type=int,
        default=300,
    )
    course_challenger_parser.add_argument(
        "--evaluation-simulations",
        type=int,
        default=1000,
    )
    course_challenger_parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=5000,
    )
    course_challenger_parser.add_argument(
        "--calibration-bins",
        type=int,
        default=10,
    )
    course_challenger_parser.add_argument("--seed", type=int, default=20260729)
    course_challenger_parser.add_argument("--cut-size", type=int, default=65)
    course_challenger_parser.add_argument(
        "--max-absolute-adjustment",
        type=float,
        default=2.0,
    )

    baseline_parser = subparsers.add_parser(
        "time-split-baseline",
        help="Run time-split baseline reports from player-event features.",
    )
    baseline_parser.add_argument("--features", required=True, type=Path)
    baseline_parser.add_argument("--output-dir", required=True, type=Path)
    baseline_parser.add_argument("--min-train-rows", type=int, default=10)
    baseline_parser.add_argument("--min-prior-starts", type=int, default=3)
    baseline_parser.add_argument(
        "--model",
        choices=["base_rate", "player_rolling", "logistic"],
        default="base_rate",
    )
    baseline_parser.add_argument("--enable-logistic", action="store_true")

    rankings_parser = subparsers.add_parser(
        "event-rankings",
        help="Build event-level ranking cards from prediction rows.",
    )
    rankings_parser.add_argument("--predictions", required=True, type=Path)
    rankings_parser.add_argument("--output-dir", required=True, type=Path)
    rankings_parser.add_argument("--max-events", type=int, default=10)
    rankings_parser.add_argument("--top-n", type=int, default=20)

    current_rankings_parser = subparsers.add_parser(
        "current-event-rankings",
        help="Build current-event ranking cards from an odds snapshot field.",
    )
    current_rankings_parser.add_argument("--features", required=True, type=Path)
    current_rankings_parser.add_argument("--odds", required=True, type=Path)
    current_rankings_parser.add_argument("--output-dir", required=True, type=Path)
    current_rankings_parser.add_argument("--event-date")
    current_rankings_parser.add_argument("--course-name", default="")
    current_rankings_parser.add_argument("--min-prior-starts", type=int, default=3)
    current_rankings_parser.add_argument("--top-n", type=int, default=25)

    value_parser = subparsers.add_parser(
        "value-report",
        help="Join event rankings to odds snapshots and compute edge.",
    )
    value_parser.add_argument("--rankings", required=True, type=Path)
    value_parser.add_argument("--odds", required=True, type=Path)
    value_parser.add_argument("--output-dir", required=True, type=Path)
    value_parser.add_argument("--top-n", type=int, default=50)

    movement_parser = subparsers.add_parser(
        "odds-movement",
        help="Compare the latest two odds snapshots and report market movement.",
    )
    movement_parser.add_argument("--history-dir", required=True, type=Path)
    movement_parser.add_argument("--output-dir", required=True, type=Path)
    movement_parser.add_argument("--current-snapshot", type=Path)
    movement_parser.add_argument("--top-n", type=int, default=50)

    audit_parser = subparsers.add_parser(
        "audit-odds-sources",
        help="Audit candidate golf odds pages for no-browser scrape viability.",
    )
    audit_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/interim/reports/odds_source_audit"),
    )
    audit_parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate as 'Name|URL'. Can be passed multiple times.",
    )
    audit_parser.add_argument(
        "--player",
        action="append",
        default=[],
        help="Seed player name to search for. Can be passed multiple times.",
    )
    audit_parser.add_argument("--timeout-seconds", type=int, default=45)

    bovada_parser = subparsers.add_parser(
        "collect-bovada-golf-odds",
        help="Collect Bovada no-browser golf odds into canonical odds snapshots.",
    )
    bovada_parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/odds_snapshots/bovada_golf_latest.csv"),
    )
    bovada_parser.add_argument(
        "--raw-output",
        type=Path,
        default=Path("data/raw/odds_snapshots/bovada_golf_latest.json"),
    )
    bovada_parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("data/interim/reports/bovada_golf_odds_collection/report.md"),
    )
    bovada_parser.add_argument("--url", default=BOVADA_PGA_URL)
    bovada_parser.add_argument("--timeout-seconds", type=int, default=45)
    bovada_parser.add_argument("--include-unmapped", action="store_true")
    bovada_parser.add_argument(
        "--archive-dir",
        type=Path,
        default=PROJECT_ROOT / "data/raw/odds_snapshots/archive",
        help="Immutable timestamped snapshot directory (additive to the latest files).",
    )
    bovada_parser.add_argument(
        "--weekly-dir",
        type=Path,
        default=PROJECT_ROOT / "data/interim/weekly",
        help="Existing event_control records used only to resolve pre_start.",
    )

    covers_inspect_parser = subparsers.add_parser(
        "inspect-covers-odds",
        help="Inspect Covers PGA odds page structure before building a parser.",
    )
    covers_inspect_parser.add_argument(
        "--url",
        default="https://www.covers.com/sport/golf/pga/odds",
    )
    covers_inspect_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/interim/reports/covers_source_inspection"),
    )
    covers_inspect_parser.add_argument(
        "--player",
        action="append",
        default=[],
        help="Seed player name to inspect. Can be passed multiple times.",
    )
    covers_inspect_parser.add_argument("--timeout-seconds", type=int, default=45)
    covers_inspect_parser.add_argument("--context-items", type=int, default=8)

    odds_url_batch_parser = subparsers.add_parser(
        "inspect-odds-url-batch",
        help="Inspect multiple odds URLs and rank parser candidates.",
    )
    odds_url_batch_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/interim/reports/odds_url_inspection_batch"),
    )
    odds_url_batch_parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate as 'Name|URL'. Can be passed multiple times.",
    )
    odds_url_batch_parser.add_argument(
        "--player",
        action="append",
        default=[],
        help="Seed player name to inspect. Can be passed multiple times.",
    )
    odds_url_batch_parser.add_argument("--timeout-seconds", type=int, default=45)
    odds_url_batch_parser.add_argument("--context-items", type=int, default=8)

    dk_collect_parser = subparsers.add_parser(
        "collect-dk-placement",
        help="Collect a raw DraftKings Predictions golf placement snapshot.",
    )
    dk_collect_parser.add_argument("--output-dir", required=True, type=Path)
    dk_collect_parser.add_argument("--url", default=DK_PREDICTIONS_URL)
    dk_collect_parser.add_argument("--timeout-seconds", type=int, default=90)
    dk_collect_parser.add_argument("--retries", type=int, default=3)
    dk_collect_parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)

    dk_parse_parser = subparsers.add_parser(
        "parse-dk-placement",
        help="Parse a raw DraftKings Predictions golf placement snapshot.",
    )
    dk_parse_parser.add_argument("--raw", required=True, type=Path)
    dk_parse_parser.add_argument("--output", required=True, type=Path)
    dk_parse_parser.add_argument("--metadata", type=Path)
    dk_parse_parser.add_argument("--url", default=DK_PREDICTIONS_URL)
    dk_parse_parser.add_argument("--season")

    dk_collect_parse_parser = subparsers.add_parser(
        "collect-parse-dk-placement",
        help="Collect and parse DraftKings Predictions golf placement odds.",
    )
    dk_collect_parse_parser.add_argument("--raw-output-dir", required=True, type=Path)
    dk_collect_parse_parser.add_argument("--processed-output", required=True, type=Path)
    dk_collect_parse_parser.add_argument("--url", default=DK_PREDICTIONS_URL)
    dk_collect_parse_parser.add_argument("--season")
    dk_collect_parse_parser.add_argument("--timeout-seconds", type=int, default=90)
    dk_collect_parse_parser.add_argument("--retries", type=int, default=3)
    dk_collect_parse_parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    dk_collect_parse_parser.add_argument("--crawl-linked", action="store_true")
    dk_collect_parse_parser.add_argument("--max-linked-pages", type=int, default=DK_MAX_LINKED_PAGES)

    dk_current_value_parser = subparsers.add_parser(
        "run-dk-current-value",
        help="Collect DK golf odds, build current rankings, and write a value report.",
    )
    dk_current_value_parser.add_argument(
        "--features",
        type=Path,
        default=Path("data/interim/features/pga_2001_2026_player_event_features.csv"),
    )
    dk_current_value_parser.add_argument(
        "--raw-output-dir",
        type=Path,
        default=Path("data/raw/odds_snapshots/draftkings_predictions_golf_placement"),
    )
    dk_current_value_parser.add_argument(
        "--odds-output",
        type=Path,
        default=Path("data/processed/odds_snapshots/draftkings_golf_placement_latest.csv"),
    )
    dk_current_value_parser.add_argument(
        "--odds-history-dir",
        type=Path,
        default=Path("data/processed/odds_snapshots/history"),
    )
    dk_current_value_parser.add_argument(
        "--rankings-output-dir",
        type=Path,
        default=Path("data/interim/reports/dk_golf_placement_current_event_rankings"),
    )
    dk_current_value_parser.add_argument(
        "--value-output-dir",
        type=Path,
        default=Path("data/interim/reports/dk_golf_placement_current_value_report"),
    )
    dk_current_value_parser.add_argument(
        "--movement-output-dir",
        type=Path,
        default=Path("data/interim/reports/dk_golf_placement_odds_movement"),
    )
    dk_current_value_parser.add_argument("--run-metadata-output", type=Path)
    dk_current_value_parser.add_argument("--url", default=DK_PREDICTIONS_URL)
    dk_current_value_parser.add_argument("--season")
    dk_current_value_parser.add_argument("--event-date")
    dk_current_value_parser.add_argument("--course-name", default="")
    dk_current_value_parser.add_argument("--min-prior-starts", type=int, default=3)
    dk_current_value_parser.add_argument("--top-n", type=int, default=50)
    dk_current_value_parser.add_argument("--timeout-seconds", type=int, default=90)
    dk_current_value_parser.add_argument("--retries", type=int, default=3)
    dk_current_value_parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    dk_current_value_parser.add_argument("--max-linked-pages", type=int, default=DK_MAX_LINKED_PAGES)
    dk_current_value_parser.add_argument("--skip-collect", action="store_true")
    dk_current_value_parser.add_argument("--no-save-odds-history", action="store_true")
    dk_current_value_parser.add_argument("--no-build-movement", action="store_true")

    return parser


def run_doctor() -> int:
    print(f"project_root={PROJECT_ROOT}")
    for name, path in project_paths().items():
        status = "ok" if path.exists() else "missing"
        print(f"{name}={path} [{status}]")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor()
    if args.command == "audit-performance-data":
        result = write_performance_data_audit(args.input_dir, args.output_dir)
        print(f"performance_data_summary={result['summary_path']}")
        print(f"performance_data_report={result['report_path']}")
        return 0
    if args.command == "history-freshness":
        result = assess_history_freshness(
            canonical_dir=args.canonical_dir,
            schedule_path=args.schedule,
            as_of_date=args.as_of_date,
            frozen_manifest=args.frozen_manifest,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "refresh-history":
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        metadata = prepare_refresh_raw(inventory, args.output_root / "inputs")
        plan = RefreshPlan(
            base_canonical=args.base_canonical,
            base_round_performance=args.base_round_performance,
            add_raw_dir=args.output_root / "inputs",
            output_root=args.output_root,
            version=args.version,
            source_cutoff=args.source_cutoff,
            as_of_date=args.as_of_date,
            course_aliases=args.course_aliases,
            parent_manifest=args.parent_manifest,
            excluded_events=[
                {
                    "event_name": event["event_name"],
                    "reason": "; ".join(event.get("exclusion_reasons") or []),
                }
                for event in metadata["excluded_events"]
            ],
        )
        manifest = build_history_refresh(plan)
        print(f"refresh_manifest={args.output_root / 'refresh_manifest.json'}")
        print(f"refresh_version={manifest['version']}")
        print(f"refresh_status={manifest['status']}")
        print(f"refresh_events={manifest['validation']['events']}")
        print(f"refresh_latest_event_end={manifest['validation']['latest_event_end']}")
        return 0
    if args.command == "normalize-bootstrap-results":
        normalize_file(args.input, args.output_dir)
        return 0
    if args.command == "normalize-espn-results":
        normalize_espn_file(args.input, args.output_dir)
        return 0
    if args.command == "collect-cbs-results":
        from datetime import date

        collect_cbs_results(
            args.output_dir,
            schedule_url=args.schedule_url,
            as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
            timeout_seconds=args.timeout_seconds,
            limit=args.limit,
        )
        return 0
    if args.command == "normalize-cbs-results":
        normalize_cbs_directory(args.input_dir, args.output_dir)
        return 0
    if args.command == "merge-results":
        merge_directories(
            args.base,
            args.add,
            args.output_dir,
            course_aliases_path=args.course_aliases,
        )
        return 0
    if args.command == "audit-course-crosswalk":
        result = audit_course_aliases(
            args.base,
            args.add,
            args.output,
            report_path=args.report_output,
        )
        print(f"course_crosswalk_output={result['output_path']}")
        print(f"course_crosswalk_report={result['report_path']}")
        print(f"course_crosswalk_rows={len(result['rows'])}")
        return 0
    if args.command == "normalize-manual-odds":
        normalize_manual_odds_file(args.input, args.output)
        return 0
    if args.command == "build-player-event-features":
        build_features(args.input_dir, args.output)
        return 0
    if args.command == "build-current-event-features":
        result = build_current_event_features(
            args.input_dir,
            args.field,
            args.output,
            event_name=args.event_name,
            event_date=args.event_date,
            course_name=args.course_name,
            season=args.season,
            report_path=args.report_output,
        )
        print(f"current_event_features={result['output_path']}")
        print(f"current_event_feature_report={result['report_path']}")
        print(f"current_event_feature_rows={len(result['rows'])}")
        return 0
    if args.command == "build-round-performance":
        result = build_round_performance(
            args.input_dir,
            args.output,
            report_path=args.report_output,
            min_group_size=args.min_group_size,
            min_score=args.min_score,
            max_score=args.max_score,
        )
        print(f"round_performance_output={result['output_path']}")
        print(f"round_performance_rows={len(result['rows'])}")
        print(f"round_performance_report={result['report_path']}")
        return 0
    if args.command == "build-round-strength":
        result = build_round_strength_snapshot(
            args.round_performance,
            args.field,
            args.output,
            args.as_of_date,
            report_path=args.report_output,
            half_life_days=args.half_life_days,
            prior_rounds=args.prior_rounds,
            variance_prior_rounds=args.variance_prior_rounds,
        )
        print(f"round_strength_output={result['output_path']}")
        print(f"round_strength_rows={len(result['rows'])}")
        print(f"round_strength_report={result['report_path']}")
        return 0
    if args.command == "simulate-tournament":
        result = run_tournament_simulation(
            args.strengths,
            args.output_dir,
            args.event_name,
            args.event_date,
            simulations=args.simulations,
            seed=args.seed,
            cut_size=args.cut_size,
            cut_rule=args.cut_rule,
            top_n=args.top_n,
        )
        print(f"simulation_predictions={result['predictions_path']}")
        print(f"simulation_report={result['report_path']}")
        print(f"simulation_rows={len(result['rows'])}")
        return 0
    if args.command == "predict-current-event":
        try:
            result = run_frozen_current_event(
                args.manifest,
                args.field,
                args.output_dir,
                args.event_name,
                args.event_date,
                as_of_date=args.as_of_date,
                simulations=args.simulations,
                seed=args.seed,
                top_n=args.top_n,
                allow_retrospective=args.allow_retrospective,
                cut_rule=args.cut_rule,
                event_start_at_utc=args.event_start_at_utc,
            )
        except FrozenCurrentEventError as exc:
            print(f"Frozen current-event forecast failed: {exc}", file=sys.stderr)
            return 1
        print(f"frozen_current_strengths={result['strengths_path']}")
        print(f"frozen_current_predictions={result['predictions_path']}")
        print(f"frozen_current_report={result['report_path']}")
        print(f"frozen_current_manifest={result['run_manifest_path']}")
        return 0
    if args.command == "weekly-forecast":
        exit_code, status = weekly_forecast(
            WeeklyPaths(),
            dry_run=args.dry_run,
            forecast_due_hours_before=args.forecast_due_hours_before,
            schedule_url=args.schedule_url,
            simulations=args.simulations,
            top_n=args.top_n,
        )
        print(f"weekly_forecast_exit={exit_code}")
        print(f"weekly_forecast_state={status.get('state')}")
        print(f"weekly_forecast_event={status.get('event_name')}")
        print(f"weekly_forecast_reason={status.get('blocking_reason')}")
        return exit_code
    if args.command == "weekly-forecast-status":
        status = weekly_forecast_status(WeeklyPaths())
        import json as _json

        print(_json.dumps(status, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-forecast-archive":
        try:
            result = verify_forecast_archive(args.archive_dir)
        except ForecastArchiveError as exc:
            print(f"Forecast archive verification failed: {exc}", file=sys.stderr)
            return 1
        print(f"archive_verified={result['verified']}")
        print(f"archive_dir={result['archive_dir']}")
        for problem in result["problems"]:
            print(f"archive_problem={problem}")
        return 0 if result["verified"] else 1
    if args.command == "grade-forecast":
        try:
            result = grade_forecast(
                args.archive_dir,
                args.results_page,
                args.rolling_metrics,
                args.output_dir,
                results_url=args.results_url,
            )
        except (ForecastGradingError, ForecastArchiveError) as exc:
            print(f"Forecast grading failed: {exc}", file=sys.stderr)
            return 1
        print(f"graded_predictions={result['graded_predictions_path']}")
        print(f"grading_metrics={result['metrics_path']}")
        print(f"grading_report={result['report_path']}")
        print(f"grading_manifest={result['manifest_path']}")
        return 0
    if args.command == "publish-forecast-board":
        output_dir = args.output_dir or (
            PROJECT_ROOT / "data/interim/reports/forecast_delivery" / args.archive_dir.name
        )
        try:
            result = publish_board(
                args.archive_dir,
                output_dir,
                dry_run=args.dry_run,
                resend=args.resend,
            )
        except DiscordBoardError as exc:
            print(f"Forecast board publication failed: {exc}", file=sys.stderr)
            return 1
        print(f"forecast_board={result['board']}")
        print(f"discord_payload={result['payload']}")
        print(f"delivery_receipt={result['receipt']}")
        return 0 if result["receipt_data"]["status"] != "failed" else 1
    if args.command == "price-addendum":
        try:
            addendum = build_price_addendum(
                args.archive_dir,
                odds_snapshot=args.odds_snapshot,
                odds_latest_csv=args.odds_latest_csv,
                weekly_dir=args.weekly_dir,
            )
            result = write_price_addendum(
                addendum,
                args.delivery_root,
                send=args.send,
                resend=args.resend,
            )
        except PriceAddendumError as exc:
            print(f"price addendum failed: {exc}", file=sys.stderr)
            return 1
        print(f"price_addendum_id={result['addendum_id']}")
        print(f"price_addendum_status={result['status']}")
        print(f"price_addendum_output={result['output_dir']}")
        return 0 if result["status"] not in {"failed", "unknown_delivery"} else 1
    if args.command == "init-grade-recap-activation":
        try:
            result = initialize_activation_state(
                activation_state_path(args.weekly_dir), notes=args.note
            )
        except ActivationStateError as exc:
            print(f"grade recap activation refused: {exc}", file=sys.stderr)
            return 1
        print(f"grade_recap_activation={result['activation_utc']}")
        print(f"grade_recap_activation_result={result['result']}")
        print(f"grade_recap_activation_path={result['path']}")
        print("grade_recap_activation_side_effects=none (no forecast, no grading, no send)")
        return 0
    if args.command == "publish-grade-recap":
        event_key = args.event_key
        grading_dir = args.grading_dir or (
            PROJECT_ROOT / "data/interim/reports/forecast_grading" / event_key
        )
        delivery_dir = args.delivery_dir or (
            PROJECT_ROOT / "data/interim/reports/forecast_delivery" / event_key
        )
        try:
            manifest = json.loads(
                (grading_dir / "grading_manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            print(
                f"grade recap: no readable verified grading manifest in {grading_dir}",
                file=sys.stderr,
            )
            return 1
        event_name = str(manifest.get("event_name") or "")
        if args.results_page is not None:
            # An explicit page is accepted only if its bytes are the graded ones.
            results_page = args.results_page
            results_evidence = results_page_evidence(results_page, manifest)
        else:
            results_page, results_evidence = _graded_results_page(event_key, manifest)
        event_dates, finality = _recap_event_context(event_key, results_page)
        try:
            demo_label = demo_label_for(event_key) if args.demo else None
            recap = build_recap(
                event_key=event_key,
                event_name=event_name,
                grading_dir=grading_dir,
                results_page=results_page,
                event_dates=event_dates,
                finality=finality,
                demo_label=demo_label,
                results_evidence=results_evidence,
            )
        except GradeRecapError as exc:
            print(f"grade recap preview failed: {exc}", file=sys.stderr)
            return 1
        paths = preview_grade_recap(recap, delivery_dir)
        print(f"grade_recap_preview_json={paths['json']}")
        print(f"grade_recap_preview_markdown={paths['markdown']}")
        print(f"grade_recap_fingerprint={recap['fingerprint']}")
        print(f"grade_recap_graded_players={recap['coverage']['graded_players']}")
        print(f"grade_recap_priced_roi={recap['price_availability']['roi']}")
        print(
            "grade_recap_event_window="
            f"{recap['event_dates'].get('start')}..{recap['event_dates'].get('end')}"
            f" (source={recap['event_dates'].get('source')})"
        )
        print(
            "grade_recap_event_finality="
            f"{recap['event_finality'].get('state')} "
            f"({recap['event_finality'].get('reason')})"
        )
        print(f"grade_recap_winner={recap['winner'] or 'not recorded'}")
        print(
            f"grade_recap_results_page={results_evidence.get('path') or 'none'}"
        )
        print(
            "grade_recap_results_page_sha256="
            f"{results_evidence.get('sha256') or ''}"
        )
        print(
            "grade_recap_results_page_verified="
            f"{str(bool(results_evidence.get('verified'))).lower()} "
            f"({results_evidence.get('reason') or ''})"
        )
        blockers = recap_release_blockers(recap, require_results_evidence=True)
        print(
            "grade_recap_release_blockers="
            + ("; ".join(blockers) if blockers else "none")
        )
        state = preview_delivery_state(
            recap, delivery_dir, require_results_evidence=True
        )
        print(f"grade_recap_delivery_state={state['state']}")
        if not state["send"]:
            print(f"grade_recap_would_send=false ({state['reason']})")
        if not args.send:
            print(
                "grade_recap_sent=false (dry run; pass --send --allow-prior-grades "
                "for an explicit one-event backfill)"
            )
            return 0
        if args.demo and not args.allow_prior_grades:
            print(
                "grade recap demo refused: the archived demo grade needs "
                "--allow-prior-grades",
                file=sys.stderr,
            )
            return 1
        try:
            result = deliver_recap(
                recap,
                delivery_dir,
                allow_prior_grades=args.allow_prior_grades,
                weekly_dir=args.weekly_dir,
                require_results_evidence=True,
            )
        except GradeRecapError as exc:
            print(f"grade recap delivery failed: {exc}", file=sys.stderr)
            return 1
        print(f"grade_recap_status={result['status']}")
        message_id = (result.get("receipt") or {}).get("message_id")
        if message_id:
            print(f"grade_recap_message_id={message_id}")
        if args.readback:
            if not message_id:
                print("grade_recap_readback=no_message_id")
            else:
                print(
                    "grade_recap_readback="
                    + json.dumps(readback_message(str(message_id)), sort_keys=True)
                )
        return 0 if result["status"] in {"sent", "already_sent"} else 1
    if args.command == "import-current-field-evidence":
        evidence = import_field_evidence(
            args.event_key,
            args.payload,
            source_kind=args.source_kind,
            org=args.org,
            url=args.url,
            captured_at_utc=args.captured_at_utc,
            finality=args.finality,
            event_name=args.event_name,
            expected_field_size=args.expected_field_size,
        )
        print(f"field_evidence_payload={evidence.payload_path}")
        print(f"field_evidence_rows={len(evidence.rows)}")
        print(f"field_evidence_ready={evidence.ready()}")
        return 0
    if args.command == "import-current-tee-time-evidence":
        evidence = import_tee_time_evidence(
            args.event_key,
            args.event_name,
            args.payload,
            org=args.org,
            url=args.url,
            captured_at_utc=args.captured_at_utc,
            local_timezone=args.local_timezone,
            reviewed_by=args.reviewed_by,
        )
        print(f"tee_evidence_payload={evidence.payload_path}")
        print(f"tee_evidence_rows={len(evidence.rows)}")
        print(f"tee_earliest_at_utc={evidence.earliest_tee_at_utc}")
        return 0
    if args.command == "simulation-backtest":
        result = run_simulation_backtest(
            args.canonical_dir,
            args.round_performance,
            args.output_dir,
            date_from=args.date_from,
            date_to=args.date_to,
            max_events=args.max_events,
            simulations=args.simulations,
            seed=args.seed,
            cut_size=args.cut_size,
            half_life_days=args.half_life_days,
            prior_rounds=args.prior_rounds,
            variance_prior_rounds=args.variance_prior_rounds,
        )
        print(f"simulation_backtest_events={len(result['event_summaries'])}")
        print(f"simulation_backtest_predictions={result['predictions_path']}")
        print(f"simulation_backtest_metrics={result['metrics_path']}")
        print(f"simulation_backtest_report={result['report_path']}")
        return 0
    if args.command == "simulation-model-selection":
        result = run_simulation_model_selection(
            args.canonical_dir,
            args.round_performance,
            args.output_dir,
            args.validation_date_from,
            args.validation_date_to,
            args.test_date_from,
            args.test_date_to,
            args.half_life_grid,
            args.prior_rounds_grid,
            args.variance_prior_rounds_grid,
            max_validation_events=args.max_validation_events,
            max_test_events=args.max_test_events,
            validation_simulations=args.validation_simulations,
            test_simulations=args.test_simulations,
            seed=args.seed,
            cut_size=args.cut_size,
        )
        print(f"simulation_selection={result['selection_path']}")
        print(f"simulation_selection_parameters={result['metadata_path']}")
        print(f"simulation_selection_report={result['report_path']}")
        return 0
    if args.command == "rolling-simulation-validation":
        result = run_rolling_simulation_validation(
            args.canonical_dir,
            args.round_performance,
            args.output_dir,
            args.fold,
            args.half_life_grid,
            args.prior_rounds_grid,
            args.variance_prior_rounds_grid,
            args.freeze_date_from,
            args.freeze_date_to,
            max_selection_events=args.max_selection_events,
            max_evaluation_events=args.max_evaluation_events,
            selection_simulations=args.selection_simulations,
            evaluation_simulations=args.evaluation_simulations,
            bootstrap_samples=args.bootstrap_samples,
            calibration_bins=args.calibration_bins,
            seed=args.seed,
            cut_size=args.cut_size,
        )
        print(f"rolling_validation_report={result['report_path']}")
        print(f"rolling_validation_metrics={result['aggregate_metrics_path']}")
        print(f"rolling_validation_manifest={result['manifest_path']}")
        return 0
    if args.command == "course-challenger-validation":
        result = run_course_challenger_validation(
            args.canonical_dir,
            args.round_performance,
            args.output_dir,
            args.fold,
            args.half_life_grid,
            args.prior_rounds_grid,
            args.variance_prior_rounds_grid,
            args.course_weight_grid,
            args.course_prior_rounds_grid,
            args.freeze_date_from,
            args.freeze_date_to,
            max_selection_events=args.max_selection_events,
            max_evaluation_events=args.max_evaluation_events,
            selection_simulations=args.selection_simulations,
            evaluation_simulations=args.evaluation_simulations,
            bootstrap_samples=args.bootstrap_samples,
            calibration_bins=args.calibration_bins,
            seed=args.seed,
            cut_size=args.cut_size,
            max_absolute_adjustment=args.max_absolute_adjustment,
        )
        print(f"course_challenger_report={result['report_path']}")
        print(f"course_challenger_metrics={result['paired_metrics_path']}")
        print(f"course_challenger_manifest={result['manifest_path']}")
        return 0
    if args.command == "time-split-baseline":
        run_time_split_baseline(
            args.features,
            args.output_dir,
            args.min_train_rows,
            args.min_prior_starts,
            args.model,
            args.enable_logistic,
        )
        return 0
    if args.command == "event-rankings":
        build_event_rankings(
            args.predictions,
            args.output_dir,
            max_events=args.max_events,
            top_n=args.top_n,
        )
        return 0
    if args.command == "current-event-rankings":
        build_current_event_rankings(
            args.features,
            args.odds,
            args.output_dir,
            event_date=args.event_date,
            course_name=args.course_name,
            min_prior_starts=args.min_prior_starts,
            top_n=args.top_n,
        )
        return 0
    if args.command == "value-report":
        build_value_report(
            args.rankings,
            args.odds,
            args.output_dir,
            top_n=args.top_n,
        )
        return 0
    if args.command == "odds-movement":
        build_odds_movement_report(
            args.history_dir,
            args.output_dir,
            current_snapshot_path=args.current_snapshot,
            top_n=args.top_n,
        )
        return 0
    if args.command == "audit-odds-sources":
        candidates = [parse_candidate(value) for value in args.candidate] if args.candidate else None
        player_names = args.player if args.player else None
        result = audit_sources(
            args.output_dir,
            candidates=candidates,
            player_names=player_names,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"source_audit_output_dir={result['output_dir']}")
        print(f"source_count={len(result['rows'])}")
        usable_count = sum(1 for row in result["rows"] if row.get("status") == "usable")
        promising_count = sum(1 for row in result["rows"] if row.get("status") == "promising")
        print(f"usable_sources={usable_count}")
        print(f"promising_sources={promising_count}")
        return 0
    if args.command == "collect-bovada-golf-odds":
        try:
            result = collect_bovada_golf_odds(
                output=args.output,
                raw_output=args.raw_output,
                report_output=args.report_output,
                url=args.url,
                timeout_seconds=args.timeout_seconds,
                include_unmapped=args.include_unmapped,
                archive_dir=args.archive_dir,
                weekly_dir=args.weekly_dir,
            )
        except BovadaOddsError as exc:
            print(f"Bovada odds collection failed: {exc}", file=sys.stderr)
            return 1
        print(f"bovada_odds_output={result['output']}")
        print(f"bovada_raw_output={result['raw_output']}")
        print(f"bovada_report_output={result['report_output']}")
        print(f"bovada_odds_rows={len(result['rows'])}")
        snapshot = result.get("snapshot") or {}
        if snapshot:
            print(f"bovada_snapshot_json={snapshot.get('json_path')}")
            print(f"bovada_snapshot_csv={snapshot.get('csv_path')}")
            print(f"bovada_snapshot_pre_start={snapshot.get('pre_start')}")
            print(f"bovada_snapshot_pre_start_basis={snapshot.get('pre_start_basis')}")
        return 0
    if args.command == "inspect-covers-odds":
        player_names = args.player if args.player else None
        result = inspect_covers_odds(
            output_dir=args.output_dir,
            url=args.url,
            player_names=player_names,
            timeout_seconds=args.timeout_seconds,
            context_items=args.context_items,
        )
        summary = result["summary"]
        print(f"covers_inspection_output_dir={result['output_dir']}")
        print(f"text_item_count={summary['text_item_count']}")
        print(f"odds_token_count={summary['odds_token_count']}")
        print(f"snippet_count={summary['snippet_count']}")
        print(f"likely_parseable={summary['likely_parseable']}")
        print(f"recommendation={summary['recommendation']}")
        return 0
    if args.command == "inspect-odds-url-batch":
        candidates = [parse_candidate(value) for value in args.candidate] if args.candidate else None
        player_names = args.player if args.player else None
        result = inspect_odds_url_batch(
            output_dir=args.output_dir,
            candidates=candidates,
            player_names=player_names,
            timeout_seconds=args.timeout_seconds,
            context_items=args.context_items,
        )
        parseable_count = sum(1 for row in result["rows"] if str(row.get("likely_parseable")).casefold() == "true")
        print(f"odds_url_batch_output_dir={result['output_dir']}")
        print(f"url_count={len(result['rows'])}")
        print(f"parseable_urls={parseable_count}")
        return 0
    if args.command == "collect-dk-placement":
        collect_dk_placement(
            args.output_dir,
            url=args.url,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            retry_sleep_seconds=args.retry_sleep_seconds,
        )
        return 0
    if args.command == "parse-dk-placement":
        parse_dk_placement(
            args.raw,
            args.output,
            metadata_path=args.metadata,
            source_url=args.url,
            season=args.season,
        )
        return 0
    if args.command == "collect-parse-dk-placement":
        try:
            collect_parse_dk_placement(
                args.raw_output_dir,
                args.processed_output,
                url=args.url,
                season=args.season,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
                crawl_linked=args.crawl_linked,
                max_linked_pages=args.max_linked_pages,
            )
        except DraftKingsParseError as exc:
            print(f"DraftKings odds collection failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "run-dk-current-value":
        try:
            result = run_dk_current_value(
                features_path=args.features,
                raw_output_dir=args.raw_output_dir,
                odds_output=args.odds_output,
                odds_history_dir=args.odds_history_dir,
                rankings_output_dir=args.rankings_output_dir,
                value_output_dir=args.value_output_dir,
                movement_output_dir=args.movement_output_dir,
                run_metadata_output=args.run_metadata_output,
                url=args.url,
                season=args.season,
                event_date=args.event_date,
                course_name=args.course_name,
                min_prior_starts=args.min_prior_starts,
                top_n=args.top_n,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
                max_linked_pages=args.max_linked_pages,
                skip_collect=args.skip_collect,
                save_odds_history=not args.no_save_odds_history,
                build_movement=not args.no_build_movement,
            )
        except DraftKingsParseError as exc:
            print(f"DraftKings odds collection failed: {exc}", file=sys.stderr)
            return 1
        print(f"odds_output={result['odds_output']}")
        print(f"odds_history_path={result['odds_history_path']}")
        print(f"rankings_output_dir={result['rankings_output_dir']}")
        print(f"value_output_dir={result['value_output_dir']}")
        print(f"movement_output_dir={result['movement_output_dir']}")
        print(f"run_metadata_path={result['run_metadata_path']}")
        print(f"ranking_rows={len(result['rankings'])}")
        print(f"value_rows={len(result['value_rows'])}")
        print(f"movement_rows={len(result['movement_rows'])}")
        print(f"unmatched_players={len(result['unmatched_players'])}")
        return 0

    if args.command == "review-prospective-golf":
        event_keys = sorted(
            path.name
            for path in args.prospective_root.iterdir()
            if path.is_dir() and (path / "run_manifest.json").exists()
        )
        if not event_keys:
            print("review: no prospective archives found", file=sys.stderr)
            return 1
        try:
            bundles = [
                load_event_bundle(
                    args.prospective_root / event_key,
                    args.grading_root / event_key,
                )
                for event_key in event_keys
                if (args.grading_root / event_key / "grading_manifest.json").exists()
            ]
        except ProspectiveReviewError as exc:
            print(f"review failed: {exc}", file=sys.stderr)
            return 1
        skipped = sorted(set(event_keys) - {bundle.event_key for bundle in bundles})
        challenger_probs = None
        challenger_manifest = None
        if args.cold_start_challenger:
            challenger_probs = {}
            per_event = {}
            for bundle in bundles:
                rows, _ = simulate_challenger(
                    bundle.strength_rows,
                    bundle.run_manifest,
                    prior_rounds=args.prior_rounds,
                )
                challenger_probs[bundle.event_key] = {
                    str(row["player_id"]): {
                        target: float(row[column])
                        for target, column in {
                            "top20": "top20_prob",
                            "top10": "top10_prob",
                            "top5": "top5_prob",
                            "winner": "winner_prob",
                        }.items()
                    }
                    for row in rows
                }
                bundle_result = build_challenger_bundle(
                    bundle.archive_dir,
                    args.output_dir / "challenger" / bundle.event_key,
                    prior_rounds=args.prior_rounds,
                )
                per_event[bundle.event_key] = bundle_result["manifest"]
            challenger_manifest = {
                "challenger_id": CHALLENGER_ID,
                "status": "disabled",
                "production_effect": "none",
                "formula": COLD_START_FORMULA,
                "prior_rounds": args.prior_rounds,
                "events": per_event,
            }
        try:
            report = review_events(
                bundles,
                bootstrap_samples=args.bootstrap_samples,
                seed=args.seed,
                challenger=challenger_probs,
                challenger_manifest=challenger_manifest,
            )
        except ProspectiveReviewError as exc:
            print(f"review failed: {exc}", file=sys.stderr)
            return 1
        paths = write_review(report, args.output_dir)
        print(f"review_json={paths['json']}")
        print(f"review_markdown={paths['markdown']}")
        print(f"review_events={report['cohort']['n_events']}")
        print(f"review_skipped_without_grade={','.join(skipped) or 'none'}")
        if "challenger" in report:
            print(f"challenger_verdict={report['challenger']['decision']['verdict']}")
        return 0
    if args.command == "cold-start-challenger":
        try:
            result = build_challenger_bundle(
                args.archive_dir,
                args.output_dir,
                prior_rounds=args.prior_rounds,
                simulations=args.simulations,
                seed=args.seed,
            )
        except ColdStartChallengerError as exc:
            print(f"cold-start challenger failed: {exc}", file=sys.stderr)
            return 1
        print(f"challenger_predictions={result['predictions_path']}")
        print(f"challenger_report={result['report_path']}")
        print(f"challenger_manifest={result['manifest_path']}")
        print("challenger_activation=disabled")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
