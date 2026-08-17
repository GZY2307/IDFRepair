"""User-supplied candidates that still pass every engine validator."""

from __future__ import annotations

from idfrepair.candidates.base import CandidateProvider
from idfrepair.candidates.schedules import _cross_role
from idfrepair.domain.enums import OperationKind
from idfrepair.io.idf import canonical, parse_idf


class UserCandidateProvider(CandidateProvider):
    """Semantic gate for finite operations compiled from user answers."""

    name = "user_input"
    families = frozenset({
        "ems",
        "external_dependency",
        "extra_field",
        "geometry",
        "hvac_reference",
        "output_variable",
        "reference",
        "reference_schedule",
        "schema",
        "syntax",
        "unknown",
        "version_migration",
    })

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        return ()

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        document = parse_idf(after)
        reasons: list[str] = []
        details: dict[str, object] = {"validated_as_user_input": True}
        for operation in candidate.operations:
            if operation.kind is OperationKind.INSERT_OBJECT:
                continue
            if operation.object_index is None or not 0 <= operation.object_index < len(document.objects):
                reasons.append("user_target_object_missing_after_patch")
                continue
            obj = document.objects[operation.object_index]
            definition = context.idd.get(obj.object_type)
            if definition is None:
                reasons.append("user_target_not_in_bound_idd")
                continue
            if operation.kind in {
                OperationKind.REPLACE_FIELD,
                OperationKind.RENAME_REFERENCE,
                OperationKind.UPDATE_VERSION,
            }:
                if operation.field_index is None or not 1 <= operation.field_index <= len(obj.fields):
                    reasons.append("user_target_field_missing_after_patch")
                    continue
                field = obj.fields[operation.field_index - 1]
                field_definition = definition.field_at(operation.field_index)
                if field_definition and field_definition.keys and not any(
                    canonical(field.value) == canonical(key) for key in field_definition.keys
                ):
                    reasons.append("user_value_not_in_idd_keys")
                if field_definition and field_definition.role == "schedule_reference":
                    role = " ".join((obj.object_type, obj.name, field_definition.name, operation.old_value or ""))
                    if _cross_role(role, field.value):
                        reasons.append("schedule_cross_role_copy_forbidden")
                if field_definition and field_definition.role == "output_variable":
                    if context.rdd.variable_names and not context.rdd.contains(field.value):
                        reasons.append("user_output_value_not_in_bound_rdd")
        return not reasons, tuple(reasons), details
