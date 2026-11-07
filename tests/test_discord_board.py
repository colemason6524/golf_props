import csv
import hashlib
import json
from pathlib import Path

import pytest

from golf_props.notifications.discord import (
    DiscordBoardError,
    build_board,
    discord_payload,
    publish_board,
    render_markdown,
    send_ops_alert,
)

FIXTURES = Path(__file__).parent / "fixtures" / "odds"
ODDS_SNAPSHOT = FIXTURES / "bovada_golf_20261026T125600Z_excerpt.json"
POST_START = FIXTURES / "bovada_golf_20261030T180000Z_poststart.json"
EVENT_ALIASES = FIXTURES / "odds_event_aliases.csv"
PLAYERS = FIXTURES / "players.csv"
PLAYER_ALIASES = FIXTURES / "player_aliases.csv"


@pytest.fixture(autouse=True)
def _isolated_ops_alert_ledger(tmp_path, monkeypatch):
    # Ops-alert dedupe persists in data/interim/weekly/ops_alerts.json; keep
    # tests hermetic so alert tests never see each other's deliveries.
    monkeypatch.setenv(
        "GOLF_PROPS_OPS_ALERT_LEDGER", str(tmp_path / "ops_alerts.json")
    )


def _archive(
    tmp_path: Path,
    classification: str = "prospective_forecast",
    timing_source: str = "exact_tee_times",
    event_name: str = "Test Championship",
    players: tuple[str, ...] = ("Player B", "Player A"),
) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "archive_manifest.json").write_text(json.dumps({"files": {}}))
    (archive / "run_manifest.json").write_text(json.dumps({
        "event_name": event_name,
        "created_at_utc": "2026-09-16T12:00:00+00:00",
        "event_start_at_utc": "2026-09-17T11:20:00+00:00",
        "timing_source": timing_source,
        "pre_start_verified": True,
        "eligibility": {"classification": classification, "event_date": "2026-09-17"},
        "event_structure": {"format": "72_hole_stroke_play", "cut_rule": "top_n_and_ties"},
        "frozen_parameters": {"half_life_days": 365, "prior_rounds": 8, "variance_prior_rounds": 20, "source_data_through": "2026-07-11"},
        "field_quality": {"quality_status": "ok"},
    }))
    with (archive / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["player_name", "winner_prob", "top5_prob", "top10_prob", "top20_prob", "make_cut_prob"])
        writer.writeheader()
        writer.writerows([
            {
                "player_name": name,
                "winner_prob": f"{0.20 - 0.01 * index:.3f}",
                "top5_prob": ".30",
                "top10_prob": ".50",
                "top20_prob": f"{0.90 - 0.01 * index:.3f}",
                "make_cut_prob": ".90",
            }
            for index, name in enumerate(players)
        ])
    return archive


def _patch_verify(monkeypatch):
    monkeypatch.setattr(
        "golf_props.notifications.discord.verify_forecast_archive",
        lambda _: {"verified": True, "problems": []},
    )


def _priced_board(tmp_path, monkeypatch, **kwargs):
    _patch_verify(monkeypatch)
    archive = _archive(tmp_path, event_name="Mexico Open", players=("Twin Price", "Player A", "Player B"))
    return archive, build_board(
        archive,
        odds_snapshot=kwargs.pop("odds_snapshot", ODDS_SNAPSHOT),
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
        weekly_dir=None,
        **kwargs,
    )


def test_board_requires_prospective_archive(tmp_path, monkeypatch):
    archive = _archive(tmp_path, "retrospective_replay")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    with pytest.raises(DiscordBoardError, match="prospective"):
        build_board(archive)


def test_board_renders_ranked_forecasts_without_recommendation_language(tmp_path, monkeypatch):
    archive = _archive(tmp_path)
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["rows"][0]["player_name"] == "Player B"
    payload = discord_payload(board)
    encoded = json.dumps(payload).casefold()
    assert "model probabilities are not book prices" in encoded
    assert "lock" not in encoded
    assert "wager" not in encoded
    assert "edge" not in encoded
    assert "Player B" in render_markdown(board)


