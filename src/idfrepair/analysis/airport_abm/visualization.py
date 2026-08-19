"""Private V3 viewer payload compiler for room occupancy and process flows."""

from __future__ import annotations

from collections import defaultdict
import gzip
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .model import AgentClass
from .source import SourceSpace, load_space_mapping


_SERIES_LENGTH = 96
_CLASS_NAMES = tuple(member.value for member in AgentClass)
_EDGE_LAYERS = frozenset({"A_EXPLICIT_DOOR", "B_FUNCTIONAL_PROCESS"})


def _series(value: object, identity: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"viewer series is missing: {identity}")
    values = [float(item) for item in value]
    if len(values) != _SERIES_LENGTH:
        raise ValueError(f"viewer series length is invalid: {identity}")
    if any(not math.isfinite(item) or item < 0 for item in values):
        raise ValueError(f"viewer series value is invalid: {identity}")
    return values


def _sum_series(target: list[float], values: Sequence[float]) -> None:
    for index, value in enumerate(values):
        target[index] += float(value)


def _edge_lookup(access: Mapping[str, object]) -> dict[tuple[str, str, str], str]:
    labels: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for collection in ("passenger_edges", "staff_edges"):
        rows = access.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f"access registry field is invalid: {collection}")
        for row in rows:
            if not isinstance(row, Mapping) or row.get("routable") is not True:
                continue
            source = str(row.get("from", ""))
            target = str(row.get("to", ""))
            label = str(row.get("evidence_label", ""))
            if not source or not target or not label:
                raise ValueError("routable access edge is incomplete")
            for role in row.get("roles", []):
                role_name = str(role)
                if role_name in _CLASS_NAMES:
                    labels[(source, target, role_name)].add(label)
    output: dict[tuple[str, str, str], str] = {}
    for key, candidates in labels.items():
        output[key] = (
            "STRONG_ACCESS_EDGE"
            if "STRONG_ACCESS_EDGE" in candidates
            else sorted(candidates)[0]
        )
    return output


def _edge_metadata(
    access: Mapping[str, object],
) -> dict[tuple[str, str, str], dict[str, object]]:
    candidates: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for collection in ("passenger_edges", "staff_edges"):
        rows = access.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f"access registry field is invalid: {collection}")
        for row in rows:
            if not isinstance(row, Mapping) or row.get("routable") is not True:
                continue
            source = str(row.get("from", ""))
            target = str(row.get("to", ""))
            layer = str(row.get("evidence_layer", ""))
            label = str(row.get("evidence_label", ""))
            reference = str(row.get("evidence_ref", ""))
            abstraction = row.get("abstraction_flag")
            doors = row.get("door_instances", [])
            roles = row.get("roles", [])
            if (
                not source
                or not target
                or layer not in _EDGE_LAYERS
                or not label
                or not reference
                or not isinstance(abstraction, bool)
                or not isinstance(doors, list)
                or not isinstance(roles, list)
            ):
                raise ValueError("routable access edge metadata is incomplete")
            metadata = {
                "evidence_layer": layer,
                "evidence_label": label,
                "evidence_ref": reference,
                "abstraction_flag": abstraction,
                "scenario_condition": (
                    None
                    if row.get("scenario_condition") is None
                    else str(row.get("scenario_condition"))
                ),
                "door_instances": [str(value) for value in doors],
            }
            for role in roles:
                role_name = str(role)
                if role_name in _CLASS_NAMES:
                    candidates[(source, target, role_name)].append(metadata)

    output: dict[tuple[str, str, str], dict[str, object]] = {}
    for key, rows in candidates.items():
        output[key] = sorted(
            rows,
            key=lambda row: (
                0 if row["evidence_layer"] == "A_EXPLICIT_DOOR" else 1,
                str(row["evidence_ref"]),
                str(row["scenario_condition"] or ""),
            ),
        )[0]
    return output


def _location_functions(
    spaces: Iterable[SourceSpace], access: Mapping[str, object]
) -> dict[str, str]:
    functions = {space.name: space.function for space in spaces}
    for row in access.get("nodes", []):
        if isinstance(row, Mapping):
            name = str(row.get("name", ""))
            function = str(row.get("function", ""))
            if name and function:
                functions[name] = function
    return functions


