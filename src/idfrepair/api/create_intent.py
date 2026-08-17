from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Mapping

from idfrepair.domain.errors import SessionStateError

CREATE_INTENT_LEAF = "session-create-intent.json"
CREATE_INTENT_SCHEMA = "idfrepair.session-create-intent.v1"
CREATE_RECOVERY_PREFIX = ".create-recovery-"
MAX_CREATE_INTENT_BYTES, MAX_CREATE_INTENT_SCAN = 4096, 4096
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RECOVERY_LEAF = re.compile(
    rf"{re.escape(CREATE_RECOVERY_PREFIX)}([0-9a-f]{{32}})-[0-9a-f]{{32}}\Z"
)


def create_recovery_leaf(session_id: str) -> str:
    """Return an exact, unguessable leaf that retains its session identity."""

    if type(session_id) is not str or _SESSION_ID.fullmatch(session_id) is None:
        raise SessionStateError("session_create_intent_invalid")
    return f"{CREATE_RECOVERY_PREFIX}{session_id}-{secrets.token_hex(16)}"


def recovery_session_id(leaf: str) -> str | None:
    """Parse only canonical create-recovery leaves."""

    match = _RECOVERY_LEAF.fullmatch(leaf) if type(leaf) is str else None
    return match.group(1) if match is not None else None

@dataclass(frozen=True, slots=True)
class SessionCreateIntent:
    session_id: str
    input_name: str
    input_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": CREATE_INTENT_SCHEMA,
            "session_id": self.session_id, "input_name": self.input_name,
            "input_sha256": self.input_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SessionCreateIntent":
        keys = {"schema_version", "session_id", "input_name", "input_sha256"}
        if set(value) != keys:
            raise SessionStateError("session_create_intent_invalid")
        result = cls(value["session_id"], value["input_name"], value["input_sha256"])
        try:
            input_name_bytes = (
                result.input_name.encode("utf-8")
                if type(result.input_name) is str else b""
            )
        except UnicodeEncodeError as exc:
            raise SessionStateError("session_create_intent_invalid") from exc
        if (
            value.get("schema_version") != CREATE_INTENT_SCHEMA
            or type(result.session_id) is not str
            or _SESSION_ID.fullmatch(result.session_id) is None
            or type(result.input_name) is not str
            or not result.input_name
            or not 0 < len(input_name_bytes) <= 1024
            or type(result.input_sha256) is not str
            or _SHA256.fullmatch(result.input_sha256) is None
        ):
            raise SessionStateError("session_create_intent_invalid")
        return result

def _directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    return flags | (os.O_CLOEXEC if hasattr(os, "O_CLOEXEC") else 0)

def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("session_create_intent_short_write")
        remaining = remaining[written:]

def publish_create_intent(workspace_root: Path, intent: SessionCreateIntent) -> None:
    intent = SessionCreateIntent.from_mapping(intent.to_dict())
    content = (json.dumps(intent.to_dict(), sort_keys=True) + "\n").encode()
    if len(content) > MAX_CREATE_INTENT_BYTES:
        raise SessionStateError("session_create_intent_invalid")
    directory = -1
    temporary: str | None = None
    linked = False
    try:
        directory = os.open(workspace_root, _directory_flags())
        try:
            os.stat(CREATE_INTENT_LEAF, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SessionStateError("session_create_intent_leaf_exists")
        temporary = f".create-intent-{secrets.token_hex(16)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
        try:
            _write_all(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, CREATE_INTENT_LEAF, src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False)
        linked = True
        os.unlink(temporary, dir_fd=directory)
        temporary = None
        os.fsync(directory)
    except SessionStateError:
        raise
    except OSError as exc:
        if linked:
            try:
                os.unlink(CREATE_INTENT_LEAF, dir_fd=directory)
                os.fsync(directory)
            except OSError:
                pass
        raise SessionStateError("session_create_intent_storage_invalid") from exc
    finally:
        if directory >= 0:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
            os.close(directory)

def read_create_intent(
    workspace_root: Path, *, expected_session_id: str,
) -> SessionCreateIntent:
    directory = -1
    try:
        try:
            directory = os.open(workspace_root, _directory_flags())
        except OSError as exc:
            raise SessionStateError("session_create_intent_storage_invalid") from exc
        return read_create_intent_at(
            directory, expected_session_id=expected_session_id,
        )
    finally:
        if directory >= 0:
            os.close(directory)

def read_create_intent_at(
    directory: int, *, expected_session_id: str,
) -> SessionCreateIntent:
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(CREATE_INTENT_LEAF, flags, dir_fd=directory)
        node = os.fstat(descriptor)
        if not stat.S_ISREG(node.st_mode) or not 0 < node.st_size <= MAX_CREATE_INTENT_BYTES:
            raise SessionStateError("session_create_intent_invalid")
        content = os.read(descriptor, node.st_size + 1)
        value = json.loads(content.decode("utf-8"))
        if len(content) != node.st_size or type(value) is not dict:
            raise SessionStateError("session_create_intent_invalid")
        intent = SessionCreateIntent.from_mapping(value)
        if intent.session_id != expected_session_id:
            raise SessionStateError("session_create_intent_invalid")
        return intent
    except FileNotFoundError:
        raise
    except SessionStateError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise SessionStateError("session_create_intent_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

def remove_create_intent(workspace_root: Path) -> None:
    directory = -1
    try:
        try:
            directory = os.open(workspace_root, _directory_flags())
        except OSError as exc:
            raise SessionStateError("session_create_intent_storage_invalid") from exc
        remove_create_intent_at(directory)
    finally:
        if directory >= 0:
            os.close(directory)

def remove_create_intent_at(directory: int) -> None:
    try:
        node = os.stat(CREATE_INTENT_LEAF, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(node.st_mode):
            raise SessionStateError("session_create_intent_invalid")
        os.unlink(CREATE_INTENT_LEAF, dir_fd=directory)
        os.fsync(directory)
    except FileNotFoundError:
        return
    except SessionStateError:
        raise
    except OSError as exc:
        raise SessionStateError("session_create_intent_storage_invalid") from exc
