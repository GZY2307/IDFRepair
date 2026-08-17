"""验证 occupancy 场景的 passenger-hours 守恒与可复现性。"""

from __future__ import annotations

import math

import pytest

from idfrepair.analysis.occupancy.scenarios import (
    normalize_profile,
    person_hours,
    profile_digest,
    redistribute_spatial,
    scale_volume,
    temporal_profiles,
)


def test_normalize_profile_resamples_and_has_unit_integral() -> None:
    """小时序列可确定性展开为 96 点，并归一到单位离散积分。"""

    profile = normalize_profile([1.0, 3.0], steps=4)

    assert profile == pytest.approx((0.125, 0.125, 0.375, 0.375))
    assert sum(profile) == pytest.approx(1.0, rel=0, abs=1e-15)


def test_temporal_profiles_conserve_passenger_hours() -> None:
    """四种时间重排必须与基线拥有完全相同的 passenger-hours。"""

    baseline = tuple([0.25] * 24 + [0.75] * 48 + [0.25] * 24)
    target = person_hours(baseline, design_people=100.0)

    profiles = temporal_profiles(baseline)

    assert set(profiles) == {
        "morning_peak",
        "midday_peak",
        "evening_peak",
        "double_peak",
    }
    for profile in profiles.values():
        assert person_hours(profile, 100.0) == pytest.approx(target, rel=1e-9)
        assert len(profile) == 96
        assert min(profile) >= 0.0


def test_temporal_profiles_are_distinct_and_deterministic() -> None:
    """时间峰型既要真正不同，也要在重复构造时逐字节稳定。"""

    baseline = (0.5,) * 96
    first = temporal_profiles(baseline)
    second = temporal_profiles(baseline)

    assert first == second
    assert len({profile_digest(value) for value in first.values()}) == 4
    assert max(range(96), key=first["morning_peak"].__getitem__) in range(20, 36)
    assert max(range(96), key=first["midday_peak"].__getitem__) in range(44, 60)
    assert max(range(96), key=first["evening_peak"].__getitem__) in range(68, 88)


def test_spatial_redistribution_conserves_every_timestep() -> None:
    """空间重排保持每个时步的总 occupancy load，不只保持日积分。"""

    baselines = {
        "check_in": (2.0, 1.0, 0.0, 1.0),
        "gate": (0.0, 1.0, 2.0, 1.0),
    }
    redistributed = redistribute_spatial(
        baselines,
        {"check_in": 1.0, "security": 2.0, "gate": 5.0},
    )

    assert tuple(sum(values) for values in zip(*redistributed.values())) == pytest.approx(
        (2.0, 2.0, 2.0, 2.0)
    )
    assert sum(sum(values) for values in redistributed.values()) == pytest.approx(8.0)
    assert all(min(values) >= 0.0 for values in redistributed.values())


def test_volume_sensitivity_is_explicitly_nonconserving() -> None:
    """客流量敏感性用独立 API 表达，不能混入时间/空间守恒场景。"""

    baseline = (0.5,) * 96

    assert person_hours(scale_volume(baseline, 1.25), 100.0) == pytest.approx(
        1.25 * person_hours(baseline, 100.0)
    )


@pytest.mark.parametrize(
    "values",
    [(), (0.0, 0.0), (-1.0, 2.0), (math.nan, 1.0), (math.inf, 1.0)],
)
def test_normalize_profile_rejects_invalid_inputs(values: tuple[float, ...]) -> None:
    """空、零积分、负值及非有限输入均不得被静默修补。"""

    with pytest.raises(ValueError):
        normalize_profile(values)


def test_spatial_redistribution_rejects_mismatched_or_zero_weights() -> None:
    """不一致长度与零权重都必须显式失败。"""

    with pytest.raises(ValueError, match="profile_lengths_must_match"):
        redistribute_spatial({"a": (1.0,), "b": (1.0, 2.0)}, {"a": 1.0})
    with pytest.raises(ValueError, match="spatial_weights_must_have_positive_sum"):
        redistribute_spatial({"a": (1.0,)}, {"a": 0.0})
