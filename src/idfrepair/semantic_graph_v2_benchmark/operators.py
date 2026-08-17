"""独立遍历 clean IDF 并枚举 V2 development mutation opportunities。

本模块有意重复少量 Branch/Connector/Zone parsing。它只依据 clean source
structure 及既有值构造 mutation，不调用 production scanner、candidate 或 solver。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2_benchmark.schema import (
    MutationFieldEdit,
    MutationOpportunity,
    MutationSupportObject,
)


def _edit(obj: IDFObject, field_index: int, new_value: str) -> MutationFieldEdit | None:
    if not 1 <= field_index <= len(obj.fields):
        return None
    field = obj.fields[field_index - 1]
    if field.value == new_value:
        return None
    return MutationFieldEdit(obj.index, field_index, field.value, new_value)


def _inverse(edits: tuple[MutationFieldEdit, ...]) -> tuple[MutationFieldEdit, ...]:
    return tuple(
        MutationFieldEdit(
            object_index=edit.object_index,
            field_index=edit.field_index,
            old_value=edit.new_value,
            new_value=edit.old_value,
        )
        for edit in edits
    )


def _opportunity(
    operator_id: str,
    relation_class: str,
    stratum: str,
    semantic_edit_cost: int,
    scope_keys: tuple[str, ...],
    edits: Iterable[MutationFieldEdit | None],
    *,
    metadata: tuple[tuple[str, str], ...] = (),
    supporting_objects: tuple[MutationSupportObject, ...] = (),
) -> MutationOpportunity | None:
    concrete = tuple(edit for edit in edits if edit is not None)
    if semantic_edit_cost and not concrete:
        return None
    fields = "-".join(
        f"o{edit.object_index}f{edit.field_index}" for edit in concrete
    ) or "noedit"
    scope = "-".join(scope_keys) or "model"
    return MutationOpportunity(
        opportunity_id=f"{operator_id}:{scope}:{fields}",
        operator_id=operator_id,
        relation_class=relation_class,
        stratum=stratum,
        semantic_edit_cost=semantic_edit_cost,
        scope_keys=scope_keys,
        edits=concrete,
        inverse_edits=_inverse(concrete),
        metadata=metadata,
        supporting_objects=supporting_objects,
    )


def apply_mutation(text: str, edits: tuple[MutationFieldEdit, ...]) -> str:
    """对一个 clean/current snapshot 原子应用 exact guarded mutation。"""

    document = parse_idf(text)
    selected: dict[tuple[int, int], MutationFieldEdit] = {}
    for edit in edits:
        key = (edit.object_index, edit.field_index)
        prior = selected.get(key)
        if prior is not None and (
            prior.old_value != edit.old_value or prior.new_value != edit.new_value
        ):
            raise ValueError("conflicting_mutation_field_write")
        selected[key] = edit
    replacements = []
    for (object_index, field_index), edit in selected.items():
        if not 0 <= object_index < len(document.objects):
            raise ValueError("mutation_object_index_out_of_range")
        obj = document.objects[object_index]
        if not 1 <= field_index <= len(obj.fields):
            raise ValueError("mutation_field_index_out_of_range")
        field = obj.fields[field_index - 1]
        if field.value != edit.old_value:
            raise ValueError("mutation_old_value_mismatch")
        replacements.append((field.start, field.end, edit.new_value))
    output = text
    for start, end, value in sorted(replacements, reverse=True):
        output = output[:start] + value + output[end:]
    return output


def materialize_mutation(
    clean_text: str,
    opportunity: MutationOpportunity,
) -> str:
    """Apply and independently validate one builder mutation.

    Validation is intentionally direct-IDF only: it confirms every declared
    relation field changed to its declared value and reparses the resulting IDF.
    It never imports or calls the production V2 graph, scanner, candidates, or
    repair API.
    """

    clean = parse_idf(clean_text)
    if clean.issues:
        raise ValueError("clean_mutation_source_parse_failed")
    faulty_text = apply_mutation(clean_text, opportunity.edits)
    if opportunity.supporting_objects:
        suffix = "\n".join(obj.object_text.strip() for obj in opportunity.supporting_objects)
        faulty_text = f"{faulty_text.rstrip()}\n{suffix}\n"
    faulty = parse_idf(faulty_text)
    if faulty.issues:
        raise ValueError("mutation_materialization_parse_failed")
    if not opportunity.edits:
        if faulty_text != clean_text:
            raise ValueError("clean_control_materialization_changed")
        return faulty_text

    for support in opportunity.supporting_objects:
        matches = faulty.find_objects(support.object_type, support.object_name)
        if len(matches) != 1:
            raise ValueError("mutation_support_object_missing_or_nonunique")
        if clean.find_objects(support.object_type, support.object_name):
            raise ValueError("mutation_support_object_already_in_clean")

    relation_changed = False
    for edit in opportunity.edits:
        if not 0 <= edit.object_index < len(clean.objects):
            raise ValueError("mutation_relation_object_out_of_range")
        clean_obj = clean.objects[edit.object_index]
        faulty_obj = faulty.objects[edit.object_index]
        if not 1 <= edit.field_index <= len(clean_obj.fields):
            raise ValueError("mutation_relation_field_out_of_range")
        if (
            clean_obj.fields[edit.field_index - 1].value != edit.old_value
            or faulty_obj.fields[edit.field_index - 1].value != edit.new_value
        ):
            raise ValueError("mutation_target_relation_mismatch")
        relation_changed |= edit.old_value != edit.new_value
    if not relation_changed:
        raise ValueError("mutation_target_relation_unchanged")
    return faulty_text


def _branch_members(obj: IDFObject) -> tuple[tuple[int, str, str, str, str], ...]:
    rows = []
    ordinal = 1
    for start in range(3, len(obj.fields) + 1, 4):
        if start + 3 > len(obj.fields):
            break
        values = tuple(obj.fields[index - 1].value for index in range(start, start + 4))
        if any(value.strip() for value in values):
            rows.append((ordinal, *values))
        ordinal += 1
    return tuple(rows)


def _renamed_object_text(obj: IDFObject, name: str) -> str | None:
    """Copy one parsed object with only its defining name changed."""

    if not obj.fields or not name.strip():
        return None
    field = obj.fields[0]
    start = field.start - obj.start
    end = field.end - obj.start
    if not 0 <= start <= end <= len(obj.raw):
        return None
    return obj.raw[:start] + name + obj.raw[end:]


# Builder-owned, version-bound direct port table.  This duplicates only the
# public IDD field positions needed to construct independent mutation sources;
# it never imports the production V2 port registry or scanner.
_BUILDER_DIRECT_PORT_TOKENS: dict[str, tuple[tuple[str, str], ...]] = {
    "fan:constantvolume": (("A3", "A4"),),
    "fan:variablevolume": (("A4", "A5"),),
    "fan:systemmodel": (("A3", "A4"),),
    "pipe:adiabatic": (("A2", "A3"),),
    "zonehvac:fourpipefancoil": (("A5", "A6"),),
    "zonehvac:packagedterminalairconditioner": (("A3", "A4"),),
    "zonehvac:packagedterminalheatpump": (("A3", "A4"),),
    "zonehvac:unitheater": (("A3", "A4"),),
    "fan:zoneexhaust": (("A3", "A4"),),
    "airloophvac:zonesplitter": (("A2", "A3"),),
}


def _has_direct_supported_pair(
    document: IDFDocument,
    component_type: str,
    component_name: str,
    inlet: str,
    outlet: str,
    idd: IDDSchema | None,
) -> bool:
    """Independently require a clean exact typed component/endpoint witness."""

    matches = document.find_objects(component_type, component_name)
    if len(matches) != 1:
        return False
    component = matches[0]
    token_pairs = _BUILDER_DIRECT_PORT_TOKENS.get(canonical(component_type), ())
    definition = idd.get(component_type) if idd is not None else None
    for inlet_token, outlet_token in token_pairs:
        inlet_index = int(inlet_token[1:])
        outlet_index = int(outlet_token[1:])
        if definition is not None:
            inlet_field = next(
                (field for field in definition.fields if field.field_id == inlet_token),
                None,
            )
            outlet_field = next(
                (field for field in definition.fields if field.field_id == outlet_token),
                None,
            )
            if inlet_field is None or outlet_field is None:
                continue
            inlet_index = inlet_field.index
            outlet_index = outlet_field.index
        if outlet_index > len(component.fields):
            continue
        if (
            canonical(component.fields[inlet_index - 1].value) == canonical(inlet)
            and canonical(component.fields[outlet_index - 1].value) == canonical(outlet)
        ):
            return True
    return False


def _zone_boundary_nodes(document: IDFDocument, value: str) -> tuple[str, ...]:
    """Resolve a unique NodeList without treating its name as node evidence."""

    node_lists = document.find_objects("NodeList", value)
    if len(node_lists) != 1:
        return (value,)
    return tuple(field.value for field in node_lists[0].fields[1:] if field.value.strip())


def _has_explicit_zone_port_witness(
    document: IDFDocument,
    object_type: str,
    object_name: str,
    connection: IDFObject,
    idd: IDDSchema | None,
) -> bool:
    """Require direct equipment inlet/outlet evidence at the zone boundary."""

    if len(connection.fields) < 3:
        return False
    boundary_nodes = tuple(
        node
        for field in connection.fields[2:6]
        if field.value.strip()
        for node in _zone_boundary_nodes(document, field.value)
    )
    return any(
        _has_direct_supported_pair(
            document, object_type, object_name, inlet, outlet, idd,
        )
        for inlet in boundary_nodes
        for outlet in boundary_nodes
        if canonical(inlet) != canonical(outlet)
    )


def _typed_members(
    obj: IDFObject, start: int,
) -> tuple[tuple[int, int, str, str], ...]:
    rows = []
    ordinal = 1
    for type_index in range(start, len(obj.fields) + 1, 2):
        name_index = type_index + 1
        if name_index > len(obj.fields):
            break
        object_type = obj.fields[type_index - 1].value
        object_name = obj.fields[name_index - 1].value
        if object_type.strip() or object_name.strip():
            rows.append((type_index, name_index, object_type, object_name))
        ordinal += 1
    return tuple(rows)


def _foreign_value(values: Iterable[str], excluded: Iterable[str]) -> str | None:
    excluded_keys = {canonical(value) for value in excluded}
    return next(
        (
            value for value in sorted(set(values), key=lambda item: canonical(item))
            if value.strip() and canonical(value) not in excluded_keys
        ),
        None,
    )


def _branch_opportunities(
    document: IDFDocument, idd: IDDSchema | None,
) -> list[MutationOpportunity]:
    rows: list[MutationOpportunity] = []
    branches = document.find_objects("Branch")
    node_values = tuple(
        value
        for branch in branches
        for _, _, _, inlet, outlet in _branch_members(branch)
        for value in (inlet, outlet)
        if value.strip()
    )
    referenced = tuple(
        (component_type, component_name, inlet, outlet)
        for branch in branches
        for _, component_type, component_name, inlet, outlet in _branch_members(branch)
    )
    by_endpoints: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for component_type, component_name, inlet, outlet in referenced:
        by_endpoints[(canonical(inlet), canonical(outlet))].add((
            canonical(component_type), canonical(component_name),
        ))
    for branch in branches:
        scope = (f"branch:{branch.index}",)
        members = _branch_members(branch)
        for ordinal, component_type, component_name, inlet, outlet in members:
            start = 3 + (ordinal - 1) * 4
            foreign_inlet = _foreign_value(node_values, (inlet, outlet))
            foreign_outlet = _foreign_value(reversed(node_values), (inlet, outlet))
            for operator_id, index, value in (
                ("branch_wrong_inlet", start + 2, foreign_inlet),
                ("branch_wrong_outlet", start + 3, foreign_outlet),
            ):
                if value is None:
                    continue
                row = _opportunity(
                    operator_id, "branch_path", "single", 1, scope,
                    (_edit(branch, index, value),),
                    metadata=(("member_ordinal", str(ordinal)),),
                )
                if row is not None:
                    rows.append(row)
            donor = next((
                candidate for candidate in referenced
                if (
                    canonical(candidate[0]), canonical(candidate[1])
                ) != (canonical(component_type), canonical(component_name))
                and (canonical(candidate[2]), canonical(candidate[3]))
                != (canonical(inlet), canonical(outlet))
            ), None)
            if donor is not None:
                row = _opportunity(
                    "branch_wrong_typed_reference", "branch_path", "single", 1,
                    scope,
                    (
                        _edit(branch, start, donor[0]),
                        _edit(branch, start + 1, donor[1]),
                    ),
                    metadata=(("member_ordinal", str(ordinal)),),
                )
                if row is not None:
                    rows.append(row)
                endpoint_peers = by_endpoints.get(
                    (canonical(inlet), canonical(outlet)), set()
                )
                if len(endpoint_peers) >= 2:
                    ambiguous = _opportunity(
                        "ambiguous_typed_reference", "branch_path", "ambiguity", 1,
                        scope,
                        (
                            _edit(branch, start, donor[0]),
                            _edit(branch, start + 1, donor[1]),
                        ),
                        metadata=((
                            "independent_candidate_witness_count",
                            str(len(endpoint_peers)),
                        ),),
                    )
                    if ambiguous is not None:
                        rows.append(ambiguous)
            source_matches = document.find_objects(component_type, component_name)
            if (
                len(source_matches) == 1
                and _has_direct_supported_pair(
                    document, component_type, component_name, inlet, outlet, idd,
                )
            ):
                source = source_matches[0]
                twin_name = (
                    f"{component_name} V2 Ambiguity Twin "
                    f"{branch.index} {ordinal}"
                )
                unknown_name = f"V2 Ambiguous Unknown {branch.index} {ordinal}"
                twin_text = _renamed_object_text(source, twin_name)
                if (
                    twin_text is not None
                    and not document.find_objects(component_type, twin_name)
                    and not document.find_objects(component_type, unknown_name)
                ):
                    ambiguous_twin = _opportunity(
                        "ambiguous_branch_twin", "branch_path", "ambiguity", 1,
                        (f"branch-factor:{branch.index}",),
                        (_edit(branch, start + 1, unknown_name),),
                        metadata=(
                            ("branch_factor", f"branch-factor:{branch.index}"),
                            ("member_ordinal", str(ordinal)),
                            ("source_identity", f"{component_type}|{component_name}"),
                            ("twin_name", twin_name),
                            ("unknown_reference", unknown_name),
                            ("injected_support_object_count", "1"),
                            ("oracle_witness_count", "2"),
                            (
                                "oracle_alternative_identities",
                                f"{component_type}|{component_name}|{twin_name}",
                            ),
                        ),
                        supporting_objects=(MutationSupportObject(
                            source_object_index=source.index,
                            object_type=source.object_type,
                            object_name=twin_name,
                            object_text=twin_text,
                        ),),
                    )
                    if ambiguous_twin is not None:
                        rows.append(ambiguous_twin)
        if len(members) == 1:
            # A single-member Branch has no adjacent continuity relation. Its
            # two typed ports therefore share one exact branch-member factor
            # while yielding two complete endpoint domains, without invoking
            # the production reorder/continuity co-occurrence guard.
            first = members[0]
            last = members[-1]
            first_start = 3 + (first[0] - 1) * 4
            last_start = 3 + (last[0] - 1) * 4
            first_wrong_inlet = _foreign_value(
                node_values, (first[3], first[4]),
            )
            last_wrong_outlet = _foreign_value(
                reversed(node_values), (last[3], last[4]),
            )
            endpoints_supported = all((
                _has_direct_supported_pair(
                    document, first[1], first[2], first[3], first[4],
                    idd,
                ),
                _has_direct_supported_pair(
                    document, last[1], last[2], last[3], last[4],
                    idd,
                ),
            ))
            connected = _opportunity(
                "connected_branch_double", "branch_path", "connected_double", 2,
                (f"branch-factor:{branch.index}",),
                (
                    _edit(branch, first_start + 2, first_wrong_inlet)
                    if first_wrong_inlet is not None else None,
                    _edit(branch, last_start + 3, last_wrong_outlet)
                    if last_wrong_outlet is not None else None,
                ),
                metadata=(
                    ("branch_factor", f"branch-factor:{branch.index}"),
                    ("branch_object_index", str(branch.index)),
                    ("member_ordinals", f"{first[0]}|{last[0]}"),
                    ("atomic_operators", "branch_wrong_inlet|branch_wrong_outlet"),
                    ("joint_proof", "two_ports_one_member_branch_factor"),
                ),
            )
            if (
                endpoints_supported
                and connected is not None
                and len(connected.edits) == 2
            ):
                rows.append(connected)
        for left, right in zip(members, members[1:]):
            left_start = 3 + (left[0] - 1) * 4
            right_start = 3 + (right[0] - 1) * 4
            edits = []
            for offset in range(4):
                edits.extend((
                    _edit(branch, left_start + offset, right[offset + 1]),
                    _edit(branch, right_start + offset, left[offset + 1]),
                ))
            row = _opportunity(
                "branch_member_order", "branch_path", "single", 1, scope, edits,
                metadata=(("ordinals", f"{left[0]}|{right[0]}"),),
            )
            if row is not None:
                rows.append(row)
        if len(members) >= 2:
            first, second = members[0], members[1]
            first_name_index = 4 + (first[0] - 1) * 4
            row = _opportunity(
                "insufficient_evidence", "branch_path", "insufficient", 1,
                scope,
                (_edit(branch, first_name_index, second[2]),),
                metadata=(("reason", "duplicate_member_design_intent"),),
            )
            if row is not None:
                rows.append(row)
    return rows


def _connector_opportunities(document: IDFDocument) -> list[MutationOpportunity]:
    rows: list[MutationOpportunity] = []
    branch_names = tuple(obj.name for obj in document.find_objects("Branch"))
    for object_type, operator_id in (
        ("Connector:Splitter", "splitter_wrong_parallel_member"),
        ("Connector:Mixer", "mixer_wrong_parallel_member"),
    ):
        for connector in document.find_objects(object_type):
            existing = tuple(field.value for field in connector.fields[1:])
            foreign = _foreign_value(branch_names, existing)
            if foreign is None:
                continue
            for field in connector.fields[2:]:
                row = _opportunity(
                    operator_id, "loop_connector", "single", 1,
                    (f"connector:{connector.index}",),
                    (_edit(connector, field.index, foreign),),
                )
                if row is not None:
                    rows.append(row)

    for branch_list in document.find_objects("BranchList"):
        members = tuple(
            field for field in branch_list.fields[1:] if field.value.strip()
        )
        foreign = _foreign_value(branch_names, (field.value for field in members))
        if foreign is not None:
            for field in members:
                row = _opportunity(
                    "branchlist_wrong_member", "loop_connector", "single", 1,
                    (f"branchlist:{branch_list.index}",),
                    (_edit(branch_list, field.index, foreign),),
                )
                if row is not None:
                    rows.append(row)
        if len(members) >= 3:
            first, middle = members[0], members[1]
            row = _opportunity(
                "branchlist_boundary_swap", "loop_connector", "single", 1,
                (f"branchlist:{branch_list.index}",),
                (
                    _edit(branch_list, first.index, middle.value),
                    _edit(branch_list, middle.index, first.value),
                ),
                metadata=(("boundary", "inlet"),),
            )
            if row is not None:
                rows.append(row)

    connector_by_type = {
        canonical(object_type): tuple(document.find_objects(object_type))
        for object_type in ("Connector:Splitter", "Connector:Mixer")
    }
    for connector_list in document.find_objects("ConnectorList"):
        for type_index, name_index, object_type, object_name in _typed_members(
            connector_list, 2,
        ):
            donor = next((
                obj for obj in connector_by_type.get(canonical(object_type), ())
                if canonical(obj.name) != canonical(object_name)
            ), None)
            if donor is None:
                continue
            row = _opportunity(
                "connectorlist_typed_member_mismatch", "loop_connector", "single",
                1, (f"connectorlist:{connector_list.index}",),
                (_edit(connector_list, name_index, donor.name),),
            )
            if row is not None:
                rows.append(row)

    connector_list_names = tuple(
        obj.name for obj in document.find_objects("ConnectorList")
    )
    for loop_type in ("PlantLoop", "CondenserLoop"):
        for loop in document.find_objects(loop_type):
            for connector_index in (14, 18):
                if connector_index > len(loop.fields):
                    continue
                current = loop.fields[connector_index - 1].value
                donor = _foreign_value(connector_list_names, (current,))
                if donor is None:
                    continue
                row = _opportunity(
                    "loop_side_connectorlist_mismatch", "loop_connector", "single",
                    1, (f"loop:{loop.index}:{connector_index}",),
                    (_edit(loop, connector_index, donor),),
                )
                if row is not None:
                    rows.append(row)
    return rows


def _path_opportunities(document: IDFDocument) -> list[MutationOpportunity]:
    rows: list[MutationOpportunity] = []
    for path_type in ("AirLoopHVAC:SupplyPath", "AirLoopHVAC:ReturnPath"):
        for path in document.find_objects(path_type):
            for _, name_index, object_type, object_name in _typed_members(path, 3):
                donor = next((
                    obj for obj in document.find_objects(object_type)
                    if canonical(obj.name) != canonical(object_name)
                ), None)
                if donor is None:
                    continue
                row = _opportunity(
                    "airpath_typed_member_mismatch", "air_path", "single", 1,
                    (f"airpath:{path.index}",),
                    (_edit(path, name_index, donor.name),),
                )
                if row is not None:
                    rows.append(row)

    for equipment_list in document.find_objects(
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList"
    ):
        members = _typed_members(equipment_list, 2)
        for _, name_index, object_type, object_name in members:
            donor = next((
                obj for obj in document.find_objects(object_type)
                if canonical(obj.name) != canonical(object_name)
            ), None)
            if donor is None:
                continue
            row = _opportunity(
                "oa_typed_member_mismatch", "outdoor_air_path", "single", 1,
                (f"oa-list:{equipment_list.index}",),
                (_edit(equipment_list, name_index, donor.name),),
            )
            if row is not None:
                rows.append(row)
        for left, right in zip(members, members[1:]):
            edits = (
                _edit(equipment_list, left[0], right[2]),
                _edit(equipment_list, left[1], right[3]),
                _edit(equipment_list, right[0], left[2]),
                _edit(equipment_list, right[1], left[3]),
            )
            row = _opportunity(
                "oa_member_order", "outdoor_air_path", "single", 1,
                (f"oa-list:{equipment_list.index}",), edits,
            )
            if row is not None:
                rows.append(row)
    return rows


def _zone_members(obj: IDFObject) -> tuple[tuple[int, int, str, str], ...]:
    rows = []
    for type_index in range(3, len(obj.fields) + 1, 6):
        name_index = type_index + 1
        if name_index > len(obj.fields):
            break
        object_type = obj.fields[type_index - 1].value
        object_name = obj.fields[name_index - 1].value
        if object_type.strip() or object_name.strip():
            rows.append((type_index, name_index, object_type, object_name))
    return tuple(rows)


def _zone_opportunities(
    document: IDFDocument, idd: IDDSchema | None,
) -> list[MutationOpportunity]:
    rows: list[MutationOpportunity] = []
    equipment_lists = document.find_objects("ZoneHVAC:EquipmentList")
    list_by_name = {canonical(obj.name): obj for obj in equipment_lists}
    list_names = tuple(obj.name for obj in equipment_lists)
    member_mutations: dict[tuple[int, int], MutationOpportunity] = {}
    for equipment_list in equipment_lists:
        scope = (f"zone-list:{equipment_list.index}",)
        for ordinal, name_index, object_type, object_name in _zone_members(equipment_list):
            donor = next((
                obj for obj in document.find_objects(object_type)
                if canonical(obj.name) != canonical(object_name)
            ), None)
            if donor is None:
                continue
            row = _opportunity(
                "zone_typed_member_mismatch", "zone_equipment", "single", 1,
                scope, (_edit(equipment_list, name_index, donor.name),),
            )
            if row is not None:
                rows.append(row)
                member_mutations[(equipment_list.index, ordinal)] = row

    for connection in document.find_objects("ZoneHVAC:EquipmentConnections"):
        if len(connection.fields) < 2:
            continue
        current_name = connection.fields[1].value
        donor_name = _foreign_value(list_names, (current_name,))
        if donor_name is None:
            continue
        list_row = _opportunity(
            "zone_list_ownership_mismatch", "zone_equipment", "single", 1,
            (f"zone-connection:{connection.index}",),
            (_edit(connection, 2, donor_name),),
        )
        if list_row is not None:
            rows.append(list_row)
        intended = list_by_name.get(canonical(current_name))
        member_row = next((
            member_mutations.get((intended.index, ordinal))
            for ordinal, _, object_type, object_name in _zone_members(intended)
            if _has_explicit_zone_port_witness(
                document, object_type, object_name, connection, idd,
            )
            and member_mutations.get((intended.index, ordinal)) is not None
        ), None) if intended is not None else None
        if list_row is not None and member_row is not None:
            combined = _opportunity(
                "connected_zone_list_member", "zone_equipment",
                "connected_double", 2,
                (f"zone-factor:{connection.index}",),
                (*list_row.edits, *member_row.edits),
                metadata=(
                    (
                        "atomic_operators",
                        "zone_list_ownership_mismatch|zone_typed_member_mismatch",
                    ),
                    ("zone_port_witness", "explicit_direct_inlet_outlet"),
                ),
            )
            if combined is not None:
                rows.append(combined)
    return rows


def _loop_factors(
    document: IDFDocument,
) -> tuple[tuple[str, int, int, tuple[int, ...]], ...]:
    """Map builder-visible loop sides to their BranchList and connector objects."""

    branch_lists = {
        canonical(obj.name): obj for obj in document.find_objects("BranchList")
    }
    connector_lists = {
        canonical(obj.name): obj for obj in document.find_objects("ConnectorList")
    }
    branches = {
        canonical(obj.name): obj for obj in document.find_objects("Branch")
    }
    connectors = {
        (canonical(obj.object_type), canonical(obj.name)): obj
        for object_type in ("Connector:Splitter", "Connector:Mixer")
        for obj in document.find_objects(object_type)
    }
    rows: list[tuple[str, int, int, tuple[int, ...]]] = []
    for loop_type in ("PlantLoop", "CondenserLoop"):
        for loop in document.find_objects(loop_type):
            for side, branch_field, connector_field in (
                ("supply", 13, 14), ("demand", 17, 18),
            ):
                if connector_field > len(loop.fields):
                    continue
                branch_list = branch_lists.get(
                    canonical(loop.fields[branch_field - 1].value)
                )
                connector_list = connector_lists.get(
                    canonical(loop.fields[connector_field - 1].value)
                )
                if branch_list is None or connector_list is None:
                    continue
                indices = {loop.index, branch_list.index, connector_list.index}
                for field in branch_list.fields[1:]:
                    branch = branches.get(canonical(field.value))
                    if branch is not None:
                        indices.add(branch.index)
                for _, _, object_type, object_name in _typed_members(
                    connector_list, 2,
                ):
                    connector = connectors.get(
                        (canonical(object_type), canonical(object_name))
                    )
                    if connector is not None:
                        indices.add(connector.index)
                rows.append((
                    f"loop-factor:{loop.index}:{side}",
                    branch_list.index,
                    connector_list.index,
                    tuple(sorted(indices)),
                ))
    return tuple(rows)


def _topology_scopes_by_object(document: IDFDocument) -> dict[int, tuple[str, ...]]:
    scopes: dict[int, set[str]] = defaultdict(set)
    for factor, _, _, object_indices in _loop_factors(document):
        for object_index in object_indices:
            scopes[object_index].add(factor)
    return {
        obj.index: tuple(sorted(scopes.get(obj.index, {f"object:{obj.index}"})))
        for obj in document.objects
    }


def _opportunity_topology_scopes(
    opportunity: MutationOpportunity,
    scopes_by_object: dict[int, tuple[str, ...]],
) -> tuple[str, ...]:
    return tuple(sorted({
        scope
        for edit in opportunity.edits
        for scope in scopes_by_object.get(edit.object_index, ())
    }))


def _compose_opportunities(
    document: IDFDocument,
    singles: list[MutationOpportunity],
) -> list[MutationOpportunity]:
    rows: list[MutationOpportunity] = []
    factors = _loop_factors(document)
    for factor, branch_list_index, connector_list_index, object_indices in factors:
        loop_member = next((
            row for row in singles
            if row.operator_id in {
                "splitter_wrong_parallel_member", "mixer_wrong_parallel_member",
            }
            and any(edit.object_index in object_indices for edit in row.edits)
        ), None)
        branchlist = next((
            row for row in singles
            if row.operator_id == "branchlist_wrong_member"
            and any(edit.object_index == branch_list_index for edit in row.edits)
        ), None)
        if loop_member is None or branchlist is None:
            continue
        row = _opportunity(
            "connected_loop_double", "loop_connector", "connected_double", 2,
            (factor,), (*loop_member.edits, *branchlist.edits),
            metadata=(
                ("atomic_operators", f"{loop_member.operator_id}|{branchlist.operator_id}"),
                ("loop_factor", factor),
                ("branch_list_index", str(branch_list_index)),
                ("connector_list_index", str(connector_list_index)),
                ("loop_member_object_index", str(loop_member.edits[0].object_index)),
                ("branchlist_object_index", str(branchlist.edits[0].object_index)),
            ),
        )
        if row is not None:
            rows.append(row)

    scopes_by_object = _topology_scopes_by_object(document)
    objects_by_index = {obj.index: obj for obj in document.objects}
    airloop_membership_names = {
        canonical(field.value)
        for airloop in document.find_objects("AirLoopHVAC")
        for field in airloop.fields
        if field.value.strip()
    }
    independent_factor_names = {
        factor
        for factor, branch_list_index, connector_list_index, _ in factors
        if canonical(objects_by_index[branch_list_index].name)
        not in airloop_membership_names
        and canonical(objects_by_index[connector_list_index].name)
        not in airloop_membership_names
    }
    independent_atomics: list[tuple[str, str, MutationOpportunity]] = []
    for row in singles:
        if row.operator_id not in {
            "splitter_wrong_parallel_member", "mixer_wrong_parallel_member",
        }:
            continue
        factor_scopes = _opportunity_topology_scopes(row, scopes_by_object)
        if len(factor_scopes) != 1 or not factor_scopes[0].startswith("loop-factor:"):
            continue
        if factor_scopes[0] not in independent_factor_names:
            continue
        parts = factor_scopes[0].split(":")
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        independent_atomics.append((parts[1], factor_scopes[0], row))

    independent_count = 0
    for left_loop_index, left_factor, left_parallel in independent_atomics:
        for right_loop_index, right_factor, right_parallel in independent_atomics:
            if left_loop_index == right_loop_index:
                continue
            row = _opportunity(
                "independent_double", "cross_relation", "independent_double", 2,
                (f"topology:{left_factor}", f"topology:{right_factor}"),
                (*left_parallel.edits, *right_parallel.edits),
                metadata=(
                    (
                        "atomic_operators",
                        f"{left_parallel.operator_id}|{right_parallel.operator_id}",
                    ),
                    ("left_topology_scopes", left_factor),
                    ("right_topology_scopes", right_factor),
                    ("independence_proof", "distinct_parent_loops_complete_factors"),
                    ("left_atomic_proof", "direct_parallel_member_overwrite"),
                    ("right_atomic_proof", "direct_parallel_member_overwrite"),
                ),
            )
            if row is not None:
                rows.append(row)
                independent_count += 1
            if independent_count >= 8:
                return rows
    return rows


def enumerate_mutation_opportunities(
    document: IDFDocument,
    *,
    idd: IDDSchema | None = None,
) -> tuple[MutationOpportunity, ...]:
    """确定性枚举，不依据 production repair success 删除任何机会。"""

    rows = [
        *_branch_opportunities(document, idd),
        *_connector_opportunities(document),
        *_path_opportunities(document),
        *_zone_opportunities(document, idd),
    ]
    singles = list(rows)
    rows.extend(_compose_opportunities(document, singles))
    control = _opportunity(
        "clean_control", "whole_model", "control", 0,
        ("model",), (),
    )
    if control is not None:
        rows.append(control)
    unique: dict[str, MutationOpportunity] = {}
    for row in rows:
        unique.setdefault(row.opportunity_id, row)
    return tuple(unique[key] for key in sorted(unique))


__all__ = [
    "apply_mutation",
    "enumerate_mutation_opportunities",
    "materialize_mutation",
]
