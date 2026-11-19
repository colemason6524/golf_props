"""Round-score projection: field expectation + shrunk trailing form.

For a player and round, using strictly prior events:

    field_exp  = mean score for (course, round) over prior events
    form       = mean of trailing relative_to_field (<=20 rounds), shrunk to 0
    projection = field_exp + form
    sigma      = player's trailing SD (>=5 rounds) else GLOBAL_SD

prob_over is a normal tail probability. Nothing here reads a book line.
"""
from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd

from .config import GLOBAL_SD, K_SHRINK, MIN_FIELD_PRIOR, TRAILING_ROUNDS


def prob_over(projection: float, line: float, sigma: float) -> float:
    """Normal predictive probability that the realized score beats `line`."""
    z = (line - projection) / sigma if sigma else 0.0
    return 0.5 * (1.0 - erf(z / sqrt(2)))


def field_expectation(df: pd.DataFrame) -> pd.Series:
    """Per-row course+round mean over strictly prior events (fallback: round)."""
    d = df
    cs = d.groupby(["course_id", "round_number"])["score"].cumsum()
    cc = d.groupby(["course_id", "round_number"]).cumcount()
    ecs = d.groupby(["event_id", "course_id", "round_number"])["score"].cumsum()
    ecc = d.groupby(["event_id", "course_id", "round_number"]).cumcount()
    ps, pc = (cs - ecs).to_numpy(float), (cc - ecc).to_numpy(float)
    rs = (d.groupby(["round_number"])["score"].cumsum()
          - d.groupby(["event_id", "round_number"])["score"].cumsum())
    rc = (d.groupby(["round_number"]).cumcount()
          - d.groupby(["event_id", "round_number"]).cumcount())
    rs, rc = rs.to_numpy(float), rc.to_numpy(float)
    return pd.Series(np.where(pc >= MIN_FIELD_PRIOR, ps / np.maximum(pc, 1),
                      np.where(rc >= MIN_FIELD_PRIOR, rs / np.maximum(rc, 1),
                               d["field_round_score_avg"].to_numpy(float))),
                     index=d.index)


def project(df: pd.DataFrame, field_exp: pd.Series | None = None) -> pd.DataFrame:
    """One projection row per (player, event, round) from prior events only."""
    d = df.reset_index(drop=True)
    fe = field_exp if field_exp is not None else field_expectation(d)
    rel = d["relative_to_field"].to_numpy(float)
    ev_end = d["event_date_end"].to_numpy()
    out = []
    for (pid, event, rnd), idx in d.groupby(
            ["player_id", "event_id", "round_number"]).groups.items():
        ii = np.asarray(sorted(idx), dtype=int)
        # strictly prior events for this player
        prior = np.flatnonzero(ev_end < ev_end[ii[0]])
        w = rel[prior[-TRAILING_ROUNDS:]] if len(prior) else np.array([])
        n = len(w)
        form = float(w.mean()) * n / (n + K_SHRINK) if n else 0.0
        sigma = max(float(w.std(ddof=1)), 1.5) if n >= 5 else GLOBAL_SD
        if n < 3:  # shortcut: too little history to price, skip loudly
            continue
        row = d.iloc[ii[0]]
        out.append({"player_id": str(pid), "player_name": row["player_name"],
                    "event_id": str(event), "event_name": row["event_name"],
                    "round_number": int(rnd),
                    "projection": float(fe.iloc[ii[0]] + form),
                    "form": round(form, 3), "sigma": round(sigma, 3),
                    "n_rounds": n})
    return pd.DataFrame(out)
