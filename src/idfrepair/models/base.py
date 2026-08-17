"""Model backend protocol and deterministic unavailable-runtime stub."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ModelBackend(Protocol):
    name: str

    def generate(self, request: Mapping[str, Any]) -> Mapping[str, Any] | str: ...


class UnavailableModelBackend:
    name = "MODEL_RUNTIME_UNAVAILABLE"

    def generate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "root_id": str(request.get("root_id", "")),
            "hypothesized_family": str(request.get("family", "unknown")),
            "target_object": None,
            "target_field": None,
            "requested_tools": [],
            "evidence_summary": ["MODEL_RUNTIME_UNAVAILABLE"],
            "candidate_primitives": [],
            "confidence": 0.0,
            "ambiguities": ["local_model_weights_not_loaded"],
            "needs_user_input": True,
        }
