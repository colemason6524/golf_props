"""Attach real sportsbook quotes to a forecast board, or attach nothing.

This module only *reads* an already-preserved Bovada capture (the immutable
archive snapshot or the collector's existing latest CSV).  It never calls the
collector, never performs a network request, never rewrites an odds file and
never turns a model probability into a price.

Joins are deliberately strict:

* an event is matched by exact normalised name or by one explicit, reviewed
  provider alias (``config/odds_event_aliases.csv``), or a full initialism
  expansion corroborated by the event date and >=80% field overlap (>=10 players);
* a player is matched by exact normalised name or by one explicit alias whose
  canonical player id is unique in the canonical players table;
* several provider events or several different quotes for the same board player
  are ambiguous and stay unpriced;
* a quote is only ever presented as a pre-event price when the capture is
  provably before the competitive start.  A known exact start is compared as an
  instant; a date-only start proves pre-start only when the capture's UTC date
  is strictly earlier.  Same-day date-only captures stay unknown.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from golf_props.odds.event_identity import event_name_key, event_name_match

BOOK = "Bovada"
WINNER_MARKET = "winner"
WINNER_LABEL = "Winner"
MARKET_SPECS = (
    (WINNER_MARKET, WINNER_LABEL),
    ("top5", "Top 5"),
    ("top10", "Top 10"),
    ("top20", "Top 20"),
    ("make_cut", "Make cut"),
)
PLACEMENT_MARKETS = ("top5", "top10", "top20")
MARKET_LABELS = dict(MARKET_SPECS)

PLACEMENT_STATEMENT = (
    "Placement market prices unavailable: no top-5, top-10 or top-20 prices "
    "were collected; none are derived from model probabilities."
)
ROI_STATEMENT = (
    "Prospective ROI unavailable: no official priced selection or settlement "
    "contract exists for golf."
)
SETTLEMENT_SEMANTICS = {
    "grading_target": "finish_position_le_n_all_ties_count",
    "book_settlement": "not_defined_no_official_contract",
    "dead_heat": (
        "book-specific and not modelled; a tied finisher may be settled at a "
        "reduced stake even though the grading target counts every tie"
    ),
    "prospective_roi": "unavailable",
}

STATUS_PRICED = "priced"
STATUS_UNPRICED = "unpriced"


class BoardPricesError(ValueError):
    """Raised when the odds evidence cannot be read safely."""


def normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoardPricesError(f"invalid odds snapshot JSON: {path}") from exc


# --------------------------------------------------------------------------
# reviewed aliases
# --------------------------------------------------------------------------


def load_event_aliases(path: Optional[Path]) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    """Provider event name -> explicit canonical event, by season.

    An empty season in the CSV applies to every season.  Aliases are evidence,
    not heuristics: only rows that were deliberately reviewed belong here.
    """
    aliases: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    if not path or not Path(path).exists():
        return aliases
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            book = normalize_key(row.get("sportsbook"))
            provider = event_name_key(row.get("provider_event_name"))
            season = str(row.get("season") or "").strip()
            canonical_key = str(row.get("canonical_event_key") or "").strip()
            canonical_name = str(row.get("canonical_event_name") or "").strip()
            if not (book and provider and (canonical_key or canonical_name)):
                continue
            aliases.setdefault((book, provider, season), []).append(
                {
                    "canonical_event_key": canonical_key,
                    "canonical_event_name": canonical_name,
                    "provider_event_url": str(row.get("provider_event_url") or ""),
                    "provider_event_start_date": str(
                        row.get("provider_event_start_date") or ""
                    ),
                    "review_status": str(row.get("review_status") or ""),
                    "reviewed_by": str(row.get("reviewed_by") or ""),
                    "evidence": str(row.get("evidence") or ""),
                }
            )
    return aliases


def load_player_aliases(
    path: Optional[Path], players_table: Optional[Path]
) -> dict[str, str]:
    """Alias variant name -> canonical name, only when the mapping is unique."""
    if not path or not Path(path).exists() or not players_table or not Path(players_table).exists():
        return {}
    names_by_id: dict[str, str] = {}
    with Path(players_table).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            player_id = str(row.get("player_id") or "").strip()
            name = str(row.get("player_name") or "").strip()
            if player_id and name:
                names_by_id[player_id] = name
    aliases: dict[str, str] = {}
    seen: dict[str, set[str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            variant = normalize_key(row.get("variant_name"))
            canonical_id = str(row.get("canonical_player_id") or "").strip()
            canonical_name = names_by_id.get(canonical_id)
            if not variant or not canonical_name:
                continue
            seen.setdefault(variant, set()).add(normalize_key(canonical_name))
    for variant, targets in seen.items():
        if len(targets) == 1:
            aliases[variant] = next(iter(targets))
    return aliases


# --------------------------------------------------------------------------
# quote evidence
# --------------------------------------------------------------------------


def load_quote_source(path: Path) -> dict[str, Any]:
    """Read one snapshot JSON or the existing latest CSV; never mutate it."""
    path = Path(path)
    if not path.exists():
        raise BoardPricesError(f"missing odds evidence: {path}")
    digest = _sha256_file(path)
    if path.suffix.casefold() == ".json":
        data = _read_json(path)
        if not isinstance(data, dict):
            raise BoardPricesError(f"expected a snapshot object: {path}")
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise BoardPricesError(f"snapshot has no row list: {path}")
        return {
            "kind": "snapshot_json",
            "path": str(path),
            "sha256": digest,
            "captured_at_utc": str(data.get("captured_at_utc") or ""),
            "rows": rows,
            "event_names": list(data.get("event_names") or []),
            "competitive_start": dict(data.get("competitive_start") or {}),
            "source": str(data.get("source") or BOOK),
        }
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    stamps = {
        str(row.get("captured_at_utc") or "").strip()
        for row in rows
        if row.get("captured_at_utc")
    }
    return {
        "kind": "latest_csv",
        "path": str(path),
        "sha256": digest,
        "captured_at_utc": next(iter(stamps)) if len(stamps) == 1 else "",
        "rows": rows,
        "event_names": sorted(
            {str(row.get("event_name") or "") for row in rows if row.get("event_name")}
        ),
        "competitive_start": {},
        "source": BOOK,
    }


def resolve_quote_pre_start(
    captured_at_utc: str, competitive_start: dict[str, Any]
) -> tuple[Optional[bool], str]:
    """Tri-state pre-start, stricter for date-only evidence.

    ``known_start`` compares instants.  ``date_only`` returns ``True`` only when
    the capture's UTC date is strictly before the start date; a same-day capture
    stays ``None`` because the intraday order is unknown.
    """
    state = str(competitive_start.get("state") or "unknown")
    captured = _parse(captured_at_utc)
    if captured is None:
        return None, "unparseable_capture_timestamp"
    if state == "known_start":
        start = _parse(competitive_start.get("start_at_utc"))
        if start is None:
            return None, "unparseable_competitive_start"
        return (captured < start), (
            "captured_before_first_tee" if captured < start else "captured_after_first_tee"
        )
    if state == "date_only":
        raw = str(competitive_start.get("competitive_start_date") or "").strip()
        try:
            start_date = date.fromisoformat(raw[:10])
        except ValueError:
            return None, "unparseable_competitive_start_date"
        if captured.date() < start_date:
            return True, "captured_before_date_only_competitive_start"
        if captured.date() == start_date:
            return None, "same_day_date_only_competitive_start_unknown"
        return False, "captured_after_date_only_competitive_start"
    return None, "competitive_start_unknown"


def _as_float(value: object, field: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise BoardPricesError(f"quote has no usable {field}") from exc


def _parse(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _competitive_start_for(
    source: dict[str, Any], provider_event_name: str, board_event_name: str,
    weekly_dir: Optional[Path],
) -> dict[str, Any]:
    starts = source.get("competitive_start") or {}
    for name in (provider_event_name, board_event_name):
        entry = starts.get(name)
        if (
            isinstance(entry, dict)
            and entry.get("state") in {"known_start", "date_only"}
            and (entry.get("start_at_utc") or entry.get("competitive_start_date"))
        ):
            return entry
    if weekly_dir is not None:
        from golf_props.odds.bovada import resolve_competitive_start

        resolved = resolve_competitive_start(Path(weekly_dir), board_event_name)
        if resolved.get("state") in {"known_start", "date_only"}:
            return resolved
        if provider_event_name and provider_event_name != board_event_name:
            return resolve_competitive_start(Path(weekly_dir), provider_event_name)
        return resolved
    return {"state": "unknown", "source": "no_event_control_evidence"}


# --------------------------------------------------------------------------
# joins
# --------------------------------------------------------------------------


def _event_match(
    *,
    board_event_name: str,
    board_event_key: str,
    provider_event_name: str,
    season: str,
    aliases: dict[tuple[str, str, str], list[dict[str, str]]],
) -> Optional[dict[str, str]]:
    board_key = event_name_key(board_event_name)
    provider_key = event_name_key(provider_event_name)
    if not provider_key:
        return None
    if provider_key == board_key:
        return {"match": "exact", "provider_event_name": provider_event_name}
    for key in ((normalize_key(BOOK), provider_key, season), (normalize_key(BOOK), provider_key, "")):
        entries = aliases.get(key, [])
        targets = {
            (str(alias.get("canonical_event_key") or ""), event_name_key(alias.get("canonical_event_name")))
            for alias in entries
        }
        if len(targets) > 1:
            return {"match": "ambiguous_alias", "provider_event_name": provider_event_name}
        for alias in entries:
            canonical_key = str(alias.get("canonical_event_key") or "")
            canonical_name = event_name_key(alias.get("canonical_event_name"))
            if canonical_key and board_event_key and canonical_key != board_event_key:
                continue
            if (board_event_key and canonical_key == board_event_key) or (
                canonical_name and canonical_name == board_key
            ):
                return {
                    "match": "alias",
                    "provider_event_name": provider_event_name,
                    **alias,
                }
    if event_name_match(board_event_name, provider_event_name) == "initialism":
        return {"match": "initialism", "provider_event_name": provider_event_name}
    return None


def _season_from_event_key(event_key: str, event_date: str) -> str:
    match = re.search(r"(20\d{2})$", str(event_key or ""))
    if match:
        return match.group(1)
    match = re.search(r"(20\d{2})", str(event_date or ""))
    return match.group(1) if match else ""


def _candidate_paths(
    archive_dir: Optional[Path], latest_csv: Optional[Path]
) -> list[Path]:
    candidates: list[Path] = []
    if archive_dir and Path(archive_dir).is_dir():
        candidates.extend(sorted(Path(archive_dir).glob("bovada_golf_*.json")))
    if latest_csv and Path(latest_csv).exists():
        candidates.append(Path(latest_csv))
    return candidates


def _quote_map(
    rows: list[dict[str, Any]], aliases: dict[str, str], market_type: str
) -> dict[str, list[dict[str, Any]]]:
    quotes: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("market_type") or "").casefold() != market_type:
            continue
        name_key = normalize_key(row.get("player_name"))
        if not name_key:
            continue
        quotes.setdefault(aliases.get(name_key, name_key), []).append(row)
    return quotes


def _readiness(
    status: str,
    reason: str,
    diagnostics: Optional[list[dict[str, Any]]] = None,
    observed: Optional[list[str]] = None,
    pre_start: Optional[bool] = None,
) -> dict[str, Any]:
    if status == STATUS_PRICED:
        return {"state": "ready", "reason": ""}
    if reason == "no_preserved_snapshot":
        return {"state": "capture_missing", "reason": reason}
    if reason == "ambiguous_event":
        return {"state": "event_identity_ambiguous", "reason": reason}
    if reason == "no_matching_event_snapshot":
        if diagnostics:
            return {"state": "event_identity_unresolved", "reason": reason}
        if observed:
            return {"state": "event_not_offered", "reason": reason}
        return {"state": "capture_empty", "reason": reason}
    if pre_start is not True:
        return {"state": "timing_unproven", "reason": reason}
    return {"state": "quote_unavailable", "reason": reason}


def _capture_age_hours(captured_at_utc: str) -> Optional[float]:
    captured = _parse(captured_at_utc)
    if captured is None:
        return None
    return round((datetime.now(timezone.utc) - captured).total_seconds() / 3600.0, 3)


def annotate_board_rows(
    *,
    event_name: str,
    event_key: str,
    event_date: str = "",
    rows: list[dict[str, Any]],
    odds_snapshot: Optional[Path] = None,
    odds_archive_dir: Optional[Path] = None,
    odds_latest_csv: Optional[Path] = None,
    weekly_dir: Optional[Path] = None,
    event_aliases_path: Optional[Path] = None,
    player_aliases_path: Optional[Path] = None,
    players_table: Optional[Path] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return board rows carrying ``price`` (or ``None``) plus an audit block."""
    annotated = [dict(row) for row in rows]
    for row in annotated:
        row["price"] = None
    season = _season_from_event_key(event_key, event_date)
    event_aliases = load_event_aliases(event_aliases_path)
    player_aliases = load_player_aliases(player_aliases_path, players_table)

    paths = [Path(odds_snapshot)] if odds_snapshot else _candidate_paths(
        odds_archive_dir, odds_latest_csv
    )
    loaded: list[dict[str, Any]] = []
    for path in paths:
        try:
            loaded.append(load_quote_source(path))
        except BoardPricesError:
            continue
    base = {
        "schema_version": 1,
        "sportsbook": BOOK,
        "market": WINNER_MARKET,
        "market_label": WINNER_LABEL,
        "market_types": [market for market, _ in MARKET_SPECS],
        "placement_market_prices": "unavailable",
        "placement_statement": PLACEMENT_STATEMENT,
        "settlement_semantics": dict(SETTLEMENT_SEMANTICS),
        "roi_statement": ROI_STATEMENT,
        "prospective_roi": "unavailable",
        "board_event_name": event_name,
        "board_event_key": event_key,
    }
    if not loaded:
        return annotated, {
            **base,
            "status": STATUS_UNPRICED,
            "reason": "no_preserved_snapshot",
            "statement": "No preserved sportsbook snapshot available; forecasts unpriced.",
            "priced_players": 0,
            "any_market_priced_players": 0,
            "unpriced_players": len(annotated),
            "unpriced_reasons": {"no_preserved_snapshot": len(annotated)},
            "market_coverage": {},
            "readiness": _readiness(STATUS_UNPRICED, "no_preserved_snapshot"),
        }

    matches: list[tuple[dict[str, Any], dict[str, str]]] = []
    identity_diagnostics: list[dict[str, Any]] = []
    for source in loaded:
        provider_names = sorted(
            {
                (str(row.get("event_name") or ""), str(row.get("season") or ""))
                for row in source["rows"]
                if row.get("event_name")
            }
        )
        for provider_name, row_season in provider_names:
            # Never join a capture from another season, even with the same name.
            if season and row_season and row_season != season:
                continue
            match = _event_match(
                board_event_name=event_name,
                board_event_key=event_key,
                provider_event_name=provider_name,
                season=season,
                aliases=event_aliases,
            )
            if match and match["match"] == "initialism":
                provider_rows = [
                    row for row in source["rows"]
                    if row.get("event_name") == provider_name
                    and (not season or not row.get("season") or str(row["season"]) == season)
                ]
                start = _competitive_start_for(source, provider_name, event_name, weekly_dir)
                start_date = str(start.get("competitive_start_date") or "")[:10]
                board_names = {
                    player_aliases.get(normalize_key(row.get("player_name")), normalize_key(row.get("player_name")))
                    for row in rows if normalize_key(row.get("player_name"))
                }
                quote_names = {
                    player_aliases.get(normalize_key(row.get("player_name")), normalize_key(row.get("player_name")))
                    for row in provider_rows if normalize_key(row.get("player_name"))
                }
                overlap = len(board_names & quote_names)
                corroborated = bool(
                    event_date and start_date == event_date
                    and overlap >= 10 and overlap >= 0.8 * len(board_names)
                )
                identity_diagnostics.append({
                    "provider_event_name": provider_name,
                    "candidate_match": "initialism",
                    "competitive_start_date": start_date,
                    "matched_field_players": overlap,
                    "field_players": len(board_names),
                    "accepted": corroborated,
                })
                if not corroborated:
                    continue
                match = {**match, "matched_field_players": str(overlap),
                         "competitive_start_date": start_date}
            if match and match["match"] == "ambiguous_alias":
                identity_diagnostics.append({"provider_event_name": provider_name,
                                             "candidate_match": "ambiguous_alias", "accepted": False})
                continue
            if match:
                matches.append((source, match))

    base["event_identity_diagnostics"] = identity_diagnostics
    base["observed_provider_events"] = sorted({
        str(row["event_name"]) for source in loaded for row in source["rows"]
        if row.get("event_name")
    })

    if not matches:
        return annotated, {
            **base,
            "status": STATUS_UNPRICED,
            "reason": "no_matching_event_snapshot",
            "statement": (
                "Preserved captures exist but no event identity passed matching; "
                "check provider names, aliases, season and date/field evidence. "
                "Forecasts remain unpriced. Provider events: "
                + ", ".join(base["observed_provider_events"])[:500]
            ),
            "priced_players": 0,
            "any_market_priced_players": 0,
            "unpriced_players": len(annotated),
            "unpriced_reasons": {"no_matching_event_snapshot": len(annotated)},
            "market_coverage": {},
            "readiness": _readiness(
                STATUS_UNPRICED,
                "no_matching_event_snapshot",
                identity_diagnostics,
                base["observed_provider_events"],
            ),
        }
    provider_event_names = {match["provider_event_name"] for _, match in matches}
    if len(provider_event_names) > 1:
        return annotated, {
            **base,
            "status": STATUS_UNPRICED,
            "reason": "ambiguous_event",
            "statement": (
                "More than one provider event name maps to this board; prices stay "
                "unattached until the event identity is resolved."
            ),
            "priced_players": 0,
            "any_market_priced_players": 0,
            "unpriced_players": len(annotated),
            "unpriced_reasons": {"ambiguous_event": len(annotated)},
            "market_coverage": {},
            "readiness": _readiness(STATUS_UNPRICED, "ambiguous_event"),
        }

    evaluated = []
    for source, match in matches:
        competitive_start = _competitive_start_for(
            source, match["provider_event_name"], event_name, weekly_dir
        )
        pre_start, basis = resolve_quote_pre_start(
            str(source.get("captured_at_utc") or ""), competitive_start
        )
        evaluated.append(
            {
                "source": source,
                "match": match,
                "competitive_start": competitive_start,
                "pre_start": pre_start,
                "basis": basis,
                "captured": _parse(source.get("captured_at_utc"))
                or datetime.min.replace(tzinfo=timezone.utc),
            }
        )
    # A provably pre-start capture wins over a later post-start one; otherwise
    # the latest capture is the one whose availability is reported.
    eligible = [item for item in evaluated if item["pre_start"] is True]
    chosen = max(eligible or evaluated, key=lambda item: item["captured"])
    source = chosen["source"]
    match = chosen["match"]
    competitive_start = chosen["competitive_start"]
    pre_start = chosen["pre_start"]
    pre_start_basis = chosen["basis"]
    provider_rows = [
        row
        for row in source["rows"]
        if str(row.get("event_name") or "") == match["provider_event_name"]
        and (not season or not row.get("season") or str(row.get("season")) == season)
    ]
    quotes_by_market = {
        market: _quote_map(provider_rows, player_aliases, market)
        for market, _ in MARKET_SPECS
    }
    market_coverage: dict[str, dict[str, Any]] = {
        market: {
            "market": market,
            "market_label": label,
            "priced_players": 0,
            "unpriced_players": 0,
            "unpriced_reasons": {},
        }
        for market, label in MARKET_SPECS
    }

    for row in annotated:
        key = normalize_key(row.get("player_name"))
        alias_key = player_aliases.get(key, key)
        row_prices: dict[str, Optional[dict[str, Any]]] = {
            market: None for market, _ in MARKET_SPECS
        }
        for market, label in MARKET_SPECS:
            coverage = market_coverage[market]
            candidates = quotes_by_market[market].get(alias_key, [])
            distinct_prices = {
                (str(item.get("price_american")), str(item.get("captured_at_utc")))
                for item in candidates
            }
            reason = ""
            if not candidates:
                reason = "no_quote_for_player"
            elif len(distinct_prices) > 1:
                reason = "ambiguous_player"
            elif pre_start is not True:
                reason = (
                    "captured_after_start" if pre_start is False
                    else "capture_time_unproven_pre_start"
                )
            if reason:
                coverage["unpriced_players"] += 1
                coverage["unpriced_reasons"][reason] = (
                    coverage["unpriced_reasons"].get(reason, 0) + 1
                )
                continue
            quote = candidates[0]
            row_prices[market] = {
                "sportsbook": str(quote.get("sportsbook") or BOOK),
                "market": market,
                "market_label": label,
                "market_name": str(quote.get("market_name") or label),
                "captured_at_utc": str(
                    quote.get("captured_at_utc") or source.get("captured_at_utc")
                ),
                "price_american": int(
                    _as_float(quote.get("price_american"), "price_american")
                ),
                "price_decimal": _as_float(quote.get("price_decimal"), "price_decimal"),
                "implied_probability": _as_float(
                    quote.get("implied_probability"), "implied_probability"
                ),
                "market_status": str(quote.get("market_status") or ""),
                "pre_start": True,
                "pre_start_basis": pre_start_basis,
                "pre_event_price": True,
                "prospective_roi_eligible": False,
                "settlement": "book_specific_not_modelled_no_roi",
                "provenance": {
                    "odds_id": str(quote.get("odds_id") or ""),
                    "provider_event_id": str(quote.get("provider_event_id") or ""),
                    "provider_market_id": str(quote.get("provider_market_id") or ""),
                    "provider_outcome_id": str(quote.get("provider_outcome_id") or ""),
                    "provider_price_id": str(quote.get("provider_price_id") or ""),
                    "source_url": str(quote.get("source_url") or ""),
                    "provider_event_name": match["provider_event_name"],
                    "event_match": match["match"],
                },
                "source": {
                    "kind": source["kind"],
                    "path": source["path"],
                    "sha256": source["sha256"],
                },
            }
            coverage["priced_players"] += 1
        row["prices"] = row_prices
        row["price"] = row_prices.get(WINNER_MARKET)

    winner_priced = market_coverage[WINNER_MARKET]["priced_players"]
    any_priced = sum(item["priced_players"] for item in market_coverage.values())
    placement_priced = sum(
        market_coverage[market]["priced_players"] for market in PLACEMENT_MARKETS
    )
    placement_statement = PLACEMENT_STATEMENT
    if placement_priced:
        placement_statement = (
            "Placement prices attached as descriptive references only: "
            + ", ".join(
                f"{MARKET_LABELS[market]} "
                f"{market_coverage[market]['priced_players']}"
                f"/{len(annotated)}"
                for market in PLACEMENT_MARKETS
            )
            + ". Settlement would follow book-specific dead-heat rules; no "
            "priced placement return or ROI is computed."
        )
    if any_priced:
        statement = (
            f"Real {BOOK} prices shown from one preserved capture: winner "
            f"{winner_priced}/{len(annotated)}"
            + (
                f", placement {placement_priced}/{len(annotated)}"
                if placement_priced
                else ""
            )
            + f", captured {source.get('captured_at_utc')} "
            f"(pre-start: {str(pre_start).lower()}). Model probabilities are not "
            "book prices; no ROI is computed."
        )
        status = STATUS_PRICED
        reason = ""
    else:
        status = STATUS_UNPRICED
        reason = "no_usable_quote"
        statement = (
            "Preserved sportsbook capture has no usable pre-start quote for this "
            "board; forecasts remain visible and unpriced."
        )
    odds_block = {
        **base,
        "status": status,
        "reason": reason,
        "statement": statement,
        "placement_statement": placement_statement,
        "placement_market_prices": (
            "attached" if placement_priced else "unavailable"
        ),
        "source": {
            "kind": source["kind"],
            "path": source["path"],
            "sha256": source["sha256"],
        },
        "capture_utc": str(source.get("captured_at_utc") or ""),
        "pre_start": pre_start,
        "pre_start_basis": pre_start_basis,
        "competitive_start": competitive_start,
        "event_identity": {
            "board_event_name": event_name,
            "board_event_key": event_key,
            "provider_event_name": match["provider_event_name"],
            "match": match["match"],
            "alias": {
                key: value
                for key, value in match.items()
                if key not in {"provider_event_name", "match"}
            }
            or None,
        },
        "priced_players": winner_priced,
        "any_market_priced_players": any_priced,
        "unpriced_players": len(annotated) - winner_priced,
        "unpriced_reasons": market_coverage[WINNER_MARKET]["unpriced_reasons"],
        "market_coverage": market_coverage,
        "capture_age_hours": _capture_age_hours(str(source.get("captured_at_utc") or "")),
        "readiness": _readiness(
            status,
            reason,
            identity_diagnostics,
            base["observed_provider_events"],
            pre_start,
        ),
        "usable_as_pre_event_price": pre_start is True,
    }
    return annotated, odds_block
