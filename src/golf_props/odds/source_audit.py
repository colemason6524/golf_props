"""Audit candidate golf odds pages for no-browser scrape viability."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 45
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
ODDS_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[+-]\d{2,5}|[1-9]\d{0,2}/[1-9]\d{0,2})(?![A-Za-z0-9])")
JS_SHELL_MARKERS = [
    "__NEXT_DATA__",
    "__reactRouterContext",
    "modulepreload",
    "window.__",
    "app-root",
]
DEFAULT_PLAYER_NAMES = [
    "Scottie Scheffler",
    "Rory McIlroy",
    "Xander Schauffele",
    "Collin Morikawa",
    "Justin Thomas",
    "Tony Finau",
    "Akshay Bhatia",
    "Sahith Theegala",
    "Sam Burns",
    "Viktor Hovland",
]
MARKET_PATTERNS = {
    "winner": re.compile(r"\b(winner|outright|tournament winner)\b", re.IGNORECASE),
    "top5": re.compile(r"\btop\s*5\b", re.IGNORECASE),
    "top10": re.compile(r"\btop\s*10\b", re.IGNORECASE),
    "top20": re.compile(r"\btop\s*20\b", re.IGNORECASE),
    "make_cut": re.compile(r"\b(make|to make)\s+the\s+cut\b", re.IGNORECASE),
}
AUDIT_COLUMNS = [
    "source_name",
    "url",
    "status",
    "http_status",
    "html_bytes",
    "odds_token_count",
    "player_hit_count",
    "player_hits",
    "markets_found",
    "market_count",
    "js_shell_score",
    "recommendation",
    "reason",
    "error_type",
    "error",
]


@dataclass(frozen=True)
class CandidateSource:
    source_name: str
    url: str


DEFAULT_CANDIDATES = [
    CandidateSource("Oddschecker 3M Open", "https://www.oddschecker.com/golf/3m-open"),
    CandidateSource("DraftKings Predictions Golf Topic", "https://predictions.draftkings.com/en/topic/golf"),
    CandidateSource("DraftKings Predictions 3M Open", "https://predictions.draftkings.com/en/markets/golf/3m-open"),
    CandidateSource("FanDuel Sportsbook Golf", "https://sportsbook.fanduel.com/navigation/pga"),
    CandidateSource("Covers PGA Odds", "https://www.covers.com/sport/golf/pga/odds"),
    CandidateSource("VegasInsider Golf Odds", "https://www.vegasinsider.com/golf/odds/"),
]


def fetch_page(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str]:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout_seconds) as response:
        return int(response.status), response.read().decode("utf-8", "replace")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def count_js_shell_markers(html: str) -> int:
    return sum(1 for marker in JS_SHELL_MARKERS if marker in html)


def find_player_hits(html: str, player_names: list[str]) -> list[str]:
    normalized_html = normalize_text(html)
    return [name for name in player_names if normalize_text(name) in normalized_html]


def find_markets(html: str) -> list[str]:
    return [market for market, pattern in MARKET_PATTERNS.items() if pattern.search(html)]


def classify_source(
    odds_token_count: int,
    player_hits: list[str],
    markets_found: list[str],
    js_shell_score: int,
) -> tuple[str, str, str]:
    if odds_token_count >= 20 and player_hits and markets_found:
        return "usable", "Build parser candidate.", "Raw page includes prices, player names, and supported market labels."
    if odds_token_count >= 20 and markets_found:
        return "promising", "Inspect manually.", "Raw page includes prices and market labels but few seed player names."
    if odds_token_count >= 10 and len(markets_found) >= 3:
        return "promising", "Inspect manually.", "Raw page includes several golf market labels and some price tokens."
    if player_hits and markets_found and odds_token_count == 0:
        return "not_usable_static", "Needs another extraction route.", "Player/market text exists, but prices are not static."
    if js_shell_score >= 3 and odds_token_count < 10:
        return "not_usable_static", "Likely JS/async rendered.", "Raw page looks like an app shell and has few price tokens."
    return "weak", "Deprioritize.", "Raw page does not expose enough odds structure."


def audit_html(
    candidate: CandidateSource,
    html: str,
    http_status: int,
    player_names: list[str],
) -> dict[str, object]:
    odds_tokens = ODDS_PATTERN.findall(html)
    player_hits = find_player_hits(html, player_names)
    markets_found = find_markets(html)
    js_shell_score = count_js_shell_markers(html)
    status, recommendation, reason = classify_source(
        len(odds_tokens),
        player_hits,
        markets_found,
        js_shell_score,
    )
    return {
        "source_name": candidate.source_name,
        "url": candidate.url,
        "status": status,
        "http_status": http_status,
        "html_bytes": len(html.encode("utf-8")),
        "odds_token_count": len(odds_tokens),
        "player_hit_count": len(player_hits),
        "player_hits": "; ".join(player_hits),
        "markets_found": "; ".join(markets_found),
        "market_count": len(markets_found),
        "js_shell_score": js_shell_score,
        "recommendation": recommendation,
        "reason": reason,
        "error_type": "",
        "error": "",
    }


def audit_candidate(
    candidate: CandidateSource,
    player_names: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    try:
        http_status, html = fetch_page(candidate.url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return error_row(candidate, exc.code, exc)
    except (TimeoutError, URLError, OSError) as exc:
        return error_row(candidate, "", exc)
    return audit_html(candidate, html, http_status, player_names)


def error_row(candidate: CandidateSource, http_status: object, error: BaseException) -> dict[str, object]:
    return {
        "source_name": candidate.source_name,
        "url": candidate.url,
        "status": "failed",
        "http_status": http_status,
        "html_bytes": 0,
        "odds_token_count": 0,
        "player_hit_count": 0,
        "player_hits": "",
        "markets_found": "",
        "market_count": 0,
        "js_shell_score": 0,
        "recommendation": "Do not build parser yet.",
        "reason": "Fetch failed.",
        "error_type": type(error).__name__,
        "error": str(error),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_markdown(rows: list[dict[str, object]]) -> str:
    lines = ["# Odds Source Audit", ""]
    if not rows:
        lines.append("No candidate sources audited.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "| Status | Source | Odds | Players | Markets | JS | Recommendation |",
            "|---|---|---:|---:|---|---:|---|",
        ]
    )
    for row in sorted(rows, key=sort_key):
        lines.append(
            "| {status} | [{source}]({url}) | {odds} | {players} | {markets} | {js} | {recommendation} |".format(
                status=row["status"],
                source=row["source_name"],
                url=row["url"],
                odds=row["odds_token_count"],
                players=row["player_hit_count"],
                markets=row["markets_found"] or "",
                js=row["js_shell_score"],
                recommendation=row["recommendation"],
            )
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for row in sorted(rows, key=sort_key):
        lines.append(f"- {row['source_name']}: {row['reason']}")
    return "\n".join(lines) + "\n"


def sort_key(row: dict[str, object]) -> tuple[int, int, str]:
    order = {"usable": 0, "promising": 1, "not_usable_static": 2, "weak": 3, "failed": 4}
    return (order.get(str(row["status"]), 9), -int(row.get("odds_token_count") or 0), str(row["source_name"]))


def parse_candidate(value: str) -> CandidateSource:
    if "|" in value:
        name, url = value.split("|", 1)
        return CandidateSource(name.strip(), url.strip())
    return CandidateSource(value.strip(), value.strip())


def audit_sources(
    output_dir: Path,
    candidates: Optional[list[CandidateSource]] = None,
    player_names: Optional[list[str]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    candidates = candidates or DEFAULT_CANDIDATES
    player_names = player_names or DEFAULT_PLAYER_NAMES
    rows = [audit_candidate(candidate, player_names, timeout_seconds=timeout_seconds) for candidate in candidates]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "source_audit.csv", rows)
    (output_dir / "report.md").write_text(render_markdown(rows), encoding="utf-8")
    return {"rows": rows, "output_dir": output_dir}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-odds-sources")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--player", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    candidates = [parse_candidate(value) for value in args.candidate] if args.candidate else None
    player_names = args.player if args.player else None
    audit_sources(
        args.output_dir,
        candidates=candidates,
        player_names=player_names,
        timeout_seconds=args.timeout_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
