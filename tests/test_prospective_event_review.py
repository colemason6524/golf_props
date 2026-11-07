"""Event-level review of prospective golf forecasts: dependence and honest loss."""

import csv
import json
import math
from pathlib import Path

import pytest

from golf_props.backtest import prospective_event_review as review
from golf_props.models.tournament_simulator import (
    CUT_RULE_NO_CUT,
    simulate_tournament_rows,
)


def _graded(player_id, target, actual, model, baseline, position):
    return review.GradedRow(
        player_id=player_id,
        player_name=f"Player {player_id}",
        target=target,
        actual=actual,
        model_prob=model,
        baseline_prob=baseline,
        finish_position=position,
    )


def _bundle(key, rows_by_target, predictions, event_date="2026-10-01"):
    return review.EventBundle(
        event_key=key,
        archive_dir=Path(key),
        grading_dir=Path(key),
        event_name=f"Event {key}",
        event_date=event_date,
        graded_rows=rows_by_target,
        predictions=predictions,
        strength_rows=[],
        run_manifest={"event_name": f"Event {key}"},
    )


def test_brier_log_loss_and_ece_are_the_standard_definitions():
    probabilities = [0.9, 0.1]
    outcomes = [1, 0]
    assert review.brier(probabilities, outcomes) == pytest.approx(0.01)
    assert review.log_loss(probabilities, outcomes) == pytest.approx(
        -math.log(0.9), abs=1e-12
    )
    assert review.expected_calibration_error([0.05] * 10, [0] * 10) == pytest.approx(
        0.05
    )


def test_event_bootstrap_resamples_events_and_is_deterministic():
    same = review.event_bootstrap([0.1, 0.1, 0.1, 0.1], samples=500, seed=7)
    assert same["ci90_low"] == pytest.approx(0.1)
    assert same["ci90_high"] == pytest.approx(0.1)
    mixed = review.event_bootstrap([0.4, -0.2, 0.1, 0.0], samples=500, seed=7)
    again = review.event_bootstrap([0.4, -0.2, 0.1, 0.0], samples=500, seed=7)
    assert mixed == again
    assert mixed["ci90_low"] < mixed["mean"] < mixed["ci90_high"]


def test_sign_test_is_exact_and_never_claims_significance_at_four_events():
    assert review._sign_test_p(4, 4) == pytest.approx(0.125)
    assert review._sign_test_p(0, 4) == pytest.approx(0.125)
    assert review._sign_test_p(2, 4) == pytest.approx(1.0)


def test_equal_event_mean_differs_from_row_weighted_pooling():
    targets = review.TARGETS
    big_rows = {
        target: [
            _graded(f"b{index}", target, 1 if index == 0 else 0, 1.0 if index == 0 else 0.0, 0.5, index + 1)
            for index in range(100)
        ]
        for target in targets
    }
    small_rows = {
        target: [_graded(f"s{target}", target, 0, 0.4, 0.5, 1)]
        for target in targets
    }
    big_predictions = {f"b{index}": {column: 0.0 for column in review.TARGET_PROB_COLUMN.values()} for index in range(100)}
    big_predictions["b0"] = {column: 1.0 for column in review.TARGET_PROB_COLUMN.values()}
    small_predictions = {
        f"s{target}": {column: 0.4 for column in review.TARGET_PROB_COLUMN.values()}
        for target in targets
    }
    report = review.review_events(
        [
            _bundle("big", big_rows, big_predictions),
            _bundle("small", small_rows, small_predictions),
        ],
        bootstrap_samples=100,
        seed=3,
    )
    # big: structural 0.25 vs model 0.0 -> +0.25 Brier improvement
    # small: structural 0.25 vs model 0.16 -> +0.09
    equal_event = report["event_level"]["top20"]["brier_improvement"]["equal_event_mean"]
    row_weighted = report["pooled_row_weighted"]["top20"][
        "row_weighted_brier_improvement_vs_baseline"
    ]
    assert equal_event == pytest.approx((0.25 + 0.09) / 2)
    assert row_weighted == pytest.approx((100 * 0.25 + 1 * 0.09) / 101)
    assert equal_event < row_weighted


def test_decision_is_keep_when_the_primary_target_is_not_positive():
    report = {
        "cohort": {"n_events": 8},
        "event_level": {
            target: {
                "challenger_vs_incumbent": {
                    "equal_event_mean": -0.01 if target == "top20" else 0.01,
                    "positive_events": 7,
                    "bootstrap": {"ci90_low": -0.02},
                }
            }
            for target in review.TARGETS
        },
    }
    decision = review.challenger_decision(report)
    assert decision["verdict"] == "KEEP"
    assert decision["activation"] == "none"


