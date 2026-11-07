import csv
import hashlib
import json
from pathlib import Path

import pytest

from golf_props.notifications import price_addendum as pa

FIXTURES = Path(__file__).parent / "fixtures" / "odds"
SNAPSHOT = FIXTURES / "bovada_golf_20261026T125600Z_excerpt.json"
ALIASES = FIXTURES / "odds_event_aliases.csv"
PLAYERS = FIXTURES / "players.csv"
PLAYER_ALIASES = FIXTURES / "player_aliases.csv"


def _archive(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "archive_manifest.json").write_text(json.dumps({"files": {}}))
    (archive / "run_manifest.json").write_text(
        json.dumps(
            {
                "event_name": "Mexico Open",
                "created_at_utc": "2026-10-26T00:00:00Z",
                "pre_start_verified": True,
                "eligibility": {
                    "classification": "prospective_forecast",
                    "event_date": "2026-10-29",
                },
            }
        )
    )
    with (archive / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "player_name",
                "winner_prob",
                "top5_prob",
                "top10_prob",
                "top20_prob",
                "make_cut_prob",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "player_name": "Player A",
                "winner_prob": ".1",
                "top5_prob": ".3",
                "top10_prob": ".5",
                "top20_prob": ".7",
                "make_cut_prob": ".9",
            }
        )
    return archive


@pytest.fixture(autouse=True)
def _verified(monkeypatch):
    monkeypatch.setattr(
        pa,
        "verify_forecast_archive",
        lambda _: {"verified": True, "problems": []},
    )


def _build(archive, **kwargs):
    return pa.build_price_addendum(
        archive,
        odds_snapshot=kwargs.pop("odds_snapshot", SNAPSHOT),
        odds_archive_dir=kwargs.pop("odds_archive_dir", None),
        odds_latest_csv=kwargs.pop("odds_latest_csv", None),
        weekly_dir=kwargs.pop("weekly_dir", None),
        event_aliases_path=kwargs.pop("event_aliases_path", ALIASES),
        player_aliases_path=kwargs.pop("player_aliases_path", PLAYER_ALIASES),
        players_table=kwargs.pop("players_table", PLAYERS),
    )


def test_addendum_links_to_archive_and_never_rewrites_it(tmp_path):
    archive = _archive(tmp_path)
    before = hashlib.sha256((archive / "predictions.csv").read_bytes()).hexdigest()
    addendum = _build(archive)
    assert addendum["archive_manifest_sha256"]
    assert addendum["odds"]["status"] == "priced"
    assert addendum["rows"][0]["price"]["price_american"] == 1100
    assert addendum["classification"] == "post_forecast_price_addendum"
    assert hashlib.sha256((archive / "predictions.csv").read_bytes()).hexdigest() == before


def test_dry_run_writes_addendum_without_sending(tmp_path):
    addendum = _build(_archive(tmp_path))
    result = pa.write_price_addendum(addendum, tmp_path / "delivery")
    assert result["status"] == "dry_run"
    assert Path(result["addendum"]).exists()
    assert not list((tmp_path / "delivery").rglob("*.tmp"))


def test_sent_addendum_dedupes_by_id_and_resend_is_explicit(tmp_path):
    addendum = _build(_archive(tmp_path))
    calls = []

    def transport(payload, url):
        calls.append(url)
        return {"status_code": 204, "message_id": None}

    first = pa.write_price_addendum(
        addendum,
        tmp_path / "delivery",
        send=True,
        webhook_url="https://x.invalid/h",
        transport=transport,
    )
    assert first["status"] == "sent" and len(calls) == 1
    repeat = pa.write_price_addendum(
        addendum,
        tmp_path / "delivery",
        send=True,
        webhook_url="https://x.invalid/h",
        transport=transport,
    )
    assert repeat["status"] == "deduped" and len(calls) == 1
    resent = pa.write_price_addendum(
        addendum,
        tmp_path / "delivery",
        send=True,
        resend=True,
        webhook_url="https://x.invalid/h",
        transport=transport,
    )
    assert resent["status"] == "sent" and len(calls) == 2


def test_unpriced_addendum_is_refused_for_send(tmp_path):
    addendum = _build(_archive(tmp_path), odds_snapshot=FIXTURES / "bovada_golf_20261030T180000Z_poststart.json")
    with pytest.raises(pa.PriceAddendumError, match="no usable prices"):
        pa.write_price_addendum(
            addendum,
            tmp_path / "delivery",
            send=True,
            webhook_url="https://x.invalid/h",
            transport=lambda payload, url: {"status_code": 204, "message_id": None},
        )
