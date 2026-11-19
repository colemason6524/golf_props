"""Ingest DraftKings R1 round-score O/U lines for the RSM Classic (paper).

The 34 lines below are transcribed verbatim from the approved plan on the VM
(`~/muse-harness/plans/golf-rsm-r1-dk-lines-ingest.md`), which recorded a live
browser read at 2026-11-19 04:41 UTC — before Round 1 teed off. Nothing here
is synthesized: each line was observed at DraftKings, both prices are kept, and
the book travels in `source` (that is where the line came from). FanDuel posted
nothing for R1 and Fanatics had one line (already in the ledger, untouched), so
DraftKings is the fallback book, not the primary.

A player with no prior-event history cannot be priced here; the row is still
recorded (NO_VALUE / unpriced, result `no_pick`) rather than dropped or forced.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from golf_props.props_ou import ledger, lines, publish, shadow  # noqa: E402
from golf_props.props_ou.config import PROPS_OU_DIR, RUN_LABEL  # noqa: E402
from golf_props.props_ou.ingest import round_table  # noqa: E402

EVENT_ID = "rsm-classic-2026"
EVENT_NAME = "PGA The RSM Classic 2026"
ROUND = 1
BOOK = "draftkings-browser-read"
MARKET = "Round Score – Round 1 O/U"
CAPTURED_AT = "2026-11-19T04:41:00+00:00"
# Row date = local (ET) date of the browser read, not the wall clock at ingest:
# pick_id keys on it, so a re-run tomorrow must not append the same lines again.
ROW_DATE = "2026-11-18"
PROVENANCE = "browser-read by Muse 2026-11-19 04:41 UTC, pre-start"

# player, line, over, under — verbatim, plan order.
DK_LINES = [
    ("Harris English", 68.5, 102, -138),
    ("Keith Mitchell", 67.5, -154, 115),
    ("J.T. Poston", 69.5, 110, -148),
    ("Jackson Koivun", 68.5, -142, 106),
    ("Mac Meissner", 68.5, -104, -130),
    ("Doug Ghim", 68.5, -146, 108),
    ("John Keefer", 69.5, -118, -114),
    ("Marco Penge", 69.5, -130, -104),
    ("Brian Harman", 68.5, -150, 112),
    ("Keegan Bradley", 69.5, 102, -136),
    ("Denny McCarthy", 68.5, -102, -132),
    ("Alex Smalley", 68.5, -108, -124),
    ("Sepp Straka", 68.5, -114, -118),
    ("Pierceson Coody", 68.5, -102, -134),
    ("Austin Smotherman", 69.5, 104, -140),
    ("Benjamin James", 68.5, -128, -106),
    ("Chris Kirk", 69.5, 100, -136),
    ("Blades Brown", 67.5, -150, 110),
    ("Brooks Koepka", 68.5, -110, -124),
    ("Michael Thorbjornsen", 67.5, -158, 118),
    ("Matt Wallace", 68.5, 112, -150),
    ("Ben Kohles", 68.5, 118, -158),
    ("Mackenzie Hughes", 68.5, -108, -124),
    ("Harry Hall", 68.5, 104, -140),
    ("Ricky Castillo", 68.5, -108, -124),
    ("Steven Fisk", 68.5, -110, -124),
    ("Christiaan Bezuidenhout", 69.5, -110, -124),
    ("Andrew Novak", 68.5, 108, -146),
    ("Michael Brennan", 67.5, -144, 106),
    ("Sami Valimaki", 68.5, -106, -126),
    ("Eric Cole", 68.5, -104, -130),
    ("Jordan Smith", 67.5, -156, 116),
    ("Kris Ventura", 68.5, 110, -148),
    ("Ryo Hisatsune", 68.5, -112, -120),
]


def as_read_lines() -> list[lines.RoundLine]:
    """RoundLine objects carrying book + provenance; no pricing touched."""
    out = []
    for name, line, over, under in DK_LINES:
        out.append(lines.RoundLine(
            event_id=EVENT_ID, event_name=EVENT_NAME,
            market_id=f"{BOOK}-{lines.normalize_name(name)}-r{ROUND}",
            market_name=MARKET, player_name=name, round_number=ROUND,
            line=float(line), over_american=int(over),
            under_american=int(under), captured_at=CAPTURED_AT,
            source=BOOK, provenance=PROVENANCE))
    return out


def unpriced_row(ln: lines.RoundLine, reason: str) -> dict:
    """A recorded observation with no model price and no side."""
    return {"date": ROW_DATE, "run_label": RUN_LABEL,
            "captured_at": ln.captured_at, "event_id": ln.event_id,
            "event_name": ln.event_name, "player_id": None,
            "player_name": ln.player_name, "round_number": ln.round_number,
            "line": ln.line, "projection": None,
            "over_american": ln.over_american,
            "under_american": ln.under_american, "source": ln.source,
            "provenance": ln.provenance, "result": "no_pick", "units": 0.0,
            "settled_at": None, "side": None, "p_model": None,
            "p_market": None, "american": None, "decimal": None,
            "edge": None, "ev": None, "tier": "NO_VALUE", "sigma": None,
            "unpriced_reason": reason}


def run(commit: bool = True) -> dict:
    table = round_table()
    read = as_read_lines()
    priced, diag = shadow.build_picks(table, _project(table), read)
    seen = {lines.normalize_name(r["player_name"]) for r in priced}
    for r in priced:
        r["date"] = ROW_DATE  # build_picks stamps the wall clock; pin to the read
    rows = priced + [unpriced_row(ln, "no_history_match")
                     for ln in read
                     if lines.normalize_name(ln.player_name) not in seen]
    existing = {ledger.pick_id(r) for r in ledger.read()}
    new_rows = [r for r in rows if ledger.pick_id(r) not in existing]
    appended = ledger.append(new_rows) if (commit and new_rows) else 0
    report = {"generated_at": ledger.today() + " ingest", "run_label": RUN_LABEL,
              "event_id": EVENT_ID, "book": BOOK, "captured_at": CAPTURED_AT,
              "provenance": PROVENANCE, "diag": diag,
              "diag_unpriced": len(rows) - len(priced),
              "rows": rows, "appended": appended,
              "already_present": len(rows) - len(new_rows)}
    out = PROPS_OU_DIR / "shadow_run_2026-11-19_dk.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"dk r1 ingest: read={len(read)} priced={len(priced)} "
          f"unpriced={report['diag_unpriced']} appended={appended} -> {out.name}")
    return report


def _project(table):
    import pandas as pd
    from golf_props.props_ou import project
    return project.project_new_event(table, EVENT_ID, EVENT_NAME, ROUND)


if __name__ == "__main__":
    rep = run(commit="--no-commit" not in sys.argv)
    led = ledger.read()
    ev = [r for r in led if r["event_id"] == EVENT_ID]
    print("ledger rows for event:", len(ev),
          "| by source:", {s: sum(1 for r in ev if r["source"] == s)
                           for s in sorted({r["source"] for r in ev})})
    print("gates:", publish.soft_publish_gate(led))
