"""Fail-closed Final-validity evidence for OSM writeback artifacts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Any, Mapping


_ERROR_KEYS = {
    "scope", "error_type", "object_type", "object_name", "field", "raw",
}
_STAGE_KEYS = {
    "valid", "error_count", "errors", "errors_truncated",
    "normalized_error_multiset", "normalized_error_count",
    "normalization_truncated", "normalization_truncated_field_count",
    "normalization_truncated_fields", "no_regression",
}
_BRACKETED_ABSOLUTE_PATH_RE = re.compile(
    r"\[(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^\]\r\n]*\]", re.ASCII,
)
_DOUBLE_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r'"(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^"\r\n]*"', re.ASCII,
)
_SINGLE_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"'(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^'\r\n]*'", re.ASCII,
)
_BARE_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_\\/])(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)"
    r"[^\]\[;,\"'\r\n]*?"
    r"\.(?:[oO][sS][mM]|[iI][dD][fF]|[jJ][sS][oO][nN]|"
    r"[eE][pP][wW]|[iI][dD][dD])(?::[0-9]+)?"
    r"(?=$|[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\]\[;,\"')])",
)
_CANONICAL_WHITESPACE_RE = re.compile(r"[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+")
MAX_VALIDITY_FIELD_CHARS = 1_000
_TRUNCATION_MARKER = "␞<truncated>␞"
MAX_VALIDITY_ERRORS = 500


@dataclass(frozen=True, slots=True)
class ValidatedValidity:
    """Canonical multiplicities recovered from one complete validity stage."""

    error_count: int
    multiset: Counter[str]


def normalize_validity_error(value: object) -> dict[str, Any] | None:
    result = _normalize_validity_error_with_metadata(value)
    return None if result is None else result[0]


def _normalize_validity_error_with_metadata(
    value: object,
) -> tuple[dict[str, Any], int] | None:
    if not isinstance(value, Mapping) or set(value) != _ERROR_KEYS:
        return None
    normalized: dict[str, Any] = {}
    truncated_field_count = 0
    for key in ("scope", "error_type", "object_type", "object_name", "field"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            return None
        if item is not None and not _valid_unicode(item):
            return None
        if item is None:
            normalized[key] = None
        else:
            normalized[key], truncated = _bounded_validity_text(item)
            truncated_field_count += int(truncated)
    raw = value.get("raw")
    if raw is None:
        normalized["raw"] = None
    else:
        if not isinstance(raw, str) or not _valid_unicode(raw):
            return None
        normalized["raw"], truncated = _bounded_validity_text(raw)
        truncated_field_count += int(truncated)
    return normalized, truncated_field_count


def _bounded_validity_text(value: str) -> tuple[str, bool]:
    text = _BRACKETED_ABSOLUTE_PATH_RE.sub("[<path>]", value)
    text = _DOUBLE_QUOTED_ABSOLUTE_PATH_RE.sub('"<path>"', text)
    text = _SINGLE_QUOTED_ABSOLUTE_PATH_RE.sub("'<path>'", text)
    text = _BARE_ABSOLUTE_PATH_RE.sub("<path>", text)
    text = _CANONICAL_WHITESPACE_RE.sub(" ", text).strip(" ")
    text = text.replace("~", "~0").replace("<truncated>", "~1")
    if len(text) <= MAX_VALIDITY_FIELD_CHARS:
        return text, False
    keep = MAX_VALIDITY_FIELD_CHARS - len(_TRUNCATION_MARKER)
    if text[keep - 1:keep] == "~":
        keep -= 1
    return text[:keep] + _TRUNCATION_MARKER, True


def _valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _canonical_published_validity_text(value: str) -> bool:
    if (
        not _valid_unicode(value)
        or len(value) > MAX_VALIDITY_FIELD_CHARS
        or _CANONICAL_WHITESPACE_RE.sub(" ", value).strip(" ") != value
    ):
        return False
    truncated = value.endswith(_TRUNCATION_MARKER)
    if truncated:
        if len(value) not in {MAX_VALIDITY_FIELD_CHARS, MAX_VALIDITY_FIELD_CHARS - 1}:
            return False
        body = value[:-len(_TRUNCATION_MARKER)]
    else:
        body = value
    if _TRUNCATION_MARKER in body or "<truncated>" in body:
        return False
    if (
        _BRACKETED_ABSOLUTE_PATH_RE.search(body)
        or _DOUBLE_QUOTED_ABSOLUTE_PATH_RE.search(body)
        or _SINGLE_QUOTED_ABSOLUTE_PATH_RE.search(body)
        or _BARE_ABSOLUTE_PATH_RE.search(body)
    ):
        return False
    index = 0
    while index < len(body):
        if body[index] != "~":
            index += 1
            continue
        if index + 1 >= len(body) or body[index + 1] not in {"0", "1"}:
            return False
        index += 2
    return True


def validity_error_multiset(value: object) -> Counter[str] | None:
    """Return the canonical six-field multiset for one raw Final report."""

    if not isinstance(value, Mapping):
        return None
    valid = value.get("valid")
    error_count = value.get("error_count")
    errors = value.get("errors")
    if (
        not isinstance(valid, bool)
        or not isinstance(error_count, int)
        or isinstance(error_count, bool)
        or error_count < 0
        or error_count > MAX_VALIDITY_ERRORS
        or not isinstance(errors, list)
        or error_count != len(errors)
        or value.get("errors_truncated") is not False
        or valid is not (error_count == 0)
    ):
        return None
    normalized: list[dict[str, Any]] = []
    for error in errors:
        row = normalize_validity_error(error)
        if row is None:
            return None
        normalized.append(row)
    return Counter(_error_token(error) for error in normalized)


def _error_token(error: Mapping[str, Any]) -> str:
    return json.dumps(
        error,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def validate_validity_stage(value: object) -> ValidatedValidity | None:
    """Recompute one bounded stage instead of trusting self-asserted fields."""

    if not isinstance(value, Mapping) or set(value) != _STAGE_KEYS:
        return None
    valid = value.get("valid")
    error_count = value.get("error_count")
    errors = value.get("errors")
    if (
        not isinstance(valid, bool)
        or not isinstance(error_count, int)
        or isinstance(error_count, bool)
        or error_count < 0
        or error_count > MAX_VALIDITY_ERRORS
        or not isinstance(errors, list)
        or error_count != len(errors)
        or value.get("errors_truncated") is not False
        or valid is not (error_count == 0)
        or not isinstance(value.get("normalized_error_count"), int)
        or isinstance(value.get("normalized_error_count"), bool)
        or value.get("normalized_error_count") != error_count
        or not isinstance(value.get("no_regression"), bool)
    ):
        return None

    normalized_errors: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, Mapping) or set(error) != _ERROR_KEYS:
            return None
        normalized = dict(error)
        if any(
            item is not None and (
                not isinstance(item, str)
                or not _canonical_published_validity_text(item)
            )
            for item in normalized.values()
        ):
            return None
        normalized_errors.append(normalized)
    counts = Counter(_error_token(error) for error in normalized_errors)
    truncated_field_count = value.get("normalization_truncated_field_count")
    truncated_fields = value.get("normalization_truncated_fields")
    normalization_truncated = value.get("normalization_truncated")
    if (
        not isinstance(truncated_field_count, int)
        or isinstance(truncated_field_count, bool)
        or truncated_field_count < 0
        or truncated_field_count > error_count * len(_ERROR_KEYS)
        or not isinstance(normalization_truncated, bool)
        or normalization_truncated is not (truncated_field_count > 0)
        or not isinstance(truncated_fields, list)
        or len(truncated_fields) != truncated_field_count
    ):
        return None
    expected_truncated_fields = sorted(
        (
            {"error_index": error_index, "field": field}
            for error_index, error in enumerate(normalized_errors)
            for field, item in error.items()
            if isinstance(item, str) and item.endswith(_TRUNCATION_MARKER)
        ),
        key=lambda row: (row["error_index"], row["field"]),
    )
    if (
        any(
            not isinstance(row, Mapping)
            or set(row) != {"error_index", "field"}
            or not isinstance(row.get("error_index"), int)
            or isinstance(row.get("error_index"), bool)
            or row.get("error_index", -1) < 0
            or row.get("field") not in _ERROR_KEYS
            for row in truncated_fields
        )
        or truncated_fields != expected_truncated_fields
    ):
        return None
    rows_by_token = {
        _error_token(error): error for error in normalized_errors
    }
    expected_rows = [
        {**rows_by_token[token], "count": counts[token]}
        for token in sorted(counts)
    ]
    normalized_multiset = value.get("normalized_error_multiset")
    if (
        not isinstance(normalized_multiset, list)
        or any(
            not isinstance(row, Mapping)
            or set(row) != _ERROR_KEYS | {"count"}
            or not isinstance(row.get("count"), int)
            or isinstance(row.get("count"), bool)
            or row.get("count", 0) < 1
            for row in normalized_multiset
        )
        or normalized_multiset != expected_rows
    ):
        return None
    return ValidatedValidity(error_count=error_count, multiset=counts)


def is_validity_subset(
    candidate: ValidatedValidity,
    baseline: ValidatedValidity,
) -> bool:
    """Return whether no normalized error multiplicity was introduced."""

    return all(
        count <= baseline.multiset.get(token, 0)
        for token, count in candidate.multiset.items()
    )


def validate_validity_chain(
    value: object,
    *,
    independent_source: ValidatedValidity,
    independent_child: ValidatedValidity,
) -> bool:
    """Verify source→mutation→reload evidence and both independent endpoints."""

    required = {
        "source_before", "after_mutation_before_save", "after_reload",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return False
    source = validate_validity_stage(value.get("source_before"))
    mutation = validate_validity_stage(value.get("after_mutation_before_save"))
    reload = validate_validity_stage(value.get("after_reload"))
    if source is None or mutation is None or reload is None:
        return False
    stages = [value[key] for key in (
        "source_before", "after_mutation_before_save", "after_reload",
    )]
    return bool(
        all(stage.get("no_regression") is True for stage in stages)
        and source.multiset == independent_source.multiset
        and reload.multiset == independent_child.multiset
        and is_validity_subset(mutation, source)
        and is_validity_subset(reload, mutation)
        and is_validity_subset(reload, source)
    )


__all__ = [
    "ValidatedValidity",
    "is_validity_subset",
    "normalize_validity_error",
    "validate_validity_chain",
    "validate_validity_stage",
    "validity_error_multiset",
]
