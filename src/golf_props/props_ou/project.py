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

import re

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


def project_new_event(table: pd.DataFrame, event_id: str, event_name: str,
                     round_number: int, course_id: str | None = None,
                     player_ids: list[str] | None = None,
                     field_exp_override: float | None = None) -> pd.DataFrame:
    """Price an upcoming (event, round) from strictly prior history.

    field_exp is the historical mean for (event course, round) — blended
    across course tags when the rotation cannot be separated (RSM Seaside /
    Plantation share tags in this table; the blend and its uncertainty are
    recorded in the receipt, not hidden). player_ids=None prices everyone
    with enough history.
    """
    d = table.sort_values(["event_date_end"]).reset_index(drop=True)
    key = re.sub(r"[^a-z]", "", event_name.lower())
    hist_names = d["event_name"].str.lower().str.replace(r"[^a-z]", "", regex=True)
    mask = hist_names.apply(lambda h: h in key or key in h)
    same = d[mask]
    if field_exp_override is not None:
        fe = float(field_exp_override)
    elif course_id is not None and not same.empty:
        sub = same[(same["course_id"] == course_id)
                   & (same["round_number"] == round_number)]
        fe = float(sub["score"].mean()) if len(sub) >= 30 else float(
            same[same["round_number"] == round_number]["score"].mean())
    elif not same.empty:
        fe = float(same[same["round_number"] == round_number]["score"].mean())
    else:
        fe = float(d[d["round_number"] == round_number]["score"].mean())
    rel = d["relative_to_field"].to_numpy(float)
    ev_end = d["event_date_end"].to_numpy()
    player = d["player_id"].to_numpy()
    names = d["player_name"].to_numpy()
    out = []
    ids = player_ids if player_ids is not None else list(pd.unique(player))
    for pid in ids:
        ii = np.flatnonzero(player == pid)
        if len(ii) == 0:
            continue
        # all history is prior to an upcoming event
        w = rel[ii[-TRAILING_ROUNDS:]]
        n = len(w)
        if n < 3:
            continue
        form = float(w.mean()) * n / (n + K_SHRINK)
        sigma = max(float(w.std(ddof=1)), 1.5) if n >= 5 else GLOBAL_SD
        nm = names[ii[-1]]
        out.append({"player_id": str(pid), "player_name": nm,
                    "event_id": str(event_id), "event_name": event_name,
                    "round_number": int(round_number),
                    "projection": float(fe + form),
                    "form": round(form, 3), "sigma": round(sigma, 3),
                    "n_rounds": n, "field_exp": round(fe, 2)})
    return pd.DataFrame(out)


def project(df: pd.DataFrame, field_exp: pd.Series | None = None) -> pd.DataFrame:
    """One projection row per (player, event, round) from prior events only."""
    d = df.reset_index(drop=True)
    fe = (field_exp if field_exp is not None
          else field_expectation(d)).to_numpy(float)
    rel = d["relative_to_field"].to_numpy(float)
    ev_end = d["event_date_end"].to_numpy()
    player = d["player_id"].to_numpy()
    names = d["player_name"].to_numpy()
    events = d["event_id"].to_numpy()
    event_names = d["event_name"].to_numpy()
    rnds = d["round_number"].to_numpy(int)
    out = []
    # shortcut: per-player loop would be O(players); per-group flatnonzero
    # over the full table is O(groups x rows) — do not do that here.
    order = np.argsort(ev_end, kind="stable")
    sp, see, srel = player[order], ev_end[order], rel[order]
    bounds = np.flatnonzero(np.r_[True, sp[1:] != sp[:-1]])
    for b0, b1 in zip(bounds, np.r_[bounds[1:], len(sp)]):
        ee, rr = see[b0:b1], srel[b0:b1]
        left = np.searchsorted(ee, ee, side="left")
        # one row per (event, round): last index of each run
        for k in range(b0, b1):
            kk = k - b0
            if kk + 1 < len(ee) and see[b0 + kk + 1] == ee[kk] and \
                    rnds[order[b0 + kk + 1]] == rnds[order[k]]:
                continue
            lo = max(left[kk] - TRAILING_ROUNDS, 0)
            w = rr[lo:left[kk]]
            n = len(w)
            if n < 3:  # too little history to price, skip loudly
                continue
            form = float(w.mean()) * n / (n + K_SHRINK)
            sigma = max(float(w.std(ddof=1)), 1.5) if n >= 5 else GLOBAL_SD
            i = order[k]
            out.append({"player_id": str(player[i]),
                        "player_name": names[i],
                        "event_id": str(events[i]),
                        "event_name": event_names[i],
                        "round_number": int(rnds[i]),
                        "projection": float(fe[i] + form),
                        "form": round(form, 3), "sigma": round(sigma, 3),
                        "n_rounds": n})
    return pd.DataFrame(out)
