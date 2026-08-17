"""Stable diagnostic normalization helpers."""

from __future__ import annotations

import re


_PATH = re.compile(r"(?:[A-Za-z]:)?[/\\][^\s,;]+")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_SPACE = re.compile(r"\s+")


def normalize_message(value: str, *, replace_numbers: bool = False) -> str:
    text = _PATH.sub("<path>", value.casefold())
    if replace_numbers:
        text = _NUMBER.sub("<n>", text)
    return _SPACE.sub(" ", text).strip()


def message_tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9_:+.-]+", normalize_message(value)))
