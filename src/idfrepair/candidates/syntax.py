"""Exact delimiter recovery from parser state and the current-version IDD."""

from __future__ import annotations

from typing import Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.diagnostics.structural import SyntaxSite, detect_syntax_sites
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, DiagnosticRoot, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical, parse_idf


def _operation(text: str, site: SyntaxSite) -> RepairOperation:
    width = 24
    return RepairOperation(
        kind=OperationKind.INSERT_DELIMITER,
        object_type=site.object_type or None,
        object_index=site.object_index,
        metadata={
            "delimiter": site.delimiter,
            "offset": site.offset,
            "line_number": site.line_number,
            "structural_kind": site.kind,
            "next_object_type": site.next_object_type,
            "left_context": text[max(0, site.offset - width):site.offset],
            "right_context": text[site.offset:site.offset + width],
        },
    )


class SyntaxProvider(CandidateProvider):
    name = "syntax_delimiter"
    families = frozenset({"syntax"})

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        sites = detect_syntax_sites(
            context.document,
            context.idd,
            context.diagnostics_text,
            include_eof=True,
        )
        strong = tuple(site for site in sites if site.kind != "unterminated_eof")
        if strong:
            sites = strong
        if len(sites) != 1:
            return ()
        site = sites[0]
        operation = _operation(context.document.text, site)
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=(operation,),
        )
        interactive_only = site.kind == "unterminated_eof"
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="syntax",
            operations=(operation,),
            evidence=(
                CandidateEvidence(
                    kind="parser_state_boundary",
                    source="faulty_idf_parser",
                    strength=1.0,
                    details={
                        "kind": site.kind,
                        "line_number": site.line_number,
                        "delimiter": site.delimiter,
                    },
                ),
                CandidateEvidence(
                    kind="idd_object_boundary",
                    source="current_version_Energy+.idd",
                    strength=1.0 if not interactive_only else 0.6,
                    details={
                        "object_type": site.object_type,
                        "next_object_type": site.next_object_type,
                        "evidence": site.evidence,
                    },
                ),
            ),
            risk=RiskLevel.HIGH if interactive_only else RiskLevel.LOW,
            confidence=0.6 if interactive_only else 0.995,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            requires_user_confirmation=interactive_only,
            metadata={
                "mechanism": site.kind,
                "single_exact_delimiter_insertion": True,
                "automatic_policy": "interactive_only" if interactive_only else "unique_structural_boundary",
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        offset = operation.metadata.get("offset")
        delimiter = operation.metadata.get("delimiter")
        kind = str(operation.metadata.get("structural_kind") or "")
        reasons: list[str] = []
        if not isinstance(offset, int) or delimiter not in {",", ";"}:
            return False, ("syntax_operation_metadata_invalid",), {}
        expected = before[:offset] + str(delimiter) + before[offset:]
        if after != expected:
            reasons.append("syntax_patch_not_single_exact_insertion")
        old_document = parse_idf(before)
        new_document = parse_idf(after)
        if kind in {
            "missing_blank_comma",
            "missing_comma",
            "numeric_concatenation_comma",
            "schedule_compact_until_comma",
        }:
            if len(new_document.objects) != len(old_document.objects):
                reasons.append("comma_changed_object_count")
            target_index = operation.object_index
            if not isinstance(target_index, int) or target_index >= len(new_document.objects):
                reasons.append("comma_target_missing")
            else:
                old_obj = old_document.objects[target_index]
                new_obj = new_document.objects[target_index]
                if canonical(old_obj.object_type) != canonical(new_obj.object_type):
                    reasons.append("comma_changed_object_type")
                if len(new_obj.fields) != len(old_obj.fields) + 1:
                    reasons.append("comma_did_not_restore_field_boundary")
                definition = context.idd.get(new_obj.object_type)
                if definition is None:
                    reasons.append("comma_target_not_in_current_idd")
                elif definition.maximum_fields is not None and len(new_obj.fields) > definition.maximum_fields:
                    reasons.append("comma_exceeds_current_idd_shape")
        elif kind in {"missing_semicolon", "missing_object_type_comma"}:
            if len(new_document.objects) != len(old_document.objects) + 1:
                reasons.append("object_boundary_not_restored")
            expected_type = operation.object_type or ""
            if not any(canonical(obj.object_type) == canonical(expected_type) for obj in new_document.objects):
                reasons.append("restored_object_type_missing")
            next_type = operation.metadata.get("next_object_type")
            if isinstance(next_type, str) and next_type and not any(
                canonical(obj.object_type) == canonical(next_type) for obj in new_document.objects
            ):
                reasons.append("next_object_boundary_missing")
        elif kind == "unterminated_eof":
            if "unterminated_object" in new_document.issues:
                reasons.append("eof_object_still_unterminated")
            if len(new_document.objects) != len(old_document.objects) + 1:
                reasons.append("eof_object_not_recovered")
        else:
            reasons.append("syntax_mechanism_unknown")
        return not reasons, tuple(reasons), {
            "structural_kind": kind,
            "delimiter": delimiter,
            "offset": offset,
            "before_object_count": len(old_document.objects),
            "after_object_count": len(new_document.objects),
            "before_issues": old_document.issues,
            "after_issues": new_document.issues,
            "single_exact_insertion": after == expected,
        }


__all__ = ["SyntaxProvider"]
