'''
提供 Repair Memory 规则集、规则、版本、案例和应用历史的事务仓储。

RuleRepository.create_rule(): 创建并版本化一条安全规则。
RuleRepository.list_rules(): 使用结构过滤和 FTS5 搜索规则。
RuleRepository.record_application(): 记录验证与 EnergyPlus 结果并更新统计。
'''

from __future__ import annotations

from dataclasses import replace
import json
import re
import sqlite3
from typing import Any, Iterable, Mapping
from uuid import uuid4

from idfrepair.domain.enums import OperationKind
from idfrepair.domain.models import to_primitive, utc_now
from idfrepair.memory.database import MemoryDatabase
from idfrepair.memory.models import RepairRule, RuleSource


_RULE_COLUMNS = (
    "rule_id", "rule_set_id", "name_zh", "name_en", "description_zh",
    "description_en", "enabled", "priority", "scope", "source", "created_at",
    "updated_at", "energyplus_version_min", "energyplus_version_max",
    "error_signature", "family", "object_type", "field_name", "field_index",
    "field_role", "graph_fingerprint", "conditions_json", "candidate_template_json",
    "finite_operations_json", "requires_confirmation", "confidence", "success_count",
    "failure_count", "last_validation_status", "tags_json",
)
_JSON_COLUMNS = {
    "conditions": "conditions_json",
    "candidate_template": "candidate_template_json",
    "finite_operations": "finite_operations_json",
    "tags": "tags_json",
}
_ALLOWED_RULE_OPERATIONS = frozenset({
    OperationKind.REPLACE_FIELD.value,
    OperationKind.INSERT_FIELD.value,
    OperationKind.DELETE_FIELD.value,
    OperationKind.RENAME_REFERENCE.value,
    OperationKind.REPLACE_VERTICES.value,
    OperationKind.UPDATE_VERSION.value,
})
_FORBIDDEN_KEYS = frozenset({"python", "shell", "command", "script", "executable"})