def _flow_rows(
    *,
    detail: Mapping[str, object],
    spaces: Iterable[SourceSpace],
    access: Mapping[str, object],
) -> list[dict[str, object]]:
    functions = _location_functions(spaces, access)
    evidence = _edge_lookup(access)
    aggregated: dict[
        tuple[str, str, str], dict[str, list[float]]
    ] = {}
    raw_flows = detail.get("class_space_flows", [])
    if not isinstance(raw_flows, list):
        raise ValueError("class Space flow data is invalid")
    for flow_index, row in enumerate(raw_flows):
        if not isinstance(row, Mapping):
            raise ValueError(f"class Space flow row is invalid: {flow_index}")
        source = str(row.get("from", ""))
        target = str(row.get("to", ""))
        source_function = functions.get(source)
        target_function = functions.get(target)
        if not source_function or not target_function:
            raise ValueError(f"flow endpoint function is missing: {source}->{target}")
        raw_classes = row.get("classes", {})
        if not isinstance(raw_classes, Mapping):
            raise ValueError(f"class Space flow classes are invalid: {flow_index}")
        for class_name in _CLASS_NAMES:
            values = _series(
                raw_classes.get(class_name),
                f"flow:{flow_index}:{class_name}",
            )
            if not any(values):
                continue
            label = evidence.get((source, target, class_name))
            if not label:
                raise ValueError(
                    f"flow has no routable access evidence: {source}->{target}:{class_name}"
                )
            key = (source_function, target_function, label)
            class_values = aggregated.setdefault(
                key,
                {name: [0.0] * _SERIES_LENGTH for name in _CLASS_NAMES},
            )
            _sum_series(class_values[class_name], values)

    output: list[dict[str, object]] = []
    for (source_function, target_function, label), class_values in sorted(
        aggregated.items()
    ):
        counts = [
            sum(class_values[class_name][index] for class_name in _CLASS_NAMES)
            for index in range(_SERIES_LENGTH)
        ]
        output.append(
            {
                "from_function": source_function,
                "to_function": target_function,
                "evidence_label": label,
                "counts": counts,
                "class_counts": class_values,
            }
        )
    return output


def _space_edge_flow_rows(
    *,
    detail: Mapping[str, object],
    spaces: Iterable[SourceSpace],
    access: Mapping[str, object],
) -> list[dict[str, object]]:
    space_rows = tuple(spaces)
    space_names = {space.name for space in space_rows}
    functions = _location_functions(space_rows, access)
    evidence = _edge_metadata(access)
    virtual_nodes = {
        str(row.get("name", ""))
        for row in access.get("nodes", [])
        if isinstance(row, Mapping) and row.get("is_virtual") is True
    }
    raw_flows = detail.get("class_space_flows", [])
    if not isinstance(raw_flows, list):
        raise ValueError("class Space flow data is invalid")
    output: list[dict[str, object]] = []
    for flow_index, row in enumerate(raw_flows):
        if not isinstance(row, Mapping):
            raise ValueError(f"class Space flow row is invalid: {flow_index}")
        source = str(row.get("from", ""))
        target = str(row.get("to", ""))
        source_function = functions.get(source)
        target_function = functions.get(target)
        if not source_function or not target_function:
            raise ValueError(f"flow endpoint function is missing: {source}->{target}")
        if source not in space_names and source not in virtual_nodes:
            raise ValueError(f"flow source is neither a mapped Space nor a boundary: {source}")
        if target not in space_names and target not in virtual_nodes:
            raise ValueError(f"flow target is neither a mapped Space nor a boundary: {target}")
        if source in virtual_nodes and target in virtual_nodes:
            raise ValueError(f"flow cannot connect two off-model boundaries: {source}->{target}")
        raw_classes = row.get("classes", {})
        if not isinstance(raw_classes, Mapping):
            raise ValueError(f"class Space flow classes are invalid: {flow_index}")

        grouped: dict[
            tuple[object, ...], tuple[dict[str, object], dict[str, list[float]], list[str]]
        ] = {}
        for class_name in _CLASS_NAMES:
            values = _series(
                raw_classes.get(class_name),
                f"space-edge-flow:{flow_index}:{class_name}",
            )
            if not any(values):
                continue
            metadata = evidence.get((source, target, class_name))
            if not metadata:
                raise ValueError(
                    f"flow has no routable access evidence: {source}->{target}:{class_name}"
                )
            identity = (
                metadata["evidence_layer"],
                metadata["evidence_label"],
                metadata["evidence_ref"],
                metadata["abstraction_flag"],
                metadata["scenario_condition"],
                tuple(metadata["door_instances"]),
            )
            if identity not in grouped:
                grouped[identity] = (
                    metadata,
                    {name: [0.0] * _SERIES_LENGTH for name in _CLASS_NAMES},
                    [],
                )
            _, class_values, roles = grouped[identity]
            _sum_series(class_values[class_name], values)
            roles.append(class_name)

        for metadata, class_values, roles in grouped.values():
            counts = [
                sum(class_values[class_name][index] for class_name in _CLASS_NAMES)
                for index in range(_SERIES_LENGTH)
            ]
            output.append(
                {
                    "from_node": source,
                    "to_node": target,
                    "from_space_name": source if source in space_names else None,
                    "to_space_name": target if target in space_names else None,
                    "from_function": source_function,
                    "to_function": target_function,
                    **metadata,
                    "roles": sorted(roles),
                    "off_model_boundary": source in virtual_nodes or target in virtual_nodes,
                    "boundary_direction": (
                        "incoming"
                        if source in virtual_nodes
                        else "outgoing"
                        if target in virtual_nodes
                        else None
                    ),
                    "counts": counts,
                    "class_counts": class_values,
                }
            )
    return sorted(
        output,
        key=lambda row: (
            str(row["from_node"]),
            str(row["to_node"]),
            str(row["evidence_layer"]),
            str(row["evidence_ref"]),
        ),
    )


