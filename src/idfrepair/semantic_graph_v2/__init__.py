"""导出 V2 whole-model HVAC relation engine 的稳定 public records。"""

from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.candidates import (
    CandidateDomainStatus,
    CandidateGeneration,
    CandidateSet,
    generate_candidates,
)
from idfrepair.semantic_graph_v2.edits import (
    FieldEdit as SemanticFieldEdit,
    FieldValuePrecondition,
    RelationStatePrecondition,
    SemanticEdit,
    SemanticEditKind,
    apply_semantic_edits,
)
from idfrepair.semantic_graph_v2.ir import (
    CompoundFlowProjection,
    FieldRef,
    FlowTopologyForm,
    FlowStreamRole,
    FlowTransition,
    FlowTraversalRole,
    ModelIR,
    ObjectRef,
    OutdoorAirSystemContext,
    PortRef,
    ProjectionApplicability,
)
from idfrepair.semantic_graph_v2.ports import (
    ExtensiblePortRule,
    PortRegistry,
    PortRule,
)
from idfrepair.semantic_graph_v2.registry import (
    AdmissionStatus,
    ConstraintRegistry,
    ConstraintSpec,
)
from idfrepair.semantic_graph_v2.runtime import (
    RepairOutcome,
    RepairPhaseTiming,
    RepairStatus,
    repair_model,
)
from idfrepair.semantic_graph_v2.scan import ScanResult, Violation, scan_ir, scan_model
from idfrepair.semantic_graph_v2.solver import SolverLimits


__all__ = [
    "CompoundFlowProjection",
    "ExtensiblePortRule",
    "FieldRef",
    "FieldValuePrecondition",
    "FlowTopologyForm",
    "FlowStreamRole",
    "FlowTransition",
    "FlowTraversalRole",
    "ModelIR",
    "ObjectRef",
    "OutdoorAirSystemContext",
    "PortRef",
    "PortRegistry",
    "PortRule",
    "ProjectionApplicability",
    "AdmissionStatus",
    "CandidateDomainStatus",
    "CandidateGeneration",
    "CandidateSet",
    "ConstraintRegistry",
    "ConstraintSpec",
    "ScanResult",
    "RepairOutcome",
    "RepairPhaseTiming",
    "RepairStatus",
    "RelationStatePrecondition",
    "SemanticEdit",
    "SemanticEditKind",
    "SemanticFieldEdit",
    "SolverLimits",
    "Violation",
    "build_model_ir",
    "generate_candidates",
    "apply_semantic_edits",
    "repair_model",
    "scan_ir",
    "scan_model",
]
