"""General deterministic mechanisms recovered from the historical P5 engine."""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Sequence

from idfrepair.candidates.base import (
    CandidateContext,
    CandidateProvider,
    candidate_identity,
)
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import (
    CandidateEvidence,
    DiagnosticRoot,
    RepairCandidate,
    RepairOperation,
)
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.provenance import semantic_multiset, unique_missing_reference


_INVALID_DESIGN = re.compile(
    r"Object\s*=\s*(?P<owner_type>.+?)\s+with\s+the\s+Name\s*=\s*"
    r"(?P<owner_name>.+?)\s+has\s+an\s+invalid\s+Design\s+Object\s+Name\s*=\s*"
    r"(?P<reference>.+?)\.",
    re.I,
)


def _render_object(object_type: str, fields: Sequence[str]) -> str:
    lines = [f"{object_type},"]
    for index, value in enumerate(fields):
        delimiter = ";" if index == len(fields) - 1 else ","
        lines.append(f"  {value}{delimiter}")
    return "\n".join(lines) + "\n"


def _number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _sizing_mode(
    value: str,
    axis: str,
    sibling_area_values: Sequence[str],
    sibling_fraction_values: Sequence[str],
) -> tuple[str, str, str] | None:
    folded = canonical(value).replace(" ", "")
    if folded == "autosize" or _number(folded):
        return f"{axis}DesignCapacity", "", ""
    if folded.startswith("capacityperfloorarea"):
        suffix = re.split(r"[:=]", value, maxsplit=1)
        number = suffix[1].strip() if len(suffix) == 2 else ""
        if not number:
            values = {item.strip() for item in sibling_area_values if item.strip()}
            number = next(iter(values)) if len(values) == 1 else ""
        return ("CapacityPerFloorArea", number, "") if number else None
    fraction_token = f"fractionofautosized{axis.casefold()}capacity"
    if folded.startswith(fraction_token):
        suffix = re.split(r"[:=]", value, maxsplit=1)
        number = suffix[1].strip() if len(suffix) == 2 else ""
        if not number:
            values = {
                item.strip() for item in sibling_fraction_values if item.strip()
            }
            number = next(iter(values)) if len(values) == 1 else ""
        return (
            f"FractionOfAutosized{axis}Capacity", "", number
        ) if number else None
    return None


