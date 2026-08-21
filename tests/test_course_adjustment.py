from golf_props.models.course_adjustment import (
    apply_course_adjustment,
    prepare_course_history,
)


def round_row(event_id, event_end, course_id, performance):
    return {
        "event_id": event_id,
        "event_date_start": event_end,
        "event_date_end": event_end,
        "course_id": course_id,
        "player_id": "player_a",
        "player_name": "Player A",
        "round_number": "1",
        "relative_to_field": str(performance),
    }


def strength_row():
    return {
        "player_id": "player_a",
        "player_name": "Player A",
        "weighted_mean_relative": 1.0,
        "shrunk_mean_relative": 0.8,
    }


def test_course_adjustment_uses_only_completed_prior_same_course_rounds():
    history = prepare_course_history(
        [
            round_row("past_same", "2025-01-01", "course_a", 3.0),
            round_row("past_other", "2025-01-02", "course_b", -5.0),
            round_row("current", "2025-04-10", "course_a", -8.0),
            round_row("future", "2025-05-01", "course_a", -8.0),
        ]
    )

    rows = apply_course_adjustment(
        [strength_row()],
        "course_a",
        "2025-04-10",
        history,
        half_life_days=365,
        course_prior_rounds=1,
        adjustment_weight=1,
    )

    assert rows[0]["course_rounds_used"] == 1
    assert rows[0]["course_residual_relative"] == 2.0
    assert rows[0]["course_adjustment"] > 0
    assert rows[0]["shrunk_mean_relative"] > 0.8


def test_course_adjustment_shrinks_and_caps_signal():
    history = prepare_course_history(
        [round_row("past", "2025-01-01", "course_a", 20.0)]
    )

    shrunk = apply_course_adjustment(
        [strength_row()],
        "course_a",
        "2025-04-10",
        history,
        half_life_days=365,
        course_prior_rounds=20,
        adjustment_weight=1,
    )[0]
    capped = apply_course_adjustment(
        [strength_row()],
        "course_a",
        "2025-04-10",
        history,
        half_life_days=365,
        course_prior_rounds=0,
        adjustment_weight=1,
        max_absolute_adjustment=2,
    )[0]

    assert 0 < shrunk["course_adjustment"] < 2
    assert capped["course_adjustment"] == 2


def test_zero_weight_or_unknown_course_preserves_incumbent_strength():
    history = prepare_course_history(
        [round_row("past", "2025-01-01", "course_a", 3.0)]
    )

    zero_weight = apply_course_adjustment(
        [strength_row()],
        "course_a",
        "2025-04-10",
        history,
        half_life_days=365,
        course_prior_rounds=8,
        adjustment_weight=0,
    )[0]
    unknown = apply_course_adjustment(
        [strength_row()],
        "course_unknown",
        "2025-04-10",
        history,
        half_life_days=365,
        course_prior_rounds=8,
        adjustment_weight=1,
    )[0]

    assert zero_weight["shrunk_mean_relative"] == 0.8
    assert unknown["shrunk_mean_relative"] == 0.8
    assert unknown["course_rounds_used"] == 0
