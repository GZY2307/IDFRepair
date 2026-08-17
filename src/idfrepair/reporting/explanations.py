"""Short user-facing explanations for terminal outcomes and rejections."""

from __future__ import annotations

from idfrepair.domain.enums import RepairStatus


STATUS_EXPLANATIONS = {
    RepairStatus.VALID: "The input completed EnergyPlus validation without an actionable error root.",
    RepairStatus.REPAIRED: "Every committed repair passed the configured validation chain and the final run passed.",
    RepairStatus.NEEDS_INPUT: "The intended change cannot be identified safely without a user decision.",
    RepairStatus.UNSUPPORTED: "No provider could create a safe finite candidate for the selected root.",
    RepairStatus.SEARCH_EXHAUSTED: "Every bounded candidate path was rejected and the original bytes were restored.",
    RepairStatus.PROCESS_FAILED: "EnergyPlus did not complete as a process; no modification was committed.",
    RepairStatus.ROLLED_BACK: "The transaction was rolled back to the original input.",
    RepairStatus.LIMIT_REACHED: "A configured search limit was reached and the original bytes were restored.",
}


def explain_status(status: RepairStatus) -> str:
    return STATUS_EXPLANATIONS[status]