def test_dry_run_writes_receipt_and_deduplicates(tmp_path, monkeypatch, capsys):
    archive = _archive(tmp_path)
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    output = tmp_path / "delivery"
    result = publish_board(archive, output, dry_run=True)
    assert result["receipt_data"]["status"] == "dry_run"
    assert (output / "forecast_board.json").exists()
    assert json.loads((output / "delivery_receipt.json").read_text())["messages"] == 0
    with pytest.raises(DiscordBoardError, match="already has"):
        publish_board(archive, output, dry_run=True)
    assert "Test Championship" in capsys.readouterr().out


def test_board_displays_timing_source(tmp_path, monkeypatch):
    archive = _archive(tmp_path, timing_source="exact_tee_times")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["timing_source"] == "exact_tee_times"
    payload = discord_payload(board)
    # Verify timing source field exists in embed
    fields = payload["embeds"][0]["fields"]
    timing_field = next((f for f in fields if f["name"] == "Timing source"), None)
    assert timing_field is not None
    assert timing_field["value"] == "exact tee times"
    # Verify markdown rendering
    markdown = render_markdown(board)
    assert "Timing source: `exact tee times`" in markdown


def test_board_displays_schedule_date_fallback(tmp_path, monkeypatch):
    archive = _archive(tmp_path, timing_source="schedule_date_fallback")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["timing_source"] == "schedule_date_fallback"
    payload = discord_payload(board)
    # Verify timing source field exists in embed
    fields = payload["embeds"][0]["fields"]
    timing_field = next((f for f in fields if f["name"] == "Timing source"), None)
    assert timing_field is not None
    assert timing_field["value"] == "official event date"
    # Verify markdown rendering
    markdown = render_markdown(board)
    assert "Timing source: `official event date`" in markdown


def test_priced_board_shows_real_quote_and_keeps_probability_distinct(
    tmp_path, monkeypatch
):
    archive, board = _priced_board(tmp_path, monkeypatch)
    odds = board["odds"]
    assert odds["status"] == "priced"
    assert odds["sportsbook"] == "Bovada"
    assert odds["market_label"] == "Winner"
    assert odds["capture_utc"] == "2026-10-26T12:56:00.947497Z"
    assert odds["pre_start"] is True

    by_name = {row["player_name"]: row for row in board["rows"]}
    assert by_name["Player A"]["price"]["price_american"] == 1100
    assert by_name["Player A"]["price"]["price_decimal"] == 12.0
    assert by_name["Twin Price"]["price"] is None

    payload = discord_payload(board)
    embed = payload["embeds"][0]
    encoded = json.dumps(payload)
    assert "+1100" in encoded
    assert "Bovada" in encoded
    assert "2026-10-26T12:56:00.947497Z" in encoded
    assert "pre-start: true" in encoded
    # Probability and real quote stay separate, both visible on one line.
    priced_line = next(
        line for line in embed["description"].splitlines() if "odds +1100" in line
    )
    assert "winner 19.0%" in priced_line
    price_field = next(f for f in embed["fields"] if f["name"] == "Prices")
    assert "placement" in price_field["value"].casefold()

    markdown = render_markdown(board)
    assert "Winner odds (book)" in markdown
    assert "+1100 (12.00)" in markdown
    assert "18.0%" in markdown
    assert "Placement market prices unavailable" in markdown
    assert "Prospective ROI unavailable" in markdown


def test_unpriced_forecasts_stay_visible_without_a_price(tmp_path, monkeypatch):
    _patch_verify(monkeypatch)
    archive = _archive(tmp_path, event_name="Butterfield Bermuda Championship")
    board = build_board(
        archive,
        odds_snapshot=ODDS_SNAPSHOT,
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
    )
    assert board["odds"]["status"] == "unpriced"
    assert all(row["price"] is None for row in board["rows"])
    assert board["field_size"] == 2
    markdown = render_markdown(board)
    assert "Player B" in markdown and "not priced" in markdown
    payload = discord_payload(board)
    assert "Player B" in json.dumps(payload)
    price_field = next(f for f in payload["embeds"][0]["fields"] if f["name"] == "Prices")
    assert "none attached" in price_field["value"].casefold()

    output = tmp_path / "delivery"
    publish_board(
        archive,
        output,
        dry_run=True,
        odds_snapshot=ODDS_SNAPSHOT,
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
    )
    receipt = json.loads((output / "delivery_receipt.json").read_text(encoding="utf-8"))
    assert receipt["odds"]["status"] == "unpriced"
    assert receipt["odds"]["reason"] == "no_matching_event_snapshot"


