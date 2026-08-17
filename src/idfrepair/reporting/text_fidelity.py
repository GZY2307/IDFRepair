"""Deterministic, operation-aware IDF text-fidelity evidence."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re
from typing import Any, Iterable, Sequence

from idfrepair.domain.enums import OperationKind
from idfrepair.domain.models import RepairOperation
from idfrepair.io.idf import apply_operations, parse_idf


_FIELD_COMMENT = re.compile(r"!-[^\r\n]*")


def _line_number(text: str, offset: int) -> int:
    prefix = text[:max(0, offset)]
    return 1 + prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")


def _line_ending(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    styles = [("CRLF", crlf), ("LF", lf), ("CR", cr)]
    present = [name for name, count in styles if count]
    if not present:
        return "NONE"
    return present[0] if len(present) == 1 else "MIXED"


def _change_envelope(before: str, after: str) -> list[dict[str, Any]]:
    if before == after:
        return []
    prefix = 0
    limit = min(len(before), len(after))
    while prefix < limit and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    before_remaining = len(before) - prefix
    after_remaining = len(after) - prefix
    while (
        suffix < before_remaining
        and suffix < after_remaining
        and before[len(before) - suffix - 1] == after[len(after) - suffix - 1]
    ):
        suffix += 1
    before_end = len(before) - suffix
    after_end = len(after) - suffix
    return [{
        "method": "minimal_common_prefix_suffix_envelope",
        "before_start": prefix,
        "before_end": before_end,
        "after_start": prefix,
        "after_end": after_end,
        "before_line_start": _line_number(before, prefix),
        "before_line_end": _line_number(before, max(prefix, before_end - 1)),
        "after_line_start": _line_number(after, prefix),
        "after_line_end": _line_number(after, max(prefix, after_end - 1)),
        "before_sha256": sha256(before[prefix:before_end].encode("utf-8")).hexdigest(),
        "after_sha256": sha256(after[prefix:after_end].encode("utf-8")).hexdigest(),
    }]


def _resolve_before_object(document: Any, operation: RepairOperation) -> Any | None:
    if operation.object_index is not None:
        if 0 <= operation.object_index < len(document.objects):
            return document.objects[operation.object_index]
        return None
    if not operation.object_type:
        return None
    matches = document.find_objects(operation.object_type, operation.object_name)
    return matches[0] if len(matches) == 1 else None


def _authorized_removed_comments(
    before: str,
    operations: Sequence[RepairOperation],
) -> Counter[str]:
    authorized: Counter[str] = Counter()
    document = parse_idf(before) if operations else None
    for operation in operations:
        if operation.kind not in {
            OperationKind.DELETE_FIELD,
            OperationKind.DELETE_OBJECT,
            OperationKind.REPLACE_OBJECT,
            OperationKind.REPLACE_VERTICES,
        }:
            continue
        obj = _resolve_before_object(document, operation)
        if obj is None:
            continue
        line_end = before.find("\n", obj.end)
        if line_end < 0:
            line_end = len(before)
        object_text = before[obj.start:line_end]
        if operation.kind is OperationKind.DELETE_FIELD and operation.field_index is not None:
            if not 1 <= operation.field_index <= len(obj.fields):
                continue
            field = obj.fields[operation.field_index - 1]
            field_line_end = before.find("\n", field.end)
            if field_line_end < 0:
                field_line_end = len(before)
            comments = _FIELD_COMMENT.findall(before[field.end:field_line_end])
        else:
            comments = _FIELD_COMMENT.findall(object_text)
        authorized.update(comments)
    return authorized


def _replay(
    before: str,
    operation_groups: Sequence[Sequence[RepairOperation]],
) -> str | None:
    working = before
    try:
        for group in operation_groups:
            if group:
                working = apply_operations(working, group)
    except Exception:
        return None
    return working


def analyze_text_fidelity(
    before: str,
    after: str,
    *,
    operations: Iterable[RepairOperation] = (),
    operation_groups: Iterable[Sequence[RepairOperation]] | None = None,
    input_had_utf8_bom: bool = False,
    output_has_utf8_bom: bool = False,
) -> dict[str, Any]:
    """Return bounded proof data; never infer field names or rewrite the IDF."""
    flat_operations = tuple(operations)
    groups = tuple(tuple(group) for group in operation_groups) if operation_groups is not None else (
        (flat_operations,) if flat_operations else ()
    )
    if operation_groups is not None:
        flat_operations = tuple(operation for group in groups for operation in group)

    before_comments = Counter(_FIELD_COMMENT.findall(before))
    after_comments = Counter(_FIELD_COMMENT.findall(after))
    authorized_removed = _authorized_removed_comments(before, flat_operations)
    required_comments = before_comments - authorized_removed
    missing_comments = required_comments - after_comments
    inserted_fields = sum(operation.kind is OperationKind.INSERT_FIELD for operation in flat_operations)
    deleted_fields = sum(operation.kind is OperationKind.DELETE_FIELD for operation in flat_operations)
    eligible_names = [
        " ".join(str(operation.field_name).splitlines()).strip()
        for operation in flat_operations
        if operation.kind is OperationKind.INSERT_FIELD and operation.field_name
    ]
    generated = sum(
        max(0, after_comments[f"!- {name}"] - before_comments[f"!- {name}"])
        for name in eligible_names if name
    )
    replayed = before if not groups else _replay(before, groups)
    replay_matches = replayed == after
    before_line_ending = _line_ending(before)
    after_line_ending = _line_ending(after)
    line_ending_preserved = (
        before_line_ending == after_line_ending
        or before_line_ending == "NONE"
    )
    bom_preserved = input_had_utf8_bom == output_has_utf8_bom
    exact = before == after
    comments_preserved = not missing_comments
    proof_passed = replay_matches and comments_preserved and line_ending_preserved and bom_preserved
    return {
        "existing_comment_count_before": sum(before_comments.values()),
        "existing_comment_count_after": sum(after_comments.values()),
        "existing_comments_preserved": comments_preserved,
        "missing_existing_comments": list(missing_comments.elements())[:50],
        "authorized_removed_comment_count": sum(authorized_removed.values()),
        "changed_spans": _change_envelope(before, after),
        "inserted_fields": inserted_fields,
        "deleted_fields": deleted_fields,
        "generated_field_comments": {
            "eligible": len([name for name in eligible_names if name]),
            "generated": generated,
        },
        "line_ending_before": before_line_ending,
        "line_ending_after": after_line_ending,
        "line_ending_preserved": line_ending_preserved,
        "utf8_bom_policy": "preserve-input",
        "input_had_utf8_bom": input_had_utf8_bom,
        "output_has_utf8_bom": output_has_utf8_bom,
        "utf8_bom_preserved": bom_preserved,
        "exact_text_match": exact,
        "operation_replay_matches_output": replay_matches,
        "unmodified_regions_preserved": replay_matches,
        "proof_passed": proof_passed,
    }
