"""Finite JSON contracts accepted from a language model."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence

from idfrepair.domain.errors import ModelContractError


ALLOWED_TOOLS = frozenset({
    "query_idd_object",
    "query_idd_field",
    "query_rdd",
    "inspect_object",
    "inspect_graph_neighbors",
    "find_same_type_peers",
    "find_reference_targets",
    "retrieve_public_cases",
    "retrieve_memory_rules",
    "simulate_candidate",
    "run_energyplus_candidate",
    "request_user_input",
})
TOOL_ARGUMENTS = {
    "query_idd_object": (frozenset({"object_type"}), frozenset()),
    "query_idd_field": (frozenset({"object_type"}), frozenset({"field_index", "field_name"})),
    "query_rdd": (frozenset({"query"}), frozenset({"limit"})),
    "inspect_object": (frozenset(), frozenset({"object_index", "object_name"})),
    "inspect_graph_neighbors": (frozenset({"node_id"}), frozenset()),
    "find_same_type_peers": (frozenset({"object_index"}), frozenset()),
    "find_reference_targets": (frozenset({"object_index", "field_index"}), frozenset()),
    "retrieve_public_cases": (frozenset({"error_tokens"}), frozenset({"field_roles", "limit", "object_types"})),
    "retrieve_memory_rules": (frozenset({"family", "error_signature"}), frozenset({"limit", "object_type"})),
    "simulate_candidate": (frozenset({"candidate_id"}), frozenset()),
    "run_energyplus_candidate": (frozenset({"candidate_id"}), frozenset()),
    "request_user_input": (frozenset({"root_id", "question_type", "prompt"}), frozenset({"choices"})),
}
FORBIDDEN_KEYS = frozenset({"patch", "diff", "python", "shell", "code", "script"})


@dataclass(frozen=True, slots=True)
class RepairIntent:
    root_id: str
    family: str
    target_object: str | None
    target_field: str | None
    confidence: float


@dataclass(frozen=True, slots=True)
class ToolRequest:
    tool: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.tool not in ALLOWED_TOOLS:
            raise ModelContractError(f"unknown_tool:{self.tool}")
        if any(str(key).casefold() in FORBIDDEN_KEYS for key in self.arguments):
            raise ModelContractError("free_form_patch_argument_forbidden")
        required, optional = TOOL_ARGUMENTS[self.tool]
        provided = frozenset(str(key) for key in self.arguments)
        missing = sorted(required - provided)
        if missing:
            raise ModelContractError("tool_arguments_missing:" + ",".join(missing))
        unknown = sorted(provided - required - optional)
        if unknown:
            raise ModelContractError("tool_arguments_unknown:" + ",".join(unknown))


@dataclass(frozen=True, slots=True)
class RepairPlan:
    root_id: str
    hypothesized_family: str
    target_object: str | None
    target_field: str | None
    requested_tools: tuple[ToolRequest, ...]
    evidence_summary: tuple[str, ...]
    candidate_primitives: tuple[Mapping[str, Any], ...]
    confidence: float
    ambiguities: tuple[str, ...]
    needs_user_input: bool


@dataclass(frozen=True, slots=True)
class UserQuestionProposal:
    question_type: str
    prompt: str
    choices: tuple[str, ...] = ()


def _mapping(value: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ModelContractError("invalid_json") from exc
    else:
        payload = value
    if not isinstance(payload, Mapping):
        raise ModelContractError("model_response_must_be_object")
    return payload


def _reject_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise ModelContractError(f"forbidden_key:{path}.{key}")
            _reject_forbidden(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _reject_forbidden(item, f"{path}[{index}]")


def parse_repair_plan(value: str | Mapping[str, Any]) -> RepairPlan:
    payload = _mapping(value)
    _reject_forbidden(payload)
    required = {
        "root_id",
        "hypothesized_family",
        "requested_tools",
        "evidence_summary",
        "candidate_primitives",
        "confidence",
        "ambiguities",
        "needs_user_input",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ModelContractError("missing_fields:" + ",".join(missing))
    allowed = required | {"target_object", "target_field"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ModelContractError("unknown_fields:" + ",".join(unknown))
    try:
        confidence = float(payload["confidence"])
    except (TypeError, ValueError) as exc:
        raise ModelContractError("confidence_must_be_number") from exc
    if not 0 <= confidence <= 1:
        raise ModelContractError("confidence_out_of_range")
    if not isinstance(payload["requested_tools"], Sequence) or isinstance(payload["requested_tools"], (str, bytes)):
        raise ModelContractError("requested_tools_must_be_array")
    if not all(isinstance(row, Mapping) for row in payload["requested_tools"]):
        raise ModelContractError("tool_request_must_be_object")
    requests = tuple(
        ToolRequest(str(row["tool"]), dict(row.get("arguments", {})))
        for row in payload["requested_tools"]
    )
    if not isinstance(payload["candidate_primitives"], Sequence) or isinstance(payload["candidate_primitives"], (str, bytes)):
        raise ModelContractError("candidate_primitives_must_be_array")
    if not all(isinstance(row, Mapping) for row in payload["candidate_primitives"]):
        raise ModelContractError("candidate_primitive_must_be_object")
    primitives = tuple(dict(row) for row in payload["candidate_primitives"])
    allowed_operations = {
        "replace_field", "insert_field", "delete_field", "rename_reference",
        "replace_vertices", "insert_object", "delete_object", "replace_object",
        "update_version",
    }
    if any(str(row.get("operation", "")) not in allowed_operations for row in primitives):
        raise ModelContractError("unknown_candidate_primitive")
    if not isinstance(payload["needs_user_input"], bool):
        raise ModelContractError("needs_user_input_must_be_boolean")
    return RepairPlan(
        root_id=str(payload["root_id"]),
        hypothesized_family=str(payload["hypothesized_family"]),
        target_object=str(payload["target_object"]) if payload.get("target_object") is not None else None,
        target_field=str(payload["target_field"]) if payload.get("target_field") is not None else None,
        requested_tools=requests,
        evidence_summary=tuple(str(item) for item in payload["evidence_summary"]),
        candidate_primitives=primitives,
        confidence=confidence,
        ambiguities=tuple(str(item) for item in payload["ambiguities"]),
        needs_user_input=payload["needs_user_input"],
    )
