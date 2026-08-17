'''
以 JSON 或 YAML 兼容文本导入导出规则集，不执行输入中的任何代码。

export_rules(): 写出稳定规则文档。
import_rules(): 验证来源、作用域和有限操作后创建规则。
'''

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from idfrepair.memory.models import RuleSource
from idfrepair.memory.repository import RuleRepository


def _load(path: Path) -> Any:
    '''优先读取 JSON；YAML 依赖可用时才解析非 JSON YAML。'''
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("yaml_runtime_not_installed; JSON is valid YAML 1.2") from exc
        return yaml.safe_load(text)


def export_rules(repository: RuleRepository, path: Path, *, rule_set_id: str | None = None) -> Path:
    '''以确定性 JSON 写出规则集；该文本同时是合法 YAML 1.2。'''
    rules = repository.list_rules(rule_set_id=rule_set_id)
    payload = {
        "schema_version": "idfrepair.repair_memory.export.v1",
        "format": "json-yaml-1.2",
        "rule_sets": repository.list_rule_sets(),
        "rules": [rule.to_dict() for rule in rules],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def import_rules(repository: RuleRepository, path: Path, *, rule_set_id: str | None = None) -> tuple[str, ...]:
    '''导入规则并强制标记为 IMPORTED 和默认禁用。'''
    payload = _load(path)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "idfrepair.repair_memory.export.v1":
        raise ValueError("unsupported_rule_export_schema")
    rows = payload.get("rules")
    if not isinstance(rows, list):
        raise ValueError("rules_must_be_array")
    created = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("rule_import_item_must_be_object")
        value = dict(raw)
        value.pop("rule_id", None)
        value.update({
            "rule_set_id": rule_set_id or value.get("rule_set_id", "default"),
            "source": RuleSource.IMPORTED.value,
            "enabled": False,
            "success_count": 0,
            "failure_count": 0,
            "last_validation_status": None,
        })
        created.append(repository.create_rule(value).rule_id)
    return tuple(created)


__all__ = ["export_rules", "import_rules"]
