"""Project raw EnergyPlus evidence onto deterministic actionable issue roots."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable, Mapping

from idfrepair.diagnostics.err_parser import Diagnostic, parse_err
from idfrepair.diagnostics.normalization import normalize_message
from idfrepair.domain.models import DiagnosticRoot, to_primitive
from idfrepair.io.idf import canonical


_CHAIN_TOKENS = (
    "errors found in getting",
    "errors occurred on processing input file",
    "energyplus terminated--fatal error detected",
    "getstageddualsetpoint",
    "schedule input",
)


def _diagnostic_row(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "continuation": list(diagnostic.continuation),
        "message": diagnostic.message,
        "severity": diagnostic.severity,
        "signature": diagnostic.signature,
    }


def _unique_diagnostics(
    diagnostics: Iterable[Diagnostic],
) -> tuple[Diagnostic, ...]:
    unique: dict[str, Diagnostic] = {}
    for diagnostic in diagnostics:
        signature = normalize_message(
            " ".join((diagnostic.message, *diagnostic.continuation)),
        )
        unique.setdefault(signature, diagnostic)
    return tuple(unique.values())


def _diagnostic_identity(diagnostic: Diagnostic) -> str:
    return normalize_message(" ".join((diagnostic.message, *diagnostic.continuation)))


def _cluster_id(root: DiagnosticRoot) -> str:
    owner = (
        root.metadata.get("object_index"),
        root.metadata.get("field_index"),
        root.family,
        root.root_id,
    )
    return sha256("|".join(map(str, owner)).encode("utf-8")).hexdigest()[:24]


def _owner(root: DiagnosticRoot) -> tuple[Any, Any, str] | None:
    object_index = root.metadata.get("object_index")
    field_index = root.metadata.get("field_index")
    if object_index is not None or field_index is not None:
        return object_index, field_index, root.family
    if root.object_type or root.object_name:
        return (
            canonical(root.object_type or ""),
            canonical(root.object_name or ""),
            root.family,
        )
    return None


def _fault_token(root: DiagnosticRoot) -> str:
    for key in ("faulty_value", "missing_reference_name", "variable_name"):
        value = root.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return canonical(value)
    return ""


def _same_evidence(left: DiagnosticRoot, right: DiagnosticRoot) -> bool:
    left_owner = _owner(left)
    right_owner = _owner(right)
    if left_owner is not None and left_owner == right_owner:
        return True
    if left_owner is not None and right_owner is not None:
        left_is_numeric = (
            left.metadata.get("object_index") is not None
            or left.metadata.get("field_index") is not None
        )
        right_is_numeric = (
            right.metadata.get("object_index") is not None
            or right.metadata.get("field_index") is not None
        )
        if left_is_numeric == right_is_numeric:
            return False
    left_token = _fault_token(left)
    right_token = _fault_token(right)
    if left_token and right_token and left_token == right_token:
        return left.family == right.family
    if left.family == right.family:
        left_message = canonical(left.message)
        right_message = canonical(right.message)
        if left_token and left_token in right_message:
            return True
        if right_token and right_token in left_message:
            return True
    return (
        normalize_message(left.message, replace_numbers=True)
        == normalize_message(right.message, replace_numbers=True)
        and left.family == right.family
        and left_owner == right_owner
    )


def _termination_chain_target(
    root: DiagnosticRoot,
    semantic: tuple[DiagnosticRoot, ...],
) -> DiagnosticRoot | None:
    if _owner(root) is not None:
        return None
    message = canonical(root.message)
    if not any(token in message for token in _CHAIN_TOKENS):
        return None
    if "schedule" in message or "getstageddualsetpoint" in message:
        matches = tuple(row for row in semantic if row.family == "reference_schedule")
        return matches[0] if len(matches) == 1 else None
    return semantic[0] if len(semantic) == 1 else None


def _root_positions(
    root: DiagnosticRoot,
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[int, ...]:
    signature_positions = tuple(
        index for index, diagnostic in enumerate(diagnostics)
        if diagnostic.signature in root.signatures
    )
    if signature_positions:
        return signature_positions
    root_message = normalize_message(root.message)
    if not root_message:
        return ()
    return tuple(
        index for index, diagnostic in enumerate(diagnostics)
        if root_message == _diagnostic_identity(diagnostic)
        or root_message in _diagnostic_identity(diagnostic)
    )


def _actionable_roots(
    roots: tuple[DiagnosticRoot, ...],
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[DiagnosticRoot, ...]:
    semantic = tuple(
        root for root in roots if root.metadata.get("semantic_issue") is True
    )
    actionable: list[DiagnosticRoot] = list(semantic)
    attached_positions: dict[str, set[int]] = {
        root.root_id: set() for root in semantic
    }
    pending: list[DiagnosticRoot] = []
    for root in roots:
        if root in semantic:
            continue
        matches = tuple(
            preferred for preferred in semantic if _same_evidence(root, preferred)
        )
        if len(matches) == 1:
            attached_positions[matches[0].root_id].update(
                _root_positions(root, diagnostics)
            )
            continue
        pending.append(root)
    pending.sort(key=lambda root: (
        min(_root_positions(root, diagnostics), default=len(diagnostics) + 1),
        roots.index(root),
    ))
    for root in pending:
        target = _termination_chain_target(root, semantic)
        positions = _root_positions(root, diagnostics)
        if target is not None and any(
            position - 1 in attached_positions[target.root_id]
            for position in positions
        ):
            attached_positions[target.root_id].update(positions)
            continue
        if any(_same_evidence(root, existing) for existing in actionable):
            continue
        actionable.append(root)
    return tuple(actionable)


def _diagnostic_owner_matches(root: DiagnosticRoot, diagnostic: Diagnostic) -> bool:
    combined = canonical(" ".join((diagnostic.message, *diagnostic.continuation)))
    token = _fault_token(root)
    if token and token in combined:
        return True
    named = tuple(
        canonical(value) for value in (root.object_type, root.object_name)
        if isinstance(value, str) and value.strip()
    )
    if bool(named) and all(value in combined for value in named):
        return True
    return normalize_message(root.message) == _diagnostic_identity(diagnostic)


def _assign_diagnostics(
    roots: tuple[DiagnosticRoot, ...],
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[tuple[Diagnostic, ...], ...]:
    assignments: list[list[Diagnostic]] = [[] for _ in roots]
    previous: int | None = None
    for diagnostic in diagnostics:
        matches = [
            index for index, root in enumerate(roots)
            if _diagnostic_owner_matches(root, diagnostic)
        ]
        if len(matches) == 1:
            previous = matches[0]
            assignments[previous].append(diagnostic)
            continue
        combined = canonical(" ".join((diagnostic.message, *diagnostic.continuation)))
        is_chain = any(token in combined for token in _CHAIN_TOKENS)
        if previous is not None and is_chain:
            assignments[previous].append(diagnostic)
        else:
            previous = None
    return tuple(tuple(rows) for rows in assignments)


def cluster_roots(
    roots: Iterable[DiagnosticRoot],
    diagnostics: Iterable[Diagnostic],
) -> tuple[dict[str, Any], ...]:
    """Return one cluster per currently actionable root.

    The first implementation deliberately keeps the raw rows independent of
    root construction: EnergyPlus messages remain evidence and are never
    rewritten into synthetic diagnostics.
    """
    evidence = _unique_diagnostics(diagnostics)
    root_rows = _actionable_roots(tuple(roots), evidence)
    assignments = _assign_diagnostics(root_rows, evidence)
    clusters = []
    for index, root in enumerate(root_rows):
        related = assignments[index]
        clusters.append({
            "cluster_id": _cluster_id(root),
            "root": to_primitive(root),
            "related_diagnostics": [_diagnostic_row(row) for row in related],
            "resolution": {
                "committed_operation_count": 0,
                "eliminated_related_diagnostic_count": 0,
                "resolved": False,
            },
            "question_ids": [],
            "presentation": {
                "resolution": {"zh-CN": "", "en": ""},
            },
        })
    return tuple(clusters)


def _root(value: Mapping[str, Any]) -> DiagnosticRoot:
    return DiagnosticRoot(
        root_id=str(value.get("root_id") or ""),
        family=str(value.get("family") or "unknown"),
        message=str(value.get("message") or ""),
        severity=str(value.get("severity") or "Severe"),
        object_type=(str(value["object_type"]) if value.get("object_type") else None),
        object_name=(str(value["object_name"]) if value.get("object_name") else None),
        field_name=(str(value["field_name"]) if value.get("field_name") else None),
        signatures=tuple(str(item) for item in value.get("signatures", ())),
        metadata=dict(value.get("metadata", {})),
    )


def _report_diagnostics(report: Mapping[str, Any]) -> tuple[Diagnostic, ...]:
    if "initial_energyplus_err" in report:
        return parse_err(str(report.get("initial_energyplus_err") or ""))
    raw = report.get("raw_energyplus_err", ())
    if not raw and report.get("initial_energyplus_diagnostics"):
        raw = (report["initial_energyplus_diagnostics"],)
    first = next((str(value) for value in raw if value), "")
    text = first
    return parse_err(text)


def _round_operations(round_: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    candidate = round_.get("candidate", {})
    if not isinstance(candidate, Mapping):
        return ()
    operations = candidate.get("operations", candidate.get("patch", ()))
    return tuple(row for row in operations if isinstance(row, Mapping))


def _bind_transition_evidence(
    report: Mapping[str, Any],
    clusters: list[dict[str, Any]],
    diagnostics: tuple[Diagnostic, ...],
) -> None:
    by_root = {
        str(cluster["root"].get("root_id") or ""): cluster for cluster in clusters
    }
    assigned = {
        normalize_message(" ".join((
            str(row.get("message") or ""),
            *(str(value) for value in row.get("continuation", ())),
        )))
        for cluster in clusters
        for row in cluster["related_diagnostics"]
        if isinstance(row, Mapping)
    }
    attempts = report.get("candidate_attempts", report.get("attempts", ()))
    for attempt in attempts if isinstance(attempts, (list, tuple)) else ():
        if not isinstance(attempt, Mapping) or attempt.get("accepted") is not True:
            continue
        target = by_root.get(str(attempt.get("root_id") or ""))
        result = attempt.get("energyplus_result")
        if target is None or not isinstance(result, Mapping):
            continue
        after = parse_err(str(result.get("diagnostics") or ""))
        after_signatures = {_diagnostic_identity(row) for row in after}
        for diagnostic in diagnostics:
            identity = _diagnostic_identity(diagnostic)
            if (
                identity in assigned
                or identity in after_signatures
            ):
                continue
            target["related_diagnostics"].append(_diagnostic_row(diagnostic))
            assigned.add(identity)


def build_issue_clusters(
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Build report-facing issue clusters without mutating raw report fields."""
    initial = tuple(
        _root(value) for value in report.get("initial_diagnostics", ())
        if isinstance(value, Mapping)
    )
    final_ids = {
        str(value.get("root_id"))
        for value in report.get("final_diagnostics", ())
        if isinstance(value, Mapping)
    }
    questions = tuple(
        value for value in report.get("user_questions", report.get("questions", ()))
        if isinstance(value, Mapping)
    )
    rounds = tuple(
        value for value in report.get("rounds", report.get("committed_rounds", ()))
        if isinstance(value, Mapping)
    )
    diagnostics = _report_diagnostics(report)
    base_clusters = list(cluster_roots(initial, diagnostics))
    _bind_transition_evidence(report, base_clusters, diagnostics)
    clusters = []
    for cluster in base_clusters:
        root_id = str(cluster["root"].get("root_id") or "")
        operations = tuple(
            operation
            for round_ in rounds
            if isinstance(round_.get("root"), Mapping)
            and str(round_["root"].get("root_id") or "") == root_id
            for operation in _round_operations(round_)
        )
        related_count = len(cluster["related_diagnostics"])
        resolved = root_id not in final_ids
        operation_count = len(operations)
        cluster["resolution"] = {
            "committed_operation_count": operation_count,
            "eliminated_related_diagnostic_count": related_count if resolved else 0,
            "resolved": resolved,
        }
        cluster["question_ids"] = [
            str(question.get("question_id")) for question in questions
            if str(question.get("root_id") or "") == root_id
            and question.get("question_id")
        ]
        cluster["presentation"] = {
            "resolution": {
                "zh-CN": (
                    f"{operation_count} 处修改同时消除了 {related_count} 条相关日志"
                    if resolved and operation_count else ""
                ),
                "en": (
                    f"{operation_count} change eliminated {related_count} related logs"
                    if resolved and operation_count else ""
                ),
            },
        }
        clusters.append(cluster)
    return tuple(clusters)


def has_renderable_questions(report: Mapping[str, Any]) -> bool:
    """Whether the payload contains a concrete, target-bound user control."""
    questions = report.get("user_questions", report.get("questions", ()))
    for question in questions if isinstance(questions, (list, tuple)) else ():
        if not isinstance(question, Mapping):
            continue
        choices = question.get("choices", ())
        if isinstance(choices, (list, tuple)) and any(
            isinstance(choice, Mapping)
            and any(
                choice.get(key) is not None and choice.get(key) != ""
                for key in ("candidate_id", "value", "family")
            )
            for choice in choices
        ):
            return True
        question_type = str(question.get("question_type") or "")
        metadata = question.get("metadata", {})
        if not isinstance(metadata, Mapping):
            continue
        if question_type == "enter_field_value" and (
            metadata.get("object_index") is not None
            and metadata.get("field_index") is not None
        ):
            return True
        if question_type == "provide_external_file" and metadata.get("relative_path"):
            return True
    return False


__all__ = ["build_issue_clusters", "cluster_roots", "has_renderable_questions"]
