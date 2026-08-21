import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from golf_props.backtest.rolling_simulation_validation import file_sha256
from golf_props.cli import main
from golf_props.features.round_performance import build_round_performance
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.pipelines import current_event_simulation as ces
from golf_props.pipelines.current_event_simulation import (
    FrozenCurrentEventError,
    run_frozen_current_event,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"
START = "2025-05-01T13:00:00Z"


def freeze_clock(monkeypatch, iso):
    current = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    monkeypatch.setattr(ces, "utc_now", lambda: current)
    return current


def prepare_frozen_inputs(tmp_path):
    canonical = tmp_path / "canonical"
    round_performance = tmp_path / "round_performance.csv"
    field = tmp_path / "field.csv"
    manifest = tmp_path / "frozen_model_manifest.json"
    normalize_file(FIXTURE, canonical)
    build_round_performance(canonical, round_performance)
    field.write_text(
        "player_name,entry_status\n"
        "Scottie Scheffler,confirmed\n"
        "Rory McIlroy,confirmed\n"
        "New Player,confirmed\n",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "status": "frozen_awaiting_future_evaluation",
                "seed": 17,
                "cut_size": 2,
                "canonical_dir": str(canonical),
                "round_performance_path": str(round_performance),
                "input_sha256": {
                    "events": file_sha256(canonical / "events.csv"),
                    "player_event_results": file_sha256(
                        canonical / "player_event_results.csv"
                    ),
                    "round_performance": file_sha256(round_performance),
                },
                "frozen_model": {
                    "half_life_days": 365.0,
                    "prior_rounds": 8.0,
                    "variance_prior_rounds": 20.0,
                    "source_data_through": "2025-04-13",
                    "prospective_holdout_after": "2025-04-20",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return canonical, round_performance, field, manifest


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_frozen_current_event_writes_reproducible_manifest_driven_outputs(
    tmp_path, monkeypatch
):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")

    first = run_frozen_current_event(
        manifest,
        field,
        first_output,
        "Future Event",
        "2025-05-01",
        simulations=200,
        seed=7,
        event_start_at_utc=START,
    )
    second = run_frozen_current_event(
        manifest,
        field,
        second_output,
        "Future Event",
        "2025-05-01",
        simulations=200,
        seed=7,
        event_start_at_utc=START,
    )

    assert first["prediction_rows"] == second["prediction_rows"]
    assert read_csv(first_output / "predictions.csv") == read_csv(
        second_output / "predictions.csv"
    )
    metadata = json.loads((first_output / "run_manifest.json").read_text())
    assert metadata["run_manifest_version"] == 2
    assert metadata["eligibility"]["classification"] == "prospective_forecast"
    assert metadata["frozen_parameters"]["half_life_days"] == 365.0
    assert metadata["frozen_parameters"]["prior_rounds"] == 8.0
    assert metadata["frozen_parameters"]["variance_prior_rounds"] == 20.0
    assert metadata["seed"] == 7
    assert metadata["field_quality"]["fallback_rows"] == 1
    assert metadata["course_challenger_applied"] is False
    assert metadata["sportsbook_prices_used"] is False
    assert metadata["pre_start_verified"] is True
    assert metadata["event_structure"]["cut_rule"] == "top_n_and_ties"
    assert metadata["event_structure"]["cut_applied"] is True
    assert metadata["event_structure"]["frozen_manifest_cut_size"] == 2
    assert metadata["event_structure"]["effective_advancing_size"] == 2
    assert metadata["artifact_sha256"]["predictions"] == file_sha256(
        first_output / "predictions.csv"
    )
    assert "No sportsbook prices" in (first_output / "report.md").read_text()
    assert "applied cut rule: top_n_and_ties" in (
        first_output / "report.md"
    ).read_text()


def test_frozen_current_event_rejects_stale_manifest_input_hash(tmp_path):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    value = json.loads(manifest.read_text())
    value["input_sha256"]["round_performance"] = "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FrozenCurrentEventError, match="hash mismatch"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "output",
            "Future Event",
            "2025-05-01",
            simulations=20,
        )


def test_nonprospective_event_requires_and_records_override(tmp_path):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)

    with pytest.raises(FrozenCurrentEventError, match="not prospective"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "rejected",
            "Old Event",
            "2025-04-20",
            simulations=20,
        )

    result = run_frozen_current_event(
        manifest,
        field,
        tmp_path / "retrospective",
        "Old Event",
        "2025-04-20",
        simulations=20,
        allow_retrospective=True,
    )

    eligibility = result["run_manifest"]["eligibility"]
    assert eligibility["classification"] == "retrospective_replay"
    assert eligibility["retrospective_override_used"] is True
    assert eligibility["is_prospective"] is False


def test_frozen_current_event_rejects_future_as_of_and_unsafe_player_id(
    tmp_path, monkeypatch
):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")

    with pytest.raises(FrozenCurrentEventError, match="cannot be after"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "future_as_of",
            "Future Event",
            "2025-05-01",
            as_of_date="2025-05-02",
            simulations=20,
            event_start_at_utc=START,
        )

    field.write_text(
        "player_id,player_name,entry_status\n"
        "unknown_id,Scottie Scheffler,confirmed\n"
        ",Rory McIlroy,confirmed\n",
        encoding="utf-8",
    )
    with pytest.raises(FrozenCurrentEventError, match="unsafe field identities"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "unsafe_id",
            "Future Event",
            "2025-05-01",
            simulations=20,
            event_start_at_utc=START,
        )


def test_frozen_current_event_rejects_ambiguous_player_name(tmp_path, monkeypatch):
    _, round_performance, field, manifest = prepare_frozen_inputs(tmp_path)
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")
    rows = read_csv(round_performance)
    duplicate = dict(
        next(row for row in rows if row["player_name"] == "Scottie Scheffler")
    )
    duplicate["player_id"] = "duplicate_scottie"
    rows.append(duplicate)
    write_csv(round_performance, rows)
    value = json.loads(manifest.read_text())
    value["input_sha256"]["round_performance"] = file_sha256(round_performance)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    field.write_text(
        "player_name,entry_status\n"
        "Scottie Scheffler,confirmed\n"
        "Rory McIlroy,confirmed\n",
        encoding="utf-8",
    )

    with pytest.raises(FrozenCurrentEventError, match="ambiguous_player_name"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "ambiguous",
            "Future Event",
            "2025-05-01",
            simulations=20,
            event_start_at_utc=START,
        )


def test_cli_predict_current_event(tmp_path, monkeypatch):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    output = tmp_path / "cli_output"
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")

    exit_code = main(
        [
            "predict-current-event",
            "--manifest",
            str(manifest),
            "--field",
            str(field),
            "--output-dir",
            str(output),
            "--event-name",
            "Future Event",
            "--event-date",
            "2025-05-01",
            "--simulations",
            "20",
            "--seed",
            "9",
            "--top-n",
            "2",
            "--event-start-at-utc",
            START,
        ]
    )

    assert exit_code == 0
    assert (output / "strengths.csv").exists()
    assert (output / "predictions.csv").exists()
    assert (output / "report.md").exists()
    assert (output / "run_manifest.json").exists()


def test_frozen_prospective_requires_event_start_timestamp(tmp_path):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)

    with pytest.raises(FrozenCurrentEventError, match="event_start_at_utc"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "missing_start",
            "Future Event",
            "2025-05-01",
            simulations=20,
        )


