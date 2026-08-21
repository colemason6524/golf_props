import json
from pathlib import Path

from golf_props.analysis.performance_data import write_performance_data_audit
from golf_props.cli import main
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def prepare_results(tmp_path):
    processed_dir = tmp_path / "processed"
    normalize_file(FIXTURE, processed_dir)
    return processed_dir


def test_performance_data_audit_reports_model_readiness(tmp_path):
    processed_dir = prepare_results(tmp_path)
    output_dir = tmp_path / "audit"

    result = write_performance_data_audit(processed_dir, output_dir)
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert result["summary"]["table_rows"]["events"] == 2
    assert summary["table_rows"]["player_event_results"] == 6
    assert summary["table_rows"]["round_scores"] == 19
    assert summary["date_range"] == {
        "first_event": "2025-03-13",
        "last_event": "2025-04-10",
    }
    assert summary["event_coverage"]["field_size"]["median"] == 3.0
    assert summary["targets"]["make_cut"]["eligible_rows"] == 6
    assert summary["targets"]["make_cut"]["positive_rows"] == 4
    assert summary["targets"]["top20"]["eligible_rows"] == 5
    assert summary["targets"]["top20"]["positive_rows"] == 4
    assert "# Performance Data Audit" in report
    assert "No event, referential-integrity, or course-mapping warnings." in report


def test_cli_audit_performance_data(tmp_path):
    processed_dir = prepare_results(tmp_path)
    output_dir = tmp_path / "audit"

    exit_code = main(
        [
            "audit-performance-data",
            "--input-dir",
            str(processed_dir),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "report.md").exists()
