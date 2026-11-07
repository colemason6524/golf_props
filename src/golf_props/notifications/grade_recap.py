"""Build, preview and deliver the public final-grade recap for one event.

The recap is a plain report of a verified grade: event, winner, coverage,
forecast-accuracy scores against the named structural baseline, and an explicit
statement of what priced performance is *not* available.  It never selects
positions, sizes stakes or claims an edge, because no official priced selection
population exists for golf.

Delivery is receipt-driven:

* a ``pending`` receipt is written before any network call (no optimistic
  "sent" marker), and ``sent`` is only recorded after a confirmed 2xx;
* receipts are keyed by event plus a grade fingerprint (graded membership,
  artifact hashes, event finality, price availability), so the same message is
  never posted twice and a re-run after a crash finds the undelivered grade;
* an ambiguous transport outcome (timeout / connection error after submit) is
  recorded as ``unknown_delivery`` for manual reconciliation, never retried
  automatically;
* grades recorded before ``GOLF_PROPS_RECAP_ACTIVATION_UTC`` are held as
  ``legacy_backfill_pending`` and only reachable through an explicit
  ``--send --allow-prior-grades`` operator action.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from golf_props.notifications.discord import PROHIBITED_WORDS

SCHEMA_VERSION = 1
RECEIPT_NAME = "grade_recap_receipt.json"
PREVIEW_JSON_NAME = "grade_recap_preview.json"
PREVIEW_MD_NAME = "grade_recap_preview.md"

ACTIVATION_ENV = "GOLF_PROPS_RECAP_ACTIVATION_UTC"
ACTIVATION_STATE_NAME = "grade_recap_activation.json"
ACTIVATION_STATE_SCHEMA_VERSION = 1
WEBHOOK_ENV = "GOLF_PROPS_DISCORD_WEBHOOK_URL"
MAX_SEND_ATTEMPTS = 3
READBACK_TIMEOUT_SECONDS = 20
EMBED_FIELD_LIMIT = 1024

DEMO_LABEL = "End-to-end verification demo \u2014 archived final grade"
# The single event Cole explicitly authorised for one public demo message.
DEMO_AUTHORIZED_EVENTS = {
    "butterfield_bermuda_championship_2026": "Butterfield Bermuda Championship",
}

FOOTER_TEXT = "forecast only | private paper research | prices omitted"
PRICED_UNAVAILABLE = (
    "Priced ROI unavailable: no pre-event prices and official priced selection "
    "list preserved"
)

STATUS_LEGACY_HOLD = "legacy_backfill_pending"
STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown_delivery"
STATUS_RECONCILE = "manual_reconciliation"

GRADED_TARGETS = ("top20", "top10", "top5", "winner")
TARGET_LABELS = {"top20": "Top 20", "top10": "Top 10", "top5": "Top 5", "winner": "Winner"}

# The results page prints the real competitive window (e.g. "Oct 22-25, 2026"),
# which is authoritative for the recap: the CBS schedule feed can be a day off.
# The range is read from the leaderboard's own date-range HUD only.  A global
# scan would happily return a navigation/JSON-LD date from an unrelated page
# (the 2026-01-08..11 case), so the element is the evidence boundary.
PAGE_DATE_RANGE_RE = re.compile(
    r"\b([A-Z][a-z]{2})\.? (\d{1,2})\s*[-\u2013]\s*(?:([A-Z][a-z]{2})\.? )?(\d{1,2}), (\d{4})"
)
PAGE_HUD_DATE_RANGE_RE = re.compile(
    r'class="[^"]*GolfLeaderboard-hudDateRange[^"]*"[^>]*>(.*?)</div>', re.S
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Identity of the CBS leaderboard a grade was computed from, as recorded in the
# grading manifest: content hash of the exact page plus its source URL.
CBS_RESULTS_URL_RE = re.compile(r"/leaderboard/pga-tour/(\d{5,})/([^/?#]+)/?")
CBS_EVENT_ID_RE = re.compile(r"(?<!\d)(\d{6,})(?!\d)")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class GradeRecapError(ValueError):
    """Raised when a recap cannot be built or delivered safely."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GradeRecapError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise GradeRecapError(f"expected JSON object: {path}")
    return value


