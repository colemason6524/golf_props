#!/usr/bin/env python3
"""Round-score O/U scheduled ops: the daily grade, plus a manual capture.

    props_ou_ops.py grade [--event E] [--round R]
    props_ou_ops.py capture --lines FILE --event E --round R --book B [...]

`grade` is the timer-fired task (daily 08:00 ET, after finals and before the
next round's capture). It settles only rounds that already have realized
scores in the round table: a round that has not been played — or is not yet
final there — keeps its open rows, so a second run settles nothing new and no
row is voided early.

`capture` is never timer-fired. The lines come from Muse's browser read and are
supplied verbatim in a per-round plan; this command is the manual entry point
the harness runs on that file. Nothing here fetches, synthesizes or compares a
line, and nothing publishes (no Discord until Gate 1).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from golf_props.props_ou import ledger, shadow  # noqa: E402
from golf_props.props_ou.ingest import round_table  # noqa: E402

import props_ou_ingest  # noqa: E402  (the ingest CLI, same run() path)


def open_pairs(rows, event_id=None, round_number=None):
    """(event_id, round) pairs that still carry open ledger rows."""
    pairs = sorted({(str(r["event_id"]), int(r["round_number"]))
                    for r in rows if r.get("result") in (None, "", "open")})
    if event_id is not None:
        pairs = [p for p in pairs if p[0] == event_id]
    if round_number is not None:
        pairs = [p for p in pairs if p[1] == round_number]
    return pairs


def played_rounds(table):
    """(event_id, round) pairs with at least one realized score.

    This is the settlement gate: a round absent here has not been played (or
    has not reached the round table yet), so its open rows are left alone
    rather than voided.
    """
    return {(str(r.event_id), int(r.round_number))
            for r in table.dropna(subset=["score"]).itertuples()}


def grade(event_id=None, round_number=None) -> int:
    pairs = open_pairs(ledger.read(), event_id, round_number)
    if not pairs:
        print("grade: no open rows — nothing to settle")
        return 0
    played = played_rounds(round_table())
    graded, pending = 0, []
    for ev, rnd in pairs:
        if (ev, rnd) not in played:
            pending.append((ev, rnd))
            continue
        print(f"grade {ev} r{rnd}: {shadow.grade_event(ev, rnd)}")
        graded += 1
    for ev, rnd in pending:
        print(f"grade {ev} r{rnd}: round not final in the round table — "
              f"open rows kept, nothing settled")
    print(f"grade: open rounds={len(pairs)} graded={graded} pending={len(pending)}")
    return 0


def capture(argv) -> int:
    return props_ou_ingest.main(argv)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("capture", "grade"):
        print("usage: props_ou_ops.py capture|grade [options]", file=sys.stderr)
        return 2
    task, rest = argv[0], argv[1:]
    if task == "capture":
        return capture(rest)
    ap = argparse.ArgumentParser(prog="props_ou_ops.py grade",
                                 description="Settle every final, still-open round")
    ap.add_argument("--event", default=None)
    ap.add_argument("--round", type=int, default=None)
    a = ap.parse_args(rest)
    return grade(a.event, a.round)


if __name__ == "__main__":
    raise SystemExit(main())
