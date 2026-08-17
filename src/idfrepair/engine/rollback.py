"""Explicit byte restoration helpers."""

from __future__ import annotations

from idfrepair.io.idf import text_sha256


def restore_original(original: str, current: str) -> tuple[str, bool]:
    restored = original
    return restored, text_sha256(restored) == text_sha256(original)
