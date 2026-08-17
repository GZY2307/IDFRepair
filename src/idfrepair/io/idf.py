"""Loss-aware IDF parsing and finite operation application."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Iterable, Sequence

from idfrepair.domain.errors import CandidateApplicationError, InputFormatError
from idfrepair.domain.models import RepairOperation
from idfrepair.domain.enums import OperationKind


def canonical(value: str) -> str:
    return " ".join(value.casefold().split())


def text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IDFField:
    index: int
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class IDFObject:
    index: int
    object_type: str
    fields: tuple[IDFField, ...]
    start: int
    end: int
    raw: str

    @property
    def name(self) -> str:
        return self.fields[0].value if self.fields else ""


@dataclass(frozen=True, slots=True)
class IDFDocument:
    text: str
    objects: tuple[IDFObject, ...]
    issues: tuple[str, ...] = ()

    @property
    def sha256(self) -> str:
        return text_sha256(self.text)

    @property
    def version(self) -> str:
        for obj in self.objects:
            if canonical(obj.object_type) == "version" and obj.fields:
                return obj.fields[0].value.strip()
        return ""

    def find_objects(
        self, object_type: str, object_name: str | None = None,
    ) -> tuple[IDFObject, ...]:
        type_key = canonical(object_type)
        name_key = canonical(object_name or "")
        return tuple(
            obj for obj in self.objects
            if canonical(obj.object_type) == type_key
            and (object_name is None or canonical(obj.name) == name_key)
        )


def _visible_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    positions: list[int] = []
    in_comment = False
    in_quote = False
    for offset in range(start, end):
        char = text[offset]
        if in_comment:
            if char in "\r\n":
                in_comment = False
            continue
        if char == '"':
            in_quote = not in_quote
            positions.append(offset)
            continue
        if char == "!" and not in_quote:
            in_comment = True
            continue
        positions.append(offset)
    while positions and text[positions[0]].isspace():
        positions.pop(0)
    while positions and text[positions[-1]].isspace():
        positions.pop()
    if not positions:
        return end, end, ""
    left = positions[0]
    right = positions[-1] + 1
    return left, right, text[left:right].strip()


def parse_idf(text: str) -> IDFDocument:
    """Parse complete semicolon-terminated objects while retaining field spans."""
    if "\x00" in text:
        raise InputFormatError("idf_contains_nul")
    objects: list[IDFObject] = []
    issues: list[str] = []
    object_start = 0
    token_start = 0
    tokens: list[tuple[int, int, str]] = []
    in_comment = False
    in_quote = False
    for offset, char in enumerate(text):
        if in_comment:
            if char in "\r\n":
                in_comment = False
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if char == "!" and not in_quote:
            in_comment = True
            continue
        if in_quote:
            continue
        if char not in ",;":
            continue
        left, right, value = _visible_span(text, token_start, offset)
        tokens.append((left, right, value))
        token_start = offset + 1
        if char != ";":
            continue
        meaningful = [item for item in tokens if item[2] or len(tokens) > 1]
        if meaningful and meaningful[0][2]:
            object_type = meaningful[0][2]
            fields = tuple(
                IDFField(index=index, value=value, start=left, end=right)
                for index, (left, right, value) in enumerate(meaningful[1:], start=1)
            )
            objects.append(IDFObject(
                index=len(objects),
                object_type=object_type,
                fields=fields,
                start=object_start,
                end=offset + 1,
                raw=text[object_start:offset + 1],
            ))
        tokens = []
        object_start = offset + 1
    trailing_visible = _visible_span(text, token_start, len(text))[2]
    if tokens or trailing_visible:
        issues.append("unterminated_object")
    return IDFDocument(text=text, objects=tuple(objects), issues=tuple(issues))


def _resolve_object(document: IDFDocument, operation: RepairOperation) -> IDFObject:
    if operation.object_index is not None:
        if not 0 <= operation.object_index < len(document.objects):
            raise CandidateApplicationError("object_index_out_of_range")
        obj = document.objects[operation.object_index]
        if operation.object_type and canonical(obj.object_type) != canonical(operation.object_type):
            raise CandidateApplicationError("object_type_identity_mismatch")
        if operation.object_name and canonical(obj.name) != canonical(operation.object_name):
            raise CandidateApplicationError("object_name_identity_mismatch")
        return obj
    if not operation.object_type:
        raise CandidateApplicationError("object_identity_missing")
    matches = document.find_objects(operation.object_type, operation.object_name)
    if len(matches) != 1:
        raise CandidateApplicationError("object_identity_not_unique")
    return matches[0]


def _replace_field(text: str, obj: IDFObject, operation: RepairOperation) -> str:
    if operation.field_index is None or not 1 <= operation.field_index <= len(obj.fields):
        raise CandidateApplicationError("field_index_out_of_range")
    field = obj.fields[operation.field_index - 1]
    if operation.old_value is not None and field.value != operation.old_value:
        raise CandidateApplicationError("field_old_value_mismatch")
    if operation.new_value is None or operation.new_value == field.value:
        raise CandidateApplicationError("field_replacement_is_empty_or_noop")
    return text[:field.start] + operation.new_value + text[field.end:]


def _delete_field(text: str, obj: IDFObject, operation: RepairOperation) -> str:
    if operation.field_index is None or not 1 <= operation.field_index <= len(obj.fields):
        raise CandidateApplicationError("field_index_out_of_range")
    field = obj.fields[operation.field_index - 1]
    if operation.old_value is not None and field.value != operation.old_value:
        raise CandidateApplicationError("field_old_value_mismatch")
    line_start = max(text.rfind("\n", 0, field.start), text.rfind("\r", 0, field.start)) + 1
    line_breaks = [position for position in (
        text.find("\n", field.end), text.find("\r", field.end),
    ) if position >= 0]
    line_end = min(line_breaks) if line_breaks else len(text)
    line_ending_end = line_end
    if line_end < len(text):
        if text.startswith("\r\n", line_end):
            line_ending_end += 2
        else:
            line_ending_end += 1
    if operation.field_index == len(obj.fields):
        delimiter = text.rfind(",", obj.start, field.start)
        if delimiter < obj.start:
            raise CandidateApplicationError("field_delimiter_missing")
        start = line_start if not text[line_start:field.start].strip() else field.start
        if start == field.start:
            return text[:delimiter] + ";" + text[line_end:]
        return text[:delimiter] + ";" + text[delimiter + 1:start] + text[line_ending_end:]
    delimiter = text.find(",", field.end, obj.end)
    if delimiter < 0:
        raise CandidateApplicationError("field_delimiter_missing")
    trailing = text[delimiter + 1:line_end]
    if trailing.lstrip().startswith("!-"):
        start = line_start if not text[line_start:field.start].strip() else field.start
        return text[:start] + text[line_ending_end:]
    return text[:field.start] + text[delimiter + 1:]


def _insert_field(text: str, obj: IDFObject, operation: RepairOperation) -> str:
    if operation.new_value is None:
        raise CandidateApplicationError("inserted_field_value_missing")
    index = operation.field_index or len(obj.fields) + 1
    line_ending = "\r\n" if "\r\n" in text else ("\r" if "\r" in text else "\n")
    field_comment = ""
    if operation.field_name:
        field_name = " ".join(str(operation.field_name).splitlines()).strip()
        if field_name:
            field_comment = f"  !- {field_name}"
    if index == len(obj.fields) + 1:
        semicolon = obj.end - 1
        line_breaks = [position for position in (
            text.find("\n", semicolon), text.find("\r", semicolon),
        ) if position >= 0]
        line_end = min(line_breaks) if line_breaks else len(text)
        trailing = text[semicolon + 1:line_end]
        indent_start = max(text.rfind("\n", 0, semicolon), text.rfind("\r", 0, semicolon)) + 1
        indent = text[indent_start:obj.fields[-1].start] if obj.fields else "  "
        indent = indent if indent and not indent.strip() else "  "
        insertion = f"{line_ending}{indent}{operation.new_value};{field_comment}"
        if trailing.lstrip().startswith("!-"):
            boundary = line_end
            return text[:semicolon] + "," + text[semicolon + 1:boundary] + insertion + text[boundary:]
        return text[:semicolon] + "," + insertion + text[semicolon + 1:]
    if not 1 <= index <= len(obj.fields):
        raise CandidateApplicationError("inserted_field_index_out_of_range")
    field = obj.fields[index - 1]
    if not field_comment:
        return text[:field.start] + operation.new_value + ", " + text[field.start:]
    indent_start = max(text.rfind("\n", 0, field.start), text.rfind("\r", 0, field.start)) + 1
    indent = text[indent_start:field.start]
    indent = indent if not indent.strip() else "  "
    return (
        text[:field.start]
        + operation.new_value + "," + field_comment + line_ending + indent
        + text[field.start:]
    )


def _replace_object(text: str, obj: IDFObject, operation: RepairOperation) -> str:
    if operation.object_text is None:
        raise CandidateApplicationError("replacement_object_text_missing")
    if operation.old_value is not None and text[obj.start:obj.end] != operation.old_value:
        raise CandidateApplicationError("replacement_object_old_text_mismatch")
    return text[:obj.start] + operation.object_text + text[obj.end:]


def apply_operation(text: str, operation: RepairOperation) -> str:
    """Apply one allowlisted operation after resolving its exact target."""
    if operation.kind is OperationKind.INSERT_DELIMITER:
        offset = operation.metadata.get("offset")
        delimiter = operation.metadata.get("delimiter")
        left_context = operation.metadata.get("left_context")
        right_context = operation.metadata.get("right_context")
        if not isinstance(offset, int) or not 0 <= offset <= len(text):
            raise CandidateApplicationError("delimiter_offset_out_of_range")
        if delimiter not in {",", ";"}:
            raise CandidateApplicationError("delimiter_value_invalid")
        if isinstance(left_context, str) and text[max(0, offset - len(left_context)):offset] != left_context:
            raise CandidateApplicationError("delimiter_left_context_mismatch")
        if isinstance(right_context, str) and text[offset:offset + len(right_context)] != right_context:
            raise CandidateApplicationError("delimiter_right_context_mismatch")
        if offset < len(text) and text[offset] == delimiter:
            raise CandidateApplicationError("delimiter_already_present")
        return text[:offset] + delimiter + text[offset:]
    document = parse_idf(text)
    if operation.kind is OperationKind.INSERT_OBJECT:
        if not operation.object_text:
            raise CandidateApplicationError("inserted_object_text_missing")
        separator = "" if text.endswith(("\n", "\r")) else "\n"
        return text + separator + operation.object_text
    obj = _resolve_object(document, operation)
    if operation.kind in {OperationKind.REPLACE_FIELD, OperationKind.RENAME_REFERENCE, OperationKind.UPDATE_VERSION}:
        return _replace_field(text, obj, operation)
    if operation.kind is OperationKind.DELETE_FIELD:
        return _delete_field(text, obj, operation)
    if operation.kind is OperationKind.INSERT_FIELD:
        return _insert_field(text, obj, operation)
    if operation.kind is OperationKind.DELETE_OBJECT:
        return text[:obj.start] + text[obj.end:]
    if operation.kind in {OperationKind.REPLACE_OBJECT, OperationKind.REPLACE_VERTICES}:
        return _replace_object(text, obj, operation)
    raise CandidateApplicationError(f"unsupported_operation:{operation.kind.value}")


def apply_operations(text: str, operations: Sequence[RepairOperation]) -> str:
    """Apply finite operations from the end of the file to keep indexes stable."""
    if not operations:
        raise CandidateApplicationError("candidate_has_no_operations")
    original = parse_idf(text)
    resolved: list[tuple[int, RepairOperation]] = []
    for operation in operations:
        if operation.kind is OperationKind.INSERT_OBJECT:
            resolved.append((len(text) + 1, operation))
        elif operation.kind is OperationKind.INSERT_DELIMITER:
            offset = operation.metadata.get("offset")
            if not isinstance(offset, int):
                raise CandidateApplicationError("delimiter_offset_missing")
            resolved.append((offset, operation))
        else:
            resolved.append((_resolve_object(original, operation).start, operation))
    working = text
    for _, operation in sorted(resolved, key=lambda item: item[0], reverse=True):
        working = apply_operation(working, operation)
    return working


def changed_fields(before: str, after: str) -> tuple[tuple[int, int, str, str], ...]:
    """Return structured field changes when the object layout is preserved."""
    left = parse_idf(before)
    right = parse_idf(after)
    if len(left.objects) != len(right.objects):
        return ()
    changes: list[tuple[int, int, str, str]] = []
    for old_obj, new_obj in zip(left.objects, right.objects):
        if canonical(old_obj.object_type) != canonical(new_obj.object_type):
            return ()
        if len(old_obj.fields) != len(new_obj.fields):
            return ()
        for old_field, new_field in zip(old_obj.fields, new_obj.fields):
            if old_field.value != new_field.value:
                changes.append((old_obj.index, old_field.index, old_field.value, new_field.value))
    return tuple(changes)
