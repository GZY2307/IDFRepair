"""Bilingual explanation catalog that never replaces raw EnergyPlus evidence."""

from __future__ import annotations

from typing import Any

from idfrepair.domain.models import DiagnosticRoot


_FAMILIES: dict[str, tuple[str, str, str, str, str, str]] = {
    "syntax": (
        "分隔符或对象终止错误", "IDF delimiter or object terminator error",
        "IDF 对象没有按当前语法完整分隔或终止。", "An IDF object is not fully delimited or terminated under the current syntax.",
        "检查定位行附近的逗号、分号以及前后对象边界。", "Inspect commas, semicolons, and adjacent object boundaries near the located line.",
    ),
    "extra_field": (
        "对象包含多余字段", "Object contains extra fields",
        "对象字段数超过当前 EnergyPlus IDD 对该对象的定义。", "The object has more fields than the bound EnergyPlus IDD allows.",
        "核对末尾字段，仅在 IDD 与对象身份唯一时删除确定的多余值。", "Check trailing fields and remove a value only when the IDD and object identity are unique.",
    ),
    "finite_key": (
        "枚举字段值无效", "Invalid enumerated field value",
        "字段值不属于当前 IDD 声明的有限选项。", "The field value is outside the finite choices declared by the current IDD.",
        "从当前 IDD 的有限选项中确认预期值。", "Confirm the intended value from the finite choices in the current IDD.",
    ),
    "extensible_shape": (
        "可扩展字段组结构不完整", "Malformed extensible field group",
        "对象的可扩展字段数量或分组形状不符合 IDD。", "The object's extensible field count or grouping does not match the IDD.",
        "核对完整字段组及其来源，避免凭空补值。", "Verify complete field groups and their provenance; do not invent missing values.",
    ),
    "version_migration": (
        "模型版本与运行时不一致", "Model and runtime versions differ",
        "IDF 的版本身份与当前运行时架构需要明确迁移。", "The IDF version identity requires an explicit migration to the current runtime schema.",
        "确认目标 EnergyPlus 版本，再执行受约束的版本迁移。", "Confirm the target EnergyPlus version before a bounded migration.",
    ),
    "reference_schedule": (
        "日程引用无法解析", "Schedule reference cannot be resolved",
        "字段引用的日程对象在当前文件中不存在或不唯一。", "A referenced schedule is missing or not unique in the current file.",
        "核对引用名称与兼容的日程对象类型。", "Check the reference name and compatible schedule object type.",
    ),
    "reference": (
        "对象引用无法解析", "Object reference cannot be resolved",
        "字段引用的对象在当前模型关系图中缺失或不唯一。", "A referenced object is missing or ambiguous in the current model graph.",
        "根据字段角色和对象类型确认唯一目标。", "Confirm a unique target using the field role and object type.",
    ),
    "object_reference": (
        "对象引用拼写或身份错误", "Object reference spelling or identity error",
        "对象引用未匹配到当前模型中的唯一兼容对象。", "The reference does not match one unique compatible object in the model.",
        "检查候选对象、拼写距离和类型约束。", "Review candidate objects, spelling distance, and type constraints.",
    ),
    "output_variable": (
        "输出变量名称无效", "Invalid output variable name",
        "请求的输出变量未与当前运行时生成的 RDD 唯一匹配。", "The requested output variable does not uniquely match the runtime-generated RDD.",
        "依据同一运行时的 RDD 确认变量名称。", "Confirm the variable name against the RDD from the same runtime.",
    ),
    "geometry": (
        "建筑几何关系异常", "Building geometry relationship error",
        "表面顶点、方向、闭合或配对关系存在冲突。", "Surface vertices, orientation, closure, or pairing relationships conflict.",
        "查看定位表面及其配对面；证据不足时保持只读。", "Inspect the located surface and its pair; remain read-only when evidence is insufficient.",
    ),
    "schema": (
        "对象或字段不符合 IDD", "Object or field violates the IDD",
        "对象类型、字段数量或字段定义与绑定的 IDD 不一致。", "The object type, field count, or field definition conflicts with the bound IDD.",
        "核对对象类型、字段位置和当前版本 IDD。", "Check the object type, field position, and current-version IDD.",
    ),
    "hvac_reference": (
        "HVAC 组件引用异常", "HVAC component reference error",
        "HVAC 节点或组件在类型关系图中缺失、冲突或不唯一。", "An HVAC node or component is missing, conflicting, or ambiguous in the typed graph.",
        "检查组件类型、节点连接和容器关系。", "Inspect component types, node connections, and container relationships.",
    ),
    "ems": (
        "EMS 符号或调用关系异常", "EMS symbol or call relationship error",
        "EMS 符号定义、调用或执行顺序无法唯一解析。", "An EMS symbol definition, call, or execution relationship is unresolved.",
        "检查定义、调用点和可见作用域。", "Inspect definitions, call sites, and visible scope.",
    ),
    "external_dependency": (
        "缺少外部依赖文件", "External dependency is missing",
        "模型引用的本地资源未随会话提供。", "A local resource referenced by the model was not provided to the session.",
        "上传报告指出的相对路径文件后重新验证。", "Upload the reported relative-path file and validate again.",
    ),
    "transition_semantics": (
        "修改后的错误状态未改善", "Post-change diagnostic state did not improve",
        "候选修改没有满足状态迁移安全约束。", "The candidate change did not satisfy the transition-safety contract.",
        "保留原文并查看首次失败的验证门禁。", "Keep the original text and inspect the first failed validation gate.",
    ),
}

