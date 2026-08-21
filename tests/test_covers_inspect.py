import csv
import json

from golf_props.cli import main
from golf_props.odds import covers_inspect
from golf_props.odds.source_audit import CandidateSource
from golf_props.odds.covers_inspect import inspect_covers_odds, inspect_odds_url_batch


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


HTML = """
<html>
  <body>
    <h1>PGA Odds</h1>
    <h2>3M Open Winner</h2>
    <div>Tony Finau</div><div>+2200</div>
    <div>Akshay Bhatia</div><div>+2800</div>
    <h2>Top 20</h2>
    <div>Tony Finau</div><div>-110</div>
    <div>Akshay Bhatia</div><div>+140</div>
    <h2>Top 10</h2>
    <div>Tony Finau</div><div>+250</div>
    <div>Akshay Bhatia</div><div>+320</div>
  </body>
</html>
"""


def test_inspect_covers_odds_writes_artifacts(tmp_path, monkeypatch):
    def fake_fetch(url, timeout_seconds):
        return 200, HTML

    monkeypatch.setattr(covers_inspect, "fetch_page", fake_fetch)
    output_dir = tmp_path / "inspection"

    result = inspect_covers_odds(
        output_dir=output_dir,
        url="https://example.test/covers",
        player_names=["Tony Finau", "Akshay Bhatia"],
        context_items=4,
    )
    text_items = read_csv(output_dir / "text_items.csv")
    summary = json.loads((output_dir / "inspection_summary.json").read_text(encoding="utf-8"))
    snippets = (output_dir / "snippets.md").read_text(encoding="utf-8")

    assert result["summary"]["likely_parseable"] is True
    assert summary["odds_token_count"] == 6
    assert summary["market_hits"] == ["top10", "top20", "winner"]
    assert summary["player_hits"] == ["Akshay Bhatia", "Tony Finau"]
    assert text_items
    assert "# Covers Source Inspection" in snippets
    assert "Tony Finau" in snippets


def test_cli_inspect_covers_odds(tmp_path, monkeypatch):
    def fake_fetch(url, timeout_seconds):
        return 200, HTML

    monkeypatch.setattr(covers_inspect, "fetch_page", fake_fetch)
    output_dir = tmp_path / "inspection"

    exit_code = main(
        [
            "inspect-covers-odds",
            "--url",
            "https://example.test/covers",
            "--output-dir",
            str(output_dir),
            "--player",
            "Tony Finau",
            "--player",
            "Akshay Bhatia",
            "--context-items",
            "4",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "text_items.csv").exists()
    assert (output_dir / "snippets.md").exists()
    assert (output_dir / "inspection_summary.json").exists()


def test_inspect_odds_url_batch_writes_summary_and_subfolders(tmp_path, monkeypatch):
    def fake_fetch(url, timeout_seconds):
        if "failed" in url:
            raise OSError("boom")
        return 200, HTML

    monkeypatch.setattr(covers_inspect, "fetch_page", fake_fetch)
    output_dir = tmp_path / "batch"

    result = inspect_odds_url_batch(
        output_dir=output_dir,
        candidates=[
            CandidateSource("Good Source", "https://example.test/good"),
            CandidateSource("Failed Source", "https://example.test/failed"),
        ],
        player_names=["Tony Finau", "Akshay Bhatia"],
        context_items=4,
    )
    rows = read_csv(output_dir / "batch_summary.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert len(result["rows"]) == 2
    assert {row["status"] for row in rows} == {"ok", "failed"}
    assert (output_dir / "good_source" / "snippets.md").exists()
    assert (output_dir / "failed_source" / "inspection_summary.json").exists()
    assert "# Odds URL Inspection Batch" in report


def test_cli_inspect_odds_url_batch(tmp_path, monkeypatch):
    def fake_fetch(url, timeout_seconds):
        return 200, HTML

    monkeypatch.setattr(covers_inspect, "fetch_page", fake_fetch)
    output_dir = tmp_path / "batch"

    exit_code = main(
        [
            "inspect-odds-url-batch",
            "--output-dir",
            str(output_dir),
            "--candidate",
            "Good Source|https://example.test/good",
            "--player",
            "Tony Finau",
            "--player",
            "Akshay Bhatia",
            "--context-items",
            "4",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "batch_summary.csv").exists()
    assert (output_dir / "report.md").exists()
