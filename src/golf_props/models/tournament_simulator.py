"""Simulate a stroke-play tournament from point-in-time player strengths."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Optional

import numpy as np

SIMULATION_COLUMNS = [
    "event_name",
    "event_date",
    "player_id",
    "player_name",
    "rounds_used",
    "strength_mean_relative",
    "strength_std_relative",
    "make_cut_prob",
    "top20_prob",
    "top10_prob",
    "top5_prob",
    "winner_prob",
    "expected_finish_if_made_cut",
    "median_finish_if_made_cut",
    "simulations",
    "seed",
]

INACTIVE_ENTRY_STATUSES = {"withdrawn", "wd", "out", "inactive"}

CUT_RULE_TOP_N_AND_TIES = "top_n_and_ties"
CUT_RULE_NO_CUT = "no_cut"
SUPPORTED_CUT_RULES = {CUT_RULE_TOP_N_AND_TIES, CUT_RULE_NO_CUT}


class TournamentSimulationError(ValueError):
    """Raised when a tournament field cannot be simulated."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise TournamentSimulationError(f"missing strength file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SIMULATION_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def active_strength_rows(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    active = []
    excluded = 0
    for row in rows:
        status = str(row.get("entry_status") or "").strip().casefold()
        if status in INACTIVE_ENTRY_STATUSES:
            excluded += 1
            continue
        active.append(row)
    return active, excluded


def median_rank(histogram: np.ndarray) -> Optional[int]:
    total = int(histogram.sum())
    if total == 0:
        return None
    threshold = (total + 1) // 2
    return int(np.searchsorted(np.cumsum(histogram), threshold) + 1)


def simulate_tournament_rows(
    strength_rows: list[dict[str, object]],
    event_name: str,
    event_date: str,
    simulations: int = 20000,
    seed: int = 20260729,
    cut_size: int = 65,
    cut_rule: str = CUT_RULE_TOP_N_AND_TIES,
    rounds: int = 4,
    cut_after_round: int = 2,
    batch_size: int = 2000,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if simulations <= 0:
        raise TournamentSimulationError("simulations must be positive")
    if cut_rule not in SUPPORTED_CUT_RULES:
        raise TournamentSimulationError(f"unsupported cut_rule: {cut_rule}")
    if cut_rule == CUT_RULE_TOP_N_AND_TIES and cut_size < 1:
        raise TournamentSimulationError(
            "cut_size must be positive for top_n_and_ties"
        )
    if rounds < 2 or not 0 < cut_after_round < rounds:
        raise TournamentSimulationError("invalid round/cut configuration")
    active_rows, excluded_rows = active_strength_rows(strength_rows)
    if len(active_rows) < 2:
        raise TournamentSimulationError("at least two active field rows are required")
    player_names = [str(row.get("player_name") or "").strip() for row in active_rows]
    if not all(player_names) or len(set(player_names)) != len(player_names):
        raise TournamentSimulationError("active field player names must be unique and nonblank")

    means = np.asarray(
        [float(row["shrunk_mean_relative"]) for row in active_rows],
        dtype=float,
    )
    standard_deviations = np.asarray(
        [float(row["shrunk_std_relative"]) for row in active_rows],
        dtype=float,
    )
    if np.any(~np.isfinite(means)) or np.any(~np.isfinite(standard_deviations)):
        raise TournamentSimulationError("strength inputs must be finite")
    if np.any(standard_deviations <= 0):
        raise TournamentSimulationError("strength standard deviations must be positive")

    rng = np.random.default_rng(seed)
    player_count = len(active_rows)
    if cut_rule == CUT_RULE_TOP_N_AND_TIES:
        effective_cut_size = min(cut_size, player_count)
    else:
        effective_cut_size = player_count
    cut_applied = cut_rule == CUT_RULE_TOP_N_AND_TIES
    make_cut_counts = np.zeros(player_count, dtype=np.int64)
    placement_counts = {
        20: np.zeros(player_count, dtype=np.int64),
        10: np.zeros(player_count, dtype=np.int64),
        5: np.zeros(player_count, dtype=np.int64),
    }
    winner_counts = np.zeros(player_count, dtype=np.int64)
    finish_histograms = np.zeros((player_count, player_count), dtype=np.int64)
    total_cut_count = 0

    completed = 0
    while completed < simulations:
        current_batch = min(batch_size, simulations - completed)
        performances = rng.normal(
            loc=means[None, :, None],
            scale=standard_deviations[None, :, None],
            size=(current_batch, player_count, rounds),
        )
        # A neutral 72 baseline makes the simulated scores discrete while
        # preserving relative rankings. Absolute course scoring is not claimed.
        scores = np.rint(72.0 - performances).astype(np.int16)
        two_round_scores = scores[:, :, :cut_after_round].sum(axis=2)
        if cut_rule == CUT_RULE_TOP_N_AND_TIES:
            cut_thresholds = np.partition(
                two_round_scores,
                effective_cut_size - 1,
                axis=1,
            )[:, effective_cut_size - 1]
            made_cut = two_round_scores <= cut_thresholds[:, None]
        else:
            made_cut = np.ones((current_batch, player_count), dtype=bool)
        make_cut_counts += made_cut.sum(axis=0)
        total_cut_count += int(made_cut.sum())

        final_scores = scores.sum(axis=2)
        masked_final_scores = np.where(made_cut, final_scores, 32767)
        for top_n, counts in placement_counts.items():
            slots = min(top_n, player_count)
            thresholds = np.partition(
                masked_final_scores,
                slots - 1,
                axis=1,
            )[:, slots - 1]
            counts += (made_cut & (final_scores <= thresholds[:, None])).sum(axis=0)

        tie_breakers = rng.random((current_batch, player_count)) * 0.001
        winner_indices = np.argmin(
            np.where(made_cut, final_scores + tie_breakers, np.inf),
            axis=1,
        )
        winner_counts += np.bincount(winner_indices, minlength=player_count)

        for simulation_index in range(current_batch):
            made_indices = np.flatnonzero(made_cut[simulation_index])
            made_scores = final_scores[simulation_index, made_indices]
            unique_scores, score_counts = np.unique(made_scores, return_counts=True)
            competition_ranks = np.concatenate(
                ([1], 1 + np.cumsum(score_counts[:-1]))
            )
            rank_by_score = dict(zip(unique_scores.tolist(), competition_ranks.tolist()))
            for player_index, score in zip(made_indices, made_scores):
                rank = int(rank_by_score[int(score)])
                finish_histograms[player_index, rank - 1] += 1
        completed += current_batch

    output = []
    for index, source in enumerate(active_rows):
        made_count = int(make_cut_counts[index])
        histogram = finish_histograms[index]
        expected_finish = (
            float(
                sum((rank + 1) * int(count) for rank, count in enumerate(histogram))
                / made_count
            )
            if made_count
            else None
        )
        output.append(
            {
                "event_name": event_name,
                "event_date": event_date,
                "player_id": source.get("player_id", ""),
                "player_name": source.get("player_name", ""),
                "rounds_used": source.get("rounds_used", ""),
                "strength_mean_relative": source.get("shrunk_mean_relative", ""),
                "strength_std_relative": source.get("shrunk_std_relative", ""),
                "make_cut_prob": round(made_count / simulations, 6),
                "top20_prob": round(
                    int(placement_counts[20][index]) / simulations,
                    6,
                ),
                "top10_prob": round(
                    int(placement_counts[10][index]) / simulations,
                    6,
                ),
                "top5_prob": round(
                    int(placement_counts[5][index]) / simulations,
                    6,
                ),
                "winner_prob": round(int(winner_counts[index]) / simulations, 6),
                "expected_finish_if_made_cut": (
                    round(expected_finish, 3) if expected_finish is not None else ""
                ),
                "median_finish_if_made_cut": median_rank(histogram),
                "simulations": simulations,
                "seed": seed,
            }
        )

    output.sort(
        key=lambda row: (
            -float(row["winner_prob"]),
            -float(row["top20_prob"]),
            str(row["player_name"]),
        )
    )
    summary = {
        "event_name": event_name,
        "event_date": event_date,
        "field_size": player_count,
        "inactive_rows_excluded": excluded_rows,
        "simulations": simulations,
        "seed": seed,
        "rounds": rounds,
        "cut_after_round": cut_after_round,
        "cut_rule": cut_rule,
        "cut_applied": cut_applied,
        "configured_cut_size": cut_size,
        "cut_size": effective_cut_size,
        "average_players_making_cut": round(total_cut_count / simulations, 6),
        "sum_winner_probability": round(
            sum(float(row["winner_prob"]) for row in output),
            6,
        ),
        "sum_top5_probability": round(
            sum(float(row["top5_prob"]) for row in output),
            6,
        ),
        "sum_top10_probability": round(
            sum(float(row["top10_prob"]) for row in output),
            6,
        ),
        "sum_top20_probability": round(
            sum(float(row["top20_prob"]) for row in output),
            6,
        ),
    }
    return output, summary


def render_report(
    rows: list[dict[str, object]],
    summary: dict[str, object],
    top_n: int = 25,
) -> str:
    lines = ["# Performance-Only Tournament Simulation", ""]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    if str(summary.get("cut_rule")) == CUT_RULE_NO_CUT:
        lines.extend(
            [
                "",
                "This event has no cut: every active player advances to all four",
                "rounds. make_cut_prob is structural (1.0) and is not an empirical",
                "prediction target.",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "No sportsbook prices are used in this report.",
            "",
            "| Player | Strength | Cut | Top 20 | Top 10 | Top 5 | Win |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows[:top_n]:
        lines.append(
            "| {player} | {strength:.3f} | {cut:.3f} | {top20:.3f} | "
            "{top10:.3f} | {top5:.3f} | {win:.3f} |".format(
                player=row["player_name"],
                strength=float(row["strength_mean_relative"]),
                cut=float(row["make_cut_prob"]),
                top20=float(row["top20_prob"]),
                top10=float(row["top10_prob"]),
                top5=float(row["top5_prob"]),
                win=float(row["winner_prob"]),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def run_tournament_simulation(
    strength_path: Path,
    output_dir: Path,
    event_name: str,
    event_date: str,
    simulations: int = 20000,
    seed: int = 20260729,
    cut_size: int = 65,
    cut_rule: str = CUT_RULE_TOP_N_AND_TIES,
    top_n: int = 25,
) -> dict[str, object]:
    rows, summary = simulate_tournament_rows(
        read_csv(strength_path),
        event_name,
        event_date,
        simulations=simulations,
        seed=seed,
        cut_size=cut_size,
        cut_rule=cut_rule,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.csv"
    report_path = output_dir / "report.md"
    summary_path = output_dir / "summary.json"
    write_csv(predictions_path, rows)
    report_path.write_text(
        render_report(rows, summary, top_n=top_n),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "rows": rows,
        "summary": summary,
        "predictions_path": predictions_path,
        "report_path": report_path,
        "summary_path": summary_path,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="simulate-tournament")
    parser.add_argument("--strengths", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-date", required=True)
    parser.add_argument("--simulations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--cut-size", type=int, default=65)
    parser.add_argument(
        "--cut-rule",
        choices=sorted(SUPPORTED_CUT_RULES),
        default=CUT_RULE_TOP_N_AND_TIES,
    )
    parser.add_argument("--top-n", type=int, default=25)
    args = parser.parse_args(argv)

    result = run_tournament_simulation(
        args.strengths,
        args.output_dir,
        args.event_name,
        args.event_date,
        simulations=args.simulations,
        seed=args.seed,
        cut_size=args.cut_size,
        cut_rule=args.cut_rule,
        top_n=args.top_n,
    )
    print(f"simulation_predictions={result['predictions_path']}")
    print(f"simulation_report={result['report_path']}")
    print(f"simulation_rows={len(result['rows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