def _read_metrics(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise GradeRecapError(f"missing grading metrics: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitized_url(value: str) -> str:
    """Drop query strings/fragments: URLs may carry tokens."""
    try:
        parts = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if not parts.scheme:
        return str(value or "")
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def activation_from_env() -> Optional[str]:
    return os.environ.get(ACTIVATION_ENV) or None


# --------------------------------------------------------------------------
# durable activation state (no service-definition change)
# --------------------------------------------------------------------------


class ActivationStateError(ValueError):
    """Raised when the durable activation state cannot be read or written safely."""


def default_weekly_dir() -> Path:
    from golf_props.config import PROJECT_ROOT

    return PROJECT_ROOT / "data" / "interim" / "weekly"


def activation_state_path(weekly_dir: Optional[Path] = None) -> Path:
    base = Path(weekly_dir) if weekly_dir else default_weekly_dir()
    return base / ACTIVATION_STATE_NAME


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_activation_state(path: Optional[Path] = None) -> dict[str, Any]:
    """Read the durable activation record without ever writing to it."""
    path = Path(path) if path is not None else activation_state_path()
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
            "activation_utc": None,
            "reason": "recap activation state not initialized",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "corrupt",
            "path": str(path),
            "activation_utc": None,
            "reason": "recap activation state is not readable JSON",
        }
    if not isinstance(data, dict):
        return {
            "status": "corrupt",
            "path": str(path),
            "activation_utc": None,
            "reason": "recap activation state is not a JSON object",
        }
    activation = str(data.get("activation_utc") or "")
    if _parse_iso(activation) is None:
        return {
            "status": "corrupt",
            "path": str(path),
            "activation_utc": None,
            "reason": "recap activation state has no valid activation_utc",
        }
    return {
        "status": "valid",
        "path": str(path),
        "activation_utc": activation,
        "initialized_at_utc": data.get("initialized_at_utc"),
        "initialized_by": data.get("initialized_by"),
        "source": data.get("source"),
        "reason": "",
    }


def initialize_activation_state(
    path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
    initialized_by: str = "cli:init-grade-recap-activation",
    notes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Create the activation record exactly once; repeat calls never move it.

    An existing valid record is returned untouched.  A corrupt record is never
    overwritten: activation is a threshold that historical delivery decisions
    depend on, so it needs an explicit human fix, not a silent reset.
    """
    path = Path(path) if path is not None else activation_state_path()
    current = load_activation_state(path)
    if current["status"] == "valid":
        return {**current, "result": "unchanged"}
    if current["status"] == "corrupt":
        raise ActivationStateError(
            f"refusing to overwrite unreadable activation state: {path}"
        )
    moment = now or _utc_now()
    record = {
        "schema_version": ACTIVATION_STATE_SCHEMA_VERSION,
        "activation_utc": _iso(moment),
        "initialized_at_utc": _iso(moment),
        "initialized_by": initialized_by,
        "source": "cli_initialization",
        "notes": list(notes or []),
    }
    _atomic_write_json(path, record)
    return {"status": "valid", "path": str(path), "result": "initialized", **record}


def resolve_activation(weekly_dir: Optional[Path] = None) -> dict[str, Any]:
    """Durable state wins; the old env var stays as a compatibility fallback."""
    path = activation_state_path(weekly_dir)
    state = load_activation_state(path)
    if state["status"] == "valid":
        return {
            "source": "durable_state",
            "state_status": "valid",
            "activation_utc": state["activation_utc"],
            "path": str(path),
            "reason": "",
        }
    if state["status"] == "missing":
        env = activation_from_env()
        if env:
            return {
                "source": "env_compat",
                "state_status": "missing",
                "activation_utc": env,
                "path": str(path),
                "reason": "durable state missing; legacy env fallback",
            }
        return {
            "source": "uninitialized",
            "state_status": "missing",
            "activation_utc": None,
            "path": str(path),
            "reason": state["reason"],
        }
    return {
        "source": "corrupt_state",
        "state_status": "corrupt",
        "activation_utc": None,
        "path": str(path),
        "reason": state["reason"],
    }


def assert_house_language(payload: Any) -> None:
    """Fail closed if a payload would use recommendation/staking wording."""
    text = json.dumps(payload).casefold()
    for word in PROHIBITED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            raise GradeRecapError(f"recap payload contains prohibited wording: {word}")


# --------------------------------------------------------------------------
# price availability
# --------------------------------------------------------------------------


def _event_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def assess_price_availability(
    event_name: str, archive_dir: Optional[Path] = None
) -> dict[str, Any]:
    """State honestly whether a priced record can be computed.

    Golf has no official priced selection or settlement contract, so ROI is
    unavailable by definition; archived odds can only ever describe collector
    coverage.  The result is descriptive and never a synthetic record.
    """
    if archive_dir is None:
        from golf_props.config import PROJECT_ROOT

        archive_dir = PROJECT_ROOT / "data/raw/odds_snapshots/archive"
    target = _event_key(event_name)
    snapshots: list[Path] = []
    matched = 0
    pre_start = 0
    market_counts: dict[str, int] = {}
    from golf_props.config import PROJECT_ROOT
    from golf_props.odds.board_prices import (
        load_event_aliases,
        normalize_key,
        resolve_quote_pre_start,
    )
    from golf_props.odds.bovada import resolve_competitive_start

    provider_names: set[str] = set()
    aliases = load_event_aliases(PROJECT_ROOT / "config" / "odds_event_aliases.csv")
    for (_, provider, _season), rows in aliases.items():
        for row in rows:
            canonical_name = normalize_key(row.get("canonical_event_name"))
            canonical_key = normalize_key(row.get("canonical_event_key"))
            if canonical_name == normalize_key(event_name) or (
                canonical_key and canonical_key.startswith(target)
            ):
                provider_names.add(provider)
    weekly_dir = PROJECT_ROOT / "data" / "interim" / "weekly"
    if archive_dir.exists():
        snapshots = sorted(archive_dir.glob("*.json"))
        for snapshot in snapshots:
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            raw_names = list(data.get("event_names", []) or [])
            names = {normalize_key(name) for name in raw_names}
            matched_provider = next(
                (
                    name
                    for name in raw_names
                    if normalize_key(name) in provider_names
                    or normalize_key(name) == target
                ),
                "",
            )
            if not (target in names or matched_provider):
                continue
            matched += 1
            resolved = None
            competitive_start = (data.get("competitive_start") or {}).get(
                matched_provider or event_name
            )
            if isinstance(competitive_start, dict):
                resolved, _ = resolve_quote_pre_start(
                    str(data.get("captured_at_utc") or ""), competitive_start
                )
            if resolved is None:
                control = resolve_competitive_start(weekly_dir, event_name)
                if control.get("state") in {"known_start", "date_only"}:
                    resolved, _ = resolve_quote_pre_start(
                        str(data.get("captured_at_utc") or ""), control
                    )
            if data.get("pre_start") is True or resolved is True:
                pre_start += 1
                snapshot_pre_start = True
            else:
                snapshot_pre_start = False
            if not snapshot_pre_start:
                continue
            for row in data.get("rows") or []:
                if _event_key(str(row.get("event_name") or "")) != _event_key(
                    matched_provider or event_name
                ):
                    continue
                market = str(row.get("market_type") or "").strip()
                if market:
                    market_counts[market] = market_counts.get(market, 0) + 1
    if market_counts:
        ordered = ", ".join(
            f"{market} ({count} rows)"
            for market, count in sorted(market_counts.items())
        )
        market_coverage = (
            "matched preserved captures contain " + ordered + "; prices are "
            "descriptive only, placement settlement/dead-heat is not modelled "
            "and no priced return is computed"
        )
    else:
        market_coverage = "no matched price rows in the preserved captures"
    reasons = ["no official priced selection or settlement contract defined"]
    if matched == 0:
        reasons.insert(0, "no archived price snapshot for this event")
    elif pre_start == 0:
        reasons.insert(
            0,
            "no matched snapshot carries a resolved pre-start flag",
        )
    if pre_start:
        statement = (
            "Priced ROI unavailable: pre-event prices are preserved, but no "
            "official priced selection list or settlement contract exists"
        )
    else:
        statement = PRICED_UNAVAILABLE
    return {
        "status": "unavailable",
        "roi": "unavailable",
        "selection_policy": "undefined",
        "archived_snapshots": len(snapshots),
        "matched_snapshots": matched,
        "pre_start_snapshots": pre_start,
        "market_counts": dict(sorted(market_counts.items())),
        "market_coverage": market_coverage,
        "reasons": reasons,
        "statement": statement,
    }


# --------------------------------------------------------------------------
# recap building
# --------------------------------------------------------------------------


def _winner_from_page(page_html: str) -> tuple[Optional[str], int]:
    from golf_props.normalization.cbs_results import parse_finish_position, parse_leaderboard_rows

    winners = []
    for row in parse_leaderboard_rows(page_html):
        if parse_finish_position(str(row["position"])) == 1:
            winners.append(str(row["player_name"]))
    return (winners[0] if len(winners) == 1 else None), len(winners)


def _window_from_match(match: "re.Match[str]") -> Optional[dict[str, str]]:
    month1, day1, month2, day2, year = match.groups()
    start_month = _MONTHS.get(month1.casefold())
    end_month = _MONTHS.get((month2 or month1).casefold())
    if not start_month or not end_month:
        return None
    try:
        start = date(int(year), start_month, int(day1))
        end = date(int(year), end_month, int(day2))
    except ValueError:
        return None
    if end < start:
        return None
    return {"start": start.isoformat(), "end": end.isoformat()}


def page_event_window(page_html: str) -> Optional[dict[str, str]]:
    """The window printed inside the leaderboard's own date-range HUD.

    Navigation/schedule fragments and JSON-LD dates elsewhere in the document
    are not evidence for this event: only the GolfLeaderboard HUD is read, and
    the page must print exactly one unambiguous window there.
    """
    windows = []
    for hud in PAGE_HUD_DATE_RANGE_RE.finditer(page_html or ""):
        match = PAGE_DATE_RANGE_RE.search(hud.group(1))
        if match:
            window = _window_from_match(match)
            if window:
                windows.append((window["start"], window["end"]))
    unique = sorted(set(windows))
    if len(unique) != 1:
        return None
    return {"start": unique[0][0], "end": unique[0][1]}


def window_check(
    window: Optional[dict[str, str]], expected: Optional[dict[str, str]]
) -> dict[str, Any]:
    """Compare a page window with the event_control competitive window.

    The CBS schedule feed can be a day early on the Sunday (Bermuda: feed end
    2026-10-24, real final round 2026-10-25), so a page end one day after the
    control end is accepted.  Anything further apart - a January window on an
    October event, for example - is a mismatch, not a date to publish.
    """
    result: dict[str, Any] = {"checked": False, "consistent": None, "reason": ""}
    if not window:
        result["reason"] = "page_has_no_unambiguous_hud_window"
        return result
    if not expected or not (expected.get("start") or expected.get("end")):
        result["reason"] = "event_control_window_not_recorded"
        return result
    result["checked"] = True
    problems = []
    start_text = str(expected.get("start") or "")
    end_text = str(expected.get("end") or "")
    try:
        page_start = date.fromisoformat(window["start"])
        page_end = date.fromisoformat(window["end"])
    except ValueError:
        result["reason"] = "page_window_unparsable"
        return result
    if start_text:
        try:
            if abs((page_start - date.fromisoformat(start_text)).days) > 1:
                problems.append(f"page start {window['start']} vs event control {start_text}")
        except ValueError:
            pass
    if end_text:
        try:
            control_end = date.fromisoformat(end_text)
            if not control_end <= page_end <= control_end + timedelta(days=1):
                problems.append(f"page end {window['end']} vs event control {end_text}")
        except ValueError:
            pass
    result["consistent"] = not problems
    result["reason"] = "; ".join(problems)
    return result


def event_dates_from_page(
    page_html: str, expected: Optional[dict[str, str]] = None
) -> Optional[dict[str, str]]:
    """Read the competitive window printed on the results page.

    Returns ``None`` when the page prints no unambiguous HUD range or when the
    printed window contradicts the event_control window, so the caller keeps
    the recorded dates rather than publishing an unrelated event's dates.
    """
    window = page_event_window(page_html)
    if window is None:
        return None
    if window_check(window, expected)["consistent"] is False:
        return None
    return {
        "start": window["start"],
        "end": window["end"],
        "source": "results_page",
    }



def grade_fingerprint(recap: dict[str, Any]) -> str:
    """Stable identity for one delivered message of one verified grade."""
    material = {
        "schema_version": SCHEMA_VERSION,
        "event_key": recap["event_key"],
        "event_name": recap["event_name"],
        "event_dates": {
            "start": recap["event_dates"].get("start", ""),
            "end": recap["event_dates"].get("end", ""),
            "source": recap["event_dates"].get("source", ""),
        },
        "graded_targets": recap["grading"]["graded_targets"],
        "coverage": {
            "forecast_players": recap["coverage"]["forecast_players"],
            "intersection_players": recap["coverage"]["intersection_players"],
            "graded_players": recap["coverage"]["graded_players"],
            "excluded_players": recap["coverage"]["excluded_players"],
            "forecast_players_without_results": recap["coverage"][
                "forecast_players_without_results"
            ],
        },
        "grading_input_sha256": recap["grading"]["input_sha256"],
        "grading_artifact_sha256": recap["grading"]["artifact_sha256"],
        "event_finality": {
            "state": recap["event_finality"]["state"],
            "reason": recap["event_finality"]["reason"],
            "results_page_sha256": recap["grading"]["input_sha256"].get(
                "results_page", ""
            ),
        },
        "price_availability": {
            "status": recap["price_availability"]["status"],
            "selection_policy": recap["price_availability"]["selection_policy"],
            "archived_snapshots": recap["price_availability"]["archived_snapshots"],
            "matched_snapshots": recap["price_availability"]["matched_snapshots"],
            "pre_start_snapshots": recap["price_availability"]["pre_start_snapshots"],
        },
    }
    # Only demo messages change identity; an ordinary recap keeps its previous
    # fingerprint so already-published evidence stays auditable.
    if recap.get("demo_label"):
        material["demo_label"] = recap["demo_label"]
    return _sha256_bytes(_canonical_json(material).encode("utf-8"))


def graded_results_identity(manifest: dict[str, Any]) -> dict[str, str]:
    """The graded results page identity recorded in the grading manifest."""
    source = manifest.get("results_source") or {}
    url = str(source.get("url") or "")
    recorded = str((manifest.get("input_sha256") or {}).get("results_page") or "")
    match = CBS_RESULTS_URL_RE.search(url)
    return {
        "expected_sha256": recorded if _SHA256_RE.fullmatch(recorded) else "",
        "source_url": url,
        "source_event_id": match.group(1) if match else "",
        "source_slug": match.group(2) if match else "",
    }


def results_page_evidence(
    page: Path,
    manifest: dict[str, Any],
    identity: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Prove (or refuse) that ``page`` is the bytes this grade was computed from."""
    identity = identity or graded_results_identity(manifest)
    evidence: dict[str, Any] = dict(identity)
    path = Path(page)
    evidence["path"] = str(path)
    evidence["sha256"] = ""
    evidence["filename_matches_source"] = None
    if not path.exists():
        evidence["verified"] = False
        evidence["reason"] = "results page file is missing"
        return evidence
    actual = _sha256_file(path)
    evidence["sha256"] = actual
    name_ids = set(CBS_EVENT_ID_RE.findall(path.name))
    filename_matches = True
    if identity["source_event_id"] and name_ids:
        filename_matches = identity["source_event_id"] in name_ids
    evidence["filename_matches_source"] = filename_matches
    if not identity["expected_sha256"]:
        evidence["verified"] = False
        evidence["reason"] = "grade manifest records no results page hash"
    elif actual != identity["expected_sha256"]:
        evidence["verified"] = False
        evidence["reason"] = "preserved page sha256 does not match the grade manifest"
    elif not filename_matches:
        evidence["verified"] = False
        evidence["reason"] = "preserved page filename identifies a different CBS event"
    else:
        evidence["verified"] = True
        evidence["reason"] = "page sha256 matches the grade manifest"
    return evidence


def resolve_graded_results_page(
    results_dir: Path, manifest: dict[str, Any]
) -> tuple[Optional[Path], dict[str, Any]]:
    """Pick the preserved page the grade was computed from - never a neighbour.

    Selection is by content hash from the grading manifest, so a directory that
    also holds a whole season of other events' leaderboards (the live Bermuda
    layout: 43 CBS pages, alphabetically first = the January Sentry capture)
    cannot leak an unrelated event into the recap.  Grades that predate the
    manifest hash fall back to the legacy ``*leaderboard*.html`` name, and are
    reported as unverified instead of silently trusted.
    """
    identity = graded_results_identity(manifest)
    evidence: dict[str, Any] = dict(identity)
    evidence.update({"path": "", "sha256": "", "verified": False})
    directory = Path(results_dir)
    if not directory.exists():
        evidence["reason"] = "results directory is missing"
        return None, evidence
    candidates = sorted(path for path in directory.glob("*.html") if path.is_file())
    expected = identity["expected_sha256"]
    if expected:
        matches = [path for path in candidates if _sha256_file(path) == expected]
    else:
        matches = [path for path in candidates if "leaderboard" in path.name.casefold()]
    if len(matches) > 1:
        evidence["reason"] = (
            f"ambiguous results page: {len(matches)} preserved files share the "
            "graded results hash"
        )
        evidence["candidates"] = [path.name for path in matches]
        return None, evidence
    if not matches:
        evidence["reason"] = (
            "no preserved page matches the graded results page sha256"
            if expected
            else "no preserved leaderboard page for a grade with no recorded hash"
        )
        return None, evidence
    page = matches[0]
    page_evidence = results_page_evidence(page, manifest, identity)
    evidence.update(page_evidence)
    if expected and not page_evidence["verified"]:
        return None, evidence
    return page, evidence


def recap_release_blockers(
    recap: dict[str, Any], *, require_results_evidence: bool = False
) -> list[str]:
    """Reasons this recap must not be published, in operator-readable order."""
    blockers: list[str] = []
    finality = recap.get("event_finality") or {}
    if str(finality.get("state") or "unknown") != "final":
        blockers.append(
            "event finality is "
            f"{finality.get('state') or 'unknown'} ({finality.get('reason') or 'no reason'})"
        )
    if int(recap.get("winner_rows") or 0) != 1 or not recap.get("winner"):
        blockers.append(
            "winner is not definitively identified "
            f"(position-1 rows: {int(recap.get('winner_rows') or 0)})"
        )
    dates = recap.get("event_dates") or {}
    if not dates.get("start") or not dates.get("end"):
        blockers.append("event window is not recorded")
    check = (recap.get("date_evidence") or {}).get("check") or {}
    if check.get("consistent") is False:
        blockers.append(
            "results page window contradicts event control: "
            + str(check.get("reason") or "unknown mismatch")
        )
    if require_results_evidence:
        evidence = recap.get("results_evidence") or {}
        if not evidence.get("verified"):
            blockers.append(
                "results page not verified against the grade manifest: "
                + str(evidence.get("reason") or "unverified")
            )
    return blockers


def demo_label_for(event_key: str) -> str:
    """The one authorised demo label, or a hard failure for any other event."""
    if event_key not in DEMO_AUTHORIZED_EVENTS:
        raise GradeRecapError(
            f"no demo publication is authorised for event {event_key!r}"
        )
    return DEMO_LABEL


def build_recap(
    *,
    event_key: str,
    event_name: str,
    grading_dir: Path,
    results_page: Optional[Path] = None,
    event_dates: Optional[dict[str, str]] = None,
    finality: Optional[dict[str, Any]] = None,
    odds_archive_dir: Optional[Path] = None,
    demo_label: Optional[str] = None,
    results_evidence: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the recap from the verified grading artifacts only."""
    if demo_label is not None and event_key not in DEMO_AUTHORIZED_EVENTS:
        raise GradeRecapError(
            f"no demo publication is authorised for event {event_key!r}"
        )
    manifest = _read_json(grading_dir / "grading_manifest.json")
    metrics = _read_metrics(grading_dir / "metrics.csv")
    if manifest.get("forecast_classification") != "prospective_forecast":
        raise GradeRecapError("recap requires a prospective forecast grade")
    if str(manifest.get("event_name", "")) and event_name != str(manifest["event_name"]):
        raise GradeRecapError(
            "recap event name does not match the graded manifest: "
            f"{event_name!r} != {manifest['event_name']!r}"
        )

    targets = []
    metrics_by_target = {row.get("target"): row for row in metrics}
    for target in GRADED_TARGETS:
        row = metrics_by_target.get(target)
        if row is None:
            raise GradeRecapError(f"grading metrics missing target: {target}")
        targets.append(
            {
                "target": target,
                "label": TARGET_LABELS[target],
                "graded_players": int(float(row["graded_players"])),
                "actual_count": int(float(row["actual_count"])),
                "expected_count": float(row["expected_count"]),
                "model_brier": float(row["model_brier"]),
                "baseline_brier": float(row["baseline_brier"]),
                "brier_improvement": float(row["brier_improvement"]),
                "rolling_model_brier": float(row["rolling_model_brier"]),
            }
        )

    winner: Optional[str] = None
    winner_rows = 0
    page_html = ""
    if results_page is not None and results_page.exists():
        page_html = results_page.read_text(encoding="utf-8")
        winner, winner_rows = _winner_from_page(page_html)
    if finality is None:
        finality = {"state": "final", "reason": "verified_before_recap"}

    # The results page dates the event itself; prefer that over the schedule
    # feed, which can be a day early (Bermuda: schedule 10-24 vs real 10-25).
    page_window = page_event_window(page_html)
    date_check = window_check(page_window, event_dates)
    effective_dates = event_dates_from_page(
        page_html, expected=event_dates
    ) or event_dates or {
        "start": "",
        "end": "",
        "source": "not recorded",
    }
    evidence = (
        dict(results_evidence)
        if results_evidence is not None
        else {"verified": False, "reason": "no results page evidence supplied"}
    )

    price_availability = assess_price_availability(event_name, odds_archive_dir)
    recap: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key,
        "event_name": event_name,
        "event_dates": effective_dates,
        "winner": winner,
        "winner_rows": winner_rows,
        "event_finality": {
            "state": finality.get("state", "unknown"),
            "reason": finality.get("reason", ""),
        },
        "results_evidence": evidence,
        "date_evidence": {
            "page_window": page_window,
            "event_control_window": {
                "start": str((event_dates or {}).get("start") or ""),
                "end": str((event_dates or {}).get("end") or ""),
                "source": str((event_dates or {}).get("source") or ""),
            },
            "check": date_check,
        },
        "coverage": {
            "forecast_players": int(manifest.get("forecast_players", 0)),
            "intersection_players": int(manifest.get("intersection_players", 0)),
            "graded_players": int(manifest.get("graded_players_per_target", 0)),
            "excluded_players": list(manifest.get("excluded_players", [])),
            "forecast_players_without_results": list(
                manifest.get("forecast_players_without_results", [])
            ),
            "ungraded_results_players": list(
                manifest.get("ungraded_results_players", [])
            ),
            "name_aliases_applied": len(manifest.get("name_aliases_applied", [])),
        },
        "targets": targets,
        "baseline": {
            "name": "structural baseline (target slots / graded players)",
            "rolling_reference": "rolling 365/8/20 recompute",
        },
        "research_cohort": (
            "prospective frozen forecast; single-event research cohort, not a "
            "calibration estimate"
        ),
        "price_availability": price_availability,
        "grading": {
            "created_at_utc": manifest.get("created_at_utc", ""),
            "graded_targets": list(manifest.get("graded_targets", [])),
            "input_sha256": dict(manifest.get("input_sha256", {})),
            "artifact_sha256": dict(manifest.get("artifact_sha256", {})),
            "manifest_sha256": _sha256_file(grading_dir / "grading_manifest.json"),
            "report_sha256": _sha256_file(grading_dir / "report.md")
            if (grading_dir / "report.md").exists()
            else "",
        },
    }
    if demo_label:
        recap["demo_label"] = demo_label
    recap["fingerprint"] = grade_fingerprint(recap)
    return recap


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def _date_label(recap: dict[str, Any]) -> str:
    dates = recap["event_dates"]
    start = str(dates.get("start") or "")
    end = str(dates.get("end") or "")
    if start and end and start != end:
        return f"{start}..{end}"
    return start or end or "dates not recorded"


def render_markdown(recap: dict[str, Any]) -> str:
    coverage = recap["coverage"]
    excluded = coverage["excluded_players"]
    missing = coverage["forecast_players_without_results"]
    demo = recap.get("demo_label")
    release_blockers = recap_release_blockers(recap)
    title = f"# {recap['event_name']} | Final Grade"
    if release_blockers:
        title = f"# {recap['event_name']} | Grade Recap (pending verification)"
    if demo:
        title += " (demo)"
    lines = [
        title,
        "",
    ]
    if release_blockers:
        lines.append(
            "- Recap status: **publication blocked** - " + "; ".join(release_blockers)
        )
    if demo:
        lines.append(
            f"- Delivery: **{demo}** \u2014 event window {_date_label(recap)}; "
            "archived real grade, not a new forecast"
        )
    lines.extend([
        f"- Event: `{_date_label(recap)}` (finality: {recap['event_finality']['state']})",
        f"- Winner: `{recap['winner'] or 'not recorded'}`",
        f"- Coverage: {coverage['graded_players']} of {coverage['forecast_players']} "
        f"forecast players graded ({coverage['intersection_players']} had a results row)",
        f"- Withdrawn / disqualified (excluded): {', '.join(excluded) if excluded else 'none'}",
        f"- No results row (excluded): {', '.join(missing) if missing else 'none'}",
        f"- Research cohort: {recap['research_cohort']}",
        f"- Baseline: {recap['baseline']['name']}",
        "",
        "| Target | Actual | Expected | Model Brier | Structural Brier | Improvement | Rolling Brier |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in recap["targets"]:
        lines.append(
            "| {label} | {actual_count} | {expected:.3f} | {model:.4f} | {base:.4f} | "
            "{improvement:+.4f} | {rolling:.4f} |".format(
                label=row["label"],
                actual_count=row["actual_count"],
                expected=row["expected_count"],
                model=row["model_brier"],
                base=row["baseline_brier"],
                improvement=row["brier_improvement"],
                rolling=row["rolling_model_brier"],
            )
        )
    lines.extend(
        [
            "",
            "`Improvement` is structural-baseline Brier minus model Brier (positive is better). "
            "Probability scores are accuracy measures, not returns.",
            "",
            f"**{recap['price_availability']['statement']}**",
            "",
            "Coverage caveat: " + recap["price_availability"]["market_coverage"] + ".",
            "",
            FOOTER_TEXT,
            "",
        ]
    )
    return "\n".join(lines)


def recap_embed(recap: dict[str, Any]) -> dict[str, Any]:
    coverage = recap["coverage"]
    excluded = coverage["excluded_players"]
    missing = coverage["forecast_players_without_results"]
    accuracy_lines = [
        "{label}: actual {actual} vs expected {expected:.2f} | Brier {model:.4f} vs "
        "structural {base:.4f} ({improvement:+.4f})".format(
            label=row["label"],
            actual=row["actual_count"],
            expected=row["expected_count"],
            model=row["model_brier"],
            base=row["baseline_brier"],
            improvement=row["brier_improvement"],
        )
        for row in recap["targets"]
    ]
    coverage_text = (
        f"{coverage['graded_players']} of {coverage['forecast_players']} forecast "
        f"players graded ({coverage['intersection_players']} had a results row)"
    )
    if excluded:
        coverage_text += f"; excluded: {', '.join(excluded)} (WD/DQ)"
    if missing:
        coverage_text += f"; no results row: {', '.join(missing)}"
    finality_state = str(recap["event_finality"].get("state") or "unknown")
    release_blockers = recap_release_blockers(recap)
    title_suffix = "Final Grade" if finality_state == "final" else "Grade Recap (pending)"
    if release_blockers:
        title_suffix = "Grade Recap (pending)"
    payload = {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": (
                    f"{recap['demo_label']} | {recap['event_name']} | {title_suffix}"
                    if recap.get("demo_label")
                    else f"{recap['event_name']} | {title_suffix}"
                )[:256],
                "description": (
                    f"{_date_label(recap)} | {finality_state} | "
                    f"winner {recap['winner'] or 'not recorded'}"
                ),
                "color": 0x2ECC71,
                "fields": [
                    *(
                        [
                            {
                                "name": "Status",
                                "value": (
                                    "Publication blocked: " + "; ".join(release_blockers)
                                )[:EMBED_FIELD_LIMIT],
                                "inline": False,
                            }
                        ]
                        if release_blockers
                        else []
                    ),
                    *(
                        [
                            {
                                "name": "Delivery",
                                "value": (
                                    f"{recap['demo_label']}; event window "
                                    f"{_date_label(recap)}; archived real grade, "
                                    "not a new forecast"
                                )[:EMBED_FIELD_LIMIT],
                                "inline": False,
                            }
                        ]
                        if recap.get("demo_label")
                        else []
                    ),
                    {"name": "Winner", "value": recap["winner"] or "not recorded", "inline": True},
                    {
                        "name": "Event",
                        "value": f"{_date_label(recap)} ({recap['event_finality']['state']})",
                        "inline": True,
                    },
                    {"name": "Coverage", "value": coverage_text[:1000], "inline": False},
                    {
                        "name": "Accuracy vs baseline",
                        "value": "\n".join(accuracy_lines)[:1000],
                        "inline": False,
                    },
                    {
                        "name": "Baseline",
                        "value": (
                            f"{recap['baseline']['name']}; rolling reference "
                            f"{recap['baseline']['rolling_reference']}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Research cohort",
                        "value": recap["research_cohort"],
                        "inline": False,
                    },
                    {
                        "name": "Priced record",
                        "value": recap["price_availability"]["statement"],
                        "inline": False,
                    },
                ],
                "footer": {"text": FOOTER_TEXT},
            }
        ],
    }
    assert_house_language(payload)
    return payload


def preview(recap: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    """Write offline preview artifacts; never sends."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = recap_embed(recap)
    json_path = output_dir / PREVIEW_JSON_NAME
    md_path = output_dir / PREVIEW_MD_NAME
    json_path.write_text(
        json.dumps(
            {"recap": recap, "payload": payload, "payload_sha256": _sha256_bytes(_canonical_json(payload).encode("utf-8"))},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(recap), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


# --------------------------------------------------------------------------
# delivery
# --------------------------------------------------------------------------


def default_transport(payload: dict[str, Any], webhook_url: str) -> dict[str, Any]:
    """POST one Discord payload; classify the outcome honestly.

    Returns ``status_code`` (None when no HTTP response arrived), ``message_id``
    from the response body when Discord provides one, and ``ambiguous`` when the
    outcome cannot be proven (timeout / connection error after submit) so the
    caller records an unknown delivery instead of retrying blindly.
    """
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "golf_props/0.1 grade-recap",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return {
            "status_code": int(exc.code),
            "message_id": None,
            "ambiguous": False,
            "error": f"HTTP {exc.code}",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status_code": None,
            "message_id": None,
            "ambiguous": True,
            "error": f"{type(exc).__name__}: ambiguous network outcome",
        }
    message_id = None
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            message_id = str(parsed.get("id") or "") or None
    except json.JSONDecodeError:
        message_id = None
    return {
        "status_code": status_code,
        "message_id": message_id,
        "ambiguous": False,
        "error": "" if 200 <= status_code < 300 else f"HTTP {status_code}",
    }


def _receipt_path(delivery_dir: Path) -> Path:
    return delivery_dir / RECEIPT_NAME


def _load_receipt(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _base_receipt(recap: dict[str, Any], payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_key": recap["event_key"],
        "event_name": recap["event_name"],
        "grade_fingerprint": recap["fingerprint"],
        "status": STATUS_PENDING,
        "created_at_utc": _iso(now),
        "updated_at_utc": _iso(now),
        "attempts": 0,
        "last_attempt_at_utc": None,
        "message_id": None,
        "http_status": None,
        "transport": "discord_webhook",
        "payload_sha256": _sha256_bytes(_canonical_json(payload).encode("utf-8")),
        "grading_manifest_sha256": recap["grading"]["manifest_sha256"],
        "event_finality": recap["event_finality"]["state"],
        "price_availability": recap["price_availability"]["status"],
        "notes": [],
    }


def preview_delivery_state(
    recap: dict[str, Any],
    delivery_dir: Path,
    *,
    require_results_evidence: bool = False,
) -> dict[str, Any]:
    """Say what a dry run would do, without touching the receipt or the network."""
    blockers = recap_release_blockers(
        recap, require_results_evidence=require_results_evidence
    )
    receipt = _load_receipt(_receipt_path(delivery_dir))
    if not receipt:
        if blockers:
            return {
                "state": "blocked_pending",
                "send": False,
                "reason": "; ".join(blockers),
                "blockers": blockers,
            }
        return {"state": "not_sent", "send": True, "reason": "no receipt yet"}
    status = receipt.get("status")
    if status == STATUS_SENT:
        if receipt.get("grade_fingerprint") == recap["fingerprint"]:
            return {
                "state": "already_sent",
                "send": False,
                "reason": "matching sent receipt; deduped, no second message",
                "message_id": receipt.get("message_id"),
            }
        return {
            "state": "sent_other_grade",
            "send": False,
            "reason": "a different grade was already delivered; manual reconciliation required",
            "message_id": receipt.get("message_id"),
        }
    if status in {STATUS_UNKNOWN, STATUS_RECONCILE}:
        return {
            "state": status,
            "send": False,
            "reason": "prior outcome is unproven; reconcile before any retry",
        }
    if blockers:
        return {
            "state": "blocked_pending",
            "send": False,
            "reason": "; ".join(blockers),
            "blockers": blockers,
        }
    return {
        "state": status or STATUS_PENDING,
        "send": True,
        "reason": "previous attempt did not deliver",
    }


def _default_readback(url: str) -> tuple[int, str]:
    request = Request(
        url,
        headers={"User-Agent": "golf_props/0.1 grade-recap-readback"},
        method="GET",
    )
    with urlopen(request, timeout=READBACK_TIMEOUT_SECONDS) as response:
        return int(response.status), response.read().decode("utf-8", "replace")


def readback_message(
    message_id: str,
    *,
    webhook_url: Optional[str] = None,
    fetch: Optional[Callable[[str], tuple[int, str]]] = None,
) -> dict[str, Any]:
    """Read back one delivered message; credentials and the URL never escape."""
    if not message_id:
        return {"status": "no_message_id"}
    base = webhook_url or os.environ.get(WEBHOOK_ENV)
    if not base:
        return {"status": "not_configured", "message_id": str(message_id)}
    url = f"{str(base).rstrip('/')}/messages/{quote(str(message_id), safe='')}"
    reader = fetch or _default_readback
    try:
        status_code, raw = reader(url)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            "status": "failed",
            "message_id": str(message_id),
            "error": type(exc).__name__,
        }
    try:
        body = json.loads(raw) if str(raw).strip() else {}
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    content = str(body.get("content") or "")
    embeds = body.get("embeds") or []
    return {
        "status": "ok" if 200 <= int(status_code) < 300 else "failed",
        "http_status": int(status_code),
        "message_id": str(body.get("id") or message_id),
        "channel_id": str(body.get("channel_id") or ""),
        "embeds": len(embeds) if isinstance(embeds, list) else 0,
        "content_length": len(content),
        "content_sha256": _sha256_bytes(content.encode("utf-8")),
    }


def deliver_recap(
    recap: dict[str, Any],
    delivery_dir: Path,
    *,
    webhook_url: Optional[str] = None,
    transport: Optional[Callable[[dict[str, Any], str], dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    allow_prior_grades: bool = False,
    weekly_dir: Optional[Path] = None,
    require_results_evidence: bool = False,
) -> dict[str, Any]:
    """Deliver one recap exactly as far as evidence allows; never raises on send."""
    now = now or _utc_now()
    payload = recap_embed(recap)
    receipt_path = _receipt_path(delivery_dir)
    receipt = _load_receipt(receipt_path)
    fingerprint = recap["fingerprint"]

    if receipt:
        status = receipt.get("status")
        if status == STATUS_SENT:
            if receipt.get("grade_fingerprint") == fingerprint:
                return {"status": "already_sent", "receipt": receipt}
            return {
                "status": STATUS_RECONCILE,
                "reason": "a different grade fingerprint was already delivered; "
                "do not re-post without manual reconciliation",
                "receipt": receipt,
            }
        if status in {STATUS_UNKNOWN, STATUS_RECONCILE}:
            return {
                "status": status,
                "reason": "previous attempt has an unproven outcome; manual reconciliation required",
                "receipt": receipt,
            }
        if receipt.get("grade_fingerprint") not in {None, fingerprint}:
            receipt = None

    # Never publish a recap whose event, winner or results page is not proven.
    # This runs before the activation check so a held grade cannot be forced out
    # with --allow-prior-grades / --demo while its metadata is unresolved.
    blockers = recap_release_blockers(
        recap, require_results_evidence=require_results_evidence
    )
    if blockers:
        raise GradeRecapError(
            "recap is not publishable: " + "; ".join(blockers)
        )

    grade_created = _parse_iso(recap["grading"]["created_at_utc"])
    activation_info = resolve_activation(weekly_dir)
    activation = _parse_iso(activation_info["activation_utc"])
    eligible = bool(
        activation is not None and grade_created is not None and grade_created >= activation
    )
    if not eligible and not allow_prior_grades:
        if (
            receipt
            and receipt.get("status") == STATUS_LEGACY_HOLD
            and receipt.get("grade_fingerprint") == fingerprint
        ):
            # Already held for the same grade: no rewrite, no send.
            return {"status": STATUS_LEGACY_HOLD, "receipt": receipt}
        held = _base_receipt(recap, payload, now)
        held["status"] = STATUS_LEGACY_HOLD
        held["activation"] = activation_info
        if activation is None:
            held["notes"] = [
                "recap activation is uninitialized or unreadable; every grade is held "
                f"({activation_info['source']}: {activation_info['reason']})"
            ]
        else:
            held["notes"] = [
                "grade predates recap activation; held for explicit one-event backfill"
            ]
        if not receipt or receipt.get("status") != STATUS_SENT:
            _write_receipt(receipt_path, held)
        return {"status": STATUS_LEGACY_HOLD, "receipt": held}

    attempts = int((receipt or {}).get("attempts") or 0)
    if attempts >= MAX_SEND_ATTEMPTS:
        reconcile = dict(receipt or _base_receipt(recap, payload, now))
        reconcile["status"] = STATUS_RECONCILE
        reconcile["updated_at_utc"] = _iso(now)
        reconcile.setdefault("notes", []).append(
            f"retry cap reached after {attempts} known failed attempts"
        )
        _write_receipt(receipt_path, reconcile)
        return {"status": STATUS_RECONCILE, "receipt": reconcile}

    url = webhook_url or os.environ.get(WEBHOOK_ENV)
    pending = dict(receipt or _base_receipt(recap, payload, now))
    pending.update(
        {
            "grade_fingerprint": fingerprint,
            "status": STATUS_PENDING,
            "updated_at_utc": _iso(now),
            "attempts": attempts,
            "event_finality": recap["event_finality"]["state"],
            "price_availability": recap["price_availability"]["status"],
            "activation": activation_info,
        }
    )
    if not url:
        # An outbox entry is kept so the next scheduled run retries; no marker
        # pretends the message was delivered.
        pending.setdefault("notes", []).append("webhook not configured")
        _write_receipt(receipt_path, pending)
        return {"status": "not_configured", "receipt": pending}

    pending["attempts"] = attempts + 1
    pending["last_attempt_at_utc"] = _iso(now)
    _write_receipt(receipt_path, pending)

    send = transport or default_transport
    try:
        outcome = send(payload, url)
    except Exception as exc:  # an unexpected transport failure is ambiguous
        outcome = {
            "status_code": None,
            "message_id": None,
            "ambiguous": True,
            "error": f"{type(exc).__name__}: ambiguous transport failure",
        }
    pending["http_status"] = outcome.get("status_code")
    if outcome.get("ambiguous"):
        pending["status"] = STATUS_UNKNOWN
        pending.setdefault("notes", []).append(
            "ambiguous send outcome; manual reconciliation required, no automatic retry"
        )
        _write_receipt(receipt_path, pending)
        return {"status": STATUS_UNKNOWN, "receipt": pending}
    code = outcome.get("status_code")
    if code is not None and 200 <= int(code) < 300:
        pending["status"] = STATUS_SENT
        pending["message_id"] = outcome.get("message_id")
        pending["updated_at_utc"] = _iso(now)
        _write_receipt(receipt_path, pending)
        return {"status": STATUS_SENT, "receipt": pending}

    pending["status"] = STATUS_FAILED
    pending["error"] = str(outcome.get("error") or "delivery failed")[:200]
    pending["updated_at_utc"] = _iso(now)
    if pending["attempts"] >= MAX_SEND_ATTEMPTS:
        pending["status"] = STATUS_RECONCILE
        pending.setdefault("notes", []).append(
            f"retry cap reached after {pending['attempts']} known failed attempts"
        )
    _write_receipt(receipt_path, pending)
    return {"status": pending["status"], "receipt": pending}


def ensure_grade_recap(
    *,
    event_key: str,
    event_name: str,
    delivery_dir: Path,
    grading_dir: Path,
    results_page: Optional[Path],
    event_dates: Optional[dict[str, str]] = None,
    finality: Optional[dict[str, Any]] = None,
    odds_archive_dir: Optional[Path] = None,
    transport: Optional[Callable[[dict[str, Any], str], dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    allow_prior_grades: bool = False,
    weekly_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Build and (receipt-permitting) deliver the recap for a graded event."""
    manifest = _read_json(grading_dir / "grading_manifest.json")
    if results_page is not None:
        evidence = results_page_evidence(results_page, manifest)
    else:
        evidence = {
            "verified": False,
            "reason": "no preserved results page recorded for this grade",
        }
    recap = build_recap(
        event_key=event_key,
        event_name=event_name,
        grading_dir=grading_dir,
        results_page=results_page,
        event_dates=event_dates,
        finality=finality,
        odds_archive_dir=odds_archive_dir,
        results_evidence=evidence,
    )
    delivery = deliver_recap(
        recap,
        delivery_dir,
        transport=transport,
        now=now,
        allow_prior_grades=allow_prior_grades,
        weekly_dir=weekly_dir,
        require_results_evidence=True,
    )
    return {"recap": recap, **delivery}
