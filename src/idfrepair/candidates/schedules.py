"""Role-aware Schedule reference recovery from local peer consensus."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Mapping

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.candidates.finite_keys import _project_case
from idfrepair.diagnostics.semantic_preflight import bounded_unique_choice
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import IDFObject, canonical, changed_fields, parse_idf


_TOKENS = re.compile(r"[a-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_GENERIC_NAME_TOKENS = {
    "a", "b", "candidate", "idfrepair", "peer", "schedule", "target",
}
_OPPOSED = (
    frozenset({"heating", "cooling"}),
    frozenset({"heat", "cool"}),
    frozenset({"humidify", "dehumidify"}),
)


def _tokens(value: str) -> set[str]:
    expanded = _CAMEL_BOUNDARY.sub(" ", value)
    tokens = set(_TOKENS.findall(expanded.casefold()))
    lowered = value.casefold()
    for role in {"heating", "cooling", "heat", "cool", "humidify", "dehumidify"}:
        if role in lowered:
            tokens.add(role)
    return tokens


def _cross_role(source: str, proposed: str) -> bool:
    left = _tokens(source)
    right = _tokens(proposed)
    for pair in _OPPOSED:
        left_side = left & pair
        right_side = right & pair
        if len(left_side) == len(right_side) == 1 and left_side != right_side:
            return True
    return False


@dataclass(frozen=True, slots=True)
class ScheduleRecord:
    key: str
    name: str
    object_index: int
    object_type: str
    type_limits_name: str
    profile_fingerprint: tuple[str, ...]
    reference_lists: tuple[str, ...]


def _schedule_inventory(context: CandidateContext) -> Mapping[str, ScheduleRecord]:
    grouped: dict[str, list[ScheduleRecord]] = {}
    for obj in context.document.objects:
        object_key = canonical(obj.object_type)
        if not object_key.startswith("schedule:") or object_key in {
            "schedule:typelimits",
        } or not obj.name:
            continue
        definition = context.idd.get(obj.object_type)
        name_definition = definition.field_at(1) if definition else None
        references = tuple(sorted(canonical(value) for value in (name_definition.references if name_definition else ())))
        # Direct schedules normally expose ScheduleNames on their name field.
        # Retain historical versions without that directive, but never retain
        # ScheduleTypeLimits itself.
        type_limits = obj.fields[1].value.strip() if len(obj.fields) >= 2 else ""
        profile = tuple(canonical(field.value) for field in obj.fields[1:])
        record = ScheduleRecord(
            key=canonical(obj.name),
            name=obj.name,
            object_index=obj.index,
            object_type=obj.object_type,
            type_limits_name=type_limits,
            profile_fingerprint=profile,
            reference_lists=references,
        )
        grouped.setdefault(record.key, []).append(record)
    return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}


def _informative_name_tokens(value: str) -> set[str]:
    return {
        token for token in _tokens(value)
        if token not in _GENERIC_NAME_TOKENS and len(token) > 1
    }


def _similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


@dataclass(frozen=True, slots=True)
class PeerConsensus:
    proposed_key: str
    peer_names: tuple[str, ...]
    peer_count: int
    closest_similarity: float
    competing_reference_count: int


def _peer_consensus(
    *,
    target: IDFObject,
    field_index: int,
    document_objects: tuple[IDFObject, ...],
    inventory: Mapping[str, ScheduleRecord],
) -> PeerConsensus | None:
    owner_tokens = _informative_name_tokens(target.name)
    peers: list[tuple[float, str, str]] = []
    for peer in document_objects:
        if (
            peer.index == target.index
            or canonical(peer.object_type) != canonical(target.object_type)
            or field_index > len(peer.fields)
        ):
            continue
        reference = canonical(peer.fields[field_index - 1].value)
        if reference not in inventory:
            continue
        score = _similarity(owner_tokens, _informative_name_tokens(peer.name))
        peers.append((score, reference, peer.name))
    if not peers:
        return None
    maximum = max(row[0] for row in peers)
    if owner_tokens and maximum < 0.5:
        return None
    selected = [row for row in peers if abs(row[0] - maximum) <= 1e-12]
    counts = Counter(row[1] for row in selected)
    if not counts:
        return None
    maximum_count = max(counts.values())
    winners = [key for key, count in counts.items() if count == maximum_count]
    if len(winners) != 1 or maximum_count < 2:
        return None
    proposed = winners[0]
    competing = sum(count for key, count in counts.items() if key != proposed)
    if competing:
        return None
    names = tuple(sorted(row[2] for row in selected if row[1] == proposed))
    return PeerConsensus(
        proposed_key=proposed,
        peer_names=names,
        peer_count=maximum_count,
        closest_similarity=maximum,
        competing_reference_count=competing,
    )


def _targets(context: CandidateContext, inventory: Mapping[str, ScheduleRecord]):  # type: ignore[no-untyped-def]
    diagnostics = canonical(context.diagnostics_text)
    rows = []
    for obj in context.document.objects:
        definition = context.idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or field_def.role != "schedule_reference" or not field.value.strip():
                continue
            if "schedulenames" not in {canonical(value).replace(" ", "") for value in field_def.object_lists}:
                continue
            key = canonical(field.value)
            if key in inventory or key not in diagnostics:
                continue
            rows.append((obj, field, field_def))
    return tuple(rows)


class ScheduleProvider(CandidateProvider):
    name = "schedule_reference"
    families = frozenset({"reference_schedule"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        inventory = _schedule_inventory(context)
        if root.metadata.get("semantic_issue") is True:
            if root.metadata.get("recoverability") != "RECOVERABLE":
                return ()
            object_index = root.metadata.get("object_index")
            field_index = root.metadata.get("field_index")
            if not isinstance(object_index, int) or not isinstance(field_index, int):
                return ()
            if not 0 <= object_index < len(context.document.objects):
                return ()
            obj = context.document.objects[object_index]
            definition = context.idd.get(obj.object_type)
            field_def = definition.field_at(field_index) if definition else None
            if (
                field_def is None
                or field_def.role != "schedule_reference"
                or field_index > len(obj.fields)
            ):
                return ()
            field = obj.fields[field_index - 1]
            choices = tuple(row.name for row in inventory.values())
            selected_typo = bounded_unique_choice(field.value, choices)
            if (
                selected_typo is None
                or selected_typo[0] != root.metadata.get("bounded_candidate")
            ):
                return ()
            selected = inventory.get(canonical(selected_typo[0]))
            if selected is None:
                return ()
            role_context = " ".join((
                obj.object_type,
                obj.name,
                field_def.name,
                field.value,
            ))
            if _cross_role(role_context, selected.name):
                return ()
            operation = RepairOperation(
                kind=OperationKind.RENAME_REFERENCE,
                object_type=obj.object_type,
                object_name=obj.name or None,
                object_index=obj.index,
                field_index=field.index,
                field_name=field_def.name,
                old_value=field.value,
                new_value=_project_case(field.value, selected.name),
                metadata={
                    "schedule_profile_fingerprint": selected.profile_fingerprint,
                    "schedule_type_limits_name": selected.type_limits_name,
                    "semantic_issue_id": root.root_id,
                },
            )
            identity = candidate_identity(
                provider=self.name,
                root_id=root.root_id,
                input_sha256=context.input_sha256,
                operations=(operation,),
            )
            return (RepairCandidate(
                candidate_id=identity,
                provider=self.name,
                root_id=root.root_id,
                family="reference_schedule",
                operations=(operation,),
                evidence=(
                    CandidateEvidence(
                        kind="idd_schedule_role_binding",
                        source="current_version_Energy+.idd",
                        strength=1.0,
                        details={
                            "field_name": field_def.name,
                            "object_lists": field_def.object_lists,
                        },
                    ),
                    CandidateEvidence(
                        kind="unique_bounded_typo",
                        source="whole_file_semantic_preflight",
                        strength=1.0,
                        details={"edit_distance": selected_typo[1]},
                    ),
                    CandidateEvidence(
                        kind="schedule_type_limit_compatibility",
                        source="existing_schedule_object",
                        strength=1.0,
                        details={
                            "schedule_object_type": selected.object_type,
                            "schedule_type_limits_name": selected.type_limits_name,
                        },
                    ),
                ),
                risk=RiskLevel.LOW,
                confidence=0.99,
                input_sha256=context.input_sha256,
                idd_sha256=context.idd_sha256,
                version=context.version,
                metadata={
                    "cross_role_copy_forbidden": True,
                    "mechanism": "schedule_unique_bounded_typo",
                    "opposed_semantic_role_excluded": True,
                },
            ),)
        targets = _targets(context, inventory)
        if len(targets) != 1:
            return ()
        obj, field, field_def = targets[0]
        consensus = _peer_consensus(
            target=obj,
            field_index=field.index,
            document_objects=context.document.objects,
            inventory=inventory,
        )
        if consensus is None:
            return ()
        selected = inventory[consensus.proposed_key]
        role_context = " ".join((obj.object_type, obj.name, field_def.name, field.value))
        if _cross_role(role_context, selected.name):
            return ()
        operation = RepairOperation(
            kind=OperationKind.RENAME_REFERENCE,
            object_type=obj.object_type,
            object_name=obj.name or None,
            object_index=obj.index,
            field_index=field.index,
            field_name=field_def.name,
            old_value=field.value,
            new_value=selected.name,
            metadata={
                "schedule_profile_fingerprint": selected.profile_fingerprint,
                "schedule_type_limits_name": selected.type_limits_name,
                "peer_names": consensus.peer_names,
            },
        )
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=(operation,),
        )
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="reference_schedule",
            operations=(operation,),
            evidence=(
                CandidateEvidence(
                    kind="idd_field_role",
                    source="current_version_Energy+.idd",
                    strength=1.0,
                    details={
                        "field_name": field_def.name,
                        "object_lists": field_def.object_lists,
                    },
                ),
                CandidateEvidence(
                    kind="same_role_peer_consensus",
                    source="local_object_graph",
                    strength=1.0,
                    details={
                        "peer_count": consensus.peer_count,
                        "peer_names": consensus.peer_names,
                        "closest_similarity": consensus.closest_similarity,
                        "competing_reference_count": consensus.competing_reference_count,
                    },
                ),
                CandidateEvidence(
                    kind="schedule_profile_identity",
                    source="faulty_idf_existing_schedule",
                    strength=1.0,
                    details={
                        "schedule_object_type": selected.object_type,
                        "schedule_type_limits_name": selected.type_limits_name,
                        "profile_fingerprint": selected.profile_fingerprint,
                    },
                ),
            ),
            risk=RiskLevel.LOW,
            confidence=0.995,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            requires_user_confirmation=False,
            metadata={
                "mechanism": "same_role_local_peer_consensus",
                "cross_role_copy_forbidden": True,
                "counterpart_copy_forbidden": True,
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        changes = changed_fields(before, after)
        expected = ((operation.object_index, operation.field_index, operation.old_value, operation.new_value),)
        reasons: list[str] = []
        role_context = " ".join(filter(None, (
            operation.object_type,
            operation.object_name,
            operation.field_name,
            operation.old_value,
        )))
        cross_role = _cross_role(role_context, operation.new_value or "")
        if cross_role:
            reasons.append("schedule_cross_role_copy_forbidden")
        if changes != expected:
            reasons.append("schedule_patch_scope_changed")
        document = parse_idf(after)
        if context is None:
            reasons.append("schedule_validation_context_missing")
            return False, tuple(reasons), {
                "changes": changes,
                "replacement_exists": False,
                "cross_role": cross_role,
                "peer_names": operation.metadata.get("peer_names", ()),
                "schedule_type_limits_name": None,
            }
        if operation.object_index is None or operation.object_index >= len(document.objects):
            reasons.append("schedule_target_missing_after_patch")
        else:
            target = document.objects[operation.object_index]
            definition = context.idd.get(target.object_type)
            field_def = definition.field_at(operation.field_index or 0) if definition else None
            if field_def is None or field_def.role != "schedule_reference":
                reasons.append("schedule_target_role_changed")
        after_context = CandidateContext(
            document=document,
            idd=context.idd,
            roots=context.roots,
            diagnostics_text=context.diagnostics_text,
            rdd=context.rdd,
            version=context.version,
            runtime_identity=context.runtime_identity,
            object_graph=context.object_graph,
            metadata=context.metadata,
        )
        inventory = _schedule_inventory(after_context)
        selected = inventory.get(canonical(operation.new_value or ""))
        if selected is None:
            reasons.append("replacement_schedule_not_unique_existing_object")
        if (
            candidate.metadata.get("mechanism") == "schedule_unique_bounded_typo"
            and operation.object_index is not None
            and operation.object_index < len(context.document.objects)
        ):
            choices = tuple(row.name for row in _schedule_inventory(context).values())
            bounded = bounded_unique_choice(operation.old_value or "", choices)
            if bounded is None or canonical(bounded[0]) != canonical(
                operation.new_value or ""
            ):
                reasons.append("schedule_bounded_typo_not_reproducible")
        elif operation.object_index is not None and operation.object_index < len(context.document.objects):
            old_target = context.document.objects[operation.object_index]
            consensus = _peer_consensus(
                target=old_target,
                field_index=operation.field_index or 0,
                document_objects=context.document.objects,
                inventory=_schedule_inventory(context),
            )
            if consensus is None or consensus.proposed_key != canonical(operation.new_value or ""):
                reasons.append("schedule_peer_consensus_not_reproducible")
        return not reasons, tuple(reasons), {
            "changes": changes,
            "replacement_exists": selected is not None,
            "cross_role": cross_role,
            "peer_names": operation.metadata.get("peer_names", ()),
            "schedule_type_limits_name": selected.type_limits_name if selected else None,
        }


__all__ = ["ScheduleProvider"]
