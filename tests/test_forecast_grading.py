import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from golf_props.backtest.forecast_archive import REQUIRED_ARCHIVE_FILES
from golf_props.backtest.forecast_grading import ForecastGradingError, grade_forecast
from golf_props.cli import main


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    for name in REQUIRED_ARCHIVE_FILES:
        if name != "archive_manifest.json":
            (archive / name).write_text(name, encoding="utf-8")
    with (archive / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_name", "event_date", "player_id", "player_name",
                "top20_prob", "top10_prob", "top5_prob", "winner_prob",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {"event_name": "Test Event", "event_date": "2026-01-01", "player_id": "p1", "player_name": "Alpha One", "top20_prob": .9, "top10_prob": .7, "top5_prob": .5, "winner_prob": .3},
                {"event_name": "Test Event", "event_date": "2026-01-01", "player_id": "p2", "player_name": "Beta Two", "top20_prob": .8, "top10_prob": .5, "top5_prob": .3, "winner_prob": .2},
                {"event_name": "Test Event", "event_date": "2026-01-01", "player_id": "p3", "player_name": "Gamma Three", "top20_prob": .7, "top10_prob": .3, "top5_prob": .1, "winner_prob": .1},
            ]
        )
    (archive / "run_manifest.json").write_text(
        json.dumps({"eligibility": {"classification": "prospective_forecast"}}),
        encoding="utf-8",
    )
    hashes = {
        path.name: _sha(path)
        for path in archive.iterdir()
        if path.name != "archive_manifest.json"
    }
    (archive / "archive_manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": hashes}), encoding="utf-8"
    )
    return archive


def _results_page(tmp_path, third_name="Gamma Three"):
    rows = []
    for position, name in [("1", "Alpha One"), ("T2", "Beta Two"), ("WD", third_name)]:
        cells = ["", position, "", name, "E", "$1", "70", "70", "70", "70", "280"]
        rendered_cells = []
        for index, value in enumerate(cells):
            if index == 3:
                rendered_cells.append(
                    '<td><span class="CellPlayerName--long"><a>' + name + "</a></span></td>"
                )
            else:
                rendered_cells.append(f"<td>{value}</td>")
        rows.append(
            '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr">'
            + "".join(rendered_cells) + "</tr>"
        )
    path = tmp_path / "results.html"
    path.write_text("".join(rows), encoding="utf-8")
    return path


def _rolling_metrics(tmp_path):
    path = tmp_path / "rolling.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["target", "model_brier", "model_log_loss"])
        writer.writeheader()
        for target in ("top20", "top10", "top5", "winner"):
            writer.writerow({"target": target, "model_brier": .1, "model_log_loss": .2})
    return path


def test_grade_forecast_excludes_make_cut_and_withdrawal(tmp_path):
    archive = _archive(tmp_path)
    result = grade_forecast(
        archive,
        _results_page(tmp_path),
        _rolling_metrics(tmp_path),
        tmp_path / "grade",
        created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    assert [row["target"] for row in result["metrics"]] == ["top20", "top10", "top5", "winner"]
    assert all(row["graded_players"] == 2 for row in result["metrics"])
    assert result["manifest"]["excluded_players"] == ["Gamma Three"]
    assert result["manifest"]["frozen_parameters_changed"] is False
    assert "make_cut" not in (tmp_path / "grade" / "metrics.csv").read_text()
    assert _sha(archive / "predictions.csv") == result["manifest"]["input_sha256"]["predictions"]


def test_grade_forecast_fails_on_field_mismatch(tmp_path):
    with pytest.raises(ForecastGradingError, match="field mismatch"):
        grade_forecast(
            _archive(tmp_path),
            _results_page(tmp_path, third_name="Other Player"),
            _rolling_metrics(tmp_path),
            tmp_path / "grade",
        )


def test_grade_forecast_cli(tmp_path):
    exit_code = main(
        [
            "grade-forecast",
            "--archive-dir", str(_archive(tmp_path)),
            "--results-page", str(_results_page(tmp_path)),
            "--rolling-metrics", str(_rolling_metrics(tmp_path)),
            "--output-dir", str(tmp_path / "grade"),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "grade" / "grading_manifest.json").exists()
