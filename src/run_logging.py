"""Local, provider-neutral run and cost logging."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def prompt_version(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def token_count(value: Any) -> int | None:
    return value if isinstance(value, int) else None


class RunLogger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def log(self, **event: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
