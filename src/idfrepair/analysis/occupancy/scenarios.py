"""构造 passenger-hours 守恒的确定性 occupancy 分布场景。

这里的数值表示相对于 People 设计人数的时步乘数。时间与空间场景只重排
既有总量；客流量敏感性必须显式调用 :func:`scale_volume`。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence


DEFAULT_STEPS = 96


def _validated(values: Sequence[float], *, label: str) -> tuple[float, ...]:
    """返回有限、非负且非空的浮点序列。"""

    parsed = tuple(float(value) for value in values)
    if not parsed:
        raise ValueError(f"{label}_must_not_be_empty")
    if any(not math.isfinite(value) for value in parsed):
        raise ValueError(f"{label}_must_be_finite")
    if any(value < 0.0 for value in parsed):
        raise ValueError(f"{label}_must_be_nonnegative")
    return parsed


def normalize_profile(
    values: Sequence[float], *, steps: int = DEFAULT_STEPS
) -> tuple[float, ...]:
    """按零阶保持重采样到 ``steps``，并归一化为单位离散积分。"""

    source = _validated(values, label="profile")
    if steps <= 0:
        raise ValueError("steps_must_be_positive")
    total = math.fsum(source)
    if total <= 0.0:
        raise ValueError("profile_integral_must_be_positive")
    source_count = len(source)
    resampled = tuple(source[(index * source_count) // steps] for index in range(steps))
    resampled_total = math.fsum(resampled)
    if resampled_total <= 0.0:
        raise ValueError("resampled_profile_integral_must_be_positive")
    return tuple(value / resampled_total for value in resampled)


def person_hours(
    profile: Sequence[float],
    design_people: float,
    *,
    minutes_per_step: float = 15.0,
) -> float:
    """计算时步乘数对应的 passenger-hours。"""

    values = _validated(profile, label="profile")
    if not math.isfinite(design_people) or design_people < 0.0:
        raise ValueError("design_people_must_be_finite_and_nonnegative")
    if not math.isfinite(minutes_per_step) or minutes_per_step <= 0.0:
        raise ValueError("minutes_per_step_must_be_finite_and_positive")
    return math.fsum(values) * design_people * minutes_per_step / 60.0


def _window_template(windows: Sequence[tuple[int, int]]) -> tuple[float, ...]:
    """生成带平滑三角峰的 96 点正权重模板。"""

    values = [0.2] * DEFAULT_STEPS
    for start, stop in windows:
        center = (start + stop - 1) / 2.0
        half_width = max((stop - start) / 2.0, 1.0)
        for index in range(start, stop):
            triangular = max(0.0, 1.0 - abs(index - center) / half_width)
            values[index] += 1.8 + 1.2 * triangular
    return tuple(values)


def _scale_to_sum(values: Sequence[float], target_sum: float) -> tuple[float, ...]:
    """把非负模板缩放到指定离散积分。"""

    source_sum = math.fsum(values)
    if source_sum <= 0.0:
        raise ValueError("scenario_template_integral_must_be_positive")
    factor = target_sum / source_sum
    return tuple(value * factor for value in values)


def temporal_profiles(
    baseline: Sequence[float],
) -> dict[str, tuple[float, ...]]:
    """生成四种 15 分钟峰型，保持基线 passenger-hours 不变。

    时间窗分别为 05:00–09:00、11:00–15:00 与 17:00–22:00；双峰为
    早晚组合。输入必须已经是单日 96 个 15 分钟时步。
    """

    source = _validated(baseline, label="baseline")
    if len(source) != DEFAULT_STEPS:
        raise ValueError("baseline_must_have_96_steps")
    target_sum = math.fsum(source)
    if target_sum <= 0.0:
        raise ValueError("baseline_integral_must_be_positive")
    templates = {
        "morning_peak": _window_template(((20, 36),)),
        "midday_peak": _window_template(((44, 60),)),
        "evening_peak": _window_template(((68, 88),)),
        "double_peak": _window_template(((20, 36), (68, 88))),
    }
    return {
        name: _scale_to_sum(template, target_sum)
        for name, template in templates.items()
    }


def redistribute_spatial(
    baselines: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
) -> dict[str, tuple[float, ...]]:
    """按权重重分配各区 occupancy，并保持每一时步的总量。"""

    if not baselines:
        raise ValueError("baselines_must_not_be_empty")
    parsed = {
        name: _validated(values, label=f"baseline:{name}")
        for name, values in baselines.items()
    }
    lengths = {len(values) for values in parsed.values()}
    if len(lengths) != 1:
        raise ValueError("profile_lengths_must_match")
    if not weights:
        raise ValueError("spatial_weights_must_not_be_empty")
    parsed_weights = {name: float(value) for name, value in weights.items()}
    if any(not math.isfinite(value) for value in parsed_weights.values()):
        raise ValueError("spatial_weights_must_be_finite")
    if any(value < 0.0 for value in parsed_weights.values()):
        raise ValueError("spatial_weights_must_be_nonnegative")
    weight_sum = math.fsum(parsed_weights.values())
    if weight_sum <= 0.0:
        raise ValueError("spatial_weights_must_have_positive_sum")

    names = sorted(parsed_weights)
    step_count = next(iter(lengths))
    totals = tuple(math.fsum(values[index] for values in parsed.values()) for index in range(step_count))
    result: dict[str, list[float]] = {name: [] for name in names}
    for total in totals:
        assigned = 0.0
        for name in names[:-1]:
            value = total * parsed_weights[name] / weight_sum
            result[name].append(value)
            assigned += value
        result[names[-1]].append(max(0.0, total - assigned))
    return {name: tuple(values) for name, values in result.items()}


def redistribute_spatial_bounded(
    baselines: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    capacities: Mapping[str, float],
) -> dict[str, tuple[float, ...]]:
    """按权重重分配 occupant counts，并逐时步遵守显式上限。

    当某一组达到上限，剩余人数继续按尚未饱和组的权重分配。该函数不把
    People 设计人数声称为真实航站楼容量；调用方必须明确提供本场景采用的
    数值上限。
    """

    if not baselines:
        raise ValueError("baselines_must_not_be_empty")
    parsed = {
        name: _validated(values, label=f"baseline:{name}")
        for name, values in baselines.items()
    }
    names = tuple(parsed)
    if set(weights) != set(names) or set(capacities) != set(names):
        raise ValueError("bounded_spatial_names_must_match")
    lengths = {len(values) for values in parsed.values()}
    if len(lengths) != 1:
        raise ValueError("profile_lengths_must_match")
    parsed_weights = {name: float(weights[name]) for name in names}
    parsed_capacities = {name: float(capacities[name]) for name in names}
    if any(
        not math.isfinite(value) or value < 0.0
        for value in parsed_weights.values()
    ):
        raise ValueError("bounded_spatial_weights_invalid")
    if any(
        not math.isfinite(value) or value < 0.0
        for value in parsed_capacities.values()
    ):
        raise ValueError("bounded_spatial_capacities_invalid")
    if math.fsum(parsed_weights.values()) <= 0.0:
        raise ValueError("bounded_spatial_weights_must_have_positive_sum")

    step_count = next(iter(lengths))
    results: dict[str, list[float]] = {name: [] for name in names}
    capacity_sum = math.fsum(parsed_capacities.values())
    tolerance = 1e-10
    for index in range(step_count):
        total = math.fsum(parsed[name][index] for name in names)
        if total > capacity_sum + tolerance:
            raise ValueError("bounded_spatial_total_exceeds_capacity")
        assigned = {name: 0.0 for name in names}
        active = {
            name
            for name in names
            if parsed_weights[name] > 0.0 and parsed_capacities[name] > 0.0
        }
        remaining = total
        while remaining > tolerance:
            weight_sum = math.fsum(parsed_weights[name] for name in active)
            if not active or weight_sum <= 0.0:
                raise ValueError("bounded_spatial_positive_capacity_exhausted")
            proposals = {
                name: remaining * parsed_weights[name] / weight_sum for name in active
            }
            saturated: list[str] = []
            for name in active:
                available = parsed_capacities[name] - assigned[name]
                if proposals[name] >= available - tolerance:
                    assigned[name] += max(0.0, available)
                    remaining -= max(0.0, available)
                    saturated.append(name)
            if saturated:
                active.difference_update(saturated)
                continue
            allocated = 0.0
            active_order = [name for name in names if name in active]
            for name in active_order[:-1]:
                value = proposals[name]
                assigned[name] += value
                allocated += value
            assigned[active_order[-1]] += remaining - allocated
            remaining = 0.0
        for name in names:
            results[name].append(assigned[name])
    return {name: tuple(values) for name, values in results.items()}


def scale_volume(profile: Sequence[float], factor: float) -> tuple[float, ...]:
    """显式改变总客流量；该 API 不属于守恒的时间/空间重排。"""

    values = _validated(profile, label="profile")
    if not math.isfinite(factor) or factor < 0.0:
        raise ValueError("volume_factor_must_be_finite_and_nonnegative")
    return tuple(value * factor for value in values)


def profile_digest(profile: Sequence[float]) -> str:
    """返回跨运行稳定的 profile SHA-256。"""

    values = _validated(profile, label="profile")
    payload = "\n".join(f"{value:.15f}" for value in values).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "DEFAULT_STEPS",
    "normalize_profile",
    "person_hours",
    "profile_digest",
    "redistribute_spatial",
    "redistribute_spatial_bounded",
    "scale_volume",
    "temporal_profiles",
]
