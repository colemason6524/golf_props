import csv
import json
from pathlib import Path

from golf_props.backtest.current_event_rankings import (
    blend_event_fit_probability,
    build_current_event_rankings,
    shrink_probability,
)
from golf_props.backtest.value_report import build_value_report
from golf_props.cli import main
from golf_props.features.player_event import build_features
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.pipelines.dk_current_value import run_dk_current_value

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_features(tmp_path):
    processed_dir = tmp_path / "processed"
    features_path = tmp_path / "features" / "player_event_features.csv"
    normalize_file(FIXTURE, processed_dir)
    build_features(processed_dir, features_path)
    return features_path


def write_odds(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "odds_id,event_id,event_name,season,player_id,player_name,sportsbook,market_type,market_name,selection_name,line,price_american,price_decimal,implied_probability,captured_at_utc,source_url,market_status,is_closing_candidate",
                "odds_0,,Masters Tournament,2026,,Scottie Scheffler,DraftKings,winner,winner,Scottie Scheffler,,500,6.0,0.166667,2026-04-09T12:00:00Z,https://example.test,open,False",
                "odds_1,,Masters Tournament,2026,,Scottie Scheffler,DraftKings,top20,top20,Scottie Scheffler,,110,2.1,0.47619,2026-04-09T12:00:00Z,https://example.test,open,False",
                "odds_2,,Masters Tournament,2026,,Jordan Spieth,DraftKings,make_cut,make_cut,Jordan Spieth,,-200,1.5,0.666667,2026-04-09T12:00:00Z,https://example.test,open,False",
                "odds_3,,Masters Tournament,2026,,New Player,DraftKings,top10,top10,New Player,,300,4.0,0.25,2026-04-09T12:00:00Z,https://example.test,open,False",
                "odds_4,,Masters Tournament,2026,,Jordan L. Spieth,DraftKings,top5,top5,Jordan L. Spieth,,500,6.0,0.166667,2026-04-09T12:00:00Z,https://example.test,open,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_previous_odds(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "odds_id,event_id,event_name,season,player_id,player_name,sportsbook,market_type,market_name,selection_name,line,price_american,price_decimal,implied_probability,captured_at_utc,source_url,market_status,is_closing_candidate",
                "odds_0,,Masters Tournament,2026,,Scottie Scheffler,DraftKings,winner,winner,Scottie Scheffler,,600,7.0,0.142857,2026-04-09T11:00:00Z,https://example.test,open,False",
                "odds_1,,Masters Tournament,2026,,Scottie Scheffler,DraftKings,top20,top20,Scottie Scheffler,,130,2.3,0.434783,2026-04-09T11:00:00Z,https://example.test,open,False",
                "odds_2,,Masters Tournament,2026,,Jordan Spieth,DraftKings,make_cut,make_cut,Jordan Spieth,,-180,1.555556,0.642857,2026-04-09T11:00:00Z,https://example.test,open,False",
                "odds_3,,Masters Tournament,2026,,New Player,DraftKings,top10,top10,New Player,,250,3.5,0.285714,2026-04-09T11:00:00Z,https://example.test,open,False",
                "odds_4,,Masters Tournament,2026,,Jordan L. Spieth,DraftKings,top5,top5,Jordan L. Spieth,,550,6.5,0.153846,2026-04-09T11:00:00Z,https://example.test,open,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_current_event_rankings_from_odds_field_join_value_report(tmp_path):
    features = prepare_features(tmp_path)
    odds = tmp_path / "odds" / "dk.csv"
    odds_history_dir = tmp_path / "odds_history"
    rankings_dir = tmp_path / "rankings"
    value_dir = tmp_path / "value"
    movement_dir = tmp_path / "movement"
    write_previous_odds(odds_history_dir / "dk_golf_placement_20260409T110000Z.csv")
    write_odds(odds)

    result = build_current_event_rankings(
        features,
        odds,
        rankings_dir,
        event_date="2026-04-09",
        min_prior_starts=1,
    )
    build_value_report(rankings_dir / "event_rankings.csv", odds, value_dir)

    rankings = read_csv(rankings_dir / "event_rankings.csv")
    value_rows = read_csv(value_dir / "value_report.csv")
    report = (rankings_dir / "report.md").read_text(encoding="utf-8")

    assert len(rankings) == 4
    assert round(sum(float(row["winner_prob"]) for row in rankings), 6) == 1.0
    assert all(row["winner_rank"] for row in rankings)
    assert result["unmatched_players"] == ["New Player"]
    assert all(row["event_name"] == "Masters Tournament" for row in rankings)
    assert all(row["season"] == "2026" for row in rankings)
    assert all(row["model_type"] == "current_player_rolling" for row in rankings)
    assert len(value_rows) == 5
    assert "winner" in {row["market_type"] for row in value_rows}
    assert "unmatched_players_using_base_rates: 1" in report


def test_shrink_probability_blends_small_samples_toward_base_rate():
    assert round(shrink_probability(1.0, 0.5, prior_starts=2), 6) == 0.6
    assert round(shrink_probability(1.0, 0.5, prior_starts=40), 6) == 0.916667


def test_blend_event_fit_probability_uses_open_history_for_the_open():
    feature_row = {
        "major_starts": "8",
        "major_top20_rate": "0.5",
        "open_starts": "4",
        "open_top20_rate": "0.75",
    }

    blended = blend_event_fit_probability(
        recent_prob=0.4,
        market="top20",
        feature_row=feature_row,
        fallback_prob=0.25,
        event_name="The Open Championship",
    )

    assert round(blended, 6) == 0.384091


def test_cli_current_event_rankings(tmp_path):
    features = prepare_features(tmp_path)
    odds = tmp_path / "odds" / "dk.csv"
    output_dir = tmp_path / "rankings"
    write_odds(odds)

    exit_code = main(
        [
            "current-event-rankings",
            "--features",
            str(features),
            "--odds",
            str(odds),
            "--output-dir",
            str(output_dir),
            "--event-date",
            "2026-04-09",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "event_rankings.csv").exists()


def test_run_dk_current_value_skip_collect(tmp_path):
    features = prepare_features(tmp_path)
    odds = tmp_path / "odds" / "dk.csv"
    odds_history_dir = tmp_path / "odds_history"
    rankings_dir = tmp_path / "rankings"
    value_dir = tmp_path / "value"
    movement_dir = tmp_path / "movement"
    write_previous_odds(odds_history_dir / "dk_golf_placement_20260409T110000Z.csv")
    write_odds(odds)

    result = run_dk_current_value(
        features_path=features,
        odds_output=odds,
        odds_history_dir=odds_history_dir,
        rankings_output_dir=rankings_dir,
        value_output_dir=value_dir,
        movement_output_dir=movement_dir,
        event_date="2026-04-09",
        skip_collect=True,
    )

    assert len(result["rankings"]) == 4
    assert len(result["value_rows"]) == 5
    assert (rankings_dir / "event_rankings.csv").exists()
    assert (value_dir / "value_report.csv").exists()
    assert result["odds_history_path"] == odds_history_dir / "dk_golf_placement_20260409T120000Z.csv"
    assert result["odds_history_path"].exists()
    assert result["run_metadata_path"] == value_dir / "run_metadata.json"
    assert len(result["movement_rows"]) == 5
    assert (movement_dir / "odds_movement.csv").exists()
    metadata = json.loads((value_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["odds_file_rows"] == 5
    assert metadata["ranking_rows"] == 4
    assert metadata["value_rows"] == 5
    assert metadata["movement_rows"] == 5
    assert metadata["unmatched_players"] == ["New Player"]


def test_cli_run_dk_current_value_skip_collect(tmp_path):
    features = prepare_features(tmp_path)
    odds = tmp_path / "odds" / "dk.csv"
    odds_history_dir = tmp_path / "odds_history"
    rankings_dir = tmp_path / "rankings"
    value_dir = tmp_path / "value"
    movement_dir = tmp_path / "movement"
    metadata_path = tmp_path / "run" / "metadata.json"
    write_previous_odds(odds_history_dir / "dk_golf_placement_20260409T110000Z.csv")
    write_odds(odds)

    exit_code = main(
        [
            "run-dk-current-value",
            "--features",
            str(features),
            "--odds-output",
            str(odds),
            "--odds-history-dir",
            str(odds_history_dir),
            "--rankings-output-dir",
            str(rankings_dir),
            "--value-output-dir",
            str(value_dir),
            "--movement-output-dir",
            str(movement_dir),
            "--run-metadata-output",
            str(metadata_path),
            "--event-date",
            "2026-04-09",
            "--skip-collect",
        ]
    )

    assert exit_code == 0
    assert (value_dir / "value_report.csv").exists()
    assert (odds_history_dir / "dk_golf_placement_20260409T120000Z.csv").exists()
    assert (movement_dir / "odds_movement.csv").exists()
    assert metadata_path.exists()
