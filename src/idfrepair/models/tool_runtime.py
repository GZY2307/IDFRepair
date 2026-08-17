"""Schema-checked and call-limited model tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from idfrepair.candidates.base import CandidateContext
from idfrepair.domain.errors import ModelContractError
from idfrepair.domain.models import RepairCandidate, to_primitive
from idfrepair.io.idf import canonical
from idfrepair.knowledge.case_retrieval import CaseIndex
from idfrepair.models.contracts import ALLOWED_TOOLS, ToolRequest
from idfrepair.memory.repository import RuleRepository


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    tool: str
    arguments: Mapping[str, Any]
    succeeded: bool
    result: Any


class ToolRuntime:
    def __init__(
        self,
        tools: Mapping[str, Callable[..., Any]],
        *,
        maximum_calls: int = 12,
    ) -> None:
        if maximum_calls < 0:
            raise ValueError("maximum_calls_must_be_non_negative")
        self.tools = dict(tools)
        self.maximum_calls = maximum_calls
        self.records: list[ToolCallRecord] = []

    def call(self, request: ToolRequest) -> Any:
        if len(self.records) >= self.maximum_calls:
            raise ModelContractError("tool_call_limit_exceeded")
        tool = self.tools.get(request.tool)
        if tool is None:
            raise ModelContractError(f"tool_not_allowed_or_registered:{request.tool}")
        try:
            result = tool(**dict(request.arguments))
        except Exception as exc:
            self.records.append(ToolCallRecord(request.tool, request.arguments, False, type(exc).__name__))
            raise
        self.records.append(ToolCallRecord(request.tool, request.arguments, True, result))
        return result


def build_standard_tool_runtime(
    context: CandidateContext,
    *,
    candidates: Mapping[str, RepairCandidate] | None = None,
    case_index: CaseIndex | None = None,
    simulate: Callable[[RepairCandidate], Any] | None = None,
    run_candidate: Callable[[RepairCandidate], Any] | None = None,
    request_input: Callable[..., Any] | None = None,
    rule_repository: RuleRepository | None = None,
    maximum_calls: int = 12,
    allowed_tools: Iterable[str] | None = None,
) -> ToolRuntime:
    """Build all public model tools over read-only state and bounded candidates."""
    candidate_map = dict(candidates or {})

    def query_idd_object(*, object_type: str) -> Any:
        return to_primitive(context.idd.get(object_type))

    def query_idd_field(
        *, object_type: str, field_index: int | None = None, field_name: str | None = None,
    ) -> Any:
        definition = context.idd.get(object_type)
        if definition is None:
            return None
        if field_index is not None:
            return to_primitive(definition.field_at(int(field_index)))
        if field_name is not None:
            matches = [field for field in definition.fields if canonical(field.name) == canonical(field_name)]
            return to_primitive(matches[0]) if len(matches) == 1 else None
        return to_primitive(definition.fields)

    def query_rdd(*, query: str, limit: int = 20) -> Any:
        token = canonical(query)
        matches = [
            name for name in context.rdd.variable_names + context.rdd.meter_names
            if token in canonical(name)
        ]
        return matches[:max(0, min(int(limit), 100))]

    def inspect_object(*, object_index: int | None = None, object_name: str | None = None) -> Any:
        rows = list(context.document.objects)
        if object_index is not None:
            rows = [row for row in rows if row.index == int(object_index)]
        if object_name is not None:
            rows = [row for row in rows if canonical(row.name) == canonical(object_name)]
        return to_primitive(tuple(rows))

    def inspect_graph_neighbors(*, node_id: str) -> Any:
        return to_primitive(context.object_graph.neighbors(node_id))

    def find_same_type_peers(*, object_index: int) -> Any:
        index = int(object_index)
        if not 0 <= index < len(context.document.objects):
            return []
        target = context.document.objects[index]
        return to_primitive(tuple(
            row for row in context.document.objects
            if row.index != index and canonical(row.object_type) == canonical(target.object_type)
        ))

    def find_reference_targets(*, object_index: int, field_index: int) -> Any:
        index = int(object_index)
        field = int(field_index)
        if not 0 <= index < len(context.document.objects):
            return []
        source_node = context.object_graph.nodes[index].node_id
        target_ids = {
            edge.target for edge in context.object_graph.edges
            if edge.source == source_node and edge.field_index == field
        }
        return to_primitive(tuple(node for node in context.object_graph.nodes if node.node_id in target_ids))

    def retrieve_public_cases(
        *, error_tokens: list[str], object_types: list[str] | None = None,
        field_roles: list[str] | None = None, limit: int = 5,
    ) -> Any:
        if case_index is None:
            return []
        return to_primitive(case_index.retrieve(
            error_tokens=error_tokens,
            object_types=object_types or (),
            field_roles=field_roles or (),
            limit=max(0, min(int(limit), 20)),
            allowed_usage=context.metadata.get(
                "retrieval_allowed_usage", ("development-exposed", "demo-only"),
            ),
        ))

    def retrieve_memory_rules(
        *, family: str, error_signature: str,
        object_type: str | None = None, limit: int = 5,
    ) -> Any:
        repository = rule_repository
        if repository is None:
            value = context.metadata.get("rule_repository")
            repository = value if isinstance(value, RuleRepository) else None
        if repository is None:
            return []
        rows = []
        selected_rule_set = str(context.metadata.get("selected_rule_set_id") or "default")
        for rule in repository.list_rules(
            enabled=True, family=family, rule_set_id=selected_rule_set,
        ):
            if rule.error_signature and canonical(rule.error_signature) not in canonical(error_signature):
                continue
            if object_type and rule.object_type and canonical(rule.object_type) != canonical(object_type):
                continue
            rows.append({
                "rule_id": rule.rule_id,
                "rule_set_id": rule.rule_set_id,
                "scope": rule.scope.value,
                "source": rule.source.value,
                "confidence": rule.confidence,
                "priority": rule.priority,
                "requires_confirmation": rule.requires_confirmation,
            })
        return rows[:max(0, min(int(limit), 20))]

    def _candidate(candidate_id: str) -> RepairCandidate:
        try:
            return candidate_map[candidate_id]
        except KeyError as exc:
            raise ModelContractError("candidate_not_found") from exc

    def simulate_candidate(*, candidate_id: str) -> Any:
        if simulate is None:
            raise ModelContractError("simulate_candidate_not_available")
        return simulate(_candidate(candidate_id))

    def run_energyplus_candidate(*, candidate_id: str) -> Any:
        if run_candidate is None:
            raise ModelContractError("run_energyplus_candidate_not_available")
        return run_candidate(_candidate(candidate_id))

    def request_user_input(
        *, root_id: str, question_type: str, prompt: str, choices: list[str] | None = None,
    ) -> Any:
        if request_input is None:
            return {
                "choices": choices or [],
                "prompt": prompt,
                "question_type": question_type,
                "root_id": root_id,
                "status": "NEEDS_INPUT",
            }
        return request_input(
            root_id=root_id,
            question_type=question_type,
            prompt=prompt,
            choices=choices or [],
        )

    tools: dict[str, Callable[..., Any]] = {
        "find_reference_targets": find_reference_targets,
        "find_same_type_peers": find_same_type_peers,
        "inspect_graph_neighbors": inspect_graph_neighbors,
        "inspect_object": inspect_object,
        "query_idd_field": query_idd_field,
        "query_idd_object": query_idd_object,
        "query_rdd": query_rdd,
        "request_user_input": request_user_input,
        "retrieve_public_cases": retrieve_public_cases,
        "retrieve_memory_rules": retrieve_memory_rules,
        "run_energyplus_candidate": run_energyplus_candidate,
        "simulate_candidate": simulate_candidate,
    }
    if set(tools) != set(ALLOWED_TOOLS):
        raise RuntimeError("standard_tool_registry_incomplete")
    enabled = frozenset(ALLOWED_TOOLS if allowed_tools is None else allowed_tools)
    if not enabled <= ALLOWED_TOOLS:
        raise ValueError("model_tool_allowlist_invalid")
    return ToolRuntime(
        {name: tools[name] for name in sorted(enabled)},
        maximum_calls=maximum_calls,
    )
