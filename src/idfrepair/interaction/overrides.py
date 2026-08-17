"""Auditable override records; overrides never disable a validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class UserOverride:
    question_id: str
    kind: str
    value: Any
    provenance: str
    validation_bypassed: bool = False
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.validation_bypassed:
            raise ValueError("validation_bypass_is_forbidden")
