"""Event-level review of the genuinely prospective frozen golf forecasts.

The unit of inference is the *event*.  A 120-player field is one tournament, not
120 independent observations.  This module therefore reports equal-event means
with an event-level bootstrap and an exact sign test, and keeps the common
row-weighted pooling only as a descriptive number.

It reads already preserved, hash-pinned artifacts:

* ``prospective_forecasts/<event_key>/{predictions,strengths,run_manifest}.csv/json``
* ``forecast_grading/<event_key>/graded_predictions.csv``

It never re-grades, never retunes, never reads a sportsbook price into the
performance comparison, and never writes to either input directory.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

TARGETS = ("top20", "top10", "top5", "winner")
TARGET_PROB_COLUMN = {
    "top20": "top20_prob",
    "top10": "top10_prob",
    "top5": "top5_prob",
    "winner": "winner_prob",
}
REPRODUCTION_TOLERANCE = 1e-6
LOG_LOSS_CLIP = 1e-9
ECE_BINS = 10


class ProspectiveReviewError(ValueError):
    """Raised when the preserved cohort cannot be reviewed safely."""


@dataclass(frozen=True)
class GradedRow:
    player_id: str
    player_name: str
    target: str
    actual: int
    model_prob: float
    baseline_prob: float
    finish_position: Optional[float]


@dataclass(frozen=True)
class EventBundle:
    event_key: str
    archive_dir: Path
    grading_dir: Path
    event_name: str
    event_date: str
    graded_rows: dict[str, list[GradedRow]]
    predictions: dict[str, dict[str, float]]
    strength_rows: list[dict[str, str]]
    run_manifest: dict[str, Any]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ProspectiveReviewError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveReviewError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ProspectiveReviewError(f"expected a JSON object: {path}")
    return value


def load_event_bundle(archive_dir: Path, grading_dir: Path) -> EventBundle:
    archive_dir = Path(archive_dir)
    grading_dir = Path(grading_dir)
    run_manifest = _read_json(archive_dir / "run_manifest.json")
    eligibility = run_manifest.get("eligibility") or {}
    if eligibility.get("classification") != "prospective_forecast":
        raise ProspectiveReviewError(
            f"{archive_dir.name}: not a prospective forecast archive"
        )
    if run_manifest.get("pre_start_verified") is not True:
        raise ProspectiveReviewError(f"{archive_dir.name}: archive is not pre-start verified")

    predictions: dict[str, dict[str, float]] = {}
    for row in _read_csv(archive_dir / "predictions.csv"):
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            raise ProspectiveReviewError(f"{archive_dir.name}: prediction without player_id")
        if player_id in predictions:
            raise ProspectiveReviewError(
                f"{archive_dir.name}: duplicate prediction for {player_id}"
            )
        predictions[player_id] = {column: float(row[column]) for column in TARGET_PROB_COLUMN.values()}

    grading_manifest = _read_json(grading_dir / "grading_manifest.json")
    if grading_manifest.get("forecast_classification") != "prospective_forecast":
        raise ProspectiveReviewError(f"{grading_dir.name}: grade is not prospective")
    if str(grading_manifest.get("event_name") or "") != str(
        run_manifest.get("event_name") or ""
    ):
        raise ProspectiveReviewError(
            f"{grading_dir.name}: grade event name does not match the archive"
        )

    grouped: dict[str, list[GradedRow]] = {target: [] for target in TARGETS}
    for row in _read_csv(grading_dir / "graded_predictions.csv"):
        target = str(row.get("target") or "").strip()
        if target not in grouped:
            continue
        player_id = str(row.get("player_id") or "").strip()
        if player_id not in predictions:
            raise ProspectiveReviewError(
                f"{grading_dir.name}: graded player {player_id!r} not in the archive"
            )
        model_prob = float(row["model_prob"])
        archived_prob = predictions[player_id][TARGET_PROB_COLUMN[target]]
        if abs(model_prob - archived_prob) > REPRODUCTION_TOLERANCE:
            raise ProspectiveReviewError(
                f"{grading_dir.name}: graded model_prob disagrees with the archive "
                f"for {row.get('player_name')!r} / {target}"
            )
        position_text = str(row.get("finish_position") or "").strip()
        grouped[target].append(
            GradedRow(
                player_id=player_id,
                player_name=str(row.get("player_name") or ""),
                target=target,
                actual=int(row["actual"]),
                model_prob=archived_prob,
                baseline_prob=float(row["baseline_prob"]),
                finish_position=float(position_text) if position_text else None,
            )
        )
    if not all(grouped[target] for target in TARGETS):
        raise ProspectiveReviewError(f"{grading_dir.name}: a graded target has no rows")

    return EventBundle(
        event_key=archive_dir.name,
        archive_dir=archive_dir,
        grading_dir=grading_dir,
        event_name=str(run_manifest.get("event_name") or ""),
        event_date=str(eligibility.get("event_date") or ""),
        graded_rows=grouped,
        predictions=predictions,
        strength_rows=_read_csv(archive_dir / "strengths.csv"),
        run_manifest=run_manifest,
    )


def brier(probabilities: Iterable[float], outcomes: Iterable[int]) -> float:
    pairs = list(zip(probabilities, outcomes))
    if not pairs:
        raise ProspectiveReviewError("brier needs at least one pair")
    return sum((probability - outcome) ** 2 for probability, outcome in pairs) / len(pairs)


def log_loss(probabilities: Iterable[float], outcomes: Iterable[int]) -> float:
    pairs = list(zip(probabilities, outcomes))
    if not pairs:
        raise ProspectiveReviewError("log_loss needs at least one pair")
    total = 0.0
    for probability, outcome in pairs:
        clipped = min(max(float(probability), LOG_LOSS_CLIP), 1.0 - LOG_LOSS_CLIP)
        total += -(
            outcome * math.log(clipped) + (1 - outcome) * math.log(1.0 - clipped)
        )
    return total / len(pairs)


def expected_calibration_error(
    probabilities: list[float], outcomes: list[int], bins: int = ECE_BINS
) -> float:
    if len(probabilities) != len(outcomes):
        raise ProspectiveReviewError("ECE inputs must have equal length")
    if not probabilities:
        return 0.0
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probability, outcome in zip(probabilities, outcomes):
        index = min(int(float(probability) * bins), bins - 1)
        buckets[max(index, 0)].append((float(probability), int(outcome)))
    total = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        mean_probability = sum(item[0] for item in bucket) / len(bucket)
        mean_outcome = sum(item[1] for item in bucket) / len(bucket)
        total += (
            len(bucket) / len(probabilities) * abs(mean_probability - mean_outcome)
        )
    return total


def score_rows(
    rows: list[GradedRow],
    probability: str = "model_prob",
    challenger: Optional[dict[str, dict[str, float]]] = None,
) -> dict[str, Any]:
    if probability == "challenger" and challenger is None:
        raise ProspectiveReviewError("no challenger probabilities supplied")
    if probability == "challenger":
        probabilities = [challenger[row.player_id][row.target] for row in rows]  # type: ignore[index]
    else:
        probabilities = [float(getattr(row, probability)) for row in rows]
    outcomes = [row.actual for row in rows]
    mean_probability = sum(probabilities) / len(probabilities)
    mean_outcome = sum(outcomes) / len(outcomes)
    return {
        "graded_players": len(rows),
        "actual_count": sum(outcomes),
        "actual_rate": round(mean_outcome, 6),
        "expected_count": round(sum(probabilities), 6),
        "mean_probability": round(mean_probability, 6),
        "calibration_gap": round(mean_probability - mean_outcome, 6),
        "brier": round(brier(probabilities, outcomes), 9),
        "log_loss": round(log_loss(probabilities, outcomes), 9),
        "ece": round(expected_calibration_error(probabilities, outcomes), 9),
    }


def _sign_test_p(positive: int, total: int) -> float:
    if total == 0:
        return 1.0
    tail = max(positive, total - positive)
    probability = sum(math.comb(total, count) for count in range(tail, total + 1))
    return min(1.0, 2 * probability / (2**total))


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ProspectiveReviewError("cannot take a percentile of no values")
    index = min(max(int(round(quantile * (len(sorted_values) - 1))), 0), len(sorted_values) - 1)
    return sorted_values[index]


def event_bootstrap(
    differences: list[float], samples: int = 10000, seed: int = 20261103
) -> dict[str, float]:
    """Paired bootstrap that resamples whole events, never player rows."""
    if not differences:
        raise ProspectiveReviewError("bootstrap needs at least one event")
    if samples <= 0:
        raise ProspectiveReviewError("bootstrap samples must be positive")
    generator = random.Random(seed)
    count = len(differences)
    means = []
    for _ in range(samples):
        draw = [differences[generator.randrange(count)] for _ in range(count)]
        means.append(sum(draw) / count)
    means.sort()
    return {
        "samples": samples,
        "seed": seed,
        "mean": round(sum(differences) / count, 9),
        "ci95_low": round(_percentile(means, 0.025), 9),
        "ci95_high": round(_percentile(means, 0.975), 9),
        "ci90_low": round(_percentile(means, 0.05), 9),
        "ci90_high": round(_percentile(means, 0.95), 9),
    }


def _target_summary(
    values: list[float],
    labels: list[str],
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    positive = sum(1 for value in values if value > 0)
    bootstrap = event_bootstrap(values, samples=bootstrap_samples, seed=seed)
    return {
        "events": len(values),
        "equal_event_mean": round(sum(values) / len(values), 9),
        "median": round(sorted(values)[len(values) // 2], 9),
        "positive_events": positive,
        "sign_test_p_two_sided": round(_sign_test_p(positive, len(values)), 6),
        "bootstrap": bootstrap,
        "per_event": {label: round(value, 9) for label, value in zip(labels, values)},
    }


def reproduce_incumbent(bundle: EventBundle) -> dict[str, Any]:
    """Re-run the unchanged simulator from the archived strengths."""
    from golf_props.models.tournament_simulator import simulate_tournament_rows

    structure = bundle.run_manifest.get("event_structure") or {}
    summary = bundle.run_manifest.get("simulation_summary") or {}
    rows, _ = simulate_tournament_rows(
        bundle.strength_rows,
        event_name=bundle.event_name,
        event_date=bundle.event_date,
        simulations=int(summary.get("simulations") or 20000),
        seed=int(bundle.run_manifest.get("seed") or 20260729),
        cut_size=int(
            structure.get("effective_advancing_size")
            or structure.get("frozen_manifest_cut_size")
            or 65
        ),
        cut_rule=str(structure.get("cut_rule") or "top_n_and_ties"),
    )
    reproduced = {
        str(row["player_id"]): {
            column: float(row[column]) for column in TARGET_PROB_COLUMN.values()
        }
        for row in rows
    }
    worst = 0.0
    missing = 0
    for player_id, archived in bundle.predictions.items():
        if player_id not in reproduced:
            missing += 1
            continue
        for column, value in archived.items():
            worst = max(worst, abs(value - reproduced[player_id][column]))
    return {
        "archive_players": len(bundle.predictions),
        "reproduced_players": len(reproduced),
        "missing_reproduced_players": missing,
        "max_abs_probability_difference": round(worst, 12),
        "within_tolerance": missing == 0 and worst <= REPRODUCTION_TOLERANCE,
        "tolerance": REPRODUCTION_TOLERANCE,
    }


def review_events(
    bundles: list[EventBundle],
    *,
    bootstrap_samples: int = 10000,
    seed: int = 20261103,
    challenger: Optional[dict[str, dict[str, dict[str, float]]]] = None,
    challenger_manifest: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compare incumbent/baseline (and optionally one challenger) by event."""
    if not bundles:
        raise ProspectiveReviewError("no prospective event bundles supplied")
    labels = [bundle.event_key for bundle in bundles]
    per_event: dict[str, Any] = {}
    reproductions: dict[str, Any] = {}
    for bundle in bundles:
        if bundle.strength_rows and (bundle.run_manifest.get("simulation_summary") or {}):
            reproductions[bundle.event_key] = reproduce_incumbent(bundle)
        else:
            reproductions[bundle.event_key] = {
                "skipped": "no archived strengths/simulation summary in this bundle"
            }
        event_block: dict[str, Any] = {
            "event_name": bundle.event_name,
            "event_date": bundle.event_date,
            "graded_players": {
                target: len(bundle.graded_rows[target]) for target in TARGETS
            },
            "targets": {},
        }
        for target in TARGETS:
            rows = bundle.graded_rows[target]
            model = score_rows(rows, "model_prob")
            baseline = score_rows(rows, "baseline_prob")
            target_block = {
                "model": model,
                "baseline": baseline,
                "brier_improvement_vs_baseline": round(
                    baseline["brier"] - model["brier"], 9
                ),
                "log_loss_improvement_vs_baseline": round(
                    baseline["log_loss"] - model["log_loss"], 9
                ),
            }
            if challenger is not None and bundle.event_key in challenger:
                challenger_scores = score_rows(
                    rows, "challenger", challenger[bundle.event_key]
                )
                target_block["challenger"] = challenger_scores
                target_block["brier_improvement_challenger_vs_incumbent"] = round(
                    model["brier"] - challenger_scores["brier"], 9
                )
                target_block["log_loss_improvement_challenger_vs_incumbent"] = round(
                    model["log_loss"] - challenger_scores["log_loss"], 9
                )
            event_block["targets"][target] = target_block
        per_event[bundle.event_key] = event_block

    pooled: dict[str, Any] = {}
    event_level: dict[str, Any] = {}
    for target in TARGETS:
        all_rows = [row for bundle in bundles for row in bundle.graded_rows[target]]
        pooled[target] = {
            "graded_rows": len(all_rows),
            "model": score_rows(all_rows, "model_prob"),
            "baseline": score_rows(all_rows, "baseline_prob"),
            "row_weighted_brier_improvement_vs_baseline": round(
                score_rows(all_rows, "baseline_prob")["brier"]
                - score_rows(all_rows, "model_prob")["brier"],
                9,
            ),
        }
        if challenger is not None:
            # Pooled challenger rows use exactly the incumbent graded membership.
            challenger_probs = []
            for bundle in bundles:
                for row in bundle.graded_rows[target]:
                    challenger_probs.append(challenger[bundle.event_key][row.player_id][target])
            outcomes = [row.actual for bundle in bundles for row in bundle.graded_rows[target]]
            pooled[target]["challenger"] = {
                "brier": round(brier(challenger_probs, outcomes), 9),
                "log_loss": round(log_loss(challenger_probs, outcomes), 9),
            }
        improvements = [
            per_event[key]["targets"][target]["brier_improvement_vs_baseline"]
            for key in labels
        ]
        event_level[target] = {
            "model_brier_equal_event_mean": round(
                sum(per_event[key]["targets"][target]["model"]["brier"] for key in labels)
                / len(labels),
                9,
            ),
            "baseline_brier_equal_event_mean": round(
                sum(
                    per_event[key]["targets"][target]["baseline"]["brier"]
                    for key in labels
                )
                / len(labels),
                9,
            ),
            "calibration_equal_event": {
                "model_ece_mean": round(
                    sum(
                        per_event[key]["targets"][target]["model"]["ece"]
                        for key in labels
                    )
                    / len(labels),
                    9,
                ),
                "model_gap_mean": round(
                    sum(
                        per_event[key]["targets"][target]["model"]["calibration_gap"]
                        for key in labels
                    )
                    / len(labels),
                    9,
                ),
                "baseline_ece_mean": round(
                    sum(
                        per_event[key]["targets"][target]["baseline"]["ece"]
                        for key in labels
                    )
                    / len(labels),
                    9,
                ),
                "baseline_gap_mean": round(
                    sum(
                        per_event[key]["targets"][target]["baseline"][
                            "calibration_gap"
                        ]
                        for key in labels
                    )
                    / len(labels),
                    9,
                ),
            },
            "brier_improvement": _target_summary(
                improvements, labels, bootstrap_samples, seed
            ),
        }
        if challenger is not None:
            challenger_improvements = [
                per_event[key]["targets"][target][
                    "brier_improvement_challenger_vs_incumbent"
                ]
                for key in labels
            ]
            event_level[target]["challenger_vs_incumbent"] = _target_summary(
                challenger_improvements, labels, bootstrap_samples, seed
            )
            challenger_ll = [
                per_event[key]["targets"][target][
                    "log_loss_improvement_challenger_vs_incumbent"
                ]
                for key in labels
            ]
            event_level[target]["challenger_log_loss_improvement"] = _target_summary(
                challenger_ll, labels, bootstrap_samples, seed
            )

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": (now or datetime.now(timezone.utc)).isoformat(),
        "unit_of_inference": "event",
        "cohort": {
            "events": labels,
            "n_events": len(labels),
            "targets": list(TARGETS),
            "graded_rows_per_target": {
                target: sum(len(bundle.graded_rows[target]) for bundle in bundles)
                for target in TARGETS
            },
            "note": (
                "Players within one event are dependent. Equal-event means are "
                "the inference unit; row-weighted pooling is descriptive only."
            ),
        },
        "frozen_inputs": {
            key: {
                "event_name": bundle.event_name,
                "event_date": bundle.event_date,
                "run_manifest": str(bundle.archive_dir / "run_manifest.json"),
                "grading_manifest": str(bundle.grading_dir / "grading_manifest.json"),
                "seed": bundle.run_manifest.get("seed"),
                "simulations": (bundle.run_manifest.get("simulation_summary") or {}).get(
                    "simulations"
                ),
                "frozen_parameters": bundle.run_manifest.get("frozen_parameters"),
            }
            for key, bundle in zip(labels, bundles)
        },
        "reproduction": reproductions,
        "per_event": per_event,
        "pooled_row_weighted": pooled,
        "event_level": event_level,
    }
    if challenger is not None:
        report["challenger"] = {
            "manifest": challenger_manifest or {},
            "decision": challenger_decision(report),
        }
    return report


