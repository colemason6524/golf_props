"""ESPN golf withdrawal feed (fail-open).

The free ESPN golf leaderboard API (no key) reports a per-player status;
``WD`` (withdrawn) and ``DQ`` (disqualified) mean the player will not
complete the tournament. Combined with the PGA TOUR collector's
``entry_status="withdrawn"`` (pre-tournament withdrawals, already collected
but never filtered), this module drops both classes from the resolved
forecast field BEFORE the frozen simulation runs.

Fail-open: any fetch or parse failure keeps the field untouched and records
diagnostics. This module never blocks the forecast.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..normalization.player_identity import compact_name

ESPN_LEADERBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard"
    "?league={league}"
)

HTTP_TIMEOUT_SECONDS = 25
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; golf-props/1.0)"

# ESPN displayValue values (and status-type name fragments) that mean the
# player is out of the tournament.
OUT_STATUSES = {"WD", "DQ"}
OUT_TYPE_HINTS = ("WITHDRAW", "DISQUALIF")


def _espn_get(url: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        req = Request(url, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.load(resp), None
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError,
            OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _is_out(status: dict) -> Tuple[bool, str]:
    """Return (is_out, status_label) for an ESPN competitor status dict."""
    display = str(status.get("displayValue", "") or "").strip().upper()
    type_name = str((status.get("type") or {}).get("name", "") or "").upper()
    if display in OUT_STATUSES:
        return True, display
    if any(hint in type_name for hint in OUT_TYPE_HINTS):
        return True, display or type_name
    return False, display


def fetch_withdrawals(
    league: str = "pga",
) -> Tuple[List[Dict[str, Any]], dict]:
    """Fetch WD/DQ players from ESPN's golf leaderboard."""
    now = datetime.now(timezone.utc).isoformat()
    withdrawals: List[Dict[str, Any]] = []
    events_seen = 0
    players_seen = 0
    payload, err = _espn_get(ESPN_LEADERBOARD_URL.format(league=league))
    if err or not payload:
        diag = {
            "status": "failed",
            "league": league,
            "events_seen": 0,
            "players_seen": 0,
            "withdrawals": 0,
            "error": err or "empty payload",
            "retrieved_at_utc": now,
            "source": "espn-golf-leaderboard",
        }
        return [], diag
    for event in payload.get("events", []):
        events_seen += 1
        event_name = str(event.get("name", "") or "")
        for comp in event.get("competitions", []):
            for player in comp.get("competitors", []):
                players_seen += 1
                status = player.get("status", {}) or {}
                out, label = _is_out(status)
                if not out:
                    continue
                athlete = player.get("athlete", {}) or {}
                name = str(athlete.get("displayName", "") or "").strip()
                if not name:
                    continue
                withdrawals.append({
                    "player": name,
                    "key": compact_name(name),
                    "status": label,
                    "event_name": event_name,
                    "retrieved_at_utc": now,
                    "source": "espn-golf-leaderboard",
                })
    diag = {
        "status": "ok",
        "league": league,
        "events_seen": events_seen,
        "players_seen": players_seen,
        "withdrawals": len(withdrawals),
        "error": None,
        "retrieved_at_utc": now,
        "source": "espn-golf-leaderboard",
    }
    return withdrawals, diag


def filter_field_withdrawals(
    field_csv_path: Path,
    withdrawals: Optional[List[Dict[str, Any]]] = None,
    fetch: bool = True,
) -> Tuple[List[Dict[str, Any]], dict]:
    """Drop withdrawn players from a resolved field CSV (in place).

    Removes rows whose ``entry_status`` is "withdrawn" (PGA TOUR collector
    pre-tournament signal) and rows whose player matches an ESPN WD/DQ
    entry. Returns (removed_rows, diag). Fail-open: on any error the file
    is left untouched and ``removed_rows`` is empty.
    """
    now = datetime.now(timezone.utc).isoformat()
    path = Path(field_csv_path)
    removed: List[Dict[str, Any]] = []
    espn_diag: dict = {"status": "skipped", "withdrawals": 0}
    try:
        if withdrawals is None and fetch:
            withdrawals, espn_diag = fetch_withdrawals()
        elif withdrawals is None:
            withdrawals = []
        wd_keys = {str(w.get("key", "")) for w in withdrawals if w.get("key")}

        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        fieldnames = ["player_id", "player_name", "entry_status"]
        kept = []
        for row in rows:
            name = str(row.get("player_name", "") or "")
            entry_status = str(row.get("entry_status", "") or "").strip().lower()
            reason = ""
            if entry_status == "withdrawn":
                reason = "entry_status=withdrawn (pga tour field)"
            elif compact_name(name) in wd_keys and compact_name(name):
                reason = "espn status WD/DQ"
            if reason:
                removed.append({
                    "player_name": name,
                    "player_id": str(row.get("player_id", "") or ""),
                    "reason": reason,
                })
            else:
                kept.append(row)
        if removed:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                        extrasaction="ignore")
                writer.writeheader()
                writer.writerows(kept)
        diag = {
            "status": "ok",
            "field_path": str(path),
            "field_size_before": len(rows),
            "field_size_after": len(kept),
            "removed": len(removed),
            "removed_players": removed,
            "espn": espn_diag,
            "retrieved_at_utc": now,
        }
        return removed, diag
    except (OSError, csv.Error) as exc:
        diag = {
            "status": "failed",
            "field_path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
            "removed": 0,
            "removed_players": [],
            "espn": espn_diag,
            "retrieved_at_utc": now,
        }
        return [], diag
