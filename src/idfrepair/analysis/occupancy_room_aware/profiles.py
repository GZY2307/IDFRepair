"""六类 15 分钟 occupancy profiles 与守恒反事实。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from statistics import median


MINUTES_PER_STEP = 15
STEPS_PER_DAY = 24 * 60 // MINUTES_PER_STEP
STAFF_CATEGORIES = ("office", "breakroom")
PUBLIC_DYNAMIC_CATEGORIES = (
    "terminal_hall",
    "commerce_retail",
    "dining",
    "restroom",
)
PUBLIC_ONLY_CATEGORIES = ("terminal_hall",)
PUBLIC_FACING_UNSPLIT_CATEGORIES = ("commerce_retail", "dining")
PUBLIC_LINKED_CATEGORIES = ("restroom",)


@dataclass(frozen=True, slots=True)
class SpaceCapacity:
    """空间分配所需的最小 source-backed 容量与几何暴露信息。"""

    space_name: str
    category: str
    design_people: float
    exterior_area_m2: float
    floor_area_m2: float

    @property
    def exterior_exposure_ratio(self) -> float:
        if self.floor_area_m2 <= 0:
            return 0.0
        return self.exterior_area_m2 / self.floor_area_m2


def _piecewise(anchors: Sequence[tuple[float, float]]) -> tuple[float, ...]:
    if not anchors or anchors[0][0] != 0.0 or anchors[-1][0] != 24.0:
        raise ValueError("profile_anchors_must_cover_day")
    if any(right[0] <= left[0] for left, right in zip(anchors, anchors[1:])):
        raise ValueError("profile_anchor_time_not_increasing")
    values: list[float] = []
    segment = 0
    for index in range(STEPS_PER_DAY):
        hour = index * MINUTES_PER_STEP / 60.0
        while hour > anchors[segment + 1][0]:
            segment += 1
        left_time, left_value = anchors[segment]
        right_time, right_value = anchors[segment + 1]
        weight = (hour - left_time) / (right_time - left_time)
        value = left_value + weight * (right_value - left_value)
        values.append(round(value, 10))
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("profile_value_out_of_bounds")
    return tuple(values)


def build_category_profiles() -> dict[str, tuple[float, ...]]:
    """构建互不相同的 Tier-C 基线曲线；不声称为真实运营记录。"""

    hall = _piecewise(
        (
            (0.0, 0.03),
            (4.0, 0.03),
            (6.0, 0.10),
            (8.0, 0.42),
            (10.0, 0.55),
            (12.0, 0.38),
            (14.0, 0.45),
            (17.0, 0.62),
            (19.0, 0.48),
            (22.0, 0.12),
            (24.0, 0.03),
        )
    )
    office = _piecewise(
        (
            (0.0, 0.01),
            (6.5, 0.01),
            (8.0, 0.55),
            (9.0, 0.85),
            (12.0, 0.82),
            (13.0, 0.48),
            (14.0, 0.80),
            (17.5, 0.78),
            (19.0, 0.12),
            (21.0, 0.03),
            (24.0, 0.01),
        )
    )
    commerce = _piecewise(
        (
            (0.0, 0.01),
            (6.0, 0.01),
            (8.0, 0.18),
            (10.0, 0.38),
            (13.0, 0.58),
            (16.0, 0.52),
            (19.0, 0.70),
            (21.5, 0.45),
            (23.0, 0.08),
            (24.0, 0.01),
        )
    )
    dining = _piecewise(
        (
            (0.0, 0.01),
            (5.5, 0.01),
            (7.5, 0.38),
            (9.5, 0.12),
            (11.0, 0.25),
            (12.5, 0.82),
            (14.5, 0.18),
            (17.0, 0.28),
            (19.0, 0.88),
            (21.0, 0.25),
            (23.0, 0.04),
            (24.0, 0.01),
        )
    )
    breakroom = _piecewise(
        (
            (0.0, 0.01),
            (6.0, 0.01),
            (8.0, 0.28),
            (9.5, 0.08),
            (11.5, 0.18),
            (12.5, 0.72),
            (14.0, 0.10),
            (15.5, 0.32),
            (17.0, 0.08),
            (18.5, 0.42),
            (20.0, 0.06),
            (22.0, 0.01),
            (24.0, 0.01),
        )
    )
    public_signal = tuple(
        0.70 * hall_value + 0.15 * commerce_value + 0.15 * dining_value
        for hall_value, commerce_value, dining_value in zip(
            hall, commerce, dining, strict=True
        )
    )
    restroom = tuple(
        round(min(0.35, max(0.01, 0.015 + 0.24 * value)), 10)
        for value in public_signal
    )
    result = {
        "terminal_hall": hall,
        "office": office,
        "commerce_retail": commerce,
        "dining": dining,
        "restroom": restroom,
        "breakroom": breakroom,
    }
    if len(set(result.values())) != len(result):
        raise AssertionError("room_profiles_not_distinct")
    return result


def profile_digest(values: Sequence[float]) -> str:
    """以稳定十位小数 JSON 计算 profile 身份。"""

    normalized = [f"{float(value):.10f}" for value in values]
    payload = json.dumps(normalized, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _rotate(values: tuple[float, ...], steps: int) -> tuple[float, ...]:
    if not values:
        return values
    shift = steps % len(values)
    if shift == 0:
        return values
    return values[-shift:] + values[:-shift]


def build_temporal_scenarios(
    baseline: Mapping[str, tuple[float, ...]],
) -> dict[str, dict[str, tuple[float, ...]]]:
    """移动 public-facing peaks，同时逐类严格保持积分并固定 staff。"""

    missing = set((*STAFF_CATEGORIES, *PUBLIC_DYNAMIC_CATEGORIES)) - set(baseline)
    if missing:
        raise ValueError(f"profile_categories_missing:{'|'.join(sorted(missing))}")
    shifts = {
        "public_morning": -16,
        "public_midday": 0,
        "public_evening": 16,
    }
    result: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario, shift in shifts.items():
        profiles = dict(baseline)
        for category in PUBLIC_DYNAMIC_CATEGORIES:
            profiles[category] = _rotate(baseline[category], shift)
        for category in STAFF_CATEGORIES:
            profiles[category] = baseline[category]
        result[scenario] = profiles
    return result


def _validate_space_profile_inputs(
    profiles_by_space: Mapping[str, tuple[float, ...]],
    category_by_space: Mapping[str, str],
    flow_topology: Mapping[str, object] | None = None,
) -> Mapping[str, Mapping[str, object]] | None:
    if set(profiles_by_space) != set(category_by_space):
        raise ValueError("space_profile_category_coverage_mismatch")
    if flow_topology is None:
        return None
    raw_spaces = flow_topology.get("spaces")
    if not isinstance(raw_spaces, Mapping) or set(raw_spaces) != set(category_by_space):
        raise ValueError("space_profile_flow_coverage_mismatch")
    return raw_spaces  # type: ignore[return-value]


def apply_entrance_phase_profiles(
    category_profiles: Mapping[str, tuple[float, ...]],
    category_by_space: Mapping[str, str],
    flow_topology: Mapping[str, object],
) -> dict[str, tuple[float, ...]]:
    """Delay public response by controlled topology bands; keep staff unchanged."""

    missing_categories = set(category_by_space.values()) - set(category_profiles)
    if missing_categories:
        raise ValueError(
            "space_profile_categories_missing:" + "|".join(sorted(missing_categories))
        )
    raw_spaces = flow_topology.get("spaces")
    if not isinstance(raw_spaces, Mapping) or set(raw_spaces) != set(category_by_space):
        raise ValueError("space_profile_flow_coverage_mismatch")
    result: dict[str, tuple[float, ...]] = {}
    for space_name, category in category_by_space.items():
        profile = category_profiles[category]
        flow_row = raw_spaces[space_name]
        if not isinstance(flow_row, Mapping):
            raise ValueError(f"space_profile_flow_row_invalid:{space_name}")
        phase_steps = int(flow_row.get("flow_phase_steps", -1))
        if category in STAFF_CATEGORIES:
            if phase_steps != 0:
                raise ValueError(f"space_profile_staff_phase_nonzero:{space_name}")
            result[space_name] = profile
        elif category in PUBLIC_DYNAMIC_CATEGORIES:
            if not 0 <= phase_steps <= 3:
                raise ValueError(f"space_profile_public_phase_invalid:{space_name}")
            result[space_name] = _rotate(profile, phase_steps)
        else:
            raise ValueError(f"space_profile_category_unknown:{space_name}:{category}")
    return result


def build_space_temporal_scenarios(
    baseline_by_space: Mapping[str, tuple[float, ...]],
    category_by_space: Mapping[str, str],
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Shift already-phased public Space profiles while holding staff bitwise fixed."""

    _validate_space_profile_inputs(baseline_by_space, category_by_space)
    shifts = {
        "public_morning": -16,
        "public_midday": 0,
        "public_evening": 16,
    }
    result: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario_id, shift in shifts.items():
        scenario = {}
        for space_name, baseline in baseline_by_space.items():
            category = category_by_space[space_name]
            if category in STAFF_CATEGORIES or shift == 0:
                scenario[space_name] = baseline
            elif category in PUBLIC_DYNAMIC_CATEGORIES:
                scenario[space_name] = _rotate(baseline, shift)
            else:
                raise ValueError(f"space_profile_category_unknown:{space_name}:{category}")
        result[scenario_id] = scenario
    return result


