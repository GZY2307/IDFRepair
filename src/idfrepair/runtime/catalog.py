"""Thread-safe, presentation-safe catalog of validated EnergyPlus runtimes."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from idfrepair.domain.errors import RuntimeDiscoveryError
from idfrepair.runtime.discovery import RuntimeSpec, discover_runtimes, normalize_version


Discoverer = Callable[[], Iterable[RuntimeSpec]]


def _git_common_repository(project_root: Path) -> Path | None:
    marker = project_root / ".git"
    if marker.is_dir():
        return project_root.resolve()
    if not marker.is_file():
        return None
    try:
        directive = marker.read_text(encoding="utf-8").strip()
        if not directive.startswith("gitdir:"):
            return None
        git_dir = Path(directive.removeprefix("gitdir:").strip())
        if not git_dir.is_absolute():
            git_dir = marker.parent / git_dir
        common_file = git_dir / "commondir"
        common_dir = Path(common_file.read_text(encoding="utf-8").strip())
        if not common_dir.is_absolute():
            common_dir = git_dir / common_dir
        common_dir = common_dir.resolve()
    except (OSError, RuntimeError):
        return None
    return common_dir.parent if common_dir.name == ".git" else None


def default_runtime_roots(
    *,
    cwd: Path | None = None,
    module_root: Path | None = None,
) -> tuple[Path, ...]:
    """Return existing project-local runtime roots, including a worktree's common repo."""
    working_root = (cwd or Path.cwd()).resolve()
    package_root = (module_root or Path(__file__).resolve().parents[3]).resolve()
    candidates: list[Path] = []
    configured = os.environ.get("IDFREPAIR_RUNTIME_ROOTS", "")
    candidates.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    for project_root in (working_root, package_root):
        candidates.append(project_root / ".local")
        common = _git_common_repository(project_root)
        if common is not None:
            candidates.append(common / ".local")
    unique: dict[str, Path] = {}
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            unique[str(resolved)] = resolved
    return tuple(unique.values())


def _discover_defaults() -> Iterable[RuntimeSpec]:
    return discover_runtimes(search_roots=default_runtime_roots())


def _resolved(runtime: RuntimeSpec) -> RuntimeSpec:
    return replace(
        runtime,
        version=normalize_version(runtime.version),
        executable=runtime.executable.resolve(),
        idd_path=runtime.idd_path.resolve(),
        home=runtime.home.resolve(),
    )


def _runtime_id(runtime: RuntimeSpec) -> str:
    identity = json.dumps(
        {
            "version": normalize_version(runtime.version),
            "executable": str(runtime.executable.resolve()),
            "idd": str(runtime.idd_path.resolve()),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"ep-{hashlib.sha256(identity).hexdigest()[:20]}"


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in normalize_version(version).replace("-", ".").split(".")
    )


class RuntimeCatalog:
    """Discover runtimes once, expose opaque IDs, and revalidate on resolution."""

    def __init__(self, *, discoverer: Discoverer | None = None) -> None:
        self._discoverer = discoverer or _discover_defaults
        self._lock = RLock()
        self._runtimes: dict[str, RuntimeSpec] = {}
        self._default_runtime_id: str | None = None
        self.rescan()

    def rescan(self) -> dict[str, Any]:
        discovered = (_resolved(runtime) for runtime in self._discoverer())
        runtimes = {
            _runtime_id(runtime): runtime
            for runtime in discovered
            if runtime.executable.is_file() and runtime.idd_path.is_file()
        }
        ordered = sorted(
            runtimes,
            key=lambda identity: (
                _version_key(runtimes[identity].version),
                str(runtimes[identity].home).casefold(),
                identity,
            ),
        )
        with self._lock:
            self._runtimes = {identity: runtimes[identity] for identity in ordered}
            self._default_runtime_id = ordered[-1] if ordered else None
            return self._snapshot_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "runtimes": [
                {
                    "runtime_id": identity,
                    "version": runtime.version,
                    "home": str(runtime.home),
                    "executable_name": runtime.executable.name,
                    "idd_ready": runtime.idd_path.is_file(),
                }
                for identity, runtime in self._runtimes.items()
            ],
            "default_runtime_id": self._default_runtime_id,
        }

    def resolve(self, runtime_id: str | None) -> RuntimeSpec:
        with self._lock:
            runtime = self._runtimes.get(runtime_id or "")
        if runtime is None:
            raise RuntimeDiscoveryError(f"runtime_id_unknown:{runtime_id or '<empty>'}")
        if not runtime.executable.is_file() or not runtime.idd_path.is_file():
            raise RuntimeDiscoveryError(f"runtime_unavailable:{runtime_id}")
        return runtime

    def specs(self) -> tuple[RuntimeSpec, ...]:
        """Return the ordered runtime specs after revalidating their files."""

        with self._lock:
            identities = tuple(self._runtimes)
        return tuple(self.resolve(identity) for identity in identities)

    def resolve_version(self, version: str) -> RuntimeSpec:
        """Resolve one exact normalized version and reject ambiguous installations."""

        target = normalize_version(version)
        with self._lock:
            matches = [
                (identity, runtime)
                for identity, runtime in self._runtimes.items()
                if normalize_version(runtime.version) == target
            ]
        if len(matches) != 1:
            reason = "runtime_not_found" if not matches else "runtime_ambiguous"
            raise RuntimeDiscoveryError(f"{reason}:{target}")
        return self.resolve(matches[0][0])
