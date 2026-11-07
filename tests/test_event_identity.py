import pytest

from golf_props.odds.event_identity import event_name_match


@pytest.mark.parametrize("left,right,expected", [
    ("WWT Championship", "World Wide Technology Championship", "initialism"),
    ("W.W.T. Championship", "World Wide Technology Championship", "initialism"),
    ("World Wide Technology Championship", "WWT Championship", "initialism"),
    ("ABC Open", "Alpha Beta Company Open", "initialism"),
    ("Café–Open", "Cafe Open", "exact"),
    ("WWT", "World Wide Technology", None),
    ("WW Championship", "World Wide Championship", None),
    ("WWT Championship", "World Wide Technology Open", None),
    ("Mexico Open", "VidantaWorld Mexico Open", None),
    ("PGA Championship", "PGA TOUR Championship", None),
    ("", "", None),
])
def test_event_name_equivalence_preserves_distinctive_words(left, right, expected):
    assert event_name_match(left, right) == expected
