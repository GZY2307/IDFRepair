"""Parse-only AirPath/OA mutation builder; no V2.2 production dependency."""

from __future__ import annotations

from collections.abc import Iterable

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, parse_idf
from idfrepair.semantic_graph_v22_benchmark.schema import (
    ExtensionOpportunity,
    MutationFieldEdit,
)


_AIRPATH_TYPES = {
    "airloophvac:supplypath": {
        "airloophvac:zonesplitter", "airloophvac:supplyplenum",
    },
    "airloophvac:returnpath": {
        "airloophvac:zonemixer", "airloophvac:returnplenum",
    },
}
_OA_SUPPORTED_TYPES = {
    "outdoorair:mixer",
    "heatexchanger:airtoair:sensibleandlatent",
    "heatexchanger:airtoair:flatplate",
}


def _edit(obj: IDFObject, field_index: int, value: str) -> MutationFieldEdit | None:
    if not 1 <= field_index <= len(obj.fields):
        return None
    field = obj.fields[field_index - 1]
    if field.value == value:
        return None
    return MutationFieldEdit(obj.index, field_index, field.value, value)


def _inverse(edits: tuple[MutationFieldEdit, ...]) -> tuple[MutationFieldEdit, ...]:
    return tuple(
        MutationFieldEdit(edit.object_index, edit.field_index, edit.new_value, edit.old_value)
        for edit in edits
    )


def _opportunity(
    operator_id: str,
    relation_class: str,
    stratum: str,
    scope_keys: tuple[str, ...],
    edits: Iterable[MutationFieldEdit | None],
    *,
    metadata: tuple[tuple[str, str], ...] = (),
) -> ExtensionOpportunity | None:
    concrete = tuple(edit for edit in edits if edit is not None)
    if stratum != "control" and not concrete:
        return None
    fields = "-".join(f"o{edit.object_index}f{edit.field_index}" for edit in concrete) or "clean"
    return ExtensionOpportunity(
        opportunity_id=f"{operator_id}:{'-'.join(scope_keys)}:{fields}",
        operator_id=operator_id,
        relation_class=relation_class,
        stratum=stratum,
        semantic_edit_cost=len(concrete),
        scope_keys=scope_keys,
        edits=concrete,
        inverse_edits=_inverse(concrete),
        metadata=metadata,
    )


def _typed_members(obj: IDFObject, start: int) -> tuple[tuple[int, int, str, str], ...]:
    rows = []
    for type_index in range(start, len(obj.fields) + 1, 2):
        name_index = type_index + 1
        if name_index > len(obj.fields):
            break
        object_type = obj.fields[type_index - 1].value
        object_name = obj.fields[name_index - 1].value
        if object_type.strip() or object_name.strip():
            rows.append((type_index, name_index, object_type, object_name))
    return tuple(rows)


def _same_type_donor(document: IDFDocument, object_type: str, object_name: str) -> IDFObject | None:
    return next((
        obj for obj in document.find_objects(object_type)
        if canonical(obj.name) != canonical(object_name)
    ), None)


def _airpath_opportunities(document: IDFDocument) -> list[ExtensionOpportunity]:
    rows: list[ExtensionOpportunity] = []
    for path_type, allowed_types in _AIRPATH_TYPES.items():
        short = "supplypath" if path_type.endswith("supplypath") else "returnpath"
        for path in document.find_objects(path_type):
            scope = (f"airpath:{path.index}",)
            for ordinal, (type_index, name_index, object_type, object_name) in enumerate(
                _typed_members(path, 3), start=1,
            ):
                normalized_type = canonical(object_type)
                donor = _same_type_donor(document, object_type, object_name)
                name_row = _opportunity(
                    f"v22_{short}_member_name_mismatch", "air_path", "single", scope,
                    (_edit(path, name_index, donor.name) if donor is not None else None,),
                    metadata=(("member_ordinal", str(ordinal)), ("mutation", "name")),
                )
                if name_row is not None:
                    rows.append(name_row)
                donor_type = next((
                    candidate_type for candidate_type in sorted(allowed_types)
                    if candidate_type != normalized_type
                    and document.find_objects(candidate_type)
                ), None)
                if donor_type is not None:
                    donor_object = document.find_objects(donor_type)[0]
                    pair_row = _opportunity(
                        f"v22_{short}_type_name_mismatch", "air_path", "single", scope,
                        (_edit(path, type_index, donor_object.object_type), _edit(path, name_index, donor_object.name)),
                        metadata=(("member_ordinal", str(ordinal)), ("mutation", "type_name")),
                    )
                    if pair_row is not None:
                        rows.append(pair_row)
                if normalized_type not in allowed_types:
                    incomplete = _opportunity(
                        "v22_incomplete_domain_control", "air_path", "control", scope, (),
                        metadata=(("reason", "unsupported_airpath_member_type"),),
                    )
                    if incomplete is not None:
                        rows.append(incomplete)
                elif len(document.find_objects(object_type)) >= 2:
                    ambiguous = _opportunity(
                        "v22_ambiguous_domain_control", "air_path", "control", scope, (),
                        metadata=(("reason", "multiple_same_type_identities"),),
                    )
                    if ambiguous is not None:
                        rows.append(ambiguous)
    return rows


