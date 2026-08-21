"""Conservative, auditable cross-source course identity matching."""

from __future__ import annotations

import csv
import html
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

from golf_props.schemas import COURSE_ALIASES_COLUMNS


ACCEPTED_REVIEW_STATUSES = {"accepted"}
GENERIC_COURSE_NAMES = {
    "champion course",
    "championship course",
    "north course",
    "oaks course",
    "south course",
    "stadium course",
}
ABBREVIATIONS = {
    "cc": ("country", "club"),
    "gc": ("golf", "club"),
}


class CourseIdentityError(ValueError):
    """Raised when a course crosswalk is invalid or unsafe to apply."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise CourseIdentityError(f"missing course identity input: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    columns: list[str],
    rows: Iterable[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def strip_location_suffix(value: str) -> str:
    """Remove only a trailing `` - City, Region``-style source suffix."""

    parts = re.split(r"\s+-\s+", value)
    if len(parts) < 2:
        return value
    suffix = parts[-1].strip()
    if "," not in suffix:
        return value
    location_parts = [part.strip() for part in suffix.split(",")]
    if len(location_parts) not in {2, 3} or not all(location_parts):
        return value
    return " - ".join(parts[:-1]).strip()


def normalize_course_name(value: object) -> str:
    """Normalize course names for exact, explainable matching only."""

    text = html.unescape(str(value or "")).strip().casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = strip_location_suffix(text)
    text = text.replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", text)
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(ABBREVIATIONS.get(token, (token,)))
    return " ".join(expanded)


def normalized_tokens(value: object) -> tuple[str, ...]:
    return tuple(sorted(normalize_course_name(value).split()))


def is_generic_course_name(value: object) -> bool:
    normalized = normalize_course_name(value)
    if normalized in GENERIC_COURSE_NAMES:
        return True
    tokens = normalized.split()
    return len(tokens) <= 2 and bool(tokens) and tokens[-1] == "course"


def _proposal_row(
    source_row: dict[str, str],
    canonical_row: Optional[dict[str, str]],
    match_method: str,
    confidence: str,
    review_status: str,
    notes: str,
) -> dict[str, str]:
    return {
        "source": source_row.get("source", ""),
        "source_course_id": source_row.get("source_course_id", ""),
        "source_course_name": source_row.get("course_name", ""),
        "canonical_course_id": (
            canonical_row.get("course_id", "") if canonical_row else ""
        ),
        "canonical_course_name": (
            canonical_row.get("course_name", "") if canonical_row else ""
        ),
        "match_method": match_method,
        "confidence": confidence,
        "review_status": review_status,
        "notes": notes,
    }


def propose_course_aliases(
    canonical_courses: list[dict[str, str]],
    source_courses: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Propose only unique exact normalized or exact token-set matches."""

    by_normalized: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_tokens: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in canonical_courses:
        by_normalized[normalize_course_name(row.get("course_name"))].append(row)
        by_tokens[normalized_tokens(row.get("course_name"))].append(row)

    proposals = []
    for source_row in source_courses:
        source_name = source_row.get("course_name", "")
        if is_generic_course_name(source_name):
            proposals.append(
                _proposal_row(
                    source_row,
                    None,
                    "generic_name_blocked",
                    "",
                    "review_required",
                    "Generic course name requires venue/location review.",
                )
            )
            continue

        normalized_matches = by_normalized.get(normalize_course_name(source_name), [])
        if len(normalized_matches) == 1:
            proposals.append(
                _proposal_row(
                    source_row,
                    normalized_matches[0],
                    "exact_normalized_name",
                    "high",
                    "proposed",
                    "Unique exact match after documented normalization.",
                )
            )
            continue
        if len(normalized_matches) > 1:
            proposals.append(
                _proposal_row(
                    source_row,
                    None,
                    "ambiguous_exact_normalized_name",
                    "",
                    "review_required",
                    f"{len(normalized_matches)} canonical candidates share the normalized name.",
                )
            )
            continue

        token_matches = by_tokens.get(normalized_tokens(source_name), [])
        if len(token_matches) == 1:
            proposals.append(
                _proposal_row(
                    source_row,
                    token_matches[0],
                    "exact_normalized_tokens",
                    "high",
                    "proposed",
                    "Unique exact token-set match after documented normalization.",
                )
            )
        elif len(token_matches) > 1:
            proposals.append(
                _proposal_row(
                    source_row,
                    None,
                    "ambiguous_exact_normalized_tokens",
                    "",
                    "review_required",
                    f"{len(token_matches)} canonical candidates share the normalized tokens.",
                )
            )
        else:
            proposals.append(
                _proposal_row(
                    source_row,
                    None,
                    "unresolved",
                    "",
                    "review_required",
                    "No unique exact normalized or token-set match.",
                )
            )
    return proposals


