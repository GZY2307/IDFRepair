'''
定义 API 与网页共享的本地化消息协议。

message(): 把稳定消息身份、插值参数和原始值封装为统一对象。
status_message(): 把修复状态转换为前端可本地化的消息身份。
error_message(): 把异常转换为不丢失原始诊断的错误消息。
'''

from __future__ import annotations

from typing import Any, Mapping


Message = dict[str, Any]
_WORKSPACE_ERROR_TOKENS = frozenset({
    "session_workspace_missing",
    "session_workspace_not_directory",
    "session_workspace_unreadable",
})
_STABLE_ERROR_TOKENS = frozenset({
    "session_storage_row_invalid",
    "weather_asset_state_invalid",
    "weather_attachment_conflict",
    "weather_blob_integrity_error",
    "weather_commit_state_unknown",
    "weather_storage_write_failed",
})


def message(message_id: str, raw_message: str, params: Mapping[str, Any] | None = None) -> Message:
    '''返回稳定三字段消息对象，前端只翻译 message_id。'''
    return {
        "message_id": message_id,
        "params": dict(params or {}),
        "raw_message": raw_message,
    }


def status_message(status: str | None, lifecycle_status: str) -> Message:
    '''优先表达修复状态；未运行时使用会话生命周期。'''
    raw = status or lifecycle_status
    namespace = "repair.status" if status else "session.lifecycle"
    return message(f"{namespace}.{raw.casefold()}", raw)


def error_message(exc: Exception) -> Message:
    '''保留内部错误 token，并提供可按异常类型翻译的稳定身份。'''
    raw = str(exc) or type(exc).__name__
    if raw.startswith("run_readiness_blocked:"):
        check_ids = [
            value for value in raw.partition(":")[2].split(",") if value
        ]
        return message(
            "error.run_readiness_blocked",
            raw,
            {"error_type": type(exc).__name__, "check_ids": check_ids},
        )
    if raw in _WORKSPACE_ERROR_TOKENS:
        return message(
            f"error.{raw}",
            raw,
            {"error_type": "OSError"},
        )
    if raw in _STABLE_ERROR_TOKENS:
        return message(
            f"error.{raw}",
            raw,
            {"error_type": type(exc).__name__},
        )
    return message(
        f"error.{type(exc).__name__.casefold()}",
        raw,
        {"error_type": type(exc).__name__},
    )


__all__ = ["Message", "error_message", "message", "status_message"]
