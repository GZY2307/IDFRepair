"""Project-level readiness and dependency inspection."""

from idfrepair.project.readiness import (
    inspect_project_files,
    inspect_readiness,
    normalize_project_path,
    resolve_external_dependencies,
)

__all__ = [
    "inspect_project_files",
    "inspect_readiness",
    "normalize_project_path",
    "resolve_external_dependencies",
]
