'''
依据源、目标 IDD 的字段语义生成 fail-closed 多对象迁移计划。

diff_idd(): 比较对象和字段的新增、删除与重排。
plan_migration(): 将当前 IDF 编译为可回滚的对象级迁移计划。
'''

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, text_sha256
from idfrepair.knowledge.idd import IDDField, IDDObject, IDDSchema


def _field_key(field: IDDField) -> str:
    '''生成对象内部字段的规范语义身份。'''
    return canonical(field.name or field.token)


def _field_map(definition: IDDObject) -> tuple[dict[str, IDDField], set[str]]:
    '''建立唯一字段名映射，并单独返回重复身份。'''
    counts = Counter(_field_key(field) for field in definition.fields)
    ambiguous = {key for key, count in counts.items() if key and count > 1}
    return {
        _field_key(field): field for field in definition.fields
        if _field_key(field) and _field_key(field) not in ambiguous
    }, ambiguous


def _metadata(field: IDDField) -> tuple[Any, ...]:
    '''提取影响迁移安全性的字段约束。'''
    return (
        canonical(field.data_type or ""),
        canonical(field.units or ""),
        tuple(sorted(canonical(value) for value in field.object_lists)),
        tuple(sorted(canonical(value) for value in field.references)),
        bool(field.required),
        field.default,
        bool(field.extensible),
    )


def diff_idd(source: IDDSchema, target: IDDSchema) -> dict[str, Any]:
    '''
    比较两个已解析 IDD，记录对象和字段的新增、删除、重排及约束变化。

    :param source: 源 EnergyPlus 版本的 IDD schema。
    :param target: 目标 EnergyPlus 版本的 IDD schema。
    :return: 绑定两侧摘要的机器可读差分。
    '''
    source_keys = set(source.objects)
    target_keys = set(target.objects)
    object_diffs = []
    ambiguous = []
    for key in sorted(source_keys & target_keys):
        left = source.objects[key]
        right = target.objects[key]
        left_map, left_ambiguous = _field_map(left)
        right_map, right_ambiguous = _field_map(right)
        if left_ambiguous or right_ambiguous:
            ambiguous.append({
                "object_type": left.name,
                "source_duplicate_fields": tuple(sorted(left_ambiguous)),
                "target_duplicate_fields": tuple(sorted(right_ambiguous)),
            })
        shared = sorted(set(left_map) & set(right_map))
        added = [right_map[name] for name in sorted(set(right_map) - set(left_map))]
        deleted = [left_map[name] for name in sorted(set(left_map) - set(right_map))]
        reordered = [{
            "field_name": right_map[name].name,
            "source_index": left_map[name].index,
            "target_index": right_map[name].index,
        } for name in shared if left_map[name].index != right_map[name].index]
        metadata = [{
            "field_name": right_map[name].name,
            "source_index": left_map[name].index,
            "target_index": right_map[name].index,
        } for name in shared if _metadata(left_map[name]) != _metadata(right_map[name])]
        if added or deleted or reordered or metadata:
            object_diffs.append({
                "object_type": left.name,
                "added_fields": tuple({
                    "index": field.index,
                    "name": field.name,
                    "required": field.required,
                    "default": field.default,
                } for field in added),
                "deleted_fields": tuple({"index": field.index, "name": field.name} for field in deleted),
                "reordered_fields": tuple(reordered),
                "metadata_changes": tuple(metadata),
            })
    return {
        "schema_version": "idfrepair.idd.diff.v1",
        "status": "REQUEST_USER_INPUT" if ambiguous else "OK",
        "source_version": source.version,
        "target_version": target.version,
        "source_idd_sha256": source.sha256,
        "target_idd_sha256": target.sha256,
        "added_objects": tuple(target.objects[key].name for key in sorted(target_keys - source_keys)),
        "deleted_objects": tuple(source.objects[key].name for key in sorted(source_keys - target_keys)),
        "object_diffs": tuple(object_diffs),
        "ambiguous_alignments": tuple(ambiguous),
    }


def _renames(
    object_type: str, value: Mapping[str, Any] | None,
) -> dict[str, str]:
    '''读取显式字段重命名映射，不从名称相似度推导。'''
    if not isinstance(value, Mapping):
        return {}
    row = value.get(object_type, value.get(canonical(object_type), {}))
    if not isinstance(row, Mapping):
        return {}
    return {canonical(str(before)): canonical(str(after)) for before, after in row.items()}


def _render_object(obj: IDFObject, object_type: str, values: list[str]) -> str:
    '''将迁移后的字段顺序写成稳定对象文本，并保留对象前导空白。'''
    raw = obj.raw
    position = raw.find(obj.object_type)
    prefix = raw[:position] if position >= 0 else ""
    if not values:
        return f"{prefix}{object_type};"
    lines = [f"{prefix}{object_type},"]
    for index, value in enumerate(values):
        delimiter = ";" if index == len(values) - 1 else ","
        lines.append(f"  {value}{delimiter}")
    return "\n".join(lines)


