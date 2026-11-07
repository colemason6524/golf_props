"""The disabled cold-start uncertainty challenger: fixed form, no activation."""

import csv
import json
from pathlib import Path

import pytest

from golf_props.models import cold_start_uncertainty as cs


def _strength_row(player_id, effective_rounds, std, mean=0.5):
    return {
        "player_id": player_id,
        "player_name": f"Player {player_id}",
        "entry_status": "confirmed",
        "player_match_status": "matched_player_id",
        "as_of_date": "2026-10-29",
        "rounds_used": str(int(effective_rounds)),
        "effective_rounds": str(effective_rounds),
        "shrunk_mean_relative": str(mean),
        "shrunk_std_relative": str(std),
    }


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    rows = [_strength_row("a", 0.0, 2.0), _strength_row("b", 120.0, 2.0)]
    with (archive / "strengths.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    predictions = [
        {
            "event_name": "Test Open",
            "event_date": "2026-10-29",
            "player_id": player_id,
            "player_name": f"Player {player_id}",
            "winner_prob": 0.5,
            "top20_prob": 0.5,
            "top10_prob": 0.5,
            "top5_prob": 0.5,
        }
        for player_id in ("a", "b")
    ]
    with (archive / "predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    manifest = {
        "event_name": "Test Open",
        "event_date": "2026-10-29",
        "seed": 20260729,
        "pre_start_verified": True,
        "eligibility": {
            "classification": "prospective_forecast",
            "event_date": "2026-10-29",
        },
        "event_structure": {
            "cut_rule": "top_n_and_ties",
            "effective_advancing_size": 65,
        },
        "simulation_summary": {"simulations": 200, "seed": 20260729},
        "frozen_parameters": {"half_life_days": 365, "prior_rounds": 8},
    }
    (archive / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return archive


def test_multiplier_is_fixed_and_keyed_on_effective_rounds():
    assert cs.variance_multiplier(0.0, 8.0) == pytest.approx(2.0)
    assert cs.variance_multiplier(8.0, 8.0) == pytest.approx(1.5)
    assert cs.variance_multiplier(120.0, 8.0) == pytest.approx(1.0625)
    values = [cs.variance_multiplier(value, 8.0) for value in (0, 1, 4, 8, 20, 120)]
    assert values == sorted(values, reverse=True)
    assert all(1.0 < value <= 2.0 for value in values)


def test_invalid_inputs_fail_closed():
    with pytest.raises(cs.ColdStartChallengerError):
        cs.variance_multiplier(-1.0, 8.0)
    with pytest.raises(cs.ColdStartChallengerError):
        cs.variance_multiplier(1.0, -1.0)
    with pytest.raises(cs.ColdStartChallengerError):
        cs.inflate_strength_uncertainty(
            [{"effective_rounds": "1", "shrunk_std_relative": "0"}]
        )


def test_only_uncertainty_changes_and_means_stay_frozen():
    rows = [_strength_row("a", 0.0, 2.0), _strength_row("b", 120.0, 2.0)]
    inflated = cs.inflate_strength_uncertainty(rows, prior_rounds=8.0)
    assert inflated[0]["shrunk_mean_relative"] == rows[0]["shrunk_mean_relative"]
    assert inflated[0]["effective_rounds"] == rows[0]["effective_rounds"]
    assert float(inflated[0]["shrunk_std_relative"]) == pytest.approx(2.0 * 2**0.5, abs=1e-6)
    assert float(inflated[1]["shrunk_std_relative"]) == pytest.approx(
        2.0 * (1.0625) ** 0.5, abs=1e-6
    )
    assert rows[0]["shrunk_std_relative"] == "2.0"


def test_bundle_manifest_is_disabled_and_never_inside_the_archive(tmp_path):
    archive = _archive(tmp_path)
    result = cs.build_challenger_bundle(archive, tmp_path / "out")
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["status"] == "disabled"
    assert manifest["production_effect"] == "none"
    assert manifest["applied_to_production"] is False
    assert manifest["challenger_id"] == cs.CHALLENGER_ID
    assert manifest["strength_coverage"]["effective_rounds_zero"] == 1
    assert Path(result["predictions_path"]).exists()
    with pytest.raises(cs.ColdStartChallengerError):
        cs.build_challenger_bundle(archive, archive / "nested")


def test_bundle_rejects_a_non_prospective_archive(tmp_path):
    archive = _archive(tmp_path)
    manifest = json.loads((archive / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["eligibility"]["classification"] = "retrospective_replay"
    (archive / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(cs.ColdStartChallengerError):
        cs.build_challenger_bundle(archive, tmp_path / "out")


def test_challenger_is_deterministic_for_a_fixed_seed(tmp_path):
    archive = _archive(tmp_path)
    first = cs.build_challenger_bundle(archive, tmp_path / "one")
    second = cs.build_challenger_bundle(archive, tmp_path / "two")
    assert first["rows"] == second["rows"]
