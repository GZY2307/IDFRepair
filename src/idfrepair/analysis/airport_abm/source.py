"""Immutable source-model and mapping contracts for Airport Occupancy V3."""

from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SourceMappingError(ValueError):
    """Raised when the source mapping is incomplete or internally ambiguous."""


_FUNCTION_ALIASES = {
    "general_commercial": "commercial",
    "staff_breakroom": "breakroom",
    "information_room": "info",
}


@dataclass(frozen=True, slots=True)
class SourceSpace:
    """Public-safe subset of one source mapping row."""

    name: str
    thermal_zone: str
    region: str
    function: str
    source_function: str
    original_space_type: str
    area_m2: float
    people_m2_per_person: float | None
    source_design_people: float | None
    public_air_loop: str | None
    office_doas: str | None
    zone_hvac: str | None

    @property
    def bem_people_supported(self) -> bool:
        return self.source_design_people is not None

    @property
    def occupancy_evidence_status(self) -> str:
        if self.bem_people_supported:
            return "SOURCE_PEOPLE_SUPPORTED"
        return "FLOW_ONLY_NO_SOURCE_PEOPLE"


def _required_text(row: dict[str, str], field: str, line_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise SourceMappingError(f"line {line_number}: missing {field}")
    return value


def _optional_text(row: dict[str, str], field: str) -> str | None:
    value = (row.get(field) or "").strip()
    return value or None


def _required_positive_float(
    row: dict[str, str], field: str, line_number: int
) -> float:
    raw = _required_text(row, field, line_number)
    try:
        value = float(raw)
    except ValueError as exc:
        raise SourceMappingError(
            f"line {line_number}: invalid {field}: {raw}"
        ) from exc
    if value <= 0:
        raise SourceMappingError(f"line {line_number}: {field} must be positive")
    return value


def _optional_positive_float(
    row: dict[str, str], field: str, line_number: int
) -> float | None:
    raw = (row.get(field) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise SourceMappingError(
            f"line {line_number}: invalid {field}: {raw}"
        ) from exc
    if value <= 0:
        raise SourceMappingError(f"line {line_number}: {field} must be positive")
    return value


def load_space_mapping(path: str | Path) -> tuple[SourceSpace, ...]:
    """Load the explicit source mapping without inferring missing People data."""

    spaces: list[SourceSpace] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {
            "space",
            "thermal_zone",
            "region",
            "function",
            "original_space_type",
            "area_m2",
            "people_m2_per_person",
        }
        missing = required_fields.difference(reader.fieldnames or ())
        if missing:
            raise SourceMappingError(
                "missing columns: " + ", ".join(sorted(missing))
            )
        for line_number, row in enumerate(reader, start=2):
            name = _required_text(row, "space", line_number)
            if name in seen:
                raise SourceMappingError(f"duplicate space: {name}")
            seen.add(name)
            source_function = _required_text(row, "function", line_number)
            function = _FUNCTION_ALIASES.get(source_function, source_function)
            area_m2 = _required_positive_float(row, "area_m2", line_number)
            people_m2_per_person = _optional_positive_float(
                row, "people_m2_per_person", line_number
            )
            design_people = (
                area_m2 / people_m2_per_person
                if people_m2_per_person is not None
                else None
            )
            spaces.append(
                SourceSpace(
                    name=name,
                    thermal_zone=_required_text(row, "thermal_zone", line_number),
                    region=_required_text(row, "region", line_number),
                    function=function,
                    source_function=source_function,
                    original_space_type=_required_text(
                        row, "original_space_type", line_number
                    ),
                    area_m2=area_m2,
                    people_m2_per_person=people_m2_per_person,
                    source_design_people=design_people,
                    public_air_loop=_optional_text(row, "public_air_loop"),
                    office_doas=_optional_text(row, "office_doas"),
                    zone_hvac=_optional_text(row, "zone_hvac"),
                )
            )
    return tuple(spaces)


def mapping_inventory(spaces: Iterable[SourceSpace]) -> dict[str, int]:
    """Count canonical functions deterministically."""

    counts = Counter(space.function for space in spaces)
    return dict(sorted(counts.items()))
