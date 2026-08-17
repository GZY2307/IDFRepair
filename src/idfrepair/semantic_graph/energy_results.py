"""读取并比较 EnergyPlus 年度表格中的能耗证据。

read_annual_energy_summary(): 读取总场地能耗和 End Uses 表。
compare_annual_energy(): 计算 clean 与 faulty 年度结果差值。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AnnualEnergySummary:
    total_site_energy_gj: float | None
    end_uses: Mapping[str, Mapping[str, float]]


def _percent_delta(clean: float, faulty: float) -> float | None:
    if clean == 0.0:
        return None
    return (faulty - clean) / clean * 100.0


def compare_annual_energy(
    clean: AnnualEnergySummary,
    faulty: AnnualEnergySummary,
) -> dict[str, Any]:
    """返回不提前舍入的 clean-to-fault 总量与分项差值。"""

    clean_total = clean.total_site_energy_gj
    faulty_total = faulty.total_site_energy_gj
    if clean_total is None or faulty_total is None:
        total_delta = None
        total_percent = None
    else:
        total_delta = faulty_total - clean_total
        total_percent = _percent_delta(clean_total, faulty_total)
    end_use_deltas: dict[str, dict[str, dict[str, float | None]]] = {}
    for end_use in sorted(set(clean.end_uses) | set(faulty.end_uses)):
        clean_fuels = clean.end_uses.get(end_use, {})
        faulty_fuels = faulty.end_uses.get(end_use, {})
        fuel_deltas: dict[str, dict[str, float | None]] = {}
        for fuel in sorted(set(clean_fuels) | set(faulty_fuels)):
            clean_value = clean_fuels.get(fuel, 0.0)
            faulty_value = faulty_fuels.get(fuel, 0.0)
            fuel_deltas[fuel] = {
                "clean_gj": clean_value,
                "faulty_gj": faulty_value,
                "delta_gj": faulty_value - clean_value,
                "delta_percent": _percent_delta(clean_value, faulty_value),
            }
        end_use_deltas[end_use] = fuel_deltas
    return {
        "clean_total_site_energy_gj": clean_total,
        "faulty_total_site_energy_gj": faulty_total,
        "total_site_energy_delta_gj": total_delta,
        "total_site_energy_delta_percent": total_percent,
        "end_use_deltas": end_use_deltas,
    }


def _number(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def read_annual_energy_summary(path: Path | str) -> AnnualEnergySummary:
    """读取 EnergyPlus 总场地能耗与 End Uses 表。"""

    with Path(path).open(
        encoding="utf-8-sig", errors="replace", newline=""
    ) as handle:
        rows = list(csv.reader(handle))
    total: float | None = None
    for row in rows:
        if len(row) >= 3 and row[1].strip() == "Total Site Energy":
            total = _number(row[2])
            break
    try:
        table_start = next(
            index for index, row in enumerate(rows)
            if row and row[0].strip() == "End Uses"
        )
    except StopIteration:
        return AnnualEnergySummary(total_site_energy_gj=total, end_uses={})
    header_index = next((
        index for index in range(table_start + 1, len(rows))
        if len(rows[index]) >= 3 and "[GJ]" in rows[index][2]
    ), None)
    if header_index is None:
        return AnnualEnergySummary(total_site_energy_gj=total, end_uses={})
    header = rows[header_index]
    fuels = [
        cell.split("[", 1)[0].strip()
        for cell in header[2:]
    ]
    end_uses: dict[str, dict[str, float]] = {}
    for row in rows[header_index + 1:]:
        if len(row) < 2 or not row[1].strip():
            break
        name = row[1].strip()
        if name == "Total End Uses":
            break
        values: dict[str, float] = {}
        for fuel, cell in zip(fuels, row[2:]):
            if not fuel or not fuel.endswith(("Electricity", "Natural Gas")):
                continue
            value = _number(cell)
            if value is not None:
                values[fuel] = value
        end_uses[name] = values
    return AnnualEnergySummary(total_site_energy_gj=total, end_uses=end_uses)


__all__ = [
    "AnnualEnergySummary",
    "compare_annual_energy",
    "read_annual_energy_summary",
]
