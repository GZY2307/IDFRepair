"""Minimal but version-aware EnergyPlus IDD parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import Iterator

from idfrepair.io.idf import canonical


_FIELD = re.compile(r"^\s*([AN]\d+)\s*[,;]", re.I)
_OBJECT = re.compile(r"^\s*([^!\\][^,;]*?)\s*[,;]\s*(?:!.*)?$")
_DIRECTIVE = re.compile(
    r"\\([A-Za-z0-9_>\-]+)(?:\s*:\s*|\s+)?([^\\!]*?)(?=\\|!|$)"
)
_VERSION = re.compile(r"!\s*IDD_Version\s+([^\s]+)", re.I)


@dataclass(frozen=True, slots=True)
class IDDField:
    index: int
    token: str
    name: str
    required: bool = False
    keys: tuple[str, ...] = ()
    object_lists: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    data_type: str | None = None
    default: str | None = None
    units: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    extensible: bool = False

    @property
    def field_id(self) -> str:
        """Return the stable IDD token used inside one object definition."""
        return self.token

    @property
    def role(self) -> str:
        name = canonical(self.name)
        if "variable" in name and "name" in name:
            return "output_variable"
        if self.object_lists:
            object_lists = {
                canonical(value).replace(" ", "") for value in self.object_lists
            }
            if any(
                "schedule" in value and "scheduletypelimits" not in value
                for value in object_lists
            ):
                return "schedule_reference"
            return "object_reference"
        if "schedule" in name and "name" in name:
            return "schedule_reference"
        if "vertex" in name and "coordinate" in name:
            return "vertex_coordinate"
        return "field"


@dataclass(frozen=True, slots=True)
class IDDObject:
    name: str
    fields: tuple[IDDField, ...]
    extensible: int | None = None
    required: bool = False
    groups: tuple[str, ...] = ()

    @property
    def minimum_fields(self) -> int:
        required = [field.index for field in self.fields if field.required]
        return max(required, default=0)

    @property
    def maximum_fields(self) -> int | None:
        return None if self.extensible else len(self.fields)

    def field_at(self, index: int) -> IDDField | None:
        if 1 <= index <= len(self.fields):
            return self.fields[index - 1]
        if self.extensible and self.fields:
            start = len(self.fields) - self.extensible + 1
            if index >= start:
                return self.fields[start - 1 + ((index - start) % self.extensible)]
        return None

    @property
    def extensible_start(self) -> int | None:
        """Return the exact begin-extensible index, never the expanded tail."""

        starts = tuple(field.index for field in self.fields if field.extensible)
        if starts:
            return starts[0]
        if self.extensible and len(self.fields) >= self.extensible:
            return len(self.fields) - self.extensible + 1
        return None

    def semantic_field_at(self, index: int) -> IDDField | None:
        """Map repeated fields to the begin-extensible template slot.

        EnergyPlus IDDs may pre-expand a finite display range and then use
        shorthand tokens for later repetitions.  Semantic consumers need the
        exact begin marker and group offset, not the last parsed display field.
        """

        start = self.extensible_start
        if self.extensible and start is not None and index >= start:
            template_index = start + ((index - start) % self.extensible)
            if 1 <= template_index <= len(self.fields):
                return self.fields[template_index - 1]
            return None
        return self.field_at(index)


@dataclass(frozen=True, slots=True)
class IDDSchema:
    text: str
    version: str
    objects: dict[str, IDDObject]

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    def get(self, object_type: str) -> IDDObject | None:
        return self.objects.get(canonical(object_type))

    def reference_fields(self) -> Iterator[tuple[IDDObject, IDDField]]:
        for definition in self.objects.values():
            for field in definition.fields:
                if field.object_lists or field.role.endswith("reference"):
                    yield definition, field


def _directives(line: str) -> list[tuple[str, str]]:
    return [
        (match.group(1).casefold(), (match.group(2) or "").strip())
        for match in _DIRECTIVE.finditer(line)
    ]


def _as_float(value: str) -> float | None:
    try:
        return float(value.split()[0])
    except (IndexError, ValueError):
        return None


def parse_idd(text: str) -> IDDSchema:
    """Parse object and field metadata needed by safe repair providers."""
    version_match = _VERSION.search(text)
    version = version_match.group(1).rstrip("0").rstrip(".") if version_match else ""
    definitions: dict[str, IDDObject] = {}
    current_name: str | None = None
    current_fields: list[dict[str, object]] = []
    current_extensible: int | None = None
    current_required = False
    current_groups: list[str] = []
    current_field: dict[str, object] | None = None

    def finish_object() -> None:
        nonlocal current_name, current_fields, current_extensible
        nonlocal current_required, current_groups, current_field
        if not current_name:
            return
        fields = tuple(
            IDDField(
                index=index,
                token=str(row["token"]),
                name=str(row.get("name") or row["token"]),
                required=bool(row.get("required", False)),
                keys=tuple(row.get("keys", ())),
                object_lists=tuple(row.get("object_lists", ())),
                references=tuple(row.get("references", ())),
                data_type=str(row["data_type"]) if row.get("data_type") else None,
                default=str(row["default"]) if row.get("default") is not None else None,
                units=str(row["units"]) if row.get("units") else None,
                minimum=row.get("minimum") if isinstance(row.get("minimum"), float) else None,
                maximum=row.get("maximum") if isinstance(row.get("maximum"), float) else None,
                extensible=bool(row.get("extensible", False)),
            )
            for index, row in enumerate(current_fields, start=1)
        )
        definitions[canonical(current_name)] = IDDObject(
            name=current_name,
            fields=fields,
            extensible=current_extensible,
            required=current_required,
            groups=tuple(current_groups),
        )
        current_name = None
        current_fields = []
        current_extensible = None
        current_required = False
        current_groups = []
        current_field = None

    for raw in text.splitlines():
        stripped = raw.strip()
        field_match = _FIELD.match(raw)
        object_match = _OBJECT.match(raw)
        if field_match and current_name:
            current_field = {
                "token": field_match.group(1).upper(),
                "keys": [],
                "object_lists": [],
                "references": [],
            }
            current_fields.append(current_field)
        elif object_match and not stripped.startswith(("\\", "!")):
            name = object_match.group(1).strip()
            if not _FIELD.match(raw) and " " not in name.strip() and name:
                finish_object()
                current_name = name
        for directive, value in _directives(raw):
            if current_field is not None:
                if directive == "field" and value:
                    current_field["name"] = value
                elif directive == "required-field":
                    current_field["required"] = True
                elif directive == "key" and value:
                    current_field.setdefault("keys", []).append(value)
                elif directive == "object-list" and value:
                    current_field.setdefault("object_lists", []).append(value)
                elif directive == "reference" and value:
                    current_field.setdefault("references", []).append(value)
                elif directive == "type" and value:
                    current_field["data_type"] = value
                elif directive == "default":
                    current_field["default"] = value
                elif directive == "units" and value:
                    current_field["units"] = value
                elif directive == "begin-extensible":
                    current_field["extensible"] = True
                elif directive in {"minimum", "minimum>"}:
                    current_field["minimum"] = _as_float(value)
                elif directive in {"maximum", "maximum<"}:
                    current_field["maximum"] = _as_float(value)
            if current_name:
                if directive == "extensible":
                    value_match = re.search(r"(\d+)", value)
                    current_extensible = int(value_match.group(1)) if value_match else 1
                elif directive == "required-object":
                    current_required = True
                elif directive == "group" and value:
                    current_groups.append(value)
    finish_object()
    return IDDSchema(text=text, version=version, objects=definitions)
