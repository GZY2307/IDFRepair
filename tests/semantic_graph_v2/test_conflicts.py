"""验证 violation/edit/constraint dependency factor graph 的保守分量。"""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.candidates import generate_candidates
from idfrepair.semantic_graph_v2.scan import scan_ir
from idfrepair.semantic_graph_v2.solver import build_conflict_components

from .conftest import IR_IDD
from .test_candidates import CLEAN, _connected_zone_double


def _components(text: str):  # type: ignore[no-untyped-def]
    model = build_model_ir(parse_idf(text), IR_IDD)
    scan = scan_ir(model)
    candidates = generate_candidates(model, scan)
    return scan, build_conflict_components(scan.hard_violations, candidates)


def test_zone_list_and_member_violations_share_one_component() -> None:
    scan, components = _components(_connected_zone_double())
    zone = tuple(
        row for row in scan.hard_violations if row.constraint_id.startswith("V2-ZONE-")
    )

    assert len(zone) == 2
    assert len(components) == 1
    assert {row.violation_id for row in components[0].violations} == {
        row.violation_id for row in zone
    }


def test_independent_branch_and_loop_faults_form_two_components() -> None:
    independent = CLEAN.replace(
        "Fan:ConstantVolume,Fan B,,A1,A2;",
        (
            "Fan:ConstantVolume,Fan B,,A1,A2;\n"
            "Fan:ConstantVolume,Fan A Twin,,A0,A1;"
        ),
    ).replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Unknown,A0,A1,",
    ).replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,SI,P2,Air Branch,SO;",
    )
    _, components = _components(independent)

    assert len(components) == 2
    assert {
        tuple(sorted(row.constraint_id for row in component.violations))
        for component in components
    } == {
        ("V2-BRANCH-TYPED-IDENTITY-001",),
        ("V2-LOOP-BRANCHLIST-SET-005",),
    }


def test_endpoint_violations_on_different_branches_form_two_components() -> None:
    text = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,"
        "Fan:ConstantVolume,Fan B,A1,A2;",
        (
            "Branch,Air Branch,,Fan:ConstantVolume,Fan A,BAD INLET,A1,"
            "Fan:ConstantVolume,Fan B,A1,A2;\n"
            "Branch,Other Air Branch,,Fan:ConstantVolume,Fan B,A1,BAD OUTLET;"
        ),
    )

    scan, components = _components(text)
    endpoint_violations = tuple(
        row for row in scan.hard_violations
        if row.constraint_id == "V2-BRANCH-ENDPOINT-002"
    )

    assert len(endpoint_violations) == 2
    assert len(components) == 2
    assert all(len(component.violations) == 1 for component in components)
