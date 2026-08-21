"""Join model rankings to sportsbook odds and compute simple value signals."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Optional

from golf_props.normalization.manual_odds import american_to_decimal

MARKET_PROB_COLUMNS = {
    "winner": "winner_prob",
    "make_cut": "make_cut_prob",
    "top20": "top20_prob",
    "top10": "top10_prob",
    "top5": "top5_prob",
}

VALUE_COLUMNS = [
    "captured_at_utc",
    "sportsbook",
    "event_id",
    "event_name",
    "season",
    "player_id",
    "player_name",
    "market_type",
    "line",
    "price_american",
    "price_decimal",
    "model_prob",
    "market_implied_prob",
    "edge",
    "expected_value_per_1",
    "model_rank",
    "value_tier",
    "confidence_note",
    "source_url",
]


class ValueReportError(ValueError):
    """Raised when value report inputs cannot be joined."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ValueReportError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_float(value: object) -> Optional[float]:
    if value in {None, ""}:
        return None
    return float(value)


def parse_int(value: object) -> Optional[int]:
    if value in {None, ""}:
        return None
    return int(str(value).replace("+", ""))


def normalize_text(value: object) -> str:
    return str(value or "").strip().casefold()


def join_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        normalize_text(row.get("season")),
        normalize_text(row.get("event_name")),
        normalize_text(row.get("player_name")),
    )


def expected_value_per_1(model_prob: float, price_american: int) -> float:
    decimal = american_to_decimal(price_american)
    return model_prob * (decimal - 1) - (1 - model_prob)


def parse_rank(value: object) -> Optional[int]:
    if value in {None, ""}:
        return None
    return int(value)


def classify_value_row(market_type: str, model_prob: float, edge: float, rank: Optional[int]) -> tuple[str, str]:
    if edge <= 0:
        return "market_favored_or_no_edge", "Market prices player stronger than model."
    if market_type == "winner":
        if rank is not None and rank <= 15 and model_prob >= 0.02:
            return "winner_core_value", "Evidence-backed outright contender with positive edge."
        return "winner_speculative", "Positive edge, but outright probability or rank is thinner."
    if market_type == "make_cut":
        return "make_cut_value", "Positive edge in make-cut market."
    if market_type in {"top5", "top10", "top20"}:
        if rank is not None and rank <= 30:
            return "placement_value", "Positive edge in placement market."
        return "placement_speculative", "Positive placement edge, but model rank is thin."
    return "unclassified_positive_edge", "Positive edge in supported market."


def build_value_rows(
    rankings: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    rankings_by_key = {join_key(row): row for row in rankings}
    value_rows: list[dict[str, object]] = []

    for odds in odds_rows:
        market_type = odds.get("market_type", "")
        prob_column = MARKET_PROB_COLUMNS.get(market_type)
        if prob_column is None:
            continue
        ranking = rankings_by_key.get(join_key(odds))
        if ranking is None:
            continue
        model_prob = parse_float(ranking.get(prob_column))
        market_prob = parse_float(odds.get("implied_probability"))
        price_american = parse_int(odds.get("price_american"))
        if model_prob is None or market_prob is None or price_american is None:
            continue

        rank = ranking.get(f"{market_type}_rank")
        edge = model_prob - market_prob
        value_tier, confidence_note = classify_value_row(
            market_type,
            model_prob,
            edge,
            parse_rank(rank),
        )
        value_rows.append(
            {
                "captured_at_utc": odds.get("captured_at_utc"),
                "sportsbook": odds.get("sportsbook"),
                "event_id": ranking.get("event_id"),
                "event_name": ranking.get("event_name"),
                "season": ranking.get("season"),
                "player_id": ranking.get("player_id"),
                "player_name": ranking.get("player_name"),
                "market_type": market_type,
                "line": odds.get("line"),
                "price_american": price_american,
                "price_decimal": odds.get("price_decimal"),
                "model_prob": round(model_prob, 6),
                "market_implied_prob": round(market_prob, 6),
                "edge": round(edge, 6),
                "expected_value_per_1": round(expected_value_per_1(model_prob, price_american), 6),
                "model_rank": rank,
                "value_tier": value_tier,
                "confidence_note": confidence_note,
                "source_url": odds.get("source_url"),
            }
        )

    return sorted(
        value_rows,
        key=lambda row: (
            -float(row["edge"]),
            str(row["event_name"]),
            str(row["market_type"]),
            str(row["player_name"]),
        ),
    )


def render_markdown(value_rows: list[dict[str, object]], top_n: int) -> str:
    lines = ["# Value Report", ""]
    if not value_rows:
        lines.append("No joined odds/model rows.")
        return "\n".join(lines) + "\n"

    sections = [
        ("Winner Core Value", "winner_core_value"),
        ("Placement Value", "placement_value"),
        ("Make Cut Value", "make_cut_value"),
        ("Speculative Winner Longshots", "winner_speculative"),
        ("Speculative Placement", "placement_speculative"),
        ("Market Favored / No Edge", "market_favored_or_no_edge"),
    ]
    for title, tier in sections:
        rows = [row for row in value_rows if row.get("value_tier") == tier]
        if top_n > 0:
            rows = rows[:top_n]
        lines.extend([f"## {title}", ""])
        if not rows:
            lines.extend(["No rows.", ""])
            continue
        lines.extend(table_lines(rows))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def table_lines(rows: list[dict[str, object]]) -> list[str]:
    lines = [
        "| Edge | EV/$1 | Player | Market | Book | Model | Market | Odds | Rank | Note |",
        "|---:|---:|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {edge:.3f} | {ev:.3f} | {player} | {market} | {book} | {model:.3f} | {market_prob:.3f} | {odds} | {rank} | {note} |".format(
                edge=float(row["edge"]),
                ev=float(row["expected_value_per_1"]),
                player=row["player_name"],
                market=row["market_type"],
                book=row["sportsbook"],
                model=float(row["model_prob"]),
                market_prob=float(row["market_implied_prob"]),
                odds=row["price_american"],
                rank=row.get("model_rank") or "",
                note=row.get("confidence_note") or "",
            )
        )
    return lines


def build_value_report(
    rankings_path: Path,
    odds_path: Path,
    output_dir: Path,
    top_n: int = 50,
) -> dict[str, list[dict[str, object]]]:
    rankings = read_csv(rankings_path)
    odds_rows = read_csv(odds_path)
    value_rows = build_value_rows(rankings, odds_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "value_report.csv", VALUE_COLUMNS, value_rows)
    (output_dir / "report.md").write_text(render_markdown(value_rows, top_n=top_n), encoding="utf-8")

    return {"value_rows": value_rows}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="value-report")
    parser.add_argument("--rankings", required=True, type=Path)
    parser.add_argument("--odds", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args(argv)

    build_value_report(args.rankings, args.odds, args.output_dir, top_n=args.top_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