def _align_object(
    obj: IDFObject,
    source_def: IDDObject,
    target_def: IDDObject,
    field_renames: Mapping[str, Any] | None,
) -> dict[str, Any]:
    '''
    对齐一个对象实例；删除非空字段或新增无默认必需字段时立即拒绝。

    extensible 对象只有在两侧循环组起点、宽度和字段身份一致时才保留额外组。
    '''
    source_map, source_ambiguous = _field_map(source_def)
    target_map, target_ambiguous = _field_map(target_def)
    if source_ambiguous or target_ambiguous:
        return {"status": "REQUEST_USER_INPUT", "reason": "ambiguous_field_identity"}
    renames = _renames(source_def.name, field_renames)
    mapped_source: dict[str, IDDField] = {}
    for key, field in source_map.items():
        target_key = renames.get(key, key)
        if target_key in mapped_source:
            return {"status": "REQUEST_USER_INPUT", "reason": "field_rename_collision"}
        mapped_source[target_key] = field
    if len(obj.fields) > len(source_def.fields):
        source_start = len(source_def.fields) - (source_def.extensible or 0) + 1
        target_start = len(target_def.fields) - (target_def.extensible or 0) + 1
        source_group = tuple(_field_key(field) for field in source_def.fields[source_start - 1:])
        target_group = tuple(_field_key(field) for field in target_def.fields[target_start - 1:])
        if not source_def.extensible or source_group != target_group or source_start != target_start:
            return {"status": "REQUEST_USER_INPUT", "reason": "extensible_alignment_not_exact"}
    values: list[str] = []
    used_source: set[int] = set()
    blockers: list[str] = []
    for target_field in target_def.fields:
        key = _field_key(target_field)
        source_field = mapped_source.get(key)
        if source_field is not None:
            used_source.add(source_field.index)
            value = obj.fields[source_field.index - 1].value if source_field.index <= len(obj.fields) else ""
            if not value and target_field.required:
                if target_field.default is None:
                    blockers.append(f"required_field_without_value:{target_field.name}")
                else:
                    value = target_field.default
            values.append(value)
        elif target_field.required:
            if target_field.default is None:
                blockers.append(f"required_added_field_without_default:{target_field.name}")
                values.append("")
            else:
                values.append(target_field.default)
        else:
            values.append(target_field.default or "")
    for source_field in source_def.fields:
        if source_field.index in used_source or source_field.index > len(obj.fields):
            continue
        if obj.fields[source_field.index - 1].value.strip():
            blockers.append(f"nonempty_deleted_field:{source_field.name}")
    if blockers:
        return {"status": "REQUEST_USER_INPUT", "reason": "unsafe_field_migration", "blockers": tuple(blockers)}
    last_nonempty = max((index for index, value in enumerate(values, start=1) if value), default=0)
    output_count = max(target_def.minimum_fields, last_nonempty)
    values = values[:output_count]
    object_text = _render_object(obj, target_def.name, values)
    current_values = tuple(field.value for field in obj.fields)
    return {
        "status": "OK",
        "object_text": object_text,
        "values": tuple(values),
        "changed": (
            canonical(obj.object_type) != canonical(target_def.name)
            or current_values != tuple(values)
        ),
        "source_field_count": len(obj.fields),
        "target_field_count": len(values),
    }


def plan_migration(
    document: IDFDocument,
    source: IDDSchema,
    target: IDDSchema,
    target_version: str,
    *,
    field_renames: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    '''
    为当前 IDF 的全部对象生成无冲突迁移计划，Version 对象单独更新。

    :param document: 当前源版本 IDF 文档。
    :param source: 源版本 IDD schema。
    :param target: 目标版本 IDD schema。
    :param target_version: 运行时要求的目标 EnergyPlus 版本。
    :param field_renames: 可选的权威字段重命名表。
    :return: 对象替换、版本更新、阻塞原因和两侧摘要。
    '''
    diff = diff_idd(source, target)
    blockers: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    version_objects = document.find_objects("Version")
    if len(version_objects) != 1:
        blockers.append({"reason": "version_object_missing_or_ambiguous"})
    for obj in document.objects:
        if canonical(obj.object_type) == "version":
            continue
        source_def = source.get(obj.object_type)
        target_def = target.get(obj.object_type)
        if source_def is None or target_def is None:
            blockers.append({
                "object_index": obj.index,
                "object_type": obj.object_type,
                "reason": "object_type_not_shared_by_both_idds",
            })
            continue
        aligned = _align_object(obj, source_def, target_def, field_renames)
        if aligned["status"] != "OK":
            blockers.append({
                "object_index": obj.index,
                "object_type": obj.object_type,
                **aligned,
            })
        elif aligned["changed"]:
            replacements.append({
                "object_index": obj.index,
                "object_type": obj.object_type,
                "object_name": obj.name,
                "old_text": obj.raw,
                "object_text": aligned["object_text"],
                "source_field_count": aligned["source_field_count"],
                "target_field_count": aligned["target_field_count"],
            })
    status = "OK" if not blockers and diff["status"] == "OK" else "REQUEST_USER_INPUT"
    return {
        "schema_version": "idfrepair.migration.plan.v1",
        "status": status,
        "source_version": document.version,
        "target_version": target_version,
        "source_idd_sha256": source.sha256,
        "target_idd_sha256": target.sha256,
        "input_sha256": document.sha256,
        "replacements": tuple(replacements),
        "update_version": bool(
            len(version_objects) == 1 and document.version != target_version
        ),
        "blockers": tuple(blockers),
        "diff": diff,
        "plan_sha256": text_sha256(repr((replacements, target_version, source.sha256, target.sha256))),
    }


__all__ = ["diff_idd", "plan_migration"]
