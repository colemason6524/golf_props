"""Automated official PGA TOUR field and tee-time collector.

Fetches the official PGA TOUR field and tee-time pages, extracts structured
data from the embedded __NEXT_DATA__ JSON and server-rendered HTML, preserves
raw snapshots as evidence, and writes CSV payloads compatible with the existing
field/tee-time evidence ingestion pipeline.

This replaces the manual ``import-current-field-evidence`` and
``import-current-tee-time-evidence`` commands for normal automated operation.
Those commands remain available for research, recovery, and testing.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from golf_props.config import RAW_DIR
from golf_props.ingestion.cbs_results import fetch_page
from golf_props.ingestion.current_field import (
    FIELDS_ROOT,
    FINALITY_FINAL,
    SOURCE_KIND_OFFICIAL,
    FieldEvidence,
    sha256_file,
)
from golf_props.ingestion.tee_times import (
    TEE_TIMES_ROOT,
    TeeTimeEvidence,
    derive_earliest_tee_utc,
)

PGA_TOUR_BASE_URL = "https://www.pgatour.com"
PGA_TOUR_FIELD_PATH = "/tournaments/{year}/{slug}/{tournament_id}/field"
PGA_TOUR_TEE_TIMES_PATH = "/tournaments/{year}/{slug}/{tournament_id}/tee-times"
PGA_TOUR_SCHEDULE_URL = "https://www.pgatour.com/schedule"

REQUEST_TIMEOUT_SECONDS = 90


def lookup_tournament_id(
    event_name: str,
    season: int,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> Optional[tuple[str, str, str, str]]:
    """Look up the PGA TOUR tournament ID, URL slug, and official start date.

    Fetches the PGA TOUR schedule page, extracts tournament data from
    ``__NEXT_DATA__``, and matches by name.

    Returns ``(tournament_id, slug, display_date, timezone)`` or ``None`` if
    not found.  ``display_date`` is the raw display string from the schedule
    (e.g. ``"Sep 17 - 20, 2026"``) and ``timezone`` is the IANA timezone
    string from the tournament query (e.g. ``"America/New_York"``).
    """
    status_code, html = fetch_page(PGA_TOUR_SCHEDULE_URL, timeout_seconds=timeout_seconds)
    if status_code != 200:
        return None

    try:
        next_data = _extract_next_data(html)
    except PGATourCollectorError:
        return None

    page_props = next_data.get("props", {}).get("pageProps", {})
    queries = page_props.get("dehydratedState", {}).get("queries", [])

    # The schedule query contains tournament objects
    schedule_data = _find_query(queries, "schedule")
    if not schedule_data:
        # Try the first query which often contains the tournament list
        for q in queries:
            qdata = q.get("state", {}).get("data", {})
            if isinstance(qdata, list) and len(qdata) > 0:
                schedule_data = qdata
                break
            if isinstance(qdata, dict) and "tournaments" in qdata:
                schedule_data = qdata["tournaments"]
                break

    # If schedule_data is a dict with a "tournaments" key, extract the list
    if isinstance(schedule_data, dict) and "tournaments" in schedule_data:
        schedule_data = schedule_data["tournaments"]

    if not schedule_data:
        return None

    # Normalize event name for matching
    target_name = event_name.lower().strip()

    tournaments = schedule_data if isinstance(schedule_data, list) else []
    for t in tournaments:
        if not isinstance(t, dict):
            continue
        t_name = str(t.get("tournamentName", "") or t.get("name", "")).lower().strip()
        t_id = str(t.get("id", "") or t.get("tournamentId", "")).strip()
        t_year = t.get("season", t.get("year", ""))
        t_display_date = str(t.get("displayDate", "")).strip()
        t_timezone = str(t.get("timezone", "")).strip()

        # Check year matches
        try:
            if int(t_year) != season:
                continue
        except (ValueError, TypeError):
            continue

        if not t_id:
            continue

        # Match by name (exact or contained)
        if target_name == t_name or target_name in t_name or t_name in target_name:
            # Extract slug from tournament URL if available
            slug = _event_name_to_slug(t_name)
            # Also try to get timezone from tournament query if not in schedule
            if not t_timezone:
                t_timezone = _lookup_tournament_timezone(t_id, next_data, queries)
            return (t_id, slug, t_display_date, t_timezone)

    return None


def _lookup_tournament_timezone(
    tournament_id: str,
    next_data: dict[str, Any],
    queries: list[dict],
) -> str:
    """Look up the timezone for a specific tournament from the tournament query."""
    # Find the tournament query by ID
    for q in queries:
        qkey = q.get("queryKey", [])
        if qkey and qkey[0] == "tournament":
            qdata = q.get("state", {}).get("data", {})
            if isinstance(qdata, dict) and qdata.get("id") == tournament_id:
                tz = str(qdata.get("timezone", "")).strip()
                if tz:
                    return tz
    return ""


def parse_display_date_start(display_date: str, season: int) -> Optional[str]:
    """Parse the start date from a PGA TOUR display date string.

    Examples:
        ``"Sep 17 - 20, 2026"`` -> ``"2026-09-17"``
        ``"January 15 - 18, 2026"`` -> ``"2026-01-15"``
    """
    import re
    # Try to extract "Month DD" from the start of the string
    match = re.match(r"([A-Za-z]+)\s+(\d{1,2})", display_date)
    if not match:
        return None
    month_str, day_str = match.group(1), match.group(2)
    try:
        from datetime import datetime
        dt = datetime.strptime(f"{month_str} {day_str} {season}", "%B %d %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            from datetime import datetime
            dt = datetime.strptime(f"{month_str} {day_str} {season}", "%b %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None


class PGATourCollectorError(ValueError):
    """Raised when the automated PGA TOUR collector cannot proceed."""


@dataclass
class CollectedField:
    """Result of automated PGA TOUR field collection."""

    event_key: str
    event_name: str
    tournament_id: str
    url: str
    captured_at_utc: str
    raw_html_path: str
    raw_html_sha256: str
    players: list[dict[str, str]] = field(default_factory=list)
    field_size: int = 0
    alternates_size: int = 0
    withdrawn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "collector": "pga_tour_automated",
            "event_key": self.event_key,
            "event_name": self.event_name,
            "tournament_id": self.tournament_id,
            "url": self.url,
            "captured_at_utc": self.captured_at_utc,
            "raw_html_path": self.raw_html_path,
            "raw_html_sha256": self.raw_html_sha256,
            "parsed_players": len(self.players),
            "field_size": self.field_size,
            "alternates_size": self.alternates_size,
            "withdrawn_count": self.withdrawn_count,
        }


@dataclass
class CollectedTeeTimes:
    """Result of automated PGA TOUR tee-time collection."""

    event_key: str
    event_name: str
    tournament_id: str
    url: str
    captured_at_utc: str
    raw_html_path: str
    raw_html_sha256: str
    local_timezone: str
    rows: list[dict[str, str]] = field(default_factory=list)
    earliest_tee_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "collector": "pga_tour_automated",
            "event_key": self.event_key,
            "event_name": self.event_name,
            "tournament_id": self.tournament_id,
            "url": self.url,
            "captured_at_utc": self.captured_at_utc,
            "raw_html_path": self.raw_html_path,
            "raw_html_sha256": self.raw_html_sha256,
            "local_timezone": self.local_timezone,
            "derived_rows": len(self.rows),
            "earliest_tee_at_utc": self.earliest_tee_at_utc,
        }


def _event_name_to_slug(event_name: str) -> str:
    """Convert an event name to a PGA TOUR URL slug."""
    slug = event_name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _extract_next_data(html: str) -> dict[str, Any]:
    """Extract the __NEXT_DATA__ JSON from a PGA TOUR Next.js page."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise PGATourCollectorError("no __NEXT_DATA__ found in PGA TOUR page")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PGATourCollectorError(f"invalid __NEXT_DATA__ JSON: {exc}") from exc


