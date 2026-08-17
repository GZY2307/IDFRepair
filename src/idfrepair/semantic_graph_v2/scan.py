"""对 canonical IR 执行 target-free whole-model constraint scan。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from itertools import permutations
from typing import Callable, TypeAlias

from idfrepair.io.idf import IDFDocument, canonical
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.ir import (
    AirPathRelation,
    BranchListRelation,
    BranchMember,
    BranchPath,
    ConnectorKind,
    ConnectorPair,
    ConnectorRelation,
    CompoundFlowProjection,
    EquipmentPathRelation,
    EvidenceScore,
    FieldRef,
    LoopSideRelation,
    ModelIR,
    ObjectRef,
    OutdoorAirSystemContext,
    PortRef,
    PortRole,
    ZoneEquipmentListRelation,
    ZoneEquipmentMember,
    ZoneEquipmentRelation,
)
from idfrepair.semantic_graph_v2.registry import (
    AdmissionStatus,
    ConstraintRegistry,
    ConstraintSpec,
    EvidenceClass,
    production_registry,
)


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ViolationSeverity(_StringEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


FactTuple: TypeAlias = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Violation:
    """一个纯 observation；候选生成与求解不会参与其成立判断。"""

    violation_id: str
    constraint_id: str
    severity: ViolationSeverity
    admission_status: AdmissionStatus
    evidence_class: EvidenceClass
    scope_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    field_refs: tuple[FieldRef, ...]
    observed: FactTuple
    expected: FactTuple
    evidence: FactTuple
    read_variables: tuple[str, ...]
    latent_factors: tuple[str, ...]
    message: str

    @property
    def hard(self) -> bool:
        return self.admission_status is AdmissionStatus.ADMIT_SAFE_AUTO


@dataclass(frozen=True, slots=True)
class ApplicabilityRecord:
    constraint_id: str
    scope_id: str
    applied: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    model: ModelIR
    violations: tuple[Violation, ...]
    applicability: tuple[ApplicabilityRecord, ...]

    @property
    def hard_violations(self) -> tuple[Violation, ...]:
        return tuple(row for row in self.violations if row.hard)

    @property
    def constraint_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(row.constraint_id for row in self.violations))


@dataclass(frozen=True, slots=True)
class _PortPair:
    object_ref: ObjectRef
    inlet: PortRef
    outlet: PortRef

    @property
    def nodes(self) -> tuple[str, str]:
        return self.inlet.normalized_node_name, self.outlet.normalized_node_name


def _facts(**values: object) -> FactTuple:
    return tuple((key, str(value)) for key, value in sorted(values.items()))


def _stable_violation_id(
    spec: ConstraintSpec,
    relation_ids: tuple[str, ...],
    fields: tuple[FieldRef, ...],
    suffix: str = "",
) -> str:
    anchors = tuple(field.field_id for field in fields) or relation_ids
    return "@".join((spec.constraint_id, *anchors, suffix)).rstrip("@")


def _violation(
    spec: ConstraintSpec,
    *,
    scope_ids: tuple[str, ...],
    relation_ids: tuple[str, ...],
    field_refs: tuple[FieldRef, ...],
    observed: FactTuple,
    expected: FactTuple,
    evidence: FactTuple = (),
    read_variables: tuple[str, ...] = (),
    latent_factors: tuple[str, ...] = (),
    message: str,
    suffix: str = "",
) -> Violation:
    severity = (
        ViolationSeverity.ERROR if spec.hard else ViolationSeverity.WARNING
    )
    return Violation(
        violation_id=_stable_violation_id(spec, relation_ids, field_refs, suffix),
        constraint_id=spec.constraint_id,
        severity=severity,
        admission_status=spec.admission_status,
        evidence_class=spec.evidence_class,
        scope_ids=scope_ids,
        relation_ids=relation_ids,
        field_refs=field_refs,
        observed=observed,
        expected=expected,
        evidence=evidence,
        read_variables=tuple(sorted(set(read_variables))),
        latent_factors=tuple(sorted(set(latent_factors))),
        message=message,
    )


def _port_pairs(model: ModelIR, object_ref: ObjectRef) -> tuple[_PortPair, ...]:
    grouped: dict[tuple[str, str], list[PortRef]] = {}
    for port in model.ports_for(object_ref.object_id):
        grouped.setdefault((str(port.medium), port.port_group), []).append(port)
    rows: list[_PortPair] = []
    for ports in grouped.values():
        inlets = tuple(port for port in ports if port.role is PortRole.INLET)
        outlets = tuple(port for port in ports if port.role is PortRole.OUTLET)
        if len(inlets) == 1 and len(outlets) == 1:
            rows.append(_PortPair(object_ref, inlets[0], outlets[0]))
    return tuple(rows)


def _all_port_pairs(model: ModelIR) -> tuple[_PortPair, ...]:
    return tuple(
        pair for obj in model.objects for pair in _port_pairs(model, obj)
    )


def _member_identity(model: ModelIR, member: BranchMember) -> tuple[ObjectRef, ...]:
    return model.resolve_identity(member.object_type, member.object_name)


def _branch_factor(branch: BranchPath, member: BranchMember | None = None) -> str:
    if member is None:
        return f"branch-path:{branch.object_ref.object_id}"
    return f"branch-member:{branch.object_ref.object_id}:{member.ordinal}"


def _eval_branch_typed_identity(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    all_pairs = _all_port_pairs(model)
    rows: list[Violation] = []
    for branch in model.branches:
        for member in branch.members:
            endpoints = (
                member.inlet_field.normalized_value,
                member.outlet_field.normalized_value,
            )
            compatible = tuple(
                pair for pair in all_pairs if pair.nodes == endpoints
            )
            if not compatible:
                continue
            current_ids = {
                obj.object_id for obj in _member_identity(model, member)
            }
            if any(pair.object_ref.object_id in current_ids for pair in compatible):
                continue
            factor = _branch_factor(branch, member)
            rows.append(_violation(
                spec,
                scope_ids=(factor,),
                relation_ids=(branch.relation_id,),
                field_refs=(member.type_field, member.name_field),
                observed=_facts(
                    object_type=member.object_type,
                    object_name=member.object_name,
                ),
                expected=_facts(
                    compatible_object_ids="|".join(
                        sorted({pair.object_ref.object_id for pair in compatible})
                    ),
                ),
                evidence=_facts(
                    inlet=member.inlet_node,
                    outlet=member.outlet_node,
                ),
                read_variables=(
                    f"field:{member.type_field.field_id}",
                    f"field:{member.name_field.field_id}",
                    f"field:{member.inlet_field.field_id}",
                    f"field:{member.outlet_field.field_id}",
                    *(f"port:{pair.inlet.port_id}" for pair in compatible),
                    *(f"port:{pair.outlet.port_id}" for pair in compatible),
                ),
                latent_factors=(factor,),
                message="Branch typed member is inconsistent with its exact endpoint pair.",
                suffix=str(member.ordinal),
            ))
    return tuple(rows)


def _select_expected_pair(
    pairs: tuple[_PortPair, ...],
    declared: tuple[str, str],
) -> _PortPair | None:
    if len(pairs) == 1:
        return pairs[0]
    exact = tuple(pair for pair in pairs if pair.nodes == declared)
    if len(exact) == 1:
        return exact[0]
    partial = tuple(
        pair for pair in pairs
        if pair.nodes[0] == declared[0] or pair.nodes[1] == declared[1]
    )
    return partial[0] if len(partial) == 1 else None


def _eval_branch_endpoint(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for branch in model.branches:
        for member in branch.members:
            identities = _member_identity(model, member)
            if len(identities) != 1:
                continue
            declared = (
                member.inlet_field.normalized_value,
                member.outlet_field.normalized_value,
            )
            expected_pair = _select_expected_pair(
                _port_pairs(model, identities[0]), declared,
            )
            if expected_pair is None:
                continue
            factor = _branch_factor(branch, member)
            comparisons = (
                ("inlet", member.inlet_field, expected_pair.inlet),
                ("outlet", member.outlet_field, expected_pair.outlet),
            )
            for role, declared_field, port in comparisons:
                if declared_field.normalized_value == port.normalized_node_name:
                    continue
                rows.append(_violation(
                    spec,
                    scope_ids=(factor,),
                    relation_ids=(branch.relation_id,),
                    field_refs=(declared_field,),
                    observed=_facts(role=role, node=declared_field.raw_value),
                    expected=_facts(role=role, node=port.node_name),
                    evidence=_facts(
                        typed_object=identities[0].object_id,
                        port_rule=port.rule_id,
                    ),
                    read_variables=(
                        f"field:{member.type_field.field_id}",
                        f"field:{member.name_field.field_id}",
                        f"field:{declared_field.field_id}",
                        f"port:{port.port_id}",
                    ),
                    latent_factors=(factor,),
                    message=f"Branch {role} disagrees with the declared component port.",
                    suffix=f"{member.ordinal}:{role}",
                ))
    return tuple(rows)


def _eval_branch_continuity(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for branch in model.branches:
        factor = _branch_factor(branch)
        for left, right in zip(branch.members, branch.members[1:]):
            if left.outlet_field.normalized_value == right.inlet_field.normalized_value:
                continue
            rows.append(_violation(
                spec,
                scope_ids=(factor,),
                relation_ids=(branch.relation_id,),
                field_refs=(left.outlet_field, right.inlet_field),
                observed=_facts(
                    upstream_outlet=left.outlet_node,
                    downstream_inlet=right.inlet_node,
                ),
                expected=_facts(relation="equal_adjacent_nodes"),
                read_variables=(
                    f"field:{left.outlet_field.field_id}",
                    f"field:{right.inlet_field.field_id}",
                    *(
                        f"branch-member:{branch.object_ref.object_id}:{member.ordinal}"
                        for member in branch.members
                    ),
                ),
                latent_factors=(factor,),
                message="Adjacent Branch member endpoints are discontinuous.",
                suffix=f"{left.ordinal}:{right.ordinal}",
            ))
    return tuple(rows)


def _eval_branch_duplicate_member(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for branch in model.branches:
        positions: dict[tuple[str, str], list[BranchMember]] = {}
        for member in branch.members:
            positions.setdefault((
                member.type_field.normalized_value,
                member.name_field.normalized_value,
            ), []).append(member)
        for members in positions.values():
            if len(members) < 2 or not all(member.object_name.strip() for member in members):
                continue
            fields = tuple(
                field for member in members
                for field in (member.type_field, member.name_field)
            )
            rows.append(_violation(
                spec,
                scope_ids=(_branch_factor(branch),),
                relation_ids=(branch.relation_id,),
                field_refs=fields,
                observed=_facts(ordinals="|".join(str(row.ordinal) for row in members)),
                expected=_facts(action="external_intent_required_before_deletion"),
                read_variables=tuple(f"field:{field.field_id}" for field in fields),
                latent_factors=(_branch_factor(branch),),
                message="Branch repeats the same typed member; deletion is not autonomous.",
            ))
    return tuple(rows)


def _eval_loop_parallel_set(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for pair in model.connector_pairs:
        if pair.splitter is None or pair.mixer is None:
            continue
        splitter_set = pair.splitter.parallel_branch_set
        mixer_set = pair.mixer.parallel_branch_set
        if splitter_set == mixer_set:
            continue
        factor = f"connector-pair:{pair.object_ref.object_id}"
        fields = (*pair.splitter.parallel_fields, *pair.mixer.parallel_fields)
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(
                pair.relation_id,
                pair.splitter.relation_id,
                pair.mixer.relation_id,
            ),
            field_refs=fields,
            observed=_facts(
                splitter="|".join(sorted(splitter_set)),
                mixer="|".join(sorted(mixer_set)),
            ),
            expected=_facts(relation="equal_parallel_sets"),
            read_variables=tuple(f"field:{field.field_id}" for field in fields),
            latent_factors=(factor,),
            message="Splitter and Mixer parallel branch sets are not reciprocal.",
        ))
    return tuple(rows)


def _unique_relation_by_name(
    relations: tuple,
    name: str,
) -> object | None:
    matches = tuple(
        relation for relation in relations
        if relation.object_ref.normalized_name == canonical(name)
    )
    return matches[0] if len(matches) == 1 else None


def _loop_relations(
    model: ModelIR,
    side: LoopSideRelation,
) -> tuple[BranchListRelation | None, ConnectorPair | None]:
    branch_list = _unique_relation_by_name(
        model.branch_lists, side.branch_list_field.raw_value,
    )
    connector_pair = _unique_relation_by_name(
        model.connector_pairs, side.connector_list_field.raw_value,
    )
    return (
        branch_list if isinstance(branch_list, BranchListRelation) else None,
        connector_pair if isinstance(connector_pair, ConnectorPair) else None,
    )


def _connector_needed_set(pair: ConnectorPair) -> frozenset[str] | None:
    if pair.splitter is None or pair.mixer is None:
        return None
    return frozenset((
        pair.splitter.boundary_field.normalized_value,
        *pair.splitter.parallel_branch_names,
        pair.mixer.boundary_field.normalized_value,
    ))


def _eval_loop_branchlist_set(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for side in model.loop_sides:
        branch_list, pair = _loop_relations(model, side)
        if branch_list is None or pair is None:
            continue
        needed = _connector_needed_set(pair)
        if needed is None or frozenset(branch_list.normalized_members) == needed:
            continue
        factor = f"loop-topology:{side.object_ref.object_id}:{side.side.value.casefold()}"
        fields = (
            side.branch_list_field,
            side.connector_list_field,
            *branch_list.member_fields,
        )
        connector_evidence_fields = (
            pair.splitter.boundary_field,
            *pair.splitter.parallel_fields,
            pair.mixer.boundary_field,
            *pair.mixer.parallel_fields,
        )
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(side.relation_id, branch_list.relation_id, pair.relation_id),
            field_refs=fields,
            observed=_facts(members="|".join(sorted(branch_list.normalized_members))),
            expected=_facts(members="|".join(sorted(needed))),
            read_variables=tuple(
                f"field:{field.field_id}"
                for field in (*fields, *connector_evidence_fields)
            ),
            latent_factors=(factor,),
            message="Loop-side BranchList membership does not close over its connectors.",
        ))
    return tuple(rows)


def _eval_loop_branchlist_boundary(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for side in model.loop_sides:
        branch_list, pair = _loop_relations(model, side)
        if (
            branch_list is None or pair is None or pair.splitter is None
            or pair.mixer is None or not branch_list.member_fields
        ):
            continue
        factor = f"loop-topology:{side.object_ref.object_id}:{side.side.value.casefold()}"
        comparisons = (
            (
                "inlet",
                branch_list.member_fields[0],
                pair.splitter.boundary_field,
            ),
            (
                "outlet",
                branch_list.member_fields[-1],
                pair.mixer.boundary_field,
            ),
        )
        for boundary, current, expected in comparisons:
            if current.normalized_value == expected.normalized_value:
                continue
            rows.append(_violation(
                spec,
                scope_ids=(factor,),
                relation_ids=(side.relation_id, branch_list.relation_id, pair.relation_id),
                field_refs=(current, expected),
                observed=_facts(boundary=boundary, branch=current.raw_value),
                expected=_facts(boundary=boundary, branch=expected.raw_value),
                read_variables=(
                    f"field:{current.field_id}", f"field:{expected.field_id}",
                ),
                latent_factors=(factor,),
                message=f"BranchList {boundary} boundary disagrees with its connector.",
                suffix=boundary,
            ))
    return tuple(rows)


def _branch_by_name(model: ModelIR, name: str) -> BranchPath | None:
    matches = tuple(
        branch for branch in model.branches
        if branch.object_ref.normalized_name == canonical(name)
    )
    return matches[0] if len(matches) == 1 else None


def _branch_list_endpoints(
    model: ModelIR, branch_list: BranchListRelation,
) -> tuple[str, str] | None:
    if not branch_list.member_fields:
        return None
    first = _branch_by_name(model, branch_list.member_fields[0].raw_value)
    last = _branch_by_name(model, branch_list.member_fields[-1].raw_value)
    if first is None or last is None or not first.members or not last.members:
        return None
    return (
        first.members[0].inlet_field.normalized_value,
        last.members[-1].outlet_field.normalized_value,
    )


def _compatible_loop_pairs(
    model: ModelIR, side: LoopSideRelation,
) -> tuple[tuple[BranchListRelation, ConnectorPair], ...]:
    rows = []
    side_endpoints = (
        side.inlet_field.normalized_value,
        side.outlet_field.normalized_value,
    )
    for branch_list in model.branch_lists:
        if _branch_list_endpoints(model, branch_list) != side_endpoints:
            continue
        for pair in model.connector_pairs:
            needed = _connector_needed_set(pair)
            if needed is not None and frozenset(branch_list.normalized_members) == needed:
                rows.append((branch_list, pair))
    return tuple(rows)


def _eval_loop_side_ownership(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for side in model.loop_sides:
        compatible = _compatible_loop_pairs(model, side)
        if not compatible:
            continue
        current = (
            canonical(side.branch_list_field.raw_value),
            canonical(side.connector_list_field.raw_value),
        )
        compatible_names = tuple((
            branch_list.object_ref.normalized_name,
            pair.object_ref.normalized_name,
        ) for branch_list, pair in compatible)
        if current in compatible_names:
            continue
        factor = f"loop-side:{side.object_ref.object_id}:{side.side.value.casefold()}"
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(side.relation_id,),
            field_refs=(side.branch_list_field, side.connector_list_field),
            observed=_facts(branch_list=current[0], connector_list=current[1]),
            expected=_facts(
                compatible_pairs="|".join(
                    f"{branch}/{connector}" for branch, connector in compatible_names
                ),
            ),
            evidence=_facts(
                inlet=side.inlet_field.raw_value,
                outlet=side.outlet_field.raw_value,
            ),
            read_variables=(
                f"field:{side.inlet_field.field_id}",
                f"field:{side.outlet_field.field_id}",
                f"field:{side.branch_list_field.field_id}",
                f"field:{side.connector_list_field.field_id}",
                *(branch_list.relation_id for branch_list, _ in compatible),
                *(pair.relation_id for _, pair in compatible),
            ),
            latent_factors=(factor,),
            message="Loop side references do not select a structurally compatible pair.",
        ))
    return tuple(rows)


def _connector_candidates(
    model: ModelIR,
    kind: ConnectorKind,
    other: ConnectorRelation | None,
) -> tuple[ConnectorRelation, ...]:
    candidates = tuple(row for row in model.connectors if row.kind is kind)
    if other is None:
        return candidates
    return tuple(
        row for row in candidates
        if row.parallel_branch_set == other.parallel_branch_set
    )


def _eval_connector_typed_member(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for pair in model.connector_pairs:
        for member in pair.declared_members:
            declared_type = canonical(member.object_type)
            kind = (
                ConnectorKind.SPLITTER if declared_type == "connector:splitter"
                else ConnectorKind.MIXER if declared_type == "connector:mixer"
                else ConnectorKind.SPLITTER if member.ordinal == 1
                else ConnectorKind.MIXER
            )
            resolved = model.resolve_identity(member.object_type, member.object_name)
            other = pair.mixer if kind is ConnectorKind.SPLITTER else pair.splitter
            candidates = _connector_candidates(model, kind, other)
            valid = (
                len(resolved) == 1
                and canonical(resolved[0].raw_object_type)
                == f"connector:{kind.value.casefold()}"
                and (
                    other is None
                    or any(
                        candidate.object_ref.object_id == resolved[0].object_id
                        for candidate in candidates
                    )
                )
            )
            if valid:
                continue
            if not candidates:
                continue
            factor = f"connector-pair:{pair.object_ref.object_id}"
            rows.append(_violation(
                spec,
                scope_ids=(factor,),
                relation_ids=(pair.relation_id,),
                field_refs=(member.type_field, member.name_field),
                observed=_facts(
                    object_type=member.object_type,
                    object_name=member.object_name,
                ),
                expected=_facts(
                    compatible_connector_ids="|".join(
                        row.object_ref.object_id for row in candidates
                    ),
                ),
                read_variables=(
                    f"field:{member.type_field.field_id}",
                    f"field:{member.name_field.field_id}",
                    *(row.relation_id for row in candidates),
                    *((other.relation_id,) if other is not None else ()),
                ),
                latent_factors=(factor,),
                message="ConnectorList typed member does not resolve to reciprocal closure.",
                suffix=str(member.ordinal),
            ))
    return tuple(rows)


_AIRPATH_ALLOWED_TYPES = {
    "airloophvac:supplypath": frozenset({
        "airloophvac:zonesplitter", "airloophvac:supplyplenum",
    }),
    "airloophvac:returnpath": frozenset({
        "airloophvac:zonemixer", "airloophvac:returnplenum",
    }),
}

_OA_ALLOWED_TYPES = frozenset({
    "outdoorair:mixer",
    "heatexchanger:airtoair:sensibleandlatent",
})


def _one_complete_projection(
    model: ModelIR, object_ref: ObjectRef,
) -> CompoundFlowProjection | None:
    rows = model.projections_for(object_ref.object_id)
    return rows[0] if len(rows) == 1 and rows[0].complete else None


def _unique_supported_objects(
    model: ModelIR,
    allowed_types: frozenset[str],
) -> tuple[tuple[ObjectRef, ...], bool]:
    """Return every addressable complete object and domain completeness."""

    occurrences = Counter(
        (obj.normalized_object_type, obj.normalized_name)
        for obj in model.objects if obj.normalized_object_type in allowed_types
    )
    rows: list[ObjectRef] = []
    complete = True
    for obj in model.objects:
        if obj.normalized_object_type not in allowed_types:
            continue
        if (
            not obj.normalized_name
            or occurrences[(obj.normalized_object_type, obj.normalized_name)] != 1
            or _one_complete_projection(model, obj) is None
        ):
            complete = False
            continue
        rows.append(obj)
    return tuple(rows), complete


def _resolved_supported_members(
    model: ModelIR,
    members: tuple,
    allowed_types: frozenset[str],
) -> tuple[ObjectRef | None, ...]:
    rows: list[ObjectRef | None] = []
    for member in members:
        if canonical(member.object_type) not in allowed_types:
            rows.append(None)
            continue
        resolved = model.resolve_identity(member.object_type, member.object_name)
        rows.append(resolved[0] if len(resolved) == 1 else None)
    return tuple(rows)


def _projection_reads(projections: tuple[CompoundFlowProjection, ...]) -> tuple[str, ...]:
    return tuple(sorted({
        variable
        for projection in projections
        for variable in (
            f"flow-projection:{projection.projection_id}",
            *(
                f"field:{port.field_ref.field_id}"
                for transition in projection.transitions
                for port in (*transition.inlet_ports, *transition.outlet_ports)
            ),
        )
    }))


def _acyclic(nodes: set[str], edges: set[tuple[str, str]]) -> bool:
    indegree = {node: 0 for node in nodes}
    outgoing: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        if right not in outgoing[left]:
            outgoing[left].add(right)
            indegree[right] += 1
    ready = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for target in outgoing[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return visited == len(nodes)


def _reachable(seed: str, adjacency: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [seed]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(sorted(adjacency.get(node, set()) - seen, reverse=True))
    return seen


def _airpath_graph_closed(
    model: ModelIR,
    path: AirPathRelation,
    objects: tuple[ObjectRef, ...],
) -> bool:
    allowed = _AIRPATH_ALLOWED_TYPES.get(path.object_ref.normalized_object_type)
    if (
        allowed is None
        or not objects
        or len(objects) != len(path.members)
        or len({obj.object_id for obj in objects}) != len(objects)
        or any(obj.normalized_object_type not in allowed for obj in objects)
    ):
        return False
    projections = tuple(_one_complete_projection(model, obj) for obj in objects)
    if any(projection is None for projection in projections):
        return False
    complete = tuple(
        projection for projection in projections if projection is not None
    )
    if any(len(projection.primary_transitions) != 1 for projection in complete):
        return False
    edges: set[tuple[str, str]] = set()
    edge_sets: list[frozenset[tuple[str, str]]] = []
    nodes: set[str] = set()
    for projection in complete:
        transition = projection.primary_transitions[0]
        current = frozenset(
            (left.normalized_node_name, right.normalized_node_name)
            for left in transition.inlet_ports
            for right in transition.outlet_ports
        )
        if not current or any(not left or not right or left == right for left, right in current):
            return False
        if any(current == prior for prior in edge_sets):
            return False
        edge_sets.append(current)
        edges.update(current)
        nodes.update(node for edge in current for node in edge)
    boundary = path.boundary_field.normalized_value
    if not boundary or boundary not in nodes or not _acyclic(nodes, edges):
        return False
    outgoing: dict[str, set[str]] = {node: set() for node in nodes}
    incoming: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        outgoing[left].add(right)
        incoming[right].add(left)
    supply = path.object_ref.normalized_object_type == "airloophvac:supplypath"
    if supply:
        sources = {node for node in nodes if not incoming[node]}
        return sources == {boundary} and _reachable(boundary, outgoing) == nodes
    sinks = {node for node in nodes if not outgoing[node]}
    return sinks == {boundary} and _reachable(boundary, incoming) == nodes


def _airpath_scope_supported(model: ModelIR, path: AirPathRelation) -> bool:
    allowed = _AIRPATH_ALLOWED_TYPES.get(path.object_ref.normalized_object_type)
    if (
        allowed is None
        or not path.reference_shape_complete
        or not path.boundary_field.normalized_value
        or not path.members
        or any(canonical(member.object_type) not in allowed for member in path.members)
    ):
        return False
    _, universe_complete = _unique_supported_objects(model, allowed)
    if not universe_complete:
        return False
    for member in path.members:
        resolved = model.resolve_identity(member.object_type, member.object_name)
        if len(resolved) == 1 and _one_complete_projection(model, resolved[0]) is None:
            return False
    return True


def _airpath_replacements(
    model: ModelIR,
    path: AirPathRelation,
) -> tuple[tuple[int, ObjectRef], ...]:
    allowed = _AIRPATH_ALLOWED_TYPES[path.object_ref.normalized_object_type]
    universe, _ = _unique_supported_objects(model, allowed)
    current = _resolved_supported_members(model, path.members, allowed)
    rows: list[tuple[int, ObjectRef]] = []
    for index, member in enumerate(path.members):
        other_ids = {
            obj.object_id for offset, obj in enumerate(current)
            if offset != index and obj is not None
        }
        for target in universe:
            if target.object_id in other_ids:
                continue
            replaced = list(current)
            replaced[index] = target
            if any(obj is None for obj in replaced):
                continue
            assigned = tuple(obj for obj in replaced if obj is not None)
            if _airpath_graph_closed(model, path, assigned):
                rows.append((member.ordinal, target))
    return tuple(sorted(
        rows, key=lambda row: (row[0], row[1].object_id),
    ))


def _eval_airpath_typed_member(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for path in model.air_paths:
        if not _airpath_scope_supported(model, path):
            continue
        allowed = _AIRPATH_ALLOWED_TYPES[path.object_ref.normalized_object_type]
        current = _resolved_supported_members(model, path.members, allowed)
        if all(obj is not None for obj in current) and _airpath_graph_closed(
            model, path, tuple(obj for obj in current if obj is not None),
        ):
            continue
        alternatives = _airpath_replacements(model, path)
        member_fields = tuple(
            field for member in path.members
            for field in (member.type_field, member.name_field)
        )
        universe, universe_complete = _unique_supported_objects(model, allowed)
        status = "COMPLETE" if universe_complete else "INCOMPLETE_UNSUPPORTED"
        factor = f"air-path:{path.object_ref.object_id}"
        projections = tuple(
            projection for obj in universe
            for projection in model.projections_for(obj.object_id)
        )
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(path.relation_id,),
            field_refs=(path.boundary_field, *member_fields),
            observed=_facts(
                members="|".join(
                    f"{member.object_type}@{member.object_name}"
                    for member in path.members
                ),
                relation="compound_topology_not_closed",
            ),
            expected=_facts(
                candidate_domain_status=status,
                compatible_replacements="|".join(
                    f"{ordinal}@{target.object_id}"
                    for ordinal, target in alternatives
                ),
                relation="closed_member_induced_flow_graph",
            ),
            evidence=_facts(
                boundary=path.boundary_field.raw_value,
                candidate_universe=len(universe),
            ),
            read_variables=(
                f"field:{path.boundary_field.field_id}",
                *(f"field:{field.field_id}" for field in member_fields),
                *_projection_reads(projections),
            ),
            latent_factors=(factor,),
            message="AirPath declared members do not close the supported compound topology.",
        ))
    return tuple(rows)


def _oa_projection_parts(
    model: ModelIR, object_ref: ObjectRef,
) -> tuple[CompoundFlowProjection, object, object] | None:
    projection = _one_complete_projection(model, object_ref)
    if projection is None:
        return None
    primary = projection.primary_transitions
    auxiliary = tuple(
        row for row in projection.transitions if row not in primary
    )
    if len(primary) != 1 or len(auxiliary) != 1:
        return None
    return projection, primary[0], auxiliary[0]


def _oa_chain_closed(
    model: ModelIR,
    path: EquipmentPathRelation,
    objects: tuple[ObjectRef, ...],
) -> bool:
    if (
        path.context is not OutdoorAirSystemContext.NORMAL
        or not objects
        or len(objects) != len(path.members)
        or len({obj.object_id for obj in objects}) != len(objects)
        or any(obj.normalized_object_type not in _OA_ALLOWED_TYPES for obj in objects)
        or len(path.controller_node_fields) != 4
    ):
        return False
    parts = tuple(_oa_projection_parts(model, obj) for obj in objects)
    if any(part is None for part in parts):
        return False
    resolved_parts = tuple(part for part in parts if part is not None)
    mixer_indexes = tuple(
        index for index, obj in enumerate(objects)
        if obj.normalized_object_type == "outdoorair:mixer"
    )
    if mixer_indexes != (len(objects) - 1,):
        return False
    primary = tuple(part[1] for part in resolved_parts)
    mixer_primary = primary[-1]
    mixer_auxiliary = resolved_parts[-1][2]
    relief, return_air, mixed, outdoor = (
        field.normalized_value for field in path.controller_node_fields
    )
    if (
        primary[0].inlet_ports[0].normalized_node_name != outdoor
        or mixer_primary.outlet_ports[0].normalized_node_name != mixed
        or mixer_auxiliary.inlet_ports[0].normalized_node_name != return_air
        or mixer_auxiliary.outlet_ports[0].normalized_node_name != relief
    ):
        return False
    if any(
        left.outlet_ports[0].normalized_node_name
        != right.inlet_ports[0].normalized_node_name
        for left, right in zip(primary, primary[1:])
    ):
        return False
    auxiliary = tuple(part[2] for part in reversed(resolved_parts))
    return not any(
        left.outlet_ports[0].normalized_node_name
        != right.inlet_ports[0].normalized_node_name
        for left, right in zip(auxiliary, auxiliary[1:])
    )


def _oa_scope_supported(model: ModelIR, path: EquipmentPathRelation) -> bool:
    if (
        path.context is not OutdoorAirSystemContext.NORMAL
        or path.equipment_list_ref is None
        or not path.reference_shape_complete
        or not path.members
        or len(path.members) > 7
        or len(path.controller_node_fields) != 4
        or any(canonical(member.object_type) not in _OA_ALLOWED_TYPES for member in path.members)
    ):
        return False
    _, universe_complete = _unique_supported_objects(model, _OA_ALLOWED_TYPES)
    if not universe_complete:
        return False
    for member in path.members:
        resolved = model.resolve_identity(member.object_type, member.object_name)
        if len(resolved) == 1 and _oa_projection_parts(model, resolved[0]) is None:
            return False
    return True


def _oa_alternatives(
    model: ModelIR,
    path: EquipmentPathRelation,
) -> tuple[tuple[tuple[int, ObjectRef], ...], tuple[tuple[int, ...], ...]]:
    universe, _ = _unique_supported_objects(model, _OA_ALLOWED_TYPES)
    current = _resolved_supported_members(model, path.members, _OA_ALLOWED_TYPES)
    replacements: list[tuple[int, ObjectRef]] = []
    for index, member in enumerate(path.members):
        other_ids = {
            obj.object_id for offset, obj in enumerate(current)
            if offset != index and obj is not None
        }
        for target in universe:
            if target.object_id in other_ids:
                continue
            replaced = list(current)
            replaced[index] = target
            if any(obj is None for obj in replaced):
                continue
            assigned = tuple(obj for obj in replaced if obj is not None)
            if _oa_chain_closed(model, path, assigned):
                replacements.append((member.ordinal, target))
    valid_orders: list[tuple[int, ...]] = []
    if all(obj is not None for obj in current):
        indexed = tuple(zip(path.members, current))
        for order in permutations(indexed):
            ordinals = tuple(member.ordinal for member, _ in order)
            if ordinals == tuple(member.ordinal for member in path.members):
                continue
            assigned = tuple(obj for _, obj in order if obj is not None)
            if _oa_chain_closed(model, path, assigned):
                valid_orders.append(ordinals)
    return (
        tuple(sorted(replacements, key=lambda row: (row[0], row[1].object_id))),
        tuple(sorted(set(valid_orders))),
    )


def _eval_oa_equipment_path(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for path in model.equipment_paths:
        if not _oa_scope_supported(model, path):
            continue
        current = _resolved_supported_members(model, path.members, _OA_ALLOWED_TYPES)
        if all(obj is not None for obj in current) and _oa_chain_closed(
            model, path, tuple(obj for obj in current if obj is not None),
        ):
            continue
        replacements, orders = _oa_alternatives(model, path)
        # The EquipmentList constraint edits only declared type/name/order.
        # A primary/auxiliary inconsistency with no closing list alternative
        # is not evidence that one of those fields is wrong, so abstain.
        if not replacements and not orders:
            continue
        universe, universe_complete = _unique_supported_objects(
            model, _OA_ALLOWED_TYPES,
        )
        member_fields = tuple(
            field for member in path.members
            for field in (member.type_field, member.name_field)
        )
        factor = f"oa-equipment-path:{path.system_ref.object_id}"
        projections = tuple(
            projection for obj in universe
            for projection in model.projections_for(obj.object_id)
        )
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(path.relation_id,),
            field_refs=(*member_fields, *path.controller_node_fields),
            observed=_facts(
                order="|".join(member.object_name for member in path.members),
                relation="compound_primary_or_auxiliary_not_closed",
            ),
            expected=_facts(
                candidate_domain_status=(
                    "COMPLETE" if universe_complete else "INCOMPLETE_UNSUPPORTED"
                ),
                compatible_orders="|".join(
                    ",".join(str(ordinal) for ordinal in order)
                    for order in orders
                ),
                compatible_replacements="|".join(
                    f"{ordinal}@{target.object_id}"
                    for ordinal, target in replacements
                ),
                relation="closed_primary_and_reverse_auxiliary_traversals",
            ),
            evidence=_facts(
                controller=path.outdoor_air_controller_ref.object_id
                if path.outdoor_air_controller_ref is not None else "",
                candidate_universe=len(universe),
            ),
            read_variables=(
                *(f"field:{field.field_id}" for field in member_fields),
                *(f"field:{field.field_id}" for field in path.controller_node_fields),
                *_projection_reads(projections),
            ),
            latent_factors=(factor,),
            message=(
                "Outdoor-air EquipmentList does not close both the primary "
                "and auxiliary compound traversals."
            ),
        ))
    return tuple(rows)


def _top_zone_list(
    relation: ZoneEquipmentRelation,
) -> tuple[str, bool] | None:
    if not relation.ranked_list_evidence:
        return None
    top_score = relation.ranked_list_evidence[0].score
    if top_score <= 0:
        return None
    winners = tuple(
        row for row in relation.ranked_list_evidence if row.score == top_score
    )
    if len(winners) != 1:
        return None
    return winners[0].candidate_id, winners[0].complete


def _zone_factor(relation: ZoneEquipmentRelation) -> str:
    return f"zone-equipment-factor:{relation.connection_ref.object_id}"


def _zone_list_by_id(
    model: ModelIR, relation_id: str,
) -> ZoneEquipmentListRelation | None:
    return next(
        (row for row in model.zone_equipment_lists if row.relation_id == relation_id),
        None,
    )


def _zone_list_evidence(
    relation: ZoneEquipmentRelation,
    zone_list: ZoneEquipmentListRelation,
) -> EvidenceScore | None:
    return next(
        (
            row for row in relation.ranked_list_evidence
            if row.candidate_id == zone_list.relation_id
        ),
        None,
    )


def _structural_zone_list(
    model: ModelIR,
    relation: ZoneEquipmentRelation,
) -> tuple[ZoneEquipmentListRelation, tuple[FieldRef, ...]] | None:
    """用完整的一对一 ownership reciprocity 识别唯一 orphan list。"""

    if len(model.zone_relations) != len(model.zone_equipment_lists) or any(
        row.declared_list_ref is None for row in model.zone_relations
    ):
        return None
    owners: dict[str, list[ZoneEquipmentRelation]] = {}
    for row in model.zone_relations:
        assert row.declared_list_ref is not None
        owners.setdefault(row.declared_list_ref.object_id, []).append(row)
    unowned = tuple(
        row for row in model.zone_equipment_lists
        if row.object_ref.object_id not in owners
    )
    duplicated = tuple(
        rows for rows in owners.values() if len(rows) > 1
    )
    if (
        len(unowned) != 1 or len(duplicated) != 1
        or len(duplicated[0]) != 2
        or any(
            len(rows) != 1
            for rows in owners.values() if rows is not duplicated[0]
        )
        or relation not in duplicated[0]
    ):
        return None
    declared = relation.declared_list_ref
    assert declared is not None
    declared_list = next(
        (
            row for row in model.zone_equipment_lists
            if row.object_ref.object_id == declared.object_id
        ),
        None,
    )
    if declared_list is None:
        return None
    independently_valid = []
    for owner in duplicated[0]:
        evidence = _zone_list_evidence(owner, declared_list)
        if evidence is not None and evidence.score > 0 and evidence.complete:
            independently_valid.append(owner)
    if (
        len(independently_valid) != 1
        or independently_valid[0].relation_id == relation.relation_id
    ):
        return None
    return unowned[0], tuple(
        owner.declared_list_field for owner in duplicated[0]
    )


def _intended_zone_list(
    model: ModelIR,
    relation: ZoneEquipmentRelation,
) -> tuple[ZoneEquipmentListRelation, tuple[FieldRef, ...]] | None:
    top = _top_zone_list(relation)
    if top is not None and top[1]:
        intended = _zone_list_by_id(model, top[0])
        if intended is not None:
            return intended, ()
    structural = _structural_zone_list(model, relation)
    if structural is not None:
        return structural
    if (
        relation.declared_list_ref is None
        or len(model.zone_relations) != len(model.zone_equipment_lists)
        or any(row.declared_list_ref is None for row in model.zone_relations)
    ):
        return None
    owner_ids = []
    for row in model.zone_relations:
        assert row.declared_list_ref is not None
        owner_ids.append(row.declared_list_ref.object_id)
    list_ids = {row.object_ref.object_id for row in model.zone_equipment_lists}
    if len(set(owner_ids)) != len(owner_ids) or set(owner_ids) != list_ids:
        return None
    intended = next(
        (
            row for row in model.zone_equipment_lists
            if row.object_ref.object_id == relation.declared_list_ref.object_id
        ),
        None,
    )
    if intended is None:
        return None
    evidence = _zone_list_evidence(relation, intended)
    if evidence is None or not evidence.complete:
        return None
    return intended, ()


def _eval_zone_list_ownership(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for relation in model.zone_relations:
        if not relation.evidence_complete:
            continue
        selection = _intended_zone_list(model, relation)
        if selection is None:
            continue
        intended, structural_fields = selection
        if (
            relation.declared_list_ref is not None
            and relation.declared_list_ref.object_id == intended.object_ref.object_id
        ):
            continue
        factor = _zone_factor(relation)
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(relation.relation_id, intended.relation_id),
            field_refs=(relation.declared_list_field,),
            observed=_facts(declared_list=relation.declared_list_field.raw_value),
            expected=_facts(intended_list=intended.object_ref.raw_name),
            evidence=_facts(
                score=next(
                    (
                        row.score for row in relation.ranked_list_evidence
                        if row.candidate_id == intended.relation_id
                    ),
                    0,
                ),
                structural_ownership=bool(structural_fields),
                evidence_fields="|".join(
                    next(
                        (
                            row.evidence_field_ids
                            for row in relation.ranked_list_evidence
                            if row.candidate_id == intended.relation_id
                        ),
                        (),
                    )
                ),
            ),
            read_variables=(
                f"field:{relation.declared_list_field.field_id}",
                intended.relation_id,
                *(f"field:{field.field_id}" for field in relation.boundary_node_fields),
                *(f"field:{field.field_id}" for field in structural_fields),
            ),
            latent_factors=(factor,),
            message="Zone EquipmentConnections declares a list inconsistent with explicit zone-side ports.",
        ))
    return tuple(rows)


def _zone_ports(model: ModelIR, object_ref: ObjectRef) -> tuple[PortRef, ...]:
    return tuple(
        port for port in model.ports_for(object_ref.object_id)
        if str(port.zone_side_role) != "NONE"
    )


def _zone_match_nodes(
    model: ModelIR,
    relation: ZoneEquipmentRelation,
    object_ref: ObjectRef,
) -> frozenset[str]:
    boundary = {
        field.normalized_value for field in relation.boundary_node_fields
        if field.normalized_value
    }
    return frozenset(
        port.normalized_node_name for port in _zone_ports(model, object_ref)
        if port.normalized_node_name in boundary
    )


def _is_zone_equipment_candidate(object_ref: ObjectRef) -> bool:
    """限制为 EnergyPlus ZoneHVAC EquipmentList 可承载的主类。

    AirLoop distribution containers may expose a zone-side node, but they are not
    legal ZoneHVAC:EquipmentList members and therefore cannot enter this domain.
    """

    return (
        object_ref.normalized_object_type.startswith("zonehvac:")
        or object_ref.normalized_object_type == "fan:zoneexhaust"
    )


def _eval_zone_typed_member(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    occupied_counts = Counter(
        resolved[0].object_id
        for zone_list in model.zone_equipment_lists
        for member in zone_list.members
        for resolved in (
            model.resolve_identity(member.object_type, member.object_name),
        )
        if len(resolved) == 1
    )
    for relation in model.zone_relations:
        if not relation.evidence_complete:
            continue
        selection = _intended_zone_list(model, relation)
        if selection is None:
            continue
        intended, structural_fields = selection
        factor = _zone_factor(relation)
        for member in intended.members:
            current = model.resolve_identity(member.object_type, member.object_name)
            if len(current) == 1:
                # A resolved member without an exact zone-side port rule is
                # outside this constraint's applicability.  Other explicitly
                # witnessed members may still prove list ownership, but this
                # member must remain untouched rather than being guessed.
                if not _zone_ports(model, current[0]):
                    continue
                if _zone_match_nodes(model, relation, current[0]):
                    continue
            candidates = tuple(
                obj for obj in model.objects
                if _is_zone_equipment_candidate(obj)
                and occupied_counts[obj.object_id] - (
                    1 if len(current) == 1 and current[0].object_id == obj.object_id
                    else 0
                ) == 0
                and _zone_match_nodes(model, relation, obj)
            )
            if not candidates:
                continue
            rows.append(_violation(
                spec,
                scope_ids=(factor,),
                relation_ids=(relation.relation_id, intended.relation_id),
                field_refs=(member.type_field, member.name_field),
                observed=_facts(
                    object_type=member.object_type,
                    object_name=member.object_name,
                ),
                expected=_facts(
                    compatible_object_ids="|".join(obj.object_id for obj in candidates),
                ),
                evidence=_facts(
                    boundary_nodes="|".join(sorted({
                        field.normalized_value
                        for field in relation.boundary_node_fields
                        if field.normalized_value
                    })),
                ),
                read_variables=(
                    f"field:{member.type_field.field_id}",
                    f"field:{member.name_field.field_id}",
                    *(f"zone-ports:{obj.object_id}" for obj in candidates),
                    intended.relation_id,
                    relation.relation_id,
                    *(f"field:{field.field_id}" for field in structural_fields),
                ),
                latent_factors=(factor,),
                message="Zone EquipmentList typed member lacks the intended zone boundary evidence.",
                suffix=str(member.ordinal),
            ))
    return tuple(rows)


def _eval_controller_ownership(
    model: ModelIR, spec: ConstraintSpec,
) -> tuple[Violation, ...]:
    rows: list[Violation] = []
    for relation in model.controller_relations:
        if not relation.controller_list_field.raw_value.strip():
            continue
        if relation.controller_list_ref is not None:
            continue
        factor = f"controller-ownership:{relation.owner_ref.object_id}"
        rows.append(_violation(
            spec,
            scope_ids=(factor,),
            relation_ids=(relation.relation_id,),
            field_refs=(relation.controller_list_field,),
            observed=_facts(controller_list=relation.controller_list_field.raw_value),
            expected=_facts(action="diagnostic_only"),
            read_variables=(f"field:{relation.controller_list_field.field_id}",),
            latent_factors=(factor,),
            message="AirLoop controller-list ownership does not resolve uniquely.",
        ))
    return tuple(rows)


Evaluator: TypeAlias = Callable[[ModelIR, ConstraintSpec], tuple[Violation, ...]]


_EVALUATORS: dict[str, Evaluator] = {
    "branch_typed_identity": _eval_branch_typed_identity,
    "branch_endpoint": _eval_branch_endpoint,
    "branch_continuity": _eval_branch_continuity,
    "branch_duplicate_member": _eval_branch_duplicate_member,
    "loop_parallel_set": _eval_loop_parallel_set,
    "loop_branchlist_set": _eval_loop_branchlist_set,
    "loop_branchlist_boundary": _eval_loop_branchlist_boundary,
    "loop_side_ownership": _eval_loop_side_ownership,
    "connector_typed_member": _eval_connector_typed_member,
    "airpath_typed_member": _eval_airpath_typed_member,
    "oa_equipment_path": _eval_oa_equipment_path,
    "zone_list_ownership": _eval_zone_list_ownership,
    "zone_typed_member": _eval_zone_typed_member,
    "controller_ownership": _eval_controller_ownership,
}


def _constraint_applicability(
    model: ModelIR,
    spec: ConstraintSpec,
) -> tuple[bool, str]:
    """报告 evaluator 在当前 IR 中是否有完整、受支持的实际 scope。"""

    key = spec.evaluator_key
    if key == "branch_typed_identity":
        pairs = _all_port_pairs(model)
        applicable = any(
            any(pair.nodes == (
                member.inlet_field.normalized_value,
                member.outlet_field.normalized_value,
            ) for pair in pairs)
            for branch in model.branches for member in branch.members
        )
        return applicable, (
            "evaluated" if applicable else
            "unsupported_or_absent_port_scope" if model.branches else
            "no_applicable_scope"
        )
    if key == "branch_endpoint":
        applicable = any(
            len(identities) == 1 and _select_expected_pair(
                _port_pairs(model, identities[0]),
                (
                    member.inlet_field.normalized_value,
                    member.outlet_field.normalized_value,
                ),
            ) is not None
            for branch in model.branches
            for member in branch.members
            for identities in (_member_identity(model, member),)
        )
        return applicable, (
            "evaluated" if applicable else
            "unsupported_or_absent_port_scope" if model.branches else
            "no_applicable_scope"
        )
    if key in {"branch_continuity", "branch_duplicate_member"}:
        applicable = any(len(branch.members) >= 2 for branch in model.branches)
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    if key == "loop_parallel_set":
        applicable = any(
            pair.splitter is not None and pair.mixer is not None
            for pair in model.connector_pairs
        )
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    if key in {"loop_branchlist_set", "loop_branchlist_boundary"}:
        applicable = any(
            branch_list is not None
            and pair is not None
            and _connector_needed_set(pair) is not None
            for side in model.loop_sides
            for branch_list, pair in (_loop_relations(model, side),)
        )
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    if key == "loop_side_ownership":
        applicable = any(
            _compatible_loop_pairs(model, side) for side in model.loop_sides
        )
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    if key == "connector_typed_member":
        applicable = any(pair.declared_members for pair in model.connector_pairs)
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    if key == "airpath_typed_member":
        if not model.air_paths:
            return False, "no_applicable_scope"
        applicable = any(_airpath_scope_supported(model, path) for path in model.air_paths)
        return applicable, (
            "evaluated" if applicable else "incomplete_compound_flow_scope"
        )
    if key == "oa_equipment_path":
        if not model.equipment_paths:
            return False, "no_applicable_scope"
        applicable = any(
            _oa_scope_supported(model, path) for path in model.equipment_paths
        )
        if applicable:
            return True, "evaluated"
        if all(
            path.context is OutdoorAirSystemContext.DEDICATED
            for path in model.equipment_paths
        ):
            return False, "dedicated_outdoor_air_context"
        return applicable, (
            "evaluated" if applicable else "incomplete_compound_flow_scope"
        )
    if key in {"zone_list_ownership", "zone_typed_member"}:
        if not model.zone_relations:
            return False, "no_applicable_scope"
        applicable = any(
            relation.evidence_complete for relation in model.zone_relations
        )
        return applicable, (
            "evaluated" if applicable else "incomplete_evidence_domain"
        )
    if key == "controller_ownership":
        applicable = bool(model.controller_relations)
        return applicable, "evaluated" if applicable else "no_applicable_scope"
    return False, "no_applicable_scope"


def scan_ir(
    model: ModelIR,
    *,
    registry: ConstraintRegistry | None = None,
) -> ScanResult:
    """对一个 canonical snapshot 执行全部 active constraints。"""

    active = registry or production_registry()
    violations: list[Violation] = []
    applicability: list[ApplicabilityRecord] = []
    for spec in active.specs:
        evaluator = _EVALUATORS.get(spec.evaluator_key)
        if evaluator is None:
            applicability.append(ApplicabilityRecord(
                constraint_id=spec.constraint_id,
                scope_id="model",
                applied=False,
                reason="evaluator_not_registered",
            ))
            continue
        applied, reason = _constraint_applicability(model, spec)
        if not applied:
            applicability.append(ApplicabilityRecord(
                constraint_id=spec.constraint_id,
                scope_id="model",
                applied=False,
                reason=reason,
            ))
            continue
        produced = evaluator(model, spec)
        violations.extend(produced)
        applicability.append(ApplicabilityRecord(
            constraint_id=spec.constraint_id,
            scope_id="model",
            applied=True,
            reason=reason,
        ))
    return ScanResult(
        model=model,
        violations=tuple(sorted(violations, key=lambda row: row.violation_id)),
        applicability=tuple(applicability),
    )


def scan_model(
    document: IDFDocument,
    idd: IDDSchema,
    *,
    registry: ConstraintRegistry | None = None,
) -> ScanResult:
    """Public target-free boundary：只接收 faulty/current IDF 与 exact IDD。"""

    return scan_ir(build_model_ir(document, idd), registry=registry)


__all__ = [
    "ApplicabilityRecord",
    "ScanResult",
    "Violation",
    "ViolationSeverity",
    "scan_ir",
    "scan_model",
]
