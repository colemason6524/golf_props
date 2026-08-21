"""Collect CBS Sports PGA leaderboard pages for completed events."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DEFAULT_SCHEDULE_URL = "https://www.cbssports.com/golf/schedules/2026/"
BASE_URL = "https://www.cbssports.com"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class CbsCollectionError(ValueError):
    """Raised when CBS pages cannot be collected."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def fetch_page(url: str, timeout_seconds: int = 90) -> tuple[int, str]:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout_seconds) as response:
        return int(response.status), response.read().decode("utf-8", "replace")


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def field(block: str, name: str) -> str:
    match = re.search(rf'"{re.escape(name)}"\s*:\s*"(.*?)"', block, flags=re.S)
    return clean_space(match.group(1)) if match else ""


def place_name(block: str) -> str:
    location_match = re.search(r'"location"\s*:\s*\{(.*?)\}\s*,\s*"name"', block, flags=re.S)
    if not location_match:
        return ""
    return field(location_match.group(1), "name")


def event_name(block: str) -> str:
    match = re.search(r'"name"\s*:\s*"([^"]+)"\s*,\s*"sport"\s*:\s*"golf"', block, flags=re.S)
    return clean_space(match.group(1)) if match else field(block, "name")


def address_field(block: str, name: str) -> str:
    location_match = re.search(r'"address"\s*:\s*\{(.*?)\}\s*\}', block, flags=re.S)
    if not location_match:
        return ""
    return field(location_match.group(1), name)


def parse_cbs_date(value: str) -> date:
    return datetime.strptime(clean_space(value), "%b %d, %Y").date()


def extract_schedule_events(schedule_html: str, as_of_date: Optional[date] = None) -> list[dict[str, object]]:
    events = []
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
        schedule_html,
        flags=re.S,
    )
    for block in blocks:
        if '"@type": "SportsEvent"' not in block:
            continue
        name = event_name(block)
        url = field(block, "url")
        start_raw = field(block, "startDate")
        end_raw = field(block, "endDate")
        if not name or not url or not start_raw or not end_raw:
            continue
        start_date = parse_cbs_date(start_raw)
        end_date = parse_cbs_date(end_raw)
        status = "completed" if as_of_date is None or end_date < as_of_date else "not_completed"
        events.append(
            {
                "event_name": name,
                "date_start": start_date.isoformat(),
                "date_end": end_date.isoformat(),
                "status": status,
                "url": urljoin(BASE_URL, url),
                "course_name": place_name(block),
                "location": ", ".join(
                    part
                    for part in [
                        address_field(block, "addressLocality"),
                        address_field(block, "addressRegion"),
                        address_field(block, "addressCountry"),
                    ]
                    if part
                ),
            }
        )
    return events


def event_slug(event: dict[str, object]) -> str:
    match = re.search(r"/(\d+)/([^/]+)/?$", str(event["url"]))
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    return re.sub(r"[^a-z0-9]+", "_", str(event["event_name"]).casefold()).strip("_")


def collect_cbs_results(
    output_dir: Path,
    schedule_url: str = DEFAULT_SCHEDULE_URL,
    as_of_date: Optional[date] = None,
    timeout_seconds: int = 90,
    limit: Optional[int] = None,
) -> dict[str, object]:
    captured_at = utc_now()
    output_dir.mkdir(parents=True, exist_ok=True)
    status_code, schedule_html = fetch_page(schedule_url, timeout_seconds=timeout_seconds)
    schedule_path = output_dir / "schedule.html"
    schedule_path.write_text(schedule_html, encoding="utf-8")
    events = [
        event
        for event in extract_schedule_events(schedule_html, as_of_date=as_of_date)
        if event["status"] == "completed"
    ]
    if limit is not None:
        events = events[:limit]

    collected_events = []
    for event in events:
        event_status, html = fetch_page(str(event["url"]), timeout_seconds=timeout_seconds)
        raw_path = output_dir / f"{event_slug(event)}.html"
        raw_path.write_text(html, encoding="utf-8")
        collected_events.append(
            {
                **event,
                "status_code": event_status,
                "content_hash": content_hash(html),
                "raw_path": str(raw_path),
            }
        )

    metadata = {
        "source": "cbs_sports",
        "tour": "PGA",
        "schedule_url": schedule_url,
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "captured_at_utc": iso_timestamp(captured_at),
        "status_code": status_code,
        "schedule_raw_path": str(schedule_path),
        "event_count": len(collected_events),
        "events": collected_events,
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="collect-cbs-results")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--schedule-url", default=DEFAULT_SCHEDULE_URL)
    parser.add_argument("--as-of-date")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    collect_cbs_results(
        args.output_dir,
        schedule_url=args.schedule_url,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        timeout_seconds=args.timeout_seconds,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