def test_post_start_snapshot_never_reaches_the_board(tmp_path, monkeypatch):
    _, board = _priced_board(tmp_path, monkeypatch, odds_snapshot=POST_START)
    assert board["odds"]["status"] == "unpriced"
    assert board["odds"]["pre_start"] is False
    assert all(row["price"] is None for row in board["rows"])


def test_existing_sent_receipt_still_dedupes_a_priced_board(tmp_path, monkeypatch):
    _patch_verify(monkeypatch)
    archive = _archive(tmp_path, event_name="Mexico Open")
    output = tmp_path / "delivery"
    output.mkdir()
    board_id = hashlib.sha256((archive / "archive_manifest.json").read_bytes()).hexdigest()
    # A receipt written before the pricing change: same board, other payload.
    (output / "delivery_receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "board_id": board_id,
                "archive_manifest_sha256": board_id,
                "status": "sent",
                "payload_sha256": "0" * 64,
                "messages": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DiscordBoardError, match="already has a delivery receipt"):
        publish_board(
            archive,
            output,
            dry_run=True,
            odds_snapshot=ODDS_SNAPSHOT,
            event_aliases_path=EVENT_ALIASES,
            player_aliases_path=PLAYER_ALIASES,
            players_table=PLAYERS,
            odds_archive_dir=tmp_path / "no-archive",
            odds_latest_csv=tmp_path / "no-latest.csv",
        )
    receipt = json.loads((output / "delivery_receipt.json").read_text(encoding="utf-8"))
    assert receipt["payload_sha256"] == "0" * 64
    assert receipt["status"] == "sent"


def test_board_build_and_publish_never_rewrite_the_archive(tmp_path, monkeypatch):
    _patch_verify(monkeypatch)
    archive = _archive(tmp_path, event_name="Mexico Open")
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in archive.iterdir()
    }
    output = tmp_path / "delivery"
    publish_board(
        archive,
        output,
        dry_run=True,
        odds_snapshot=ODDS_SNAPSHOT,
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
    )
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in archive.iterdir()
    }
    assert after == before


def test_receipt_audits_the_exact_displayed_price_source(tmp_path, monkeypatch):
    _patch_verify(monkeypatch)
    archive = _archive(tmp_path, event_name="Mexico Open")
    output = tmp_path / "delivery"
    result = publish_board(
        archive,
        output,
        dry_run=True,
        odds_snapshot=ODDS_SNAPSHOT,
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
    )
    receipt = json.loads((output / "delivery_receipt.json").read_text(encoding="utf-8"))
    snapshot_sha = hashlib.sha256(ODDS_SNAPSHOT.read_bytes()).hexdigest()
    assert receipt["odds"]["source_sha256"] == snapshot_sha
    assert receipt["odds"]["capture_utc"] == "2026-10-26T12:56:00.947497Z"
    assert receipt["odds"]["event_match"] == "exact"
    assert receipt["odds"]["pre_start"] is True

    board_json = json.loads((output / "forecast_board.json").read_text(encoding="utf-8"))
    priced_rows = [row for row in board_json["rows"] if row["price"]]
    assert priced_rows
    assert priced_rows[0]["price"]["source"]["sha256"] == snapshot_sha
    assert priced_rows[0]["price"]["provenance"]["provider_price_id"]
    assert result["receipt_data"]["odds"]["status"] == "priced"


