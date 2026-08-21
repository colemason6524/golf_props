"""Reviewed player identity resolution for current-event fields.

Matching is conservative and fail-closed:

- an explicit canonical player_id must resolve and its canonical name must agree
  with the supplied name;
- exact normalized names match;
- compact (non-alphanumeric-stripped) names match when unambiguous;
- reviewed aliases in config/player_aliases.csv map known source variants;
- ambiguous or unmatched names block prospective forecasts unless explicitly
  approved.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from golf_props.config import PROJECT_ROOT
from golf_props.features.current_event import normalize_name

DEFAULT_ALIASES_PATH = PROJECT_ROOT / "config" / "player_aliases.csv"

MATCHED = "matched"
AMBIGUOUS = "ambiguous"
UNKNOWN_ID = "unknown_player_id"
ID_NAME_MISMATCH = "id_name_mismatch"
UNMATCHED = "unmatched"
MATCHED_NO_PRIOR = "matched_no_prior_rounds"

BLOCKING_STATUSES = {AMBIGUOUS, UNKNOWN_ID, ID_NAME_MISMATCH, UNMATCHED}


class PlayerIdentityError(ValueError):
    """Raised when player identity resolution cannot be completed."""


@dataclass
class ResolvedPlayer:
    player_name: str
    player_id: str
    entry_status: str
    match_status: str
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "player_name": self.player_name,
            "player_id": self.player_id,
            "entry_status": self.entry_status,
            "match_status": self.match_status,
            "note": self.note,
        }


def compact_name(value: object) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def load_aliases(path: Path = DEFAULT_ALIASES_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    aliases: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            variant = str(row.get("variant_name") or "").strip()
            player_id = str(row.get("canonical_player_id") or "").strip()
            if variant and player_id:
                aliases[compact_name(variant)] = player_id
    return aliases


def build_canonical_index(
    players_rows: list[dict[str, str]],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    by_id: dict[str, str] = {}
    ids_by_normal: dict[str, list[str]] = {}
    ids_by_compact: dict[str, list[str]] = {}
    for row in players_rows:
        player_id = str(row.get("player_id") or "").strip()
        player_name = str(row.get("player_name") or "").strip()
        if not player_id or not player_name:
            continue
        by_id[player_id] = player_name
        normal = normalize_name(player_name)
        compact = compact_name(player_name)
        if normal:
            ids_by_normal.setdefault(normal, []).append(player_id)
        if compact:
            ids_by_compact.setdefault(compact, []).append(player_id)
    return by_id, ids_by_normal, ids_by_compact


def resolve_player(
    field_row: dict[str, str],
    by_id: dict[str, str],
    ids_by_normal: dict[str, list[str]],
    ids_by_compact: dict[str, list[str]],
    aliases: dict[str, str],
) -> ResolvedPlayer:
    player_name = str(field_row.get("player_name") or "").strip()
    entry_status = str(field_row.get("entry_status") or "confirmed").strip()
    supplied_id = str(field_row.get("player_id") or "").strip()

    if supplied_id:
        if supplied_id not in by_id:
            return ResolvedPlayer(player_name, supplied_id, entry_status, UNKNOWN_ID)
        canonical_name = by_id[supplied_id]
        if compact_name(player_name) != compact_name(canonical_name):
            return ResolvedPlayer(
                player_name,
                supplied_id,
                entry_status,
                ID_NAME_MISMATCH,
                note=f"canonical name is {canonical_name}",
            )
        return ResolvedPlayer(canonical_name, supplied_id, entry_status, MATCHED)

    compact = compact_name(player_name)
    alias_id = aliases.get(compact)
    if alias_id and alias_id in by_id:
        return ResolvedPlayer(by_id[alias_id], alias_id, entry_status, MATCHED)

    normal_candidates = ids_by_normal.get(normalize_name(player_name), [])
    if len(normal_candidates) == 1:
        player_id = normal_candidates[0]
        return ResolvedPlayer(by_id[player_id], player_id, entry_status, MATCHED)
    if len(normal_candidates) > 1:
        return ResolvedPlayer(player_name, "", entry_status, AMBIGUOUS)

    compact_candidates = ids_by_compact.get(compact, [])
    if len(compact_candidates) == 1:
        player_id = compact_candidates[0]
        return ResolvedPlayer(by_id[player_id], player_id, entry_status, MATCHED)
    if len(compact_candidates) > 1:
        return ResolvedPlayer(player_name, "", entry_status, AMBIGUOUS)

    return ResolvedPlayer(player_name, "", entry_status, UNMATCHED)


def resolve_field_identities(
    field_rows: list[dict[str, str]],
    players_rows: list[dict[str, str]],
    aliases_path: Path = DEFAULT_ALIASES_PATH,
    prior_player_ids: Optional[set[str]] = None,
) -> tuple[list[ResolvedPlayer], dict[str, Any]]:
    by_id, ids_by_normal, ids_by_compact = build_canonical_index(players_rows)
    aliases = load_aliases(aliases_path)
    prior_player_ids = prior_player_ids or set()
    resolved = [
        resolve_player(row, by_id, ids_by_normal, ids_by_compact, aliases)
        for row in field_rows
    ]
    for item in resolved:
        if item.match_status == MATCHED and item.player_id not in prior_player_ids:
            item.match_status = MATCHED_NO_PRIOR
    counts: dict[str, int] = {}
    for item in resolved:
        counts[item.match_status] = counts.get(item.match_status, 0) + 1
    problems = [
        f"{item.player_name}: {item.match_status}"
        + (f" ({item.note})" if item.note else "")
        for item in resolved
        if item.match_status in BLOCKING_STATUSES
    ]
    audit = {
        "total": len(resolved),
        "match_status_counts": dict(sorted(counts.items())),
        "problems": problems,
        "ok": not problems,
    }
    return resolved, audit


def identity_gate(
    audit: dict[str, Any],
    allowed_unmatched: Optional[set[str]] = None,
) -> tuple[bool, list[str]]:
    allowed = allowed_unmatched or set()
    problems = []
    for problem in audit.get("problems", []):
        name = problem.split(":")[0]
        if compact_name(name) in allowed:
            continue
        problems.append(problem)
    return not problems, problems


def write_identity_audit(path: Path, audit: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_resolved_field_csv(path: Path, resolved: list[ResolvedPlayer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["player_id", "player_name", "entry_status"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for item in resolved:
            writer.writerow(item.to_dict())
