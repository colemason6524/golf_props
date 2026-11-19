"""Shadow/paper pipeline: projection -> captured FanDuel line -> pick -> ledger.

    history -> projection -> captured line -> edge/EV tier -> paper ledger

No Discord, no board, no tournament ledger. `run_label` namespaces every
published cohort. Nothing is priced without a captured book line.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..normalization.manual_odds import american_to_decimal
from . import grade, ledger, lines, project, publish
from .config import (EDGE_MIN, EV_MAX, EV_MIN, PROPS_OU_DIR, RUN_LABEL,
                     ensure_dirs)
from .ingest import round_table


def _name_index(table: pd.DataFrame) -> Dict[str, str]:
    """Normalized player name -> player_id (history ids win ties by recency)."""
    d = table.sort_values("event_date_end").drop_duplicates(
        subset=["player_id"], keep="last")
    return {lines.normalize_name(str(r.player_name)): str(r.player_id)
            for r in d.itertuples()}


def _fold_key(name: str) -> str:
    """Second-chance key: diacritics folded, parenthetical tags dropped.

    Only consulted when the exact key misses, so "Michael Thorbjornsen" never
    resolves through his amateur "(a)" row.
    """
    text = unicodedata.normalize("NFKD", str(name)).encode(
        "ascii", "ignore").decode("ascii")
    return lines.normalize_name(re.sub(r"\([^)]*\)", " ", text))


def _fold_index(table: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Folded name -> player_id, or None when the fold is ambiguous."""
    d = table.sort_values("event_date_end").drop_duplicates(
        subset=["player_id"], keep="last")
    out: Dict[str, Optional[str]] = {}
    for r in d.itertuples():
        key = _fold_key(str(r.player_name))
        pid = str(r.player_id)
        if key in out and out[key] != pid:
            out[key] = None
        else:
            out.setdefault(key, pid)
    return out


def resolve_player(index: Dict[str, str], folded: Dict[str, Optional[str]],
                   name: str) -> Optional[str]:
    key = lines.normalize_name(name)
    if key in index:
        return index[key]
    return folded.get(_fold_key(name))


def pick_row(projection: float, sigma: float, ln: lines.RoundLine) -> dict:
    p_over = project.prob_over(projection, ln.line, sigma)
    quotes = [(s, a) for s, a in (("OVER", ln.over_american),
                                  ("UNDER", ln.under_american))
              if a is not None]
    if len(quotes) == 2:
        p_over_raw = 1.0 / american_to_decimal(quotes[0][1])
        p_under_raw = 1.0 / american_to_decimal(quotes[1][1])
        total = p_over_raw + p_under_raw or 1.0
        p_market = {"OVER": p_over_raw / total,
                    "UNDER": p_under_raw / total}
    else:
        p_market = {}
    sides = []
    for side, american in quotes:
        p_model = p_over if side == "OVER" else 1.0 - p_over
        decimal = american_to_decimal(american)
        p_mkt = p_market.get(side)
        edge = None if p_mkt is None else p_model - p_mkt
        ev = None if p_mkt is None else p_model * decimal - 1.0
        sides.append({"side": side, "p_model": p_model, "p_market": p_mkt,
                      "american": american, "decimal": decimal,
                      "edge": edge, "ev": ev})
    if len(sides) == 1:
        # one recorded price: lean without an EV claim, never synthesized
        only = dict(sides[0])
        only["tier"] = "OBSERVED_LEAN"
        only["sigma"] = sigma
        return only
    best = max(sides, key=lambda s: s["ev"] if s["ev"] is not None else -9e9)
    playable = (best["ev"] is not None and EV_MIN <= best["ev"] <= EV_MAX
                and best["edge"] is not None and best["edge"] >= EDGE_MIN)
    return {"side": best["side"], "p_model": best["p_model"],
            "p_market": best["p_market"], "american": best["american"],
            "decimal": best["decimal"], "edge": best["edge"], "ev": best["ev"],
            "tier": "PLAYABLE" if playable else "NO_VALUE", "sigma": sigma}


