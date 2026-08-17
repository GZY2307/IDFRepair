"""Read-only discovery and exact version selection for EnergyPlus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Iterable

from idfrepair.domain.errors import RuntimeDiscoveryError
from idfrepair.io.assets import sha256_file


_IDD_VERSION = re.compile(r"!\s*IDD_Version\s+([^\s]+)", re.I)
_ENERGYPLUS_EXECUTABLE = re.compile(r"energyplus(?:[-_.]\d[\w.-]*)?(?:\.exe)?$", re.I)


def normalize_version(value: str) -> str:
    parts = value.strip().lstrip("vV").split(".")
    while parts and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    version: str
    executable: Path
    idd_path: Path
    home: Path

    @property
    def identity(self) -> dict[str, str]:
        return {
            "energyplus_executable": str(self.executable),
            "energyplus_executable_sha256": sha256_file(self.executable),
            "energyplus_version": self.version,
            "idd_path": str(self.idd_path),
            "idd_sha256": sha256_file(self.idd_path),
        }


def _runtime_from_path(path: Path) -> RuntimeSpec | None:
    if path.is_dir():
        exact = path / "energyplus"
        if exact.is_file():
            executable = exact
        else:
            try:
                versioned = sorted(
                    child for child in path.iterdir()
                    if child.is_file() and _ENERGYPLUS_EXECUTABLE.fullmatch(child.name)
                )
            except OSError:
                versioned = []
            if not versioned:
                return None
            executable = versioned[0]
    else:
        executable = path
    if not executable.is_file():
        return None
    home = executable.parent
    idd = home / "Energy+.idd"
    if not idd.is_file():
        return None
    prefix = idd.read_text(encoding="utf-8", errors="replace")[:4096]
    match = _IDD_VERSION.search(prefix)
    if match is None:
        return None
    return RuntimeSpec(
        version=normalize_version(match.group(1)),
        executable=executable.resolve(),
        idd_path=idd.resolve(),
        home=home.resolve(),
    )


def discover_runtimes(
    explicit: Path | None = None,
    *,
    search_roots: Iterable[Path] = (),
    include_defaults: bool = True,
) -> tuple[RuntimeSpec, ...]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    environment = os.environ.get("ENERGYPLUS_HOME")
    if include_defaults and environment:
        candidates.append(Path(environment))
    candidates.extend(search_roots)
    if include_defaults:
        candidates.extend((Path("/Applications"), Path("/usr/local"), Path("/opt")))
    found: dict[tuple[str, str], RuntimeSpec] = {}
    for candidate in candidates:
        direct = _runtime_from_path(candidate)
        if direct is not None:
            found[(direct.version, str(direct.executable))] = direct
            continue
        if not candidate.is_dir():
            continue
        try:
            children = tuple(candidate.glob("EnergyPlus*")) + tuple(candidate.glob("eplus*"))
        except OSError:
            continue
        for child in children:
            runtime = _runtime_from_path(child)
            if runtime is not None:
                found[(runtime.version, str(runtime.executable))] = runtime
    return tuple(found[key] for key in sorted(found))


def select_runtime(
    version: str,
    runtimes: Iterable[RuntimeSpec],
) -> RuntimeSpec:
    target = normalize_version(version)
    matches = [runtime for runtime in runtimes if normalize_version(runtime.version) == target]
    if len(matches) != 1:
        reason = "runtime_not_found" if not matches else "runtime_ambiguous"
        raise RuntimeDiscoveryError(f"{reason}:{target}")
    return matches[0]
