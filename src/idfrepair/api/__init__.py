"""FastAPI application boundary for local repair sessions."""

from __future__ import annotations

from typing import Any


def create_app(**kwargs: Any) -> Any:
    """Import web dependencies only when the API application is requested."""
    from idfrepair.api.app import create_app as factory

    return factory(**kwargs)


__all__ = ["create_app"]
