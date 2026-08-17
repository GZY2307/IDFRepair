"""从 current ModelIR 与 scanner observations 生成内部证据候选域。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import permutations

from idfrepair.io.idf import canonical
from idfrepair.semantic_graph_v2.edits import (
    FieldEdit,
    FieldValuePrecondition,
    RelationStatePrecondition,
    SemanticEdit,
    SemanticEditKind,
    compile_field_edit,
    make_semantic_edit,
)
from idfrepair.semantic_graph_v2.ir import (
    AirPathRelation,
    BranchListRelation,
    BranchPath,
    ConnectorPair,
    EquipmentPathRelation,
    FieldRef,
    LoopSideRelation,
    ModelIR,
    ObjectRef,
    OrderedTypedReference,
    ZoneEquipmentListRelation,
)
from idfrepair.semantic_graph_v2.registry import AdmissionStatus
from idfrepair.semantic_graph_v2.scan import (
    ScanResult,
    Violation,
    _compatible_loop_pairs,
    _connector_needed_set,
)


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class CandidateDomainStatus(_StringEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_UNSUPPORTED = "INCOMPLETE_UNSUPPORTED"
    TRUNCATED = "TRUNCATED"


@dataclass(frozen=True, slots=True)
class CandidateSet:
    violation_id: str
    constraint_id: str
    status: CandidateDomainStatus
    candidates: tuple[SemanticEdit, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateGeneration:
    model_sha256: str
    candidate_sets: tuple[CandidateSet, ...]

    def for_violation(self, violation_id: str) -> CandidateSet | None:
        return next(
            (row for row in self.candidate_sets if row.violation_id == violation_id),
            None,
        )

    @property
    def all_edits(self) -> tuple[SemanticEdit, ...]:
        unique: dict[str, SemanticEdit] = {}
        for domain in self.candidate_sets:
            for edit in domain.candidates:
                unique.setdefault(edit.semantic_signature, edit)
        return tuple(unique[key] for key in sorted(unique))


def _fact_map(values: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(values)


def _object_by_id(model: ModelIR, object_id: str) -> ObjectRef | None:
    return next((obj for obj in model.objects if obj.object_id == object_id), None)


def _field_writes(field_edits: tuple[FieldEdit, ...]) -> tuple[str, ...]:
    return tuple(f"field:{field.field_id}" for field in field_edits)


def _make_edit(
    model: ModelIR,
    violation: Violation,
    *,
    kind: SemanticEditKind,
    field_edits: tuple[FieldEdit, ...],
    signature: str,
    evidence: tuple[tuple[str, str], ...] = (),
    extra_reads: tuple[str, ...] = (),
    extra_writes: tuple[str, ...] = (),
) -> SemanticEdit:
    reads = tuple(sorted(set((
        *violation.read_variables,
        *violation.latent_factors,
        *extra_reads,
        *(f"field:{field.field_id}" for field in violation.field_refs),
    ))))
    fields_by_variable = {
        f"field:{field.field_id}": field
        for obj in model.objects for field in obj.fields
    }
    field_preconditions = []
    relation_preconditions = []
    for variable in reads:
        if variable.startswith("field:object:") and ":field:" in variable:
            field = fields_by_variable.get(variable)
            if field is None:
                raise ValueError(f"field_read_not_in_model:{variable}")
            field_preconditions.append(FieldValuePrecondition(
                object_index=field.object_index,
                object_type=field.object_type,
                object_name=field.object_name,
                field_index=field.field_index,
                field_name=field.field_name,
                expected_value=field.raw_value,
            ))
        else:
            relation_preconditions.append(RelationStatePrecondition(
                variable_id=variable,
                expected_document_sha256=model.document_sha256,
            ))
    return make_semantic_edit(
        kind=kind,
        scope_ids=violation.scope_ids,
        relation_ids=violation.relation_ids,
        resolves_constraint_ids=(violation.constraint_id,),
        evidence=(*violation.evidence, *evidence),
        precondition_reads=reads,
        write_variables=(*_field_writes(field_edits), *extra_writes),
        field_edits=field_edits,
        semantic_signature=signature,
        field_preconditions=tuple(field_preconditions),
        relation_preconditions=tuple(relation_preconditions),
    )


def _changed_field_edit(field: FieldRef, new_value: str) -> FieldEdit | None:
    if canonical(new_value) == field.normalized_value:
        return None
    return compile_field_edit(field, new_value)


def _typed_reference_edit(
    model: ModelIR,
    violation: Violation,
    type_field: FieldRef,
    name_field: FieldRef,
    target: ObjectRef,
    *,
    kind: SemanticEditKind = SemanticEditKind.REPLACE_TYPED_REFERENCE,
) -> SemanticEdit | None:
    fields = tuple(
        row for row in (
            _changed_field_edit(type_field, target.raw_object_type),
            _changed_field_edit(name_field, target.raw_name),
        ) if row is not None
    )
    if not fields:
        return None
    return _make_edit(
        model,
        violation,
        kind=kind,
        field_edits=fields,
        signature=(
            f"typed-reference:{type_field.field_id}:{target.object_id}:"
            f"{target.normalized_object_type}:{target.normalized_name}"
        ),
        evidence=(("target_object_id", target.object_id),),
        extra_writes=(f"typed-reference:{type_field.object_index}:{type_field.field_index}",),
    )


def _ids_from_expected(violation: Violation, key: str) -> tuple[str, ...]:
    value = _fact_map(violation.expected).get(key, "")
    return tuple(item for item in value.split("|") if item)


def _branch_identity_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    if len(violation.field_refs) < 2:
        return ()
    type_field, name_field = violation.field_refs[:2]
    rows = []
    for object_id in _ids_from_expected(violation, "compatible_object_ids"):
        target = _object_by_id(model, object_id)
        if target is None:
            continue
        edit = _typed_reference_edit(
            model, violation, type_field, name_field, target,
        )
        if edit is not None:
            rows.append(edit)
    return tuple(rows)


def _branch_endpoint_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    if not violation.field_refs:
        return ()
    value = _fact_map(violation.expected).get("node", "")
    field_edit = _changed_field_edit(violation.field_refs[0], value)
    if field_edit is None:
        return ()
    return (_make_edit(
        model,
        violation,
        kind=SemanticEditKind.REPLACE_ENDPOINT,
        field_edits=(field_edit,),
        signature=f"endpoint:{field_edit.field_id}:{canonical(value)}",
        extra_writes=(f"endpoint:{field_edit.field_id}",),
    ),)


def _branch_from_violation(
    model: ModelIR, violation: Violation,
) -> BranchPath | None:
    return next(
        (
            relation for relation_id in violation.relation_ids
            for relation in (model.relation(relation_id),)
            if isinstance(relation, BranchPath)
        ),
        None,
    )


def _branch_reorder_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[tuple[SemanticEdit, ...], CandidateDomainStatus]:
    branch = _branch_from_violation(model, violation)
    if branch is None or len(branch.members) < 2:
        return (), CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
    if len(branch.members) > 7:
        return (), CandidateDomainStatus.TRUNCATED
    rows = []
    current = tuple(branch.members)
    for order in permutations(current):
        if order == current or any(
            left.outlet_field.normalized_value != right.inlet_field.normalized_value
            for left, right in zip(order, order[1:])
        ):
            continue
        field_edits: list[FieldEdit] = []
        for destination, source in zip(current, order):
            pairs = (
                (destination.type_field, source.type_field.raw_value),
                (destination.name_field, source.name_field.raw_value),
                (destination.inlet_field, source.inlet_field.raw_value),
                (destination.outlet_field, source.outlet_field.raw_value),
            )
            field_edits.extend(
                edit for field, value in pairs
                for edit in (_changed_field_edit(field, value),)
                if edit is not None
            )
        if not field_edits:
            continue
        order_signature = "|".join(str(member.ordinal) for member in order)
        rows.append(_make_edit(
            model,
            violation,
            kind=SemanticEditKind.REORDER_PATH_MEMBERS,
            field_edits=tuple(field_edits),
            signature=f"branch-order:{branch.object_ref.object_id}:{order_signature}",
            evidence=(("directed_order", order_signature),),
            extra_writes=(f"branch-order:{branch.object_ref.object_id}",),
        ))
    return tuple(rows), CandidateDomainStatus.COMPLETE


def _pair_from_violation(
    model: ModelIR, violation: Violation,
) -> ConnectorPair | None:
    return next(
        (
            relation for relation_id in violation.relation_ids
            for relation in (model.relation(relation_id),)
            if isinstance(relation, ConnectorPair)
        ),
        None,
    )


def _parallel_set_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    pair = _pair_from_violation(model, violation)
    if pair is None or pair.splitter is None or pair.mixer is None:
        return ()
    rows = []
    sides = (
        (pair.splitter.parallel_fields, pair.mixer.parallel_fields, "splitter"),
        (pair.mixer.parallel_fields, pair.splitter.parallel_fields, "mixer"),
    )
    for fields, other_fields, side in sides:
        other_values = {
            field.normalized_value: field.raw_value for field in other_fields
        }
        other_set = set(other_values)
        current_set = {field.normalized_value for field in fields}
        extras = tuple(field for field in fields if field.normalized_value not in other_set)
        missing = tuple(sorted(other_set - current_set))
        for field in extras:
            for normalized_value in missing:
                value = other_values[normalized_value]
                field_edit = _changed_field_edit(field, value)
                if field_edit is None:
                    continue
                rows.append(_make_edit(
                    model,
                    violation,
                    kind=SemanticEditKind.REPLACE_CONNECTOR_MEMBER,
                    field_edits=(field_edit,),
                    signature=f"parallel-set:{field.field_id}:{value}",
                    evidence=(("reciprocal_side", side),),
                    extra_writes=(f"parallel-set:{pair.object_ref.object_id}",),
                ))
    return tuple(rows)


def _branchlist_and_pair(
    model: ModelIR, violation: Violation,
) -> tuple[BranchListRelation | None, ConnectorPair | None]:
    branch_list = next(
        (
            relation for relation_id in violation.relation_ids
            for relation in (model.relation(relation_id),)
            if isinstance(relation, BranchListRelation)
        ),
        None,
    )
    return branch_list, _pair_from_violation(model, violation)


def _branchlist_set_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    branch_list, pair = _branchlist_and_pair(model, violation)
    if branch_list is None or pair is None:
        return ()
    needed = _connector_needed_set(pair)
    if needed is None:
        return ()
    assert pair.splitter is not None and pair.mixer is not None
    needed_values = {
        field.normalized_value: field.raw_value
        for field in (
            pair.splitter.boundary_field,
            *pair.splitter.parallel_fields,
            pair.mixer.boundary_field,
        )
    }
    current = set(branch_list.normalized_members)
    extras = tuple(
        field for field in branch_list.member_fields
        if field.normalized_value not in needed
    )
    missing = tuple(sorted(needed - current))
    rows = []
    for field in extras:
        for normalized_value in missing:
            value = needed_values[normalized_value]
            field_edit = _changed_field_edit(field, value)
            if field_edit is None:
                continue
            rows.append(_make_edit(
                model,
                violation,
                kind=SemanticEditKind.REPLACE_ORDERED_MEMBER,
                field_edits=(field_edit,),
                signature=f"branchlist-set:{field.field_id}:{value}",
                extra_writes=(f"branchlist-members:{branch_list.object_ref.object_id}",),
            ))
    return tuple(rows)


def _branchlist_boundary_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    branch_list, _ = _branchlist_and_pair(model, violation)
    if branch_list is None:
        return ()
    facts = _fact_map(violation.expected)
    expected = facts.get("branch", "")
    boundary = _fact_map(violation.observed).get("boundary", "")
    destination = (
        branch_list.member_fields[0] if boundary == "inlet"
        else branch_list.member_fields[-1]
    )
    donor = next(
        (
            field for field in branch_list.member_fields
            if field.normalized_value == canonical(expected)
        ),
        None,
    )
    field_edits: list[FieldEdit] = []
    if donor is not None and donor.field_id != destination.field_id:
        for field, value in (
            (destination, donor.raw_value), (donor, destination.raw_value),
        ):
            edit = _changed_field_edit(field, value)
            if edit is not None:
                field_edits.append(edit)
    else:
        edit = _changed_field_edit(destination, expected)
        if edit is not None:
            field_edits.append(edit)
    if not field_edits:
        return ()
    return (_make_edit(
        model,
        violation,
        kind=SemanticEditKind.REORDER_PATH_MEMBERS,
        field_edits=tuple(field_edits),
        signature=f"branchlist-boundary:{branch_list.object_ref.object_id}:{boundary}:{canonical(expected)}",
        extra_writes=(f"branchlist-order:{branch_list.object_ref.object_id}",),
    ),)


def _loop_side_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    side = next(
        (
            relation for relation_id in violation.relation_ids
            for relation in (model.relation(relation_id),)
            if isinstance(relation, LoopSideRelation)
        ),
        None,
    )
    if side is None:
        return ()
    rows = []
    for branch_list, pair in _compatible_loop_pairs(model, side):
        field_edits = tuple(
            edit for field, value in (
                (side.branch_list_field, branch_list.object_ref.raw_name),
                (side.connector_list_field, pair.object_ref.raw_name),
            )
            for edit in (_changed_field_edit(field, value),)
            if edit is not None
        )
        if not field_edits:
            continue
        rows.append(_make_edit(
            model,
            violation,
            kind=SemanticEditKind.REPLACE_LOOP_SIDE_REFERENCE,
            field_edits=field_edits,
            signature=(
                f"loop-ownership:{side.object_ref.object_id}:{side.side.value}:"
                f"{branch_list.object_ref.object_id}:{pair.object_ref.object_id}"
            ),
            evidence=(("branch_list", branch_list.object_ref.object_id),
                      ("connector_list", pair.object_ref.object_id)),
            extra_writes=(f"loop-ownership:{side.object_ref.object_id}:{side.side.value}",),
        ))
    return tuple(rows)


def _typed_expected_candidates(
    model: ModelIR,
    violation: Violation,
    *,
    expected_key: str,
    kind: SemanticEditKind,
) -> tuple[SemanticEdit, ...]:
    if len(violation.field_refs) < 2:
        return ()
    type_field, name_field = violation.field_refs[:2]
    rows = []
    for object_id in _ids_from_expected(violation, expected_key):
        target = _object_by_id(model, object_id)
        if target is None:
            continue
        edit = _typed_reference_edit(
            model, violation, type_field, name_field, target, kind=kind,
        )
        if edit is not None:
            rows.append(edit)
    return tuple(rows)


def _domain_status_from_expected(violation: Violation) -> CandidateDomainStatus:
    raw = _fact_map(violation.expected).get("candidate_domain_status", "")
    try:
        return CandidateDomainStatus(raw)
    except ValueError:
        return CandidateDomainStatus.INCOMPLETE_UNSUPPORTED


def _relation_from_violation(
    model: ModelIR,
    violation: Violation,
    relation_type: type[AirPathRelation] | type[EquipmentPathRelation],
) -> AirPathRelation | EquipmentPathRelation | None:
    return next(
        (
            relation
            for relation_id in violation.relation_ids
            for relation in (model.relation(relation_id),)
            if isinstance(relation, relation_type)
        ),
        None,
    )


def _compound_typed_candidates(
    model: ModelIR,
    violation: Violation,
) -> tuple[SemanticEdit, ...]:
    path = _relation_from_violation(
        model, violation, (AirPathRelation, EquipmentPathRelation),
    )
    if path is None:
        return ()
    by_ordinal = {member.ordinal: member for member in path.members}
    rows: list[SemanticEdit] = []
    for encoded in _ids_from_expected(violation, "compatible_replacements"):
        ordinal_text, separator, object_id = encoded.partition("@")
        if not separator:
            continue
        try:
            ordinal = int(ordinal_text)
        except ValueError:
            continue
        member = by_ordinal.get(ordinal)
        target = _object_by_id(model, object_id)
        if member is None or target is None:
            continue
        edit = _typed_reference_edit(
            model,
            violation,
            member.type_field,
            member.name_field,
            target,
            kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
        )
        if edit is not None:
            rows.append(edit)
    return tuple(rows)


def _oa_reorder_candidates(
    model: ModelIR,
    violation: Violation,
) -> tuple[SemanticEdit, ...]:
    path = _relation_from_violation(model, violation, EquipmentPathRelation)
    if not isinstance(path, EquipmentPathRelation):
        return ()
    by_ordinal = {member.ordinal: member for member in path.members}
    current = tuple(path.members)
    rows: list[SemanticEdit] = []
    for encoded in _ids_from_expected(violation, "compatible_orders"):
        try:
            ordinals = tuple(int(value) for value in encoded.split(","))
        except ValueError:
            continue
        if len(ordinals) != len(current) or set(ordinals) != set(by_ordinal):
            continue
        order = tuple(by_ordinal[ordinal] for ordinal in ordinals)
        field_edits = tuple(
            edit
            for destination, source in zip(current, order)
            for field, value in (
                (destination.type_field, source.type_field.raw_value),
                (destination.name_field, source.name_field.raw_value),
            )
            for edit in (_changed_field_edit(field, value),)
            if edit is not None
        )
        if not field_edits:
            continue
        order_signature = "|".join(str(ordinal) for ordinal in ordinals)
        rows.append(_make_edit(
            model,
            violation,
            kind=SemanticEditKind.REORDER_PATH_MEMBERS,
            field_edits=field_edits,
            signature=f"oa-order:{path.system_ref.object_id}:{order_signature}",
            evidence=(("directed_order", order_signature),),
            extra_writes=(f"oa-order:{path.system_ref.object_id}",),
        ))
    return tuple(rows)


def _zone_list_candidates(
    model: ModelIR, violation: Violation,
) -> tuple[SemanticEdit, ...]:
    if not violation.field_refs:
        return ()
    intended_name = _fact_map(violation.expected).get("intended_list", "")
    matches = tuple(
        row for row in model.zone_equipment_lists
        if row.object_ref.normalized_name == canonical(intended_name)
    )
    if len(matches) != 1:
        return ()
    field_edit = _changed_field_edit(violation.field_refs[0], matches[0].object_ref.raw_name)
    if field_edit is None:
        return ()
    factor_writes = tuple(f"zone-ownership:{scope}" for scope in violation.scope_ids)
    return (_make_edit(
        model,
        violation,
        kind=SemanticEditKind.REPLACE_LOOP_SIDE_REFERENCE,
        field_edits=(field_edit,),
        signature=f"zone-list:{field_edit.field_id}:{matches[0].object_ref.object_id}",
        evidence=(("target_list", matches[0].object_ref.object_id),),
        extra_writes=factor_writes,
    ),)


def _deduplicate(candidates: tuple[SemanticEdit, ...]) -> tuple[SemanticEdit, ...]:
    by_signature: dict[str, SemanticEdit] = {}
    for edit in candidates:
        by_signature.setdefault(edit.semantic_signature, edit)
    return tuple(by_signature[key] for key in sorted(by_signature))


def _generate_one(
    model: ModelIR,
    violation: Violation,
) -> tuple[tuple[SemanticEdit, ...], CandidateDomainStatus, str]:
    if violation.admission_status is not AdmissionStatus.ADMIT_SAFE_AUTO:
        return (), CandidateDomainStatus.INCOMPLETE_UNSUPPORTED, "detect_only"
    constraint = violation.constraint_id
    status = CandidateDomainStatus.COMPLETE
    if constraint == "V2-BRANCH-TYPED-IDENTITY-001":
        candidates = _branch_identity_candidates(model, violation)
    elif constraint == "V2-BRANCH-ENDPOINT-002":
        candidates = _branch_endpoint_candidates(model, violation)
    elif constraint == "V2-BRANCH-CONTINUITY-003":
        candidates, status = _branch_reorder_candidates(model, violation)
    elif constraint == "V2-LOOP-PARALLEL-SET-004":
        candidates = _parallel_set_candidates(model, violation)
    elif constraint == "V2-LOOP-BRANCHLIST-SET-005":
        candidates = _branchlist_set_candidates(model, violation)
    elif constraint == "V2-LOOP-BRANCHLIST-BOUNDARY-006":
        candidates = _branchlist_boundary_candidates(model, violation)
    elif constraint == "V2-LOOP-SIDE-OWNERSHIP-007":
        candidates = _loop_side_candidates(model, violation)
    elif constraint == "V2-CONNECTOR-TYPED-MEMBER-008":
        candidates = _typed_expected_candidates(
            model, violation, expected_key="compatible_connector_ids",
            kind=SemanticEditKind.REPLACE_CONNECTOR_MEMBER,
        )
    elif constraint == "V2-AIRPATH-TYPED-MEMBER-009":
        status = _domain_status_from_expected(violation)
        candidates = _compound_typed_candidates(model, violation)
    elif constraint == "V2-OA-EQUIPMENT-PATH-010":
        status = _domain_status_from_expected(violation)
        candidates = (
            *_compound_typed_candidates(model, violation),
            *_oa_reorder_candidates(model, violation),
        )
    elif constraint == "V2-ZONE-LIST-OWNERSHIP-011":
        candidates = _zone_list_candidates(model, violation)
    elif constraint == "V2-ZONE-TYPED-MEMBER-012":
        candidates = _typed_expected_candidates(
            model, violation, expected_key="compatible_object_ids",
            kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
        )
    else:
        return (), CandidateDomainStatus.INCOMPLETE_UNSUPPORTED, "generator_not_registered"
    candidates = _deduplicate(candidates)
    reason = "enumerated" if candidates else (
        "search_truncated" if status is CandidateDomainStatus.TRUNCATED
        else "no_internal_evidence_candidate"
    )
    return candidates, status, reason


def generate_candidates(model: ModelIR, scan: ScanResult) -> CandidateGeneration:
    """为 scanner observations 枚举 candidate domains；不读取外部 target hints。"""

    if model.document_sha256 != scan.model.document_sha256:
        raise ValueError("scan_model_identity_mismatch")
    domains = []
    for violation in scan.violations:
        mutable_path_evidence = (
            violation.constraint_id == "V2-BRANCH-CONTINUITY-003"
            and any(
                other.constraint_id in {
                    "V2-BRANCH-TYPED-IDENTITY-001",
                    "V2-BRANCH-ENDPOINT-002",
                }
                and bool(
                    set(violation.read_variables)
                    & set(other.latent_factors)
                )
                for other in scan.hard_violations
                if other.violation_id != violation.violation_id
            )
        )
        if mutable_path_evidence:
            domains.append(CandidateSet(
                violation_id=violation.violation_id,
                constraint_id=violation.constraint_id,
                status=CandidateDomainStatus.INCOMPLETE_UNSUPPORTED,
                candidates=(),
                reason="cooccurring_endpoint_or_identity_violation",
            ))
            continue
        candidates, status, reason = _generate_one(model, violation)
        domains.append(CandidateSet(
            violation_id=violation.violation_id,
            constraint_id=violation.constraint_id,
            status=status,
            candidates=candidates,
            reason=reason,
        ))
    return CandidateGeneration(
        model_sha256=model.document_sha256,
        candidate_sets=tuple(domains),
    )


__all__ = [
    "CandidateDomainStatus",
    "CandidateGeneration",
    "CandidateSet",
    "generate_candidates",
]
