"""实现 explicit、version-bound 的 HVAC port semantic registry。

extract_ports(): 只把 exact registry rule 支持的字段提升为 SAFE_AUTO port fact。
"""

from __future__ import annotations

from dataclasses import dataclass

from idfrepair.io.idf import IDFObject, canonical
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2.ir import (
    FieldRef,
    FluidMedium,
    PortApplicability,
    PortRef,
    PortRole,
    ZoneSideRole,
    object_ref_from_idf,
)


def _normalize_version(value: str) -> str:
    """把 EnergyPlus semantic version 归一化为无尾零的 dotted form。"""

    parts = value.strip().split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


@dataclass(frozen=True, slots=True)
class PortRule:
    """声明一个 exact object/IDD field 的 port semantics。"""

    rule_id: str
    versions: tuple[str, ...]
    object_type: str
    field_token: str
    field_name: str
    role: PortRole
    medium: FluidMedium
    port_group: str
    zone_side_role: ZoneSideRole = ZoneSideRole.NONE
    applicability: PortApplicability = PortApplicability.SUPPORTED_EXACT


@dataclass(frozen=True, slots=True)
class ExtensiblePortRule:
    """声明由 IDD begin-extensible/group width 证明的重复 port role。"""

    rule_id: str
    versions: tuple[str, ...]
    object_type: str
    begin_field_token: str
    begin_field_name: str
    group_width: int
    role: PortRole
    medium: FluidMedium
    port_group: str
    zone_side_role: ZoneSideRole = ZoneSideRole.NONE
    applicability: PortApplicability = PortApplicability.SUPPORTED_MULTI_PORT

    def __post_init__(self) -> None:
        if self.group_width < 1:
            raise ValueError("extensible_port_rule_group_width")


