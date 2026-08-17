'''
扫描全文件的 IDD、object-list、Schedule 与 RDD 有限语义问题。

scan_semantic_issues(): 返回不依赖 fatal/severe root 的问题清单和审计状态。
'''

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence

from idfrepair.domain.models import DiagnosticRoot
from idfrepair.io.idf import IDFDocument, canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.knowledge.rdd import RDDCatalog


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    '''描述一个全文件、字段绑定且具有明确可恢复性的语义问题。'''

    issue_id: str
    family: str
    object_identity: Mapping[str, Any]
    field_identity: Mapping[str, Any]
    severity: str
    recoverability: str
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        '''返回稳定、可报告的问题对象。'''
        return {
            "evidence": dict(self.evidence),
            "family": self.family,
            "field_identity": dict(self.field_identity),
            "issue_id": self.issue_id,
            "object_identity": dict(self.object_identity),
            "recoverability": self.recoverability,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class SemanticPreflight:
    '''封装全部语义问题和分域审计布尔值。'''

    issues: tuple[SemanticIssue, ...]
    audit: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        '''返回 runner 可冻结的预检证据。'''
        return {
            "audit": dict(self.audit),
            "issues": [issue.to_dict() for issue in self.issues],
            "supported_issue_count": sum(
                issue.recoverability == "RECOVERABLE" for issue in self.issues
            ),
            "ambiguous_issue_count": sum(
                issue.recoverability == "AMBIGUOUS" for issue in self.issues
            ),
        }


def _distance(left: str, right: str) -> int:
    '''计算两个规范字符串的 Levenshtein 距离。'''
    previous = list(range(len(right) + 1))
    for row_index, left_character in enumerate(left, start=1):
        current = [row_index]
        for column, right_character in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + int(left_character != right_character),
            ))
        previous = current
    return previous[-1]


def _compact(value: str) -> str:
    '''移除非字母数字字符供有限 typo 比较。'''
    return "".join(character for character in value.casefold() if character.isalnum())


def bounded_unique_choice(
    faulty: str,
    choices: Sequence[str],
) -> tuple[str, int] | None:
    '''返回距离一到二且最近合法值唯一的候选。'''
    nearest = bounded_nearest_choices(faulty, choices)
    if len(nearest) != 1:
        return None
    return nearest[0]


def bounded_nearest_choices(
    faulty: str,
    choices: Sequence[str],
) -> tuple[tuple[str, int], ...]:
    '''返回距离一到二的全部同距最近合法值，显式保留 tie。'''
    unique = {canonical(choice): choice for choice in choices}
    scored = sorted(
        (_distance(_compact(faulty), _compact(choice)), canonical(choice), choice)
        for choice in unique.values()
    )
    if not scored or scored[0][0] not in {1, 2}:
        return ()
    best = [row for row in scored if row[0] == scored[0][0]]
    return tuple((row[2], row[0]) for row in best)


def _references(
    document: IDFDocument,
    idd: IDDSchema,
) -> dict[str, tuple[str, ...]]:
    '''收集当前文件中每个 IDD reference-list 的唯一合法名称。'''
    values: dict[str, set[str]] = {}
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field.value:
                continue
            for reference in field_def.references:
                values.setdefault(canonical(reference), set()).add(field.value)
    return {
        key: tuple(sorted(rows, key=canonical))
        for key, rows in values.items()
    }


def _issue(
    *,
    family: str,
    obj: Any,
    field: Any | None,
    field_name: str | None,
    faulty_value: str,
    recoverability: str,
    evidence: Mapping[str, Any],
) -> SemanticIssue:
    '''构造跨修复轮次稳定的字段问题身份。'''
    field_index = field.index if field is not None else None
    payload = "|".join((
        family,
        str(obj.index),
        canonical(obj.object_type),
        str(field_index),
        canonical(faulty_value),
    ))
    return SemanticIssue(
        issue_id=sha256(payload.encode("utf-8")).hexdigest()[:24],
        family=family,
        object_identity={
            "object_index": obj.index,
            "object_name": obj.name or None,
            "object_type": obj.object_type,
        },
        field_identity={
            "field_index": field_index,
            "field_name": field_name,
        },
        severity="Severe" if recoverability == "RECOVERABLE" else "Warning",
        recoverability=recoverability,
        evidence={**evidence, "faulty_value": faulty_value},
    )