def render_course_alias_audit(rows: list[dict[str, str]]) -> str:
    status_counts: dict[str, int] = defaultdict(int)
    method_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[row["review_status"]] += 1
        method_counts[row["match_method"]] += 1
    lines = [
        "# Course Identity Proposal Audit",
        "",
        "This command proposes exact normalized/token matches only. It does not",
        "accept mappings; a reviewer must change `review_status` to `accepted`.",
        "",
        f"- source courses: {len(rows)}",
        f"- proposed: {status_counts.get('proposed', 0)}",
        f"- review required: {status_counts.get('review_required', 0)}",
        "",
        "## Match Methods",
        "",
    ]
    for method, count in sorted(method_counts.items()):
        lines.append(f"- {method}: {count}")
    return "\n".join(lines).rstrip() + "\n"


def audit_course_aliases(
    base_dir: Path,
    add_dir: Path,
    output_path: Path,
    report_path: Optional[Path] = None,
) -> dict[str, object]:
    rows = propose_course_aliases(
        read_csv(base_dir / "courses.csv"),
        read_csv(add_dir / "courses.csv"),
    )
    write_csv(output_path, COURSE_ALIASES_COLUMNS, rows)
    report_path = report_path or output_path.with_suffix(".report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_course_alias_audit(rows), encoding="utf-8")
    return {"rows": rows, "output_path": output_path, "report_path": report_path}


def load_accepted_course_aliases(
    path: Path,
    courses: list[dict[str, str]],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    rows = read_csv(path)
    available_columns = set(rows[0]) if rows else set(COURSE_ALIASES_COLUMNS)
    missing = set(COURSE_ALIASES_COLUMNS) - available_columns
    if missing:
        raise CourseIdentityError(
            f"course crosswalk missing columns: {', '.join(sorted(missing))}"
        )

    course_by_id = {row["course_id"]: row for row in courses}
    source_identity_to_course_id = {
        (row.get("source", ""), row.get("source_course_id", "")): row["course_id"]
        for row in courses
    }
    mapping: dict[str, str] = {}
    seen_source_identities: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise CourseIdentityError(
                f"course crosswalk row {row_number} has more values than columns"
            )
        source_identity = (row["source"], row["source_course_id"])
        if source_identity in seen_source_identities:
            raise CourseIdentityError(
                f"duplicate course crosswalk source identity on row {row_number}: "
                f"{source_identity[0]}|{source_identity[1]}"
            )
        seen_source_identities.add(source_identity)
        if row["review_status"].strip().casefold() not in ACCEPTED_REVIEW_STATUSES:
            continue
        source_course_id = source_identity_to_course_id.get(source_identity)
        if source_course_id is None:
            raise CourseIdentityError(
                f"accepted crosswalk row {row_number} has unknown source identity: "
                f"{source_identity[0]}|{source_identity[1]}"
            )
        canonical_course_id = row["canonical_course_id"].strip()
        if canonical_course_id not in course_by_id:
            raise CourseIdentityError(
                f"accepted crosswalk row {row_number} has unknown canonical_course_id: "
                f"{canonical_course_id}"
            )
        if row["canonical_course_name"].strip() != course_by_id[
            canonical_course_id
        ].get("course_name", "").strip():
            raise CourseIdentityError(
                f"accepted crosswalk row {row_number} canonical name does not match "
                f"{canonical_course_id}"
            )
        mapping[source_course_id] = canonical_course_id
    return mapping, rows
