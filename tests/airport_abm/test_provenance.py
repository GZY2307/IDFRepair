from __future__ import annotations

import importlib

import pytest


def test_evidence_levels_cover_every_v3_claim_boundary() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.provenance")

    assert [level.value for level in module.EvidenceLevel] == [
        "MODEL_FACT",
        "OFFICIAL_PROCESS",
        "USER_SOURCE_ANNOTATION",
        "DRAWING_EVIDENCE",
        "CONTROLLED_NOT_MEASURED",
        "MODEL_BOUNDARY_EXIT",
    ]


def test_evidence_record_serializes_scope_and_negative_boundary() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.provenance")
    record = module.EvidenceRecord(
        evidence_id="official.international-arrival.level1",
        level=module.EvidenceLevel.OFFICIAL_PROCESS,
        reference="China Southern Daxing international arrival process",
        supports="Level-2 international corridor continues to Level 1 immigration",
        does_not_support="Using Level-2 domestic baggage claim",
    )

    assert record.to_dict() == {
        "evidence_id": "official.international-arrival.level1",
        "level": "OFFICIAL_PROCESS",
        "reference": "China Southern Daxing international arrival process",
        "supports": "Level-2 international corridor continues to Level 1 immigration",
        "does_not_support": "Using Level-2 domestic baggage claim",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_id", ""),
        ("reference", "   "),
        ("supports", ""),
        ("does_not_support", ""),
    ],
)
def test_evidence_record_rejects_an_unbounded_claim(field: str, value: str) -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.provenance")
    kwargs = {
        "evidence_id": "controlled.dwell.departure",
        "level": module.EvidenceLevel.CONTROLLED_NOT_MEASURED,
        "reference": "V3 pre-registered scenario protocol",
        "supports": "A controlled 30-120 minute departure waiting range",
        "does_not_support": "A measured Daxing dwell-time distribution",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=field):
        module.EvidenceRecord(**kwargs)
