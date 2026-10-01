"""Autonomous event-structure policy.

The weekly scheduler must include ordinary PGA Tour stroke-play events without a
per-tournament human registry entry, while never silently applying a top-65 cut
to a no-cut playoff event or modelling a team/exotic format as stroke play.

Decision precedence:

1. A reviewed registry row always wins (manual override, explicit ``no_cut``, or
   deliberate exclusion).
2. Otherwise a deterministic name policy classifies the event:
   - team / match-play / non-standard formats are excluded;
   - FedExCup Playoff events are auto-included under the explicit ``no_cut`` rule
     (the frozen simulator represents them honestly; starting-stroke/staggered
     starts are not modelled, a documented limitation);
   - everything else defaults to ordinary 72-hole stroke play with the frozen
     top-65-and-ties cut.

The official PGA TOUR schedule only reliably exposes a ``PLAYOFF`` category flag
and a name; it does not encode per-event cut rules. The no-cut rule is the safe,
logged default for playoff events and strength parameters are never touched.
"""

from __future__ import annotations

from typing import Optional

from golf_props.models.tournament_simulator import (
    CUT_RULE_NO_CUT,
    CUT_RULE_TOP_N_AND_TIES,
)

DEFAULT_FORMAT = "72_hole_stroke_play"
DEFAULT_ROUNDS = 4
DEFAULT_CUT_SIZE = 65

DECISION_INCLUDE = "include"
DECISION_EXCLUDE = "exclude"

# Team, individual-format-exception, and non stroke-play events that the frozen
# simulator cannot represent and that should never be forecast.
EXCLUDED_NAME_MARKERS = (
    "presidents cup",
    "ryder cup",
    "solheim cup",
    "q-school",
    "qualifying school",
    "grant thornton invitational",
    "zurich classic",
    "olympic",
)

# FedExCup Playoff events are no-cut. They are auto-included under the explicit
# ``no_cut`` rule so a top-65 cut is never guessed onto them. Starting-stroke /
# staggered-start adjustments are not modelled; frozen 365/8/20 strength is
# unchanged. A reviewed registry row can still override this default.
PLAYOFF_NAME_MARKERS = (
    "tour championship",
    "fedex st. jude",
    "st. jude championship",
    "bmw championship",
)


def _matches(name: str, markers: tuple[str, ...]) -> Optional[str]:
    for marker in markers:
        if marker in name:
            return marker
    return None


def classify_event(
    event_name: str,
    season: int,
    registry_structure: Optional[dict[str, object]],
    source_event_id: str = "",
) -> dict[str, object]:
    """Return a structure decision for ``event_name``.

    The returned dict always carries a ``decision`` key of include or exclude.
    Include decisions additionally carry the normal structure fields plus
    ``structure_source``.
    """
    name = (event_name or "").strip().casefold()

    if registry_structure is not None:
        decision = dict(registry_structure)
        decision["decision"] = DECISION_INCLUDE
        decision["structure_source"] = "registry_override"
        return decision

    excluded = _matches(name, EXCLUDED_NAME_MARKERS)
    if excluded:
        return {
            "decision": DECISION_EXCLUDE,
            "event_name": event_name,
            "season": season,
            "reason": f"excluded_format:{excluded}",
        }

    playoff = _matches(name, PLAYOFF_NAME_MARKERS)
    if playoff:
        return {
            "decision": DECISION_INCLUDE,
            "event_name": event_name,
            "season": season,
            "source_event_id": source_event_id,
            "format": DEFAULT_FORMAT,
            "rounds": DEFAULT_ROUNDS,
            "cut_rule": CUT_RULE_NO_CUT,
            "cut_size": 0,
            "decision_status": "auto_default",
            "reviewed_at_utc": "",
            "notes": (
                "auto-included as FedExCup playoff no-cut stroke play; "
                "starting-stroke adjustments not modelled"
            ),
            "structure_source": "auto_playoff_no_cut",
        }

    return {
        "decision": DECISION_INCLUDE,
        "event_name": event_name,
        "season": season,
        "source_event_id": source_event_id,
        "format": DEFAULT_FORMAT,
        "rounds": DEFAULT_ROUNDS,
        "cut_rule": CUT_RULE_TOP_N_AND_TIES,
        "cut_size": DEFAULT_CUT_SIZE,
        "decision_status": "auto_default",
        "reviewed_at_utc": "",
        "notes": "auto-included as ordinary 72-hole stroke play; top-65 cut",
        "structure_source": "auto_default_policy",
    }


def is_no_cut(structure: dict[str, object]) -> bool:
    return str(structure.get("cut_rule") or "") == CUT_RULE_NO_CUT
