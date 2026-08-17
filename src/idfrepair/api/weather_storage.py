"""Immutable content-addressed storage for uploaded weather files."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Iterator
import unicodedata


_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_READ_CHUNK_BYTES = 1024 * 1024
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_BASENAME_PATTERN = re.compile(
    r"(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WeatherBlob:
    """Canonical identity of one immutable weather asset."""

    path: Path
    sha256: str
    size_bytes: int


def validate_upload_display_leaf(filename: object) -> str:
    """Return one unchanged cross-platform-safe display leaf."""

    if (
        not isinstance(filename, str)
        or filename in {"", ".", ".."}
        or "/" in filename
        or "\\" in filename
        or ntpath.splitdrive(filename)[0]
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in filename
        )
        or not _WINDOWS_FORBIDDEN_CHARACTERS.isdisjoint(filename)
        or filename.endswith((" ", "."))
        or _WINDOWS_RESERVED_BASENAME_PATTERN.fullmatch(
            filename.partition(".")[0].rstrip(" .")
        )
        is not None
    ):
        raise ValueError("upload_name_invalid")
    return filename


def validate_weather_upload(
    filename: object,
    content: bytes,
    *,
    max_bytes: int,
) -> str:
    """Return an unchanged safe EPW display leaf or raise a stable token."""

    if len(content) > max_bytes:
        raise ValueError("supporting_upload_too_large")
    safe_name = validate_upload_display_leaf(filename)
    if Path(safe_name).suffix.casefold() != ".epw":
        raise ValueError("weather_extension_must_be_epw")
    return safe_name


def _blob_directory(workspace_root: Path) -> Path:
    return Path(workspace_root) / "uploads" / "weather" / "blobs"


def _blob_path(workspace_root: Path, sha256: str) -> Path:
    return _blob_directory(workspace_root) / f"{sha256}.epw"


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _fsync_directory(descriptor: int) -> None:
    """Persist directory entries through an already-held trusted descriptor."""

    os.fsync(descriptor)


def _open_absolute_directory(path: Path, *, error_token: str) -> int:
    """Open an absolute directory one no-follow component at a time."""

    absolute = Path(os.path.abspath(path))
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, _directory_open_flags())
        for leaf in absolute.parts[1:]:
            child = os.open(
                leaf,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ValueError(error_token) from exc


@contextmanager
def _open_blob_directory_chain(
    workspace_root: Path,
    *,
    create: bool,
    error_token: str,
) -> Iterator[tuple[Path, int]]:
    """Hold a no-follow chain and optionally persist every child directory entry."""

    root = Path(os.path.abspath(workspace_root))
    if root == root.parent:
        raise ValueError(error_token)
    anchor = root.parent.parent if root.parent != root.parent.parent else root.parent
    try:
        workspace_leaves = root.relative_to(anchor).parts
    except ValueError as exc:  # pragma: no cover - guarded by absolute ancestry above
        raise ValueError(error_token) from exc
    held = [_open_absolute_directory(anchor, error_token=error_token)]
    current_path = anchor
    try:
        for leaf in (*workspace_leaves, "uploads", "weather", "blobs"):
            if create:
                try:
                    os.mkdir(leaf, 0o700, dir_fd=held[-1])
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise ValueError(error_token) from exc
            try:
                child = os.open(
                    leaf,
                    _directory_open_flags(),
                    dir_fd=held[-1],
                )
            except OSError as exc:
                raise ValueError(error_token) from exc
            held.append(child)
            current_path /= leaf
            if create:
                # This is intentionally unconditional. A retry must close an
                # earlier uncertain parent barrier even when the child exists.
                _fsync_directory(held[-2])
        yield current_path, held[-1]
    finally:
        for descriptor in reversed(held):
            os.close(descriptor)


def _open_random_temporary(
    directory_descriptor: int,
) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    for _attempt in range(128):
        leaf = f".weather-{secrets.token_hex(16)}.tmp"
        try:
            return (
                os.open(leaf, flags, 0o600, dir_fd=directory_descriptor),
                leaf,
            )
        except FileExistsError:
            continue
    raise FileExistsError("weather_blob_temporary_collision")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("weather_blob_short_write")
        remaining = remaining[written:]


def verify_weather_blob(
    workspace_root: Path,
    sha256: str,
    size_bytes: int,
) -> Path:
    """Verify one exact no-follow regular blob and return its canonical path."""

    if not isinstance(sha256, str) or _HASH_PATTERN.fullmatch(sha256) is None:
        raise ValueError("weather_blob_hash_invalid")
    if type(size_bytes) is not int or size_bytes < 0:
        raise ValueError("weather_blob_size_invalid")

    root = Path(os.path.abspath(workspace_root))
    path = _blob_path(root, sha256)
    with _open_blob_directory_chain(
        root,
        create=False,
        error_token="weather_blob_invalid",
    ) as (_directory, directory_descriptor):
        _verify_weather_blob_at(
            directory_descriptor,
            f"{sha256}.epw",
            sha256,
            size_bytes,
        )
    return path


def _verify_weather_blob_at(
    directory_descriptor: int,
    leaf: str,
    sha256: str,
    size_bytes: int,
) -> None:
    """Verify one blob leaf relative to a held no-follow blobs directory."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(leaf, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ValueError("weather_blob_invalid") from exc

    try:
        try:
            node = os.fstat(descriptor)
            if not stat.S_ISREG(node.st_mode) or node.st_size != size_bytes:
                raise ValueError("weather_blob_invalid")
            digest = hashlib.sha256()
            observed_size = 0
            while True:
                chunk = os.read(descriptor, _READ_CHUNK_BYTES)
                if not chunk:
                    break
                observed_size += len(chunk)
                digest.update(chunk)
            if observed_size != size_bytes or digest.hexdigest() != sha256:
                raise ValueError("weather_blob_invalid")
        except OSError as exc:
            raise ValueError("weather_blob_invalid") from exc
    finally:
        os.close(descriptor)


def publish_weather_blob(workspace_root: Path, content: bytes) -> WeatherBlob:
    """Durably publish or safely reuse an immutable content-addressed blob."""

    digest = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    root = Path(os.path.abspath(workspace_root))
    final_path = _blob_path(root, digest)
    with _open_blob_directory_chain(
        root,
        create=True,
        error_token="weather_blob_directory_invalid",
    ) as (_directory, directory_descriptor):
        descriptor, temporary_leaf = _open_random_temporary(
            directory_descriptor,
        )
        descriptor_open = True
        try:
            try:
                _write_all(descriptor, content)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
                descriptor_open = False

            try:
                os.link(
                    temporary_leaf,
                    f"{digest}.epw",
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                _verify_weather_blob_at(
                    directory_descriptor,
                    f"{digest}.epw",
                    digest,
                    size_bytes,
                )
            _fsync_directory(directory_descriptor)
            return WeatherBlob(path=final_path, sha256=digest, size_bytes=size_bytes)
        finally:
            if descriptor_open:
                os.close(descriptor)
            try:
                os.unlink(temporary_leaf, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            else:
                _fsync_directory(directory_descriptor)
