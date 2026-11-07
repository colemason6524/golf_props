"""Bovada golf odds collector and parser."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from golf_props.odds.event_identity import event_name_key

from golf_props.normalization.manual_odds import (
    american_to_decimal,
    american_to_implied_probability,
)
from golf_props.schemas import ODDS_SNAPSHOTS_COLUMNS

BOVADA_BASE_URL = "https://www.bovada.lv"
DEFAULT_PGA_URL = f"{BOVADA_BASE_URL}/services/sports/event/coupon/events/A/description/golf/pga-tour"
SPORTSBOOK = "Bovada"
DEFAULT_TIMEOUT_SECONDS = 45
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
GENERIC_TOURNAMENT_LABELS = {
    "Cut Lines",
    "Finishes",
    "Finishes Parlayable",
    "Main Markets",
    "Miscellaneous",
    "Tournament Match-Ups",
}


class BovadaOddsError(ValueError):
    """Raised when Bovada golf odds cannot be collected or parsed."""


def stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part).strip().casefold() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def fetch_json(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise BovadaOddsError(f"failed to fetch Bovada odds from {url}: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BovadaOddsError(f"Bovada response was not valid JSON: {exc}") from exc


def parse_american(value: object) -> int:
    text = str(value).strip().upper()
    if text == "EVEN":
        return 100
    if not text:
        raise BovadaOddsError("empty American price")
    return int(text.replace("+", ""))


def normalize_market_type(event_description: str, market_description: str, outcome_description: str) -> Optional[str]:
    market = normalize_spaces(market_description).casefold()
    event = normalize_spaces(event_description).casefold()
    outcome = normalize_spaces(outcome_description).casefold()
    combined = f"{event} {market} {outcome}"

    if market == "winner":
        return "winner"
    if re.search(r"\btop\s*5\b", market) and "1st round" not in market:
        return "top5"
    if re.search(r"\btop\s*10\b", market) and "1st round" not in market:
        return "top10"
    if re.search(r"\btop\s*20\b", market) and "1st round" not in market:
        return "top20"
    if "make cut" in event and outcome.startswith("make"):
        return "make_cut"
    if "round" in combined and "score" in combined and outcome.startswith(("over", "under")):
        return "round_score_ou"
    if "1st round leader" in market:
        return "round_leader"
    return None


def normalize_spaces(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def infer_player_name(event_description: str, market_description: str, outcome_description: str) -> str:
    event = normalize_spaces(event_description)
    market = normalize_spaces(market_description)
    outcome = normalize_spaces(outcome_description)
    if "Make Cut / Miss Cut" in event:
        return normalize_spaces(event.split(" - Make Cut / Miss Cut", 1)[0].split("- Make Cut / Miss Cut", 1)[0])
    if outcome.casefold() in {"make", "make ", "miss"}:
        return market
    if outcome.casefold().startswith(("over", "under")):
        return infer_round_score_player(event, market)
    return outcome


def infer_round_score_player(event_description: str, market_description: str) -> str:
    for value in (market_description, event_description):
        cleaned = normalize_spaces(value)
        cleaned = re.sub(r"^\d+(?:st|nd|rd|th)\s+Round\s+Score\s*[-:]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+\d+(?:st|nd|rd|th)\s+Round\s+Score$", "", cleaned, flags=re.IGNORECASE)
        if cleaned and "round score" not in cleaned.casefold():
            return cleaned
    return normalize_spaces(market_description or event_description)


def extract_line(outcome: dict[str, Any], market_description: str, outcome_description: str) -> Optional[str]:
    for key in ("handicap", "line", "points"):
        value = outcome.get(key)
        if value not in (None, ""):
            return str(value)
    text = f"{market_description} {outcome_description}"
    match = re.search(r"\b(\d{2,3}(?:\.\d)?)\b", text)
    return match.group(1) if match else None


def source_url(event_link: str, fallback_url: str) -> str:
    if not event_link:
        return fallback_url
    if event_link.startswith("http"):
        return event_link
    return f"{BOVADA_BASE_URL}{event_link}"


def tournament_name(block: dict[str, Any], event: dict[str, Any]) -> str:
    tournament_items = [item for item in block.get("path", []) if item.get("type") == "TOURNAMENT"]
    for item in tournament_items:
        description = normalize_spaces(item.get("description"))
        if " - " in description:
            return description.split(" - ", 1)[0].strip()
    for item in block.get("path", []):
        description = normalize_spaces(item.get("description"))
        if item.get("type") == "TOURNAMENT" and description and description not in GENERIC_TOURNAMENT_LABELS:
            return description
    return str(event.get("description") or "")


def season_from_event(event: dict[str, Any]) -> str:
    start_time = event.get("startTime")
    if isinstance(start_time, (int, float)):
        return str(datetime.fromtimestamp(start_time / 1000, timezone.utc).year)
    return str(datetime.now(timezone.utc).year)


def parse_bovada_payload(
    payload: Any,
    captured_at_utc: Optional[str] = None,
    source_api_url: str = DEFAULT_PGA_URL,
    include_unmapped: bool = False,
) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise BovadaOddsError("Bovada payload should be a list")
    captured_at_utc = captured_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows: list[dict[str, object]] = []
    for block in payload:
        for event in block.get("events", []):
            event_name = tournament_name(block, event)
            season = season_from_event(event)
            event_link = event.get("link") or ""
            for display_group in event.get("displayGroups", []):
                for market in display_group.get("markets", []):
                    market_description = normalize_spaces(market.get("description") or market.get("descriptionKey"))
                    market_status = "open" if market.get("status") == "O" else str(market.get("status") or "")
                    for outcome in market.get("outcomes", []):
                        price = outcome.get("price") or {}
                        if "american" not in price:
                            continue
                        outcome_description = normalize_spaces(outcome.get("description"))
                        market_type = normalize_market_type(
                            str(event.get("description") or ""),
                            market_description,
                            outcome_description,
                        )
                        if market_type is None and not include_unmapped:
                            continue
                        price_american = parse_american(price["american"])
                        player_name = infer_player_name(
                            str(event.get("description") or ""),
                            market_description,
                            outcome_description,
                        )
                        rows.append(
                            {
                                "odds_id": stable_id(
                                    "odds",
                                    SPORTSBOOK,
                                    event.get("id"),
                                    market.get("id"),
                                    outcome.get("id"),
                                    price.get("id"),
                                    captured_at_utc,
                                ),
                                # Canonical join keys stay blank when no
                                # canonical mapping exists; the provider ids
                                # below are the honest, unambiguous provenance.
                                "event_id": "",
                                "event_name": event_name,
                                "season": season,
                                "player_id": "",
                                "player_name": player_name,
                                "sportsbook": SPORTSBOOK,
                                "market_type": market_type or "unmapped",
                                "market_name": market_description,
                                "selection_name": outcome_description,
                                "line": extract_line(outcome, market_description, outcome_description) or "",
                                "price_american": price_american,
                                "price_decimal": american_to_decimal(price_american),
                                "implied_probability": american_to_implied_probability(price_american),
                                "captured_at_utc": captured_at_utc,
                                "source_url": source_url(event_link, source_api_url),
                                "market_status": market_status,
                                "is_closing_candidate": False,
                                # Provenance-only keys.  They are ignored by
                                # the canonical CSV writer so the latest
                                # consumer contract is unchanged.
                                "provider_event_id": str(event.get("id") or ""),
                                "provider_market_id": str(market.get("id") or ""),
                                "provider_outcome_id": str(outcome.get("id") or ""),
                                "provider_price_id": str(price.get("id") or ""),
                                "lookup_status": (
                                    "provider_ids_present; canonical_event_and_player_unmapped"
                                    if player_name
                                    else "provider_ids_present; player_name_unresolved"
                                ),
                            }
                        )
    return rows


def write_odds_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ODDS_SNAPSHOTS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_raw_payload(payload: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_summary(rows: list[dict[str, object]], output_path: Path, source_api_url: str) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["market_type"])] = counts.get(str(row["market_type"]), 0) + 1
    lines = [
        "# Bovada Golf Odds Collection",
        "",
        f"Source API: {source_api_url}",
        f"Rows parsed: {len(rows)}",
        "",
        "| Market Type | Rows |",
        "|---|---:|",
    ]
    for market_type, count in sorted(counts.items()):
        lines.append(f"| {market_type} | {count} |")
    lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Immutable timestamped snapshots
# --------------------------------------------------------------------------
#
# The collector has always overwritten one "latest" CSV/JSON pair, which loses
# every earlier capture.  Snapshots below are additive: same collector call,
# same free endpoint, same latest-path contract, plus one immutable
# ``bovada_golf_<UTC stamp>.json`` (+ parsed CSV) per capture.

SNAPSHOT_SCHEMA_VERSION = 1


def snapshot_stamp(captured_at_utc: str) -> str:
    text = str(captured_at_utc).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BovadaOddsError(f"invalid capture timestamp: {captured_at_utc}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _match_key(value: object) -> str:
    """Formatting-only event key; initialism matches require corroboration."""
    return event_name_key(value)


def resolve_competitive_start(weekly_dir: Path, event_name: str) -> dict[str, object]:
    """Look up existing competitive-start evidence for one event.

    Only already-persisted ``event_control.json`` evidence is used.  A date-only
    ``competitive_start_date`` cannot prove an intraday ordering, so it is
    reported as ``date_only`` rather than assumed to allow ``pre_start``.
    """
    target = _match_key(event_name)
    if not weekly_dir.exists():
        return {"state": "unknown", "source": "weekly_dir_missing"}
    for control_path in sorted(weekly_dir.glob("*/event_control.json")):
        try:
            data = json.loads(control_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _match_key(data.get("event_name")) != target:
            continue
        tee_source = data.get("tee_time_source")
        # A ``first_tee_at_utc`` copied from the official start date is a
        # date-derived fallback, not proof of an exact competitive start.
        if (
            data.get("first_tee_at_utc")
            and isinstance(tee_source, dict)
            and tee_source.get("earliest_tee_at_utc")
        ):
            return {
                "state": "known_start",
                "start_at_utc": str(data["first_tee_at_utc"]),
                "competitive_start_date": data.get("competitive_start_date") or "",
                "event_key": data.get("event_key") or control_path.parent.name,
                "source": "event_control.first_tee_at_utc+tee_time_evidence",
            }
        if data.get("competitive_start_date") or data.get("official_start_at_utc"):
            return {
                "state": "date_only",
                "start_at_utc": None,
                "competitive_start_date": str(
                    data.get("competitive_start_date")
                    or data.get("official_start_at_utc")
                    or ""
                ),
                "event_key": data.get("event_key") or control_path.parent.name,
                "source": (
                    "event_control.competitive_start_date"
                    if data.get("competitive_start_date")
                    else "event_control.official_start_at_utc"
                ),
            }
    return {"state": "unknown", "source": "no_matching_event_control"}


def resolve_pre_start(
    captured_at_utc: str, competitive_start: dict[str, object]
) -> tuple[Optional[bool], str]:
    """Tri-state ``pre_start``: true/false only with exact start evidence."""
    if competitive_start.get("state") != "known_start":
        return None, str(competitive_start.get("source") or "no_competitive_start_evidence")
    start = str(competitive_start.get("start_at_utc") or "")
    captured = str(captured_at_utc).replace("Z", "+00:00")
    try:
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
        captured_at = datetime.fromisoformat(captured)
    except ValueError:
        return None, "unparseable_timestamp"
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    return captured_at < start_at, "captured_before_first_tee" if captured_at < start_at else "captured_after_first_tee"


def write_snapshot(
    payload: Any,
    rows: list[dict[str, object]],
    archive_dir: Path,
    captured_at_utc: str,
    source_api_url: str = DEFAULT_PGA_URL,
    weekly_dir: Optional[Path] = None,
) -> dict[str, object]:
    """Write one immutable snapshot pair; never overwrite an existing capture."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = snapshot_stamp(captured_at_utc)
    json_path = archive_dir / f"bovada_golf_{stamp}.json"
    csv_path = archive_dir / f"bovada_golf_{stamp}.csv"
    if json_path.exists() or csv_path.exists():
        raise BovadaOddsError(
            f"snapshot already exists for capture {captured_at_utc}: {json_path.name}"
        )
    event_names = sorted({str(row["event_name"]) for row in rows if row.get("event_name")})
    market_counts: dict[str, int] = {}
    for row in rows:
        market_counts[str(row["market_type"])] = market_counts.get(str(row["market_type"]), 0) + 1
    windows = {}
    if weekly_dir is not None:
        windows = {
            name: resolve_competitive_start(weekly_dir, name) for name in event_names
        }
    pre_start: Optional[bool]
    basis: str
    if weekly_dir is None:
        pre_start, basis = None, "no_weekly_dir_supplied"
    elif len(windows) == 1:
        pre_start, basis = resolve_pre_start(captured_at_utc, next(iter(windows.values())))
    elif not windows:
        pre_start, basis = None, "no_event_name_in_payload"
    else:
        pre_start, basis = None, "multiple_events_in_snapshot"
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source": SPORTSBOOK,
        "source_api_url": source_api_url,
        "captured_at_utc": captured_at_utc,
        "event_names": event_names,
        "market_counts": market_counts,
        "row_count": len(rows),
        "pre_start": pre_start,
        "pre_start_basis": basis,
        "competitive_start": windows,
        "provider_id_fields": [
            "provider_event_id",
            "provider_market_id",
            "provider_outcome_id",
            "provider_price_id",
        ],
        "canonical_join_status": (
            "event_id and player_id are canonical keys; when blank, use the "
            "provider ids plus player_name (no invented ids)"
        ),
        "prices_are_public": False,
        "selection_policy": "undefined",
        "rows": rows,
        "raw_payload": payload,
    }
    json_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ODDS_SNAPSHOTS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return {
        "json_path": json_path,
        "csv_path": csv_path,
        "pre_start": pre_start,
        "pre_start_basis": basis,
    }


def collect_bovada_golf_odds(
    output: Path,
    raw_output: Optional[Path] = None,
    report_output: Optional[Path] = None,
    url: str = DEFAULT_PGA_URL,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    include_unmapped: bool = False,
    archive_dir: Optional[Path] = None,
    weekly_dir: Optional[Path] = None,
) -> dict[str, Any]:
    captured_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = fetch_json(url, timeout_seconds=timeout_seconds)
    if raw_output is not None:
        write_raw_payload(payload, raw_output)
    rows = parse_bovada_payload(
        payload,
        captured_at_utc=captured_at_utc,
        source_api_url=url,
        include_unmapped=include_unmapped,
    )
    write_odds_csv(rows, output)
    if report_output is not None:
        write_summary(rows, report_output, url)
    snapshot: Optional[dict[str, object]] = None
    if archive_dir is not None:
        snapshot = write_snapshot(
            payload,
            rows,
            archive_dir,
            captured_at_utc,
            source_api_url=url,
            weekly_dir=weekly_dir,
        )
    return {
        "output": output,
        "raw_output": raw_output,
        "report_output": report_output,
        "rows": rows,
        "captured_at_utc": captured_at_utc,
        "snapshot": snapshot,
    }
