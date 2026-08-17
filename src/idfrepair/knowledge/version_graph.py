"""Explicit EnergyPlus version compatibility graph."""

from __future__ import annotations

from dataclasses import dataclass


def version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split(".") if part != "")
    except ValueError:
        return ()


@dataclass(frozen=True, slots=True)
class VersionTransition:
    source: str
    target: str
    transition_program: str | None = None
    direct: bool = True


@dataclass(frozen=True, slots=True)
class VersionGraph:
    transitions: tuple[VersionTransition, ...]

    def path(self, source: str, target: str) -> tuple[VersionTransition, ...]:
        if source == target:
            return ()
        queue: list[tuple[str, tuple[VersionTransition, ...]]] = [(source, ())]
        visited = {source}
        while queue:
            current, path = queue.pop(0)
            for transition in self.transitions:
                if transition.source != current or transition.target in visited:
                    continue
                next_path = path + (transition,)
                if transition.target == target:
                    return next_path
                visited.add(transition.target)
                queue.append((transition.target, next_path))
        return ()
