import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.normalization.manual_odds import (
    american_to_decimal,
    american_to_implied_probability,
    normalize_file,
)
from golf_props.schemas import ODDS_SNAPSHOTS_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "sample_manual_odds.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_american_odds_conversion():
    assert american_to_decimal(110) == 2.1
    assert american_to_decimal(-120) == 1.833333
    assert american_to_implied_probability(110) == 0.47619
    assert american_to_implied_probability(-120) == 0.545455


def test_normalize_manual_odds_writes_schema(tmp_path):
    output = tmp_path / "odds_snapshots.csv"
    normalize_file(FIXTURE, output)

    rows = read_csv(output)
    assert list(rows[0].keys()) == ODDS_SNAPSHOTS_COLUMNS
    assert len(rows) == 3
    assert rows[0]["market_type"] == "top20"
    assert rows[0]["price_american"] == "110"
    assert rows[0]["price_decimal"] == "2.1"
    assert rows[0]["implied_probability"] == "0.47619"


def test_cli_normalize_manual_odds(tmp_path):
    output = tmp_path / "odds_snapshots.csv"

    exit_code = main(
        [
            "normalize-manual-odds",
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.exists()
