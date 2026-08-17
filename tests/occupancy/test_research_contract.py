"""锁定 occupancy 文献现实边界与预注册场景协议。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LITERATURE_PATH = (
    PROJECT_ROOT / "docs" / "research" / "occupancy" / "airport_occupancy_literature_gap.md"
)
PROTOCOL_PATH = (
    PROJECT_ROOT / "docs" / "research" / "occupancy" / "occupancy_scenario_protocol.md"
)


def test_literature_gap_disclaims_commonplace_dynamic_occupancy_claim() -> None:
    """动态人数和早中晚 EnergyPlus 敏感性必须明确标为不新颖。"""

    text = LITERATURE_PATH.read_text(encoding="utf-8")
    lowered = text.casefold()

    assert "not novel" in lowered
    assert "same passenger-hours" in lowered
    assert "Sinha" in text and "Gu" in text
    assert "10.26868/25222708.2019.211133" in text
    assert "10.1016/j.buildenv.2021.108147" in text
    assert "10.1016/j.scs.2021.103619" in text
    assert "10.1016/j.seta.2024.103790" in text
    assert "10.1016/j.buildenv.2025.112781" in text
    assert "10.1016/j.buildenv.2025.112829" in text
    assert "10.1016/j.rser.2025.116287" in text
    assert "first dynamic airport occupancy" not in lowered


def test_literature_gap_separates_prior_capabilities_from_scoped_contribution() -> None:
    """文献地图必须覆盖既有 ABM/BEM/control，并把本项目限定为 compiler workflow。"""

    text = LITERATURE_PATH.read_text(encoding="utf-8")

    for phrase in (
        "agent-based",
        "one-minute",
        "zone-wise",
        "EnergyPlus",
        "IES",
        "occupant-centric ventilation",
        "IDF-native occupancy scenario compiler",
        "People→Zone→HVAC",
    ):
        assert phrase.casefold() in text.casefold(), phrase


def test_protocol_freezes_conserved_and_volume_scenarios() -> None:
    """protocol 在看结果前锁定时间窗、守恒、空间与独立 volume controls。"""

    text = PROTOCOL_PATH.read_text(encoding="utf-8")

    for phrase in (
        "15-minute",
        "1e-9",
        "05:00–09:00",
        "11:00–15:00",
        "17:00–22:00",
        "morning_peak",
        "midday_peak",
        "evening_peak",
        "double_peak",
        "same passenger-hours",
        "0.50x",
        "0.75x",
        "1.00x",
        "1.25x",
        "1.50x",
    ):
        assert phrase in text, phrase


def test_protocol_records_controlled_data_and_failure_boundaries() -> None:
    """无 flight data、synthetic HVAC 与缺失输出的边界必须可见。"""

    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    lowered = text.casefold()

    assert "not a passenger-flow forecast" in lowered
    assert "unavailable" in lowered
    assert "schedule:file" in lowered
    assert "8760" in text and "365 × 96" in text
    assert "OCCUPANCY_DEMO_ONLY" in text
    assert "does not block" in lowered
    assert "raw OSM" in text
