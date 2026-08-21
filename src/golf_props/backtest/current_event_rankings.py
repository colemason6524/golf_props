"""Build current-event ranking rows from an odds snapshot field."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from golf_props.backtest.event_rankings import RANKING_COLUMNS, add_event_ranks, render_markdown

TARGET_TO_MARKET = {
    "target_make_cut": "make_cut",
    "target_top20": "top20",
    "target_top10": "top10",
    "target_top5": "top5",
    "target_win": "winner",
}

MARKET_TO_FEATURE = {
    "make_cut": "weighted_recent_made_cut_rate",
    "top20": "weighted_recent_top20_rate",
    "top10": "weighted_recent_top10_rate",
    "top5": "weighted_recent_top5_rate",
    "winner": "weighted_recent_win_rate",
}

MARKET_TO_FALLBACK_FEATURE = {
    "make_cut": "recent_made_cut_rate",
    "top20": "recent_top20_rate",
    "top10": "recent_top10_rate",
    "top5": "recent_top5_rate",
    "winner": "recent_win_rate",
}

PLAYER_NAME_ALIASES = {
    "alexander noren": "alex noren",
    "nicolas echavarria": "nico echavarria",
}


class CurrentEventRankingError(ValueError):
    """Raised when current event rankings cannot be built."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise CurrentEventRankingError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part).strip().casefold() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def normalize_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if len(token) > 1]
    return " ".join(tokens)


def player_lookup_keys(value: object) -> list[str]:
    normalized = normalize_name(value)
    keys = [normalized]
    aliased = PLAYER_NAME_ALIASES.get(normalized)
    if aliased:
        keys.append(normalize_name(aliased))
    compact = normalized.replace(" ", "")
    if compact and compact not in keys:
        keys.append(compact)
    return [key for key in dict.fromkeys(keys) if key]


def parse_float(value: object) -> Optional[float]:
    if value in {None, ""}:
        return None
    return float(value)


def parse_bool_target(value: object) -> Optional[int]:
    if value in {None, ""}:
        return None
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return 1
    if normalized == "false":
        return 0
    raise CurrentEventRankingError(f"invalid target value: {value}")


def captured_date(rows: list[dict[str, str]]) -> str:
    timestamps = sorted({row.get("captured_at_utc", "") for row in rows if row.get("captured_at_utc")})
    if not timestamps:
        return ""
    return datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00")).date().isoformat()


def infer_single_value(rows: list[dict[str, str]], column: str) -> str:
    values = sorted({row.get(column, "") for row in rows if row.get(column)})
    if not values:
        raise CurrentEventRankingError(f"odds snapshot has no {column}")
    if len(values) > 1:
        raise CurrentEventRankingError(f"odds snapshot has multiple {column} values: {values}")
    return values[0]


def base_rates(feature_rows: list[dict[str, str]]) -> dict[str, float]:
    rates = {}
    for target, market in TARGET_TO_MARKET.items():
        actuals = [value for row in feature_rows if (value := parse_bool_target(row.get(target))) is not None]
        if not actuals:
            raise CurrentEventRankingError(f"cannot compute base rate for {target}")
        rates[market] = sum(actuals) / len(actuals)
    return rates