_UNKNOWN = (
    "未分类诊断", "Unclassified diagnostic",
    "该消息尚未映射到确定的问题类型，原始 EnergyPlus 文本已保留。", "This message is not mapped to a known issue type; the raw EnergyPlus text is retained.",
    "查看原始英文诊断与对象证据，避免猜测性修改。", "Inspect the raw diagnostic and object evidence; avoid speculative edits.",
)

_SUPPORT_REASONS: dict[str, tuple[str, str]] = {
    "registry_entry_matches_root": ("当前模式允许该能力处理此问题", "The current mode allows this capability for the issue"),
    "registry_entry_not_enabled_for_current_mode": ("该能力未在当前模式中启用", "The capability is not enabled in the current mode"),
    "candidate_evidence_certificate_matched": ("候选证据满足发布注册表要求", "Candidate evidence satisfies the release registry"),
    "no_registry_entry_matches_root": ("没有注册表条目匹配该问题", "No registry entry matches the issue"),
    "root_not_reached_by_registry": ("该问题未进入已发布能力范围", "The issue did not reach a released capability"),
    "safe_auto_geometry_certificate_missing_assisted_preview_available": ("缺少安全自动几何证书；可在辅助模式预览", "Safe-auto geometry evidence is missing; an assisted preview is available"),
    "geometry_candidate_evidence_certificate_missing": ("几何候选缺少所需证据证书", "The geometry candidate lacks its required evidence certificate"),
}


def _localized(values: tuple[str, str, str, str, str, str]) -> dict[str, dict[str, str]]:
    return {
        "title": {"zh-CN": values[0], "en": values[1]},
        "summary": {"zh-CN": values[2], "en": values[3]},
        "action": {"zh-CN": values[4], "en": values[5]},
    }


def diagnostic_presentation(root: DiagnosticRoot) -> dict[str, Any]:
    family = root.family if root.family in _FAMILIES else "unknown"
    return {
        "message_id": f"diagnostic.{family}",
        **_localized(_FAMILIES.get(family, _UNKNOWN)),
        "raw_message": root.message,
    }


def support_reason_presentation(reason: str) -> dict[str, Any]:
    values = _SUPPORT_REASONS.get(reason)
    if values is None:
        return {
            "message_id": "support_reason.unknown",
            "text": {"zh-CN": "未分类的支持判断", "en": "Unclassified support decision"},
            "raw_token": reason,
        }
    return {
        "message_id": f"support_reason.{reason}",
        "text": {"zh-CN": values[0], "en": values[1]},
        "raw_token": reason,
    }


__all__ = ["diagnostic_presentation", "support_reason_presentation"]
