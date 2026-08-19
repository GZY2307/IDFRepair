from __future__ import annotations

import pytest

from idfrepair.analysis.airport_abm.v31 import person_hour_conservation


def test_public_and_staff_conservation_uses_independent_relative_errors() -> None:
    audit = person_hour_conservation(
        target_public=1000.0,
        actual_public=1000.0 + 5.0e-7,
        target_staff=200.0,
        actual_staff=200.0 - 1.0e-7,
        relative_tolerance=1.0e-8,
    )

    assert audit.status == "PASS"
    assert audit.public_relative_error == pytest.approx(5.0e-10)
    assert audit.staff_relative_error == pytest.approx(5.0e-10)


def test_conservation_fails_when_only_one_cohort_exceeds_tolerance() -> None:
    audit = person_hour_conservation(
        target_public=1000.0,
        actual_public=1000.00002,
        target_staff=200.0,
        actual_staff=200.0,
        relative_tolerance=1.0e-8,
    )

    assert audit.status == "FAIL"
    assert audit.public_relative_error == pytest.approx(2.0e-8)
    assert audit.staff_relative_error == 0.0