def test_discord_payload_never_exceeds_embed_limits(tmp_path, monkeypatch):
    _patch_verify(monkeypatch)
    long_names = tuple(
        f"Player With A Very Long Name Number {index:02d} " + "X" * 40
        for index in range(40)
    )
    archive = _archive(tmp_path, event_name="Mexico Open", players=long_names)
    board = build_board(
        archive,
        odds_snapshot=ODDS_SNAPSHOT,
        event_aliases_path=EVENT_ALIASES,
        player_aliases_path=PLAYER_ALIASES,
        players_table=PLAYERS,
        odds_archive_dir=tmp_path / "no-archive",
        odds_latest_csv=tmp_path / "no-latest.csv",
    )
    payload = discord_payload(board)
    embed = payload["embeds"][0]
    assert len(payload["embeds"]) == 1
    assert len(embed["title"]) <= 256
    assert len(embed["description"]) <= 4096
    assert len(embed["fields"]) <= 25
    assert all(len(field["name"]) <= 256 for field in embed["fields"])
    assert all(len(field["value"]) <= 1024 for field in embed["fields"])
    assert len(embed["footer"]["text"]) <= 2048
    total = (
        len(embed["title"])
        + len(embed["description"])
        + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"])
        + len(embed["footer"]["text"])
    )
    assert total <= 6000
    json.dumps(payload)  # serialisable exactly as posted


def test_urgent_alert_uses_main_webhook_with_prefix(tmp_path, monkeypatch):
    import golf_props.notifications.discord as discord

    sent = {}

    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=20):
        sent["url"] = request.full_url
        sent["body"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.delenv("GOLF_PROPS_DISCORD_OPS_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", fake_urlopen)

    assert send_ops_alert("golf forecast deadline missed: Test Invitational") is True
    assert sent["url"] == "https://main.example/webhook"
    payload = json.loads(sent["body"])
    assert payload["content"].startswith("[URGENT]")
    assert payload["allowed_mentions"] == {"parse": []}


def test_urgent_alert_suppressed_without_any_webhook(monkeypatch):
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_OPS_WEBHOOK_URL", raising=False)
    assert send_ops_alert("deadline missed") is False


def test_urgent_alert_delivery_failure_is_isolated(monkeypatch):
    import golf_props.notifications.discord as discord

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", boom)
    monkeypatch.setattr(discord.time, "sleep", lambda *_: None)

    # A failed alert must return False and never raise into the forecast loop.
    assert send_ops_alert("hard pipeline error") is False


def test_urgent_alert_scrubs_raw_exception_text(tmp_path, monkeypatch):
    import golf_props.notifications.discord as discord

    sent = {}

    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=20):
        sent["body"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", fake_urlopen)

    raw = "golf post-event grading failed for Baycurrent Classic (baycurrent_classic_2026): ValueError: could not convert string to float: \'3*\'"
    assert send_ops_alert(raw) is True
    payload = json.loads(sent["body"])
    assert "ValueError" not in payload["content"]
    assert "could not convert string to float" not in payload["content"]
    assert payload["content"].startswith("[URGENT]")


def test_board_displays_real_placement_prices_without_claiming_roi(tmp_path, monkeypatch):
    data = json.loads(ODDS_SNAPSHOT.read_text(encoding="utf-8"))
    template = dict(data["rows"][0])
    rows = []
    for name in ("Player A", "Player B"):
        for market, market_name, american in (
            ("winner", "Winner", 1100),
            ("top5", "Top 5", 450),
            ("top10", "Top 10", 210),
            ("top20", "Top 20", 105),
        ):
            row = dict(template)
            row.update(
                {
                    "player_name": name,
                    "selection_name": name,
                    "market_type": market,
                    "market_name": market_name,
                    "price_american": american,
                    "price_decimal": 1 + american / 100,
                    "odds_id": f"odds_{name}_{market}",
                }
            )
            rows.append(row)
    data["rows"] = rows
    snapshot = tmp_path / "bovada_golf_20261026T125600Z_placement.json"
    snapshot.write_text(json.dumps(data), encoding="utf-8")

    _, board = _priced_board(tmp_path, monkeypatch, odds_snapshot=snapshot)
    markdown = render_markdown(board)
    assert "Placement odds (book)" in markdown
    assert "T5 +450" in markdown and "T10 +210" in markdown and "T20 +105" in markdown
    assert "dead-heat" in markdown
    payload = discord_payload(board)
    description = payload["embeds"][0]["description"]
    assert "T5 +450" in description
    price_field = next(
        field for field in payload["embeds"][0]["fields"] if field["name"] == "Prices"
    )
    assert "T5 2, T10 2, T20 2" in price_field["value"]
    assert "no priced selection" in price_field["value"]
    encoded = json.dumps(payload).casefold()
    assert "wager" not in encoded and "edge" not in encoded
