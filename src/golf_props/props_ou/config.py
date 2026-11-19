"""Round-score O/U knobs. Every number here is a Step 1 design decision, dated."""
from __future__ import annotations

from pathlib import Path

from ..config import INTERIM_DIR

PROPS_OU_DIR = INTERIM_DIR / "props_ou"
LEDGER_PATH = PROPS_OU_DIR / "pick_ledger.jsonl"
LINES_DIR = PROPS_OU_DIR / "lines"

# Backtest 2026-11-19 (scripts/round_score_ou_backtest.py, 51,635 rows 2024-01-01
# through 2026-11-14, SIMULATED naive lines): model Brier 0.2397 vs naive 0.25,
# ECE 0.1403 vs 0.1471. Gate passed on both, margin thin, lines biased.
K_SHRINK = 10          # trailing-mean shrinkage toward the field mean
TRAILING_ROUNDS = 20   # trailing window of prior-event rounds
MIN_PRIOR_ROUNDS = 3   # need this many prior-event rounds before a projection
MIN_FIELD_PRIOR = 30   # course+round history rows before trusting course mean
GLOBAL_SD = 2.95       # fallback predictive SD (archive relative_to_field SD)
RUN_LABEL = "ou-exp-20261119"  # namespaced publish label for this cohort

# Playability gates mirror the NFL props family until the shadow window refits.
EV_MIN = 0.02
EV_MAX = 0.08
EDGE_MIN = 0.02


def ensure_dirs() -> None:
    for d in (PROPS_OU_DIR, LINES_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)
