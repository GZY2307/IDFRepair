"""Serializable domain records for diagnosis, search, and reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence
from uuid import uuid4

from idfrepair.domain.enums import (
    OperationKind,
    Provenance,
    QuestionType,
    RepairMode,
    RepairStatus,
    RiskLevel,
    ValidationStage,
)


PENDING_REPAIR_STATE_SCHEMA = "idfrepair.pending-repair-state.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_primitive(value: Any) -> Any:
    """Recursively convert dataclasses and enums to JSON-ready values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_primitive(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_primitive(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DiagnosticRoot:
    root_id: str
    family: str
    message: str
    severity: str = "Severe"
    object_type: str | None = None
    object_name: str | None = None
    field_name: str | None = None
    signatures: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RepairOperation:
    kind: OperationKind
    object_type: str | None = None
    object_name: str | None = None
    object_index: int | None = None
    field_index: int | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    vertices: tuple[tuple[float, float, float], ...] = ()
    object_text: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    kind: str
    source: str
    strength: float
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    total: float
    components: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    candidate_id: str
    provider: str
    root_id: str
    family: str
    operations: tuple[RepairOperation, ...]
    evidence: tuple[CandidateEvidence, ...]
    risk: RiskLevel
    confidence: float
    input_sha256: str
    idd_sha256: str
    version: str
    requires_user_confirmation: bool = False
    rollback_supported: bool = True
    provenance: Provenance = Provenance.DETERMINISTIC
    score: CandidateScore | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    stage: ValidationStage
    passed: bool
    reasons: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnergyPlusResult:
    passed: bool
    returncode: int | None
    severe_count: int
    fatal_count: int
    warning_count: int = 0
    diagnostics: str = ""
    rdd_text: str = ""
    process_failure: bool = False
    timed_out: bool = False
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    err_sha256: str | None = None
    input_sha256: str | None = None
    runtime_identity: Mapping[str, Any] = field(default_factory=dict)
    command: tuple[str, ...] = ()
    cache_hit: bool = False
    wall_seconds: float = 0.0
    preprocessing_required: bool = False
    preprocessing_used: bool = False
    preprocessing_object_types: tuple[str, ...] = ()
    expanded_input_path: str | None = None
    expanded_input_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    state_sha256: str
    root_id: str
    candidate_id: str
    rank: int
    candidate: RepairCandidate
    static_result: ValidationResult
    semantic_result: ValidationResult
    energyplus_result: EnergyPlusResult | None
    transition_result: ValidationResult | None
    accepted: bool
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommittedRound:
    round_index: int
    before_sha256: str
    after_sha256: str
    root: DiagnosticRoot
    candidate: RepairCandidate
    energyplus_result: EnergyPlusResult


@dataclass(frozen=True, slots=True)
class UserQuestion:
    question_id: str
    question_type: QuestionType
    root_id: str
    prompt: str
    choices: tuple[Mapping[str, Any], ...] = ()
    required: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UserAnswer:
    question_id: str
    value: Any
    answered_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class RepairState:
    text: str
    sha256: str
    version: str
    diagnostics: tuple[DiagnosticRoot, ...] = ()
    energyplus_result: EnergyPlusResult | None = None
    round_index: int = 0


@dataclass(frozen=True, slots=True)
class PendingDecisionFrame:
    """One accepted branch parent required for bounded backtracking after restart."""

    parent_text: str
    parent_sha256: str
    parent_result: EnergyPlusResult
    parent_round_count: int
    candidate_id: str
    root_id: str


@dataclass(frozen=True, slots=True)
class PendingFaultLedgerState:
    """Complete latent-fault lineage at a private interactive checkpoint."""

    initial: tuple[Mapping[str, Any], ...] = ()
    seen: tuple[Mapping[str, Any], ...] = ()
    current: tuple[Mapping[str, Any], ...] = ()
    newly_revealed: tuple[Mapping[str, Any], ...] = ()
    resolved: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class PendingRepairState:
    """Private, state-bound checkpoint for a repair awaiting one user answer."""

    working_text: str
    working_sha256: str
    committed_rounds: tuple[CommittedRound, ...]
    remaining_root_ids: tuple[str, ...]
    question: UserQuestion
    attempts: tuple[RepairAttempt, ...] = ()
    rejected_candidates: tuple[str, ...] = ()
    backtracks: int = 0
    energyplus_runs: int = 0
    initial_diagnostics: tuple[DiagnosticRoot, ...] = ()
    initial_energyplus_diagnostics: str = ""
    original_input_sha256: str = ""
    working_result: EnergyPlusResult | None = None
    decision_stack: tuple[PendingDecisionFrame, ...] = ()
    failed_candidate_keys: tuple[tuple[str, str, str], ...] = ()
    seen_state_sha256s: tuple[str, ...] = ()
    fault_ledger: PendingFaultLedgerState = field(
        default_factory=PendingFaultLedgerState
    )
    schema_version: str = PENDING_REPAIR_STATE_SCHEMA
    checkpoint_id: str = ""


def pending_repair_checkpoint_id(state: PendingRepairState) -> str:
    """Hash every checkpoint field except its self-identifying digest."""

    payload = to_primitive(state)
    payload.pop("checkpoint_id", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def pending_repair_state_is_valid(
    state: PendingRepairState,
    *,
    original_input_sha256: str,
) -> bool:
    """Validate all state needed to resume and backtrack without reconstruction."""

    if (
        state.schema_version != PENDING_REPAIR_STATE_SCHEMA
        or state.original_input_sha256 != original_input_sha256
        or state.checkpoint_id != pending_repair_checkpoint_id(state)
        or sha256(state.working_text.encode("utf-8")).hexdigest()
        != state.working_sha256
        or state.question.root_id not in state.remaining_root_ids
        or state.working_result is None
        or state.energyplus_runs < 1
        or state.backtracks < 0
    ):
        return False
    committed = state.committed_rounds
    if len(state.decision_stack) != len(committed):
        return False
    expected_before = original_input_sha256
    for index, round_ in enumerate(committed):
        frame = state.decision_stack[index]
        if (
            round_.round_index != index + 1
            or round_.before_sha256 != expected_before
            or frame.parent_round_count != index
            or frame.parent_sha256 != expected_before
            or sha256(frame.parent_text.encode("utf-8")).hexdigest()
            != frame.parent_sha256
            or frame.candidate_id != round_.candidate.candidate_id
            or frame.root_id != round_.root.root_id
            or (
                index > 0
                and frame.parent_result != committed[index - 1].energyplus_result
            )
        ):
            return False
        expected_before = round_.after_sha256
    if expected_before != state.working_sha256:
        return False
    if committed and state.working_result != committed[-1].energyplus_result:
        return False
    seen_states = set(state.seen_state_sha256s)
    if (
        len(seen_states) != len(state.seen_state_sha256s)
        or original_input_sha256 not in seen_states
        or state.working_sha256 not in seen_states
        or any(
            len(key) != 3
            or any(not isinstance(value, str) or not value for value in key)
            or key[0] not in seen_states
            for key in state.failed_candidate_keys
        )
    ):
        return False

    def indexed(
        rows: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Mapping[str, Any]] | None:
        required = {
            "family",
            "field_name",
            "issue_id",
            "object_name",
            "object_type",
            "recoverability",
            "root_id",
            "severity",
        }
        result: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            issue_id = row.get("issue_id")
            if (
                set(row) != required
                or not isinstance(issue_id, str)
                or not issue_id
                or issue_id in result
                or any(
                    not isinstance(row.get(key), str) or not row.get(key)
                    for key in (
                        "family", "recoverability", "root_id", "severity",
                    )
                )
                or any(
                    value is not None and not isinstance(value, str)
                    for value in (
                        row.get("field_name"),
                        row.get("object_name"),
                        row.get("object_type"),
                    )
                )
            ):
                return None
            result[issue_id] = row
        return result

    initial = indexed(state.fault_ledger.initial)
    seen = indexed(state.fault_ledger.seen)
    current = indexed(state.fault_ledger.current)
    newly = indexed(state.fault_ledger.newly_revealed)
    resolved = indexed(state.fault_ledger.resolved)
    if any(
        value is None for value in (initial, seen, current, newly, resolved)
    ):
        return False
    assert initial is not None and seen is not None and current is not None
    assert newly is not None and resolved is not None
    current_root_ids = {str(row["root_id"]) for row in current.values()}
    return bool(
        initial
        and len(state.remaining_root_ids) == len(set(state.remaining_root_ids))
        and set(state.remaining_root_ids) == current_root_ids
        and set(initial).issubset(seen)
        and set(current).issubset(seen)
        and all(current[key] == seen[key] for key in current)
        and set(newly) == set(seen) - set(initial)
        and set(resolved) == set(seen) - set(current)
        and all(resolved[key] == seen[key] for key in resolved)
    )


@dataclass(slots=True)
class RepairOutcome:
    status: RepairStatus
    input_sha256: str
    output_sha256: str
    output_text: str
    initial_diagnostics: list[DiagnosticRoot] = field(default_factory=list)
    final_diagnostics: list[DiagnosticRoot] = field(default_factory=list)
    attempts: list[RepairAttempt] = field(default_factory=list)
    committed_rounds: list[CommittedRound] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    backtracks: int = 0
    energyplus_runs: int = 0
    questions: list[UserQuestion] = field(default_factory=list)
    answers: list[UserAnswer] = field(default_factory=list)
    rollback_reason: str | None = None
    limitations: list[str] = field(default_factory=list)
    model_calls: list[Mapping[str, Any]] = field(default_factory=list)
    tool_calls: list[Mapping[str, Any]] = field(default_factory=list)
    initial_energyplus_diagnostics: str = ""
    terminal_safety_admitted: bool = False
    terminal_safety_disposition: str = "NOT_EVALUATED"
    production_enabled: bool = False
    automatic_repair_release_authorized: bool = False
    pending_state: PendingRepairState | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


@dataclass(slots=True)
class RepairSession:
    session_id: str
    mode: RepairMode
    input_name: str
    input_sha256: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    status: RepairStatus | None = None
    outcome: RepairOutcome | None = None
    pending_questions: list[UserQuestion] = field(default_factory=list)
    answers: list[UserAnswer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls, *, mode: RepairMode, input_name: str, input_sha256: str,
    ) -> "RepairSession":
        return cls(
            session_id=uuid4().hex,
            mode=mode,
            input_name=input_name,
            input_sha256=input_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)
