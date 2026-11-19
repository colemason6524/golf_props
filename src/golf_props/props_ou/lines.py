"""FanDuel round-score lines adapter (free public coupon endpoint, no login).

Endpoint (verified 2026-11-19): GET
  https://sbapi.nj.sportsbook.fanduel.com/api/content-managed-page
    ?page=CUSTOM&customPageId=pga&_ak=FhMFpcPWXMeyZxOx&timezone=America/New_York
with Origin/Referer headers. The live coupon carries outrights, Top X, groups,
3-balls, 1st Round Leader, Winning Score, hole-in-one — and a "Player Round
Scores" coupon class on some events. A market that is not posted is skipped;
this module never synthesizes a line.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..normalization.manual_odds import american_to_decimal
from .config import LINES_DIR

BASE_URL = "https://sbapi.nj.sportsbook.fanduel.com/api/content-managed-page"
PARAMS = {"page": "CUSTOM", "customPageId": "pga",
          "_ak": "FhMFpcPWXMeyZxOx", "timezone": "America/New_York"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Origin": "https://sportsbook.fanduel.com",
           "Referer": "https://sportsbook.fanduel.com/",
           "Accept": "application/json"}
TIMEOUT = 30

_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Lowercase, punctuation-free, suffix-free key for matching to history."""
    n = _SUFFIX.sub("", str(name).strip())
    return re.sub(r"[^a-z]", "", n.lower())


@dataclass(frozen=True)
class RoundLine:
    event_id: str
    event_name: str
    market_id: str
    market_name: str
    player_name: str
    round_number: int
    line: float
    over_american: Optional[int]
    under_american: Optional[int]
    captured_at: str
    source: str = "fanduel"
    provenance: str = "api"


def _american(runner: dict) -> Optional[int]:
    odds = (runner.get("winRunnerOdds") or {}).get("americanOdds")
    if odds is None:
        disp = (runner.get("winRunnerOdds") or {}).get("americanDisplayOdds")
        odds = (disp or {}).get("americanOdds")
    return int(odds) if odds is not None else None


def parse_round_score_markets(payload: dict, captured_at: str) -> List[RoundLine]:
    """Extract per-player round-score O/U pairs ("... Round N ..." Over/Under).

    Matches the swept name variants: "Round 1 Score", "Player Name Round X
    Score", "Round 1 Strokes" (Fanatics), "Player Round Scores", "18-Hole
    Score". Never guesses: a market without an Over/Under runner pair and an
    explicit line number is skipped.
    """
    att = payload.get("attachments", {})
    events = att.get("events", {})
    markets = att.get("markets", {})
    out: List[RoundLine] = []
    for m in markets.values():
        name = str(m.get("marketName", ""))
        low = name.lower()
        if "round" not in low and "18-hole" not in low and "18 hole" not in low:
            continue
        if not any(k in low for k in ("score", "strokes")):
            continue
        rm = re.search(r"round\s*(\d)", name, re.I)
        rnd = int(rm.group(1)) if rm else 1
        runners = m.get("runners", [])
        if len(runners) != 2:
            continue
        # runner names look like "Over 68.5" / player carried by market name
        player = re.sub(r"\s*round\s*\d.*$", "", name, flags=re.I).strip()
        if not player or "score" in player.lower() or "stroke" in player.lower():
            m2 = re.search(r"(?:score|strokes)\s*[-:]?\s*(.+)$", name, re.I)
            player = (m2.group(1).strip() if m2 else player)
        sides = {}
        for r in runners:
            rn = str(r.get("runnerName", ""))
            american = _american(r)
            if american is None:
                break
            if rn.lower().startswith("over"):
                sides["over"] = american
            elif rn.lower().startswith("under"):
                sides["under"] = american
        if set(sides) != {"over", "under"}:
            continue
        line_m = re.search(r"(\d{2,3}(?:\.\d)?)", " ".join(
            str(r.get("runnerName", "")) for r in runners))
        if not line_m:
            continue
        ev = events.get(str(m.get("eventId")), {})
        out.append(RoundLine(
            event_id=str(m.get("eventId")), event_name=str(ev.get("name", "")),
            market_id=str(m.get("marketId")), market_name=name,
            player_name=player, round_number=rnd, line=float(line_m.group(1)),
            over_american=sides["over"], under_american=sides["under"],
            captured_at=captured_at))
    return out


def observed_line(player_name: str, round_number: int, line: float,
                  over_american: Optional[int], under_american: Optional[int],
                  market_name: str, event_id: str, event_name: str,
                  observer: str, observed_at: str,
                  source: str = "fanatics") -> RoundLine:
    """A human-transcribed book line (e.g. read in-app by Cole).

    Not a synthesis: the line must have been observed at a real book before
    the round started. Provenance is mandatory and travels into the ledger.
    Post-start observations are refused by the caller (see shadow.run).
    Either side may be None when only one price was recorded — the missing
    side is never filled in.
    """
    if over_american is None and under_american is None:
        raise ValueError("observed line needs at least one recorded price")
    return RoundLine(
        event_id=event_id, event_name=event_name,
        market_id=f"observed-{source}-{normalize_name(player_name)}"
                  f"-r{round_number}",
        market_name=market_name, player_name=player_name,
        round_number=round_number, line=float(line),
        over_american=(int(over_american) if over_american is not None
                       else None),
        under_american=(int(under_american) if under_american is not None
                        else None),
        captured_at=observed_at, source=f"{source}-observed",
        provenance=f"human-observed by {observer} at {observed_at}")


def fetch(capture: bool = True) -> List[RoundLine]:
    """Capture the live FanDuel golf coupon; returns only round-score O/U."""
    url = BASE_URL + "?" + urllib.parse.urlencode(PARAMS)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if capture:
        LINES_DIR.mkdir(parents=True, exist_ok=True)
        (LINES_DIR / f"fanduel_golf_{stamp[:10]}.json").write_text(
            json.dumps(payload)[:2_000_000], encoding="utf-8")
    lines = parse_round_score_markets(payload, stamp)
    print(f"fanduel golf coupon: {len(payload.get('attachments', {}).get('markets', {}))} "
          f"markets, {len(lines)} round-score O/U lines")
    return lines


def as_rows(lines: List[RoundLine]) -> List[dict]:
    return [asdict(ln) for ln in lines]