class TypedDesignProvider(CandidateProvider):
    """Insert one missing typed design object from two closed peer edges."""

    name = "typed_design_consensus"
    families = frozenset({"hvac_reference"})

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        match = _INVALID_DESIGN.search(context.diagnostics_text)
        if match is None:
            return ()
        owners = context.document.find_objects(
            match.group("owner_type"), match.group("owner_name"),
        )
        if len(owners) != 1:
            return ()
        owner = owners[0]
        reference = match.group("reference").strip()
        owner_definition = context.idd.get(owner.object_type)
        if owner_definition is None:
            return ()
        target_fields = [
            field for field in owner.fields
            if canonical(field.value) == canonical(reference)
            and (
                owner_definition.field_at(field.index) is not None
                and owner_definition.field_at(field.index).object_lists
            )
        ]
        if len(target_fields) != 1:
            return ()
        target_field = target_fields[0]
        target_def = owner_definition.field_at(target_field.index)
        required_lists = {
            canonical(value) for value in target_def.object_lists
        }
        peers = [
            obj for obj in context.document.find_objects(owner.object_type)
            if obj.index != owner.index and target_field.index <= len(obj.fields)
        ]
        providers = []
        for peer in peers:
            peer_name = peer.fields[target_field.index - 1].value.strip()
            compatible = []
            for obj in context.document.objects:
                definition = context.idd.get(obj.object_type)
                declared = {
                    canonical(value)
                    for value in (
                        definition.fields[0].references
                        if definition is not None and definition.fields else ()
                    )
                }
                if (
                    canonical(obj.name) == canonical(peer_name)
                    and declared.intersection(required_lists)
                ):
                    compatible.append(obj)
            if len(compatible) == 1:
                providers.append(compatible[0])
        unique_providers = {
            (obj.index, canonical(obj.object_type), canonical(obj.name)): obj
            for obj in providers
        }
        typed = list(unique_providers.values())
        if len(typed) < 2:
            return ()
        provider_types = {canonical(obj.object_type) for obj in typed}
        if len(provider_types) != 1:
            return ()
        required_type = typed[0].object_type
        definition = context.idd.get(required_type)
        arities = {len(obj.fields) for obj in typed}
        if definition is None or len(arities) != 1:
            return ()
        arity = next(iter(arities))
        if arity < definition.minimum_fields or arity > len(definition.fields):
            return ()
        if context.document.find_objects(required_type, reference):
            return ()

        values: list[str | None] = []
        sources: list[str] = []
        for field_def in definition.fields[:arity]:
            siblings = [obj.fields[field_def.index - 1].value for obj in typed]
            unique = {value.strip() for value in siblings}
            if field_def.index == 1:
                values.append(reference)
                sources.append("diagnostic")
            elif len(unique) == 1:
                values.append(siblings[0].strip())
                sources.append("typed_peer_consensus")
            else:
                values.append(None)
                sources.append("unresolved")

        for axis in ("Heating", "Cooling"):
            owner_capacity = [
                field for field in owner_definition.fields
                if canonical(field.name) == canonical(f"{axis} Design Capacity")
            ]
            method = [
                field for field in definition.fields
                if canonical(field.name) == canonical(
                    f"{axis} Design Capacity Method"
                )
            ]
            area = [
                field for field in definition.fields
                if canonical(field.name) == canonical(
                    f"{axis} Design Capacity Per Floor Area"
                )
            ]
            fraction = [
                field for field in definition.fields
                if canonical(field.name) == canonical(
                    f"Fraction of Autosized {axis} Design Capacity"
                )
            ]
            if not (
                len(owner_capacity) == len(method) == len(area) == len(fraction) == 1
                and owner_capacity[0].index <= len(owner.fields)
            ):
                return ()
            sizing = _sizing_mode(
                owner.fields[owner_capacity[0].index - 1].value,
                axis,
                [obj.fields[area[0].index - 1].value for obj in typed],
                [obj.fields[fraction[0].index - 1].value for obj in typed],
            )
            if sizing is None:
                return ()
            for field_def, value in zip(
                (method[0], area[0], fraction[0]), sizing,
            ):
                values[field_def.index - 1] = value
                sources[field_def.index - 1] = "owner_sizing_semantics"
        if any(value is None for value in values):
            return ()
        rendered_values = tuple(str(value) for value in values)
        operation = RepairOperation(
            kind=OperationKind.INSERT_OBJECT,
            object_type=required_type,
            object_name=reference,
            object_text=_render_object(required_type, rendered_values),
            metadata={
                "field_sources": tuple(sources),
                "owner_index": owner.index,
                "owner_reference_field": target_field.index,
                "peer_object_indices": tuple(sorted(obj.index for obj in typed)),
            },
        )
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=(operation,),
        )
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="hvac_reference",
            operations=(operation,),
            evidence=(
                CandidateEvidence(
                    kind="idd_object_list",
                    source="current_version_Energy+.idd",
                    strength=1.0,
                    details={"reference_lists": tuple(sorted(required_lists))},
                ),
                CandidateEvidence(
                    kind="same_type_peer_consensus",
                    source="faulty_idf_object_graph",
                    strength=1.0,
                    details={"peer_count": len(typed), "arity": arity},
                ),
                CandidateEvidence(
                    kind="owner_sizing_semantics",
                    source="faulty_idf_and_current_idd",
                    strength=1.0,
                ),
            ),
            risk=RiskLevel.LOW,
            confidence=0.99,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            metadata={
                "historical_mechanism": "typed_design_consensus",
                "owner_index": owner.index,
                "owner_reference_field": target_field.index,
                "inserted_fields": rendered_values,
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        left = parse_idf(before)
        right = parse_idf(after)
        operation = candidate.operations[0]
        reasons = []
        if len(right.objects) != len(left.objects) + 1:
            reasons.append("typed_design_object_count_not_plus_one")
        if any(
            old.raw != new.raw
            for old, new in zip(left.objects, right.objects)
        ):
            reasons.append("typed_design_changed_existing_object")
        inserted = right.objects[-1] if right.objects else None
        if (
            inserted is None
            or canonical(inserted.object_type) != canonical(operation.object_type or "")
            or canonical(inserted.name) != canonical(operation.object_name or "")
            or tuple(field.value for field in inserted.fields)
            != tuple(candidate.metadata.get("inserted_fields", ()))
        ):
            reasons.append("typed_design_inserted_object_mismatch")
        owner_index = candidate.metadata.get("owner_index")
        field_index = candidate.metadata.get("owner_reference_field")
        if not isinstance(owner_index, int) or not isinstance(field_index, int):
            reasons.append("typed_design_owner_binding_missing")
        else:
            owner = right.objects[owner_index]
            value = owner.fields[field_index - 1].value
            providers = right.find_objects(operation.object_type or "", value)
            if len(providers) != 1 or providers[0].index != len(right.objects) - 1:
                reasons.append("typed_design_reference_not_closed_uniquely")
        return not reasons, tuple(reasons), {
            "before_object_count": len(left.objects),
            "after_object_count": len(right.objects),
            "mechanism": "typed_design_consensus",
        }


class ProvenanceObjectProvider(CandidateProvider):
    """Insert an object only from a unique same-version one-object superset."""

    name = "provenance_object"
    families = frozenset({"reference"})

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        resolution = root.metadata.get("provenance_resolution")
        if not isinstance(resolution, dict):
            return ()
        fields = resolution.get("fields")
        object_type = resolution.get("object_type")
        object_name = resolution.get("object_name")
        if (
            not isinstance(fields, (tuple, list))
            or not isinstance(object_type, str)
            or not isinstance(object_name, str)
            or resolution.get("unique_match_count") != 1
        ):
            return ()
        values = tuple(str(value) for value in fields)
        operation = RepairOperation(
            kind=OperationKind.INSERT_OBJECT,
            object_type=object_type,
            object_name=object_name,
            object_text=_render_object(object_type, values),
            metadata={
                "source_file_sha256": resolution.get("source_file_sha256"),
                "source_object_sha256": resolution.get("source_object_sha256"),
                "resolver_version": resolution.get("resolver_version"),
            },
        )
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=(operation,),
        )
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="reference",
            operations=(operation,),
            evidence=(
                CandidateEvidence(
                    kind="idd_object_list",
                    source="current_version_Energy+.idd",
                    strength=1.0,
                    details={
                        "reference_lists": root.metadata.get(
                            "missing_reference_lists", ()
                        ),
                    },
                ),
                CandidateEvidence(
                    kind="version_bound_single_object_superset",
                    source=str(resolution.get("source_path", "")),
                    strength=1.0,
                    details={
                        "source_file_sha256": resolution.get(
                            "source_file_sha256"
                        ),
                        "source_object_sha256": resolution.get(
                            "source_object_sha256"
                        ),
                        "match_evidence": resolution.get("match_evidence", ()),
                    },
                ),
            ),
            risk=RiskLevel.LOW,
            confidence=1.0,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            metadata={
                "historical_mechanism": "provenance_single_object_superset",
                "inserted_fields": values,
                "resolution": resolution,
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        left = parse_idf(before)
        right = parse_idf(after)
        operation = candidate.operations[0]
        reasons = []
        difference = semantic_multiset(right) - semantic_multiset(left)
        removed = semantic_multiset(left) - semantic_multiset(right)
        if sum(difference.values()) != 1 or removed:
            reasons.append("provenance_patch_not_exact_single_object_addition")
        if len(right.objects) != len(left.objects) + 1:
            reasons.append("provenance_object_count_not_plus_one")
        if any(
            old.raw != new.raw
            for old, new in zip(left.objects, right.objects)
        ):
            reasons.append("provenance_patch_changed_existing_object")
        matches = right.find_objects(
            operation.object_type or "", operation.object_name,
        )
        if len(matches) != 1:
            reasons.append("provenance_inserted_identity_not_unique")
        elif tuple(field.value for field in matches[0].fields) != tuple(
            candidate.metadata.get("inserted_fields", ())
        ):
            reasons.append("provenance_inserted_fields_mismatch")
        before_missing = unique_missing_reference(left, context.idd)
        after_missing = unique_missing_reference(right, context.idd)
        if before_missing is None:
            reasons.append("provenance_missing_reference_not_unique_before")
        if (
            after_missing is not None
            and before_missing is not None
            and canonical(after_missing.name) == canonical(before_missing.name)
        ):
            reasons.append("provenance_reference_not_closed")
        return not reasons, tuple(reasons), {
            "added_semantic_rows": sum(difference.values()),
            "mechanism": "provenance_single_object_superset",
        }


__all__ = ["ProvenanceObjectProvider", "TypedDesignProvider"]
