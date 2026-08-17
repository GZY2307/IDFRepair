"""提供 DOE/PNNL Prototype 身份解析、天气映射与 HVAC 拓扑审计原语。

parse_prototype_identity(): 从路径解析可追溯的源模型身份。
build_topology_profile(): 从类型化 HVAC 图构建名称不变的拓扑画像。
audit_prototype_file(): 审计单个 IDF 的版本、身份、天气和拓扑。
summarize_inventory(): 汇总 corpus、clone group 与 topology cluster。
select_feasibility_bases(): 按独立拓扑选择可资格化 base。
write_inventory_artifacts(): 写出轻量 manifest 和审计摘要。

源 family 身份与 HVAC 拓扑身份保持分离；inventory 保留气候和规范 clone，
拓扑 fingerprint 则排除实例名称和数值运行参数。
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable

from idfrepair.io.idf import IDFDocument, canonical, parse_idf
from idfrepair.knowledge.hvac_graph import build_hvac_graph
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.runtime.discovery import normalize_version


_COMMERCIAL_CLIMATE_ZONES = {
    "HoChiMinh": "0A",
    "Dubai": "0B",
    "Miami": "1A",
    "NewDelhi": "1B",
    "Tampa": "2A",
    "Tucson": "2B",
    "Atlanta": "3A",
    "ElPaso": "3B",
    "SanDiego": "3C",
    "NewYork": "4A",
    "Albuquerque": "4B",
    "Seattle": "4C",
    "Buffalo": "5A",
    "Denver": "5B",
    "PortAngeles": "5C",
    "Rochester": "6A",
    "GreatFalls": "6B",
    "InternationalFalls": "7",
    "Fairbanks": "8",
}

_RESIDENTIAL_CLIMATE_CITIES = {
    "1AWH": "Miami",
    "1AWHT": "Honolulu",
    "1AWHTS": "Honolulu",
    "2AWH": "Tampa",
    "2B": "Tucson",
    "3A": "Atlanta",
    "3AWH": "Montgomery",
    "3B": "ElPaso",
    "3C": "SanDiego",
    "4A": "NewYork",
    "4B": "Albuquerque",
    "4C": "Seattle",
    "5A": "Buffalo",
    "5B": "Denver",
    "5C": "PortAngeles",
    "6A": "Rochester",
    "6B": "GreatFalls",
    "7": "InternationalFalls",
    "8": "Fairbanks",
}

_WEATHER_STATIONS = {
    "Albuquerque": "723650",
    "Atlanta": "722190",
    "Baltimore": "724060",
    "Birmingham": "722280",
    "Boise": "726810",
    "Buffalo": "725280",
    "Burlington": "726170",
    "Charleston": "722080",
    "Chicago": "725300",
    "Denver": "724695",
    "Dubai": "411940",
    "Duluth": "727450",
    "ElPaso": "722700",
    "Fairbanks": "702610",
    "GreatFalls": "727750",
    "Helena": "727720",
    "HoChiMinh": "489000",
    "Honolulu": "911820",
    "Houston": "722430",
    "InternationalFalls": "727470",
    "Jackson": "722350",
    "Memphis": "723340",
    "Miami": "722020",
    "Montgomery": "722260",
    "NewDelhi": "421820",
    "NewYork": "744860",
    "Phoenix": "722780",
    "PortAngeles": "727885",
    "Rochester": "726440",
    "Salem": "726940",
    "SanDiego": "722904",
    "SanFrancisco": "724940",
    "Seattle": "727930",
    "Tampa": "747880",
    "Tucson": "722745",
}

_STANDARD = re.compile(
    r"^ASHRAE901_(?P<prototype>[^_]+)_STD(?P<label>[^_]+)_(?P<city>[^.]+)\.idf$",
    re.IGNORECASE,
)
_IECC = re.compile(
    r"^IECC_(?P<prototype>[^_]+)_STD(?P<edition>\d{4})_(?P<city>[^.]+)\.idf$",
    re.IGNORECASE,
)
_APPENDIX_G = re.compile(
    r"^(?P<edition>\d{4})AppG(?P<variant>Proposed|Baseline)$",
    re.IGNORECASE,
)
_MANUFACTURED = re.compile(
    r"^(?P<prototype>MS|SS)_(?P<city>[^_]+)_(?P<climate>[^_]+)_"
    r"(?P<edition>HUD|tier1|tier2)_(?P<system>[^.]+)\.idf$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PrototypeIdentity:
    """表示由文件名解析、且不依赖文件内容的源模型身份。"""

    corpus: str
    code_family: str
    prototype: str
    code_edition: str
    variant: str
    city: str | None
    climate_zone: str
    system_type: str | None
    foundation_type: str | None
    expected_version: str

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def parse_prototype_identity(path: Path | str) -> PrototypeIdentity:
    """解析本地 DOE/PNNL 文件名，不据此推断样本独立性。"""

    source = Path(path)
    name = source.name
    parent = source.parent.name.casefold()

    if parent == "iecc_all":
        match = _IECC.fullmatch(name)
        if match is None:
            raise ValueError(f"unrecognized IECC prototype filename: {name}")
        city = match.group("city")
        return PrototypeIdentity(
            corpus="commercial_iecc",
            code_family="IECC",
            prototype=match.group("prototype"),
            code_edition=match.group("edition"),
            variant="standard",
            city=city,
            climate_zone=_COMMERCIAL_CLIMATE_ZONES[city],
            system_type=None,
            foundation_type=None,
            expected_version="22.1",
        )

    if parent in {"ashrae901_all", "appendixg_all"}:
        match = _STANDARD.fullmatch(name)
        if match is None:
            raise ValueError(f"unrecognized ASHRAE prototype filename: {name}")
        city = match.group("city")
        label = match.group("label")
        if parent == "appendixg_all":
            appendix = _APPENDIX_G.fullmatch(label)
            if appendix is None:
                raise ValueError(f"unrecognized Appendix G label: {label}")
            edition = appendix.group("edition")
            variant = f"appendix_g_{appendix.group('variant').casefold()}"
            corpus = "commercial_appendix_g"
            family = "ASHRAE90.1 Appendix G"
        else:
            if not label.isdigit() or len(label) != 4:
                raise ValueError(f"unrecognized ASHRAE edition: {label}")
            edition = label
            variant = "standard"
            corpus = "commercial_standard"
            family = "ASHRAE90.1"
        return PrototypeIdentity(
            corpus=corpus,
            code_family=family,
            prototype=match.group("prototype"),
            code_edition=edition,
            variant=variant,
            city=city,
            climate_zone=_COMMERCIAL_CLIMATE_ZONES[city],
            system_type=None,
            foundation_type=None,
            expected_version="22.1",
        )

    if parent == "resstd_allcodes":
        parts = name.removesuffix(".idf").split("+")
        if (
            len(parts) != 6
            or parts[0].casefold() != "us"
            or not parts[2].casefold().startswith("cz")
            or not parts[5].casefold().startswith("iecc_")
        ):
            raise ValueError(f"unrecognized residential prototype filename: {name}")
        climate_zone = parts[2][2:]
        return PrototypeIdentity(
            corpus="residential",
            code_family="IECC",
            prototype=parts[1],
            code_edition=parts[5].split("_", 1)[1],
            variant="standard",
            city=_RESIDENTIAL_CLIMATE_CITIES.get(climate_zone),
            climate_zone=climate_zone,
            system_type=parts[3],
            foundation_type=parts[4],
            expected_version="23.1",
        )

    if parent == "all_completeset":
        match = _MANUFACTURED.fullmatch(name)
        if match is None:
            raise ValueError(f"unrecognized manufactured-housing filename: {name}")
        edition = match.group("edition")
        return PrototypeIdentity(
            corpus="manufactured_housing",
            code_family="DOE Manufactured Housing",
            prototype=match.group("prototype").upper(),
            code_edition=edition,
            variant=edition.casefold(),
            city=match.group("city"),
            climate_zone=match.group("climate"),
            system_type=match.group("system"),
            foundation_type=None,
            expected_version="8.0",
        )

    raise ValueError(f"unrecognized prototype corpus: {source}")


def clone_group_key(identity: PrototypeIdentity) -> tuple[str, ...]:
    """返回排除气候变体后的源 family 分组键。"""

    return (
        identity.corpus,
        identity.prototype,
        identity.code_edition,
        identity.variant,
        identity.system_type or "",
        identity.foundation_type or "",
    )


def resolve_weather(
    identity: PrototypeIdentity,
    search_roots: Iterable[Path | str],
) -> Path | None:
    """按气象站编号解析 EPW，不使用模糊城市文本匹配。"""

    if identity.city is None:
        return None
    station = _WEATHER_STATIONS.get(identity.city)
    if station is None:
        return None
    matches: list[Path] = []
    for root_value in search_roots:
        root = Path(root_value)
        if not root.is_dir():
            continue
        try:
            matches.extend(
                path for path in root.rglob("*.epw")
                if station in path.name and path.is_file()
            )
        except OSError:
            continue
    return sorted(set(matches), key=lambda path: str(path).casefold())[0] if matches else None


_STRUCTURAL_OBJECT_TYPES = {
    "airloophvac",
    "airloophvac:returnpath",
    "airloophvac:supplypath",
    "airloophvac:zonesplitter",
    "airloophvac:zonemixer",
    "airloophvac:supplyplenum",
    "airloophvac:returnplenum",
    "branch",
    "branchlist",
    "condenserloop",
    "connector:mixer",
    "connector:splitter",
    "connectorlist",
    "nodelist",
    "plantloop",
    "zonehvac:airdistributionunit",
    "zonehvac:equipmentconnections",
    "zonehvac:equipmentlist",
}
_LOOP_TYPES = {"airloophvac", "plantloop", "condenserloop"}


def _ordered_relation_sequences(
    rows: Iterable[dict[str, object]],
    *,
    type_key: str,
    index_key: str,
) -> list[list[str]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["container_id"])].append(row)
    sequences = [
        [
            canonical(str(row[type_key]))
            for row in sorted(group, key=lambda item: int(item[index_key]))
        ]
        for group in grouped.values()
    ]
    return sorted(sequences)


def build_topology_profile(
    document: IDFDocument,
    idd: IDDSchema,
) -> dict[str, object]:
    """从类型化图构建实例名称不变的 HVAC 拓扑画像。"""

    graph = build_hvac_graph(document, idd)
    object_types = Counter(canonical(obj.object_type) for obj in document.objects)
    loop_counts = {
        object_type: object_types[object_type]
        for object_type in sorted(_LOOP_TYPES)
        if object_types[object_type]
    }
    structural_counts = {
        object_type: object_types[object_type]
        for object_type in sorted(_STRUCTURAL_OBJECT_TYPES)
        if object_types[object_type]
    }

    port_owners = {
        str(port["object_id"]): canonical(str(port["object_type"]))
        for port in graph["ports"]
    }
    component_counts = Counter(port_owners.values())
    port_signatures = Counter(
        (
            canonical(str(port["object_type"])),
            str(port["medium"]),
            str(port["role"]),
        )
        for port in graph["ports"]
    )
    port_types = {
        str(port["port_id"]): canonical(str(port["object_type"]))
        for port in graph["ports"]
    }
    flow_signatures = Counter(
        (
            port_types[str(edge["source_port_id"])],
            port_types[str(edge["target_port_id"])],
            str(edge["medium"]),
        )
        for edge in graph["flow_edges"]
    )

    return {
        "schema_version": "idfrepair.semantic-topology.v1",
        "zone_count": object_types["zone"],
        "loop_counts": loop_counts,
        "structural_object_counts": structural_counts,
        "component_type_counts": dict(sorted(component_counts.items())),
        "port_signatures": [
            [*signature, count]
            for signature, count in sorted(port_signatures.items())
        ],
        "branch_sequences": _ordered_relation_sequences(
            graph["branch_relations"],
            type_key="component_type",
            index_key="component_type_index",
        ),
        "equipment_sequences": _ordered_relation_sequences(
            graph["equipment_relations"],
            type_key="equipment_type",
            index_key="equipment_type_index",
        ),
        "flow_type_edges": [
            [*signature, count]
            for signature, count in sorted(flow_signatures.items())
        ],
        "port_count": len(graph["ports"]),
        "fluid_node_count": len(graph["fluid_nodes"]),
        "typed_flow_count": len(graph["flow_edges"]),
    }


def topology_fingerprint(profile: dict[str, object]) -> str:
    """返回拓扑画像的确定性身份。"""

    payload = json.dumps(
        profile,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def audit_prototype_file(
    path: Path | str,
    *,
    schemas: dict[str, IDDSchema],
    weather_roots: Iterable[Path | str],
    include_topology: bool,
) -> dict[str, object]:
    """审计单个源文件，且不把成功解析误认为 clean qualification。"""

    source = Path(path)
    identity = parse_prototype_identity(source)
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    document = parse_idf(text)
    actual_version = normalize_version(document.version)
    expected_version = normalize_version(identity.expected_version)
    weather_path = resolve_weather(identity, weather_roots)
    profile: dict[str, object] | None = None
    fingerprint: str | None = None
    if not include_topology:
        topology_status = "not_requested"
    else:
        schema = schemas.get(actual_version)
        if schema is None:
            topology_status = "schema_unavailable"
        else:
            profile = build_topology_profile(document, schema)
            fingerprint = topology_fingerprint(profile)
            topology_status = "profiled"

    return {
        "source_path": str(source),
        "file_size_bytes": source.stat().st_size,
        **identity.as_dict(),
        "actual_version": actual_version,
        "version_match": actual_version == expected_version,
        "source_clone_group": "|".join(clone_group_key(identity)),
        "weather_path": str(weather_path) if weather_path is not None else "",
        "weather_status": "available" if weather_path is not None else "missing",
        "topology_status": topology_status,
        "topology_fingerprint": fingerprint or "",
        "topology_profile": profile,
        "clean_run_status": "not_qualified",
    }


def summarize_inventory(records: Iterable[dict[str, object]]) -> dict[str, object]:
    """汇总 inventory、source clone、拓扑与 qualification 证据。"""

    rows = tuple(records)
    clone_groups = {str(row["source_clone_group"]) for row in rows}
    topology_rows = [row for row in rows if row.get("topology_fingerprint")]
    topology_clusters = {str(row["topology_fingerprint"]) for row in topology_rows}
    clone_topologies: dict[str, set[str]] = defaultdict(set)
    for row in topology_rows:
        clone_topologies[str(row["source_clone_group"])].add(
            str(row["topology_fingerprint"])
        )

    def counts(field: str) -> dict[str, int]:
        return dict(sorted(Counter(str(row[field]) for row in rows).items()))

    return {
        "schema_version": "idfrepair.prototype-inventory-summary.v1",
        "file_count": len(rows),
        "total_size_bytes": sum(int(row["file_size_bytes"]) for row in rows),
        "corpus_counts": counts("corpus"),
        "actual_version_counts": counts("actual_version"),
        "weather_status_counts": counts("weather_status"),
        "topology_status_counts": counts("topology_status"),
        "clean_run_status_counts": counts("clean_run_status"),
        "source_clone_group_count": len(clone_groups),
        "topology_profiled_model_count": len(topology_rows),
        "topology_cluster_count": len(topology_clusters),
        "clone_groups_with_one_topology": sum(
            len(fingerprints) == 1 for fingerprints in clone_topologies.values()
        ),
        "clone_groups_with_multiple_topologies": sum(
            len(fingerprints) > 1 for fingerprints in clone_topologies.values()
        ),
        "maximum_topologies_per_clone_group": max(
            (len(fingerprints) for fingerprints in clone_topologies.values()),
            default=0,
        ),
    }


def select_feasibility_bases(
    records: Iterable[dict[str, object]],
    *,
    prototypes: Iterable[str],
    code_edition: str,
    city: str,
) -> tuple[dict[str, object], ...]:
    """选择天气可用且拓扑身份互异的商用 base。"""

    rows = tuple(records)
    selected: list[dict[str, object]] = []
    seen_fingerprints: set[str] = set()
    for prototype in prototypes:
        candidates = sorted(
            (
                row for row in rows
                if row.get("corpus") == "commercial_standard"
                and row.get("prototype") == prototype
                and str(row.get("code_edition")) == code_edition
                and row.get("city") == city
                and row.get("weather_status") == "available"
                and row.get("topology_fingerprint")
            ),
            key=lambda row: str(row["source_path"]).casefold(),
        )
        if not candidates:
            continue
        candidate = candidates[0]
        fingerprint = str(candidate["topology_fingerprint"])
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        selected.append(candidate)
    return tuple(selected)


_MANIFEST_FIELDS = (
    "source_path",
    "file_size_bytes",
    "corpus",
    "code_family",
    "prototype",
    "code_edition",
    "variant",
    "city",
    "climate_zone",
    "system_type",
    "foundation_type",
    "expected_version",
    "actual_version",
    "version_match",
    "source_clone_group",
    "weather_path",
    "weather_status",
    "topology_status",
    "topology_fingerprint",
    "clean_run_status",
)


def _write_csv(path: Path, fields: tuple[str, ...], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_inventory_artifacts(
    records: Iterable[dict[str, object]],
    *,
    manifest_path: Path | str,
    profiles_path: Path | str,
    clusters_path: Path | str,
    summary_path: Path | str,
) -> None:
    """写出可审阅的轻量 inventory，不复制原始模型。"""

    rows = tuple(sorted(records, key=lambda row: str(row["source_path"]).casefold()))
    _write_csv(Path(manifest_path), _MANIFEST_FIELDS, rows)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        fingerprint = str(row.get("topology_fingerprint") or "")
        if fingerprint:
            grouped[fingerprint].append(row)
    profile_rows = [
        {
            "fingerprint": fingerprint,
            "model_count": len(members),
            "profile": members[0]["topology_profile"],
        }
        for fingerprint, members in sorted(grouped.items())
    ]
    profile_payload = {
        "schema_version": "idfrepair.semantic-topology-profile-registry.v1",
        "profiles": profile_rows,
    }
    profile_target = Path(profiles_path)
    profile_target.parent.mkdir(parents=True, exist_ok=True)
    profile_target.write_text(
        json.dumps(profile_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    cluster_fields = (
        "topology_fingerprint",
        "model_count",
        "source_clone_group_count",
        "corpora",
        "prototypes",
        "code_editions",
        "cities",
    )
    cluster_rows = []
    for fingerprint, members in sorted(grouped.items()):
        cluster_rows.append({
            "topology_fingerprint": fingerprint,
            "model_count": len(members),
            "source_clone_group_count": len({row["source_clone_group"] for row in members}),
            "corpora": ";".join(sorted({str(row["corpus"]) for row in members})),
            "prototypes": ";".join(sorted({str(row["prototype"]) for row in members})),
            "code_editions": ";".join(sorted({str(row["code_edition"]) for row in members})),
            "cities": ";".join(sorted({str(row["city"]) for row in members})),
        })
    _write_csv(Path(clusters_path), cluster_fields, cluster_rows)

    summary_target = Path(summary_path)
    summary_target.parent.mkdir(parents=True, exist_ok=True)
    summary_target.write_text(
        json.dumps(summarize_inventory(rows), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
