"""No-follow, bounded, atomic storage for OSM workflow artifacts."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import stat
from collections.abc import Iterator, Mapping
from typing import Any

from idfrepair.domain.errors import SessionStateError


_OSM_ARTIFACT_LIMIT_BYTES = 100 * 1024 * 1024
_OSM_FAILURE_REASON = re.compile(
    r"^[A-Za-z0-9_]+(?::[A-Za-z0-9_]+){0,3}$"
)


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


@contextmanager
def _open_artifacts_directory(
    workspace_root: Path,
    *,
    create: bool,
) -> Iterator[int]:
    """Hold the trusted workspace/artifacts chain without following links."""

    root_descriptor = -1
    artifacts_descriptor = -1
    try:
        try:
            root_descriptor = os.open(workspace_root, _directory_open_flags())
            if create:
                try:
                    os.mkdir("artifacts", 0o700, dir_fd=root_descriptor)
                except FileExistsError:
                    pass
            artifacts_descriptor = os.open(
                "artifacts", _directory_open_flags(), dir_fd=root_descriptor,
            )
        except OSError as exc:
            raise SessionStateError("osm_artifact_storage_invalid") from exc
        yield artifacts_descriptor
    finally:
        if artifacts_descriptor >= 0:
            os.close(artifacts_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)


def _write_descriptor(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("artifact_short_write")
        remaining = remaining[written:]


def publish_osm_artifacts(
    workspace_root: Path,
    artifacts: Mapping[str, bytes],
    *,
    commit_marker: str,
) -> None:
    """Publish regular leaves atomically, making the report visible last."""

    if commit_marker not in artifacts or any(
        not leaf
        or leaf in {".", ".."}
        or "/" in leaf
        or "\\" in leaf
        or len(content) > _OSM_ARTIFACT_LIMIT_BYTES
        for leaf, content in artifacts.items()
    ):
        raise SessionStateError("osm_artifact_payload_invalid")
    with _open_artifacts_directory(workspace_root, create=True) as directory:
        for leaf in artifacts:
            try:
                os.stat(leaf, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SessionStateError("osm_artifact_storage_invalid") from exc
            raise SessionStateError("osm_artifact_leaf_exists")
        staged: dict[str, str] = {}
        published: list[str] = []
        try:
            for leaf, content in artifacts.items():
                temporary = f".osm-{secrets.token_hex(16)}.tmp"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
                try:
                    _write_descriptor(descriptor, content)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                staged[leaf] = temporary
            for leaf in (*sorted(set(staged) - {commit_marker}), commit_marker):
                temporary = staged[leaf]
                os.link(
                    temporary,
                    leaf,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                published.append(leaf)
                os.unlink(temporary, dir_fd=directory)
                staged.pop(leaf)
            os.fsync(directory)
        except OSError as exc:
            for leaf in reversed(published):
                try:
                    os.unlink(leaf, dir_fd=directory)
                except FileNotFoundError:
                    pass
            os.fsync(directory)
            raise SessionStateError("osm_artifact_storage_invalid") from exc
        finally:
            for temporary in staged.values():
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass


def read_osm_artifact(workspace_root: Path, leaf: str) -> bytes:
    """Read one bounded no-follow regular artifact leaf."""

    with _open_artifacts_directory(workspace_root, create=False) as directory:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            descriptor = os.open(leaf, flags, dir_fd=directory)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SessionStateError("osm_artifact_storage_invalid") from exc
        try:
            node = os.fstat(descriptor)
            if (
                not stat.S_ISREG(node.st_mode)
                or node.st_size < 0
                or node.st_size > _OSM_ARTIFACT_LIMIT_BYTES
            ):
                raise SessionStateError("osm_artifact_storage_invalid")
            chunks: list[bytes] = []
            remaining = node.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise SessionStateError("osm_artifact_storage_invalid")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise SessionStateError("osm_artifact_storage_invalid")
            return b"".join(chunks)
        except OSError as exc:
            raise SessionStateError("osm_artifact_storage_invalid") from exc
        finally:
            os.close(descriptor)


def json_artifact(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def bounded_osm_failure_reason(exc: Exception) -> str:
    reason = str(exc)
    if len(reason) <= 240 and _OSM_FAILURE_REASON.fullmatch(reason):
        return reason
    return f"{type(exc).__name__.casefold()}_during_osm_writeback"


__all__ = [
    "bounded_osm_failure_reason",
    "json_artifact",
    "publish_osm_artifacts",
    "read_osm_artifact",
]
