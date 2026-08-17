"""独立执行 parse-only opportunity 枚举与 mutation materialization。

enumerate_source_candidates(): 从单个 clean source 枚举冻结机会。
enumerate_qualified_candidates(): 汇总全部资格化 source 的独立 candidate pool。
materialize_candidate(): 原子应用 exact guarded mutation 并重新解析验证。
pool_audit(): 汇总不含 inference 的 candidate pool 证据。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v22_benchmark.operators import (
    enumerate_extension_opportunities,
)
from idfrepair.semantic_graph_v2_benchmark.operators import (
    _branch_members,
    _has_direct_supported_pair,
    _has_explicit_zone_port_witness,
    _zone_members,
    enumerate_mutation_opportunities,
)

from .builder import Candidate, FinalEdit, FinalSupportObject
from .registry import BY_OPERATOR


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _edit(row: object) -> FinalEdit:
    return FinalEdit(
        object_index=int(row.object_index),  # type: ignore[attr-defined]
        field_index=int(row.field_index),  # type: ignore[attr-defined]
        old_value=str(row.old_value),  # type: ignore[attr-defined]
        new_value=str(row.new_value),  # type: ignore[attr-defined]
    )


def _support(row: object) -> FinalSupportObject:
    return FinalSupportObject(
        source_object_index=int(row.source_object_index),  # type: ignore[attr-defined]
        object_type=str(row.object_type),  # type: ignore[attr-defined]
        object_name=str(row.object_name),  # type: ignore[attr-defined]
        object_text=str(row.object_text),  # type: ignore[attr-defined]
    )


def _candidate(
    source: Mapping[str, str], opportunity: object, builder_family: str,
) -> Candidate | None:
    operator_id = str(opportunity.operator_id)  # type: ignore[attr-defined]
    spec = BY_OPERATOR.get(operator_id)
    if spec is None:
        return None
    stratum = str(opportunity.stratum)  # type: ignore[attr-defined]
    if stratum != spec.fault_stratum:
        raise ValueError(
            f"operator_stratum_mismatch:{operator_id}:{stratum}:{spec.fault_stratum}"
        )
    relation = str(opportunity.relation_class)  # type: ignore[attr-defined]
    if relation == "oa_equipment_path":
        relation = "outdoor_air_path"
    if relation != spec.relation_class:
        raise ValueError(
            f"operator_relation_mismatch:{operator_id}:{relation}:{spec.relation_class}"
        )
    cost = 0 if stratum == "control" else 2 if stratum in {
        "connected_double", "independent_double",
    } else 1
    supports = tuple(
        _support(row) for row in getattr(opportunity, "supporting_objects", ())
    )
    metadata = tuple(
        (str(key), str(value))
        for key, value in getattr(opportunity, "metadata", ())
    )
    return Candidate(
        source_id=str(source.get("sealed_source_id", source.get("membership_id", ""))),
        source_path=str(source.get("source_path", "")),
        qualified_artifact=str(source.get("qualified_artifact", "")),
        weather_path=str(source.get("weather_path", "")),
        topology_fingerprint=str(source.get("topology_fingerprint", "")),
        prototype=str(source.get("prototype", "")),
        corpus=str(source.get("corpus", "")),
        operator_id=operator_id,
        relation_class=relation,
        stratum=stratum,
        semantic_edit_cost=cost,
        opportunity_id=str(opportunity.opportunity_id),  # type: ignore[attr-defined]
        scope_keys=tuple(str(value) for value in opportunity.scope_keys),  # type: ignore[attr-defined]
        edits=tuple(_edit(row) for row in opportunity.edits),  # type: ignore[attr-defined]
        inverse_edits=tuple(_edit(row) for row in opportunity.inverse_edits),  # type: ignore[attr-defined]
        metadata=metadata,
        supporting_objects=supports,
        builder_family=builder_family,
    )


def _admissible_candidate(
    row: Candidate, document, idd: IDDSchema,
) -> bool:  # type: ignore[no-untyped-def]
    """复核冻结 operator 声明的 parse-only recoverability precondition。"""

    if row.operator_id in {
        "branch_wrong_inlet", "branch_wrong_outlet",
        "branch_wrong_typed_reference",
    }:
        if not row.edits:
            return False
        branch = document.objects[row.edits[0].object_index]
        ordinal_value = dict(row.metadata).get("member_ordinal", "")
        if not ordinal_value.isdigit():
            return False
        member = next((
            value for value in _branch_members(branch)
            if value[0] == int(ordinal_value)
        ), None)
        return bool(
            member is not None
            and _has_direct_supported_pair(
                document, member[1], member[2], member[3], member[4], idd,
            )
        )
    if row.operator_id == "zone_typed_member_mismatch":
        if not row.edits:
            return False
        equipment_list = document.objects[row.edits[0].object_index]
        member = next((
            value for value in _zone_members(equipment_list)
            if value[1] == row.edits[0].field_index
        ), None)
        connections = [
            connection
            for connection in document.find_objects("ZoneHVAC:EquipmentConnections")
            if len(connection.fields) >= 2
            and canonical(connection.fields[1].value) == canonical(equipment_list.name)
        ]
        return bool(
            member is not None
            and len(connections) == 1
            and _has_explicit_zone_port_witness(
                document, member[2], member[3], connections[0], idd,
            )
        )
    if row.operator_id == "zone_list_ownership_mismatch":
        if not row.edits:
            return False
        connection = document.objects[row.edits[0].object_index]
        intended = document.find_objects(
            "ZoneHVAC:EquipmentList", row.edits[0].old_value,
        )
        return bool(
            len(intended) == 1
            and any(
                _has_explicit_zone_port_witness(
                    document, object_type, object_name, connection, idd,
                )
                for _, _, object_type, object_name in _zone_members(intended[0])
            )
        )
    if row.operator_id.startswith("v22_oa_"):
        if not row.scope_keys or not row.scope_keys[0].startswith("oa-list:"):
            return False
        index_value = row.scope_keys[0].split(":", 1)[1]
        if not index_value.isdigit():
            return False
        equipment_list = document.objects[int(index_value)]
        members = [
            canonical(equipment_list.fields[index - 1].value)
            for index in range(2, len(equipment_list.fields) + 1, 2)
            if equipment_list.fields[index - 1].value.strip()
        ]
        allowed_patterns = {
            ("outdoorair:mixer",),
            (
                "heatexchanger:airtoair:sensibleandlatent",
                "outdoorair:mixer",
            ),
        }
        if tuple(members) not in allowed_patterns:
            return False
        return not any(
            canonical(edit.new_value) == "heatexchanger:airtoair:flatplate"
            for edit in row.edits
        )
    return True


def enumerate_source_candidates(
    source: Mapping[str, str], text: str, idd: IDDSchema,
) -> tuple[Candidate, ...]:
    document = parse_idf(text)
    if document.issues:
        raise ValueError(
            "qualified_source_parse_failed:" + "|".join(document.issues)
        )
    rows: list[Candidate] = []
    for opportunity in enumerate_mutation_opportunities(document, idd=idd):
        row = _candidate(source, opportunity, "v21")
        if row is not None and _admissible_candidate(row, document, idd):
            rows.append(row)
    for opportunity in enumerate_extension_opportunities(document):
        row = _candidate(source, opportunity, "v22")
        if row is not None and _admissible_candidate(row, document, idd):
            rows.append(row)
    unique: dict[str, Candidate] = {}
    for row in rows:
        unique.setdefault(row.mutation_key, row)
    return tuple(unique[key] for key in sorted(unique))


def enumerate_qualified_candidates(
    qualification_rows: Iterable[Mapping[str, str]],
    *,
    project_root: Path,
    idd: IDDSchema,
) -> tuple[Candidate, ...]:
    rows: list[Candidate] = []
    for source in qualification_rows:
        if source.get("qualification_status") != "PASSED":
            continue
        artifact = _resolve(project_root, str(source.get("qualified_artifact", "")))
        text = artifact.read_text(encoding="utf-8-sig", errors="replace")
        rows.extend(enumerate_source_candidates(source, text, idd))
    unique: dict[str, Candidate] = {}
    for row in rows:
        if row.mutation_key in unique:
            raise ValueError(f"cross_source_mutation_identity_collision:{row.mutation_key}")
        unique[row.mutation_key] = row
    return tuple(unique[key] for key in sorted(unique))


def materialize_candidate(clean_text: str, row: Candidate) -> str:
    clean = parse_idf(clean_text)
    if clean.issues:
        raise ValueError("clean_mutation_source_parse_failed")
    selected: dict[tuple[int, int], FinalEdit] = {}
    for edit in row.edits:
        key = (edit.object_index, edit.field_index)
        prior = selected.get(key)
        if prior is not None and prior != edit:
            raise ValueError("conflicting_mutation_field_write")
        selected[key] = edit
    replacements = []
    for edit in selected.values():
        if not 0 <= edit.object_index < len(clean.objects):
            raise ValueError("mutation_object_index_out_of_range")
        obj = clean.objects[edit.object_index]
        if not 1 <= edit.field_index <= len(obj.fields):
            raise ValueError("mutation_field_index_out_of_range")
        field = obj.fields[edit.field_index - 1]
        if field.value != edit.old_value or edit.old_value == edit.new_value:
            raise ValueError("mutation_old_value_mismatch")
        replacements.append((field.start, field.end, edit.new_value))
    output = clean_text
    for start, end, value in sorted(replacements, reverse=True):
        output = output[:start] + value + output[end:]
    if row.supporting_objects:
        suffix = "\n".join(item.object_text.strip() for item in row.supporting_objects)
        output = f"{output.rstrip()}\n{suffix}\n"
    faulty = parse_idf(output)
    if faulty.issues:
        raise ValueError("mutation_materialization_parse_failed")
    if row.stratum == "control":
        if output != clean_text or row.edits or row.supporting_objects:
            raise ValueError("clean_control_materialization_changed")
        return output
    if not row.edits:
        raise ValueError("mutation_has_no_field_effect")
    for edit in row.edits:
        value = faulty.objects[edit.object_index].fields[edit.field_index - 1].value
        if value != edit.new_value:
            raise ValueError("mutation_target_relation_not_materialized")
    for support in row.supporting_objects:
        if len(faulty.find_objects(support.object_type, support.object_name)) != 1:
            raise ValueError("mutation_support_object_missing_or_nonunique")
        if clean.find_objects(support.object_type, support.object_name):
            raise ValueError("mutation_support_object_already_in_clean")
    return output


def pool_audit(rows: Iterable[Candidate]) -> dict[str, object]:
    values = list(rows)
    by_operator = Counter(row.operator_id for row in values)
    by_relation = Counter(row.relation_class for row in values)
    by_stratum = Counter(row.stratum for row in values)
    topology_by_operator: dict[str, set[str]] = {}
    for row in values:
        topology_by_operator.setdefault(row.operator_id, set()).add(
            row.topology_fingerprint
        )
    return {
        "candidate_count": len(values),
        "unique_mutation_count": len({row.mutation_key for row in values}),
        "by_operator": dict(sorted(by_operator.items())),
        "by_relation": dict(sorted(by_relation.items())),
        "by_stratum": dict(sorted(by_stratum.items())),
        "topology_count_by_operator": {
            key: len(value) for key, value in sorted(topology_by_operator.items())
        },
    }


__all__ = [
    "enumerate_qualified_candidates",
    "enumerate_source_candidates",
    "materialize_candidate",
    "pool_audit",
]
