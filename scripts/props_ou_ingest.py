"""Parameterized round-score O/U line ingest — one lines file per round.

This replaces the per-round bespoke ingest (`rsm_r1_dk_ingest.py` stays as the
deployed record of the R1 capture). The lines file is the only per-round
input, transcribed verbatim from the plan that carried Muse's browser read:

    player,line,over,under
    Harris English,68.5,102,-138

Pricing, ledger schema and the publish label are the frozen props_ou path
(`shadow.build_picks` -> `ledger.append`, dedupe on the computed `pick_id`). A
player with no prior-event history is recorded `no_pick`, never dropped and
never forced. Nothing here fetches a line: no file, no rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from golf_props.props_ou import ledger, lines, publish, shadow  # noqa: E402
from golf_props.props_ou.config import PROPS_OU_DIR, RUN_LABEL  # noqa: E402
from golf_props.props_ou.ingest import round_table  # noqa: E402
from golf_props.props_ou.project import project_new_event  # noqa: E402

ROW_TZ = ZoneInfo("America/New_York")
COLUMNS = ("player", "line", "over", "under")


def load_lines(path: Path) -> list[tuple[str, float, int | None, int | None]]:
    """Verbatim (player, line, over, under) rows.

    A malformed row raises instead of being guessed at: this file is the only
    record that a line was observed, so a silent skip would lose evidence.
    One-sided lines are allowed (the frozen path tiers them OBSERVED_LEAN).
    """
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = set(COLUMNS) - set(rd.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        rows = []
        for i, r in enumerate(rd, start=2):
            name = (r["player"] or "").strip()
            if not name:
                raise ValueError(f"{path}:{i}: empty player")
            try:
                line = float(r["line"])
                over = int(r["over"]) if (r["over"] or "").strip() else None
                under = int(r["under"]) if (r["under"] or "").strip() else None
            except ValueError as err:
                raise ValueError(f"{path}:{i}: {err}") from err
            if over is None and under is None:
                raise ValueError(f"{path}:{i}: no price on either side")
            rows.append((name, line, over, under))
    return rows


def as_read_lines(rows, *, event_id: str, event_name: str, round_number: int,
                  book: str, captured_at: str, provenance: str,
                  market: str) -> list[lines.RoundLine]:
    """RoundLine objects carrying book + provenance; no pricing touched."""
    return [lines.RoundLine(
        event_id=event_id, event_name=event_name,
        market_id=f"{book}-{lines.normalize_name(name)}-r{round_number}",
        market_name=market, player_name=name, round_number=round_number,
        line=float(line), over_american=over, under_american=under,
        captured_at=captured_at, source=book, provenance=provenance)
        for name, line, over, under in rows]


def unpriced_row(ln: lines.RoundLine, row_date: str, reason: str) -> dict:
    """A recorded observation with no model price and no side."""
    return {"date": row_date, "run_label": RUN_LABEL,
            "captured_at": ln.captured_at, "event_id": ln.event_id,
            "event_name": ln.event_name, "player_id": None,
            "player_name": ln.player_name, "round_number": ln.round_number,
            "line": ln.line, "projection": None,
            "over_american": ln.over_american,
            "under_american": ln.under_american, "source": ln.source,
            "provenance": ln.provenance, "result": "no_pick", "units": 0.0,
            "settled_at": None, "side": None, "p_model": None,
            "p_market": None, "american": None, "decimal": None,
            "edge": None, "ev": None, "tier": "NO_VALUE", "sigma": None,
            "unpriced_reason": reason}


def run(lines_file: Path, *, event_id: str, round_number: int, book: str,
        event_name: str | None = None, captured_at: str | None = None,
        provenance: str | None = None, market: str | None = None,
        row_date: str | None = None, commit: bool = True) -> dict:
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    book = str(book).strip()
    if not book:
        raise ValueError("--book is required (the label the lines came from)")
    event_name = event_name or event_id
    market = market or f"Round Score – Round {round_number} O/U"
    provenance = provenance or (
        f"browser-read by Muse {captured_at}, supplied verbatim in plan")
    # Row date = local (ET) date of the read, not the wall clock at ingest:
    # pick_id keys on it, so a re-run the next day must not append again.
    row_date = row_date or datetime.fromisoformat(captured_at).astimezone(
        ROW_TZ).date().isoformat()

    read = as_read_lines(load_lines(lines_file), event_id=event_id,
                         event_name=event_name, round_number=round_number,
                         book=book, captured_at=captured_at,
                         provenance=provenance, market=market)
    table = round_table()
    proj = project_new_event(table, event_id, event_name, round_number)
    priced, diag = shadow.build_picks(table, proj, read)
    seen = {lines.normalize_name(r["player_name"]) for r in priced}
    for r in priced:
        r["date"] = row_date  # build_picks stamps the wall clock; pin to the read
    rows = priced + [unpriced_row(ln, row_date, "no_history_match")
                     for ln in read
                     if lines.normalize_name(ln.player_name) not in seen]
    existing = {ledger.pick_id(r) for r in ledger.read()}
    new_rows = [r for r in rows if ledger.pick_id(r) not in existing]
    appended = ledger.append(new_rows) if (commit and new_rows) else 0

    slug = re.sub(r"[^a-z0-9]+", "_", book.lower()).strip("_")
    out = PROPS_OU_DIR / f"shadow_run_{row_date}_{slug}_r{round_number}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": ledger.today() + " ingest", "run_label": RUN_LABEL,
              "event_id": event_id, "event_name": event_name,
              "round_number": round_number, "book": book,
              "lines_file": str(lines_file), "captured_at": captured_at,
              "provenance": provenance, "row_date": row_date, "diag": diag,
              "diag_unpriced": len(rows) - len(priced), "rows": rows,
              "appended": appended, "already_present": len(rows) - len(new_rows)}
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"ingest {event_id} r{round_number} [{book}]: read={len(read)} "
          f"priced={len(priced)} unpriced={report['diag_unpriced']} "
          f"appended={appended} already_present={report['already_present']} "
          f"-> {out.name}")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Golf round-score O/U lines-file ingest (one file per round)")
    ap.add_argument("--lines", required=True, type=Path,
                    help="CSV: player,line,over,under — verbatim from the plan")
    ap.add_argument("--event", required=True, help="event_id, e.g. rsm-classic-2026")
    ap.add_argument("--round", required=True, type=int)
    ap.add_argument("--book", required=True,
                    help="book the lines were read from (travels as source)")
    ap.add_argument("--event-name", default=None)
    ap.add_argument("--captured-at", default=None,
                    help="ISO timestamp of the browser read")
    ap.add_argument("--row-date", default=None,
                    help="row date (default: ET date of --captured-at)")
    ap.add_argument("--provenance", default=None)
    ap.add_argument("--market", default=None)
    ap.add_argument("--no-commit", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(a.lines, event_id=a.event, round_number=a.round,
            book=a.book, event_name=a.event_name, captured_at=a.captured_at,
            provenance=a.provenance, market=a.market, row_date=a.row_date,
            commit=not a.no_commit)
    except ValueError as err:
        print(f"ingest refused: {err}", file=sys.stderr)
        return 2
    led = ledger.read()
    ev = [r for r in led if r["event_id"] == a.event]
    print("ledger rows for event:", len(ev),
          "| by source:", {s: sum(1 for r in ev if r["source"] == s)
                           for s in sorted({r["source"] for r in ev})})
    print("gates:", publish.soft_publish_gate(led))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