def test_frozen_prospective_rejects_naive_event_start_timestamp(
    tmp_path, monkeypatch
):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")

    with pytest.raises(FrozenCurrentEventError, match="timezone-aware"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "naive_start",
            "Future Event",
            "2025-05-01",
            simulations=20,
            event_start_at_utc="2025-05-01T13:00:00",
        )


def test_frozen_prospective_rejects_run_at_or_after_start(tmp_path, monkeypatch):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    freeze_clock(monkeypatch, "2025-05-01T13:00:00Z")

    with pytest.raises(FrozenCurrentEventError, match="not strictly before"):
        run_frozen_current_event(
            manifest,
            field,
            tmp_path / "after_start",
            "Future Event",
            "2025-05-01",
            simulations=20,
            event_start_at_utc=START,
        )


def test_frozen_no_cut_advances_everyone_and_keeps_frozen_manifest(
    tmp_path, monkeypatch
):
    _, _, field, manifest = prepare_frozen_inputs(tmp_path)
    freeze_clock(monkeypatch, "2025-04-28T00:00:00Z")
    manifest_before = file_sha256(manifest)

    result = run_frozen_current_event(
        manifest,
        field,
        tmp_path / "no_cut",
        "Future Event",
        "2025-05-01",
        simulations=200,
        seed=7,
        cut_rule="no_cut",
        event_start_at_utc=START,
    )
    metadata = result["run_manifest"]
    csv_rows = read_csv(tmp_path / "no_cut" / "predictions.csv")

    assert file_sha256(manifest) == manifest_before
    assert all(row["make_cut_prob"] == "1.0" for row in csv_rows)
    assert all(row["make_cut_prob"] == 1.0 for row in result["prediction_rows"])
    assert metadata["event_structure"]["cut_rule"] == "no_cut"
    assert metadata["event_structure"]["cut_applied"] is False
    assert metadata["event_structure"]["frozen_manifest_cut_size"] == 2
    assert metadata["event_structure"]["effective_advancing_size"] == 3
    assert metadata["frozen_parameters"]["half_life_days"] == 365.0
    report = (tmp_path / "no_cut" / "report.md").read_text()
    assert "applied cut rule: no_cut" in report
    assert "cut applied: False" in report