def build_viewer_payload(
    *,
    spaces: Iterable[SourceSpace],
    detail: Mapping[str, object],
    access: Mapping[str, object],
    energy_by_space: Mapping[str, Mapping[str, Sequence[float]]] | None = None,
) -> dict[str, object]:
    """Compile one seed/scenario into the strict V3 browser schema."""

    if detail.get("schema_version") != "idfrepair.airport-abm-seed-detail.v3":
        raise ValueError("seed detail schema is invalid")
    if int(detail.get("interval_minutes", 0)) != 15:
        raise ValueError("viewer payload requires 15-minute data")
    labels = [str(value) for value in detail.get("interval_labels", [])]
    if len(labels) != _SERIES_LENGTH:
        raise ValueError("viewer interval labels are invalid")
    raw_counts = detail.get("space_counts", {})
    raw_classes = detail.get("class_counts", {})
    if not isinstance(raw_counts, Mapping) or not isinstance(raw_classes, Mapping):
        raise ValueError("seed detail Space data is invalid")
    space_rows = tuple(spaces)
    output_spaces: dict[str, dict[str, object]] = {}
    load_available = energy_by_space is not None
    if load_available and set(energy_by_space or {}) != {space.name for space in space_rows}:
        raise ValueError("viewer energy Space coverage is incomplete")
    for space in space_rows:
        if space.name not in raw_counts or space.name not in raw_classes:
            raise ValueError(f"viewer payload is missing Space data: {space.name}")
        occupancy = _series(raw_counts[space.name], f"{space.name}:occupancy")
        class_payload = raw_classes[space.name]
        if not isinstance(class_payload, Mapping):
            raise ValueError(f"viewer class counts are invalid: {space.name}")
        class_counts = {
            class_name: _series(
                class_payload.get(class_name), f"{space.name}:{class_name}"
            )
            for class_name in _CLASS_NAMES
        }
        for index in range(_SERIES_LENGTH):
            total = sum(class_counts[name][index] for name in _CLASS_NAMES)
            if abs(total - occupancy[index]) > 1e-5:
                raise ValueError(
                    f"viewer Space class counts do not reconcile: {space.name}:{index}"
                )
        output_row: dict[str, object] = {
            "source_space_name": space.name,
            "zone_name": space.thermal_zone,
            "function": space.function,
            "region": space.region,
            "floor_area_m2": space.area_m2,
            "design_people": space.source_design_people,
            "bem_people_supported": space.bem_people_supported,
            "occupancy_evidence_status": space.occupancy_evidence_status,
            "public_air_loop": space.public_air_loop,
            "office_doas": space.office_doas,
            "zone_hvac": space.zone_hvac,
            "occupancy": occupancy,
            "class_counts": class_counts,
        }
        if load_available:
            energy = (energy_by_space or {})[space.name]
            output_row["heating_kw"] = _series(
                energy.get("heating_kw"), f"{space.name}:heating_kw"
            )
            output_row["cooling_kw"] = _series(
                energy.get("cooling_kw"), f"{space.name}:cooling_kw"
            )
        output_spaces[space.name] = output_row

    return {
        "schema_version": "idfrepair.airport-abm-viewer.v3",
        "scenario_id": str(detail.get("scenario_id", "")),
        "period_id": "representative-day",
        "seed": int(detail.get("seed", 0)),
        "minutes_per_step": 15,
        "timestamps": labels,
        "agent_classes": list(_CLASS_NAMES),
        "space_count": len(output_spaces),
        "load_data_available": load_available,
        "semantics": {
            "method": "directed_discrete_event_abm",
            "measured_flow_claim": False,
            "walking_trajectory_claim": False,
            "controlled_parameters": True,
        },
        "spaces": output_spaces,
        "flows": _flow_rows(detail=detail, spaces=space_rows, access=access),
        "space_edge_flows": _space_edge_flow_rows(
            detail=detail,
            spaces=space_rows,
            access=access,
        ),
    }


def write_viewer_payload(
    *,
    mapping_path: str | Path,
    detail_path: str | Path,
    access_path: str | Path,
    output_path: str | Path,
    energy_sql_path: str | Path | None = None,
    environment_period_index: int | None = None,
) -> Path:
    spaces = load_space_mapping(mapping_path)
    with gzip.open(detail_path, "rt", encoding="utf-8") as handle:
        detail = json.load(handle)
    access = json.loads(Path(access_path).read_text(encoding="utf-8"))
    if (energy_sql_path is None) != (environment_period_index is None):
        raise ValueError("energy SQL and environment period index must be provided together")
    energy = None
    if energy_sql_path is not None and environment_period_index is not None:
        from .energyplus_coupling import extract_viewer_energy_by_space

        energy = extract_viewer_energy_by_space(
            energy_sql_path,
            spaces=spaces,
            environment_period_index=environment_period_index,
        )
    payload = build_viewer_payload(
        spaces=spaces,
        detail=detail,
        access=access,
        energy_by_space=energy,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return destination
