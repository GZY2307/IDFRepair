"""Read-only helpers for the post-Final EnergyPlus diagnostic baseline."""

from __future__ import annotations

from dataclasses import dataclass
import re


_MESSAGE = re.compile(
    r"^\s*\*\*\s*(Warning|Severe|Fatal)\s*\*\*\s*(.*?)\s*$",
    re.IGNORECASE,
)
_CONTINUATION = re.compile(r"^\s*\*\*\s*~~~\s*\*\*\s*(.*?)\s*$")


@dataclass(frozen=True, slots=True)
class ErrMessage:
    """One EnergyPlus diagnostic with its continuation text preserved."""

    severity: str
    text: str


def parse_err_messages(text: str) -> tuple[ErrMessage, ...]:
    """Extract Warning/Severe/Fatal blocks from an ``eplusout.err`` file."""

    messages: list[ErrMessage] = []
    for line in text.splitlines():
        match = _MESSAGE.match(line)
        if match:
            messages.append(ErrMessage(
                severity=match.group(1).upper(),
                text=match.group(2).strip(),
            ))
            continue
        continuation = _CONTINUATION.match(line)
        if continuation and messages:
            messages[-1] = ErrMessage(
                severity=messages[-1].severity,
                text=" ".join((messages[-1].text, continuation.group(1).strip())),
            )
    return tuple(messages)


__all__ = ["ErrMessage", "parse_err_messages"]