def test_decision_is_forward_only_below_eight_events():
    report = {
        "cohort": {"n_events": 4},
        "event_level": {
            target: {
                "challenger_vs_incumbent": {
                    "equal_event_mean": 0.01,
                    "positive_events": 4,
                    "bootstrap": {"ci90_low": 0.001},
                }
            }
            for target in review.TARGETS
        },
    }
    decision = review.challenger_decision(report)
    assert decision["verdict"] == "FORWARD_ONLY"
    assert "8 required" in " ".join(decision["reasons"])


def test_decision_can_only_reach_candidate_at_eight_events_with_a_positive_ci():
    report = {
        "cohort": {"n_events": 8},
        "event_level": {
            target: {
                "challenger_vs_incumbent": {
                    "equal_event_mean": 0.01,
                    "positive_events": 8,
                    "bootstrap": {"ci90_low": 0.002},
                }
            }
            for target in review.TARGETS
        },
    }
    decision = review.challenger_decision(report)
    assert decision["verdict"] == "PROMOTE_CANDIDATE"
    assert decision["activation"] == "none"
    assert decision["requires_independent_review"] is True


def _write_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archives" / "test_open_2026"
    archive.mkdir(parents=True)
    strength_rows = [
        {
            "player_id": f"p{index}",
            "player_name": f"Player {index}",
            "entry_status": "confirmed",
            "effective_rounds": "12",
            "shrunk_mean_relative": str(2.0 - index),
            "shrunk_std_relative": "2.5",
        }
        for index in range(4)
    ]
    with (archive / "strengths.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(strength_rows[0]))
        writer.writeheader()
        writer.writerows(strength_rows)
    rows, summary = simulate_tournament_rows(
        strength_rows,
        event_name="Test Open",
        event_date="2026-10-01",
        simulations=200,
        seed=11,
        cut_rule=CUT_RULE_NO_CUT,
    )
    with (archive / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (archive / "run_manifest.json").write_text(
        json.dumps(
            {
                "event_name": "Test Open",
                "event_date": "2026-10-01",
                "seed": 11,
                "pre_start_verified": True,
                "eligibility": {
                    "classification": "prospective_forecast",
                    "event_date": "2026-10-01",
                },
                "event_structure": {"cut_rule": CUT_RULE_NO_CUT},
                "simulation_summary": {"simulations": 200, "seed": 11},
            }
        ),
        encoding="utf-8",
    )
    return archive


def test_loading_joins_by_player_id_and_rejects_disagreeing_probabilities(tmp_path):
    archive = _write_archive(tmp_path)
    grading = tmp_path / "grades" / "test_open_2026"
    grading.mkdir(parents=True)
    predictions = {
        row["player_id"]: row
        for row in csv.DictReader((archive / "predictions.csv").open())
    }
    with (grading / "graded_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_name",
                "event_date",
                "target",
                "player_id",
                "player_name",
                "finish_text",
                "finish_position",
                "actual",
                "model_prob",
                "baseline_prob",
            ],
        )
        writer.writeheader()
        for target in review.TARGETS:
            for index, (player_id, row) in enumerate(predictions.items()):
                writer.writerow(
                    {
                        "event_name": "Test Open",
                        "event_date": "2026-10-01",
                        "target": target,
                        "player_id": player_id,
                        "player_name": row["player_name"],
                        "finish_text": str(index + 1),
                        "finish_position": index + 1,
                        "actual": 1 if index == 0 else 0,
                        "model_prob": row[review.TARGET_PROB_COLUMN[target]],
                        "baseline_prob": 0.5,
                    }
                )
    (grading / "grading_manifest.json").write_text(
        json.dumps(
            {
                "event_name": "Test Open",
                "forecast_classification": "prospective_forecast",
            }
        ),
        encoding="utf-8",
    )
    bundle = review.load_event_bundle(archive, grading)
    assert len(bundle.graded_rows["winner"]) == 4
    assert bundle.predictions["p0"]["winner_prob"] == pytest.approx(
        float(predictions["p0"]["winner_prob"])
    )

    rows = list(csv.DictReader((grading / "graded_predictions.csv").open()))
    rows[0]["model_prob"] = "0.999999"
    with (grading / "graded_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(review.ProspectiveReviewError):
        review.load_event_bundle(archive, grading)
