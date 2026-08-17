"""验证候选只使用当前 snapshot 的显式关系证据。"""

from __future__ import annotations

import pytest

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.candidates import (
    CandidateDomainStatus,
    generate_candidates,
)
from idfrepair.semantic_graph_v2.edits import (
    SemanticEditConflict,
    apply_semantic_edits,
)
from idfrepair.semantic_graph_v2.scan import scan_ir, scan_model

from .conftest import IR_IDD, IR_IDF


CLEAN = IR_IDF.replace(
    "ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,",
    "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment,",
)


def _generation(text: str):  # type: ignore[no-untyped-def]
    model = build_model_ir(parse_idf(text), IR_IDD)
    scan = scan_ir(model)
    return model, scan, generate_candidates(model, scan)


def test_branch_identity_candidate_uses_endpoint_evidence_not_name_similarity() -> None:
    fault = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Almost Fan A,A0,A1,",
    )
    _, scan, generation = _generation(fault)
    violation = next(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    domain = generation.for_violation(violation.violation_id)

    assert domain is not None
    assert domain.status is CandidateDomainStatus.COMPLETE
    assert len(domain.candidates) == 1
    assert domain.candidates[0].field_edits[-1].new_value == "Fan A"


def test_candidate_materializes_field_and_relation_read_preconditions() -> None:
    fault = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Almost Fan A,A0,A1,",
    )
    _, scan, generation = _generation(fault)
    violation = next(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    domain = generation.for_violation(violation.violation_id)
    assert domain is not None and len(domain.candidates) == 1
    edit = domain.candidates[0]

    field_reads = {
        variable for variable in edit.precondition_reads
        if variable.startswith("field:object:")
    }
    relation_reads = set(edit.precondition_reads) - field_reads
    provenance_fields = {
        f"field:{field.field_id}" for field in violation.field_refs
    }

    assert provenance_fields <= field_reads
    assert field_reads == {
        f"field:{precondition.field_id}"
        for precondition in edit.field_preconditions
    }
    assert relation_reads == {
        precondition.variable_id
        for precondition in edit.relation_preconditions
    }


def test_apply_rejects_stale_field_and_relation_preconditions() -> None:
    fault = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Almost Fan A,A0,A1,",
    )
    _, scan, generation = _generation(fault)
    violation = next(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    domain = generation.for_violation(violation.violation_id)
    assert domain is not None and len(domain.candidates) == 1
    edit = domain.candidates[0]

    stale_field = fault.replace(
        "Fan:ConstantVolume,Almost Fan A,A0,A1,",
        "Fan:ConstantVolume,Almost Fan A,STALE,A1,",
    )
    with pytest.raises(
        SemanticEditConflict, match="field_precondition_value_mismatch",
    ):
        apply_semantic_edits(stale_field, (edit,))

    stale_relation = fault.replace(
        "Fan:ConstantVolume,Fan B,A1,A2;",
        "Fan:ConstantVolume,Fan B,A1,STALE;",
    )
    with pytest.raises(
        SemanticEditConflict, match="relation_precondition_snapshot_mismatch",
    ):
        apply_semantic_edits(stale_relation, (edit,))


def test_same_endpoint_tie_returns_two_candidates_instead_of_fuzzy_choice() -> None:
    tied = CLEAN.replace(
        "Fan:ConstantVolume,Fan B,,A1,A2;",
        (
            "Fan:ConstantVolume,Fan B,,A1,A2;\n"
            "Fan:ConstantVolume,Fan A Twin,,A0,A1;"
        ),
    ).replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Unknown,A0,A1,",
    )
    _, scan, generation = _generation(tied)
    violation = next(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    domain = generation.for_violation(violation.violation_id)

    assert domain is not None
    assert domain.status is CandidateDomainStatus.COMPLETE
    assert {
        edit.field_edits[-1].new_value for edit in domain.candidates
    } == {"Fan A", "Fan A Twin"}


def test_branch_reorder_domain_is_incomplete_when_endpoint_evidence_is_also_faulty() -> None:
    fault = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,"
        "Fan:ConstantVolume,Fan B,A1,A2;",
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,BAD,"
        "Fan:ConstantVolume,Fan B,A1,A2;",
    )
    _, scan, generation = _generation(fault)
    continuity = next(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-CONTINUITY-003"
    )
    assert any(
        row.constraint_id == "V2-BRANCH-ENDPOINT-002"
        for row in scan.hard_violations
    )

    domain = generation.for_violation(continuity.violation_id)

    assert domain is not None
    assert domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
    assert domain.candidates == ()
    assert domain.reason == "cooccurring_endpoint_or_identity_violation"


def _connected_zone_double() -> str:
    return IR_IDF.replace(
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;",
        (
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;\n"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1B,,Z1 Return,Z1 Supply;"
        ),
    ).replace(
        "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;",
        (
            "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,2,1,,;"
        ),
    )


def test_connected_zone_double_candidates_share_snapshot_factor_and_close_jointly() -> None:
    text = _connected_zone_double()
    model, scan, generation = _generation(text)
    zone_violations = tuple(
        row for row in scan.hard_violations
        if row.constraint_id in {
            "V2-ZONE-LIST-OWNERSHIP-011",
            "V2-ZONE-TYPED-MEMBER-012",
        }
    )
    domains = tuple(
        generation.for_violation(row.violation_id) for row in zone_violations
    )

    assert len(zone_violations) == 2
    assert all(domain is not None for domain in domains)
    assert all(domain.status is CandidateDomainStatus.COMPLETE for domain in domains if domain)
    assert all(len(domain.candidates) == 1 for domain in domains if domain)
    edits = tuple(domain.candidates[0] for domain in domains if domain)
    assert len({factor for edit in edits for factor in edit.precondition_reads if factor.startswith("zone-equipment-factor:")}) == 1

    for edit in edits:
        residual = scan_model(parse_idf(apply_semantic_edits(text, (edit,))), IR_IDD)
        assert any(
            row.constraint_id in {
                "V2-ZONE-LIST-OWNERSHIP-011",
                "V2-ZONE-TYPED-MEMBER-012",
            }
            for row in residual.hard_violations
        )
    closed = scan_model(parse_idf(apply_semantic_edits(text, edits)), IR_IDD)
    assert not {
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    } & set(closed.constraint_ids)


def test_detect_only_violation_has_no_autonomous_candidate() -> None:
    fault = CLEAN.replace(
        "AirLoopHVAC,Main Air Loop,Main Controllers,",
        "AirLoopHVAC,Main Air Loop,Missing Controllers,",
    )
    _, scan, generation = _generation(fault)
    violation = next(
        row for row in scan.violations
        if row.constraint_id == "V2-CONTROLLER-OWNERSHIP-103"
    )
    domain = generation.for_violation(violation.violation_id)

    assert domain is not None
    assert domain.candidates == ()
    assert domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