def latest_features_by_player(feature_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in feature_rows:
        for key in player_lookup_keys(row.get("player_name")):
            previous = latest.get(key)
            if previous is None or row.get("event_date_start", "") > previous.get("event_date_start", ""):
                latest[key] = row
    return latest


def odds_field(odds_rows: list[dict[str, str]]) -> list[str]:
    names = sorted({row.get("player_name", "").strip() for row in odds_rows if row.get("player_name")})
    if not names:
        raise CurrentEventRankingError("odds snapshot has no player_name values")
    return names


def probability_for_market(
    market: str,
    feature_row: Optional[dict[str, str]],
    fallback_prob: float,
    min_prior_starts: int,
    event_name: str = "",
) -> float:
    if feature_row is None:
        return fallback_prob
    prior_starts = parse_float(feature_row.get("prior_starts")) or 0
    rolling_prob = parse_float(feature_row.get(MARKET_TO_FEATURE[market]))
    if rolling_prob is None:
        rolling_prob = parse_float(feature_row.get(MARKET_TO_FALLBACK_FEATURE[market]))
    if prior_starts >= min_prior_starts and rolling_prob is not None:
        recent_prob = shrink_probability(rolling_prob, fallback_prob, prior_starts)
        return blend_event_fit_probability(recent_prob, market, feature_row, fallback_prob, event_name)
    return fallback_prob


def shrink_probability(probability: float, fallback_prob: float, prior_starts: float, prior_strength: float = 8.0) -> float:
    return (probability * prior_starts + fallback_prob * prior_strength) / (prior_starts + prior_strength)


def event_is_open(event_name: str) -> bool:
    normalized = normalize_name(event_name)
    return "open championship" in normalized


def event_is_major(event_name: str) -> bool:
    normalized = normalize_name(event_name)
    return any(
        marker in normalized
        for marker in ["masters tournament", "pga championship", "us open", "open championship"]
    )


def event_fit_field(market: str, prefix: str) -> str:
    if market == "make_cut":
        return f"{prefix}_made_cut_rate"
    return f"{prefix}_{market}_rate"


def shrunk_event_rate(
    feature_row: dict[str, str],
    market: str,
    prefix: str,
    fallback_prob: float,
    prior_strength: float,
) -> Optional[float]:
    starts = parse_float(feature_row.get(f"{prefix}_starts")) or 0
    rate = parse_float(feature_row.get(event_fit_field(market, prefix)))
    if starts <= 0 or rate is None:
        return None
    return shrink_probability(rate, fallback_prob, starts, prior_strength=prior_strength)


def blend_event_fit_probability(
    recent_prob: float,
    market: str,
    feature_row: dict[str, str],
    fallback_prob: float,
    event_name: str,
) -> float:
    major_prob = shrunk_event_rate(feature_row, market, "major", fallback_prob, prior_strength=12)
    open_prob = shrunk_event_rate(feature_row, market, "open", fallback_prob, prior_strength=18)
    if event_is_open(event_name):
        if major_prob is not None and open_prob is not None:
            return 0.70 * recent_prob + 0.20 * major_prob + 0.10 * open_prob
        if major_prob is not None:
            return 0.80 * recent_prob + 0.20 * major_prob
        if open_prob is not None:
            return 0.90 * recent_prob + 0.10 * open_prob
    if event_is_major(event_name) and major_prob is not None:
        return 0.80 * recent_prob + 0.20 * major_prob
    return recent_prob


def win_strength(feature_row: Optional[dict[str, str]], rates: dict[str, float], event_name: str = "") -> float:
    if feature_row is None:
        return max(rates["winner"], 0.001)
    top5 = parse_float(feature_row.get("weighted_recent_top5_rate"))
    top10 = parse_float(feature_row.get("weighted_recent_top10_rate"))
    top20 = parse_float(feature_row.get("weighted_recent_top20_rate"))
    wins = parse_float(feature_row.get("weighted_recent_win_rate"))
    if top5 is None:
        top5 = parse_float(feature_row.get("recent_top5_rate"))
    if top10 is None:
        top10 = parse_float(feature_row.get("recent_top10_rate"))
    if top20 is None:
        top20 = parse_float(feature_row.get("recent_top20_rate"))
    if wins is None:
        wins = parse_float(feature_row.get("recent_win_rate"))
    prior_starts = parse_float(feature_row.get("prior_starts")) or 0
    top5 = shrink_probability(top5, rates["top5"], prior_starts) if top5 is not None else rates["top5"]
    top10 = shrink_probability(top10, rates["top10"], prior_starts) if top10 is not None else rates["top10"]
    top20 = shrink_probability(top20, rates["top20"], prior_starts) if top20 is not None else rates["top20"]
    wins = shrink_probability(wins, rates["winner"], prior_starts) if wins is not None else rates["winner"]
    top5 = blend_event_fit_probability(top5, "top5", feature_row, rates["top5"], event_name)
    top10 = blend_event_fit_probability(top10, "top10", feature_row, rates["top10"], event_name)
    top20 = blend_event_fit_probability(top20, "top20", feature_row, rates["top20"], event_name)
    wins = blend_event_fit_probability(wins, "winner", feature_row, rates["winner"], event_name)
    return max(0.45 * top5 + 0.25 * top10 + 0.20 * top20 + 0.10 * wins, 0.001)


def add_winner_probabilities(
    rows: list[dict[str, object]],
    feature_rows: list[Optional[dict[str, str]]],
    rates: dict[str, float],
    event_name: str = "",
) -> None:
    strengths = [win_strength(feature_row, rates, event_name=event_name) for feature_row in feature_rows]
    total = sum(strengths)
    if total <= 0:
        fallback = 1 / len(rows) if rows else 0
        for row in rows:
            row["winner_prob"] = fallback
        return
    for row, strength in zip(rows, strengths):
        row["winner_prob"] = strength / total


def build_current_event_rows(
    feature_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    event_date: Optional[str] = None,
    course_name: str = "",
    min_prior_starts: int = 3,
) -> tuple[list[dict[str, object]], list[str]]:
    event_name = infer_single_value(odds_rows, "event_name")
    season = infer_single_value(odds_rows, "season")
    event_date = event_date or captured_date(odds_rows)
    event_id = stable_id("event_current", season, event_name, event_date)
    course_id = stable_id("course_current", course_name) if course_name else ""
    rates = base_rates(feature_rows)
    latest_by_player = latest_features_by_player(feature_rows)

    rows: list[dict[str, object]] = []
    matched_features: list[Optional[dict[str, str]]] = []
    unmatched_players = []
    for player_name in odds_field(odds_rows):
        feature_row = None
        for key in player_lookup_keys(player_name):
            feature_row = latest_by_player.get(key)
            if feature_row is not None:
                break
        if feature_row is None:
            unmatched_players.append(player_name)
            player_id = stable_id("player_current", player_name)
        else:
            player_id = feature_row.get("player_id") or stable_id("player_current", player_name)
        matched_features.append(feature_row)

        record = {column: "" for column in RANKING_COLUMNS}
        record.update(
            {
                "event_id": event_id,
                "event_name": event_name,
                "event_date_start": event_date,
                "season": season,
                "course_id": course_id,
                "course_name": course_name,
                "player_id": player_id,
                "player_name": player_name,
                "model_type": "current_player_rolling",
            }
        )
        for market in ["make_cut", "top20", "top10", "top5"]:
            record[f"{market}_prob"] = probability_for_market(
                market,
                feature_row,
                fallback_prob=rates[market],
                min_prior_starts=min_prior_starts,
                event_name=event_name,
            )
        rows.append(record)

    add_winner_probabilities(rows, matched_features, rates, event_name=event_name)
    add_event_ranks(rows)
    return sorted(rows, key=lambda row: (int(row["top20_rank"] or 999999), str(row["player_name"]))), unmatched_players


def render_summary(rows: list[dict[str, object]], unmatched_players: list[str], top_n: int) -> str:
    lines = [
        "# Current Event Ranking Report",
        "",
        f"ranking_rows: {len(rows)}",
        f"unmatched_players_using_base_rates: {len(unmatched_players)}",
        "",
    ]
    if unmatched_players:
        lines.append("## Unmatched Players")
        lines.append("")
        for name in unmatched_players:
            lines.append(f"- {name}")
        lines.append("")
    lines.append(render_markdown(rows, max_events=1, top_n=top_n).strip())
    return "\n".join(lines).rstrip() + "\n"


def build_current_event_rankings(
    features_path: Path,
    odds_path: Path,
    output_dir: Path,
    event_date: Optional[str] = None,
    course_name: str = "",
    min_prior_starts: int = 3,
    top_n: int = 25,
) -> dict[str, object]:
    rows, unmatched_players = build_current_event_rows(
        read_csv(features_path),
        read_csv(odds_path),
        event_date=event_date,
        course_name=course_name,
        min_prior_starts=min_prior_starts,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "event_rankings.csv", RANKING_COLUMNS, rows)
    (output_dir / "report.md").write_text(render_summary(rows, unmatched_players, top_n), encoding="utf-8")
    return {"rankings": rows, "unmatched_players": unmatched_players}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="current-event-rankings")
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--odds", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--event-date")
    parser.add_argument("--course-name", default="")
    parser.add_argument("--min-prior-starts", type=int, default=3)
    parser.add_argument("--top-n", type=int, default=25)
    args = parser.parse_args(argv)

    build_current_event_rankings(
        args.features,
        args.odds,
        args.output_dir,
        event_date=args.event_date,
        course_name=args.course_name,
        min_prior_starts=args.min_prior_starts,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
