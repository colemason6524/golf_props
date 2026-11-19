"""Paper grading for round-score O/U, from realized round scores.

Over wins if score > line, under if score < line, push on equality. A player
with no score row for that round (missed cut, WD) settles `void_unplayed` and
never counts toward the record. An unmatched name is `void_unmatched`.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from . import lines as lines_mod
from .config import PROPS_OU_DIR


def realized(table: pd.DataFrame) -> Dict[Tuple[str, str, int], float]:
    d = table.dropna(subset=["score"])
    return {(str(r.player_id), str(r.event_id), int(r.round_number)): float(r.score)
            for r in d.itertuples()}


def settle(rows: List[dict], table: pd.DataFrame) -> List[dict]:
    """Settle every open row against realized scores. Mutates in place."""
    stats = realized(table)
    by_name = {}
    for r in table.itertuples():
        by_name.setdefault(lines_mod.normalize_name(str(r.player_name)), set()).add(
            str(r.player_id))
    for row in rows:
        if row.get("result") not in (None, "", "open"):
            continue
        pid = str(row.get("player_id", ""))
        key = (pid, str(row.get("event_id", "")), int(row.get("round_number", 0)))
        if key not in stats:
            row["result"] = ("void_unmatched" if pid not in
                             {p for ids in by_name.values() for p in ids}
                             else "void_unplayed")
            row["units"] = 0.0
            row["stat"] = None
            continue
        stat = stats[key]
        line = float(row["line"])
        row["stat"] = stat
        if stat == line:
            row["result"] = "push"
            row["units"] = 0.0
        elif (stat > line) == (row["side"] == "OVER"):
            row["result"] = "win"
            row["units"] = float(row["decimal"]) - 1.0
        else:
            row["result"] = "loss"
            row["units"] = -1.0
    return rows


def report_path(event_id: str, round_number: int):
    return PROPS_OU_DIR / f"shadow_graded_{event_id}_r{round_number}.json"