def _reference_issues(
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
) -> list[SemanticIssue]:
    '''识别所有缺失 object-list 引用并区分唯一 typo 与歧义。'''
    inventories = _references(document, idd)
    diagnostic_blocks: list[tuple[str, list[str]]] = []
    for line in diagnostics_text.splitlines():
        normalized = canonical(line)
        severity = next((
            value for value in ("fatal", "severe", "warning")
            if f"** {value}" in normalized
        ), None)
        if severity is not None:
            diagnostic_blocks.append((severity, [normalized]))
        elif diagnostic_blocks and "~~~" in line:
            diagnostic_blocks[-1][1].append(normalized)

    def actionable_diagnostic(value: str) -> bool:
        target = canonical(value)
        return any(
            severity in {"fatal", "severe"}
            and target in " ".join(lines)
            for severity, lines in diagnostic_blocks
        )
    issues = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field_def.object_lists or not field.value.strip():
                continue
            choices = tuple(sorted({
                value
                for object_list in field_def.object_lists
                for value in inventories.get(canonical(object_list), ())
            }, key=canonical))
            if not choices or any(
                canonical(field.value) == canonical(choice) for choice in choices
            ):
                continue
            nearest = bounded_nearest_choices(field.value, choices)
            selected = nearest[0] if len(nearest) == 1 else None
            bounded_tie = len(nearest) > 1
            if (
                selected is None
                and not bounded_tie
                and not actionable_diagnostic(field.value)
            ):
                continue
            schedule_bound = field_def.role == "schedule_reference" or any(
                "schedule" in canonical(value)
                and "scheduletypelimits" not in canonical(value).replace(" ", "")
                for value in field_def.object_lists
            )
            family = "reference_schedule" if schedule_bound else "object_reference"
            issues.append(_issue(
                family=family,
                obj=obj,
                field=field,
                field_name=field_def.name,
                faulty_value=field.value,
                recoverability="RECOVERABLE" if selected is not None else "AMBIGUOUS",
                evidence={
                    "bounded_candidate": selected[0] if selected else None,
                    "candidate_count": len(choices),
                    "edit_distance": selected[1] if selected else None,
                    "field_role": field_def.role,
                    "nearest_candidate_count": len(nearest),
                    "nearest_edit_distance": nearest[0][1] if nearest else None,
                    "object_lists": list(field_def.object_lists),
                    "opposed_role_exclusion_required": schedule_bound,
                },
            ))
    return issues


def _finite_key_issues(
    document: IDFDocument,
    idd: IDDSchema,
) -> list[SemanticIssue]:
    '''识别当前 IDD 有限 key 集中的非法字段值。'''
    issues = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field_def.keys or not field.value.strip():
                continue
            if any(canonical(field.value) == canonical(key) for key in field_def.keys):
                continue
            selected = bounded_unique_choice(field.value, field_def.keys)
            issues.append(_issue(
                family="finite_key",
                obj=obj,
                field=field,
                field_name=field_def.name,
                faulty_value=field.value,
                recoverability="RECOVERABLE" if selected is not None else "AMBIGUOUS",
                evidence={
                    "bounded_candidate": selected[0] if selected else None,
                    "candidate_count": len(field_def.keys),
                    "edit_distance": selected[1] if selected else None,
                    "finite_keys": list(field_def.keys),
                    "field_role": "finite_key",
                },
            ))
    return issues


def _field_count_issues(
    document: IDFDocument,
    idd: IDDSchema,
) -> list[SemanticIssue]:
    '''识别非 extensible 对象中 IDD 明确证明的尾字段溢出。'''
    issues = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        maximum = definition.maximum_fields if definition is not None else None
        if maximum is None or len(obj.fields) <= maximum:
            continue
        issues.append(_issue(
            family="extra_field",
            obj=obj,
            field=obj.fields[maximum],
            field_name="field beyond maximum IDD index",
            faulty_value=obj.fields[maximum].value,
            recoverability="RECOVERABLE",
            evidence={
                "bounded_candidate": None,
                "field_role": "field beyond maximum IDD index",
                "maximum_fields": maximum,
                "overflow_count": len(obj.fields) - maximum,
            },
        ))
    return issues


def _extensible_shape_issues(
    document: IDFDocument,
    idd: IDDSchema,
) -> list[SemanticIssue]:
    '''Flag incomplete current-IDD extensible groups without inventing a repair site.'''
    issues = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None or not definition.extensible:
            continue
        starts = [field.index for field in definition.fields if field.extensible]
        if starts:
            extensible_start = min(starts)
        elif len(definition.fields) >= definition.extensible:
            extensible_start = len(definition.fields) - definition.extensible + 1
        else:
            continue
        base_fields = extensible_start - 1
        if len(obj.fields) < base_fields:
            continue
        remainder = (len(obj.fields) - base_fields) % definition.extensible
        if remainder == 0:
            continue
        issues.append(_issue(
            family="extensible_shape",
            obj=obj,
            field=None,
            field_name="incomplete extensible group",
            faulty_value=f"field-count:{len(obj.fields)}",
            recoverability="AMBIGUOUS",
            evidence={
                "bounded_candidate": None,
                "extensible_group_size": definition.extensible,
                "extensible_start_field": extensible_start,
                "field_count": len(obj.fields),
                "field_role": "extensible_shape",
                "incomplete_group_remainder": remainder,
            },
        ))
    return issues


