"""Project paths and lightweight configuration."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INTERIM_DIR = DATA_DIR / "interim"
LOG_DIR = PROJECT_ROOT / "logs"


def project_paths() -> dict[str, Path]:
    return {
        "data_dir": DATA_DIR,
        "raw_dir": RAW_DIR,
        "processed_dir": PROCESSED_DIR,
        "interim_dir": INTERIM_DIR,
        "log_dir": LOG_DIR,
    }
