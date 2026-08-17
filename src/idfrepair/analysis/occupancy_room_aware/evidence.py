"""Room-aware People 参数、标准与机场文献的可机读证据台账。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from idfrepair.analysis.occupancy_room_aware.models import EvidenceStatus, RoomCategory
from idfrepair.analysis.occupancy_room_aware.source_audit import validate_source_audit


PROJECT_SOURCE_OSM_SHA256 = (
    "6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb"
)
PROJECT_NOTES_PAGE_03_SHA256 = (
    "36cf0feeb7e9c6fe8e798641b338446561bb709559c6ffc177f11e12d0defedf"
)
PROJECT_NOTES_PAGE_05_SHA256 = (
    "2589f13221cc7bfcf874182f702b8a3646e1348506ea7128bb6922a5dc4adb11"
)
PROJECT_NOTES_PAGE_06_SHA256 = (
    "236a34c4ce7c0770fe5ccfd0dca6a63970ac128b3542136b6dcc04415cd8966c"
)
PROJECT_NOTES_PAGE_07_SHA256 = (
    "1c9e49cd35f4c5fd082a0c020480e076c90bff40f836b0bbf582536efa7b34b6"
)
ASHRAE_ADDENDUM_URL = (
    "https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20"
    "guidelines/standards%20addenda/62_1_2022_ab_20231031.pdf"
)
ENERGYPLUS_23_1_IO_URL = (
    "https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v23.1.0/"
    "InputOutputReference.pdf"
)
ASHRAE_BREAKROOM_M2_PER_PERSON = 92.90304 / 25.0


@dataclass(frozen=True, slots=True)
class ParameterEvidence:
    """一个参数的数值、适用边界与采用决定。"""

    parameter_id: str
    category: str
    parameter: str
    value: float | None
    unit: str
    tier: EvidenceStatus
    source_id: str
    locator: str
    source_url: str
    source_sha256: str
    applicability: str
    confidence: str
    auto_fill_allowed: bool
    use_scope: str
    supports: str
    does_not_support: str


@dataclass(frozen=True, slots=True)
class LiteratureEvidence:
    """机场 occupancy 文献的最小可核查主张边界。"""

    source_id: str
    year: int
    authors: str
    title: str
    venue: str
    doi: str
    url: str
    access_level: str
    supports: str
    does_not_support: str
    transfer_decision: str = "NO_NUMERIC_TRANSFER"


def _parameter(
    parameter_id: str,
    category: str,
    parameter: str,
    value: float | None,
    unit: str,
    tier: EvidenceStatus,
    source_id: str,
    locator: str,
    *,
    source_url: str = "",
    source_sha256: str = "",
    applicability: str,
    confidence: str,
    auto_fill_allowed: bool,
    use_scope: str,
    supports: str,
    does_not_support: str,
) -> ParameterEvidence:
    return ParameterEvidence(
        parameter_id=parameter_id,
        category=category,
        parameter=parameter,
        value=value,
        unit=unit,
        tier=tier,
        source_id=source_id,
        locator=locator,
        source_url=source_url,
        source_sha256=source_sha256,
        applicability=applicability,
        confidence=confidence,
        auto_fill_allowed=auto_fill_allowed,
        use_scope=use_scope,
        supports=supports,
        does_not_support=does_not_support,
    )


def parameter_evidence_records() -> tuple[ParameterEvidence, ...]:
    """返回锁定的 People/OA 参数决定；不会从机场常识生成值。"""

    tier_b = EvidenceStatus.STANDARD_OR_LITERATURE_BACKED
    records: list[ParameterEvidence] = [
        _parameter(
            "density.office.project_notes",
            "office",
            "design_density_m2_per_person",
            6.0,
            "m2/person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 办公",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project office design row matches the explicit office name token.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="BASELINE_R_PEOPLE_ONLY",
            supports="Explicit office People design density in the reference derivative.",
            does_not_support="Measured staff attendance or an operational schedule.",
        ),
        _parameter(
            "density.commerce.project_notes",
            "commerce_retail",
            "design_density_m2_per_person",
            5.0,
            "m2/person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 一般商业",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project general-commerce row matches the explicit commerce token.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="BASELINE_R_PEOPLE_ONLY",
            supports="Explicit commerce People design density in the reference derivative.",
            does_not_support="A separate customer/staff split or measured operating demand.",
        ),
        _parameter(
            "density.dining.project_notes",
            "dining",
            "design_density_m2_per_person",
            2.5,
            "m2/person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 餐厅",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project dining row matches the explicit dining token.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="BASELINE_R_PEOPLE_ONLY",
            supports="Explicit dining People design density in the reference derivative.",
            does_not_support="Observed meal demand, dwell time, or staff/customer composition.",
        ),
        _parameter(
            "density.breakroom.ashrae",
            "breakroom",
            "design_density_m2_per_person",
            ASHRAE_BREAKROOM_M2_PER_PERSON,
            "m2/person",
            tier_b,
            "ASHRAE_62_1_2022_AB",
            "Table 6-1, General — Break rooms, 25 persons/1000 ft2",
            source_url=ASHRAE_ADDENDUM_URL,
            applicability="The OSM label is explicitly breakroom and no same-project density row exists.",
            confidence="MEDIUM_STANDARD_DEFAULT",
            auto_fill_allowed=True,
            use_scope="BASELINE_R_PEOPLE_ONLY",
            supports="A reference design density for explicitly labelled breakrooms.",
            does_not_support="Measured staff break attendance or airport-specific utilization.",
        ),
        _parameter(
            "density.hall.rejected",
            "terminal_hall",
            "design_density_m2_per_person",
            None,
            "m2/person",
            EvidenceStatus.DO_NOT_AUTOFILL,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, multiple non-equivalent hall rows",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="The source hall subtype is unresolved and the documented design rows span 2–10 m2/person.",
            confidence="REJECTED_AMBIGUOUS_TRANSFER",
            auto_fill_allowed=False,
            use_scope="PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK",
            supports="Keeping hall capacity unresolved and reporting the ambiguity.",
            does_not_support="Selecting one point density for every source-labelled hall.",
        ),
        _parameter(
            "density.restroom.rejected",
            "restroom",
            "design_density_m2_per_person",
            None,
            "m2/person",
            EvidenceStatus.DO_NOT_AUTOFILL,
            "SOURCE_OSM_AUDIT",
            "Terminal Model A room audit; restroom label without a dwell model",
            source_sha256=PROJECT_SOURCE_OSM_SHA256,
            applicability="Restroom occupancy duration and public linkage are unresolved in the source.",
            confidence="REJECTED_MISSING_DWELL_EVIDENCE",
            auto_fill_allowed=False,
            use_scope="PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK",
            supports="A bounded controlled schedule below the preserved source capacity.",
            does_not_support="Treating an office restroom template as measured passenger occupancy.",
        ),
        _parameter(
            "oa.office.project_notes",
            "office",
            "outdoor_air_per_person_m3_s_person",
            30.0 / 3600.0,
            "m3/s-person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 办公, 30 m3/(h-person)",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project office design value; evaluated outside the People-only baseline.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="REFERENCE_OA_IDEALLOADS_SENSITIVITY",
            supports="A separately labelled reference OA sensitivity.",
            does_not_support="Source AirLoop topology, DCV controls, or measured ventilation energy.",
        ),
        _parameter(
            "oa.commerce.project_notes",
            "commerce_retail",
            "outdoor_air_per_person_m3_s_person",
            30.0 / 3600.0,
            "m3/s-person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 一般商业, 30 m3/(h-person)",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project general-commerce value; evaluated outside the People-only baseline.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="REFERENCE_OA_IDEALLOADS_SENSITIVITY",
            supports="A separately labelled reference OA sensitivity.",
            does_not_support="Source AirLoop topology, DCV controls, or measured ventilation energy.",
        ),
        _parameter(
            "oa.dining.project_notes",
            "dining",
            "outdoor_air_per_person_m3_s_person",
            25.0 / 3600.0,
            "m3/s-person",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM05",
            "SJSM page 05, section 4.2, row 餐厅, 25 m3/(h-person)",
            source_sha256=PROJECT_NOTES_PAGE_05_SHA256,
            applicability="Same-project dining value; evaluated outside the People-only baseline.",
            confidence="HIGH_PROJECT_SPECIFIC",
            auto_fill_allowed=True,
            use_scope="REFERENCE_OA_IDEALLOADS_SENSITIVITY",
            supports="A separately labelled reference OA sensitivity.",
            does_not_support="Source AirLoop topology, DCV controls, or measured ventilation energy.",
        ),
        _parameter(
            "oa.breakroom.people.ashrae",
            "breakroom",
            "outdoor_air_per_person_m3_s_person",
            0.0025,
            "m3/s-person",
            tier_b,
            "ASHRAE_62_1_2022_AB",
            "Table 6-1, General — Break rooms, Rp=2.5 L/(s-person)",
            source_url=ASHRAE_ADDENDUM_URL,
            applicability="Reference ventilation value for an explicit breakroom label.",
            confidence="MEDIUM_STANDARD_DEFAULT",
            auto_fill_allowed=True,
            use_scope="REFERENCE_OA_IDEALLOADS_SENSITIVITY",
            supports="A separately labelled reference OA sensitivity.",
            does_not_support="Actual terminal OA delivery or demand control.",
        ),
        _parameter(
            "oa.breakroom.area.ashrae",
            "breakroom",
            "outdoor_air_per_area_m3_s_m2",
            0.0003,
            "m3/s-m2",
            tier_b,
            "ASHRAE_62_1_2022_AB",
            "Table 6-1, General — Break rooms, Ra=0.3 L/(s-m2)",
            source_url=ASHRAE_ADDENDUM_URL,
            applicability="Reference ventilation value for an explicit breakroom label.",
            confidence="MEDIUM_STANDARD_DEFAULT",
            auto_fill_allowed=True,
            use_scope="REFERENCE_OA_IDEALLOADS_SENSITIVITY",
            supports="A separately labelled reference OA sensitivity.",
            does_not_support="Actual terminal OA delivery or demand control.",
        ),
        _parameter(
            "exhaust.restroom.project_notes",
            "restroom",
            "exhaust_air_changes_per_hour",
            15.0,
            "1/h",
            tier_b,
            "PROJECT_HVAC_NOTES_SJSM06",
            "SJSM page 06, mechanical ventilation table, employee/public restroom",
            source_sha256=PROJECT_NOTES_PAGE_06_SHA256,
            applicability="Same-project exhaust design note applies to labelled restrooms.",
            confidence="HIGH_PROJECT_SPECIFIC_BUT_UNMAPPED",
            auto_fill_allowed=False,
            use_scope="DOCUMENTED_NOT_IMPLEMENTED",
            supports="Reporting that restroom exhaust design evidence exists.",
            does_not_support="Synthesizing exhaust equipment or source HVAC topology in the simplified OSM.",
        ),
        _parameter(
            "people.semantics.energyplus23_1",
            "all_spaces",
            "people_object_semantics",
            None,
            "EnergyPlus fields",
            tier_b,
            "ENERGYPLUS_23_1_IO_REFERENCE",
            "Group Internal Gains — People; Schedule:File",
            source_url=ENERGYPLUS_23_1_IO_URL,
            applicability="EnergyPlus 23.1 is the locked simulation runtime.",
            confidence="HIGH_OFFICIAL_DOCUMENTATION",
            auto_fill_allowed=False,
            use_scope="COMPILER_SEMANTICS",
            supports="People count method, number schedule, activity, radiant/sensible, and CO2 field interpretation.",
            does_not_support="Any airport-specific numerical People value.",
        ),
    ]
    for category in RoomCategory:
        records.append(
            _parameter(
                f"people_heat.{category.value}.source_preserve",
                category.value,
                "people_heat_and_co2_fields",
                None,
                "source fields",
                EvidenceStatus.SOURCE_BACKED,
                "SOURCE_OSM_AUDIT",
                "Per-Space effective PeopleDefinition and activity schedule",
                source_sha256=PROJECT_SOURCE_OSM_SHA256,
                applicability="The reference derivative changes design count/schedule only and preserves each source heat/CO2 field.",
                confidence="HIGH_SOURCE_EXACT",
                auto_fill_allowed=False,
                use_scope="PRESERVE_SOURCE",
                supports="Preserving activity, fraction radiant, sensible handling, and CO2 generation.",
                does_not_support="Claiming zone-specific measured metabolism.",
            )
        )
        records.append(
            _parameter(
                f"schedule.{category.value}.controlled",
                category.value,
                "occupancy_schedule_fraction",
                None,
                "fraction at 15-minute timestep",
                EvidenceStatus.CONTROLLED_SCENARIO_ASSUMPTION,
                "ROOM_AWARE_PROTOCOL",
                f"Controlled profile definition for {category.value}",
                applicability="Used only for deterministic counterfactuals without operational observations.",
                confidence="CONTROLLED_NOT_MEASURED",
                auto_fill_allowed=True,
                use_scope="CONTROLLED_SCENARIO_ONLY",
                supports="Distinct room-class profiles and conservation tests.",
                does_not_support="A calibrated or predicted terminal operating schedule.",
            )
        )
    return tuple(records)


def literature_evidence_records() -> tuple[LiteratureEvidence, ...]:
    """返回已核对 DOI/出版社元数据的机场 occupancy 文献边界。"""

    rows = (
        LiteratureEvidence(
            "SINHA_2019_IBPSA",
            2019,
            "Kapil Sinha; Nusrat Ali; Rajasekar Elangovan",
            "An Agent-based Dynamic Occupancy Schedule Model for Prediction of HVAC Energy Demand in an Airport Terminal Building",
            "Building Simulation Conference Proceedings",
            "10.26868/25222708.2019.211133",
            "https://doi.org/10.26868/25222708.2019.211133",
            "DOI_METADATA_AND_PROCEEDINGS_ABSTRACT",
            "Airport zone occupancy profiles can differ and can be coupled to energy simulation.",
            "The profile or calibration of Terminal Model A.",
        ),
        LiteratureEvidence(
            "LIU_2019_BUILDENV",
            2019,
            "Xiaochen Liu; Lingshan Li; Xiaohua Liu; Tao Zhang",
            "Analysis of passenger flow and its influences on HVAC systems: An agent based simulation in a Chinese hub airport terminal",
            "Building and Environment 154, 55–67",
            "10.1016/j.buildenv.2019.03.011",
            "https://doi.org/10.1016/j.buildenv.2019.03.011",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Passenger distributions can be heterogeneous in time and space and affect occupancy-linked OA demand.",
            "A transferable passenger density, route, or HVAC response for this simplified OSM.",
        ),
        LiteratureEvidence(
            "SINHA_2021_BUILDENV",
            2021,
            "Kapil Sinha; Nusrat Ali; E. Rajasekar",
            "Evaluating the dynamics of occupancy heat gains in a mid-sized airport terminal through agent-based modelling",
            "Building and Environment 204, 108147",
            "10.1016/j.buildenv.2021.108147",
            "https://doi.org/10.1016/j.buildenv.2021.108147",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Occupancy heat gains may vary dynamically and by terminal zone.",
            "Direct transfer of metabolic, sensible, or latent values as facts for this terminal.",
        ),
        LiteratureEvidence(
            "GU_2022_SCS",
            2022,
            "Xianliang Gu; Jingchao Xie; Chengyang Huang; Kai Ma; Jiaping Liu",
            "Prediction of the spatiotemporal passenger distribution of a large airport terminal and its impact on energy simulation",
            "Sustainable Cities and Society 78, 103619",
            "10.1016/j.scs.2021.103619",
            "https://doi.org/10.1016/j.scs.2021.103619",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Zone-resolved spatiotemporal passenger distributions can alter simulated terminal loads.",
            "The source-room mapping or occupancy observations for Terminal Model A.",
        ),
        LiteratureEvidence(
            "GU_2022_IBE",
            2022,
            "Xianliang Gu; Jingchao Xie; Chengyang Huang; Jiaping Liu",
            "A spatiotemporal passenger distribution model for airport terminal energy simulation",
            "Indoor and Built Environment 31(7), 1834–1857",
            "10.1177/1420326X221074222",
            "https://doi.org/10.1177/1420326X221074222",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Operational-data-informed zone schedules and annual energy coupling have established precedent.",
            "Use of that airport's schedules as measured data for this model.",
        ),
        LiteratureEvidence(
            "MA_2024_SETA",
            2024,
            "Kai Ma; Dan Wang; Yuying Sun; Wei Wang; Xianliang Gu",
            "Model predictive control for thermal comfort and energy optimization of an air handling unit system in airport terminals using occupant feedback",
            "Sustainable Energy Technologies and Assessments 65, 103790",
            "10.1016/j.seta.2024.103790",
            "https://doi.org/10.1016/j.seta.2024.103790",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Occupant-based terminal control has been evaluated on a validated air-handling-unit model.",
            "A real control system, MPC result, or HVAC topology for Terminal Model A.",
        ),
        LiteratureEvidence(
            "CONG_2025_BUILDENV",
            2025,
            "Mingyang Cong; Zheng Li; Yaling Wu; Qunshan Lu; Mei Li; Zhigang Zhou; Dayi Yang; Jing Liu",
            "Evaluating and optimizing energy and comfort performance in airport cooling systems through dynamic occupancy modeling and time-series clustering",
            "Building and Environment 274, 112781",
            "10.1016/j.buildenv.2025.112781",
            "https://doi.org/10.1016/j.buildenv.2025.112781",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "High-resolution spatiotemporal occupancy and zoning have current airport BEM precedent.",
            "A cluster model or cooling system transferable without source topology and data.",
        ),
        LiteratureEvidence(
            "TANG_2025_BUILDENV",
            2025,
            "Hao Tang; Juan Yu; Yang Geng; Xue Liu; Zujian Huang; Yuren Yang; Zhe Wang; Ying Chen; Borong Lin",
            "Enhancing occupant-centric ventilation control in airport terminals: A predictive optimization framework integrating agent-based simulation",
            "Building and Environment 276, 112829",
            "10.1016/j.buildenv.2025.112829",
            "https://doi.org/10.1016/j.buildenv.2025.112829",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Multi-zone occupant-centric airport ventilation control is established prior work.",
            "Permission to invent DCV, controls, or real equipment in Terminal Model A.",
        ),
        LiteratureEvidence(
            "MA_2026_RSER",
            2026,
            "Kai Ma; Yuying Sun; Wei Wang; Xianliang Gu",
            "Dynamic occupants, indoor environmental quality, and energy systems control at airports: A systematic review",
            "Renewable and Sustainable Energy Reviews 226, 116287",
            "10.1016/j.rser.2025.116287",
            "https://doi.org/10.1016/j.rser.2025.116287",
            "PUBLISHER_METADATA_AND_ABSTRACT",
            "Dynamic airport occupancy, IEQ, and energy-control coupling form an established research field.",
            "A novelty claim for dynamic airport occupancy or occupancy-driven HVAC.",
        ),
    )
    return rows


def validate_evidence_registry(
    parameters: Sequence[ParameterEvidence],
    literature: Sequence[LiteratureEvidence],
) -> None:
    """拒绝不完整数值、重复身份与无边界的文献记录。"""

    ids = [row.parameter_id for row in parameters]
    if len(ids) != len(set(ids)):
        raise ValueError("parameter_evidence_id_duplicate")
    allowed_categories = {category.value for category in RoomCategory} | {"all_spaces"}
    for row in parameters:
        if row.category not in allowed_categories:
            raise ValueError(f"parameter_category_invalid:{row.parameter_id}")
        if row.value is not None:
            complete = (
                math.isfinite(row.value)
                and bool(row.unit)
                and bool(row.source_id)
                and bool(row.locator)
                and bool(row.source_url or row.source_sha256)
                and bool(row.applicability)
                and bool(row.confidence)
                and bool(row.use_scope)
            )
            if not complete:
                raise ValueError(f"numeric_evidence_incomplete:{row.parameter_id}")
        if row.tier is EvidenceStatus.DO_NOT_AUTOFILL and (
            row.value is not None or row.auto_fill_allowed
        ):
            raise ValueError(f"do_not_autofill_violation:{row.parameter_id}")
        if not row.supports or not row.does_not_support:
            raise ValueError(f"claim_boundary_missing:{row.parameter_id}")

    dois = [row.doi.lower() for row in literature]
    if len(dois) != len(set(dois)):
        raise ValueError("literature_doi_duplicate")
    for row in literature:
        if not all((row.title, row.venue, row.doi, row.url, row.supports, row.does_not_support)):
            raise ValueError(f"literature_incomplete:{row.source_id}")
        if row.transfer_decision != "NO_NUMERIC_TRANSFER":
            raise ValueError(f"literature_numeric_transfer_forbidden:{row.source_id}")


def _unique(values: Sequence[Any]) -> str:
    return " | ".join(sorted({str(value) for value in values if value not in (None, "")}))


def _md_cell(value: Any) -> str:
    """把 registry 的多值分隔符转换为 table-safe 换行。"""

    return str(value).replace("|", "<br>").replace("\n", " ")


def _fmt(value: Any, digits: int = 8) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _current_category(audit: Mapping[str, Any], category: str) -> dict[str, Any]:
    rows = [row for row in audit["spaces"] if row["room_category"] == category]
    area = sum(float(row.get("floor_area_m2") or 0.0) for row in rows)
    people = sum(float(row.get("design_people") or 0.0) for row in rows)
    sources = [source for row in rows for source in row.get("people_sources", [])]
    definitions = [
        source.get("definition", {}) for source in sources if isinstance(source, Mapping)
    ]
    return {
        "space_count": len(rows),
        "floor_area_m2": area,
        "design_people": people,
        "people_per_m2": people / area if area else None,
        "m2_per_person": area / people if people else None,
        "current_space_type": _unique([row.get("effective_space_type") for row in rows]),
        "current_people_density": _unique(
            [
                f"{definition.get('method')}={_fmt(definition.get('value'))}"
                for definition in definitions
            ]
        ),
        "current_people_schedule": _unique(
            [source.get("count_schedule") for source in sources]
        ),
        "current_activity_schedule": _unique(
            [source.get("activity_schedule") for source in sources]
        ),
        "current_oa_definition": _unique(
            [
                row.get("oa", {}).get("name")
                for row in rows
                if isinstance(row.get("oa"), Mapping)
            ]
        ),
    }


def _evidence_map(
    parameters: Sequence[ParameterEvidence],
) -> dict[tuple[str, str], ParameterEvidence]:
    return {(row.category, row.parameter): row for row in parameters}


ROOM_RULES = {
    "terminal_hall": "(?<![A-Za-z])hall(?![A-Za-z])",
    "office": "(?<![A-Za-z])office(?![A-Za-z])",
    "commerce_retail": "(?<![A-Za-z])commerce(?![A-Za-z])",
    "dining": "(?<![A-Za-z])dining(?![A-Za-z])",
    "restroom": "(?<![A-Za-z])restroom(?![A-Za-z])",
    "breakroom": "(?<![A-Za-z])breakroom(?![A-Za-z])",
}


SCHEDULE_DESCRIPTIONS = {
    "terminal_hall": "15-minute controlled public profile; temporal/spatial redistribution target",
    "office": "15-minute staff workday profile; bitwise fixed in public scenarios",
    "commerce_retail": "15-minute controlled operating/public-demand profile; unsplit public-facing class",
    "dining": "15-minute controlled meal-period profile; unsplit public-facing class",
    "restroom": "15-minute bounded profile linked to public presence; no dwell-time claim",
    "breakroom": "15-minute intermittent staff break profile; bitwise fixed in public scenarios",
}


UNRESOLVED = {
    "terminal_hall": "Source room subtype and operational flow are unresolved; source design count is retained as capacity fallback.",
    "office": "Staff attendance is controlled, not measured; one IT_Room metadata conflict retains source People parameters.",
    "commerce_retail": "Customer/staff composition and operating records are unavailable.",
    "dining": "Diner/staff composition and meal demand are unavailable.",
    "restroom": "No occupancy dwell model; documented exhaust cannot be mapped to source HVAC topology.",
    "breakroom": "Standard default is not measured airport staff utilization.",
}


def build_room_function_registry(
    audit: Mapping[str, Any],
    parameters: Sequence[ParameterEvidence],
) -> list[dict[str, Any]]:
    """把源审计与参数决定合成六行 registry。"""

    validate_source_audit(audit)
    evidence = _evidence_map(parameters)
    rows: list[dict[str, Any]] = []
    for category in (item.value for item in RoomCategory):
        current = _current_category(audit, category)
        density = evidence[(category, "design_density_m2_per_person")]
        oa_rows = [
            row
            for row in parameters
            if row.category == category and row.parameter.startswith("outdoor_air_")
        ]
        provenance = [density.source_id]
        provenance.extend(row.source_id for row in oa_rows)
        proposed_density = (
            f"{_fmt(density.value)} {density.unit}"
            if density.value is not None
            else "PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK"
        )
        rows.append(
            {
                "category": category,
                "source_name_rule": ROOM_RULES[category],
                **current,
                "proposed_people_model": f"one explicit People object per Space; {proposed_density}",
                "proposed_occupancy_schedule_evidence": (
                    f"{SCHEDULE_DESCRIPTIONS[category]} [TIER_C_CONTROLLED_NOT_MEASURED]"
                ),
                "proposed_design_density_evidence": (
                    f"{density.tier.value}; {density.source_id}; {density.locator}"
                ),
                "proposed_activity_evidence": "preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED]",
                "main_oa_model": "preserve source OA in People-only S/R comparison",
                "reference_oa_evidence": _unique(
                    [f"{row.source_id}: {_fmt(row.value)} {row.unit}" for row in oa_rows]
                )
                or "DO_NOT_AUTOFILL",
                "confidence": density.confidence,
                "provenance": _unique(provenance),
                "auto_fill_allowed": density.auto_fill_allowed,
                "unresolved_assumptions": UNRESOLVED[category],
            }
        )
    return rows


ROOM_REGISTRY_FIELDS = (
    "category",
    "source_name_rule",
    "space_count",
    "floor_area_m2",
    "design_people",
    "people_per_m2",
    "m2_per_person",
    "current_space_type",
    "current_people_density",
    "current_people_schedule",
    "current_activity_schedule",
    "current_oa_definition",
    "proposed_people_model",
    "proposed_occupancy_schedule_evidence",
    "proposed_design_density_evidence",
    "proposed_activity_evidence",
    "main_oa_model",
    "reference_oa_evidence",
    "confidence",
    "provenance",
    "auto_fill_allowed",
    "unresolved_assumptions",
)


def _registry_markdown(rows: Sequence[Mapping[str, Any]], audit: Mapping[str, Any]) -> str:
    lines = [
        "# Room Function Registry",
        "",
        "**Status:** `SOURCE_BACKED_SIX_CATEGORY_REGISTRY`",
        "",
        "The registry binds each of 304 source Spaces to one room category using only",
        "an explicit `OS:Space.Name` token. It does not infer airport subfunctions from",
        "geometry, orientation, adjacency, or convention. Values marked Tier C are",
        "controlled and not measured.",
        "",
        f"Source alias: Terminal Model A · SHA-256 `{audit['source_sha256_after']}`",
        "",
        "| Category | Spaces | Area (m²) | Source design people | Proposed People model | Schedule evidence | Confidence | Auto-fill |",
        "|---|---:|---:|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['category']} | {row['space_count']} | {_fmt(row['floor_area_m2'], 3)} | "
            f"{_fmt(row['design_people'], 3)} | {row['proposed_people_model']} | "
            f"{row['proposed_occupancy_schedule_evidence']} | {row['confidence']} | "
            f"{_fmt(row['auto_fill_allowed'])} |"
        )
    lines.extend(
        [
            "",
            "## Current source metadata and proposed evidence",
            "",
            "| Category | Current SpaceType(s) | Current People density | Current schedule(s) | Activity evidence | Main OA | Reference OA |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['category']} | {_md_cell(row['current_space_type'])} | "
            f"{_md_cell(row['current_people_density'])} | "
            f"{_md_cell(row['current_people_schedule'])} | "
            f"{_md_cell(row['proposed_activity_evidence'])} | "
            f"{_md_cell(row['main_oa_model'])} | {_md_cell(row['reference_oa_evidence'])} |"
        )
    lines.extend(["", "## Unresolved assumptions", ""])
    for row in rows:
        lines.append(f"- `{row['category']}` — {row['unresolved_assumptions']}")
    lines.extend(
        [
            "",
            "The per-Space source audit remains authoritative for the one office/IT_Room",
            "metadata conflict. The reference derivative does not overwrite that row's",
            "People definition parameters.",
            "",
        ]
    )
    return "\n".join(lines)


def _parameter_table(parameters: Sequence[ParameterEvidence]) -> list[str]:
    lines = [
        "| Category | Parameter | Adopted value | Tier | Scope | Source / locator | Decision boundary |",
        "|---|---|---:|---|---|---|---|",
    ]
    for row in parameters:
        if row.parameter not in {
            "design_density_m2_per_person",
            "outdoor_air_per_person_m3_s_person",
            "outdoor_air_per_area_m3_s_m2",
            "exhaust_air_changes_per_hour",
        }:
            continue
        value = f"{_fmt(row.value)} {row.unit}" if row.value is not None else "DO_NOT_AUTOFILL"
        source = f"{row.source_id}; {row.locator}"
        lines.append(
            f"| {row.category} | {row.parameter} | {value} | {row.tier.value} | "
            f"{row.use_scope} | {source} | {row.does_not_support} |"
        )
    return lines


def _evidence_markdown(
    parameters: Sequence[ParameterEvidence],
    literature: Sequence[LiteratureEvidence],
) -> str:
    lines = [
        "# Room-aware occupancy parameter evidence",
        "",
        "**Decision:** four design densities have evidence adequate for Baseline R;",
        "two densities remain `DO_NOT_AUTOFILL`. Main Baseline S/R comparisons preserve",
        "source OA, activity, heat fractions, CO2 fields, geometry, and non-People loads.",
        "",
        "## Evidence tiers",
        "",
        "- `TIER_A_SOURCE_BACKED`: exact OSM field retained without reinterpretation.",
        "- `TIER_B_STANDARD_OR_LITERATURE_BACKED`: same-project engineering note or",
        "  authoritative standard used in a labelled reference derivative.",
        "- `TIER_C_CONTROLLED_NOT_MEASURED`: deterministic scenario input only.",
        "- `DO_NOT_AUTOFILL`: evidence is absent or does not resolve the source category.",
        "",
        "## Adopted and rejected inputs",
        "",
        *_parameter_table(parameters),
        "",
        "The three same-project density values (office 6, general commerce 5, dining",
        "2.5 m²/person) come from construction-note page 05, section 4.2. The breakroom",
        "reference converts ASHRAE's 25 persons/1000 ft² to",
        f"{ASHRAE_BREAKROOM_M2_PER_PERSON:.6f} m²/person. The hall source label does not",
        "resolve the multiple documented hall rows, whose densities span 2–10",
        "m²/person; selecting one value would be unsupported. Restroom occupancy lacks",
        "a source dwell model. The 15 h⁻¹ restroom exhaust note is documented but not",
        "implemented because the simplified OSM does not map source HVAC topology.",
        "",
        "## Local source-document provenance",
        "",
        "Only extracted facts and hashes are recorded; raw TIFF/DWG material is excluded",
        "from Git and the review package.",
        "",
        f"- `SJSM page 03`: `{PROJECT_NOTES_PAGE_03_SHA256}` — same terminal project identity and scale.",
        f"- `SJSM page 05`: `{PROJECT_NOTES_PAGE_05_SHA256}` — section 4.2 room design table.",
        f"- `SJSM page 06`: `{PROJECT_NOTES_PAGE_06_SHA256}` — restroom exhaust design note.",
        f"- `SJSM page 07`: `{PROJECT_NOTES_PAGE_07_SHA256}` — system-type descriptions.",
        "",
        "Page 07 establishes that real project HVAC design documentation exists, but the",
        "simplified second-floor OSM contains no AirLoop or PlantLoop mapping to those",
        "systems. The resulting status is `REAL_HVAC_DESIGN_EVIDENCE_PRESENT` with",
        "`HVAC_TOPOLOGY_UNRESOLVED`; no source-backed real HVAC is synthesized.",
        "",
        "## EnergyPlus and ventilation semantics",
        "",
        f"EnergyPlus 23.1 defines the People count method, Number of People Schedule, "
        f"Activity Level Schedule, Fraction Radiant, autocalculated sensible fraction, "
        f"and CO2 generation fields in its [official Input Output Reference]({ENERGYPLUS_23_1_IO_URL}).",
        "The derivative therefore preserves the source heat/CO2 fields and changes only",
        "the explicitly registered People count and controlled schedule.",
        "",
        f"[ASHRAE 62.1-2022 Addendum ab]({ASHRAE_ADDENDUM_URL}) supplies the general",
        "break-room defaults used above and reference ventilation rates. Its",
        "transportation-waiting default is not applied to the unresolved hall label.",
        "Reference OA changes, where attempted, are isolated as",
        "`REFERENCE_OA_IDEALLOADS_SENSITIVITY`; they are not a real-HVAC case and do not",
        "authorize DCV.",
        "",
        "## Airport occupancy literature ledger",
        "",
        "| Source | Prior contribution supported by verified metadata/abstract | Not transferred to this case |",
        "|---|---|---|",
    ]
    for row in literature:
        lines.append(
            f"| [{row.authors.split(';')[0]} et al. ({row.year})]({row.url}) — "
            f"{row.title} | {row.supports} | {row.does_not_support} |"
        )
    lines.extend(
        [
            "",
            "Together, these studies establish passenger-flow, zone-schedule, heat-gain,",
            "energy-simulation, MPC, and occupant-centric ventilation precedents. This",
            "case therefore makes no claim of being the first dynamic airport occupancy",
            "or occupancy–HVAC study. Its bounded contribution is an OSM/IDF-native,",
            "provenance-aware downstream workflow whose room mapping fails closed and",
            "whose counterfactuals conserve person-hours.",
            "",
            "## Claim boundary",
            "",
            "The construction-note values are project design inputs, not measured",
            "occupancy. Literature examples provide method precedent, not calibration",
            "data. Baseline R is a controlled reference derivative, and every seasonal or",
            "annual result remains an IdealLoads thermal-demand simulation rather than a",
            "calibrated terminal energy result.",
            "",
        ]
    )
    return "\n".join(lines)


def render_evidence_artifacts(
    audit: Mapping[str, Any],
    *,
    registry_csv_path: Path,
    registry_markdown_path: Path,
    evidence_markdown_path: Path,
) -> list[dict[str, Any]]:
    """生成六类 registry CSV/Markdown 与参数/文献证据报告。"""

    parameters = parameter_evidence_records()
    literature = literature_evidence_records()
    validate_evidence_registry(parameters, literature)
    registry = build_room_function_registry(audit, parameters)
    registry_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ROOM_REGISTRY_FIELDS)
        writer.writeheader()
        for row in registry:
            writer.writerow({key: _fmt(row.get(key)) for key in ROOM_REGISTRY_FIELDS})
    registry_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    registry_markdown_path.write_text(
        _registry_markdown(registry, audit), encoding="utf-8"
    )
    evidence_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_markdown_path.write_text(
        _evidence_markdown(parameters, literature), encoding="utf-8"
    )
    return registry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--registry-csv", type=Path, required=True)
    parser.add_argument("--registry-markdown", type=Path, required=True)
    parser.add_argument("--evidence-markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    registry = render_evidence_artifacts(
        audit,
        registry_csv_path=args.registry_csv,
        registry_markdown_path=args.registry_markdown,
        evidence_markdown_path=args.evidence_markdown,
    )
    print(json.dumps({"status": "evidence_rendered", "categories": len(registry)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASHRAE_BREAKROOM_M2_PER_PERSON",
    "LiteratureEvidence",
    "ParameterEvidence",
    "build_room_function_registry",
    "literature_evidence_records",
    "parameter_evidence_records",
    "render_evidence_artifacts",
    "validate_evidence_registry",
]
