"""Build immutable compound-flow projections above exact atomic PortRef facts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from idfrepair.io.idf import canonical
from idfrepair.semantic_graph_v2.ir import (
    CompoundFlowProjection,
    FlowTopologyForm,
    FlowStreamRole,
    FlowTransition,
    FlowTraversalRole,
    FluidMedium,
    ObjectRef,
    PortRef,
    PortRole,
    ProjectionApplicability,
)


@dataclass(frozen=True, slots=True)
class TransitionProjectionRule:
    """Select exact atomic port rules for one directed semantic transition."""

    stream: FlowStreamRole
    traversal_role: FlowTraversalRole
    inlet_rule_ids: tuple[str, ...]
    outlet_rule_ids: tuple[str, ...]
    minimum_inlets: int = 1
    maximum_inlets: int | None = 1
    minimum_outlets: int = 1
    maximum_outlets: int | None = 1
    medium: FluidMedium = FluidMedium.AIR


@dataclass(frozen=True, slots=True)
class FlowProjectionRule:
    """Bind an official object/version to one compound topology form."""

    rule_id: str
    version: str
    object_type: str
    topology_form: FlowTopologyForm
    transitions: tuple[TransitionProjectionRule, ...]


@dataclass(frozen=True, slots=True)
class FlowProjectionRegistry:
    """Store version-bound projection rules without model-specific exceptions."""

    rules: tuple[FlowProjectionRule, ...]

    def __post_init__(self) -> None:
        keys = tuple(
            (canonical(rule.object_type), _normalize_version(rule.version))
            for rule in self.rules
        )
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_flow_projection_rule")

    def rule_for(
        self, object_type: str, version: str,
    ) -> FlowProjectionRule | None:
        """Return the one exact object/version rule, if admitted."""

        key = (canonical(object_type), _normalize_version(version))
        return next((
            rule for rule in self.rules
            if (canonical(rule.object_type), _normalize_version(rule.version)) == key
        ), None)

    def has_object_type(self, object_type: str) -> bool:
        """Report whether a compound rule owns this type in any version."""

        key = canonical(object_type)
        return any(canonical(rule.object_type) == key for rule in self.rules)


def _normalize_version(value: str) -> str:
    parts = value.strip().split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _version_tag(version: str) -> str:
    return _normalize_version(version).replace(".", "_")


def _compound_rules_for(version: str) -> tuple[FlowProjectionRule, ...]:
    """Materialize the independently audited rule set for one IDD version."""

    tag = _version_tag(version)
    return (
        FlowProjectionRule(
            rule_id=f"flow.airpath.zonesplitter.e{tag}.v1",
            version=version,
            object_type="AirLoopHVAC:ZoneSplitter",
            topology_form=FlowTopologyForm.SPLIT,
            transitions=(TransitionProjectionRule(
                stream=FlowStreamRole.DISTRIBUTION,
                traversal_role=FlowTraversalRole.PRIMARY,
                inlet_rule_ids=(f"airpath.splitter.inlet.e{tag}.v1",),
                outlet_rule_ids=(f"airpath.splitter.outlets.e{tag}.v1",),
                maximum_outlets=None,
            ),),
        ),
        FlowProjectionRule(
            rule_id=f"flow.airpath.supplyplenum.e{tag}.v1",
            version=version,
            object_type="AirLoopHVAC:SupplyPlenum",
            topology_form=FlowTopologyForm.SPLIT,
            transitions=(TransitionProjectionRule(
                stream=FlowStreamRole.DISTRIBUTION,
                traversal_role=FlowTraversalRole.PRIMARY,
                inlet_rule_ids=(f"airpath.supplyplenum.inlet.e{tag}.v1",),
                outlet_rule_ids=(f"airpath.supplyplenum.outlets.e{tag}.v1",),
                maximum_outlets=None,
            ),),
        ),
        FlowProjectionRule(
            rule_id=f"flow.airpath.zonemixer.e{tag}.v1",
            version=version,
            object_type="AirLoopHVAC:ZoneMixer",
            topology_form=FlowTopologyForm.MERGE,
            transitions=(TransitionProjectionRule(
                stream=FlowStreamRole.RETURN,
                traversal_role=FlowTraversalRole.PRIMARY,
                inlet_rule_ids=(f"airpath.zonemixer.inlets.e{tag}.v1",),
                outlet_rule_ids=(f"airpath.zonemixer.outlet.e{tag}.v1",),
                maximum_inlets=None,
            ),),
        ),
        FlowProjectionRule(
            rule_id=f"flow.airpath.returnplenum.e{tag}.v1",
            version=version,
            object_type="AirLoopHVAC:ReturnPlenum",
            topology_form=FlowTopologyForm.MERGE,
            transitions=(TransitionProjectionRule(
                stream=FlowStreamRole.RETURN,
                traversal_role=FlowTraversalRole.PRIMARY,
                inlet_rule_ids=(f"airpath.returnplenum.inlets.e{tag}.v1",),
                outlet_rule_ids=(f"airpath.returnplenum.outlet.e{tag}.v1",),
                maximum_inlets=None,
            ),),
        ),
        FlowProjectionRule(
            rule_id=f"flow.oa.mixer.e{tag}.v1",
            version=version,
            object_type="OutdoorAir:Mixer",
            topology_form=FlowTopologyForm.COUPLED_MULTI_STREAM,
            transitions=(
                TransitionProjectionRule(
                    stream=FlowStreamRole.OUTDOOR_TO_MIXED,
                    traversal_role=FlowTraversalRole.PRIMARY,
                    inlet_rule_ids=(f"oa.mixer.outdoor.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.mixer.mixed.outlet.e{tag}.v1",),
                ),
                TransitionProjectionRule(
                    stream=FlowStreamRole.RETURN_TO_RELIEF,
                    traversal_role=FlowTraversalRole.AUXILIARY,
                    inlet_rule_ids=(f"oa.mixer.return.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.mixer.relief.outlet.e{tag}.v1",),
                ),
            ),
        ),
        FlowProjectionRule(
            rule_id=f"flow.oa.hx.sensiblelatent.e{tag}.v1",
            version=version,
            object_type="HeatExchanger:AirToAir:SensibleAndLatent",
            topology_form=FlowTopologyForm.MULTI_CIRCUIT,
            transitions=(
                TransitionProjectionRule(
                    stream=FlowStreamRole.SUPPLY,
                    traversal_role=FlowTraversalRole.PRIMARY,
                    inlet_rule_ids=(f"oa.hx.supply.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.hx.supply.outlet.e{tag}.v1",),
                ),
                TransitionProjectionRule(
                    stream=FlowStreamRole.EXHAUST,
                    traversal_role=FlowTraversalRole.AUXILIARY,
                    inlet_rule_ids=(f"oa.hx.exhaust.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.hx.exhaust.outlet.e{tag}.v1",),
                ),
            ),
        ),
        FlowProjectionRule(
            rule_id=f"flow.oa.hx.flatplate.e{tag}.v1",
            version=version,
            object_type="HeatExchanger:AirToAir:FlatPlate",
            topology_form=FlowTopologyForm.MULTI_CIRCUIT,
            transitions=(
                TransitionProjectionRule(
                    stream=FlowStreamRole.SUPPLY,
                    traversal_role=FlowTraversalRole.PRIMARY,
                    inlet_rule_ids=(f"oa.hx.flatplate.supply.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.hx.flatplate.supply.outlet.e{tag}.v1",),
                ),
                TransitionProjectionRule(
                    stream=FlowStreamRole.SECONDARY,
                    traversal_role=FlowTraversalRole.AUXILIARY,
                    inlet_rule_ids=(f"oa.hx.flatplate.secondary.inlet.e{tag}.v1",),
                    outlet_rule_ids=(f"oa.hx.flatplate.secondary.outlet.e{tag}.v1",),
                ),
            ),
        ),
    )


PRODUCTION_FLOW_PROJECTION_REGISTRY = FlowProjectionRegistry(
    (*_compound_rules_for("22.1"), *_compound_rules_for("24.1")),
)


def _cardinality_complete(
    count: int,
    minimum: int,
    maximum: int | None,
) -> bool:
    return count >= minimum and (maximum is None or count <= maximum)


def _build_compound_projection(
    object_ref: ObjectRef,
    ports: tuple[PortRef, ...],
    rule: FlowProjectionRule,
    extraction_issues: tuple[str, ...],
) -> CompoundFlowProjection:
    transitions: list[FlowTransition] = []
    all_complete = True
    projection_issues: list[str] = []
    if any(issue.startswith("extensible_port_blank_member:") for issue in extraction_issues):
        projection_issues.append("blank_extensible_port")
    for ordinal, transition_rule in enumerate(rule.transitions, start=1):
        inlets = tuple(
            port for port in ports
            if port.rule_id in transition_rule.inlet_rule_ids
            and port.role is PortRole.INLET
            and port.medium is transition_rule.medium
        )
        outlets = tuple(
            port for port in ports
            if port.rule_id in transition_rule.outlet_rule_ids
            and port.role is PortRole.OUTLET
            and port.medium is transition_rule.medium
        )
        nodes = tuple(
            port.normalized_node_name for port in (*inlets, *outlets)
        )
        cardinality_complete = (
            _cardinality_complete(
                len(inlets),
                transition_rule.minimum_inlets,
                transition_rule.maximum_inlets,
            )
            and _cardinality_complete(
                len(outlets),
                transition_rule.minimum_outlets,
                transition_rule.maximum_outlets,
            )
        )
        unique_nodes = all(nodes) and len(nodes) == len(set(nodes))
        complete = (
            cardinality_complete
            and unique_nodes
            and not projection_issues
        )
        if not cardinality_complete and "missing_required_port" not in projection_issues:
            projection_issues.append("missing_required_port")
        if not unique_nodes and "duplicate_projected_node" not in projection_issues:
            projection_issues.append("duplicate_projected_node")
        applicability = (
            ProjectionApplicability.SUPPORTED_COMPLETE
            if complete else ProjectionApplicability.INCOMPLETE_MISSING_PORT
        )
        all_complete = all_complete and complete
        transitions.append(FlowTransition(
            transition_id=(
                f"flow-transition:{object_ref.object_id}:{ordinal}:"
                f"{transition_rule.stream.value}"
            ),
            object_ref=object_ref,
            inlet_ports=inlets,
            outlet_ports=outlets,
            medium=transition_rule.medium,
            stream=transition_rule.stream,
            circuit_id=transition_rule.stream.value,
            traversal_role=transition_rule.traversal_role,
            rule_id=f"{rule.rule_id}:transition:{transition_rule.stream.value}",
            rule_version=_normalize_version(rule.version),
            applicability=applicability,
        ))
    all_nodes = tuple(
        port.normalized_node_name
        for row in transitions
        for port in (*row.inlet_ports, *row.outlet_ports)
    )
    if (
        (not all(all_nodes) or len(all_nodes) != len(set(all_nodes)))
        and "duplicate_projected_node" not in projection_issues
    ):
        projection_issues.append("duplicate_projected_node")
        all_complete = False
    applicability = (
        ProjectionApplicability.SUPPORTED_COMPLETE
        if all_complete and bool(transitions) and not projection_issues
        else ProjectionApplicability.INCOMPLETE_MISSING_PORT
    )
    return CompoundFlowProjection(
        projection_id=f"flow-projection:{object_ref.object_id}:{rule.rule_id}",
        object_ref=object_ref,
        topology_form=rule.topology_form,
        transitions=tuple(transitions),
        rule_id=rule.rule_id,
        rule_version=_normalize_version(rule.version),
        applicability=applicability,
        issues=tuple(projection_issues),
    )


def _build_direct_projections(
    object_ref: ObjectRef,
    ports: tuple[PortRef, ...],
    version: str,
) -> tuple[CompoundFlowProjection, ...]:
    grouped: dict[tuple[FluidMedium, str], list[PortRef]] = defaultdict(list)
    for port in ports:
        if port.role in {PortRole.INLET, PortRole.OUTLET}:
            grouped[(port.medium, port.port_group)].append(port)
    rows: list[CompoundFlowProjection] = []
    for (medium, group), group_ports in sorted(
        grouped.items(), key=lambda item: (item[0][0].value, item[0][1]),
    ):
        inlets = tuple(port for port in group_ports if port.role is PortRole.INLET)
        outlets = tuple(port for port in group_ports if port.role is PortRole.OUTLET)
        if len(inlets) != 1 or len(outlets) != 1:
            continue
        safe_group = canonical(group).replace(":", "-").replace(" ", "-")
        rule_id = f"flow.direct.atomic.{safe_group}.v1"
        transition = FlowTransition(
            transition_id=f"flow-transition:{object_ref.object_id}:{safe_group}",
            object_ref=object_ref,
            inlet_ports=inlets,
            outlet_ports=outlets,
            medium=medium,
            stream=FlowStreamRole.DIRECT,
            circuit_id=group,
            traversal_role=FlowTraversalRole.PRIMARY,
            rule_id=f"{rule_id}:transition:{safe_group}",
            rule_version=_normalize_version(version),
            applicability=ProjectionApplicability.SUPPORTED_COMPLETE,
        )
        rows.append(CompoundFlowProjection(
            projection_id=f"flow-projection:{object_ref.object_id}:{safe_group}",
            object_ref=object_ref,
            topology_form=FlowTopologyForm.DIRECT,
            transitions=(transition,),
            rule_id=rule_id,
            rule_version=_normalize_version(version),
            applicability=ProjectionApplicability.SUPPORTED_COMPLETE,
        ))
    return tuple(rows)


def build_flow_projections(
    objects: tuple[ObjectRef, ...],
    ports: tuple[PortRef, ...],
    *,
    idd_version: str,
    registry: FlowProjectionRegistry = PRODUCTION_FLOW_PROJECTION_REGISTRY,
    extraction_issues_by_object_id: dict[str, tuple[str, ...]] | None = None,
) -> tuple[CompoundFlowProjection, ...]:
    """Project exact ports without inferring flow from arbitrary node fields."""

    by_object: dict[str, list[PortRef]] = defaultdict(list)
    for port in ports:
        by_object[port.object_id].append(port)
    rows: list[CompoundFlowProjection] = []
    issues_by_object = extraction_issues_by_object_id or {}
    for object_ref in objects:
        object_ports = tuple(by_object.get(object_ref.object_id, ()))
        rule = registry.rule_for(object_ref.raw_object_type, idd_version)
        if rule is not None:
            rows.append(_build_compound_projection(
                object_ref,
                object_ports,
                rule,
                issues_by_object.get(object_ref.object_id, ()),
            ))
        elif not registry.has_object_type(object_ref.raw_object_type):
            rows.extend(_build_direct_projections(
                object_ref, object_ports, idd_version,
            ))
    return tuple(rows)


__all__ = [
    "FlowProjectionRegistry",
    "FlowProjectionRule",
    "PRODUCTION_FLOW_PROJECTION_REGISTRY",
    "TransitionProjectionRule",
    "build_flow_projections",
]