def _find_query(queries: list[dict], key_prefix: str) -> Optional[dict]:
    """Find a React Query entry by its key prefix."""
    for q in queries:
        qkey = q.get("queryKey", [])
        if qkey and qkey[0] == key_prefix:
            return q.get("state", {}).get("data")
    return None


def _extract_field_from_next_data(next_data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract tournament ID, players, and alternates from __NEXT_DATA__.

    Returns (tournament_id, players_list, alternates_list).
    """
    page_props = next_data.get("props", {}).get("pageProps", {})
    queries = page_props.get("dehydratedState", {}).get("queries", [])

    # Try the dedicated 'field' query first (richest data)
    field_data = _find_query(queries, "field")
    if field_data and "players" in field_data:
        tournament_id = field_data.get("id", "")
        players = field_data.get("players", [])
        alternates = field_data.get("alternates", [])
        return tournament_id, players, alternates

    # Fallback: try 'tcotrPlayerStatus' query
    tcotr_data = _find_query(queries, "tcotrPlayerStatus")
    if tcotr_data and "players" in tcotr_data:
        tournament_id = tcotr_data.get("tournamentId", "")
        players = tcotr_data.get("players", [])
        return tournament_id, players, []

    # Fallback: try 'leaderboard' query
    lb_data = _find_query(queries, "leaderboard")
    if lb_data and "leaderboard" in lb_data:
        tournament_id = lb_data.get("tournamentId", "")
        players = lb_data.get("leaderboard", [])
        return tournament_id, players, []

    raise PGATourCollectorError("no field/player data found in __NEXT_DATA__")


def _parse_player(entry: dict[str, Any]) -> Optional[dict[str, str]]:
    """Parse a player entry from the PGA TOUR field query into our CSV format."""
    # Handle field query format
    if "firstName" in entry and "lastName" in entry:
        player_id = str(entry.get("id", "")).strip()
        first = str(entry.get("firstName", "")).strip()
        last = str(entry.get("lastName", "")).strip()
        display = str(entry.get("displayName", "")).strip()
        withdrawn = entry.get("withdrawn", False)
        amateur = entry.get("amateur", False)
        status = str(entry.get("status", "")).strip()

        name = display if display else f"{last}, {first}"
        if amateur:
            name = f"{name} (a)"

        entry_status = "confirmed"
        if withdrawn:
            entry_status = "withdrawn"
        elif status and status != "IN":
            entry_status = status.lower()

        return {
            "player_name": name,
            "player_id": player_id,
            "entry_status": entry_status,
        }

    # Handle tcotrPlayerStatus format
    if "playerName" in entry:
        player_id = str(entry.get("playerId", "")).strip()
        name = str(entry.get("playerName", "")).strip()
        return {
            "player_name": name,
            "player_id": player_id,
            "entry_status": "confirmed",
        }

    # Handle leaderboard format
    if "player" in entry:
        player_obj = entry["player"]
        player_id = str(player_obj.get("id", "")).strip()
        first = str(player_obj.get("firstName", "")).strip()
        last = str(player_obj.get("lastName", "")).strip()
        display = str(player_obj.get("displayName", "")).strip()
        name = display if display else f"{last}, {first}"
        return {
            "player_name": name,
            "player_id": player_id,
            "entry_status": "confirmed",
        }

    return None


def _parse_tee_times_from_html(html: str) -> list[dict[str, str]]:
    """Parse tee times from the server-rendered PGA TOUR tee-times page.

    The tee-times page renders data like:
        1:30 PM UTC | 1 | Tommy Fleetwood / Brian Harman | -
    or
        7:15 AM ET | 1 | Player1 / Player2 / Player3 | -

    We extract time, hole, and player names.
    """
    rows: list[dict[str, str]] = []

    # Match patterns like "1:30 PM UTC | 1 | ..." or "7:15 AM ET | 1 | ..."
    # The HTML renders these in a structured format
    # Look for time patterns in the text content
    time_pattern = re.compile(
        r"(\d{1,2}:\d{2}\s*(?:AM|PM)\s*UTC)\s*\|\s*(\d+)\s*\|\s*(.+?)(?:\s*\|\s*(?:Round\s+Complete|-|\w+))",
        re.IGNORECASE,
    )

    for match in time_pattern.finditer(html):
        time_str = match.group(1).strip()
        hole = match.group(2).strip()
        players_block = match.group(3).strip()

        # Split players by "/" or newline-based grouping
        # The HTML typically groups 2-3 players per tee time
        player_names = re.split(r"\s*/\s*", players_block)
        player_names = [p.strip() for p in player_names if p.strip()]

        for player_name in player_names:
            # Clean up player name (remove status markers)
            player_name = re.sub(r"\s*\|\s*.*$", "", player_name).strip()
            player_name = re.sub(r"\s*Round Complete\s*$", "", player_name).strip()
            if player_name:
                rows.append({
                    "player_name": player_name,
                    "local_tee_datetime": _convert_utc_time_to_local(time_str),
                    "starting_hole": hole,
                })

    return rows


def _convert_utc_time_to_local(utc_time_str: str) -> str:
    """Convert a UTC time string like '1:30 PM UTC' to local datetime string.

    Returns in ``%Y-%m-%d %H:%M`` format compatible with the tee-time CSV.
    Uses a placeholder date since only the time component matters for
    deriving the earliest tee in UTC.
    """
    # Parse "1:30 PM UTC" format
    utc_time_str = utc_time_str.replace("UTC", "").strip()
    try:
        dt = datetime.strptime(utc_time_str, "%I:%M %p")
        # Use a placeholder date; only time matters for earliest-tee derivation
        return dt.strftime("1900-01-01 %H:%M")
    except ValueError:
        return utc_time_str


def _save_raw_snapshot(
    raw_dir: Path,
    event_key: str,
    content_type: str,
    content: str,
    url: str,
    captured_at_utc: str,
    extra_manifest: Optional[dict[str, Any]] = None,
) -> tuple[Path, str]:
    """Save a raw HTML snapshot and return (path, sha256)."""
    evidence_dir = raw_dir / event_key / content_type / "snapshots"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    timestamp_slug = captured_at_utc.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    filename = f"{timestamp_slug}.html"
    payload_path = evidence_dir / filename
    payload_path.write_text(content, encoding="utf-8")

    digest = sha256_file(payload_path)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "collector": "pga_tour_automated",
        "content_type": content_type,
        "url": url,
        "captured_at_utc": captured_at_utc,
        "payload_path": str(payload_path),
        "payload_sha256": digest,
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    (evidence_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Also write a latest symlink-like pointer
    latest_dir = raw_dir / event_key / content_type / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return payload_path, digest


def collect_pga_tour_field(
    event_key: str,
    event_name: str,
    tournament_id: str,
    season: int,
    local_tz: str = "America/New_York",
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    raw_events_root: Path = FIELDS_ROOT,
) -> CollectedField:
    """Automatically fetch and parse the official PGA TOUR field page.

    Preserves the raw HTML snapshot and extracts structured player data
    from the embedded ``__NEXT_DATA__`` JSON. The result is compatible
    with the existing field evidence ingestion pipeline.
    """
    slug = _event_name_to_slug(event_name)
    url = f"{PGA_TOUR_BASE_URL}{PGA_TOUR_FIELD_PATH.format(year=season, slug=slug, tournament_id=tournament_id)}"
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    status_code, html = fetch_page(url, timeout_seconds=timeout_seconds)
    if status_code != 200:
        raise PGATourCollectorError(
            f"PGA TOUR field page returned status {status_code}: {url}"
        )

    next_data = _extract_next_data(html)
    tourney_id, players_data, alternates_data = _extract_field_from_next_data(next_data)

    if tourney_id and tourney_id != tournament_id:
        # Log mismatch but continue with the ID from the page
        pass

    players = []
    for entry in players_data:
        parsed = _parse_player(entry)
        if parsed:
            players.append(parsed)

    if not players:
        raise PGATourCollectorError(
            f"no players extracted from PGA TOUR field page for {event_name}"
        )

    alternates = []
    for entry in alternates_data:
        parsed = _parse_player(entry)
        if parsed:
            alternates.append(parsed)

    withdrawn_count = sum(1 for p in players if p["entry_status"] == "withdrawn")

    raw_path, raw_hash = _save_raw_snapshot(
        raw_events_root,
        event_key,
        "field",
        html,
        url,
        captured_at,
        extra_manifest={
            "tournament_id": tourney_id or tournament_id,
            "player_count": len(players),
            "alternate_count": len(alternates),
        },
    )

    return CollectedField(
        event_key=event_key,
        event_name=event_name,
        tournament_id=tourney_id or tournament_id,
        url=url,
        captured_at_utc=captured_at,
        raw_html_path=str(raw_path),
        raw_html_sha256=raw_hash,
        players=players,
        field_size=len(players),
        alternates_size=len(alternates),
        withdrawn_count=withdrawn_count,
    )


def collect_pga_tour_tee_times(
    event_key: str,
    event_name: str,
    tournament_id: str,
    season: int,
    local_tz: str = "America/New_York",
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    raw_events_root: Path = TEE_TIMES_ROOT,
) -> Optional[CollectedTeeTimes]:
    """Automatically fetch and parse the official PGA TOUR tee-times page.

    Preserves the raw HTML snapshot and extracts tee-time pairings from
    the server-rendered HTML. Returns ``None`` if tee times are not yet
    available (e.g., before pairings are published).
    """
    slug = _event_name_to_slug(event_name)
    url = f"{PGA_TOUR_BASE_URL}{PGA_TOUR_TEE_TIMES_PATH.format(year=season, slug=slug, tournament_id=tournament_id)}"
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    status_code, html = fetch_page(url, timeout_seconds=timeout_seconds)
    if status_code != 200:
        raise PGATourCollectorError(
            f"PGA TOUR tee-times page returned status {status_code}: {url}"
        )

    # Extract tournament ID from __NEXT_DATA__ if available
    try:
        next_data = _extract_next_data(html)
        _, _, _ = _extract_field_from_next_data(next_data)
        # Tee times page may have tournament ID in the data
        page_queries = next_data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        lb_data = _find_query(page_queries, "leaderboard")
        if lb_data:
            tournament_id = lb_data.get("tournamentId", tournament_id)
    except PGATourCollectorError:
        pass  # Tee-times page might not have __NEXT_DATA__ with field data

    tee_rows = _parse_tee_times_from_html(html)

    raw_path, raw_hash = _save_raw_snapshot(
        raw_events_root,
        event_key,
        "tee_times",
        html,
        url,
        captured_at,
        extra_manifest={
            "tournament_id": tournament_id,
            "parsed_rows": len(tee_rows),
        },
    )

    if not tee_rows:
        # Tee times not yet published or page structure changed
        return CollectedTeeTimes(
            event_key=event_key,
            event_name=event_name,
            tournament_id=tournament_id,
            url=url,
            captured_at_utc=captured_at,
            raw_html_path=str(raw_path),
            raw_html_sha256=raw_hash,
            local_timezone=local_tz,
            rows=[],
            earliest_tee_at_utc="",
        )

    earliest_utc, _ = derive_earliest_tee_utc(tee_rows, local_tz)

    return CollectedTeeTimes(
        event_key=event_key,
        event_name=event_name,
        tournament_id=tournament_id,
        url=url,
        captured_at_utc=captured_at,
        raw_html_path=str(raw_path),
        raw_html_sha256=raw_hash,
        local_timezone=local_tz,
        rows=tee_rows,
        earliest_tee_at_utc=earliest_utc,
    )


def write_field_csv(path: Path, players: list[dict[str, str]]) -> None:
    """Write a field CSV compatible with the existing evidence ingestion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["player_id", "player_name", "entry_status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in players:
            writer.writerow(
                {
                    "player_id": str(row.get("player_id") or "").strip(),
                    "player_name": str(row.get("player_name") or "").strip(),
                    "entry_status": str(row.get("entry_status") or "confirmed").strip(),
                }
            )


def write_tee_times_csv(
    path: Path,
    rows: list[dict[str, str]],
    earliest_tee_at_utc: str,
) -> None:
    """Write a tee-times CSV compatible with the existing evidence ingestion.

    Writes the simple CSV format expected by ``parse_tee_time_payload``:
    ``player_name,local_tee_datetime,starting_hole``.
    The ``earliest_tee_at_utc`` is stored in the source manifest, not in the CSV.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["player_name", "local_tee_datetime", "starting_hole"])
        for row in rows:
            writer.writerow(
                [
                    str(row.get("player_name") or ""),
                    str(row.get("local_tee_datetime") or ""),
                    str(row.get("starting_hole") or ""),
                ]
            )


def persist_field_evidence(
    collected: CollectedField,
    raw_events_root: Path = FIELDS_ROOT,
) -> FieldEvidence:
    """Persist the collected field as evidence compatible with the pipeline.

    Writes a field CSV into the ``latest`` evidence directory and creates
    a ``source_manifest.json`` that the existing ``load_latest_field_evidence``
    can read.
    """
    evidence_dir = raw_events_root / collected.event_key / "field" / "latest"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Write field CSV
    csv_path = evidence_dir / "field.csv"
    write_field_csv(csv_path, collected.players)

    # Write source manifest compatible with existing load_latest_field_evidence
    payload_sha256 = sha256_file(csv_path)
    manifest = {
        "schema_version": 1,
        "event_key": collected.event_key,
        "event_name": collected.event_name,
        "source_kind": SOURCE_KIND_OFFICIAL,
        "org": "pga_tour",
        "url": collected.url,
        "captured_at_utc": collected.captured_at_utc,
        "finality": FINALITY_FINAL,
        "expected_field_size": collected.field_size,
        "payload_path": str(csv_path),
        "payload_sha256": payload_sha256,
        "parsed_rows": len(collected.players),
        "collector": "pga_tour_automated",
        "tournament_id": collected.tournament_id,
        "raw_html_path": collected.raw_html_path,
        "raw_html_sha256": collected.raw_html_sha256,
    }
    (evidence_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return FieldEvidence(
        event_key=collected.event_key,
        event_name=collected.event_name,
        source_kind=SOURCE_KIND_OFFICIAL,
        org="pga_tour",
        url=collected.url,
        captured_at_utc=collected.captured_at_utc,
        finality=FINALITY_FINAL,
        expected_field_size=collected.field_size,
        payload_path=str(csv_path),
        payload_sha256=payload_sha256,
        rows=collected.players,
    )


def persist_tee_time_evidence(
    collected: CollectedTeeTimes,
    raw_events_root: Path = TEE_TIMES_ROOT,
) -> TeeTimeEvidence:
    """Persist the collected tee times as evidence compatible with the pipeline.

    Writes a tee-times CSV into the ``latest`` evidence directory and creates
    a ``source_manifest.json`` that the existing
    ``load_latest_tee_time_evidence`` can read.
    """
    evidence_dir = raw_events_root / collected.event_key / "tee_times" / "latest"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Write tee-times CSV
    csv_path = evidence_dir / "tee_times.csv"
    write_tee_times_csv(csv_path, collected.rows, collected.earliest_tee_at_utc)

    # Write source manifest compatible with existing load_latest_tee_time_evidence
    payload_sha256 = sha256_file(csv_path)
    manifest = {
        "schema_version": 1,
        "event_key": collected.event_key,
        "event_name": collected.event_name,
        "org": "pga_tour",
        "url": collected.url,
        "captured_at_utc": collected.captured_at_utc,
        "local_timezone": collected.local_timezone,
        "reviewed_by": "pga_tour_automated",
        "payload_path": str(csv_path),
        "payload_sha256": payload_sha256,
        "derived_rows": len(collected.rows),
        "earliest_tee_at_utc": collected.earliest_tee_at_utc,
        "collector": "pga_tour_automated",
        "tournament_id": collected.tournament_id,
        "raw_html_path": collected.raw_html_path,
        "raw_html_sha256": collected.raw_html_sha256,
    }
    (evidence_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return TeeTimeEvidence(
        event_key=collected.event_key,
        event_name=collected.event_name,
        org="pga_tour",
        url=collected.url,
        captured_at_utc=collected.captured_at_utc,
        local_timezone=collected.local_timezone,
        reviewed_by="pga_tour_automated",
        payload_path=str(csv_path),
        payload_sha256=payload_sha256,
        rows=collected.rows,
        earliest_tee_at_utc=collected.earliest_tee_at_utc,
    )
