"""Weekly event control record and state machine for the frozen forecast loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1

STATE_DISCOVERED = "discovered"
STATE_AWAITING_FIELD = "awaiting_field"
STATE_AWAITING_TEE_TIMES = "awaiting_tee_times"
STATE_AWAITING_IDENTITY = "awaiting_identity_resolution"
STATE_FORECAST_READY = "forecast_ready"
STATE_FORECAST_ARCHIVED = "forecast_archived"
STATE_BLOCKED = "blocked"
STATE_DEADLINE_MISSED = "deadline_missed"

TERMINAL_STATES = {STATE_FORECAST_ARCHIVED, STATE_DEADLINE_MISSED}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATE_DISCOVERED: {STATE_AWAITING_FIELD, STATE_AWAITING_TEE_TIMES, STATE_BLOCKED},
    STATE_AWAITING_FIELD: {STATE_AWAITING_TEE_TIMES, STATE_BLOCKED, STATE_DEADLINE_MISSED},
    STATE_AWAITING_TEE_TIMES: {
        STATE_AWAITING_IDENTITY,
        STATE_BLOCKED,
        STATE_DEADLINE_MISSED,
    },
    STATE_AWAITING_IDENTITY: {
        STATE_FORECAST_READY,
        STATE_BLOCKED,
        STATE_DEADLINE_MISSED,
    },
    STATE_FORECAST_READY: {
        STATE_FORECAST_ARCHIVED,
        STATE_BLOCKED,
        STATE_DEADLINE_MISSED,
    },
    STATE_BLOCKED: {
        STATE_AWAITING_FIELD,
        STATE_AWAITING_TEE_TIMES,
        STATE_AWAITING_IDENTITY,
        STATE_FORECAST_READY,
        STATE_FORECAST_ARCHIVED,
        STATE_DEADLINE_MISSED,
    },
    STATE_FORECAST_ARCHIVED: set(),
    STATE_DEADLINE_MISSED: set(),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass
class EventControl:
    schema_version: int = SCHEMA_VERSION
    event_key: str = ""
    event_name: str = ""
    tour: str = "PGA_TOUR_MAIN"
    season: int = 0
    source_event_id: str = ""
    schedule_start_date: str = ""
    schedule_end_date: str = ""
    competitive_start_date: str = ""
    course_name: str = ""
    course_location: str = ""
    expected_field_size: Optional[int] = None
    first_tee_at_utc: Optional[str] = None
    forecast_due_at_utc: Optional[str] = None
    state: str = STATE_DISCOVERED
    blocking_reason: str = ""
    created_at_utc: str = ""
    updated_at_utc: str = ""
    field_source: Optional[dict[str, Any]] = None
    tee_time_source: Optional[dict[str, Any]] = None
    structure_decision: Optional[dict[str, Any]] = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(
        self,
        new_state: str,
        note: str,
        now: Optional[datetime] = None,
    ) -> None:
        now = now or utc_now()
        allowed = ALLOWED_TRANSITIONS.get(self.state, set())
        if self.state in TERMINAL_STATES:
            raise ValueError(f"terminal state {self.state} cannot transition")
        if new_state not in allowed:
            raise ValueError(
                f"invalid state transition {self.state} -> {new_state}"
            )
        self.history.append(
            {
                "at_utc": iso_timestamp(now),
                "from_state": self.state,
                "to_state": new_state,
                "note": note,
            }
        )
        self.state = new_state
        if new_state == STATE_BLOCKED:
            self.blocking_reason = note
        elif new_state != STATE_BLOCKED:
            self.blocking_reason = ""
        self.updated_at_utc = iso_timestamp(now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EventControl":
        record = cls()
        for key, item in value.items():
            if hasattr(record, key):
                setattr(record, key, item)
        return record

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> Optional["EventControl"]:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(value, dict):
            return None
        return cls.from_dict(value)
