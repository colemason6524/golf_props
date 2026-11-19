"""Round-score O/U paper ledger — separate file, separate cohort, never pooled.

Rows settle to win/loss/push/void. The tournament-outcome ledger is not
touched. A player with no score row for a round voids (books void unplayed
rounds; a WD/DQ is not a loss here — recorded in writing, not graded as real).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import LEDGER_PATH


def read(path: Optional[Path] = None) -> List[dict]:
    p = Path(path or LEDGER_PATH)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append(rows: Iterable[dict], path: Optional[Path] = None) -> int:
    p = Path(path or LEDGER_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with p.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def pick_id(row: dict) -> str:
    # source is part of the identity: one row per (player, round, book).
    return "|".join(str(row.get(k)) for k in
                    ("date", "player_id", "event_id", "round_number",
                     "line", "side", "source"))


def write(rows: List[dict], path: Optional[Path] = None) -> int:
    """Rewrite the ledger (used after grading settles rows in place)."""
    p = Path(path or LEDGER_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def open_rows(rows: List[dict]) -> List[dict]:
    return [r for r in rows if r.get("result") in (None, "", "open")]


def summary(rows: List[dict]) -> Dict[str, float]:
    settled = [r for r in rows if r.get("result") in ("win", "loss")]
    units = sum(float(r.get("units", 0.0)) for r in rows)
    n = len(settled)
    return {"rows": len(rows), "settled": n,
            "hit_rate": (sum(1 for r in settled if r["result"] == "win") / n) if n else 0.0,
            "units": units}


def today() -> str:
    return date.today().isoformat()
