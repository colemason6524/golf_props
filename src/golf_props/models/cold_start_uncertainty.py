"""Disabled cold-start uncertainty challenger for the frozen golf simulator.

The incumbent shrinks a player's mean toward the tour mean, but simulates each
round with the player's *performance* variance.  A player with very few
effective rounds therefore receives a confidently-estimated mean and ordinary
round-to-round noise.  The 2026-10-28 research check-in proposed one paired
challenger: "inflate cold-start strength uncertainty (extra variance term keyed
on effective_rounds)" on identical pre-start inputs.

This module implements exactly one fixed, untuned form of that proposal
(``cold_start_variance_v1``)::

    reliability r = e / (e + p)                  # e = effective_rounds
    variance multiplier f = 1 + (1 - r) = 2 - r  # p = frozen prior_rounds
    simulated std' = std * sqrt(f)

``e = 0`` doubles the variance; a long history converges to no change.  There
is no grid, threshold or fitted constant.  The challenger is research-only:

* it is **disabled** and is never read by the production forecast path;
* it only writes to an explicit, separate output directory;
* it never edits an archive, never calls the odds collector and never sends.

The registered paired forward experiment is described in
``docs/research/cold_start_forward_experiment.md`` and in the golf evidence
bundle (``CRITERIA_FREEZE.md``).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from golf_props.models.tournament_simulator import (
    CUT_RULE_TOP_N_AND_TIES,
    render_report,
    simulate_tournament_rows,
    write_csv as write_simulation_csv,
)

CHALLENGER_ID = "cold_start_variance_v1"
CHALLENGER_STATUS = "disabled"
FORMULA = (
    "variance_multiplier = 2 - effective_rounds / "
    "(effective_rounds + prior_rounds); std' = std * sqrt(multiplier)"
)
DEFAULT_PRIOR_ROUNDS = 8.0
COLD_START_EFFECTIVE_ROUNDS = 10.0


class ColdStartChallengerError(ValueError):
    """Raised when the challenger cannot be built from a verified archive."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ColdStartChallengerError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ColdStartChallengerError(f"expected a JSON object: {path}")
    return value


