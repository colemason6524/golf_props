from pathlib import Path

from golf_props.normalization.player_identity import (
    AMBIGUOUS,
    ID_NAME_MISMATCH,
    MATCHED,
    MATCHED_NO_PRIOR,
    UNMATCHED,
    UNKNOWN_ID,
    identity_gate,
    resolve_field_identities,
)

PLAYERS = [
    {"player_id": "p1", "player_name": "C.T. Pan"},
    {"player_id": "p2", "player_name": "Kris Ventura"},
    {"player_id": "p3", "player_name": "Stephan Jaeger"},
    {"player_id": "p4", "player_name": "Rory McIlroy"},
]

ALIASES = Path("config/player_aliases.csv")


def resolve(rows, aliases_path=ALIASES):
    return resolve_field_identities(
        rows, PLAYERS, aliases_path=aliases_path, prior_player_ids={"p1", "p2", "p3", "p4"}
    )


def test_compact_name_matching_resolves_initials():
    resolved, audit = resolve(
        [
            {"player_name": "CT Pan", "player_id": "", "entry_status": "confirmed"},
            {"player_name": "JT Poston", "player_id": "", "entry_status": "confirmed"},
        ]
    )
    pan = resolved[0]
    assert pan.match_status == MATCHED
    assert pan.player_id == "p1"
    assert pan.player_name == "C.T. Pan"
    assert audit["ok"] is False


def test_reviewed_alias_resolves_name_variant(tmp_path):
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "variant_name,canonical_player_id,note\n"
        "Kristoffer Ventura,p2,\n"
        "Stephen Jaeger,p3,\n",
        encoding="utf-8",
    )
    resolved, audit = resolve(
        [
            {
                "player_name": "Kristoffer Ventura",
                "player_id": "",
                "entry_status": "confirmed",
            },
            {
                "player_name": "Stephen Jaeger",
                "player_id": "",
                "entry_status": "confirmed",
            },
        ],
        aliases_path=aliases,
    )
    assert resolved[0].player_id == "p2"
    assert resolved[1].player_id == "p3"
    assert resolved[0].match_status == MATCHED
    assert audit["ok"] is True


def test_exact_name_matches():
    resolved, audit = resolve(
        [
            {"player_name": "Rory McIlroy", "player_id": "", "entry_status": "confirmed"}
        ]
    )
    assert resolved[0].player_id == "p4"
    assert resolved[0].match_status == MATCHED
    assert audit["ok"] is True
    assert audit["match_status_counts"].get("matched") == 1


def test_unknown_id_and_name_mismatch():
    resolved, audit = resolve(
        [
            {
                "player_name": "Rory McIlroy",
                "player_id": "p999",
                "entry_status": "confirmed",
            },
            {
                "player_name": "Wrong Name",
                "player_id": "p4",
                "entry_status": "confirmed",
            },
        ]
    )
    assert resolved[0].match_status == UNKNOWN_ID
    assert resolved[1].match_status == ID_NAME_MISMATCH
    assert audit["ok"] is False


def test_ambiguous_name_blocked():
    players = [
        {"player_id": "x1", "player_name": "Alex Smith"},
        {"player_id": "x2", "player_name": "Alex Smith"},
    ]
    resolved, audit = resolve_field_identities(
        [{"player_name": "Alex Smith", "player_id": "", "entry_status": "confirmed"}],
        players,
        aliases_path=ALIASES,
        prior_player_ids=set(),
    )
    assert resolved[0].match_status == AMBIGUOUS
    assert audit["ok"] is False


def test_unmatched_blocked():
    resolved, audit = resolve(
        [
            {"player_name": "New Player", "player_id": "", "entry_status": "confirmed"}
        ]
    )
    assert resolved[0].match_status == UNMATCHED
    assert audit["ok"] is False


def test_identity_gate_can_approve_specific_unmatched():
    resolved, audit = resolve(
        [
            {"player_name": "New Player", "player_id": "", "entry_status": "confirmed"}
        ]
    )
    ok, problems = identity_gate(audit, allowed_unmatched={"newplayer"})
    assert ok is True
    assert problems == []


def test_matched_no_prior_allowed():
    resolved, audit = resolve_field_identities(
        [{"player_name": "Rory McIlroy", "player_id": "", "entry_status": "confirmed"}],
        PLAYERS,
        aliases_path=ALIASES,
        prior_player_ids=set(),
    )
    assert resolved[0].match_status == MATCHED_NO_PRIOR
    assert audit["ok"] is True
