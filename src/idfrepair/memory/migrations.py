'''
定义 Repair Memory SQLite schema 和 FTS5 同步结构。

apply_migrations(): 在单个事务中建立全部规则、会话和案例表。
'''

from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 1


def apply_migrations(connection: sqlite3.Connection) -> None:
    '''建立七类业务表、版本表、FTS5 索引和默认规则集。'''
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rule_sets (
        rule_set_id TEXT PRIMARY KEY,
        name_zh TEXT NOT NULL,
        name_en TEXT NOT NULL,
        description_zh TEXT NOT NULL DEFAULT '',
        description_en TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS repair_rules (
        rule_id TEXT PRIMARY KEY,
        rule_set_id TEXT NOT NULL REFERENCES rule_sets(rule_set_id) ON DELETE CASCADE,
        name_zh TEXT NOT NULL,
        name_en TEXT NOT NULL,
        description_zh TEXT NOT NULL DEFAULT '',
        description_en TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL,
        priority INTEGER NOT NULL,
        scope TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        energyplus_version_min TEXT,
        energyplus_version_max TEXT,
        error_signature TEXT NOT NULL DEFAULT '',
        family TEXT NOT NULL DEFAULT '',
        object_type TEXT,
        field_name TEXT,
        field_index INTEGER,
        field_role TEXT,
        graph_fingerprint TEXT,
        conditions_json TEXT NOT NULL,
        candidate_template_json TEXT NOT NULL,
        finite_operations_json TEXT NOT NULL,
        requires_confirmation INTEGER NOT NULL,
        confidence REAL NOT NULL,
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        last_validation_status TEXT,
        tags_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rule_versions (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id TEXT NOT NULL REFERENCES repair_rules(rule_id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        change_reason TEXT NOT NULL,
        UNIQUE(rule_id, version_number)
    );
    CREATE TABLE IF NOT EXISTS rule_examples (
        example_id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL REFERENCES repair_rules(rule_id) ON DELETE CASCADE,
        input_fingerprint TEXT NOT NULL,
        before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,
        validation_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rule_applications (
        application_id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL REFERENCES repair_rules(rule_id) ON DELETE CASCADE,
        input_fingerprint TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        validation_result_json TEXT NOT NULL,
        energyplus_result_json TEXT,
        accepted INTEGER NOT NULL,
        rejected_reason TEXT,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS session_answers (
        answer_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        question_id TEXT NOT NULL,
        answer_json TEXT NOT NULL,
        saved_rule_id TEXT REFERENCES repair_rules(rule_id) ON DELETE SET NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS case_memories (
        memory_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        usage_status TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        features_json TEXT NOT NULL,
        outcome_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS repair_rules_fts USING fts5(
        rule_id UNINDEXED,
        name_zh,
        name_en,
        description_zh,
        description_en,
        error_signature,
        family,
        object_type,
        field_name,
        tags
    );
    CREATE INDEX IF NOT EXISTS idx_rules_enabled_family
        ON repair_rules(enabled, family, priority DESC);
    CREATE INDEX IF NOT EXISTS idx_rule_applications_rule
        ON rule_applications(rule_id, applied_at DESC);
    CREATE INDEX IF NOT EXISTS idx_session_answers_session
        ON session_answers(session_id, created_at);
    """)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
        (SCHEMA_VERSION,),
    )
    connection.execute("""
        INSERT OR IGNORE INTO rule_sets(
            rule_set_id, name_zh, name_en, description_zh, description_en,
            enabled, created_at, updated_at
        ) VALUES ('default', '默认规则集', 'Default rules', '', '', 1, datetime('now'), datetime('now'))
    """)


__all__ = ["SCHEMA_VERSION", "apply_migrations"]
