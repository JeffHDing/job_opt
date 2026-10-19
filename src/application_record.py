"""Structured local application records and artifact tracking."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = ("draft", "review", "approved", "applied", "interview", "closed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApplicationRecord:
    company: str
    role: str
    job_description: str
    resume_path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "draft"
    approval_state: str = "pending"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    artifacts: dict[str, str] = field(default_factory=dict)
    scores: dict[str, int | None] = field(default_factory=dict)
    stage_states: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown application status: {self.status}")
        if self.approval_state not in {"pending", "approved", "rejected"}:
            raise ValueError(f"unknown approval state: {self.approval_state}")

    def update(self, **changes: Any) -> None:
        for key, value in changes.items():
            if not hasattr(self, key):
                raise ValueError(f"unknown application field: {key}")
            setattr(self, key, value)
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApplicationStore:
    """Append/update records in a local JSON tracker."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[ApplicationRecord]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, list):
            raise ValueError("application tracker must contain a JSON array")
        return [ApplicationRecord(**item) for item in payload]

    def save(self, records: list[ApplicationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(
            [record.to_dict() for record in records], indent=2
        ) + "\n")
        temporary.replace(self.path)

    def upsert(self, record: ApplicationRecord) -> ApplicationRecord:
        records = self.load()
        for index, existing in enumerate(records):
            if existing.id == record.id:
                records[index] = record
                self.save(records)
                return record
        records.append(record)
        self.save(records)
        return record
