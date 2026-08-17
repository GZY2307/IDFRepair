"""External asset discovery without silently inventing files."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    relative_path: str
    source_path: str | None
    exists: bool
    sha256: str | None


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_asset(
    relative_path: str,
    *,
    input_directory: Path,
    search_roots: Iterable[Path] = (),
) -> AssetIdentity:
    """Resolve an exact relative path; basename ambiguity fails closed."""
    normalized = relative_path.replace("\\", "/")
    candidates = [input_directory / normalized]
    candidates.extend(root / normalized for root in search_roots)
    exact = [path.resolve() for path in candidates if path.is_file()]
    unique = {str(path): path for path in exact}
    if len(unique) == 1:
        path = next(iter(unique.values()))
        return AssetIdentity(relative_path, str(path), True, sha256_file(path))
    return AssetIdentity(relative_path, None, False, None)
