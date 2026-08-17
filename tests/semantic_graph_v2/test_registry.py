"""验证 V2 registry 是 declarative、target-free 且保留 rejected 语义。"""

from __future__ import annotations

from idfrepair.semantic_graph_v2.registry import (
    AdmissionStatus,
    documented_registry,
    production_registry,
)


def test_production_registry_has_no_family_or_locator_fields() -> None:
    registry = production_registry()

    assert registry.specs
    assert len(registry.specs) == len({spec.constraint_id for spec in registry.specs})
    for spec in registry.specs:
        assert not hasattr(spec, "family")
        assert not hasattr(spec, "locator")
        assert spec.admission_status in {
            AdmissionStatus.ADMIT_SAFE_AUTO,
            AdmissionStatus.ADMIT_DETECT_ONLY,
        }


def test_rejected_constraints_are_documented_but_not_scanned_in_production() -> None:
    documented = {spec.constraint_id: spec for spec in documented_registry().specs}
    production = {spec.constraint_id for spec in production_registry().specs}

    assert documented["V2-ZONE-PRIORITY-EQUALITY-901"].admission_status is (
        AdmissionStatus.REJECT_EXTERNAL_INTENT
    )
    assert documented["V2-PARALLEL-MIDDLE-ORDER-903"].admission_status is (
        AdmissionStatus.REJECT_EXTERNAL_INTENT
    )
    assert documented["V2-CONTROLLER-SENSOR-EQUALITY-902"].admission_status is (
        AdmissionStatus.REJECT_NOT_SEMANTIC
    )
    assert not {
        "V2-ZONE-PRIORITY-EQUALITY-901",
        "V2-PARALLEL-MIDDLE-ORDER-903",
        "V2-CONTROLLER-SENSOR-EQUALITY-902",
    } & production


def test_registry_declares_dependency_factors_and_candidate_keys() -> None:
    safe = tuple(
        spec for spec in production_registry().specs
        if spec.admission_status is AdmissionStatus.ADMIT_SAFE_AUTO
    )

    assert all(spec.evaluator_key for spec in safe)
    assert all(spec.candidate_generator_key for spec in safe)
    assert all(spec.latent_factor_kind for spec in safe)


def test_airpath_and_oa_constraints_are_admitted_with_complete_generators() -> None:
    specs = {spec.constraint_id: spec for spec in production_registry().specs}

    for constraint_id in (
        "V2-AIRPATH-TYPED-MEMBER-009",
        "V2-OA-EQUIPMENT-PATH-010",
    ):
        assert specs[constraint_id].admission_status is AdmissionStatus.ADMIT_SAFE_AUTO
        assert specs[constraint_id].candidate_generator_key == specs[constraint_id].evaluator_key
