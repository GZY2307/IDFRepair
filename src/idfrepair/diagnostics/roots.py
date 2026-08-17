"""Deterministic clustering of diagnostics into actionable roots."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import re
from typing import Iterable

from idfrepair.diagnostics.err_parser import Diagnostic, parse_err
from idfrepair.diagnostics.normalization import normalize_message
from idfrepair.domain.models import DiagnosticRoot
from idfrepair.io.idf import IDFDocument, canonical
from idfrepair.knowledge.idd import IDDSchema


_QUOTED = re.compile(r'["\']([^"\']+)["\']')
_OBJECT_EQUALS = re.compile(r"(?:object|type)\s*=\s*([^,;]+)", re.I)
_NAME_EQUALS = re.compile(r"(?:name|key)\s*=\s*([^,;]+)", re.I)
_LINE = re.compile(r"\bLine\s*:\s*(\d+)", re.I)
_JSON_PATH = re.compile(
    r"\[(?P<object_type>[^\]]+)\]"
    r"\[(?P<object_name>[^\]]+)\]"
    r"\[(?P<field_token>[^\]]+)\]"
)
_OUTPUT_REQUEST = re.compile(
    r"Key=(?P<key>.*?),\s*VarName=(?P<variable>.*?),\s*Frequency=(?P<frequency>[^\r\n]+)",
    re.I,
)


def classify_family(message: str) -> str:
    value = normalize_message(message)
    if any(token in value for token in (
        "more field values than maximum", "too many fields", "invalid number of fields",
    )):
        return "extra_field"
    if any(token in value for token in (
        "missing semicolon", "missing comma", "did not find terminator",
        "unexpected end-of-file", "error parsing",
    )):
        return "syntax"
    if "schedule" in value and any(token in value for token in (
        "not found", "invalid", "does not exist", "missing",
    )):
        return "reference_schedule"
    if (
        "invalid design object name" in value
        and "not found" in value
    ):
        return "hvac_reference"
    if any(token in value for token in (
        "output:variable", "variable name", "varname", "report variables were requested",
    )) and any(token in value for token in ("invalid", "not generated", "not found")):
        return "output_variable"
    if any(token in value for token in (
        "self-intersection", "self intersection", "intersecting edges",
        "degenerate polygon", "non-planar", "non planar",
    )):
        return "geometry"
    if "version" in value and any(token in value for token in (
        "mismatch", "transition", "older", "newer", "not match",
    )):
        return "version_migration"
    if any(token in value for token in (
        "external file", "file not found", "cannot open file", "missing file",
    )):
        return "external_dependency"
    if "energy management system" in value or "ems" in value:
        return "ems"
    if any(token in value for token in ("node not found", "branch", "airloop", "plantloop")):
        return "hvac_reference"
    if any(token in value for token in (
        "not a valid object type", "invalid field", "required field", "out of range",
        "invalid key", "illegal value", "failed to match against any enum values",
        "json.exception.out_of_range",
    )):
        return "schema"
    return "unknown"


def _identity(message: str) -> tuple[str | None, str | None]:
    json_path = _JSON_PATH.search(message)
    if json_path is not None:
        return (
            json_path.group("object_type").strip(),
            json_path.group("object_name").strip(),
        )
    object_match = _OBJECT_EQUALS.search(message)
    name_match = _NAME_EQUALS.search(message)
    object_type = object_match.group(1).strip() if object_match else None
    object_name = name_match.group(1).strip() if name_match else None
    if object_name is None:
        quoted = _QUOTED.findall(message)
        object_name = quoted[0].strip() if quoted else None
    return object_type, object_name


def build_roots(source: str | Iterable[Diagnostic]) -> tuple[DiagnosticRoot, ...]:
    diagnostics = parse_err(source) if isinstance(source, str) else tuple(source)
    grouped: dict[tuple[str, str, str], list[Diagnostic]] = defaultdict(list)
    identity: dict[tuple[str, str, str], tuple[str | None, str | None]] = {}
    line_numbers: dict[tuple[str, str, str], int | None] = {}
    for row in diagnostics:
        combined = " ".join((row.message, *row.continuation))
        family = classify_family(combined)
        if row.severity not in {"Severe", "Fatal"} and family != "output_variable":
            continue
        object_type, object_name = _identity(combined)
        line_match = _LINE.search(combined)
        line_number = int(line_match.group(1)) if line_match else None
        fallback = f"line:{line_number}" if line_number is not None else row.signature
        key = (
            family,
            (object_type or "").casefold(),
            (object_name or fallback).casefold(),
        )
        grouped[key].append(row)
        identity[key] = object_type, object_name
        line_numbers[key] = line_number
    roots: list[DiagnosticRoot] = []
    for key, rows in grouped.items():
        family = key[0]
        object_type, object_name = identity[key]
        signatures = tuple(sorted({row.signature for row in rows}))
        payload = "|".join((family, key[1], key[2], *signatures))
        roots.append(DiagnosticRoot(
            root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
            family=family,
            message=rows[0].message,
            severity=(
                "Fatal" if any(row.severity == "Fatal" for row in rows)
                else "Severe" if any(row.severity == "Severe" for row in rows)
                else "Warning"
            ),
            object_type=object_type,
            object_name=object_name,
            signatures=signatures,
            metadata={
                "diagnostic_count": len(rows),
                "line_number": line_numbers[key],
            },
        ))
    extra_lines = {
        root.metadata.get("line_number")
        for root in roots
        if root.family == "extra_field" and root.metadata.get("line_number") is not None
    }
    filtered = []
    for root in roots:
        line_number = root.metadata.get("line_number")
        normalized = normalize_message(root.message)
        if normalized.startswith("errors occurred on processing input file"):
            continue
        if normalized.startswith("~~~"):
            continue
        if root.family == "syntax" and line_number in extra_lines and "error parsing" in normalized:
            continue
        if (
            root.family == "schema"
            and "not a valid object type" in normalized
            and isinstance(line_number, int)
            and line_number - 1 in extra_lines
        ):
            continue
        filtered.append(root)
    roots = filtered
    priority = {
        "syntax": 0,
        "extra_field": 1,
        "version_migration": 2,
        "reference_schedule": 3,
        "output_variable": 4,
        "geometry": 5,
        "schema": 6,
        "hvac_reference": 7,
        "ems": 8,
        "external_dependency": 9,
        "unknown": 10,
    }
    roots.sort(key=lambda root: (priority.get(root.family, 99), root.root_id))
    return tuple(roots)


def bind_roots_to_document(
    roots: tuple[DiagnosticRoot, ...],
    *,
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
) -> tuple[DiagnosticRoot, ...]:
    """Bind parser cascades to exact current-IDD normalization sites."""

    from idfrepair.diagnostics.structural import detect_syntax_sites

    bound: list[DiagnosticRoot] = []
    for root in roots:
        line_number = root.metadata.get("line_number")
        normalized = normalize_message(root.message)
        if (
            root.family == "syntax"
            and isinstance(line_number, int)
            and "error parsing" in normalized
        ):
            matches = []
            for obj in document.objects:
                definition = idd.get(obj.object_type)
                if definition is None or definition.maximum_fields is None:
                    continue
                first_line = document.text.count("\n", 0, obj.start) + 1
                last_line = document.text.count("\n", 0, obj.end) + 1
                if (
                    first_line <= line_number <= last_line
                    and len(obj.fields) == definition.maximum_fields + 1
                    and obj.fields[-1].value.strip()
                ):
                    matches.append(obj)
            if len(matches) == 1:
                obj = matches[0]
                payload = "|".join((
                    "extra_field",
                    canonical(obj.object_type),
                    canonical(obj.name),
                    str(obj.index),
                    document.sha256,
                ))
                bound.append(DiagnosticRoot(
                    root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
                    family="extra_field",
                    message=root.message,
                    severity=root.severity,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    signatures=root.signatures,
                    metadata={
                        **root.metadata,
                        "object_index": obj.index,
                        "normalization_evidence": "current_idd_single_tail_overflow",
                    },
                ))
                continue
        bound.append(root)
    roots = tuple(bound)

    sites = detect_syntax_sites(document, idd, diagnostics_text, include_eof=False)
    if len(sites) != 1:
        return roots
    site = sites[0]
    payload = "|".join((
        "syntax",
        site.kind,
        site.object_type.casefold(),
        str(site.offset),
        document.sha256,
    ))
    structural_root = DiagnosticRoot(
        root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
        family="syntax",
        message=(
            f"Unique {site.kind} at line {site.line_number} "
            f"before {site.next_object_type or site.object_type}."
        ),
        object_type=site.object_type or None,
        object_name=None,
        signatures=tuple(sorted({signature for root in roots for signature in root.signatures})),
        metadata={
            "structural_kind": site.kind,
            "delimiter": site.delimiter,
            "offset": site.offset,
            "line_number": site.line_number,
            "object_index": site.object_index,
            "next_object_type": site.next_object_type,
            "fault_side_evidence": site.evidence,
        },
    )
    remaining = tuple(root for root in roots if root.root_id != structural_root.root_id)
    return (structural_root, *remaining)


def bind_output_roots_to_document(
    roots: tuple[DiagnosticRoot, ...],
    *,
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
    rdd,  # type: ignore[no-untyped-def]
) -> tuple[DiagnosticRoot, ...]:
    """Replace an output umbrella warning with actionable value-level roots."""

    output_roots = [root for root in roots if root.family == "output_variable"]
    if not output_roots:
        return roots
    from idfrepair.knowledge.rdd import unique_variable_match

    rows = []
    for match in _OUTPUT_REQUEST.finditer(diagnostics_text):
        variable = match.group("variable").strip()
        targets = []
        for obj in document.objects:
            if not canonical(obj.object_type).startswith("output:"):
                continue
            definition = idd.get(obj.object_type)
            if definition is None:
                continue
            for field in obj.fields:
                field_def = definition.field_at(field.index)
                if (
                    field_def is not None
                    and field_def.role == "output_variable"
                    and canonical(field.value) == canonical(variable)
                ):
                    targets.append((obj, field, field_def))
        selected = unique_variable_match(variable, rdd.variable_names) if getattr(rdd, "variable_names", ()) else None
        if len(targets) == 1 and selected is not None:
            rows.append((match, targets[0], selected))
    unique = {
        (target[0].index, target[1].index, canonical(match.group("variable"))): (match, target, selected)
        for match, target, selected in rows
    }
    remaining = tuple(root for root in roots if root.family != "output_variable")
    if len(unique) != 1:
        if not getattr(rdd, "variable_names", ()):
            return roots
        if len(unique) > 1:
            payload = "|".join(sorted(f"{key[0]}:{key[1]}:{key[2]}" for key in unique))
            ambiguous = DiagnosticRoot(
                root_id=sha256(f"output-ambiguous|{payload}".encode("utf-8")).hexdigest()[:20],
                family="output_variable",
                message="Multiple output-variable typo targets remain equally actionable.",
                metadata={
                    "ambiguous_output_target_count": len(unique),
                    "automatic_policy": "forbidden",
                },
            )
            return (*remaining, ambiguous)
        # A generic warning with no bounded RDD match is non-actionable and
        # must not block an otherwise successful EnergyPlus run.
        return remaining
    match, (obj, field, field_def), selected = next(iter(unique.values()))
    variable = match.group("variable").strip()
    payload = "|".join((
        "output_variable",
        str(obj.index),
        str(field.index),
        canonical(variable),
        canonical(selected[0]),
    ))
    root = DiagnosticRoot(
        root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
        family="output_variable",
        message=match.group(0).strip(),
        object_type=obj.object_type,
        object_name=variable,
        field_name=field_def.name,
        signatures=tuple(sorted({signature for row in output_roots for signature in row.signatures})),
        metadata={
            "object_index": obj.index,
            "field_index": field.index,
            "key_value": match.group("key").strip(),
            "variable_name": variable,
            "frequency": match.group("frequency").strip().strip("* "),
            "bounded_rdd_match": selected[0],
            "edit_distance": selected[1],
        },
    )
    return (*remaining, root)


__all__ = [
    "bind_output_roots_to_document",
    "bind_roots_to_document",
    "build_roots",
    "classify_family",
]
