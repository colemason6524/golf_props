"""Separate, timestamped price addenda for an immutable forecast archive.

A forecast archive is never rewritten. If sportsbook markets appear after the
forecast board was published, this module records the new quote evidence as a
new addendum keyed by the archive manifest hash and the quote-source hash.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.request import Request, urlopen

from golf_props.backtest.forecast_archive import verify_forecast_archive
from golf_props.config import PROJECT_ROOT
from golf_props.odds.board_prices import annotate_board_rows

ADDENDUM_SCHEMA_VERSION = 1
RECEIPT_NAME = "price_addendum_receipt.json"
ADDENDUM_NAME = "price_addendum.json"
Transport = Callable[[dict[str, Any], str], dict[str, Any]]


class PriceAddendumError(ValueError):
    """Raised when an addendum cannot be recorded or delivered safely."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PriceAddendumError(f"invalid JSON: {path}") from exc


def _read_predictions(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"player_name", "winner_prob", "top5_prob", "top10_prob", "top20_prob"}
    if not rows or not required.issubset(rows[0]):
        raise PriceAddendumError(f"predictions missing required columns: {path}")
    return rows


def _board_rows(predictions: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "player_name": row["player_name"],
            "winner_prob": float(row["winner_prob"]),
            "top5_prob": float(row["top5_prob"]),
            "top10_prob": float(row["top10_prob"]),
            "top20_prob": float(row["top20_prob"]),
            "make_cut_prob": float(row.get("make_cut_prob") or 0.0),
        }
        for index, row in enumerate(predictions, 1)
    ]


def _addendum_id(
    archive_manifest_sha256: str, odds: dict[str, Any]
) -> str:
    source = odds.get("source") or {}
    identity = (odds.get("event_identity") or {}).get("provider_event_name") or ""
    payload = "|".join(
        [
            archive_manifest_sha256,
            str(source.get("sha256") or ""),
            str(odds.get("capture_utc") or ""),
            str(odds.get("status") or ""),
            str(odds.get("reason") or ""),
            identity,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_price_addendum(
    archive_dir: Path,
    *,
    odds_snapshot: Optional[Path] = None,
    odds_archive_dir: Optional[Path] = None,
    odds_latest_csv: Optional[Path] = None,
    weekly_dir: Optional[Path] = None,
    event_aliases_path: Optional[Path] = None,
    player_aliases_path: Optional[Path] = None,
    players_table: Optional[Path] = None,
) -> dict[str, Any]:
    archive_dir = Path(archive_dir)
    verification = verify_forecast_archive(archive_dir)
    if not verification["verified"]:
        raise PriceAddendumError(
            "forecast archive verification failed: "
            + ", ".join(verification["problems"])
        )
    run_manifest = _read_json(archive_dir / "run_manifest.json")
    if run_manifest.get("pre_start_verified") is not True:
        raise PriceAddendumError("forecast archive is not pre-start verified")
    eligibility = run_manifest.get("eligibility") or {}
    predictions = _read_predictions(archive_dir / "predictions.csv")
    if weekly_dir is None:
        weekly_dir = PROJECT_ROOT / "data" / "interim" / "weekly"
    annotated, odds = annotate_board_rows(
        event_name=str(run_manifest.get("event_name") or ""),
        event_key=archive_dir.name,
        event_date=str(eligibility.get("event_date") or ""),
        rows=_board_rows(predictions),
        odds_snapshot=odds_snapshot,
        odds_archive_dir=odds_archive_dir,
        odds_latest_csv=odds_latest_csv,
        weekly_dir=weekly_dir,
        event_aliases_path=event_aliases_path,
        player_aliases_path=player_aliases_path,
        players_table=players_table,
    )
    archive_manifest_sha = _sha256(archive_dir / "archive_manifest.json")
    return {
        "schema_version": ADDENDUM_SCHEMA_VERSION,
        "addendum_id": _addendum_id(archive_manifest_sha, odds),
        "archive_dir": str(archive_dir),
        "archive_manifest_sha256": archive_manifest_sha,
        "forecast_created_at_utc": run_manifest.get("created_at_utc", ""),
        "event_name": run_manifest.get("event_name", ""),
        "event_date": eligibility.get("event_date", ""),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "post_forecast_price_addendum",
        "production_effect": "display_only_no_model_change",
        "odds": odds,
        "rows": annotated,
    }


def _payload(addendum: dict[str, Any]) -> dict[str, Any]:
    odds = addendum["odds"]
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"{addendum['event_name']} | Price addendum"[:256],
                "description": (
                    "Separate price reference linked to the frozen forecast. "
                    "It does not change model probabilities, selections or ROI."
                ),
                "fields": [
                    {
                        "name": "Forecast archived",
                        "value": str(addendum["forecast_created_at_utc"]),
                        "inline": True,
                    },
                    {
                        "name": "Quote capture",
                        "value": str(odds.get("capture_utc") or "none"),
                        "inline": True,
                    },
                    {
                        "name": "Status",
                        "value": str(odds.get("status") or "unknown"),
                        "inline": True,
                    },
                    {
                        "name": "Coverage",
                        "value": str(odds.get("statement") or odds.get("reason") or ""),
                        "inline": False,
                    },
                ],
                "footer": {"text": "price addendum | no model or ROI change"},
            }
        ],
    }


