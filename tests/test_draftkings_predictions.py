import csv
import json
from pathlib import Path
from urllib.error import URLError

from golf_props.cli import main
from golf_props.odds import draftkings_predictions
from golf_props.odds.draftkings_predictions import (
    DraftKingsParseError,
    collect_and_parse,
    collect_raw_snapshot,
    extract_market_links,
    parse_placement_rows,
    parse_raw_snapshot,
)
from golf_props.schemas import ODDS_SNAPSHOTS_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "draftkings_predictions_golf_placement_sample.html"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_parse_placement_rows_extracts_yes_odds_only():
    html = FIXTURE.read_text(encoding="utf-8")

    rows = parse_placement_rows(
        html,
        captured_at_utc="2026-07-17T12:00:00Z",
        source_url="https://predictions.draftkings.com/en/golf/placement",
        season="2026",
    )

    assert len(rows) == 5
    assert {row["selection_name"] for row in rows} == {
        "Scottie Scheffler",
        "Rory McIlroy",
        "Jordan Spieth",
    }
    assert {row["market_type"] for row in rows} == {"top20", "top10", "top5", "make_cut"}
    assert all(row["sportsbook"] == "DraftKings" for row in rows)
    assert all(row["event_name"] == "The Open Championship" for row in rows)
    assert all(not row["price_american"].startswith("+") for row in rows)


def test_parse_placement_rows_extracts_split_yes_price_tokens():
    html = """
    <html>
      <body>
        <h2>The Open Championship Winner</h2>
        <div>Scottie Scheffler</div>
        <span>Yes</span>
        <span>+488</span>
        <span>No</span>
        <span>-567</span>
        <div>Cameron Young</div>
        <span>Yes</span>
        <span>+614</span>
        <span>No</span>
        <span>-733</span>
        <h2>The Open Championship Top 20 (Including Ties)</h2>
        <div>Bud Cauley</div>
        <span>Yes</span>
        <span>-108</span>
        <span>No</span>
        <span>-108</span>
      </body>
    </html>
    """

    rows = parse_placement_rows(
        html,
        captured_at_utc="2026-07-17T12:00:00Z",
        source_url="https://predictions.draftkings.com/en/golf/placement",
        season="2026",
    )

    assert len(rows) == 3
    assert [(row["player_name"], row["market_type"], row["price_american"]) for row in rows] == [
        ("Scottie Scheffler", "winner", "488"),
        ("Cameron Young", "winner", "614"),
        ("Bud Cauley", "top20", "-108"),
    ]


