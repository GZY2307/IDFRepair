"""AirPath domains enumerate every supported topology alternative or abstain."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.candidates import (
    CandidateDomainStatus,
    generate_candidates,
)
from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model

from .compound_relation_fixtures import (
    BASE,
    RELATION_IDD,
    prospective_registry,
    prospective_scan,
)


AIR = "V2-AIRPATH-TYPED-MEMBER-009"


def _missing_splitter(text: str) -> str:
    return text.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:ZoneSplitter,Missing,AirLoopHVAC:SupplyPlenum,SP1;",
    )


def test_two_equal_supplypath_replacements_are_complete_but_ambiguous() -> None:
    text = _missing_splitter(BASE) + (
        "AirLoopHVAC:ZoneSplitter,ZS Twin,S Boundary,S Mid,S Leaf;\n"
    )
    registry = prospective_registry(AIR)
    outcome = repair_model(text, RELATION_IDD, registry=registry)

    assert outcome.status is RepairStatus.NEEDS_INPUT
    assert outcome.selected_edits == ()
    assert outcome.decisions[0].alternative_count == 2
    assert outcome.decisions[0].candidate_domain_complete is True


def test_complete_airpath_domain_contains_every_closing_object_occurrence() -> None:
    text = _missing_splitter(BASE) + (
        "AirLoopHVAC:ZoneSplitter,ZS Twin,S Boundary,S Mid,S Leaf;\n"
    )
    model, scan, _ = prospective_scan(text, AIR)
    violation = next(row for row in scan.hard_violations if row.constraint_id == AIR)
    domain = generate_candidates(model, scan).for_violation(violation.violation_id)

    assert domain is not None
    assert domain.status is CandidateDomainStatus.COMPLETE
    assert {
        edit.field_edits[-1].new_value for edit in domain.candidates
    } == {"ZS1", "ZS Twin"}


def test_unsupported_or_partial_airpath_never_auto_commits() -> None:
    unsupported = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "Fan:ConstantVolume,Unknown,AirLoopHVAC:SupplyPlenum,SP1;",
    )
    partial = BASE.replace(
        "AirLoopHVAC:SupplyPath,Supply Path,S Boundary,"
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:SupplyPath,Supply Path,S Boundary,"
        "AirLoopHVAC:ZoneSplitter;",
    )
    registry = prospective_registry(AIR)

    unsupported_outcome = repair_model(
        unsupported, RELATION_IDD, registry=registry,
    )
    partial_outcome = repair_model(partial, RELATION_IDD, registry=registry)

    assert unsupported_outcome.status in {RepairStatus.UNSUPPORTED, RepairStatus.VALID}
    assert unsupported_outcome.selected_edits == ()
    assert partial_outcome.status is RepairStatus.VALID
    assert partial_outcome.selected_edits == ()
