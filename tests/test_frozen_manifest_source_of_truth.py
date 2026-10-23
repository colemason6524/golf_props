"""Regression guard: exactly one frozen-model manifest is the source of truth.

Approved resolution, 2026-10-23 (``docs/INTEGRITY_AUDIT_2026-10-22.md`` section
6): the live manifest hard-coded in ``pipelines/weekly_forecast.py``
(``WeeklyPaths.manifest``) is THE manifest the production loop loads. The two
other files that used to claim the same role are labelled and read by nothing:

* ``data/frozen_model_manifest.json`` - tracked, byte-identical legacy copy.
* ``data/interim/reports/rolling_recompute_20261007/frozen_model_manifest.json``
  - derived by-product of the 2026-10-07 recompute.

These tests fail if a second manifest path appears in production code, if a
module starts reading a legacy copy, or if a legacy label is dropped.
"""

from __future__ import annotations

from pathlib import Path

from golf_props.config import PROJECT_ROOT
from golf_props.pipelines.weekly_forecast import WeeklyPaths

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

LIVE_MANIFEST = (
    "data/interim/reports/rolling_round_simulation_validation/"
    "frozen_model_manifest.json"
)
WEEKLY_FORECAST_MODULE = "src/golf_props/pipelines/weekly_forecast.py"
WRITER_MODULE = "src/golf_props/backtest/rolling_simulation_validation.py"

# (legacy manifest, adjacent label note) pairs.
LEGACY_COPIES = (
    (
        "data/frozen_model_manifest.json",
        "data/frozen_model_manifest.LEGACY.md",
    ),
    (
        "data/interim/reports/rolling_recompute_20261007/"
        "frozen_model_manifest.json",
        "data/interim/reports/rolling_recompute_20261007/"
        "frozen_model_manifest.DERIVED.md",
    ),
)

SOURCE_MODULES = sorted(
    path.relative_to(REPO_ROOT).as_posix()
    for path in SRC_ROOT.rglob("*.py")
)


def _manifest_mentions():
    """Every (module, stripped line) in src/ that names a manifest file."""
    mentions = []
    for module in SOURCE_MODULES:
        for line in (REPO_ROOT / module).read_text(encoding="utf-8").splitlines():
            if "frozen_model_manifest" in line:
                mentions.append((module, line.strip()))
    return mentions


def test_live_manifest_is_the_weekly_forecast_path():
    """(a) The production loop reads the documented live path and nothing else."""
    manifest = Path(WeeklyPaths().manifest)
    assert manifest == PROJECT_ROOT / LIVE_MANIFEST
    assert manifest.as_posix().endswith("/" + LIVE_MANIFEST)


def test_production_code_names_only_the_live_manifest():
    """(a) No second manifest path exists in src/; the writer stays path-free."""
    mentions = _manifest_mentions()
    modules = {module for module, _ in mentions}
    assert modules == {WEEKLY_FORECAST_MODULE, WRITER_MODULE}, (
        "unexpected module referencing a frozen manifest: "
        f"{sorted(modules - {WEEKLY_FORECAST_MODULE, WRITER_MODULE})}"
    )

    reader_lines = [
        line
        for module, line in mentions
        if module == WEEKLY_FORECAST_MODULE
    ]
    assert len(reader_lines) == 1, reader_lines
    assert LIVE_MANIFEST in reader_lines[0], reader_lines[0]

    writer_lines = [
        line for module, line in mentions if module == WRITER_MODULE
    ]
    assert len(writer_lines) == 1, writer_lines
    # The writer names a bare filename under a caller-supplied output directory,
    # so it cannot hard-code a second manifest location.
    assert "frozen_model_manifest.json" in writer_lines[0], writer_lines[0]
    assert "data/" not in writer_lines[0], writer_lines[0]


def test_no_module_reads_a_legacy_copy():
    """(b) Neither legacy/derived copy is referenced by any src/ module."""
    for legacy_manifest, _note in LEGACY_COPIES:
        legacy_dir = legacy_manifest.rsplit("/", 1)[0]
        for module in SOURCE_MODULES:
            text = (REPO_ROOT / module).read_text(encoding="utf-8")
            assert legacy_manifest not in text, (module, legacy_manifest)
            assert "rolling_recompute_20261007" not in text, (module, legacy_dir)
            assert "frozen_model_manifest.LEGACY" not in text, module
            assert "frozen_model_manifest.DERIVED" not in text, module
            assert "data/frozen_model_manifest.json" not in text, module


def test_legacy_copies_carry_a_label_note():
    """The labels cannot rot away while the files they describe still exist."""
    for legacy_manifest, note in LEGACY_COPIES:
        manifest_path = REPO_ROOT / legacy_manifest
        if not manifest_path.is_file():
            continue  # data/interim/ is untracked; absent in a fresh clone
        note_path = REPO_ROOT / note
        assert note_path.is_file(), f"missing label note for {legacy_manifest}"
        text = note_path.read_text(encoding="utf-8").lower()
        assert "not the source of truth" in text
        assert LIVE_MANIFEST in text


def test_legacy_note_is_versioned_with_the_tracked_copy():
    """The tracked legacy copy must never ship without its label."""
    assert (REPO_ROOT / "data/frozen_model_manifest.LEGACY.md").is_file()
