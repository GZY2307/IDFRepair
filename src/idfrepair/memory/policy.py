'''
定义 Repair Memory 的作用域匹配、版本边界和自动候选安全策略。

scope_matches(): 验证规则是否属于当前文件、模板、项目、批次或对象。
rule_confirmation(): 决定规则候选是否必须人工确认。
'''

from __future__ import annotations

import re

from idfrepair.io.idf import canonical
from idfrepair.memory.models import RepairRule, RuleMatchContext, RuleScope, RuleSource
from idfrepair.knowledge.idd_registry import version_key
from idfrepair.runtime.discovery import normalize_version


_QUOTED_VALUE = re.compile(r'(["\'])[^"\']+\1')
_IDENTITY_VALUE = re.compile(r"\b(object|type|name|key)\s*=\s*[^,;]+", re.I)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


def portable_error_signature(value: str) -> str:
    '''删除文件特有的对象名、路径和数字，生成可跨 IDF 比较的错误签名。'''
    text = _QUOTED_VALUE.sub("<value>", value)
    text = _IDENTITY_VALUE.sub(lambda match: f"{match.group(1).casefold()}=<value>", text)
    text = _NUMBER.sub("<number>", text)
    return canonical(text)


def _version_allowed(rule: RepairRule, version: str) -> bool:
    '''验证当前 EnergyPlus 版本位于规则声明的闭区间内。'''
    current = version_key(normalize_version(version))
    if not current:
        return not (rule.energyplus_version_min or rule.energyplus_version_max)
    if rule.energyplus_version_min and current < version_key(normalize_version(rule.energyplus_version_min)):
        return False
    if rule.energyplus_version_max and current > version_key(normalize_version(rule.energyplus_version_max)):
        return False
    return True


def scope_matches(rule: RepairRule, context: RuleMatchContext) -> bool:
    '''验证规则启用状态、版本、错误语义和作用域身份。'''
    if not rule.enabled or rule.source is RuleSource.MODEL_SUGGESTED:
        return False
    if not _version_allowed(rule, context.energyplus_version):
        return False
    if rule.family and canonical(rule.family) != canonical(context.family):
        return False
    if (
        rule.error_signature
        and canonical(rule.error_signature) != canonical(rule.family)
        and portable_error_signature(rule.error_signature)
        not in portable_error_signature(context.error_signature)
    ):
        return False
    if (
        rule.object_type and context.object_type
        and canonical(rule.object_type) != canonical(context.object_type)
    ):
        return False
    if (
        rule.field_name and context.field_name
        and canonical(rule.field_name) != canonical(context.field_name)
    ):
        return False
    if (
        rule.field_index is not None and context.field_index is not None
        and rule.field_index != context.field_index
    ):
        return False
    if (
        rule.field_role and context.field_role
        and canonical(rule.field_role) != canonical(context.field_role)
    ):
        return False
    if rule.graph_fingerprint and rule.graph_fingerprint != context.graph_fingerprint:
        return False
    conditions = rule.conditions
    if rule.scope is RuleScope.EXACT_FILE:
        return conditions.get("input_sha256") == context.input_sha256
    if rule.scope is RuleScope.EXACT_TEMPLATE:
        return bool(context.template_fingerprint) and conditions.get("template_fingerprint") == context.template_fingerprint
    if rule.scope is RuleScope.PROJECT:
        return bool(context.project_id) and conditions.get("project_id") == context.project_id
    if rule.scope is RuleScope.BATCH:
        return bool(context.batch_id) and conditions.get("batch_id") == context.batch_id
    if rule.scope is RuleScope.OBJECT_PATTERN:
        return bool(rule.object_type or rule.field_name or rule.field_role or rule.graph_fingerprint)
    return rule.scope is RuleScope.GLOBAL


def rule_confirmation(rule: RepairRule) -> bool:
    '''确定规则候选是否需要用户确认，导入和全局规则始终需要确认。'''
    if rule.requires_confirmation:
        return True
    if rule.scope is RuleScope.GLOBAL:
        return True
    return rule.source not in {RuleSource.BUILTIN, RuleSource.USER_CONFIRMED}


__all__ = ["portable_error_signature", "rule_confirmation", "scope_matches"]