def build_picks(table: pd.DataFrame, proj: pd.DataFrame,
                captured: List[lines.RoundLine]) -> Tuple[List[dict], dict]:
    index = _name_index(table)
    folded = _fold_index(table)
    by_key = {(str(r.player_id), int(r.round_number)): r for r in proj.itertuples()}
    rows, diag = [], {"lines": len(captured), "matched": 0, "unmatched": 0,
                      "playable": 0}
    for ln in captured:
        pid = resolve_player(index, folded, ln.player_name)
        if not pid:
            diag["unmatched"] += 1
            continue
        match = by_key.get((pid, ln.round_number))
        if match is None:
            diag["unmatched"] += 1
            continue
        diag["matched"] += 1
        row = {"date": ledger.today(), "run_label": RUN_LABEL,
               "captured_at": ln.captured_at, "event_id": ln.event_id,
               "event_name": ln.event_name, "player_id": pid,
               "player_name": ln.player_name, "round_number": ln.round_number,
               "line": ln.line, "projection": round(float(match.projection), 2),
               "over_american": ln.over_american,
               "under_american": ln.under_american,
               "source": ln.source, "provenance": ln.provenance,
               "result": "open", "units": 0.0,
               "settled_at": None}
        row.update(pick_row(float(match.projection), float(match.sigma), ln))
        if row["tier"] == "PLAYABLE":
            diag["playable"] += 1
        rows.append(row)
    return rows, diag


def run(event_id: Optional[str] = None, capture: bool = True,
        commit: bool = True,
        lines_override: Optional[List[lines.RoundLine]] = None) -> dict:
    ensure_dirs()
    table = round_table()
    captured = (lines_override if lines_override is not None
                else lines.fetch(capture))
    if event_id is not None:
        captured = [ln for ln in captured if ln.event_id == event_id]
    if event_id is not None and table[table["event_id"] == event_id].empty:
        # upcoming event (no rows yet): price each lined round from history
        frames = []
        for (eid, rnd) in sorted({(ln.event_id, ln.round_number)
                                  for ln in captured}):
            nm = next(ln.event_name for ln in captured if ln.event_id == eid)
            frames.append(project.project_new_event(table, eid, nm, rnd))
        proj = pd.concat(frames, ignore_index=True) if frames else table.iloc[0:0]
    else:
        proj = project.project(table)
    rows, diag = build_picks(table, proj, captured)
    existing = {ledger.pick_id(r) for r in ledger.read()}
    new_rows = [r for r in rows if ledger.pick_id(r) not in existing]
    appended = ledger.append(new_rows) if (commit and new_rows) else 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {"generated_at": stamp, "run_label": RUN_LABEL,
              "event_id": event_id, "diag": diag, "rows": rows,
              "appended": appended, "candidates": len(new_rows)}
    out = PROPS_OU_DIR / f"shadow_run_{stamp[:10]}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"round-score shadow: {diag} -> appended {appended} rows, {out.name}")
    return report


def grade_event(event_id: str, round_number: int) -> dict:
    """Settle the paper ledger for one event-round and write the graded report."""
    rows = ledger.read()
    table = round_table()
    if table[table["event_id"] == event_id].empty:
        return {"event_id": event_id, "round_number": round_number,
                "error": "event not in round history — not played yet, not graded"}
    rows = grade.settle(rows, table)
    ledger.write(rows)
    er = [r for r in rows if r.get("event_id") == event_id
          and int(r.get("round_number", 0)) == round_number]
    summ = ledger.summary(er)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "run_label": RUN_LABEL, "event_id": event_id,
        "round_number": round_number, "summary": summ,
        "playable": [r for r in er if r["tier"] == "PLAYABLE"]}
    grade.report_path(event_id, round_number).write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return summ


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Golf round-score O/U shadow run")
    ap.add_argument("--event-id", default=None)
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-capture", action="store_true")
    ap.add_argument("--grade", action="store_true")
    ap.add_argument("--round", type=int, default=None)
    ap.add_argument("--publish-experimental", action="store_true",
                    help="post the experimental cohort — gated on 1 settled event")
    a = ap.parse_args(argv)
    if a.grade:
        if a.event_id is None or a.round is None:
            ap.error("--grade needs --event-id and --round")
        print(grade_event(a.event_id, a.round))
        return 0
    report = run(a.event_id, capture=not a.no_capture,
                 commit=not a.no_commit)
    d = report["diag"]
    print(f"lines={d['lines']} matched={d['matched']} "
          f"unmatched={d['unmatched']} playable={d['playable']} "
          f"appended={report['appended']}")
    if a.publish_experimental:
        ok, why = publish.publish_experimental()
        print(f"experimental publish: {'sent' if ok else 'not sent'} — {why}")
    return 0
