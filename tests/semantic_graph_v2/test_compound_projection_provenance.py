"""Compound candidates guard every source-backed topology read."""

from __future__ import annotations

import pytest

from idfrepair.semantic_graph_v2.candidates import generate_candidates
from idfrepair.semantic_graph_v2.edits import (
    SemanticEditConflict,
    apply_semantic_edits,
)

from .compound_relation_fixtures import BASE, prospective_scan


AIR = "V2-AIRPATH-TYPED-MEMBER-009"


def test_airpath_candidate_materializes_projection_and_field_guards() -> None:
    fault = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:SupplyPlenum,Missing,AirLoopHVAC:SupplyPlenum,SP1;",
    )
    model, scan, _ = prospective_scan(fault, AIR)
    violation = next(row for row in scan.hard_violations if row.constraint_id == AIR)
    domain = generate_candidates(model, scan).for_violation(violation.violation_id)

    assert domain is not None and len(domain.candidates) == 1
    candidate = domain.candidates[0]
    projection_reads = {
        value for value in violation.read_variables
        if value.startswith("flow-projection:")
    }
    field_reads = {
        value.removeprefix("field:") for value in candidate.precondition_reads
        if value.startswith("field:object:")
    }
    assert projection_reads
    assert projection_reads <= set(candidate.precondition_reads)
    assert field_reads == {
        item.field_id for item in candidate.field_preconditions
    }
    assert projection_reads <= {
        item.variable_id for item in candidate.relation_preconditions
    }
    assert apply_semantic_edits(fault, (candidate,)) != fault

    stale = fault.replace("S Leaf;", "Changed Leaf;")
    with pytest.raises(SemanticEditConflict, match="precondition"):
        apply_semantic_edits(stale, (candidate,))