def _oa_opportunities(document: IDFDocument) -> list[ExtensionOpportunity]:
    rows: list[ExtensionOpportunity] = []
    all_supported_members = [
        member
        for equipment_list in document.find_objects("AirLoopHVAC:OutdoorAirSystem:EquipmentList")
        for member in _typed_members(equipment_list, 2)
        if canonical(member[2]) in _OA_SUPPORTED_TYPES
    ]
    for equipment_list in document.find_objects("AirLoopHVAC:OutdoorAirSystem:EquipmentList"):
        scope = (f"oa-list:{equipment_list.index}",)
        members = _typed_members(equipment_list, 2)
        supported_members = [member for member in members if canonical(member[2]) in _OA_SUPPORTED_TYPES]
        for ordinal, (type_index, name_index, object_type, object_name) in enumerate(members, start=1):
            normalized_type = canonical(object_type)
            if normalized_type not in _OA_SUPPORTED_TYPES:
                incomplete = _opportunity(
                    "v22_incomplete_domain_control", "oa_equipment_path", "control", scope, (),
                    metadata=(("reason", "unsupported_oa_member_type"),),
                )
                if incomplete is not None:
                    rows.append(incomplete)
                continue
            donor = _same_type_donor(document, object_type, object_name)
            name_row = _opportunity(
                "v22_oa_member_name_mismatch", "oa_equipment_path", "single", scope,
                (_edit(equipment_list, name_index, donor.name) if donor is not None else None,),
                metadata=(("member_ordinal", str(ordinal)), ("mutation", "name")),
            )
            if name_row is not None:
                rows.append(name_row)
            donor_pair = next((
                pair for pair in all_supported_members
                if canonical(pair[2]) != normalized_type
            ), None)
            if donor_pair is not None:
                pair_row = _opportunity(
                    "v22_oa_type_name_mismatch", "oa_equipment_path", "single", scope,
                    (_edit(equipment_list, type_index, donor_pair[2]), _edit(equipment_list, name_index, donor_pair[3])),
                    metadata=(("member_ordinal", str(ordinal)), ("mutation", "type_name")),
                )
                if pair_row is not None:
                    rows.append(pair_row)
            if len(document.find_objects(object_type)) >= 2:
                ambiguous = _opportunity(
                    "v22_ambiguous_domain_control", "oa_equipment_path", "control", scope, (),
                    metadata=(("reason", "multiple_same_type_identities"),),
                )
                if ambiguous is not None:
                    rows.append(ambiguous)
        if len(supported_members) >= 2:
            first, second = supported_members[0], supported_members[1]
            order_row = _opportunity(
                "v22_oa_member_order_mismatch", "oa_equipment_path", "single", scope,
                (
                    _edit(equipment_list, first[0], second[2]),
                    _edit(equipment_list, first[1], second[3]),
                    _edit(equipment_list, second[0], first[2]),
                    _edit(equipment_list, second[1], first[3]),
                ),
                metadata=(("mutation", "order"),),
            )
            if order_row is not None:
                rows.append(order_row)
    return rows


def enumerate_extension_opportunities(document: IDFDocument) -> tuple[ExtensionOpportunity, ...]:
    """Enumerate opportunities from clean source only; never consult repair output."""

    rows = [*_airpath_opportunities(document), *_oa_opportunities(document)]
    clean = _opportunity("v22_clean_control", "whole_model", "control", ("model",), ())
    if clean is not None:
        rows.append(clean)
    unique: dict[str, ExtensionOpportunity] = {}
    for row in rows:
        unique.setdefault(row.opportunity_id, row)
    return tuple(unique[key] for key in sorted(unique))


def materialize_mutation(clean_text: str, opportunity: ExtensionOpportunity) -> str:
    """Apply guarded edits and independently verify parse-only relation change."""

    clean = parse_idf(clean_text)
    if clean.issues:
        raise ValueError("clean_mutation_source_parse_failed")
    output = clean_text
    replacements = []
    for edit in opportunity.edits:
        if not 0 <= edit.object_index < len(clean.objects):
            raise ValueError("mutation_relation_object_out_of_range")
        obj = clean.objects[edit.object_index]
        if not 1 <= edit.field_index <= len(obj.fields):
            raise ValueError("mutation_relation_field_out_of_range")
        field = obj.fields[edit.field_index - 1]
        if field.value != edit.old_value or field.value == edit.new_value:
            raise ValueError("mutation_target_relation_mismatch")
        replacements.append((field.start, field.end, edit.new_value))
    for start, end, value in sorted(replacements, reverse=True):
        output = output[:start] + value + output[end:]
    faulty = parse_idf(output)
    if faulty.issues:
        raise ValueError("mutation_materialization_parse_failed")
    if not opportunity.edits:
        if output != clean_text:
            raise ValueError("clean_control_materialization_changed")
        return output
    for edit in opportunity.edits:
        if faulty.objects[edit.object_index].fields[edit.field_index - 1].value != edit.new_value:
            raise ValueError("mutation_target_relation_not_materialized")
    return output
