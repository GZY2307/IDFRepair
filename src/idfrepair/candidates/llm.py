"""Compilation boundary from a strict model plan to finite candidates."""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from idfrepair.domain.models import RepairCandidate


def compile_model_plan(
    plan: Mapping[str, object],
    *,
    compilers: Mapping[str, Callable[[Mapping[str, object]], Sequence[RepairCandidate]]],
) -> tuple[RepairCandidate, ...]:
    family = str(plan.get("hypothesized_family", ""))
    if any(key in plan for key in ("patch", "python", "shell", "code")):
        raise ValueError("free_form_model_patch_forbidden")
    compiler = compilers.get(family)
    if compiler is None:
        return ()
    rows = tuple(compiler(plan))
    return rows if len(rows) <= 3 else ()
