"""Validated configuration for bounded repair sessions."""

from __future__ import annotations

from dataclasses import dataclass

from idfrepair.domain.enums import RepairMode, RiskLevel


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Limits and policy knobs shared by the CLI, API, and engine."""

    mode: RepairMode = RepairMode.SAFE_AUTO
    max_rounds: int = 6
    max_candidates_per_root: int = 3
    max_total_energyplus_runs: int = 20
    max_backtracks: int = 1
    max_wall_time: float = 600.0
    max_model_tool_calls: int = 12
    maximum_automatic_risk: RiskLevel = RiskLevel.LOW
    minimum_automatic_confidence: float = 0.85
    model: str = "none"
    model_base_path: str | None = None
    model_adapter_path: str | None = None
    model_runtime_python: str | None = None
    timeout_seconds: int = 120
    production_enabled: bool = False
    automatic_repair_release_authorized: bool = False

    def __post_init__(self) -> None:
        positive = {
            "max_rounds": self.max_rounds,
            "max_candidates_per_root": self.max_candidates_per_root,
            "max_total_energyplus_runs": self.max_total_energyplus_runs,
            "max_wall_time": self.max_wall_time,
            "timeout_seconds": self.timeout_seconds,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name}_must_be_positive")
        if self.max_backtracks < 0:
            raise ValueError("max_backtracks_must_be_non_negative")
        if self.max_model_tool_calls < 0:
            raise ValueError("max_model_tool_calls_must_be_non_negative")
        if not 0.0 <= self.minimum_automatic_confidence <= 1.0:
            raise ValueError("minimum_automatic_confidence_out_of_range")
        if self.production_enabled:
            raise ValueError("production_mode_is_not_available")
        if self.automatic_repair_release_authorized:
            raise ValueError("automatic_repair_release_is_not_authorized")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready representation."""
        return {
            "automatic_repair_release_authorized": False,
            "case_retrieval_candidate_generation_enabled": False,
            "final_external_evaluation_authorized": False,
            "max_backtracks": self.max_backtracks,
            "max_candidates_per_root": self.max_candidates_per_root,
            "max_model_tool_calls": self.max_model_tool_calls,
            "max_rounds": self.max_rounds,
            "max_total_energyplus_runs": self.max_total_energyplus_runs,
            "max_wall_time": self.max_wall_time,
            "maximum_automatic_risk": self.maximum_automatic_risk.value,
            "minimum_automatic_confidence": self.minimum_automatic_confidence,
            "mode": self.mode.value,
            "model_adapter_path": self.model_adapter_path,
            "model_base_path": self.model_base_path,
            "model_enabled": False,
            "model_product_integration_authorized": False,
            "model_retraining_authorized": False,
            "model_runtime_python": self.model_runtime_python,
            "model": self.model,
            "production_enabled": False,
            "release_profile_id": "idfrepair.research_release.v1",
            "repair_memory_candidate_generation_enabled": False,
            "repair_memory_release_authorized": False,
            "timeout_seconds": self.timeout_seconds,
        }
