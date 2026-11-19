"""Round logs for the O/U family, from the refreshed round performance table.

Reads the versioned refresh output when present, else the frozen canonical
table. Rows are per player-round with strictly pre-round features left to
project.py; this module only loads and sorts.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import PROJECT_ROOT

REFRESHED = (PROJECT_ROOT / "data" / "interim" / "history_refresh_20261119_ou"
             / "round_performance.csv")
FROZEN = PROJECT_ROOT / "data" / "pga_2001_2026_round_performance.csv"

COLUMNS = ["event_id", "event_name", "event_date_start", "event_date_end",
           "season", "course_id", "player_id", "player_name", "round_number",
           "score", "field_round_score_avg", "relative_to_field"]


def round_table(path: Path | None = None) -> pd.DataFrame:
    """All per-player per-round rows, ordered by event then round."""
    src = Path(path) if path else (REFRESHED if REFRESHED.exists() else FROZEN)
    df = pd.read_csv(src, usecols=COLUMNS)
    return df.sort_values(["event_date_end", "event_id", "round_number",
                           "player_id"]).reset_index(drop=True)


def source_name() -> str:
    if REFRESHED.exists():
        return "history_refresh_20261119_ou"
    return "pga_2001_2026_round_performance (frozen)"
