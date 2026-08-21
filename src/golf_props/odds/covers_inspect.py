"""Inspect Covers golf odds pages before building a parser."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError

from golf_props.odds.source_audit import (
    CandidateSource,
    DEFAULT_PLAYER_NAMES,
    DEFAULT_TIMEOUT_SECONDS,
    MARKET_PATTERNS,
    ODDS_PATTERN,
    fetch_page,
    parse_candidate,
)

DEFAULT_URL = "https://www.covers.com/sport/golf/pga/odds"
DEFAULT_OUTPUT_DIR = Path("data/interim/reports/covers_source_inspection")
DEFAULT_BATCH_OUTPUT_DIR = Path("data/interim/reports/odds_url_inspection_batch")
DEFAULT_CONTEXT_ITEMS = 8

TEXT_ITEM_COLUMNS = [
    "index",
    "text",
    "odds_tokens",
    "market_hits",
    "player_hits",
]
BATCH_COLUMNS = [
    "source_name",
    "url",
    "status",
    "http_status",
    "likely_parseable",
    "row_candidate_count",
    "odds_token_count",
    "market_hits",
    "player_hits",
    "snippet_count",
    "recommendation",
    "inspection_dir",
    "summary_path",
    "snippets_path",
    "text_items_path",
    "error_type",
    "error",
]
DEFAULT_BATCH_CANDIDATES = [
    CandidateSource("Covers PGA Odds", "https://www.covers.com/sport/golf/pga/odds"),
    CandidateSource("Covers 3M Open Odds Article", "https://www.covers.com/golf/3m-open-odds-favorites-field-2025"),
    CandidateSource("Covers 3M Open Picks Article", "https://www.covers.com/golf/picks-3m-open-predictions-2025"),
]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self._parts.append(value)

    @property
    def text_items(self) -> list[str]:
        return self._parts


@dataclass(frozen=True)
class Snippet:
    trigger_type: str
    trigger: str
    index: int
    before: list[str]
    item: str
    after: list[str]
    odds_tokens: list[str]
    market_hits: list[str]
    player_hits: list[str]


def extract_text_items(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    return parser.text_items


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def item_market_hits(item: str) -> list[str]:
    return [market for market, pattern in MARKET_PATTERNS.items() if pattern.search(item)]


def item_player_hits(item: str, player_names: list[str]) -> list[str]:
    normalized = normalize_text(item)
    return [name for name in player_names if normalize_text(name) in normalized]


def item_row(index: int, item: str, player_names: list[str]) -> dict[str, object]:
    return {
        "index": index,
        "text": item,
        "odds_tokens": "; ".join(ODDS_PATTERN.findall(item)),
        "market_hits": "; ".join(item_market_hits(item)),
        "player_hits": "; ".join(item_player_hits(item, player_names)),
    }


def find_snippets(
    text_items: list[str],
    triggers: list[tuple[str, str]],
    player_names: list[str],
    context_items: int = DEFAULT_CONTEXT_ITEMS,
) -> list[Snippet]:
    snippets: list[Snippet] = []
    seen: set[tuple[str, str, int]] = set()
    for trigger_type, trigger in triggers:
        pattern = re.compile(re.escape(trigger), re.IGNORECASE)
        for index, item in enumerate(text_items):
            if not pattern.search(item):
                continue
            key = (trigger_type, trigger.casefold(), index)
            if key in seen:
                continue
            seen.add(key)
            start = max(0, index - context_items)
            end = min(len(text_items), index + context_items + 1)
            context = text_items[start:end]
            snippets.append(
                Snippet(
                    trigger_type=trigger_type,
                    trigger=trigger,
                    index=index,
                    before=text_items[start:index],
                    item=item,
                    after=text_items[index + 1 : end],
                    odds_tokens=ODDS_PATTERN.findall(" ".join(context)),
                    market_hits=sorted({market for value in context for market in item_market_hits(value)}),
                    player_hits=sorted({name for value in context for name in item_player_hits(value, player_names)}),
                )
            )
    return snippets


def market_triggers() -> list[tuple[str, str]]:
    return [
        ("market", "Winner"),
        ("market", "Outright"),
        ("market", "Top 5"),
        ("market", "Top 10"),
        ("market", "Top 20"),
        ("market", "Make The Cut"),
        ("market", "To Make The Cut"),
    ]


def player_triggers(player_names: list[str]) -> list[tuple[str, str]]:
    return [("player", name) for name in player_names]


def summarize_inspection(
    url: str,
    http_status: int,
    html: str,
    text_items: list[str],
    snippets: list[Snippet],
    player_names: list[str],
) -> dict[str, object]:
    all_text = " ".join(text_items)
    odds_count = len(ODDS_PATTERN.findall(all_text))
    market_hits = sorted({market for item in text_items for market in item_market_hits(item)})
    player_hits = sorted({name for item in text_items for name in item_player_hits(item, player_names)})
    snippets_with_players_and_odds = [
        snippet
        for snippet in snippets
        if snippet.player_hits and snippet.odds_tokens
    ]
    snippets_with_markets_players_odds = [
        snippet
        for snippet in snippets
        if snippet.market_hits and snippet.player_hits and snippet.odds_tokens
    ]
    row_candidate_count = count_player_price_adjacencies(text_items, player_names)
    likely_parseable = row_candidate_count >= 4 and len(market_hits) >= 2
    return {
        "url": url,
        "http_status": http_status,
        "html_bytes": len(html.encode("utf-8")),
        "text_item_count": len(text_items),
        "odds_token_count": odds_count,
        "market_hits": market_hits,
        "player_hits": player_hits,
        "snippet_count": len(snippets),
        "snippets_with_players_and_odds": len(snippets_with_players_and_odds),
        "snippets_with_markets_players_odds": len(snippets_with_markets_players_odds),
        "row_candidate_count": row_candidate_count,
        "likely_parseable": likely_parseable,
        "recommendation": (
            "Build a Covers parser next."
            if likely_parseable
            else "Inspect snippets manually before building a parser."
        ),
    }


def count_player_price_adjacencies(text_items: list[str], player_names: list[str], window: int = 2) -> int:
    count = 0
    for index, item in enumerate(text_items):
        if not item_player_hits(item, player_names):
            continue
        start = max(0, index - window)
        end = min(len(text_items), index + window + 1)
        if ODDS_PATTERN.search(" ".join(text_items[start:end])):
            count += 1
    return count


def write_text_items(path: Path, text_items: list[str], player_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEXT_ITEM_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for index, item in enumerate(text_items):
            writer.writerow(item_row(index, item, player_names))


def render_snippets_markdown(summary: dict[str, object], snippets: list[Snippet]) -> str:
    lines = ["# Covers Source Inspection", ""]
    lines.append(f"url: {summary['url']}")
    lines.append(f"http_status: {summary['http_status']}")
    lines.append(f"text_item_count: {summary['text_item_count']}")
    lines.append(f"odds_token_count: {summary['odds_token_count']}")
    lines.append(f"market_hits: {', '.join(summary['market_hits'])}")
    lines.append(f"player_hits: {', '.join(summary['player_hits'])}")
    lines.append(f"row_candidate_count: {summary['row_candidate_count']}")
    lines.append(f"likely_parseable: {summary['likely_parseable']}")
    lines.append(f"recommendation: {summary['recommendation']}")
    lines.append("")
    if not snippets:
        lines.append("No snippets found.")
        return "\n".join(lines) + "\n"

    for snippet in snippets:
        lines.append(f"## {snippet.trigger_type}: {snippet.trigger} @ item {snippet.index}")
        lines.append("")
        lines.append(f"- markets: {', '.join(snippet.market_hits)}")
        lines.append(f"- players: {', '.join(snippet.player_hits)}")
        lines.append(f"- odds: {', '.join(snippet.odds_tokens[:25])}")
        lines.append("")
        lines.append("```text")
        for value in snippet.before:
            lines.append(value)
        lines.append(f">>> {snippet.item}")
        for value in snippet.after:
            lines.append(value)
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def inspect_covers_odds(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    url: str = DEFAULT_URL,
    player_names: Optional[list[str]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    context_items: int = DEFAULT_CONTEXT_ITEMS,
) -> dict[str, object]:
    player_names = player_names or DEFAULT_PLAYER_NAMES
    http_status, html = fetch_page(url, timeout_seconds=timeout_seconds)
    text_items = extract_text_items(html)
    triggers = market_triggers() + player_triggers(player_names)
    snippets = find_snippets(text_items, triggers, player_names, context_items=context_items)
    summary = summarize_inspection(url, http_status, html, text_items, snippets, player_names)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_text_items(output_dir / "text_items.csv", text_items, player_names)
    (output_dir / "snippets.md").write_text(render_snippets_markdown(summary, snippets), encoding="utf-8")
    (output_dir / "inspection_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "summary": summary,
        "snippets": snippets,
        "text_items": text_items,
        "output_dir": output_dir,
    }


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "source"


def batch_row_from_result(candidate: CandidateSource, result: dict[str, object]) -> dict[str, object]:
    output_dir = Path(str(result["output_dir"]))
    summary = result["summary"]
    assert isinstance(summary, dict)
    return {
        "source_name": candidate.source_name,
        "url": candidate.url,
        "status": "ok",
        "http_status": summary.get("http_status", ""),
        "likely_parseable": summary.get("likely_parseable", ""),
        "row_candidate_count": summary.get("row_candidate_count", ""),
        "odds_token_count": summary.get("odds_token_count", ""),
        "market_hits": "; ".join(summary.get("market_hits", [])),
        "player_hits": "; ".join(summary.get("player_hits", [])),
        "snippet_count": summary.get("snippet_count", ""),
        "recommendation": summary.get("recommendation", ""),
        "inspection_dir": str(output_dir),
        "summary_path": str(output_dir / "inspection_summary.json"),
        "snippets_path": str(output_dir / "snippets.md"),
        "text_items_path": str(output_dir / "text_items.csv"),
        "error_type": "",
        "error": "",
    }


def batch_error_row(candidate: CandidateSource, output_dir: Path, error: BaseException) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "inspection_summary.json"
    summary = {
        "url": candidate.url,
        "source_name": candidate.source_name,
        "status": "failed",
        "error_type": type(error).__name__,
        "error": str(error),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "snippets.md").write_text(
        f"# Covers Source Inspection\n\nurl: {candidate.url}\nstatus: failed\nerror: {error}\n",
        encoding="utf-8",
    )
    write_text_items(output_dir / "text_items.csv", [], [])
    return {
        "source_name": candidate.source_name,
        "url": candidate.url,
        "status": "failed",
        "http_status": getattr(error, "code", ""),
        "likely_parseable": "",
        "row_candidate_count": "",
        "odds_token_count": "",
        "market_hits": "",
        "player_hits": "",
        "snippet_count": "",
        "recommendation": "Fetch failed; do not build parser from this URL yet.",
        "inspection_dir": str(output_dir),
        "summary_path": str(summary_path),
        "snippets_path": str(output_dir / "snippets.md"),
        "text_items_path": str(output_dir / "text_items.csv"),
        "error_type": type(error).__name__,
        "error": str(error),
    }


def write_batch_summary(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BATCH_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_batch_report(rows: list[dict[str, object]]) -> str:
    lines = ["# Odds URL Inspection Batch", ""]
    if not rows:
        lines.append("No URLs inspected.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "| Parseable | Rows | Odds | Source | Markets | Players | Status |",
            "|---:|---:|---:|---|---|---|---|",
        ]
    )
    for row in sorted(rows, key=batch_sort_key):
        lines.append(
            "| {parseable} | {rows} | {odds} | [{source}]({snippets}) | {markets} | {players} | {status} |".format(
                parseable=row.get("likely_parseable", ""),
                rows=row.get("row_candidate_count", ""),
                odds=row.get("odds_token_count", ""),
                source=row.get("source_name", ""),
                snippets=row.get("snippets_path", ""),
                markets=row.get("market_hits", ""),
                players=row.get("player_hits", ""),
                status=row.get("status", ""),
            )
        )
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for row in sorted(rows, key=batch_sort_key):
        lines.append(f"- {row.get('source_name')}: {row.get('recommendation')}")
    return "\n".join(lines) + "\n"


def batch_sort_key(row: dict[str, object]) -> tuple[int, int, int, str]:
    parseable = 0 if str(row.get("likely_parseable")).casefold() == "true" else 1
    row_count = int(row.get("row_candidate_count") or 0)
    odds_count = int(row.get("odds_token_count") or 0)
    return (parseable, -row_count, -odds_count, str(row.get("source_name", "")))


def inspect_odds_url_batch(
    output_dir: Path = DEFAULT_BATCH_OUTPUT_DIR,
    candidates: Optional[list[CandidateSource]] = None,
    player_names: Optional[list[str]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    context_items: int = DEFAULT_CONTEXT_ITEMS,
) -> dict[str, object]:
    candidates = candidates or DEFAULT_BATCH_CANDIDATES
    player_names = player_names or DEFAULT_PLAYER_NAMES
    rows: list[dict[str, object]] = []
    used_slugs: set[str] = set()
    for candidate in candidates:
        slug = slugify(candidate.source_name)
        base_slug = slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        used_slugs.add(slug)
        inspection_dir = output_dir / slug
        try:
            result = inspect_covers_odds(
                output_dir=inspection_dir,
                url=candidate.url,
                player_names=player_names,
                timeout_seconds=timeout_seconds,
                context_items=context_items,
            )
        except (HTTPError, TimeoutError, URLError, OSError) as exc:
            rows.append(batch_error_row(candidate, inspection_dir, exc))
            continue
        rows.append(batch_row_from_result(candidate, result))

    output_dir.mkdir(parents=True, exist_ok=True)
    write_batch_summary(output_dir / "batch_summary.csv", rows)
    (output_dir / "report.md").write_text(render_batch_report(rows), encoding="utf-8")
    return {"rows": rows, "output_dir": output_dir}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="inspect-covers-odds")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--player", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--context-items", type=int, default=DEFAULT_CONTEXT_ITEMS)
    args = parser.parse_args(argv)

    player_names = args.player if args.player else None
    inspect_covers_odds(
        output_dir=args.output_dir,
        url=args.url,
        player_names=player_names,
        timeout_seconds=args.timeout_seconds,
        context_items=args.context_items,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