def _json(value: Any) -> str:
    '''以稳定键序写入 JSON，保证版本快照可比较。'''
    return json.dumps(to_primitive(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_payload(value: Any) -> None:
    '''递归拒绝规则中的执行型键名。'''
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                raise ValueError("rule_contains_executable_payload")
            _validate_payload(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_payload(item)


def validate_rule(rule: RepairRule) -> None:
    '''验证有限操作 allowlist、目标身份和执行型内容禁令。'''
    _validate_payload(rule.to_dict())
    for operation in rule.finite_operations:
        kind = str(operation.get("kind", operation.get("operation", "")))
        if kind not in _ALLOWED_RULE_OPERATIONS:
            raise ValueError(f"rule_operation_not_allowed:{kind}")
        if not operation.get("object_type") and operation.get("object_index") is None:
            raise ValueError("rule_operation_object_identity_required")
        if kind != OperationKind.REPLACE_VERTICES.value and operation.get("field_index") is None:
            raise ValueError("rule_operation_field_identity_required")


def _db_values(rule: RepairRule) -> tuple[Any, ...]:
    '''按固定列序把规则转换为 SQLite 值。'''
    row = rule.to_dict()
    values = []
    for column in _RULE_COLUMNS:
        if column == "scope":
            values.append(rule.scope.value)
        elif column == "source":
            values.append(rule.source.value)
        elif column in {"enabled", "requires_confirmation"}:
            values.append(int(bool(row[column])))
        elif column in _JSON_COLUMNS.values():
            source_key = next(key for key, target in _JSON_COLUMNS.items() if target == column)
            values.append(_json(row[source_key]))
        else:
            values.append(row[column])
    return tuple(values)


def _rule(row: sqlite3.Row) -> RepairRule:
    '''把 SQLite 行恢复为经过同一模型验证的规则。'''
    value = {key: row[key] for key in row.keys() if key not in _JSON_COLUMNS.values()}
    for key, column in _JSON_COLUMNS.items():
        value[key] = json.loads(row[column])
    value["enabled"] = bool(value["enabled"])
    value["requires_confirmation"] = bool(value["requires_confirmation"])
    return RepairRule.from_mapping(value)


class RuleRepository:
    '''以短事务管理规则及其审计历史，不允许失败时静默改写规则。'''

    def __init__(self, database: MemoryDatabase) -> None:
        self.database = database
        self.database.initialize()

    def create_rule_set(
        self,
        *,
        rule_set_id: str | None = None,
        name_zh: str,
        name_en: str,
        description_zh: str = "",
        description_en: str = "",
    ) -> str:
        '''创建一个独立规则集并返回身份。'''
        identity = rule_set_id or uuid4().hex
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO rule_sets(
                    rule_set_id, name_zh, name_en, description_zh, description_en,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """, (identity, name_zh, name_en, description_zh, description_en, now, now))
        return identity

    def list_rule_sets(self) -> tuple[dict[str, Any], ...]:
        '''按创建时间列出规则集和其中规则数量。'''
        with self.database.connect() as connection:
            rows = connection.execute("""
                SELECT s.*, COUNT(r.rule_id) AS rule_count
                FROM rule_sets s LEFT JOIN repair_rules r ON r.rule_set_id = s.rule_set_id
                GROUP BY s.rule_set_id ORDER BY s.created_at, s.rule_set_id
            """).fetchall()
        return tuple(dict(row) for row in rows)

    def _sync_fts(self, connection: sqlite3.Connection, rule: RepairRule) -> None:
        '''更新单条规则的 FTS5 文档。'''
        connection.execute("DELETE FROM repair_rules_fts WHERE rule_id = ?", (rule.rule_id,))
        connection.execute("""
            INSERT INTO repair_rules_fts(
                rule_id, name_zh, name_en, description_zh, description_en,
                error_signature, family, object_type, field_name, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rule.rule_id, rule.name_zh, rule.name_en, rule.description_zh,
            rule.description_en, rule.error_signature, rule.family,
            rule.object_type or "", rule.field_name or "", " ".join(rule.tags),
        ))

    def create_rule(self, value: RepairRule | Mapping[str, Any]) -> RepairRule:
        '''验证、写入并创建版本一快照。'''
        rule = value if isinstance(value, RepairRule) else RepairRule.from_mapping(value)
        validate_rule(rule)
        placeholders = ",".join("?" for _ in _RULE_COLUMNS)
        with self.database.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM rule_sets WHERE rule_set_id = ?", (rule.rule_set_id,),
            ).fetchone() is None:
                raise ValueError("rule_set_not_found")
            connection.execute(
                f"INSERT INTO repair_rules({','.join(_RULE_COLUMNS)}) VALUES ({placeholders})",
                _db_values(rule),
            )
            connection.execute("""
                INSERT INTO rule_versions(
                    rule_id, version_number, snapshot_json, changed_at, change_reason
                ) VALUES (?, 1, ?, ?, 'created')
            """, (rule.rule_id, _json(rule.to_dict()), rule.created_at))
            self._sync_fts(connection, rule)
        return rule

    def get_rule(self, rule_id: str) -> RepairRule:
        '''按精确身份读取规则，不回退到名称搜索。'''
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repair_rules WHERE rule_id = ?", (rule_id,),
            ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return _rule(row)

    def list_rules(
        self,
        *,
        search: str | None = None,
        rule_set_id: str | None = None,
        enabled: bool | None = None,
        family: str | None = None,
    ) -> tuple[RepairRule, ...]:
        '''使用 FTS5 和结构条件列出规则。'''
        clauses = []
        params: list[Any] = []
        join = ""
        if search:
            terms = re.findall(r"[\w:+.-]+", search, re.UNICODE)
            if not terms:
                return ()
            join = " JOIN repair_rules_fts f ON f.rule_id = r.rule_id"
            clauses.append("f.repair_rules_fts MATCH ?")
            params.append(" AND ".join(f'"{term}"' for term in terms))
        if rule_set_id:
            clauses.append("r.rule_set_id = ?")
            params.append(rule_set_id)
        if enabled is not None:
            clauses.append("r.enabled = ?")
            params.append(int(enabled))
        if family:
            clauses.append("r.family = ?")
            params.append(family)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = f"SELECT r.* FROM repair_rules r{join}{where} ORDER BY r.priority DESC, r.updated_at DESC, r.rule_id"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_rule(row) for row in rows)

    def update_rule(
        self, rule_id: str, updates: Mapping[str, Any], *, reason: str = "updated",
    ) -> RepairRule:
        '''创建新版本快照并原子替换允许修改的规则字段。'''
        current = self.get_rule(rule_id)
        forbidden = {"rule_id", "created_at", "success_count", "failure_count", "last_validation_status"}
        if forbidden.intersection(updates):
            raise ValueError("immutable_rule_field")
        value = {**current.to_dict(), **dict(updates), "updated_at": utc_now()}
        value["rule_id"] = rule_id
        updated = RepairRule.from_mapping(value)
        validate_rule(updated)
        assignments = ",".join(f"{column} = ?" for column in _RULE_COLUMNS if column != "rule_id")
        values = _db_values(updated)
        with self.database.transaction() as connection:
            connection.execute(
                f"UPDATE repair_rules SET {assignments} WHERE rule_id = ?",
                (*values[1:], rule_id),
            )
            number = connection.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM rule_versions WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()[0]
            connection.execute("""
                INSERT INTO rule_versions(
                    rule_id, version_number, snapshot_json, changed_at, change_reason
                ) VALUES (?, ?, ?, ?, ?)
            """, (rule_id, number, _json(updated.to_dict()), updated.updated_at, reason))
            self._sync_fts(connection, updated)
        return updated

    def set_enabled(self, rule_id: str, enabled: bool) -> RepairRule:
        '''启用或禁用规则；模型建议规则不能直接启用。'''
        current = self.get_rule(rule_id)
        if enabled and current.source is RuleSource.MODEL_SUGGESTED:
            raise ValueError("model_suggested_rule_requires_user_clone")
        return self.update_rule(rule_id, {"enabled": bool(enabled)}, reason="enabled" if enabled else "disabled")

    def delete_rule(self, rule_id: str) -> None:
        '''删除一条规则及其级联版本和应用历史。'''
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM repair_rules_fts WHERE rule_id = ?", (rule_id,))
            cursor = connection.execute("DELETE FROM repair_rules WHERE rule_id = ?", (rule_id,))
            if cursor.rowcount != 1:
                raise KeyError(rule_id)

    def clone_rule(self, rule_id: str, *, rule_set_id: str | None = None) -> RepairRule:
        '''复制规则为默认禁用的 USER_CREATED 新身份。'''
        source = self.get_rule(rule_id)
        value = source.to_dict()
        value.update({
            "rule_id": uuid4().hex,
            "rule_set_id": rule_set_id or source.rule_set_id,
            "name_zh": source.name_zh + "（副本）",
            "name_en": source.name_en + " Copy",
            "source": RuleSource.USER_CREATED.value,
            "enabled": False,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "success_count": 0,
            "failure_count": 0,
            "last_validation_status": None,
        })
        return self.create_rule(value)

    def rule_versions(self, rule_id: str) -> tuple[dict[str, Any], ...]:
        '''按版本号返回规则不可变快照。'''
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rule_versions WHERE rule_id = ? ORDER BY version_number",
                (rule_id,),
            ).fetchall()
        return tuple({**dict(row), "snapshot": json.loads(row["snapshot_json"])} for row in rows)

    def add_example(
        self,
        *,
        rule_id: str,
        input_fingerprint: str,
        before: Any,
        after: Any,
        validation: Any,
    ) -> str:
        '''保存一条不含原始文件正文的规则验证示例。'''
        identity = uuid4().hex
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO rule_examples(
                    example_id, rule_id, input_fingerprint, before_json,
                    after_json, validation_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                identity, rule_id, input_fingerprint, _json(before),
                _json(after), _json(validation), utc_now(),
            ))
        return identity

    def save_session_answer(
        self,
        *,
        session_id: str,
        question_id: str,
        answer: Any,
        saved_rule_id: str | None = None,
    ) -> str:
        '''保存用户回答与可选规则身份，供重启恢复和学习审计。'''
        identity = uuid4().hex
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO session_answers(
                    answer_id, session_id, question_id, answer_json,
                    saved_rule_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                identity, session_id, question_id, _json(answer), saved_rule_id, utc_now(),
            ))
        return identity

    def add_case_memory(
        self,
        *,
        case_id: str,
        usage_status: str,
        fingerprint: str,
        features: Any,
        outcome: Any,
    ) -> str:
        '''保存案例特征和结果摘要，不存储 fixed 或 gold 原文。'''
        if usage_status not in {"development-exposed", "evaluation-replay", "held-out", "demo-only"}:
            raise ValueError("invalid_case_memory_usage_status")
        identity = uuid4().hex
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO case_memories(
                    memory_id, case_id, usage_status, fingerprint,
                    features_json, outcome_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                identity, case_id, usage_status, fingerprint,
                _json(features), _json(outcome), utc_now(),
            ))
        return identity

    def record_application(
        self,
        *,
        rule_id: str,
        input_fingerprint: str,
        candidate_id: str,
        validation_result: Any,
        energyplus_result: Any,
        accepted: bool,
        rejected_reason: str | None,
    ) -> str:
        '''记录一次规则应用，并只更新成功/失败统计和最后验证状态。'''
        identity = uuid4().hex
        status = "ACCEPTED" if accepted else "REJECTED"
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO rule_applications(
                    application_id, rule_id, input_fingerprint, candidate_id,
                    validation_result_json, energyplus_result_json, accepted,
                    rejected_reason, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                identity, rule_id, input_fingerprint, candidate_id,
                _json(validation_result),
                None if energyplus_result is None else _json(energyplus_result),
                int(accepted), rejected_reason, utc_now(),
            ))
            column = "success_count" if accepted else "failure_count"
            connection.execute(
                f"UPDATE repair_rules SET {column} = {column} + 1, last_validation_status = ?, updated_at = ? WHERE rule_id = ?",
                (status, utc_now(), rule_id),
            )
        return identity

    def list_applications(self, rule_id: str | None = None) -> tuple[dict[str, Any], ...]:
        '''按时间倒序返回规则应用历史及结构化验证结果。'''
        query = "SELECT * FROM rule_applications"
        params: tuple[Any, ...] = ()
        if rule_id:
            query += " WHERE rule_id = ?"
            params = (rule_id,)
        query += " ORDER BY applied_at DESC, application_id"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple({
            **dict(row),
            "validation_result": json.loads(row["validation_result_json"]),
            "energyplus_result": (
                json.loads(row["energyplus_result_json"]) if row["energyplus_result_json"] else None
            ),
            "accepted": bool(row["accepted"]),
        } for row in rows)


__all__ = ["RuleRepository", "validate_rule"]