def test_parse_raw_snapshot_writes_normalized_odds(tmp_path):
    raw = tmp_path / "snapshot.html"
    metadata = tmp_path / "snapshot.metadata.json"
    output = tmp_path / "odds.csv"
    raw.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    metadata.write_text(
        json.dumps(
            {
                "url": "https://predictions.draftkings.com/en/golf/placement",
                "captured_at_utc": "2026-07-17T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    rows = parse_raw_snapshot(raw, output, metadata_path=metadata, season="2026")
    written = read_csv(output)

    assert len(rows) == 5
    assert len(written) == 5
    assert list(written[0].keys()) == ODDS_SNAPSHOTS_COLUMNS
    scottie_top20 = next(
        row
        for row in written
        if row["player_name"] == "Scottie Scheffler" and row["market_type"] == "top20"
    )
    assert scottie_top20["price_american"] == "110"
    assert scottie_top20["price_decimal"] == "2.1"


def test_extract_market_links_keeps_supported_golf_pages():
    html = """
    <a href="/en/golf/market-group-details/DKP3-SPGTT20ABC">Top 20</a>
    <a href="/en/golf/to-make-the-cut">Cut</a>
    <a href="/en/markets/golf/3m-open">3M Open</a>
    <a href="/en/golf/props">Props</a>
    <a href="https://example.com/en/golf/market-group-details/DKP3-SPGTT10ABC">Wrong host</a>
    """

    links = extract_market_links(html, "https://predictions.draftkings.com/en/golf/placement")

    assert links == [
        "https://predictions.draftkings.com/en/golf/market-group-details/DKP3-SPGTT20ABC",
        "https://predictions.draftkings.com/en/golf/to-make-the-cut",
        "https://predictions.draftkings.com/en/markets/golf/3m-open",
    ]


def test_collect_and_parse_crawl_linked_pages(tmp_path, monkeypatch):
    base_url = "https://predictions.draftkings.com/en/golf/placement"
    top20_url = "https://predictions.draftkings.com/en/golf/market-group-details/DKP3-TOP20"
    cut_url = "https://predictions.draftkings.com/en/golf/to-make-the-cut"
    responses = {
        base_url: """
        <html>
          <body>
            <h2>The Open Championship Winner</h2>
            <div>Scottie Scheffler</div><span>Yes</span><span>+500</span>
            <span>No</span><span>-700</span>
            <a href="/en/golf/market-group-details/DKP3-TOP20">Top 20</a>
            <a href="/en/golf/to-make-the-cut">Cut</a>
          </body>
        </html>
        """,
        top20_url: """
        <html>
          <body>
            <h2>The Open Championship Top 20 (Including Ties)</h2>
            <div>Scottie Scheffler</div><span>Yes</span><span>-450</span>
            <span>No</span><span>+320</span>
            <div>Rory McIlroy</div><span>Yes</span><span>-200</span>
            <span>No</span><span>+160</span>
          </body>
        </html>
        """,
        cut_url: """
        <html>
          <body>
            <h2>The Open Championship To Make The Cut</h2>
            <div>Jordan Spieth</div><span>Yes</span><span>-125</span>
            <span>No</span><span>+105</span>
          </body>
        </html>
        """,
    }

    def fake_fetch(url, timeout_seconds):
        return 200, responses[url]

    monkeypatch.setattr(draftkings_predictions, "fetch_page", fake_fetch)
    output = tmp_path / "odds.csv"

    rows = collect_and_parse(
        tmp_path / "raw",
        output,
        url=base_url,
        season="2026",
        crawl_linked=True,
        retry_sleep_seconds=0,
    )
    written = read_csv(output)

    assert len(rows) == 4
    assert len(written) == 4
    assert {row["market_type"] for row in written} == {"winner", "top20", "make_cut"}
    assert (tmp_path / "raw").joinpath("20260717T120000Z.index.html").exists() is False
    assert len(list((tmp_path / "raw").glob("*.linked.metadata.json"))) == 1


def test_collect_and_parse_raises_when_linked_pages_have_no_odds_rows(tmp_path, monkeypatch):
    base_url = "https://predictions.draftkings.com/en/topic/golf"
    event_url = "https://predictions.draftkings.com/en/markets/golf/3m-open"
    responses = {
        base_url: '<html><body><a href="/en/markets/golf/3m-open">3M Open</a></body></html>',
        event_url: "<html><body><h1>3M Open</h1><div>No static market rows.</div></body></html>",
    }

    def fake_fetch(url, timeout_seconds):
        return 200, responses[url]

    monkeypatch.setattr(draftkings_predictions, "fetch_page", fake_fetch)

    try:
        collect_and_parse(
            tmp_path / "raw",
            tmp_path / "odds.csv",
            url=base_url,
            season="2026",
            crawl_linked=True,
            retry_sleep_seconds=0,
        )
    except DraftKingsParseError as exc:
        assert "parsed zero golf odds rows" in str(exc)
    else:
        raise AssertionError("expected DraftKingsParseError")


def test_cli_parse_dk_placement(tmp_path):
    output = tmp_path / "odds.csv"

    exit_code = main(
        [
            "parse-dk-placement",
            "--raw",
            str(FIXTURE),
            "--output",
            str(output),
            "--season",
            "2026",
        ]
    )

    assert exit_code == 0
    assert output.exists()


def test_cli_collect_parse_dk_placement_reports_parse_error(tmp_path, monkeypatch, capsys):
    def fake_collect_and_parse(*args, **kwargs):
        raise DraftKingsParseError("parsed zero golf odds rows")

    monkeypatch.setattr("golf_props.cli.collect_parse_dk_placement", fake_collect_and_parse)

    exit_code = main(
        [
            "collect-parse-dk-placement",
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--processed-output",
            str(tmp_path / "odds.csv"),
            "--crawl-linked",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DraftKings odds collection failed" in captured.err
    assert "parsed zero golf odds rows" in captured.err


def test_collect_raw_snapshot_writes_failure_metadata(tmp_path, monkeypatch):
    calls = {"count": 0}

    def fake_fetch(_url, timeout_seconds):
        calls["count"] += 1
        raise URLError("boom")

    monkeypatch.setattr(draftkings_predictions, "fetch_page", fake_fetch)

    try:
        collect_raw_snapshot(
            tmp_path,
            url="https://example.invalid/golf",
            retries=2,
            retry_sleep_seconds=0,
        )
    except DraftKingsParseError as exc:
        assert "failed to collect" in str(exc)
    else:
        raise AssertionError("expected DraftKingsParseError")

    metadata_files = list(tmp_path.glob("*.metadata.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert calls["count"] == 2
    assert metadata["status"] == "failed"
    assert metadata["attempts"] == 2
    assert metadata["error_type"] == "URLError"
