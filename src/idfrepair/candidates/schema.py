"""IDD-aligned arity, required-field, enum, and numeric candidates."""

from __future__ import annotations

import difflib
import math
import re
from typing import Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, DiagnosticRoot, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical, changed_fields, parse_idf


def _field_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", canonical(value)).strip("_")


def _semantic_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", canonical(value)))


class SchemaProvider(CandidateProvider):
    name = "idd_schema"
    families = frozenset({"extra_field", "schema"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        if root.family == "extra_field":
            return self._extra_fields(root, context)
        defaults = self._idd_defaults(root, context)
        if defaults:
            return defaults
        return self._schema_values(root, context)

    def _idd_defaults(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        diagnostic = context.diagnostics_text
        if "json.exception.out_of_range" not in diagnostic.casefold():
            return ()
        keys = {
            _field_token(match.group(1))
            for match in re.finditer(
                r"\bkey\s+['\"]([^'\"]+)['\"]\s+not\s+found",
                diagnostic,
                re.I,
            )
        }
        if len(keys) != 1:
            return ()
        diagnostic_key = next(iter(keys))
        operations: list[RepairOperation] = []
        fields = []
        definitions = set()
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            for field in obj.fields:
                field_def = definition.field_at(field.index)
                if (
                    field_def is None
                    or field.value.strip()
                    or field_def.default is None
                    or _field_token(field_def.name) != diagnostic_key
                ):
                    continue
                operations.append(RepairOperation(
                    kind=OperationKind.REPLACE_FIELD,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    object_index=obj.index,
                    field_index=field.index,
                    field_name=field_def.name,
                    old_value=field.value,
                    new_value=field_def.default,
                ))
                fields.append({
                    "object_type": obj.object_type,
                    "object_index": obj.index,
                    "field_index": field.index,
                    "field_name": field_def.name,
                    "default": field_def.default,
                })
                definitions.add((
                    canonical(obj.object_type),
                    field_def.index,
                    canonical(field_def.name),
                    field_def.default,
                ))
        if not operations or len(definitions) != 1:
            return ()
        return (self._candidate(
            root,
            context,
            tuple(operations),
            confidence=0.99,
            evidence=(CandidateEvidence(
                kind="idd_declared_default",
                source="current_version_Energy+.idd",
                strength=1.0,
                details={
                    "diagnostic_key": diagnostic_key,
                    "target_count": len(operations),
                },
            ),),
            family="schema",
            metadata={
                "schema_mechanism": "idd_default",
                "diagnostic_key": diagnostic_key,
                "targets": tuple(fields),
            },
        ),)

    def _extra_fields(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        result = []
        root_line = root.metadata.get("line_number")
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None or definition.maximum_fields is None:
                continue
            overflow = len(obj.fields) - definition.maximum_fields
            if overflow != 1:
                continue
            if isinstance(root_line, int):
                first_line = context.document.text.count("\n", 0, obj.start) + 1
                last_line = context.document.text.count("\n", 0, obj.end) + 1
                if not first_line <= root_line <= last_line:
                    continue
            field = obj.fields[-1]
            if not field.value.strip():
                continue
            if root.object_type and canonical(root.object_type) not in {
                canonical(obj.object_type), canonical(field.value),
            }:
                continue
            operation = RepairOperation(
                kind=OperationKind.DELETE_FIELD,
                object_type=obj.object_type,
                object_name=obj.name or None,
                object_index=obj.index,
                field_index=field.index,
                old_value=field.value,
            )
            result.append(self._candidate(
                root,
                context,
                (operation,),
                confidence=0.99,
                evidence=(CandidateEvidence(
                    kind="idd_fixed_field_boundary",
                    source="current_version_Energy+.idd",
                    strength=1.0,
                    details={
                        "actual_fields": len(obj.fields),
                        "maximum_fields": definition.maximum_fields,
                        "extensible_group_size": definition.extensible,
                        "overflow_count": overflow,
                        "tail_field_nonempty": True,
                    },
                ),),
                family="extra_field",
                metadata={"schema_mechanism": "extra_field"},
            ))
        return tuple(result) if len(result) == 1 else ()

    def _schema_values(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        exact = re.search(
            r"\[(?P<object_type>[^\]]+)\]"
            r"\[(?P<object_name>[^\]]+)\]"
            r"\[(?P<field_token>[^\]]+)\]\s*-\s*"
            r"['\"](?P<value>[^'\"]+)['\"]\s*-\s*"
            r"Failed\s+to\s+match\s+against\s+any\s+enum\s+values",
            context.diagnostics_text,
            re.I,
        )
        if exact is not None:
            return self._exact_enum(root, context, exact)
        rows = []
        diagnostic_key = canonical(context.diagnostics_text)
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            for field in obj.fields:
                field_def = definition.field_at(field.index)
                if field_def is None or not field_def.keys or not field.value.strip():
                    continue
                if any(canonical(field.value) == canonical(key) for key in field_def.keys):
                    continue
                if canonical(field.value) not in diagnostic_key:
                    continue
                matches = _unique_typo(field.value, field_def.keys)
                if matches is None:
                    continue
                operation = RepairOperation(
                    kind=OperationKind.REPLACE_FIELD,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    object_index=obj.index,
                    field_index=field.index,
                    field_name=field_def.name,
                    old_value=field.value,
                    new_value=matches,
                )
                rows.append(self._candidate(
                    root,
                    context,
                    (operation,),
                    confidence=0.94,
                    evidence=(CandidateEvidence(
                        kind="idd_enum",
                        source="Energy+.idd",
                        strength=0.95,
                        details={"keys": field_def.keys},
                    ),),
                    family="schema",
                    metadata={"schema_mechanism": "enum_typo"},
                ))
        return tuple(rows)

    def _exact_enum(
        self,
        root: DiagnosticRoot,
        context: CandidateContext,
        match: re.Match[str],
    ) -> Sequence[RepairCandidate]:
        objects = context.document.find_objects(
            match.group("object_type"), match.group("object_name"),
        )
        if len(objects) != 1:
            return ()
        obj = objects[0]
        definition = context.idd.get(obj.object_type)
        if definition is None:
            return ()
        field_token = canonical(match.group("field_token").replace("_", " "))
        definitions = [
            field for field in definition.fields
            if canonical(field.name) == field_token and field.keys
        ]
        if len(definitions) != 1:
            return ()
        field_def = definitions[0]
        if field_def.index > len(obj.fields):
            return ()
        field = obj.fields[field_def.index - 1]
        faulty = match.group("value")
        if canonical(field.value) != canonical(faulty):
            return ()
        ranked = sorted(
            (
                difflib.SequenceMatcher(
                    None, canonical(faulty), canonical(key),
                ).ratio(),
                canonical(key),
                key,
            )
            for key in field_def.keys
        )
        ranked.reverse()
        if not ranked:
            return ()
        best = ranked[0]
        if len(ranked) > 1 and best[0] <= ranked[1][0]:
            return ()
        adjacent = (
            obj.fields[field_def.index].value.strip()
            if field_def.index < len(obj.fields)
            else ""
        )
        adjacent_def = definition.field_at(field_def.index + 1)
        try:
            adjacent_number = float(adjacent)
        except ValueError:
            adjacent_number = 0.0
        adjacent_parameter_valid = (
            math.isfinite(adjacent_number) and adjacent_number != 0.0
        )
        faulty_words = _semantic_words(faulty)
        enum_context_words = _semantic_words(field_def.name) - {
            "method", "mode", "type", "value",
        }
        adjacent_words = (
            _semantic_words(adjacent_def.name)
            if adjacent_def is not None else set()
        )
        adjacent_parameter_semantic = bool(
            adjacent_def is not None
            and (
                adjacent_def.token.casefold().startswith("n")
                or canonical(adjacent_def.data_type or "")
                in {"integer", "real"}
            )
            and faulty_words.intersection(adjacent_words)
            and enum_context_words.intersection(adjacent_words)
        )
        prefix_rename = (
            canonical(best[2]).startswith(canonical(faulty))
            and canonical(best[2]) != canonical(faulty)
        )
        prefix_matches = {
            canonical(key)
            for key in field_def.keys
            if canonical(key).startswith(canonical(faulty))
            and canonical(key) != canonical(faulty)
        }
        safe_prefix_rename = (
            prefix_rename
            and len(prefix_matches) == 1
            and adjacent_parameter_valid
            and adjacent_parameter_semantic
        )
        typo_rename = bool(
            not prefix_rename
            and _distance(canonical(faulty), canonical(best[2])) <= 2
        )
        if not (typo_rename or safe_prefix_rename):
            return ()
        operation = RepairOperation(
            kind=OperationKind.REPLACE_FIELD,
            object_type=obj.object_type,
            object_name=obj.name or None,
            object_index=obj.index,
            field_index=field.index,
            field_name=field_def.name,
            old_value=field.value,
            new_value=best[2],
        )
        return (self._candidate(
            root,
            context,
            (operation,),
            confidence=0.99,
            evidence=(
                CandidateEvidence(
                    kind="idd_enum",
                    source="current_version_Energy+.idd",
                    strength=1.0,
                    details={
                        "keys": field_def.keys,
                        "unique_similarity": best[0],
                    },
                ),
                CandidateEvidence(
                    kind="enum_adjacent_parameter",
                    source="faulty_idf",
                    strength=0.98,
                    details={
                        "adjacent_parameter_valid": adjacent_parameter_valid,
                        "adjacent_parameter_semantic": (
                            adjacent_parameter_semantic
                        ),
                        "prefix_rename": prefix_rename,
                        "typo_rename": typo_rename,
                        "unique_prefix_rename": safe_prefix_rename,
                    },
                ),
            ),
            family="schema",
            metadata={
                "schema_mechanism": "enum_exact_path",
                "diagnostic_field_token": match.group("field_token"),
                "adjacent_parameter_valid": adjacent_parameter_valid,
                "adjacent_parameter_semantic": adjacent_parameter_semantic,
                "prefix_rename": prefix_rename,
                "typo_rename": typo_rename,
                "unique_prefix_rename": safe_prefix_rename,
            },
        ),)

    def _candidate(
        self,
        root: DiagnosticRoot,
        context: CandidateContext,
        operations: tuple[RepairOperation, ...],
        *,
        confidence: float,
        evidence: tuple[CandidateEvidence, ...],
        family: str,
        metadata: dict[str, object] | None = None,
    ) -> RepairCandidate:
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=operations,
        )
        return RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family=family,
            operations=operations,
            evidence=evidence,
            risk=RiskLevel.LOW,
            confidence=confidence,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            metadata=metadata or {},
        )

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        mechanism = candidate.metadata.get("schema_mechanism")
        if mechanism in {"idd_default", "enum_exact_path", "enum_typo"}:
            changes = changed_fields(before, after)
            expected = tuple(
                (
                    operation.object_index,
                    operation.field_index,
                    operation.old_value,
                    operation.new_value,
                )
                for operation in candidate.operations
            )
            reasons = []
            if changes != expected:
                reasons.append("schema_patch_scope_changed")
            document = parse_idf(after)
            for operation in candidate.operations:
                if (
                    operation.object_index is None
                    or operation.field_index is None
                    or not 0 <= operation.object_index < len(document.objects)
                ):
                    reasons.append("schema_target_missing_after_patch")
                    continue
                obj = document.objects[operation.object_index]
                definition = context.idd.get(obj.object_type)
                field_def = (
                    definition.field_at(operation.field_index)
                    if definition is not None else None
                )
                if field_def is None:
                    reasons.append("schema_target_missing_from_current_idd")
                    continue
                actual = obj.fields[operation.field_index - 1].value
                if actual != operation.new_value:
                    reasons.append("schema_target_value_mismatch")
                if mechanism == "idd_default" and actual != field_def.default:
                    reasons.append("schema_default_identity_mismatch")
                if mechanism != "idd_default" and not any(
                    canonical(actual) == canonical(key) for key in field_def.keys
                ):
                    reasons.append("schema_enum_not_legal_in_current_idd")
            return not reasons, tuple(reasons), {
                "changes": changes,
                "mechanism": mechanism,
                "operation_count": len(candidate.operations),
            }

        old_document = parse_idf(before)
        document = parse_idf(after)
        reasons = []
        for operation in candidate.operations:
            if operation.object_index is None or not 0 <= operation.object_index < len(document.objects):
                reasons.append("target_object_missing_after_patch")
                continue
            obj = document.objects[operation.object_index]
            if operation.object_index >= len(old_document.objects):
                reasons.append("target_object_missing_before_patch")
                continue
            old_obj = old_document.objects[operation.object_index]
            if len(document.objects) != len(old_document.objects):
                reasons.append("extra_field_patch_changed_object_count")
            if canonical(old_obj.object_type) != canonical(obj.object_type):
                reasons.append("extra_field_patch_changed_object_type")
            if len(old_obj.fields) != len(obj.fields) + 1:
                reasons.append("extra_field_patch_did_not_delete_one_tail_field")
            elif tuple(field.value for field in obj.fields) != tuple(field.value for field in old_obj.fields[:-1]):
                reasons.append("extra_field_patch_changed_retained_fields")
            if operation.field_index != len(old_obj.fields) or operation.old_value != old_obj.fields[-1].value:
                reasons.append("extra_field_patch_not_bound_to_exact_tail")
            if any(
                left.raw != right.raw
                for left, right in zip(old_document.objects, document.objects)
                if left.index != operation.object_index
            ):
                reasons.append("extra_field_patch_changed_other_object")
            definition = context.idd.get(obj.object_type)
            if definition is None:
                reasons.append("target_missing_from_current_idd")
            elif definition.maximum_fields is not None:
                if len(obj.fields) != definition.maximum_fields:
                    reasons.append("target_not_restored_to_current_idd_fixed_boundary")
            else:
                reasons.append("fixed_tail_delete_used_on_extensible_object")
        return not reasons, tuple(reasons), {
            "before_object_count": len(old_document.objects),
            "after_object_count": len(document.objects),
            "operation_count": len(candidate.operations),
        }


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        for column, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + int(left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _unique_typo(value: str, choices: Sequence[str]) -> str | None:
    source = canonical(value)
    scored = sorted((_distance(source, canonical(choice)), canonical(choice), choice) for choice in choices)
    if not scored or scored[0][0] > 2:
        return None
    best = [row for row in scored if row[0] == scored[0][0]]
    return best[0][2] if len(best) == 1 else None
