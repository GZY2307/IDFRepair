"""生成不含私有对象名的 occupancy 论文/审计静态图。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from idfrepair.analysis.occupancy.models import ScenarioSummary


_BLUE = "#356AA0"
_ORANGE = "#D97732"
_GOLD = "#C9A227"
_OLIVE = "#738B3A"
_PINK = "#B65A7A"
_INK = "#252A31"
_GRID = "#D9DEE5"
_PALETTE = (_BLUE, _ORANGE, _GOLD, _OLIVE, _PINK)


def _hours(count: int) -> list[float]:
    return [(index + 1) * 24.0 / count for index in range(count)]


def write_occupancy_figures(
    *,
    summaries: Sequence[ScenarioSummary],
    time_series: Mapping[str, Mapping[str, Sequence[float]]],
    profiles: Mapping[str, Mapping[str, Sequence[float]]],
    design_people: Mapping[str, float],
    group_aliases: Mapping[str, str],
    output_directory: Path,
) -> tuple[Path, ...]:
    """写三张可复现 PNG，并返回路径。

    图表契约：比较图回答同 passenger-hours 的日热负荷差异；时序图回答峰值
    时移；热图回答 neutral People 组的时空重排。所有图使用 15 分钟、单日、
    synthetic Ideal Loads 边界，且不暴露私有 zone/object 名。
    """

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "axes.edgecolor": _INK,
            "axes.labelcolor": _INK,
            "axes.titlecolor": _INK,
            "axes.titlesize": 11,
            "axes.titleweight": "semibold",
            "figure.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "grid.color": _GRID,
            "grid.linewidth": 0.7,
            "text.color": _INK,
            "xtick.color": _INK,
            "ytick.color": _INK,
        }
    )
    by_name = {row.scenario_name: row for row in summaries}
    comparison_names = [
        name
        for name in (
            "existing_baseline",
            "morning_peak",
            "midday_peak",
            "evening_peak",
            "double_peak",
            "spatial_concentrated",
            "spatial_distributed",
        )
        if name in by_name
    ]
    display = [name.replace("_", " ") for name in comparison_names]
    baseline_heating = by_name["existing_baseline"].synthetic_heating_kwh or 0.0
    baseline_cooling = by_name["existing_baseline"].synthetic_cooling_kwh or 0.0
    heating = [
        100.0 * ((by_name[name].synthetic_heating_kwh or 0.0) - baseline_heating)
        / baseline_heating
        for name in comparison_names
    ]
    cooling = [
        100.0 * ((by_name[name].synthetic_cooling_kwh or 0.0) - baseline_cooling)
        / baseline_cooling
        for name in comparison_names
    ]
    y = np.arange(len(comparison_names))
    fig, ax = plt.subplots(figsize=(9.2, 5.2), constrained_layout=True)
    height = 0.36
    ax.barh(
        y - height / 2,
        heating,
        height,
        color=_BLUE,
        edgecolor=_INK,
        linewidth=0.5,
        label="Heating",
    )
    ax.barh(
        y + height / 2,
        cooling,
        height,
        color=_ORANGE,
        edgecolor=_INK,
        linewidth=0.5,
        hatch="//",
        label="Cooling",
    )
    ax.set_yticks(y, display)
    ax.invert_yaxis()
    ax.set_xlabel("Change from existing-schedule baseline (%)")
    ax.set_title("Same-passenger-hours thermal-load response", loc="left", pad=25)
    ax.text(
        0,
        1.01,
        "Representative weekday; 15-minute controlled scenarios; original HVAC absent",
        transform=ax.transAxes,
        fontsize=8,
        color="#596273",
    )
    ax.grid(axis="x")
    ax.axvline(0.0, color=_INK, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right")
    comparison_path = destination / "same_passenger_hours_load_comparison.png"
    fig.savefig(comparison_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    temporal_names = [
        name
        for name in (
            "existing_baseline",
            "morning_peak",
            "midday_peak",
            "evening_peak",
            "double_peak",
        )
        if name in time_series
    ]
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 7.0), sharex=True, constrained_layout=True)
    for index, name in enumerate(temporal_names):
        series = time_series[name]
        occupancy = list(series.get("occupancy", ()))
        heating_rate = list(series.get("synthetic_heating_kw", ()))
        cooling_rate = list(series.get("synthetic_cooling_kw", ()))
        if not occupancy:
            continue
        x = _hours(len(occupancy))
        color = _PALETTE[index % len(_PALETTE)]
        linestyle = "--" if name == "existing_baseline" else "-"
        axes[0].plot(
            x,
            occupancy,
            label=name.replace("_", " "),
            color=color,
            linewidth=1.6,
            linestyle=linestyle,
        )
        thermal_rate = [
            (heating_rate[i] if i < len(heating_rate) else 0.0)
            + (cooling_rate[i] if i < len(cooling_rate) else 0.0)
            for i in range(len(occupancy))
        ]
        axes[1].plot(
            x,
            thermal_rate,
            color=color,
            linewidth=1.6,
            linestyle=linestyle,
        )
    axes[0].set_title(
        "Occupancy and synthetic thermal-load timing", loc="left", pad=25
    )
    axes[0].text(
        0,
        1.01,
        "All profiles have the same daily passenger-hours; lines differ in timing only",
        transform=axes[0].transAxes,
        fontsize=8,
        color="#596273",
    )
    axes[0].set_ylabel("Occupants")
    axes[1].set_ylabel("Heating + cooling rate (kW)")
    axes[1].set_xlabel("Hour of day")
    for ax in axes:
        ax.grid(True)
        ax.set_xlim(0, 24)
        ax.set_axisbelow(True)
    axes[0].legend(
        ncol=1,
        frameon=False,
        loc="upper left",
        bbox_to_anchor=(1.005, 1.0),
    )
    time_path = destination / "occupancy_load_time_series.png"
    fig.savefig(time_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    heatmap_names = [
        name
        for name in (
            "existing_baseline",
            "spatial_concentrated",
            "spatial_distributed",
        )
        if name in profiles
    ]
    group_names = tuple(design_people)
    matrices = []
    for name in heatmap_names:
        matrix = np.array(
            [[float(value) for value in profiles[name][group]] for group in group_names]
        )
        matrices.append(matrix)
    vmax = max(float(matrix.max()) for matrix in matrices) if matrices else 1.0
    fig, axes = plt.subplots(
        len(matrices),
        1,
        figsize=(10.5, 2.2 * max(1, len(matrices))),
        sharex=True,
        constrained_layout=True,
    )
    axes_array = np.atleast_1d(axes)
    image = None
    for ax, name, matrix in zip(axes_array, heatmap_names, matrices):
        image = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap="YlOrBr",
            vmin=0.0,
            vmax=vmax,
            extent=(0, 24, len(group_names) - 0.5, -0.5),
        )
        ax.set_yticks(
            range(len(group_names)),
            [group_aliases[group] for group in group_names],
        )
        ax.set_title(name.replace("_", " "), loc="left")
    axes_array[-1].set_xlabel("Hour of day")
    if image is not None:
        colorbar = fig.colorbar(image, ax=list(axes_array), pad=0.01)
        colorbar.set_label("Occupancy / translated design count")
    heatmap_path = destination / "neutral_group_occupancy_heatmap.png"
    fig.savefig(heatmap_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return comparison_path, time_path, heatmap_path


__all__ = ["write_occupancy_figures"]