@dataclass(frozen=True, slots=True)
class PortRegistry:
    """保存无 prototype/file exception 的版本绑定 port rules。"""

    rules: tuple[PortRule, ...]
    extensible_rules: tuple[ExtensiblePortRule, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(
            (
                canonical(rule.object_type),
                rule.field_token.casefold(),
                _normalize_version(version),
            )
            for rule in self.rules
            for version in rule.versions
        )
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_port_rule")
        extensible_keys = tuple(
            (
                canonical(rule.object_type),
                rule.begin_field_token.casefold(),
                _normalize_version(version),
            )
            for rule in self.extensible_rules
            for version in rule.versions
        )
        if len(extensible_keys) != len(set(extensible_keys)):
            raise ValueError("duplicate_extensible_port_rule")

    def rules_for(self, object_type: str, version: str) -> tuple[PortRule, ...]:
        """返回与 exact object type/version 匹配的 rules。"""

        type_key = canonical(object_type)
        version_key = _normalize_version(version)
        return tuple(
            rule for rule in self.rules
            if canonical(rule.object_type) == type_key
            and version_key in {_normalize_version(item) for item in rule.versions}
        )

    def extensible_rules_for(
        self, object_type: str, version: str,
    ) -> tuple[ExtensiblePortRule, ...]:
        """返回与 exact object type/version 匹配的 extensible rules。"""

        type_key = canonical(object_type)
        version_key = _normalize_version(version)
        return tuple(
            rule for rule in self.extensible_rules
            if canonical(rule.object_type) == type_key
            and version_key in {_normalize_version(item) for item in rule.versions}
        )


@dataclass(frozen=True, slots=True)
class PortExtraction:
    """返回 supported ports、未注册 node 字段和 registry identity 问题。"""

    ports: tuple[PortRef, ...]
    unregistered_node_fields: tuple[FieldRef, ...]
    issues: tuple[str, ...]


EMPTY_PORT_REGISTRY = PortRegistry(())


_SUPPORTED_VERSIONS = ("22.1", "24.1")


def _rule(
    rule_id: str,
    object_type: str,
    field_token: str,
    field_name: str,
    role: PortRole,
    medium: FluidMedium,
    port_group: str,
    zone_side_role: ZoneSideRole = ZoneSideRole.NONE,
) -> PortRule:
    """构造当前主线明确审计过的 22.1/24.1 exact port rule。"""

    return PortRule(
        rule_id=rule_id,
        versions=_SUPPORTED_VERSIONS,
        object_type=object_type,
        field_token=field_token,
        field_name=field_name,
        role=role,
        medium=medium,
        port_group=port_group,
        zone_side_role=zone_side_role,
    )


def _compound_fixed_rules() -> tuple[PortRule, ...]:
    """Return separately versioned atomic facts used by compound projections."""

    specs = (
        (
            "airpath.splitter.inlet", "AirLoopHVAC:ZoneSplitter", "A2",
            "Inlet Node Name", PortRole.INLET, "distribution",
        ),
        (
            "airpath.supplyplenum.inlet", "AirLoopHVAC:SupplyPlenum", "A4",
            "Inlet Node Name", PortRole.INLET, "distribution",
        ),
        (
            "airpath.zonemixer.outlet", "AirLoopHVAC:ZoneMixer", "A2",
            "Outlet Node Name", PortRole.OUTLET, "return",
        ),
        (
            "airpath.returnplenum.outlet", "AirLoopHVAC:ReturnPlenum", "A4",
            "Outlet Node Name", PortRole.OUTLET, "return",
        ),
        (
            "oa.mixer.mixed.outlet", "OutdoorAir:Mixer", "A2",
            "Mixed Air Node Name", PortRole.OUTLET, "mixed_air",
        ),
        (
            "oa.mixer.outdoor.inlet", "OutdoorAir:Mixer", "A3",
            "Outdoor Air Stream Node Name", PortRole.INLET, "mixed_air",
        ),
        (
            "oa.mixer.relief.outlet", "OutdoorAir:Mixer", "A4",
            "Relief Air Stream Node Name", PortRole.OUTLET, "relief_air",
        ),
        (
            "oa.mixer.return.inlet", "OutdoorAir:Mixer", "A5",
            "Return Air Stream Node Name", PortRole.INLET, "mixed_air",
        ),
        (
            "oa.hx.supply.inlet", "HeatExchanger:AirToAir:SensibleAndLatent",
            "A3", "Supply Air Inlet Node Name", PortRole.INLET, "supply",
        ),
        (
            "oa.hx.supply.outlet", "HeatExchanger:AirToAir:SensibleAndLatent",
            "A4", "Supply Air Outlet Node Name", PortRole.OUTLET, "supply",
        ),
        (
            "oa.hx.exhaust.inlet", "HeatExchanger:AirToAir:SensibleAndLatent",
            "A5", "Exhaust Air Inlet Node Name", PortRole.INLET, "exhaust",
        ),
        (
            "oa.hx.exhaust.outlet", "HeatExchanger:AirToAir:SensibleAndLatent",
            "A6", "Exhaust Air Outlet Node Name", PortRole.OUTLET, "exhaust",
        ),
        (
            "oa.hx.flatplate.supply.inlet", "HeatExchanger:AirToAir:FlatPlate",
            "A5", "Supply Air Inlet Node Name", PortRole.INLET, "supply",
        ),
        (
            "oa.hx.flatplate.supply.outlet", "HeatExchanger:AirToAir:FlatPlate",
            "A6", "Supply Air Outlet Node Name", PortRole.OUTLET, "supply",
        ),
        (
            "oa.hx.flatplate.secondary.inlet", "HeatExchanger:AirToAir:FlatPlate",
            "A7", "Secondary Air Inlet Node Name", PortRole.INLET, "secondary",
        ),
        (
            "oa.hx.flatplate.secondary.outlet", "HeatExchanger:AirToAir:FlatPlate",
            "A8", "Secondary Air Outlet Node Name", PortRole.OUTLET, "secondary",
        ),
    )
    return tuple(
        PortRule(
            rule_id=f"{base_id}.e{version.replace('.', '_')}.v1",
            versions=(version,),
            object_type=object_type,
            field_token=field_token,
            field_name=field_name,
            role=role,
            medium=FluidMedium.AIR,
            port_group=port_group,
        )
        for version in ("22.1", "24.1")
        for base_id, object_type, field_token, field_name, role, port_group in specs
    )


PRODUCTION_PORT_REGISTRY = PortRegistry((
    _rule(
        "fan.constantvolume.air.inlet.v1", "Fan:ConstantVolume", "A3",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "fan.constantvolume.air.outlet.v1", "Fan:ConstantVolume", "A4",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "fan.variablevolume.air.inlet.v1", "Fan:VariableVolume", "A4",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "fan.variablevolume.air.outlet.v1", "Fan:VariableVolume", "A5",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "fan.systemmodel.air.inlet.v1", "Fan:SystemModel", "A3",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "fan.systemmodel.air.outlet.v1", "Fan:SystemModel", "A4",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "coil.heating.water.water.inlet.v1", "Coil:Heating:Water", "A3",
        "Water Inlet Node Name", PortRole.INLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "coil.heating.water.water.outlet.v1", "Coil:Heating:Water", "A4",
        "Water Outlet Node Name", PortRole.OUTLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "coil.heating.water.air.inlet.v1", "Coil:Heating:Water", "A5",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "coil.heating.water.air.outlet.v1", "Coil:Heating:Water", "A6",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "coil.cooling.water.water.inlet.v1", "Coil:Cooling:Water", "A3",
        "Water Inlet Node Name", PortRole.INLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "coil.cooling.water.water.outlet.v1", "Coil:Cooling:Water", "A4",
        "Water Outlet Node Name", PortRole.OUTLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "coil.cooling.water.air.inlet.v1", "Coil:Cooling:Water", "A5",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "coil.cooling.water.air.outlet.v1", "Coil:Cooling:Water", "A6",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "air",
    ),
    _rule(
        "pipe.adiabatic.water.inlet.v1", "Pipe:Adiabatic", "A2",
        "Inlet Node Name", PortRole.INLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "pipe.adiabatic.water.outlet.v1", "Pipe:Adiabatic", "A3",
        "Outlet Node Name", PortRole.OUTLET, FluidMedium.WATER, "water",
    ),
    _rule(
        "zone.pthp.air.inlet.v1", "ZoneHVAC:PackagedTerminalHeatPump", "A3",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_RETURN,
    ),
    _rule(
        "zone.pthp.air.outlet.v1", "ZoneHVAC:PackagedTerminalHeatPump", "A4",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_INLET,
    ),
    _rule(
        "zone.ptac.air.inlet.v1",
        "ZoneHVAC:PackagedTerminalAirConditioner", "A3",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_RETURN,
    ),
    _rule(
        "zone.ptac.air.outlet.v1",
        "ZoneHVAC:PackagedTerminalAirConditioner", "A4",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_INLET,
    ),
    _rule(
        "zone.fourpipefancoil.air.inlet.v1",
        "ZoneHVAC:FourPipeFanCoil", "A5",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_RETURN,
    ),
    _rule(
        "zone.fourpipefancoil.air.outlet.v1",
        "ZoneHVAC:FourPipeFanCoil", "A6",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "zone_air",
        ZoneSideRole.ZONE_INLET,
    ),
    _rule(
        "zone.adu.air.outlet.v1", "ZoneHVAC:AirDistributionUnit", "A2",
        "Air Distribution Unit Outlet Node Name", PortRole.OUTLET,
        FluidMedium.AIR, "zone_air", ZoneSideRole.ZONE_INLET,
    ),
    _rule(
        "zone.exhaustfan.air.inlet.v1", "Fan:ZoneExhaust", "A3",
        "Air Inlet Node Name", PortRole.INLET, FluidMedium.AIR, "zone_exhaust",
        ZoneSideRole.ZONE_EXHAUST,
    ),
    _rule(
        "zone.exhaustfan.air.outlet.v1", "Fan:ZoneExhaust", "A4",
        "Air Outlet Node Name", PortRole.OUTLET, FluidMedium.AIR, "zone_exhaust",
    ),
    *_compound_fixed_rules(),
), tuple(
    ExtensiblePortRule(
        rule_id=f"{rule_id}.e{version.replace('.', '_')}.v1",
        versions=(version,),
        object_type=object_type,
        begin_field_token=field_token,
        begin_field_name=field_name,
        group_width=1,
        role=role,
        medium=FluidMedium.AIR,
        port_group=port_group,
    )
    for version in ("22.1", "24.1")
    for rule_id, object_type, field_token, field_name, role, port_group in (
        (
            "airpath.splitter.outlets", "AirLoopHVAC:ZoneSplitter", "A3",
            "Outlet 1 Node Name", PortRole.OUTLET, "distribution",
        ),
        (
            "airpath.supplyplenum.outlets", "AirLoopHVAC:SupplyPlenum", "A5",
            "Outlet 1 Node Name", PortRole.OUTLET, "distribution",
        ),
        (
            "airpath.zonemixer.inlets", "AirLoopHVAC:ZoneMixer", "A3",
            "Inlet 1 Node Name", PortRole.INLET, "return",
        ),
        (
            "airpath.returnplenum.inlets", "AirLoopHVAC:ReturnPlenum", "A6",
            "Inlet 1 Node Name", PortRole.INLET, "return",
        ),
    )
))


def extract_ports(
    obj: IDFObject,
    idd: IDDSchema,
    *,
    registry: PortRegistry,
) -> PortExtraction:
    """依据 exact registry rule 从一个对象提取 source-backed ports。"""

    definition = idd.get(obj.object_type)
    source = object_ref_from_idf(obj, idd)
    if definition is None:
        return PortExtraction((), (), (f"idd_object_missing:{canonical(obj.object_type)}",))

    active_rules = registry.rules_for(obj.object_type, idd.version)
    active_extensible_rules = registry.extensible_rules_for(
        obj.object_type, idd.version,
    )
    registered_indexes: set[int] = set()
    ports: list[PortRef] = []
    issues: list[str] = []
    for rule in active_rules:
        field_def = next((
            field for field in definition.fields
            if field.field_id.casefold() == rule.field_token.casefold()
        ), None)
        if field_def is None:
            issues.append(f"port_rule_field_missing:{rule.rule_id}")
            continue
        if canonical(field_def.name) != canonical(rule.field_name):
            issues.append(f"port_rule_field_identity_mismatch:{rule.rule_id}")
            continue
        registered_indexes.add(field_def.index)
        field_ref = source.field(field_def.index)
        if field_ref is None or not field_ref.raw_value.strip():
            continue
        ports.append(PortRef(
            port_id=f"{source.object_id}:port:{field_ref.field_index}:{rule.port_group}",
            object_id=source.object_id,
            field_ref=field_ref,
            node_name=field_ref.raw_value,
            normalized_node_name=field_ref.normalized_value,
            role=rule.role,
            medium=rule.medium,
            applicability=rule.applicability,
            port_group=rule.port_group,
            zone_side_role=rule.zone_side_role,
            rule_id=rule.rule_id,
            rule_version=_normalize_version(idd.version),
        ))

    for rule in active_extensible_rules:
        begin_fields = tuple(field for field in definition.fields if field.extensible)
        field_def = next((
            field for field in begin_fields
            if field.field_id.casefold() == rule.begin_field_token.casefold()
        ), None)
        if field_def is None:
            issues.append(f"extensible_port_rule_field_missing:{rule.rule_id}")
            continue
        if canonical(field_def.name) != canonical(rule.begin_field_name):
            issues.append(f"extensible_port_rule_field_identity_mismatch:{rule.rule_id}")
            continue
        if definition.extensible != rule.group_width:
            issues.append(f"extensible_port_rule_group_mismatch:{rule.rule_id}")
            continue
        for field_index in range(
            field_def.index, len(source.fields) + 1, rule.group_width,
        ):
            registered_indexes.add(field_index)
            field_ref = source.field(field_index)
            if field_ref is None:
                continue
            if not field_ref.raw_value.strip():
                issues.append(
                    f"extensible_port_blank_member:{rule.rule_id}:{field_index}"
                )
                continue
            ports.append(PortRef(
                port_id=(
                    f"{source.object_id}:port:{field_ref.field_index}:"
                    f"{rule.port_group}"
                ),
                object_id=source.object_id,
                field_ref=field_ref,
                node_name=field_ref.raw_value,
                normalized_node_name=field_ref.normalized_value,
                role=rule.role,
                medium=rule.medium,
                applicability=rule.applicability,
                port_group=rule.port_group,
                zone_side_role=rule.zone_side_role,
                rule_id=rule.rule_id,
                rule_version=_normalize_version(idd.version),
            ))

    unregistered = []
    for field_ref in source.fields:
        field_def = definition.semantic_field_at(field_ref.field_index)
        if (
            field_def is not None
            and field_ref.raw_value.strip()
            and "node" in canonical(field_def.name)
            and field_ref.field_index not in registered_indexes
        ):
            unregistered.append(field_ref)
    return PortExtraction(tuple(ports), tuple(unregistered), tuple(issues))


__all__ = [
    "EMPTY_PORT_REGISTRY",
    "ExtensiblePortRule",
    "PRODUCTION_PORT_REGISTRY",
    "PortExtraction",
    "PortRegistry",
    "PortRule",
    "extract_ports",
]
