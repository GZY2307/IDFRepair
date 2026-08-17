"""Isolated EnergyPlus execution with explicit process-failure semantics."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import time
from typing import Iterable, Mapping

from idfrepair.diagnostics.err_parser import diagnostic_counts, parse_err
from idfrepair.domain.errors import RuntimeProcessError
from idfrepair.domain.models import EnergyPlusResult
from idfrepair.io.assets import sha256_file
from idfrepair.io.idf import canonical, parse_idf, text_sha256
from idfrepair.io.workspace import SessionWorkspace
from idfrepair.runtime.cache import EnergyPlusCache, cache_key
from idfrepair.runtime.discovery import RuntimeSpec


def _sha_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def weather_asset_ready(path: Path | None) -> bool:
    """Return whether a supplied weather path is a regular EPW asset."""

    if path is None or path.suffix.casefold() != ".epw":
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def preprocessing_requirements(text: str) -> tuple[str, ...]:
    """Return object types that require EnergyPlus ExpandObjects preprocessing."""
    required = {
        obj.object_type.strip()
        for obj in parse_idf(text).objects
        if canonical(obj.object_type).startswith("hvactemplate:")
        or canonical(obj.object_type).startswith("groundheattransfer:")
    }
    return tuple(sorted(required, key=str.casefold))


def dependency_run_path(path: Path) -> Path:
    """Recover a safe logical dependency path from a session upload path."""

    parts = path.parts
    indices = [index for index, value in enumerate(parts) if value == "dependencies"]
    if indices and indices[-1] < len(parts) - 1:
        return Path(*parts[indices[-1] + 1:])
    return Path(path.name)


class EnergyPlusRunner:
    """Callable runner used by the transactional engine."""

    def __init__(
        self,
        runtime: RuntimeSpec,
        *,
        workspace: SessionWorkspace,
        weather: Path | None = None,
        dependencies: Iterable[Path] = (),
        timeout_seconds: int = 120,
        cache: EnergyPlusCache | None = None,
    ) -> None:
        self.runtime = runtime
        self.workspace = workspace
        self.weather = weather
        self.dependencies = tuple(dependencies)
        self.timeout_seconds = timeout_seconds
        self.cache = cache or EnergyPlusCache()
        self.calls = 0
        self.executions = 0
        self.results: list[EnergyPlusResult] = []

    def __call__(self, text: str, round_index: int) -> EnergyPlusResult:
        return self.run(text, round_index)

    def run(self, text: str, round_index: int) -> EnergyPlusResult:
        if self.weather is not None:
            if not weather_asset_ready(self.weather):
                raise RuntimeProcessError("run_readiness_blocked:weather")
        has_design_day = any(
            canonical(obj.object_type) == "sizingperiod:designday"
            for obj in parse_idf(text).objects
        )
        if self.weather is None and not has_design_day:
            raise RuntimeProcessError("run_readiness_blocked:weather")
        self.calls += 1
        input_identity = text_sha256(text)
        preprocessing_objects = preprocessing_requirements(text)
        identity = {
            "dependency_sha256": [sha256_file(path) for path in self.dependencies if path.is_file()],
            "executable_sha256": sha256_file(self.runtime.executable),
            "idd_sha256": sha256_file(self.runtime.idd_path),
            "input_sha256": input_identity,
            "preprocessing": {
                "expandobjects": bool(preprocessing_objects),
                "object_types": preprocessing_objects,
            },
            "weather_sha256": sha256_file(self.weather) if self.weather and self.weather.is_file() else None,
        }
        key = cache_key(identity)
        cached = self.cache.get(key)
        if cached is not None:
            self.results.append(cached)
            return cached
        self.executions += 1
        run_directory = self.workspace.round_directory(round_index, input_identity)
        input_path = run_directory / "input.idf"
        input_path.write_text(text, encoding="utf-8")
        for dependency in self.dependencies:
            if dependency.is_file():
                destination = run_directory / dependency_run_path(dependency)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.resolve() != dependency.resolve():
                    shutil.copy2(dependency, destination)
        output_directory = run_directory / "output"
        output_directory.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.runtime.executable),
            "-i", str(self.runtime.idd_path),
            "-d", str(output_directory),
        ]
        if preprocessing_objects:
            command.append("-x")
        command.append("-r")
        if self.weather is None:
            command.append("-D")
        else:
            command.extend(("-w", str(self.weather)))
        command.append(str(input_path))
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=run_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            process_failure = False
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = None
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            process_failure = True
            timed_out = True
        except OSError as exc:
            returncode = None
            stdout = b""
            stderr = str(exc).encode("utf-8", errors="replace")
            process_failure = True
            timed_out = False
        err_path = output_directory / "eplusout.err"
        rdd_path = output_directory / "eplusout.rdd"
        diagnostics = err_path.read_text(encoding="utf-8", errors="replace") if err_path.is_file() else ""
        rdd_text = rdd_path.read_text(encoding="utf-8", errors="replace") if rdd_path.is_file() else ""
        counts = diagnostic_counts(parse_err(diagnostics))
        expanded_source = next(
            (
                candidate for candidate in (
                    run_directory / "expanded.idf",
                    output_directory / "eplusout.expidf",
                    output_directory / "expanded.idf",
                )
                if candidate.is_file()
            ),
            None,
        )
        expanded_artifact = None
        if expanded_source is not None:
            expanded_artifact = output_directory / "expanded.expidf"
            if expanded_artifact.resolve() != expanded_source.resolve():
                shutil.copy2(expanded_source, expanded_artifact)
        result = EnergyPlusResult(
            passed=bool(
                not process_failure
                and returncode == 0
                and counts["severe"] == 0
                and counts["fatal"] == 0
            ),
            returncode=returncode,
            severe_count=counts["severe"],
            fatal_count=counts["fatal"],
            warning_count=counts["warning"],
            diagnostics=diagnostics,
            rdd_text=rdd_text,
            process_failure=process_failure,
            timed_out=timed_out,
            stdout_sha256=_sha_bytes(stdout),
            stderr_sha256=_sha_bytes(stderr),
            err_sha256=sha256_file(err_path) if err_path.is_file() else None,
            input_sha256=input_identity,
            runtime_identity={**self.runtime.identity, "cache_key": key},
            command=tuple(command),
            wall_seconds=time.monotonic() - started,
            preprocessing_required=bool(preprocessing_objects),
            preprocessing_used=bool(preprocessing_objects),
            preprocessing_object_types=preprocessing_objects,
            expanded_input_path=str(expanded_artifact) if expanded_artifact else None,
            expanded_input_sha256=(
                sha256_file(expanded_artifact) if expanded_artifact is not None else None
            ),
        )
        self.cache.put(key, result)
        self.results.append(result)
        return result
