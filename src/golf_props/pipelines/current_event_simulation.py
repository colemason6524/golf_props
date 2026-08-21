"""Run a reproducible current-event forecast from the frozen incumbent."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from golf_props.backtest.rolling_simulation_validation import file_sha256
from golf_props.config import PROJECT_ROOT
from golf_props.features.current_event import validate_field_columns
from golf_props.models.round_strength import (
    estimate_strength_rows,
    read_csv as read_strength_csv,
    write_csv as write_strength_csv,
)
from golf_props.models.tournament_simulator import (
    render_report as render_simulation_report,
    simulate_tournament_rows,
    write_csv as write_simulation_csv,
)


class FrozenCurrentEventError(ValueError):
    """Raised when a frozen current-event forecast is not safe to run."""


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FrozenCurrentEventError(f"missing frozen manifest: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrozenCurrentEventError(f"invalid frozen manifest JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FrozenCurrentEventError("frozen manifest must contain a JSON object")
    return value


def resolve_manifest_path(value: object) -> Path:
    text = str(value or "").strip()
    if not text:
        raise FrozenCurrentEventError("frozen manifest is missing an input path")
    path = Path(text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def frozen_configuration(manifest: dict[str, object]) -> dict[str, object]:
    if manifest.get("manifest_version") != 1:
        raise FrozenCurrentEventError("unsupported frozen manifest version")
    status = str(manifest.get("status") or "")
    if not status.startswith("frozen_"):
        raise FrozenCurrentEventError("manifest is not a frozen incumbent manifest")
    frozen = manifest.get("frozen_model")
    if not isinstance(frozen, dict):
        raise FrozenCurrentEventError("frozen manifest is missing frozen_model")
    required = {
        "half_life_days",
        "prior_rounds",
        "variance_prior_rounds",
        "source_data_through",
        "prospective_holdout_after",
    }
    missing = sorted(key for key in required if key not in frozen)
    if missing:
        raise FrozenCurrentEventError(
            f"frozen_model missing fields: {', '.join(missing)}"
        )
    source_cutoff = parse_iso_date(
        str(frozen["source_data_through"]),
        "source_data_through",
    )
    prospective_after = parse_iso_date(
        str(frozen["prospective_holdout_after"]),
        "prospective_holdout_after",
    )
    if prospective_after < source_cutoff:
        raise FrozenCurrentEventError(
            "prospective_holdout_after cannot precede source_data_through"
        )
    return frozen


def manifest_input_paths(
    manifest: dict[str, object],
) -> tuple[Path, Path, dict[str, Path]]:
    canonical_dir = resolve_manifest_path(manifest.get("canonical_dir"))
    round_performance = resolve_manifest_path(manifest.get("round_performance_path"))
    paths = {
        "events": canonical_dir / "events.csv",
        "player_event_results": canonical_dir / "player_event_results.csv",
        "round_performance": round_performance,
    }
    return canonical_dir, round_performance, paths


def verify_manifest_inputs(
    manifest: dict[str, object],
    input_paths: dict[str, Path],
) -> dict[str, str]:
    expected = manifest.get("input_sha256")
    if not isinstance(expected, dict):
        raise FrozenCurrentEventError("frozen manifest is missing input_sha256")
    required = set(input_paths)
    missing = sorted(required - set(expected))
    if missing:
        raise FrozenCurrentEventError(
            f"frozen manifest missing input hashes: {', '.join(missing)}"
        )
    actual: dict[str, str] = {}
    for name, path in input_paths.items():
        if not path.exists():
            raise FrozenCurrentEventError(f"missing frozen input {name}: {path}")
        actual[name] = file_sha256(path)
        if actual[name] != str(expected[name]):
            raise FrozenCurrentEventError(
                f"frozen input hash mismatch for {name}: {path}"
            )
    return actual


def parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise FrozenCurrentEventError(f"{label} must be an ISO date") from exc


def eligibility(
    event_date: str,
    as_of_date: str,
    prospective_holdout_after: str,
    allow_retrospective: bool,
) -> dict[str, object]:
    event = parse_iso_date(event_date, "event_date")
    as_of = parse_iso_date(as_of_date, "as_of_date")
    threshold = parse_iso_date(
        prospective_holdout_after,
        "prospective_holdout_after",
    )
    if as_of > event:
        raise FrozenCurrentEventError("as_of_date cannot be after event_date")
    is_prospective = event > threshold
    if not is_prospective and not allow_retrospective:
        raise FrozenCurrentEventError(
            "event is not prospective under the frozen manifest; "
            "use --allow-retrospective only for an explicitly labeled replay"
        )
    return {
        "event_date": event.isoformat(),
        "as_of_date": as_of.isoformat(),
        "prospective_holdout_after": threshold.isoformat(),
        "is_prospective": is_prospective,
        "retrospective_override_used": not is_prospective,
        "classification": (
            "prospective_forecast" if is_prospective else "retrospective_replay"
        ),
    }


def field_diagnostics(
    strength_rows: list[dict[str, object]],
) -> tuple[dict[str, object], list[str]]:
    counts = Counter(str(row["player_match_status"]) for row in strength_rows)
    rejected = {"ambiguous_player_name", "unknown_player_id"}
    rejected_rows = [
        row for row in strength_rows if str(row["player_match_status"]) in rejected
    ]
    if rejected_rows:
        details = ", ".join(
            f"{row['player_name']} ({row['player_match_status']})"
            for row in rejected_rows
        )
        raise FrozenCurrentEventError(f"unsafe field identities: {details}")

    warning_statuses = {"unmatched_player_name", "matched_no_prior_rounds"}
    warning_rows = [
        row
        for row in strength_rows
        if str(row["player_match_status"]) in warning_statuses
    ]
    warnings = [
        f"{row['player_name']}: {row['player_match_status']}"
        for row in warning_rows
    ]
    return (
        {
            "field_rows": len(strength_rows),
            "matched_rows": sum(
                count
                for status, count in counts.items()
                if status.startswith("matched_")
            ),
            "fallback_rows": counts.get("unmatched_player_name", 0),
            "warning_rows": len(warning_rows),
            "match_status_counts": dict(sorted(counts.items())),
            "quality_status": "warning" if warnings else "ok",
        },
        warnings,
    )


def render_report(
    simulation_rows: list[dict[str, object]],
    simulation_summary: dict[str, object],
    run_metadata: dict[str, object],
    top_n: int,
) -> str:
    eligibility_row = run_metadata["eligibility"]
    field_quality = run_metadata["field_quality"]
    frozen = run_metadata["frozen_parameters"]
    assert isinstance(eligibility_row, dict)
    assert isinstance(field_quality, dict)
    assert isinstance(frozen, dict)
    lines = [
        "# Frozen Current-Event Forecast",
        "",
        "This is a performance-only forecast. No sportsbook prices or",
        "unpromoted course adjustments were used.",
        "",
        "## Run Classification",
        "",
        f"- classification: {eligibility_row['classification']}",
        f"- event date: {eligibility_row['event_date']}",
        f"- as-of date: {eligibility_row['as_of_date']}",
        f"- prospective after: {eligibility_row['prospective_holdout_after']}",
        f"- source data through: {frozen['source_data_through']}",
        f"- frozen manifest created: {run_metadata['frozen_manifest_created_at_utc']}",
        f"- field quality: {field_quality['quality_status']}",
        "",
        "## Frozen Parameters",
        "",
        f"- half-life days: {frozen['half_life_days']}",
        f"- mean prior rounds: {frozen['prior_rounds']}",
        f"- variance prior rounds: {frozen['variance_prior_rounds']}",
        f"- cut size: {run_metadata['cut_size']}",
        f"- simulations: {run_metadata['simulations']}",
        f"- seed: {run_metadata['seed']}",
        "",
        "## Field Diagnostics",
        "",
    ]
    match_counts = field_quality["match_status_counts"]
    assert isinstance(match_counts, dict)
    for status, count in match_counts.items():
        lines.append(f"- {status}: {count}")
    warnings = run_metadata["warnings"]
    assert isinstance(warnings, list)
    if warnings:
        lines.extend(["", "### Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    simulation_report = render_simulation_report(
        simulation_rows,
        simulation_summary,
        top_n=top_n,
    ).replace(
        "# Performance-Only Tournament Simulation",
        "## Tournament Probabilities",
        1,
    )
    return "\n".join(lines).rstrip() + "\n\n" + simulation_report


def run_frozen_current_event(
    manifest_path: Path,
    field_path: Path,
    output_dir: Path,
    event_name: str,
    event_date: str,
    as_of_date: Optional[str] = None,
    simulations: int = 20_000,
    seed: Optional[int] = None,
    top_n: int = 25,
    allow_retrospective: bool = False,
) -> dict[str, object]:
    if not event_name.strip():
        raise FrozenCurrentEventError("event_name cannot be blank")
    if simulations <= 0:
        raise FrozenCurrentEventError("simulations must be positive")
    if top_n <= 0:
        raise FrozenCurrentEventError("top_n must be positive")

    manifest = read_json(manifest_path)
    frozen = frozen_configuration(manifest)
    canonical_dir, round_performance_path, input_paths = manifest_input_paths(
        manifest
    )
    verified_hashes = verify_manifest_inputs(manifest, input_paths)
    as_of_date = as_of_date or event_date
    eligibility_row = eligibility(
        event_date,
        as_of_date,
        str(frozen["prospective_holdout_after"]),
        allow_retrospective,
    )

    field_rows = read_strength_csv(field_path)
    validate_field_columns(field_path, field_rows)
    strength_rows, strength_summary = estimate_strength_rows(
        read_strength_csv(round_performance_path),
        field_rows,
        as_of_date,
        half_life_days=float(frozen["half_life_days"]),
        prior_rounds=float(frozen["prior_rounds"]),
        variance_prior_rounds=float(frozen["variance_prior_rounds"]),
    )
    field_quality, warnings = field_diagnostics(strength_rows)

    selected_seed = int(manifest.get("seed", 20260729) if seed is None else seed)
    cut_size = int(manifest.get("cut_size", 65))
    if cut_size <= 0:
        raise FrozenCurrentEventError("frozen cut_size must be positive")
    simulation_rows, simulation_summary = simulate_tournament_rows(
        strength_rows,
        event_name.strip(),
        event_date,
        simulations=simulations,
        seed=selected_seed,
        cut_size=cut_size,
    )

    run_metadata: dict[str, object] = {
        "run_manifest_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_performance_only",
        "event_name": event_name.strip(),
        "eligibility": eligibility_row,
        "frozen_manifest_path": str(manifest_path),
        "frozen_manifest_sha256": file_sha256(manifest_path),
        "frozen_manifest_created_at_utc": str(
            manifest.get("created_at_utc") or ""
        ),
        "frozen_manifest_status": str(manifest.get("status") or ""),
        "frozen_parameters": {
            "half_life_days": float(frozen["half_life_days"]),
            "prior_rounds": float(frozen["prior_rounds"]),
            "variance_prior_rounds": float(frozen["variance_prior_rounds"]),
            "source_data_through": str(frozen["source_data_through"]),
            "selection_date_from": str(frozen.get("selection_date_from") or ""),
            "selection_date_to": str(frozen.get("selection_date_to") or ""),
        },
        "canonical_dir": str(canonical_dir),
        "round_performance_path": str(round_performance_path),
        "verified_input_sha256": verified_hashes,
        "field_path": str(field_path),
        "field_sha256": file_sha256(field_path),
        "field_quality": field_quality,
        "warnings": warnings,
        "simulations": simulations,
        "seed": selected_seed,
        "cut_size": cut_size,
        "top_n": top_n,
        "strength_summary": strength_summary,
        "simulation_summary": simulation_summary,
        "course_challenger_applied": False,
        "sportsbook_prices_used": False,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    strengths_path = output_dir / "strengths.csv"
    predictions_path = output_dir / "predictions.csv"
    report_path = output_dir / "report.md"
    run_manifest_path = output_dir / "run_manifest.json"
    write_strength_csv(strengths_path, strength_rows)
    write_simulation_csv(predictions_path, simulation_rows)
    report_path.write_text(
        render_report(simulation_rows, simulation_summary, run_metadata, top_n),
        encoding="utf-8",
    )
    run_metadata["artifact_sha256"] = {
        "strengths": file_sha256(strengths_path),
        "predictions": file_sha256(predictions_path),
        "report": file_sha256(report_path),
    }
    run_manifest_path.write_text(
        json.dumps(run_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "strength_rows": strength_rows,
        "prediction_rows": simulation_rows,
        "run_manifest": run_metadata,
        "strengths_path": strengths_path,
        "predictions_path": predictions_path,
        "report_path": report_path,
        "run_manifest_path": run_manifest_path,
    }
