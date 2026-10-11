"""Publish a verified, forecast-only golf board to a private Discord channel."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from golf_props.backtest.forecast_archive import verify_forecast_archive

PROHIBITED_WORDS = ("lock", "play", "wager", "bet", "edge")
BOARD_SCHEMA_VERSION = 1


class DiscordBoardError(ValueError):
    """Raised when a forecast board cannot be safely published."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscordBoardError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise DiscordBoardError(f"expected JSON object: {path}")
    return value


def _read_predictions(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise DiscordBoardError(f"unable to read predictions: {path}") from exc
    required = {"player_name", "winner_prob", "top5_prob", "top10_prob", "top20_prob"}
    if not rows or not required.issubset(rows[0]):
        raise DiscordBoardError("predictions.csv is missing required forecast columns")
    return rows


def _percent(value: str) -> str:
    return f"{float(value):.1%}"


def build_board(archive_dir: Path, created_at: Optional[datetime] = None) -> dict[str, Any]:
    verification = verify_forecast_archive(archive_dir)
    if not verification["verified"]:
        raise DiscordBoardError(
            "forecast archive verification failed: " + ", ".join(verification["problems"])
        )
    run_manifest = _read_json(archive_dir / "run_manifest.json")
    eligibility = run_manifest.get("eligibility", {})
    if eligibility.get("classification") != "prospective_forecast":
        raise DiscordBoardError("only prospective forecasts may be published")
    if run_manifest.get("pre_start_verified") is not True:
        raise DiscordBoardError("forecast archive is not pre-start verified")
    rows = _read_predictions(archive_dir / "predictions.csv")
    rows = sorted(rows, key=lambda row: float(row["top20_prob"]), reverse=True)
    structure = run_manifest.get("event_structure", {})
    frozen = run_manifest.get("frozen_parameters", {})
    board = {
        "schema_version": BOARD_SCHEMA_VERSION,
        "board_id": _sha256(archive_dir / "archive_manifest.json"),
        "created_at_utc": (created_at or datetime.now(timezone.utc)).isoformat(),
        "archive_dir": str(archive_dir),
        "archive_manifest_sha256": _sha256(archive_dir / "archive_manifest.json"),
        "event_name": run_manifest.get("event_name", ""),
        "event_date": eligibility.get("event_date", ""),
        "forecast_created_at_utc": run_manifest.get("created_at_utc", ""),
        "event_start_at_utc": run_manifest.get("event_start_at_utc"),
        "timing_source": run_manifest.get("timing_source", "unknown"),
        "field_size": len(rows),
        "event_structure": structure,
        "frozen_parameters": frozen,
        "field_quality": run_manifest.get("field_quality", {}),
        "rows": [
            {
                "rank": index,
                "player_name": row["player_name"],
                "winner_prob": float(row["winner_prob"]),
                "top5_prob": float(row["top5_prob"]),
                "top10_prob": float(row["top10_prob"]),
                "top20_prob": float(row["top20_prob"]),
                "make_cut_prob": float(row["make_cut_prob"]),
            }
            for index, row in enumerate(rows, 1)
        ],
    }
    return board


def render_markdown(board: dict[str, Any]) -> str:
    structure = board["event_structure"]
    frozen = board["frozen_parameters"]
    quality = board["field_quality"]
    timing_source = board.get("timing_source", "unknown")
    timing_label = "exact tee times" if timing_source == "exact_tee_times" else "official event date"
    lines = [
        f"# {board['event_name']} Forecast Board",
        "",
        "Private paper-research forecast. No recommendations or staking are included.",
        "",
        f"- Forecast created: `{board['forecast_created_at_utc']}`",
        f"- Competition start: `{board['event_start_at_utc'] or 'not recorded'}`",
        f"- Timing source: `{timing_label}`",
        f"- Field: `{board['field_size']}` players",
        f"- Structure: `{structure.get('format', 'unknown')}`, `{structure.get('cut_rule', 'unknown')}`",
        f"- Frozen parameters: `{frozen.get('half_life_days')}/{frozen.get('prior_rounds')}/{frozen.get('variance_prior_rounds')}`",
        f"- Historical data through: `{frozen.get('source_data_through', 'unknown')}`",
        f"- Field quality: `{quality.get('quality_status', 'unknown')}`",
        "",
        "| # | Player | Winner | Top 5 | Top 10 | Top 20 | Make cut |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in board["rows"]:
        lines.append(
            f"| {row['rank']} | {row['player_name']} | {_percent(str(row['winner_prob']))} | "
            f"{_percent(str(row['top5_prob']))} | {_percent(str(row['top10_prob']))} | "
            f"{_percent(str(row['top20_prob']))} | {_percent(str(row['make_cut_prob']))} |"
        )
    return "\n".join(lines) + "\n"


def discord_payload(board: dict[str, Any]) -> dict[str, Any]:
    rows = board["rows"][:15]
    description = "\n".join(
        f"`{row['rank']:>2}` {row['player_name']}: winner {_percent(str(row['winner_prob']))} | "
        f"T5 {_percent(str(row['top5_prob']))} | T10 {_percent(str(row['top10_prob']))} | "
        f"T20 {_percent(str(row['top20_prob']))}"
        for row in rows
    )
    structure = board["event_structure"]
    frozen = board["frozen_parameters"]
    quality = board["field_quality"]
    timing_source = board.get("timing_source", "unknown")
    timing_label = "exact tee times" if timing_source == "exact_tee_times" else "official event date"
    payload = {
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": f"{board['event_name']} | Forecast Board",
            "description": description,
            "color": 0x3498DB,
            "fields": [
                {"name": "Event", "value": f"{board['event_date']} | {board['field_size']} players", "inline": True},
                {"name": "Competition start", "value": str(board["event_start_at_utc"] or "not recorded"), "inline": True},
                {"name": "Timing source", "value": timing_label, "inline": True},
                {"name": "Structure", "value": f"{structure.get('format', 'unknown')} / {structure.get('cut_rule', 'unknown')}", "inline": False},
                {"name": "Model", "value": f"365d / {frozen.get('prior_rounds')} / {frozen.get('variance_prior_rounds')} rounds", "inline": True},
                {"name": "Data through", "value": str(frozen.get('source_data_through', 'unknown')), "inline": True},
                {"name": "Data quality", "value": str(quality.get("quality_status", "unknown")), "inline": True},
            ],
            "footer": {"text": "forecast only | private paper research | prices omitted"},
        }],
    }
    text = json.dumps(payload).casefold()
    for word in PROHIBITED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            raise DiscordBoardError(f"payload contains prohibited wording: {word}")
    return payload


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def publish_board(
    archive_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
    resend: bool = False,
    webhook_url: Optional[str] = None,
) -> dict[str, Any]:
    board = build_board(archive_dir)
    board_json = output_dir / "forecast_board.json"
    payload_json = output_dir / "discord_payload.json"
    receipt_path = output_dir / "delivery_receipt.json"
    if receipt_path.exists() and not resend:
        receipt = _read_json(receipt_path)
        if receipt.get("board_id") == board["board_id"]:
            raise DiscordBoardError("board already has a delivery receipt; use --resend explicitly")
    _atomic_write(board_json, json.dumps(board, indent=2, sort_keys=True) + "\n")
    payload = discord_payload(board)
    _atomic_write(payload_json, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    receipt: dict[str, Any] = {
        "schema_version": BOARD_SCHEMA_VERSION,
        "board_id": board["board_id"],
        "archive_manifest_sha256": board["archive_manifest_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "dry_run" if dry_run else "pending",
        "payload_sha256": _sha256(payload_json),
        "messages": 0,
    }
    if dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        url = webhook_url or os.environ.get("GOLF_PROPS_DISCORD_WEBHOOK_URL")
        if not url:
            raise DiscordBoardError("GOLF_PROPS_DISCORD_WEBHOOK_URL is not set")
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            try:
                request = Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "golf_props/0.1 forecast-board",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=20) as response:
                    if response.status >= 300:
                        raise DiscordBoardError(f"Discord returned HTTP {response.status}")
                receipt["status"] = "sent"
                receipt["messages"] = 1
                break
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    receipt["status"] = "failed"
                    receipt["error"] = f"HTTP {exc.code}"
                    break
                time.sleep(min(2 ** attempt, 4))
            except (URLError, TimeoutError, DiscordBoardError) as exc:
                if attempt == 2:
                    receipt["status"] = "failed"
                    receipt["error"] = str(exc)
                    break
                time.sleep(min(2 ** attempt, 4))
    _atomic_write(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return {"board": board_json, "payload": payload_json, "receipt": receipt_path, "receipt_data": receipt}


MAIN_WEBHOOK_ENV = "GOLF_PROPS_DISCORD_WEBHOOK_URL"
URGENT_PREFIX = "[URGENT]"

# Repeat ops alerts with identical text are suppressed within this window so
# the two-hourly loop cannot spam the channel while a wait is still normal
# (e.g. grading retries for an event whose results are not out yet, or a
# discovery failure that persists across runs).
ALERT_DEDUPE_WINDOW_SECONDS = 24 * 3600
ALERT_LEDGER_NAME = "ops_alerts.json"
ALERT_LEDGER_ENV = "GOLF_PROPS_OPS_ALERT_LEDGER"


def _alert_ledger_path() -> Path:
    override = os.environ.get(ALERT_LEDGER_ENV)
    if override:
        return Path(override)
    from golf_props.config import PROJECT_ROOT

    return PROJECT_ROOT / "data" / "interim" / "weekly" / ALERT_LEDGER_NAME


def _load_alert_ledger(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_alert_ledger(path: Path, ledger: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        pass


def send_ops_alert(
    message: str,
    webhook_url: Optional[str] = None,
    *,
    _now: Optional[datetime] = None,
) -> bool:
    """Send a short urgent operational alert to the main forecast channel.

    The forecast channel is shared with the board, so urgent messages are clearly
    prefixed with ``[URGENT]``. Only actionable failures should reach this
    function. It returns ``True`` only when a webhook is configured and delivery
    succeeds, and it never raises: operational alerting must not break the
    forecast loop or block the board channel.  A repeat alert with identical
    text is suppressed when the same text was delivered within
    ``ALERT_DEDUPE_WINDOW_SECONDS`` (tracked in
    ``data/interim/weekly/ops_alerts.json``).
    """
    text = str(message or "").strip()
    if not text:
        return False
    sanitized = text
    for word in PROHIBITED_WORDS:
        sanitized = re.sub(
            rf"\b{re.escape(word)}\b", "suppressed", sanitized, flags=re.IGNORECASE
        )
    # Belt-and-braces: raw exception text must never reach the channel, even
    # if a future caller interpolates ``{exc}`` into the message.  Exception
    # class names, ``Class: detail`` shapes, and tracebacks are replaced with
    # a pointer to status/logs.
    # Drop the exception class AND any trailing raw detail on the same line
    # (``ValueError: could not convert ... '3*'``); free-form trace detail
    # can never be enumerated, so the whole tail goes.
    sanitized = re.sub(
        r"\s*:?\s*\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning|Exit)\b\s*:?[^\n]*",
        " (see status/logs for details)",
        sanitized,
    )
    sanitized = re.sub(r"(?m)^\s*Traceback[\s\S]*$", "see logs for details", sanitized)
    sanitized = re.sub(
        r"(?m)^\s*File \".*?\", line \d+.*$", "see logs for details", sanitized
    )
    try:
        ledger_path: Optional[Path] = _alert_ledger_path()
        ledger = _load_alert_ledger(ledger_path)
        key = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        entry = ledger.get(key)
        if isinstance(entry, dict) and entry.get("last_sent_utc"):
            raw = str(entry["last_sent_utc"])
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                last = datetime.fromisoformat(raw)
            except ValueError:
                last = None
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                now = _now or datetime.now(timezone.utc)
                if (now - last).total_seconds() < ALERT_DEDUPE_WINDOW_SECONDS:
                    return False
    except Exception:
        ledger_path = None
        ledger = {}
        key = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
    url = webhook_url or os.environ.get(MAIN_WEBHOOK_ENV)
    if not url:
        return False
    payload = {
        "content": f"{URGENT_PREFIX} {sanitized}"[:1900],
        "username": "Golf Forecast",
        "allowed_mentions": {"parse": []},
    }
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        try:
            request = Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "golf_props/0.1 urgent-alert",
                },
                method="POST",
            )
            with urlopen(request, timeout=20) as response:
                if response.status >= 300:
                    return False
            try:
                if ledger_path is not None:
                    ledger[key] = {
                        "message": sanitized,
                        "last_sent_utc": (
                            _now or datetime.now(timezone.utc)
                        ).isoformat(),
                    }
                    _write_alert_ledger(ledger_path, ledger)
            except Exception:
                pass
            return True
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                return False
            time.sleep(min(2 ** attempt, 4))
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                return False
            time.sleep(min(2 ** attempt, 4))
    return False
