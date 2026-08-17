"""Immutable state construction."""

from __future__ import annotations

from idfrepair.diagnostics.roots import build_roots
from idfrepair.domain.models import EnergyPlusResult, RepairState
from idfrepair.io.idf import parse_idf, text_sha256


def make_state(
    text: str,
    result: EnergyPlusResult,
    *,
    round_index: int,
) -> RepairState:
    document = parse_idf(text)
    return RepairState(
        text=text,
        sha256=text_sha256(text),
        version=document.version,
        diagnostics=build_roots(result.diagnostics),
        energyplus_result=result,
        round_index=round_index,
    )
