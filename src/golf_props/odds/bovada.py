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


def collect_bovada_golf_odds(
    output: Path,
    raw_output: Optional[Path] = None,
    report_output: Optional[Path] = None,
    url: str = DEFAULT_PGA_URL,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    include_unmapped: bool = False,
) -> dict[str, object]:
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
    return {
        "output": output,
        "raw_output": raw_output,
        "report_output": report_output,
        "rows": rows,
        "captured_at_utc": captured_at_utc,
    }
