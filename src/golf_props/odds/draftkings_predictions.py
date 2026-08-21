"""DraftKings Predictions golf placement raw collector and parser."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from golf_props.normalization.manual_odds import normalize_rows, write_output

DEFAULT_TOPIC_URL = "https://predictions.draftkings.com/en/topic/golf"
DEFAULT_URL = DEFAULT_TOPIC_URL
LEGACY_PLACEMENT_URL = "https://predictions.draftkings.com/en/golf/placement"
SPORTSBOOK = "DraftKings"
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_RETRIES = 3
DEFAULT_RETRY_SLEEP_SECONDS = 5.0
DEFAULT_MAX_LINKED_PAGES = 20
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
SUPPORTED_MARKET_PATTERNS = [
    (re.compile(r"\bwinner\b", re.IGNORECASE), "winner"),
    (re.compile(r"\btop\s*20\b", re.IGNORECASE), "top20"),
    (re.compile(r"\btop\s*10\b", re.IGNORECASE), "top10"),
    (re.compile(r"\btop\s*5\b", re.IGNORECASE), "top5"),
    (re.compile(r"\b(make|to make)\s+the\s+cut\b", re.IGNORECASE), "make_cut"),
]


class DraftKingsParseError(ValueError):
    """Raised when a DraftKings placement snapshot cannot be parsed."""


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self._parts.append(value)

    @property
    def text_items(self) -> list[str]:
        return self._parts


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def iso_timestamp(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def fetch_page(url: str = DEFAULT_URL, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str]:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout_seconds) as response:
        status = int(response.status)
        content = response.read().decode("utf-8", "replace")
    return status, content


def fetch_page_with_retries(
    url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
) -> tuple[int, str, int]:
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            status_code, html = fetch_page(url, timeout_seconds=timeout_seconds)
            return status_code, html, attempt
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_sleep_seconds)
    assert last_error is not None
    raise last_error


def failure_metadata(
    output_dir: Path,
    url: str,
    captured_at: datetime,
    attempts: int,
    error: BaseException,
) -> dict[str, object]:
    slug = timestamp_slug(captured_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / f"{slug}.metadata.json"
    metadata = {
        "source": "draftkings_predictions_golf_placement",
        "sportsbook": SPORTSBOOK,
        "url": url,
        "captured_at_utc": iso_timestamp(captured_at),
        "status": "failed",
        "attempts": attempts,
        "error_type": type(error).__name__,
        "error": str(error),
        "raw_path": None,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def collect_raw_snapshot(
    output_dir: Path,
    url: str = DEFAULT_URL,
    captured_at: Optional[datetime] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
) -> dict[str, object]:
    captured_at = captured_at or utc_now()
    last_error: Optional[BaseException] = None
    status_code: Optional[int] = None
    html: Optional[str] = None
    attempt = retries
    try:
        status_code, html, attempt = fetch_page_with_retries(
            url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_sleep_seconds=retry_sleep_seconds,
        )
    except (TimeoutError, URLError, OSError) as exc:
        last_error = exc
    if html is None or status_code is None:
        assert last_error is not None
        metadata = failure_metadata(output_dir, url, captured_at, retries, last_error)
        raise DraftKingsParseError(
            f"failed to collect DraftKings placement page after {retries} attempts: "
            f"{type(last_error).__name__}: {last_error}"
        )

    slug = timestamp_slug(captured_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{slug}.html"
    metadata_path = output_dir / f"{slug}.metadata.json"
    raw_path.write_text(html, encoding="utf-8")
    metadata = {
        "source": "draftkings_predictions_golf_placement",
        "sportsbook": SPORTSBOOK,
        "url": url,
        "captured_at_utc": iso_timestamp(captured_at),
        "status": "ok",
        "attempts": attempt,
        "status_code": status_code,
        "content_hash": content_hash(html),
        "raw_path": str(raw_path),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def eligible_link(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    if parsed.netloc and parsed.netloc != base.netloc:
        return False
    return bool(
        re.fullmatch(r"/en/golf/market-group-details/[^/?#]+", parsed.path)
        or parsed.path == "/en/golf/to-make-the-cut"
        or re.fullmatch(r"/en/markets/golf/[^/?#]+", parsed.path)
    )


def extract_market_links(html: str, base_url: str) -> list[str]:
    links = []
    for match in re.finditer(r'href="([^"]+)"', html):
        absolute_url = urljoin(base_url, match.group(1))
        if eligible_link(absolute_url, base_url):
            links.append(absolute_url)
    return sorted(dict.fromkeys(links))


def raw_page_path(output_dir: Path, slug: str, page_index: int) -> Path:
    if page_index == 0:
        return output_dir / f"{slug}.index.html"
    return output_dir / f"{slug}.linked_{page_index:02d}.html"


def collect_linked_snapshot(
    output_dir: Path,
    url: str = DEFAULT_URL,
    captured_at: Optional[datetime] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
    max_pages: int = DEFAULT_MAX_LINKED_PAGES,
) -> dict[str, object]:
    captured_at = captured_at or utc_now()
    slug = timestamp_slug(captured_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / f"{slug}.linked.metadata.json"

    queue = [url]
    seen: set[str] = set()
    pages: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    while queue and len(pages) < max_pages:
        page_url = queue.pop(0)
        if page_url in seen:
            continue
        seen.add(page_url)
        try:
            status_code, html, attempts = fetch_page_with_retries(
                page_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )
        except (TimeoutError, URLError, OSError) as exc:
            errors.append(
                {
                    "url": page_url,
                    "attempts": retries,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue

        page_index = len(pages)
        path = raw_page_path(output_dir, slug, page_index)
        path.write_text(html, encoding="utf-8")
        pages.append(
            {
                "url": page_url,
                "status_code": status_code,
                "attempts": attempts,
                "content_hash": content_hash(html),
                "raw_path": str(path),
            }
        )
        for link in extract_market_links(html, page_url):
            if link not in seen and link not in queue:
                queue.append(link)

    metadata = {
        "source": "draftkings_predictions_golf_placement",
        "sportsbook": SPORTSBOOK,
        "url": url,
        "captured_at_utc": iso_timestamp(captured_at),
        "status": "ok" if pages else "failed",
        "crawl_mode": "linked",
        "max_pages": max_pages,
        "page_count": len(pages),
        "errors": errors,
        "raw_path": pages[0]["raw_path"] if pages else None,
        "raw_paths": [page["raw_path"] for page in pages],
        "pages": pages,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if not pages:
        if url == LEGACY_PLACEMENT_URL:
            return collect_linked_snapshot(
                output_dir,
                url=DEFAULT_TOPIC_URL,
                captured_at=captured_at,
                timeout_seconds=timeout_seconds,
                retries=retries,
                retry_sleep_seconds=retry_sleep_seconds,
                max_pages=max_pages,
            )
        raise DraftKingsParseError(f"failed to collect any DraftKings linked pages for {url}")
    return metadata


def read_metadata(path: Optional[Path], raw_path: Path, source_url: str) -> dict[str, object]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": "draftkings_predictions_golf_placement",
        "sportsbook": SPORTSBOOK,
        "url": source_url,
        "captured_at_utc": iso_timestamp(utc_now()),
        "status_code": None,
        "content_hash": content_hash(raw_path.read_text(encoding="utf-8")),
        "raw_path": str(raw_path),
    }


def extract_text_items(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    items = []
    for value in parser.text_items:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if cleaned:
            items.append(cleaned)
    return items


def detect_market(text: str) -> Optional[str]:
    for pattern, market_type in SUPPORTED_MARKET_PATTERNS:
        if pattern.search(text):
            return market_type
    return None


def event_name_from_market_heading(text: str, market_type: str) -> str:
    patterns = {
        "winner": r"\s+winner\b.*$",
        "top20": r"\s+top\s*20\b.*$",
        "top10": r"\s+top\s*10\b.*$",
        "top5": r"\s+top\s*5\b.*$",
        "make_cut": r"\s+(to\s+)?make\s+the\s+cut\b.*$",
    }
    event_name = re.sub(patterns[market_type], "", text, flags=re.IGNORECASE).strip()
    return event_name or text.strip()


def parse_yes_price(text: str) -> Optional[int]:
    match = re.fullmatch(r"Yes\s+([+-]?\d+)", text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace("+", ""))


def parse_price_token(text: str) -> Optional[int]:
    match = re.fullmatch(r"[+-]?\d+", text.strip())
    if not match:
        return None
    return int(text.replace("+", ""))


def looks_like_player_name(text: str) -> bool:
    if not text or len(text) > 80:
        return False
    if detect_market(text):
        return False
    if re.fullmatch(r"(Yes|No)\s+[+-]?\d+", text, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"(Yes|No)", text, flags=re.IGNORECASE):
        return False
    if parse_price_token(text) is not None:
        return False
    if text.lower() in {"golf predictions", "popular", "odds", "sportsbook"}:
        return False
    return bool(re.search(r"[A-Za-z]", text))


def build_yes_row(
    captured_at_utc: str,
    season: str,
    source_url: str,
    event_name: str,
    market_type: str,
    player_name: str,
    price_american: int,
) -> dict[str, str]:
    return {
        "captured_at_utc": captured_at_utc,
        "sportsbook": SPORTSBOOK,
        "event_name": event_name,
        "season": season,
        "market_type": market_type,
        "market_name": market_type,
        "player_name": player_name,
        "selection_name": player_name,
        "line": "",
        "price_american": str(price_american),
        "source_url": source_url,
        "market_status": "open",
        "is_closing_candidate": "false",
    }


def parse_placement_rows(
    html: str,
    captured_at_utc: str,
    source_url: str,
    season: Optional[str] = None,
) -> list[dict[str, str]]:
    items = extract_text_items(html)
    rows: list[dict[str, str]] = []
    current_event: Optional[str] = None
    current_market: Optional[str] = None
    current_player: Optional[str] = None
    season = season or str(datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00")).year)

    index = 0
    while index < len(items):
        item = items[index]
        market_type = detect_market(item)
        if market_type:
            current_market = market_type
            current_event = event_name_from_market_heading(item, market_type)
            current_player = None
            index += 1
            continue

        yes_price = parse_yes_price(item)
        if yes_price is not None and current_market and current_event and current_player:
            rows.append(
                build_yes_row(
                    captured_at_utc,
                    season,
                    source_url,
                    current_event,
                    current_market,
                    current_player,
                    yes_price,
                )
            )
            current_player = None
            index += 1
            continue

        if (
            item.lower() == "yes"
            and current_market
            and current_event
            and current_player
            and index + 1 < len(items)
        ):
            token_price = parse_price_token(items[index + 1])
            if token_price is not None:
                rows.append(
                    build_yes_row(
                        captured_at_utc,
                        season,
                        source_url,
                        current_event,
                        current_market,
                        current_player,
                        token_price,
                    )
                )
                current_player = None
                index += 2
                continue

        if item.lower() == "no":
            index += 2 if index + 1 < len(items) and parse_price_token(items[index + 1]) is not None else 1
            continue

        if looks_like_player_name(item):
            current_player = item

        index += 1

    return rows


def parse_raw_snapshot(
    raw_path: Path,
    output_path: Path,
    metadata_path: Optional[Path] = None,
    source_url: str = DEFAULT_URL,
    season: Optional[str] = None,
) -> list[dict[str, object]]:
    metadata = read_metadata(metadata_path, raw_path, source_url)
    html = raw_path.read_text(encoding="utf-8")
    source_url = str(metadata.get("url") or source_url)
    captured_at_utc = str(metadata.get("captured_at_utc"))
    parsed_rows = parse_placement_rows(
        html,
        captured_at_utc=captured_at_utc,
        source_url=source_url,
        season=season,
    )
    normalized = normalize_rows(parsed_rows)
    write_output(normalized, output_path)
    return normalized


def dedupe_parsed_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        key = (
            row.get("captured_at_utc", ""),
            row.get("sportsbook", ""),
            row.get("event_name", "").casefold(),
            row.get("season", ""),
            row.get("market_type", ""),
            row.get("player_name", "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def parse_linked_snapshot(
    metadata_path: Path,
    output_path: Path,
    season: Optional[str] = None,
) -> list[dict[str, object]]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    captured_at_utc = str(metadata.get("captured_at_utc"))
    pages = metadata.get("pages") or []
    if not isinstance(pages, list) or not pages:
        raise DraftKingsParseError(f"linked metadata has no pages: {metadata_path}")

    parsed_rows: list[dict[str, str]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        raw_path = page.get("raw_path")
        if not raw_path:
            continue
        html = Path(str(raw_path)).read_text(encoding="utf-8")
        source_url = str(page.get("url") or metadata.get("url") or DEFAULT_URL)
        parsed_rows.extend(
            parse_placement_rows(
                html,
                captured_at_utc=captured_at_utc,
                source_url=source_url,
                season=season,
            )
        )

    normalized = normalize_rows(dedupe_parsed_rows(parsed_rows))
    write_output(normalized, output_path)
    return normalized


def collect_and_parse(
    raw_output_dir: Path,
    processed_output: Path,
    url: str = DEFAULT_URL,
    season: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
    crawl_linked: bool = False,
    max_linked_pages: int = DEFAULT_MAX_LINKED_PAGES,
) -> list[dict[str, object]]:
    if crawl_linked:
        metadata = collect_linked_snapshot(
            raw_output_dir,
            url=url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_sleep_seconds=retry_sleep_seconds,
            max_pages=max_linked_pages,
        )
        first_raw_path = Path(str(metadata["raw_path"]))
        metadata_path = first_raw_path.with_name(first_raw_path.name.replace(".index.html", ".linked.metadata.json"))
        rows = parse_linked_snapshot(metadata_path, processed_output, season=season)
        if not rows:
            raise DraftKingsParseError(
                "DraftKings linked crawl succeeded but parsed zero golf odds rows. "
                "The current Predictions golf page is likely rendering prices from async data "
                "instead of static HTML."
            )
        return rows

    metadata = collect_raw_snapshot(
        raw_output_dir,
        url=url,
        timeout_seconds=timeout_seconds,
        retries=retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )
    raw_path = Path(str(metadata["raw_path"]))
    metadata_path = raw_path.with_suffix(".metadata.json")
    rows = parse_raw_snapshot(
        raw_path,
        processed_output,
        metadata_path=metadata_path,
        source_url=url,
        season=season,
    )
    if not rows:
        raise DraftKingsParseError(
            "DraftKings raw scrape succeeded but parsed zero golf odds rows. "
            "The current Predictions golf page is likely rendering prices from async data "
            "instead of static HTML."
        )
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="draftkings-predictions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--output-dir", required=True, type=Path)
    collect_parser.add_argument("--url", default=DEFAULT_URL)
    collect_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    collect_parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    collect_parser.add_argument("--retry-sleep-seconds", type=float, default=DEFAULT_RETRY_SLEEP_SECONDS)

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("--raw", required=True, type=Path)
    parse_parser.add_argument("--output", required=True, type=Path)
    parse_parser.add_argument("--metadata", type=Path)
    parse_parser.add_argument("--url", default=DEFAULT_URL)
    parse_parser.add_argument("--season")

    collect_parse_parser = subparsers.add_parser("collect-parse")
    collect_parse_parser.add_argument("--raw-output-dir", required=True, type=Path)
    collect_parse_parser.add_argument("--processed-output", required=True, type=Path)
    collect_parse_parser.add_argument("--url", default=DEFAULT_URL)
    collect_parse_parser.add_argument("--season")
    collect_parse_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    collect_parse_parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    collect_parse_parser.add_argument("--retry-sleep-seconds", type=float, default=DEFAULT_RETRY_SLEEP_SECONDS)
    collect_parse_parser.add_argument("--crawl-linked", action="store_true")
    collect_parse_parser.add_argument("--max-linked-pages", type=int, default=DEFAULT_MAX_LINKED_PAGES)

    args = parser.parse_args(argv)
    if args.command == "collect":
        collect_raw_snapshot(
            args.output_dir,
            url=args.url,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            retry_sleep_seconds=args.retry_sleep_seconds,
            crawl_linked=args.crawl_linked,
            max_linked_pages=args.max_linked_pages,
        )
    elif args.command == "parse":
        parse_raw_snapshot(
            args.raw,
            args.output,
            metadata_path=args.metadata,
            source_url=args.url,
            season=args.season,
        )
    elif args.command == "collect-parse":
        collect_and_parse(
            args.raw_output_dir,
            args.processed_output,
            url=args.url,
            season=args.season,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            retry_sleep_seconds=args.retry_sleep_seconds,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
