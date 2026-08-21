"""Canonical table column definitions.

These are intentionally simple lists for Phase 0. Normalizers can use them to
order output CSVs and tests can use them to check source adapters.
"""

from __future__ import annotations

EVENTS_COLUMNS = [
    "event_id",
    "source",
    "source_event_id",
    "tour",
    "season",
    "event_name",
    "date_start",
    "date_end",
    "timezone",
    "format",
    "is_major",
    "is_alternate_field",
    "created_at_utc",
]

COURSES_COLUMNS = [
    "course_id",
    "source",
    "source_course_id",
    "course_name",
    "location",
    "country",
    "par",
    "yardage",
    "grass_type",
    "latitude",
    "longitude",
    "created_at_utc",
]

COURSE_ALIASES_COLUMNS = [
    "source",
    "source_course_id",
    "source_course_name",
    "canonical_course_id",
    "canonical_course_name",
    "match_method",
    "confidence",
    "review_status",
    "notes",
]

PLAYERS_COLUMNS = [
    "player_id",
    "source",
    "source_player_id",
    "player_name",
    "country",
    "handedness",
    "date_of_birth",
    "created_at_utc",
]

EVENT_COURSES_COLUMNS = [
    "event_id",
    "course_id",
    "round_number",
    "is_primary_course",
    "notes",
]

PLAYER_EVENT_RESULTS_COLUMNS = [
    "result_id",
    "event_id",
    "player_id",
    "finish_position",
    "finish_text",
    "made_cut",
    "withdrawn",
    "disqualified",
    "total_score",
    "total_to_par",
    "rounds_played",
    "earnings",
    "recorded_at_utc",
]

ROUND_SCORES_COLUMNS = [
    "round_score_id",
    "event_id",
    "course_id",
    "player_id",
    "round_number",
    "score",
    "to_par",
    "position_after_round",
    "made_cut_status",
    "started_at_utc",
    "completed_at_utc",
    "recorded_at_utc",
]

ODDS_SNAPSHOTS_COLUMNS = [
    "odds_id",
    "event_id",
    "event_name",
    "season",
    "player_id",
    "player_name",
    "sportsbook",
    "market_type",
    "market_name",
    "selection_name",
    "line",
    "price_american",
    "price_decimal",
    "implied_probability",
    "captured_at_utc",
    "source_url",
    "market_status",
    "is_closing_candidate",
]

FEATURES_PLAYER_EVENT_COLUMNS = [
    "feature_row_id",
    "event_id",
    "event_name",
    "player_id",
    "player_name",
    "course_id",
    "course_name",
    "season",
    "feature_timestamp_utc",
    "event_date_start",
    "field_size",
    "prior_starts",
    "days_since_last_start",
    "recent_made_cut_rate",
    "recent_top20_rate",
    "recent_top10_rate",
    "recent_top5_rate",
    "recent_win_rate",
    "weighted_recent_made_cut_rate",
    "weighted_recent_top20_rate",
    "weighted_recent_top10_rate",
    "weighted_recent_top5_rate",
    "weighted_recent_win_rate",
    "weighted_recent_avg_finish",
    "weighted_recent_avg_score_to_par",
    "recent_avg_finish",
    "recent_avg_score_to_par",
    "course_starts",
    "course_made_cut_rate",
    "course_top20_rate",
    "course_win_rate",
    "course_avg_finish",
    "major_starts",
    "major_made_cut_rate",
    "major_top20_rate",
    "major_top10_rate",
    "major_top5_rate",
    "major_win_rate",
    "major_avg_finish",
    "open_starts",
    "open_made_cut_rate",
    "open_top20_rate",
    "open_top10_rate",
    "open_top5_rate",
    "open_win_rate",
    "open_avg_finish",
    "target_make_cut",
    "target_top20",
    "target_top10",
    "target_top5",
    "target_win",
]

CURRENT_EVENT_FEATURES_COLUMNS = FEATURES_PLAYER_EVENT_COLUMNS + [
    "player_match_status",
    "history_through_date",
]

CANONICAL_TABLES = {
    "events": EVENTS_COLUMNS,
    "courses": COURSES_COLUMNS,
    "course_aliases": COURSE_ALIASES_COLUMNS,
    "players": PLAYERS_COLUMNS,
    "event_courses": EVENT_COURSES_COLUMNS,
    "player_event_results": PLAYER_EVENT_RESULTS_COLUMNS,
    "round_scores": ROUND_SCORES_COLUMNS,
    "odds_snapshots": ODDS_SNAPSHOTS_COLUMNS,
    "features_player_event": FEATURES_PLAYER_EVENT_COLUMNS,
}