def _output_issues(
    document: IDFDocument,
    idd: IDDSchema,
    rdd: RDDCatalog,
) -> list[SemanticIssue]:
    '''识别所有无效 Output 名称，即使 EnergyPlus 只产生 warning。'''
    choices = rdd.variable_names
    if not choices:
        return []
    issues = []
    for obj in document.objects:
        if not canonical(obj.object_type).startswith("output:"):
            continue
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or field_def.role != "output_variable":
                continue
            if rdd.contains(field.value):
                continue
            selected = bounded_unique_choice(field.value, choices)
            issues.append(_issue(
                family="output_variable",
                obj=obj,
                field=field,
                field_name=field_def.name,
                faulty_value=field.value,
                recoverability="RECOVERABLE" if selected is not None else "AMBIGUOUS",
                evidence={
                    "bounded_candidate": selected[0] if selected else None,
                    "candidate_count": len(choices),
                    "edit_distance": selected[1] if selected else None,
                    "field_role": "output_variable",
                    "rdd_sha256": rdd.sha256,
                },
            ))
    return issues


def scan_semantic_issues(
    text: str,
    idd: IDDSchema,
    rdd: RDDCatalog,
    runtime_identity: Mapping[str, Any],
    *,
    target_version: str,
    diagnostics_text: str = "",
) -> SemanticPreflight:
    '''扫描所有现有对象字段并返回分域审计，绝不猜测连续数值。'''
    from idfrepair.capabilities.runtime import runtime_capability

    document = parse_idf(text)
    context = type("RuntimeContext", (), {
        "idd_sha256": idd.sha256,
        "rdd": rdd,
        "runtime_identity": runtime_identity,
        "version": target_version,
    })()
    capability = runtime_capability(context)
    issues = [
        *_field_count_issues(document, idd),
        *_extensible_shape_issues(document, idd),
        *_finite_key_issues(document, idd),
        *_reference_issues(document, idd, diagnostics_text),
        *_output_issues(document, idd, rdd),
    ]
    unique = {issue.issue_id: issue for issue in issues}
    ordered = tuple(sorted(unique.values(), key=lambda issue: (
        issue.object_identity["object_index"],
        issue.field_identity["field_index"] or 0,
        issue.family,
    )))
    families = {issue.family for issue in ordered}
    has_output_objects = any(
        canonical(obj.object_type).startswith("output:") for obj in document.objects
    )
    rdd_bound = bool(rdd.text.strip()) if has_output_objects else True
    audit = {
        "energyplus_runtime_bound": capability.passed,
        "geometry_audit_passed": "geometry" not in families,
        "idd_audit_passed": not families.intersection({
            "extensible_shape", "extra_field", "finite_key",
        }),
        "rdd_audit_passed": "output_variable" not in families and rdd_bound,
        "reference_audit_passed": not families.intersection({
            "object_reference", "reference_schedule",
        }),
        "runtime_capability": capability.to_dict(),
        "warning_audit_passed": "output_variable" not in families,
    }
    return SemanticPreflight(issues=ordered, audit=audit)


def semantic_roots(report: SemanticPreflight) -> tuple[DiagnosticRoot, ...]:
    '''把 SemanticIssue 转换为 SearchEngine 可处理的字段绑定根。'''
    roots = []
    for issue in report.issues:
        object_identity = issue.object_identity
        field_identity = issue.field_identity
        evidence = dict(issue.evidence)
        roots.append(DiagnosticRoot(
            root_id=issue.issue_id,
            family=issue.family,
            message=(
                f"Whole-file semantic preflight found {issue.family} at "
                f"object {object_identity.get('object_index')}, "
                f"field {field_identity.get('field_index')}."
            ),
            severity=issue.severity,
            object_type=str(object_identity.get("object_type") or "") or None,
            object_name=(
                str(object_identity["object_name"])
                if object_identity.get("object_name") else None
            ),
            field_name=(
                str(field_identity["field_name"])
                if field_identity.get("field_name") else None
            ),
            metadata={
                **evidence,
                "field_index": field_identity.get("field_index"),
                "object_index": object_identity.get("object_index"),
                "recoverability": issue.recoverability,
                "semantic_issue": True,
                "semantic_issue_id": issue.issue_id,
                "variable_name": (
                    None if issue.family != "output_variable"
                    else evidence.get("faulty_value")
                ),
            },
        ))
    return tuple(roots)


__all__ = [
    "bounded_nearest_choices",
    "SemanticIssue",
    "SemanticPreflight",
    "bounded_unique_choice",
    "scan_semantic_issues",
    "semantic_roots",
]
