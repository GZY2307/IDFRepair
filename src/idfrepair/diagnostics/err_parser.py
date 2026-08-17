"""Parser for EnergyPlus ERR severity records and continuations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from idfrepair.diagnostics.normalization import normalize_message


_ENTRY = re.compile(r"^\s*\*\*\s*(Warning|Severe|Fatal)\s*\*\*\s*(.*)$", re.I)
_CONTINUATION = re.compile(r"^\s*\*\*\s*~~~\s*\*\*\s*(.*)$")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: str
    message: str
    continuation: tuple[str, ...]
    signature: str


def parse_err(text: str) -> tuple[Diagnostic, ...]:
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        match = _ENTRY.match(raw)
        if match:
            message = match.group(2).strip()
            rows.append({
                "severity": match.group(1).title(),
                "message": message,
                "continuation": [],
            })
            continue
        continuation = _CONTINUATION.match(raw)
        if continuation and rows:
            rows[-1]["continuation"].append(continuation.group(1).strip())
    result = []
    for row in rows:
        message = str(row["message"])
        extra = tuple(str(item) for item in row["continuation"])
        normalized = normalize_message(" ".join((message, *extra)), replace_numbers=True)
        result.append(Diagnostic(
            severity=str(row["severity"]),
            message=message,
            continuation=extra,
            signature=sha256(normalized.encode("utf-8")).hexdigest()[:16],
        ))
    return tuple(result)


def diagnostic_counts(rows: tuple[Diagnostic, ...]) -> dict[str, int]:
    return {
        severity.casefold(): sum(row.severity.casefold() == severity.casefold() for row in rows)
        for severity in ("Warning", "Severe", "Fatal")
    }