def _default_transport(payload: dict[str, Any], url: str) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "golf_props/0.1 price-addendum",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return {
                "status_code": response.status,
                "message_id": response.headers.get("X-Message-Id"),
            }
    except Exception as exc:  # network ambiguity must be recorded, not guessed
        return {"status_code": None, "message_id": None, "error": str(exc)}


def write_price_addendum(
    addendum: dict[str, Any],
    delivery_root: Path,
    *,
    send: bool = False,
    resend: bool = False,
    webhook_url: Optional[str] = None,
    transport: Optional[Transport] = None,
) -> dict[str, Any]:
    addendum_id = str(addendum["addendum_id"])
    output_dir = Path(delivery_root) / "price_addenda" / addendum_id
    output_dir.mkdir(parents=True, exist_ok=True)
    addendum_path = output_dir / ADDENDUM_NAME
    receipt_path = output_dir / RECEIPT_NAME
    if receipt_path.exists() and not resend:
        existing = _read_json(receipt_path)
        if existing.get("addendum_id") == addendum_id and existing.get("status") == "sent":
            return {
                "status": "deduped",
                "addendum_id": addendum_id,
                "output_dir": str(output_dir),
                "receipt": existing,
            }
    addendum_path.write_text(
        json.dumps(addendum, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    payload = _payload(addendum)
    receipt = {
        "schema_version": ADDENDUM_SCHEMA_VERSION,
        "addendum_id": addendum_id,
        "archive_manifest_sha256": addendum["archive_manifest_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
        "messages": 0,
        "status": "dry_run" if not send else "pending",
        "odds_status": (addendum.get("odds") or {}).get("status"),
        "capture_utc": (addendum.get("odds") or {}).get("capture_utc"),
    }
    if send:
        if (addendum.get("odds") or {}).get("status") != "priced":
            raise PriceAddendumError("refusing to send an addendum with no usable prices")
        url = webhook_url or os.environ.get("GOLF_PROPS_DISCORD_WEBHOOK_URL")
        if not url:
            raise PriceAddendumError("GOLF_PROPS_DISCORD_WEBHOOK_URL is not set")
        result = (transport or _default_transport)(payload, url)
        receipt["attempts"] = 1
        receipt["http_status"] = result.get("status_code")
        receipt["message_id"] = result.get("message_id")
        if result.get("error"):
            receipt["status"] = "unknown_delivery"
            receipt["error"] = str(result["error"])
        elif 200 <= int(result.get("status_code") or 0) < 300:
            receipt["status"] = "sent"
            receipt["messages"] = 1
        else:
            receipt["status"] = "failed"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": receipt["status"],
        "addendum_id": addendum_id,
        "output_dir": str(output_dir),
        "addendum": str(addendum_path),
        "receipt": receipt,
    }
