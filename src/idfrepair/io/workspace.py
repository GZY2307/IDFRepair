"""Isolated, path-safe session workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass(frozen=True, slots=True)
class SessionWorkspace:
    root: Path

    @classmethod
    def create(cls, parent: Path | None = None) -> "SessionWorkspace":
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="idfrepair-", dir=parent))
        return cls(root=root)

    def round_directory(self, round_index: int, identity: str) -> Path:
        path = self.root / "energyplus" / f"{round_index:02d}-{identity[:16]}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def safe_path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError("workspace_path_escape")
        return path
