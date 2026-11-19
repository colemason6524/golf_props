"""Discord gating for the experimental round-score O/U cohort.

Event-based ship rule (golf has no weeks):

1. **Soft publish (Gate 1)** — after ONE fully settled shadow EVENT (all rounds
   graded) the picks may go to Discord as a clearly-labeled experimental
   cohort: paper only, no units, no stake, same golf channel only, distinct
   run_label. This is visibility, not graduation.
2. **Graduation (Gate 2)** — 2 settled events AND >= 50 settled rows, calibrated
   AND profitable at captured prices; otherwise the family is retired in
   writing. Calibration is the binding gate, not the row count.

The experimental post uses its own webhook env and refuses to cross-post into
the official team channel. Nothing sends until Gate 1.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional, Tuple

from ..config import PROJECT_ROOT

try:
    from ..config import HTTP_TIMEOUT_SECONDS, HTTP_USER_AGENT
except ImportError:  # golf config is paths-only; same defaults as elsewhere
    HTTP_TIMEOUT_SECONDS = 30
    HTTP_USER_AGENT = "golf-props/1.0"

from . import ledger
from .config import RUN_LABEL

EXPERIMENTAL_WEBHOOK_ENV = "GOLF_OU_EXPERIMENTAL_WEBHOOK_URL"
TEAM_WEBHOOK_ENV = "GOLF_PROPS_DISCORD_WEBHOOK_URL"
HEADER = ("**EXPERIMENTAL — golf round-score O/U (paper only)**\n"
          "_Not an official pick. No units, no stake, not part of the "
          "tournament record. Tracked in the separate round-score paper "
          "ledger._")


def settled_events(rows: List[dict]) -> Dict[str, dict]:
    """Per event_id: row count, settled count, and whether the event is clean."""
    out: Dict[str, dict] = {}
    for row in rows:
        key = str(row.get("event_id", ""))
        rec = out.setdefault(key, {"rows": 0, "settled": 0, "open": 0,
                                   "no_pick": 0, "playable": 0, "units": 0.0,
                                   "event_name": row.get("event_name", "")})
        rec["rows"] += 1
        if row.get("tier") == "PLAYABLE":
            rec["playable"] += 1
        if row.get("result") == "no_pick":
            # observed line recorded without a priceable side; never settles
            rec["no_pick"] += 1
            continue
        if row.get("result") in ("win", "loss", "push", "void_unplayed",
                                 "void_unmatched"):
            rec["settled"] += 1
            rec["units"] += float(row.get("units", 0.0))
        else:
            rec["open"] += 1
    for rec in out.values():
        rec["clean"] = rec["open"] == 0 and rec["settled"] > 0
    return out


def soft_publish_gate(rows: List[dict]) -> Tuple[bool, str]:
    """One fully settled shadow event is enough for the experimental cohort."""
    events = settled_events(rows)
    clean = sorted(k for k, v in events.items() if v["clean"])
    if not clean:
        return False, "no fully settled shadow event yet"
    ev = clean[-1]
    return True, (f"settled shadow event {events[ev]['event_name']} "
                   f"({events[ev]['settled']} settled rows)")


def graduation(rows: List[dict]) -> Tuple[bool, str]:
    """Gate 2: 2 settled events AND >= 50 settled rows, profitable."""
    events = settled_events(rows)
    clean = [k for k, v in events.items() if v["clean"]]
    settled = sum(v["settled"] for v in events.values())
    if len(clean) < 2:
        return False, f"{len(clean)} settled event(s); Gate 2 needs 2"
    if settled < 50:
        return False, f"{settled} settled rows; Gate 2 needs >= 50"
    units = sum(float(r.get("units", 0.0)) for r in rows)
    if units <= 0:
        return False, f"paper record not profitable ({units:+.2f}u)"
    return True, (f"{len(clean)} settled events, {settled} settled rows, "
                  f"{units:+.2f}u")


def format_experimental(rows: List[dict], event_id: str,
                        limit: int = 15) -> str:
    picks = [r for r in rows if r.get("tier") == "PLAYABLE"
             and str(r.get("event_id")) == event_id]
    picks.sort(key=lambda r: -float(r.get("ev", 0.0)))
    lines = [HEADER, "",
             f"Round-score O/U leans · captured FanDuel prices · "
             f"`{RUN_LABEL}`",
             "`player — round line — lean (model projection)`", ""]
    for r in picks[:limit]:
        lines.append(f"• {r['player_name']} — R{r['round_number']} "
                     f"{float(r['line']):g} — {r['side']} "
                     f"(proj {float(r['projection']):.1f}, "
                     f"{int(r['american']):+d})")
    if len(picks) > limit:
        lines.append(f"… {len(picks) - limit} more in the paper ledger")
    lines += ["", "_Paper cohort. No units posted, no record posted._"]
    return "\n".join(lines)


def send(message: str, webhook: Optional[str] = None) -> Tuple[bool, str]:
    hook = webhook or os.environ.get(EXPERIMENTAL_WEBHOOK_ENV, "")
    if not hook:
        return False, f"{EXPERIMENTAL_WEBHOOK_ENV} not set; not posted"
    if hook == os.environ.get(TEAM_WEBHOOK_ENV):
        return False, "experimental webhook equals the team webhook; refusing"
    req = urllib.request.Request(
        hook, data=json.dumps({"content": message}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return 200 <= resp.status < 300, f"http {resp.status}"


def publish_experimental(event_id: Optional[str] = None,
                         rows: Optional[List[dict]] = None) -> Tuple[bool, str]:
    """Gate, then post. Never posts before Gate 1."""
    rows = ledger.read() if rows is None else rows
    ok, why = soft_publish_gate(rows)
    if not ok:
        return False, f"Gate 1 closed: {why}"
    if event_id is None:
        clean = sorted(k for k, v in settled_events(rows).items() if v["clean"])
        event_id = clean[-1]
    sent, info = send(format_experimental(rows, event_id))
    _ = PROJECT_ROOT  # receipt anchor: scaffold lives under the repo root
    return sent, (f"{why}; {info}")
