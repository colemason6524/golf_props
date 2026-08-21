import csv

from golf_props.cli import main
from golf_props.odds import source_audit
from golf_props.odds.source_audit import CandidateSource, audit_sources


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_audit_sources_classifies_static_odds_page(tmp_path, monkeypatch):
    usable_html = """
    <html><body>
      <h1>3M Open Winner</h1>
      <div>Tony Finau +2200</div>
      <div>Akshay Bhatia +2800</div>
      <h2>Top 20</h2>
      <div>Scottie Scheffler -180</div>
      <div>Rory McIlroy +110</div>
      <h2>To Make The Cut</h2>
      <div>Collin Morikawa -500</div>
      <span>+100 +105 +110 +115 +120 +125 +130 +135 +140 +145 +150 +155 +160 +165 +170 +175 +180 +185 +190 +195</span>
    </body></html>
    """
    shell_html = """
    <html><head><link rel="modulepreload" href="/app.js"></head>
    <body><div id="app-root"></div><script>window.__reactRouterContext = {}</script></body></html>
    """
    responses = {
        "https://example.test/static": usable_html,
        "https://example.test/shell": shell_html,
    }

    def fake_fetch(url, timeout_seconds):
        return 200, responses[url]

    monkeypatch.setattr(source_audit, "fetch_page", fake_fetch)
    output_dir = tmp_path / "audit"

    result = audit_sources(
        output_dir,
        candidates=[
            CandidateSource("Static Odds", "https://example.test/static"),
            CandidateSource("Shell Odds", "https://example.test/shell"),
        ],
        player_names=["Tony Finau", "Akshay Bhatia", "Scottie Scheffler", "Rory McIlroy"],
    )
    rows = read_csv(output_dir / "source_audit.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert len(result["rows"]) == 2
    assert next(row for row in rows if row["source_name"] == "Static Odds")["status"] == "usable"
    assert next(row for row in rows if row["source_name"] == "Shell Odds")["status"] == "not_usable_static"
    assert "# Odds Source Audit" in report


def test_audit_sources_marks_market_board_promising_without_seed_players(tmp_path, monkeypatch):
    html = """
    <html><body>
      <h1>PGA Odds</h1>
      <a>Winner</a><a>Top 5</a><a>Top 10</a><a>Top 20</a>
      <span>+100 +105 +110 +115 +120 +125 +130 +135 +140 +145 +150</span>
    </body></html>
    """

    def fake_fetch(url, timeout_seconds):
        return 200, html

    monkeypatch.setattr(source_audit, "fetch_page", fake_fetch)

    result = audit_sources(
        tmp_path / "audit",
        candidates=[CandidateSource("Market Board", "https://example.test/board")],
        player_names=["Tony Finau"],
    )

    assert result["rows"][0]["status"] == "promising"


def test_cli_audit_odds_sources(tmp_path, monkeypatch):
    def fake_fetch(url, timeout_seconds):
        return (
            200,
            "<html><body><h1>Winner</h1><div>Tony Finau +2200</div>"
            "<div>Akshay Bhatia +2800</div><h2>Top 10</h2>"
            "<span>+100 +105 +110 +115 +120 +125 +130 +135 +140 +145 +150 +155 +160 +165 +170 +175 +180 +185 +190 +195</span>"
            "</body></html>",
        )

    monkeypatch.setattr(source_audit, "fetch_page", fake_fetch)
    output_dir = tmp_path / "audit"

    exit_code = main(
        [
            "audit-odds-sources",
            "--output-dir",
            str(output_dir),
            "--candidate",
            "Example|https://example.test/static",
            "--player",
            "Tony Finau",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "source_audit.csv").exists()
    assert (output_dir / "report.md").exists()