def read_strength_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ColdStartChallengerError(f"missing strength file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def variance_multiplier(effective_rounds: float, prior_rounds: float) -> float:
    """Fixed variance multiplier for one player; no tuned parameters."""
    if not math.isfinite(effective_rounds) or effective_rounds < 0:
        raise ColdStartChallengerError("effective_rounds must be finite and >= 0")
    if not math.isfinite(prior_rounds) or prior_rounds < 0:
        raise ColdStartChallengerError("prior_rounds must be finite and >= 0")
    denominator = effective_rounds + prior_rounds
    reliability = effective_rounds / denominator if denominator > 0 else 0.0
    return 2.0 - reliability


def inflate_strength_uncertainty(
    rows: list[dict[str, Any]],
    prior_rounds: float = DEFAULT_PRIOR_ROUNDS,
) -> list[dict[str, Any]]:
    """Return copied strength rows with only ``shrunk_std_relative`` inflated."""
    inflated = []
    for row in rows:
        try:
            effective_rounds = float(row["effective_rounds"])
            standard_deviation = float(row["shrunk_std_relative"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ColdStartChallengerError(
                "strength rows need numeric effective_rounds and shrunk_std_relative"
            ) from exc
        if not math.isfinite(standard_deviation) or standard_deviation <= 0:
            raise ColdStartChallengerError(
                "shrunk_std_relative must be finite and positive"
            )
        multiplier = variance_multiplier(effective_rounds, prior_rounds)
        inflated.append(
            {
                **row,
                "shrunk_std_relative": round(
                    standard_deviation * math.sqrt(multiplier), 6
                ),
            }
        )
    return inflated


def strength_coverage(
    rows: list[dict[str, Any]],
    prior_rounds: float = DEFAULT_PRIOR_ROUNDS,
) -> dict[str, Any]:
    effective = [float(row["effective_rounds"]) for row in rows]
    multipliers = [variance_multiplier(value, prior_rounds) for value in effective]
    return {
        "players": len(rows),
        "effective_rounds_zero": sum(1 for value in effective if value == 0.0),
        "effective_rounds_below_10": sum(
            1 for value in effective if value < COLD_START_EFFECTIVE_ROUNDS
        ),
        "multiplier_min": round(min(multipliers), 6) if multipliers else None,
        "multiplier_max": round(max(multipliers), 6) if multipliers else None,
        "prior_rounds": prior_rounds,
    }


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def simulate_challenger(
    strength_rows: list[dict[str, Any]],
    run_manifest: dict[str, Any],
    *,
    prior_rounds: float = DEFAULT_PRIOR_ROUNDS,
    simulations: Optional[int] = None,
    seed: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the frozen simulator on the same inputs with inflated uncertainty."""
    structure = run_manifest.get("event_structure") or {}
    summary = run_manifest.get("simulation_summary") or {}
    inflated = inflate_strength_uncertainty(strength_rows, prior_rounds=prior_rounds)
    return simulate_tournament_rows(
        inflated,
        event_name=str(run_manifest.get("event_name") or ""),
        event_date=str(run_manifest.get("event_date") or ""),
        simulations=int(simulations or summary.get("simulations") or 20000),
        seed=int(seed if seed is not None else run_manifest.get("seed") or 20260729),
        cut_size=int(
            structure.get("effective_advancing_size")
            or structure.get("frozen_manifest_cut_size")
            or 65
        ),
        cut_rule=str(structure.get("cut_rule") or CUT_RULE_TOP_N_AND_TIES),
    )


def build_challenger_bundle(
    archive_dir: Path,
    output_dir: Path,
    *,
    prior_rounds: float = DEFAULT_PRIOR_ROUNDS,
    simulations: Optional[int] = None,
    seed: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Write one disabled challenger bundle beside (never inside) an archive."""
    archive_dir = Path(archive_dir)
    output_dir = Path(output_dir)
    if _inside(output_dir, archive_dir) or output_dir.resolve() == archive_dir.resolve():
        raise ColdStartChallengerError(
            "challenger output must not be written inside the immutable archive"
        )
    run_manifest_path = archive_dir / "run_manifest.json"
    strengths_path = archive_dir / "strengths.csv"
    predictions_path = archive_dir / "predictions.csv"
    run_manifest = _read_json(run_manifest_path)
    eligibility = run_manifest.get("eligibility") or {}
    if eligibility.get("classification") != "prospective_forecast":
        raise ColdStartChallengerError(
            "challenger requires a prospective forecast archive"
        )
    if run_manifest.get("pre_start_verified") is not True:
        raise ColdStartChallengerError("challenger requires a pre-start verified archive")

    strength_rows = read_strength_csv(strengths_path)
    coverage = strength_coverage(strength_rows, prior_rounds=prior_rounds)
    rows, simulation_summary = simulate_challenger(
        strength_rows,
        run_manifest,
        prior_rounds=prior_rounds,
        simulations=simulations,
        seed=seed,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    challenger_predictions = output_dir / "predictions.csv"
    challenger_report = output_dir / "report.md"
    manifest_path = output_dir / "challenger_manifest.json"
    write_simulation_csv(challenger_predictions, rows)
    challenger_report.write_text(
        render_report(rows, simulation_summary), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "challenger_id": CHALLENGER_ID,
        "status": CHALLENGER_STATUS,
        "production_effect": "none",
        "applied_to_production": False,
        "activation_state": "disabled",
        "formula": FORMULA,
        "prior_rounds": prior_rounds,
        "strength_coverage": coverage,
        "created_at_utc": (
            now or datetime.now(timezone.utc)
        ).isoformat(),
        "seed": simulation_summary.get("seed"),
        "simulations": simulation_summary.get("simulations"),
        "event_structure": {
            "cut_rule": simulation_summary.get("cut_rule"),
            "cut_size": simulation_summary.get("cut_size"),
            "rounds": simulation_summary.get("rounds"),
        },
        "source": {
            "archive_dir": str(archive_dir),
            "run_manifest_sha256": _sha256(run_manifest_path),
            "strengths_sha256": _sha256(strengths_path),
            "incumbent_predictions_sha256": _sha256(predictions_path),
        },
        "artifacts": {
            "predictions": challenger_predictions.name,
            "predictions_sha256": _sha256(challenger_predictions),
            "report": challenger_report.name,
            "report_sha256": _sha256(challenger_report),
        },
        "notes": [
            "Same frozen means, seed, simulation count, cut rule and inputs as "
            "the incumbent archive; only shrunk_std_relative is inflated.",
            "Research artifact only. It is not a forecast of record and was not "
            "published, activated or graded against production.",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "rows": rows,
        "summary": simulation_summary,
        "manifest": manifest,
        "predictions_path": challenger_predictions,
        "report_path": challenger_report,
        "manifest_path": manifest_path,
    }
