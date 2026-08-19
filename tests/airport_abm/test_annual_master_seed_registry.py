import pytest

from idfrepair.analysis.airport_abm.v31 import (
    ANNUAL_MASTER_SEED,
    annual_case_identities,
    require_annual_master_seed,
)


def test_annual_registry_has_source_static_plus_five_dynamic_cases() -> None:
    rows = annual_case_identities()

    assert ANNUAL_MASTER_SEED == 40015
    assert len(rows) == 6
    assert rows[0].scenario_id == "SOURCE_STATIC"
    assert rows[0].seed is None
    assert {row.seed for row in rows[1:]} == {40015}


def test_annual_registry_rejects_post_result_seed_substitution() -> None:
    with pytest.raises(ValueError, match="master seed"):
        require_annual_master_seed(40027)
