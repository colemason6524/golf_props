"""Round-score O/U walk-forward backtest (research only, no book lines).

Forecasts P(Over L) for each player-round where L is a SIMULATED research line
built from the NAIVE model (season-average relative_to_field + expected field
score, rounded to the nearest 0.5). These lines are NOT book lines; no ROI here
is a betting claim. Gate per plan: model must beat naive on Brier AND ECE.

Features use strictly pre-round information (prior events only).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROUND_CSV = Path("data/interim/history_refresh_20261119_ou/round_performance.csv")
FALLBACK_CSV = Path("data/pga_2001_2026_round_performance.csv")
OUT_JSON = Path("data/interim/round_score_ou_backtest_20261119.json")

K_SHRINK = 10
MIN_FIELD_PRIOR = 30
MIN_ROUND_PRIOR = 100
GLOBAL_SD = 2.95
TEST_START = "2024-01-01"


def phi_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def main() -> None:
    csv_path = ROUND_CSV if ROUND_CSV.exists() else FALLBACK_CSV
    df = pd.read_csv(csv_path, usecols=[
        "event_id", "event_name", "event_date_start", "event_date_end",
        "season", "course_id", "player_id", "round_number", "score",
        "field_round_score_avg", "relative_to_field",
    ])
    df = df.sort_values(["event_date_end", "event_id", "round_number",
                         "player_id"]).reset_index(drop=True)
    n = len(df)
    score = df["score"].to_numpy(float)
    rel = df["relative_to_field"].to_numpy(float)
    rnd = df["round_number"].to_numpy(int)

    # --- expected field score for (course, round): strictly prior events ---
    df["_cs"] = df.groupby(["course_id", "round_number"])["score"].cumsum()
    df["_cc"] = df.groupby(["course_id", "round_number"]).cumcount()
    df["_ecs"] = df.groupby(["event_id", "course_id",
                             "round_number"])["score"].cumsum()
    df["_ecc"] = df.groupby(["event_id", "course_id", "round_number"]).cumcount()
    ps = (df["_cs"] - df["_ecs"]).to_numpy(float)
    pc = (df["_cc"] - df["_ecc"]).to_numpy(float)
    # round-level fallback (prior events)
    df["_rs"] = df.groupby(["round_number"])["score"].cumsum()
    df["_rc"] = df.groupby(["round_number"]).cumcount()
    df["_res"] = df.groupby(["event_id", "round_number"])["score"].cumsum()
    df["_rec"] = df.groupby(["event_id", "round_number"]).cumcount()
    rs = (df["_rs"] - df["_res"]).to_numpy(float)
    rc = (df["_rc"] - df["_rec"]).to_numpy(float)
    tot_s = np.cumsum(score) - score
    tot_c = np.arange(n, dtype=float)
    field_exp = np.where(pc >= MIN_FIELD_PRIOR, ps / np.maximum(pc, 1),
                  np.where(rc >= MIN_ROUND_PRIOR, rs / np.maximum(rc, 1),
                           np.where(tot_c > 0, tot_s / np.maximum(tot_c, 1),
                                    np.nan)))
    # seed rows with no history: use their own row's field avg (in-sample, flagged)
    seed = np.isnan(field_exp)
    field_exp[seed] = df.loc[seed, "field_round_score_avg"].to_numpy(float)

    # --- per-player trailing features (prior events only) ---
    model_proj = np.full(n, np.nan)
    model_sd = np.full(n, GLOBAL_SD)
    naive_proj = np.full(n, np.nan)
    ev_end = df["event_date_end"].to_numpy()
    season = df["season"].to_numpy()
    pos = np.arange(n)
    for _, idx in df.groupby("player_id").groups.items():
        ii = np.asarray(idx, dtype=int)
        order = np.argsort(ev_end[ii], kind="stable")
        ii = ii[order]
        ee = ev_end[ii]
        rr = rel[ii]
        ss = season[ii]
        # left boundary: first index with event_end >= current (excludes same event)
        left = np.searchsorted(ee, ee, side="left")
        for k in range(len(ii)):
            lo = max(left[k] - 20, 0)
            lo = max(lo, 0)
            # candidates are ii[lo:left[k]]
            if left[k] - lo <= 0:
                tb, nn, sd = 0.0, 0, GLOBAL_SD
            else:
                w = rr[lo:left[k]]
                nn = len(w)
                tb = float(w.mean())
                sd = float(w.std(ddof=1)) if nn >= 5 else GLOBAL_SD
            shrunk = tb * nn / (nn + K_SHRINK)
            model_proj[ii[k]] = field_exp[ii[k]] + shrunk
            model_sd[ii[k]] = max(sd, 1.5)
            # naive: same-season prior-event average
            se = ss[k]
            # walk back within same season & prior events
            m = (ss[lo:left[k]] == se)
            if m.sum() >= 3:
                nb = float(rr[lo:left[k]][m].mean())
            else:
                nb = 0.0
            naive_proj[ii[k]] = field_exp[ii[k]] + nb

    df["model_proj"] = model_proj
    df["model_sd"] = model_sd
    df["naive_proj"] = naive_proj
    # SIMULATED research line from the naive model (NOT a book line)
    df["line_sim"] = np.round(df["naive_proj"] * 2.0) / 2.0
    z = (df["line_sim"] - df["model_proj"]) / df["model_sd"]
    df["p_over"] = 1.0 - z.map(phi_cdf)
    df["y_over"] = (df["score"] > df["line_sim"]).astype(int)

    test = df[df["event_date_end"] >= TEST_START].copy()
    p = test["p_over"].to_numpy(float)
    y = test["y_over"].to_numpy(float)

    def brier(pp: np.ndarray, yy: np.ndarray) -> float:
        return float(np.mean((pp - yy) ** 2))

    def ece(pp: np.ndarray, bins: int = 10) -> float:
        edges = np.linspace(0, 1, bins + 1)
        tot = 0.0
        for b in range(bins):
            m = (pp > edges[b]) & (pp <= edges[b + 1] if b < bins - 1
                                   else pp <= edges[b + 1] + 1e-12)
            if b == 0:
                m = m | (pp == 0.0)
            if m.sum() == 0:
                continue
            tot += m.mean() * abs(float(pp[m].mean()) - float(y[m].mean()))
        return float(tot)

    eps = 1e-6
    pc_ = np.clip(p, eps, 1 - eps)
    out = {
        "csv": str(csv_path),
        "rows_total": int(n),
        "rows_test": int(len(test)),
        "test_window": [TEST_START,
                        str(df["event_date_end"].max())],
        "lines": "SIMULATED from naive model (nearest 0.5); NOT book lines",
        "brier_model": brier(p, y),
        "brier_naive_p50": brier(np.full_like(p, 0.5), y),
        "ece_model": ece(p),
        "ece_naive_p50": ece(np.full_like(p, 0.5)),
        "logloss_model": float(np.mean(-(y * np.log(pc_) +
                                          (1 - y) * np.log(1 - pc_)))),
        "rmse_model_proj": float(np.sqrt(np.mean((test["model_proj"] -
                                                   test["score"]) ** 2))),
        "rmse_naive_proj": float(np.sqrt(np.mean((test["naive_proj"] -
                                                   test["score"]) ** 2))),
        "mae_model_proj": float(np.mean(np.abs(test["model_proj"] -
                                                test["score"]))),
        "coverage_68": float(np.mean(np.abs(test["score"] -
                                             test["model_proj"]) <=
                                     test["model_sd"])),
        "coverage_95": float(np.mean(np.abs(test["score"] -
                                             test["model_proj"]) <=
                                     1.96 * test["model_sd"])),
    }
    # by-round cut dynamics
    by_round = {}
    for r, g in test.groupby("round_number"):
        pp, yy = g["p_over"].to_numpy(float), g["y_over"].to_numpy(float)
        by_round[str(int(r))] = {
            "n": int(len(g)),
            "events": int(g["event_id"].nunique()),
            "brier_model": brier(pp, yy) if len(g) else None,
            "brier_naive": float(np.mean((0.5 - yy) ** 2)) if len(g) else None,
            "p_over_rate": float(yy.mean()),
            "mean_line": float(g["line_sim"].mean()),
        }
    out["by_round"] = by_round
    # simulated betting (informational only, -110 both sides)
    for edge in (0.04, 0.06):
        over = p >= 0.5 + edge
        under = p <= 0.5 - edge
        plays = over | under
        if plays.sum() == 0:
            continue
        wins = (over & (y == 1)) | (under & (y == 0))
        profit = wins[plays].sum() * 100 / 110 - (~wins[plays]).sum()
        out[f"sim_edge{int(edge*100)}"] = {
            "plays": int(plays.sum()),
            "win_rate": float(wins[plays].mean()),
            "units_110": float(profit),
        }
    out["gate"] = {
        "beats_naive_brier": out["brier_model"] < out["brier_naive_p50"],
        "beats_naive_ece": out["ece_model"] < out["ece_naive_p50"],
    }
    out["gate"]["pass"] = (out["gate"]["beats_naive_brier"] and
                           out["gate"]["beats_naive_ece"])
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