def challenger_decision(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the criteria frozen in CRITERIA_FREEZE.md; never activates."""
    n_events = int(report["cohort"]["n_events"])
    reasons: list[str] = []
    degradations = []
    for target in TARGETS:
        summary = report["event_level"][target]["challenger_vs_incumbent"]
        if summary["equal_event_mean"] < -0.001:
            degradations.append(
                f"{target} equal-event mean improvement "
                f"{summary['equal_event_mean']:+.6f} < -0.001"
            )
    top20 = report["event_level"]["top20"]["challenger_vs_incumbent"]
    if top20["equal_event_mean"] <= 0:
        reasons.append("top20 primary equal-event improvement is not positive")
    reasons.extend(degradations)
    if reasons:
        verdict = "KEEP"
    elif n_events < 8:
        reasons.append(f"only {n_events} paired prospective events; 8 required")
        verdict = "FORWARD_ONLY"
    elif top20["positive_events"] < 6:
        reasons.append("fewer than 6 of 8 events improve on top20")
        verdict = "FORWARD_ONLY"
    elif top20["bootstrap"]["ci90_low"] <= 0:
        reasons.append("event-bootstrap 90% CI includes zero")
        verdict = "FORWARD_ONLY"
    else:
        verdict = "PROMOTE_CANDIDATE"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "activation": "none",
        "requires_independent_review": True,
        "note": (
            "PROMOTE_CANDIDATE would still require an exact reviewed release and "
            "a separate activation decision; no path here activates anything."
        ),
    }


def _table_row(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def render_markdown(report: dict[str, Any]) -> str:
    labels = report["cohort"]["events"]
    lines = [
        "# Prospective golf event review",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        f"- Inference unit: **event** (n = {report['cohort']['n_events']})",
        "- Row-weighted numbers are descriptive only; players inside one event "
        "are dependent.",
        "",
        "## Cohort",
        "",
        _table_row(["event_key", "event", "date", "graded rows per target"]),
        _table_row(["---", "---", "---", "---"]),
    ]
    for key in labels:
        block = report["per_event"][key]
        graded = ", ".join(
            f"{target}={block['graded_players'][target]}" for target in TARGETS
        )
        lines.append(
            _table_row([f"`{key}`", block["event_name"], block["event_date"], graded])
        )
    lines.extend(
        [
            "",
            "## Incumbent versus declared baselines (Brier)",
            "",
            _table_row(
                ["target", "equal-event model", "equal-event structural",
                 "mean improvement", "positive events", "sign p", "90% event CI"]
            ),
            _table_row(["---"] * 7),
        ]
    )
    for target in TARGETS:
        summary = report["event_level"][target]["brier_improvement"]
        lines.append(
            _table_row(
                [
                    target,
                    f"{report['event_level'][target]['model_brier_equal_event_mean']:.6f}",
                    f"{report['event_level'][target]['baseline_brier_equal_event_mean']:.6f}",
                    f"{summary['equal_event_mean']:+.6f}",
                    f"{summary['positive_events']}/{summary['events']}",
                    f"{summary['sign_test_p_two_sided']:.3f}",
                    f"[{summary['bootstrap']['ci90_low']:+.6f}, "
                    f"{summary['bootstrap']['ci90_high']:+.6f}]",
                ]
            )
        )
    lines.extend(
        [
            "",
            "## Calibration (equal-event means; pooled rows are descriptive)",
            "",
            _table_row(
                ["target", "eq-event model ECE", "eq-event model gap",
                 "eq-event baseline ECE", "pooled model ECE", "pooled model gap"]
            ),
            _table_row(["---"] * 6),
        ]
    )
    for target in TARGETS:
        pooled = report["pooled_row_weighted"][target]
        calibration = report["event_level"][target]["calibration_equal_event"]
        lines.append(
            _table_row(
                [
                    target,
                    f"{calibration['model_ece_mean']:.6f}",
                    f"{calibration['model_gap_mean']:+.6f}",
                    f"{calibration['baseline_ece_mean']:.6f}",
                    f"{pooled['model']['ece']:.6f}",
                    f"{pooled['model']['calibration_gap']:+.6f}",
                ]
            )
        )
    if "challenger" in report:
        challenger = report["challenger"]
        decision = challenger["decision"]
        lines.extend(
            [
                "",
                "## Cold-start uncertainty challenger (disabled)",
                "",
                f"- Challenger: `{(challenger['manifest'] or {}).get('challenger_id', 'cold_start_variance_v1')}`",
                f"- Verdict: **{decision['verdict']}**",
                f"- Activation: `{decision['activation']}`",
                "- Reasons: " + ("; ".join(decision["reasons"]) or "none"),
                "",
                _table_row(
                    ["target", "incumbent Brier", "challenger Brier",
                     "mean improvement", "positive events", "90% event CI"]
                ),
                _table_row(["---"] * 6),
            ]
        )
        for target in TARGETS:
            summary = report["event_level"][target]["challenger_vs_incumbent"]
            lines.append(
                _table_row(
                    [
                        target,
                        f"{report['event_level'][target]['model_brier_equal_event_mean']:.6f}",
                        f"{_challenger_equal_event_mean(report, target):.6f}",
                        f"{summary['equal_event_mean']:+.6f}",
                        f"{summary['positive_events']}/{summary['events']}",
                        f"[{summary['bootstrap']['ci90_low']:+.6f}, "
                        f"{summary['bootstrap']['ci90_high']:+.6f}]",
                    ]
                )
            )
    lines.extend(["", "## Incumbent reproduction gate", "", _table_row(
        ["event", "max |delta p|", "within 1e-6", "missing players"]
    ), _table_row(["---"] * 4)])
    for key in labels:
        gate = report["reproduction"][key]
        if "max_abs_probability_difference" not in gate:
            lines.append(
                _table_row([f"`{key}`", "skipped", "n/a", gate.get("skipped", "")])
            )
            continue
        lines.append(
            _table_row(
                [
                    f"`{key}`",
                    f"{gate['max_abs_probability_difference']:.3g}",
                    str(gate["within_tolerance"]),
                    gate["missing_reproduced_players"],
                ]
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _challenger_equal_event_mean(report: dict[str, Any], target: str) -> float:
    values = []
    for key in report["cohort"]["events"]:
        block = report["per_event"][key]["targets"][target]
        values.append(block["challenger"]["brier"])
    return sum(values) / len(values)


def write_review(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "prospective_event_review.json"
    markdown_path = output_dir / "prospective_event_review.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