def build_entrance_region_scenarios(
    baseline_by_space: Mapping[str, tuple[float, ...]],
    category_by_space: Mapping[str, str],
    flow_topology: Mapping[str, object],
    *,
    lead_steps: int = 2,
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Create reciprocal entrance-region timing cases with exact per-Space integrals."""

    if not 1 <= lead_steps <= 8:
        raise ValueError("entrance_region_lead_steps_invalid")
    flow_spaces = _validate_space_profile_inputs(
        baseline_by_space,
        category_by_space,
        flow_topology,
    )
    assert flow_spaces is not None
    scenarios: dict[str, dict[str, tuple[float, ...]]] = {}
    for lead_entrance, scenario_id in (
        ("z-u-hall-2", "entrance_2_lead"),
        ("z-u-hall-3", "entrance_3_lead"),
    ):
        scenario: dict[str, tuple[float, ...]] = {}
        for space_name, baseline in baseline_by_space.items():
            category = category_by_space[space_name]
            if category in STAFF_CATEGORIES:
                scenario[space_name] = baseline
                continue
            if category not in PUBLIC_DYNAMIC_CATEGORIES:
                raise ValueError(f"space_profile_category_unknown:{space_name}:{category}")
            flow_row = flow_spaces[space_name]
            nearest = str(flow_row.get("nearest_entrance_space", ""))
            if nearest not in {"z-u-hall-2", "z-u-hall-3"}:
                raise ValueError(f"entrance_region_missing:{space_name}")
            shift = -lead_steps if nearest == lead_entrance else lead_steps
            scenario[space_name] = _rotate(baseline, shift)
        scenarios[scenario_id] = scenario
    return scenarios


def apply_public_volume_by_space(
    baseline_by_space: Mapping[str, tuple[float, ...]],
    category_by_space: Mapping[str, str],
    multiplier: float,
) -> dict[str, tuple[float, ...]]:
    """Scale only terminal-hall Space profiles without erasing their flow phases."""

    _validate_space_profile_inputs(baseline_by_space, category_by_space)
    if multiplier <= 0 or not math.isfinite(multiplier):
        raise ValueError("public_volume_multiplier_invalid")
    result = dict(baseline_by_space)
    for space_name, category in category_by_space.items():
        if category != "terminal_hall":
            continue
        scaled = tuple(value * multiplier for value in baseline_by_space[space_name])
        if max(scaled, default=0.0) > 1.0 + 1e-12:
            raise ValueError("public_volume_exceeds_design_capacity")
        result[space_name] = scaled
    return result


def apply_public_volume(
    baseline: Mapping[str, tuple[float, ...]],
    multiplier: float,
) -> dict[str, tuple[float, ...]]:
    """仅缩放明确 public 的 terminal_hall；staff 与 unsplit categories 不变。"""

    if multiplier <= 0 or not math.isfinite(multiplier):
        raise ValueError("public_volume_multiplier_invalid")
    if "terminal_hall" not in baseline:
        raise ValueError("terminal_hall_profile_missing")
    scaled = tuple(value * multiplier for value in baseline["terminal_hall"])
    if max(scaled, default=0.0) > 1.0 + 1e-12:
        raise ValueError("public_volume_exceeds_design_capacity")
    result = dict(baseline)
    result["terminal_hall"] = scaled
    return result


def person_hours(
    profiles: Mapping[str, Sequence[float]],
    design_people: Mapping[str, float],
    *,
    categories: Sequence[str] | None = None,
) -> float:
    """按类别 fraction × design people 积分为 person-hours。"""

    selected = tuple(categories) if categories is not None else tuple(profiles)
    step_hours = MINUTES_PER_STEP / 60.0
    total = 0.0
    for category in selected:
        values = profiles.get(category)
        if values is None or category not in design_people:
            raise ValueError(f"person_hours_category_missing:{category}")
        if len(values) != STEPS_PER_DAY:
            raise ValueError(f"profile_length_invalid:{category}")
        total += sum(values) * float(design_people[category]) * step_hours
    return total


def _bounded_weighted_allocation(
    total: float,
    capacities: Mapping[str, float],
    weights: Mapping[str, float],
) -> dict[str, float]:
    if total < -1e-12 or not math.isfinite(total):
        raise ValueError("spatial_total_invalid")
    available = sum(capacities.values())
    if total > available + 1e-9:
        raise ValueError("category_capacity_exceeded")
    remaining = max(0.0, total)
    active = set(capacities)
    result = {name: 0.0 for name in capacities}
    while active and remaining > 1e-12:
        weight_sum = sum(weights[name] for name in active)
        if weight_sum <= 0:
            raise ValueError("spatial_weight_sum_invalid")
        saturated: list[str] = []
        for name in sorted(active):
            share = remaining * weights[name] / weight_sum
            residual_capacity = capacities[name] - result[name]
            if share >= residual_capacity - 1e-12:
                result[name] += max(0.0, residual_capacity)
                saturated.append(name)
        if saturated:
            for name in saturated:
                active.remove(name)
            remaining = total - sum(result.values())
            continue
        for name in sorted(active):
            result[name] += remaining * weights[name] / weight_sum
        remaining = 0.0
    error = total - sum(result.values())
    if abs(error) > 1e-9:
        candidates = [
            name for name in sorted(capacities) if result[name] + error <= capacities[name] + 1e-9
        ]
        if not candidates:
            raise ValueError("spatial_conservation_failed")
        result[candidates[0]] += error
    return result


def allocate_spatial_counts(
    category_totals: Mapping[str, float],
    spaces: Sequence[SpaceCapacity],
    *,
    mode: str,
) -> dict[str, float]:
    """按 exterior-exposure 分组在同一类别内重分配人数。"""

    if mode not in {"perimeter", "core"}:
        raise ValueError(f"spatial_mode_invalid:{mode}")
    result: dict[str, float] = {}
    for category, total in category_totals.items():
        if category not in PUBLIC_DYNAMIC_CATEGORIES:
            raise ValueError(f"spatial_category_not_public_dynamic:{category}")
        selected = sorted(
            (space for space in spaces if space.category == category),
            key=lambda space: (space.exterior_exposure_ratio, space.space_name),
        )
        if not selected:
            raise ValueError(f"spatial_category_spaces_missing:{category}")
        if len({space.space_name for space in selected}) != len(selected):
            raise ValueError(f"spatial_space_identity_duplicate:{category}")
        if any(space.design_people < 0 for space in selected):
            raise ValueError(f"spatial_capacity_invalid:{category}")
        split_value = median(space.exterior_exposure_ratio for space in selected)
        perimeter_names = {
            space.space_name
            for space in selected
            if space.exterior_exposure_ratio >= split_value
        }
        target = (
            perimeter_names
            if mode == "perimeter"
            else {space.space_name for space in selected} - perimeter_names
        )
        if not target:
            target = {selected[0].space_name}
        capacities = {space.space_name: space.design_people for space in selected}
        weights = {
            space.space_name: max(space.design_people, 1e-12)
            * (3.0 if space.space_name in target else 1.0)
            for space in selected
        }
        result.update(_bounded_weighted_allocation(float(total), capacities, weights))
    return result


def render_protocol(path: Path) -> None:
    """写出场景术语、守恒量、季节日与解释边界。"""

    profiles = build_category_profiles()
    lines = [
        "# Room-aware airport occupancy protocol",
        "",
        "**Protocol status:** `CONTROLLED_NOT_MEASURED`",
        "",
        "## Scope and baselines",
        "",
        "Baseline S preserves every source design People total, schedule, activity, heat",
        "fraction, CO2 field, and OA definition while aggregating results by the six",
        "source-name room categories. Baseline R is a People-only reference derivative:",
        "it makes People explicit per Space and changes design density only where the",
        "evidence registry permits. Neither baseline represents measured operations.",
        "IdealLoads additions are synthetic thermal-demand endpoints, not real HVAC.",
        "",
        "## Occupant classes",
        "",
        "- `public`: terminal_hall only; eligible for 0.5–1.5 volume scaling.",
        "- `staff`: office and breakroom; staff fixed in all public counterfactuals.",
        "- `public-facing-unsplit`: commerce_retail and dining; no invented customer/staff split.",
        "- `public-linked-bounded`: restroom; linked to public presence without a dwell-time claim.",
        "",
        "Whole-building integrals are `person-hours`. `Passenger-hours` is reserved for",
        "the explicit terminal_hall public class; unsplit categories are reported",
        "separately.",
        "",
        "## Fifteen-minute reference profiles",
        "",
        "All profiles are Tier C controlled shapes. Their values are design-capacity",
        "fractions at 15-minute resolution; they are not flight-derived predictions.",
        "",
        "| Category | Steps/day | Minimum | Maximum | Equivalent full-occupancy hours/day | SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for category, values in profiles.items():
        lines.append(
            f"| {category} | {len(values)} | {min(values):.4f} | {max(values):.4f} | "
            f"{sum(values) * 0.25:.4f} | `{profile_digest(values)}` |"
        )
    lines.extend(
        [
            "",
            "## Controlled scenario matrix",
            "",
            "1. Baseline R seeds `z-u-hall-2` and `z-u-hall-3` at phase zero. Public",
            "   Spaces in the reciprocal paired-surface Zone graph use controlled",
            "   15/30/45-minute occupancy-response phases by within-region hop tercile.",
            "   These phases are not walking times or measured passenger trajectories;",
            "   office/breakroom staff are not entrance-delayed.",
            "2. `public_morning`, `public_midday`, and `public_evening` circularly shift",
            "   each already-phased public-dynamic Space by −4, 0, and +4 hours. Each",
            "   Space's 96-value multiset and person-hours are identical; office/breakroom arrays",
            "   are the same immutable objects in all three cases.",
            "3. `entrance_2_lead` and `entrance_3_lead` are reciprocal regional cases:",
            "   one entrance region leads by 30 minutes while the other lags by 30 minutes.",
            "   Every Space retains its exact 96-value multiset and person-hours.",
            "4. `public_perimeter` and `public_core` redistribute each category's timestep",
            "   count only among Spaces of that same category. Ranking uses source geometry",
            "   exterior-area/floor-area ratio solely as a controlled physical exposure",
            "   grouping. Geometry is not used for room-function classification.",
            "5. `public_volume_0.50` through `public_volume_1.50` scale terminal_hall only.",
            "   Office, breakroom, commerce, dining, and restroom remain unchanged because",
            "   their staff/customer decomposition is unavailable.",
            "",
            "Conservation tolerance is 1e-9 person-hours for temporal cases and 1e-9",
            "persons per category-timestep for spatial allocation. Every allocation is",
            "bounded by its per-Space design People count.",
            "",
            "## Simulation periods and outputs",
            "",
            "- Winter controlled day: 15 January (Beijing CSWD weather).",
            "- Summer controlled day: 15 July.",
            "- Shoulder controlled day: 15 April.",
            "- Annual: 1 January–31 December at 15-minute schedules if the gate below passes.",
            "",
            "Outputs are reconciled at Space/category/building level: occupant count and",
            "density, person-hours, People sensible/latent/radiant gains, IdealLoads",
            "heating/cooling demand and peaks, temperature/RH where available, OA-related",
            "IdealLoads variables where available, and unmet time. Missing EnergyPlus",
            "variables are labelled unavailable, never imputed.",
            "",
            "## `ANNUAL_RUNTIME_GATE`",
            "",
            "Annual runs proceed only after all retained seasonal cases finish with zero",
            "Fatal/Severe errors, exact source/freeze hashes, complete CSV outputs, and",
            "category reconciliation. A profiled annual Baseline R must project no more",
            "than 30 minutes and 2 GB per run, available disk must exceed 2.5 times the",
            "projected suite footprint, and concurrency is capped at two processes.",
            "",
            "## Interpretation boundary",
            "",
            "Temporal and spatial cases test distribution effects at matched integrals;",
            "volume cases are ordinary sensitivity checks and are not treated as novelty.",
            "No case is calibrated to flight, Wi-Fi, staff roster, or measured HVAC data.",
            "The official Daxing Level-2 plan supplies spatial context only and does not",
            "authorize invented check-in, gate, baggage, door, or HVAC labels in the OSM.",
            "A whole-building or local result is reported only within this controlled",
            "IdealLoads boundary.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


__all__ = [
    "MINUTES_PER_STEP",
    "PUBLIC_DYNAMIC_CATEGORIES",
    "PUBLIC_FACING_UNSPLIT_CATEGORIES",
    "PUBLIC_LINKED_CATEGORIES",
    "PUBLIC_ONLY_CATEGORIES",
    "STAFF_CATEGORIES",
    "STEPS_PER_DAY",
    "SpaceCapacity",
    "allocate_spatial_counts",
    "apply_entrance_phase_profiles",
    "apply_public_volume",
    "apply_public_volume_by_space",
    "build_category_profiles",
    "build_entrance_region_scenarios",
    "build_space_temporal_scenarios",
    "build_temporal_scenarios",
    "person_hours",
    "profile_digest",
    "render_protocol",
]
