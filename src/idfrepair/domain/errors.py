"""Typed errors raised at public trust boundaries."""


class IDFRepairError(Exception):
    """Base class for expected engine errors."""


class InputFormatError(IDFRepairError):
    """The IDF or supporting asset cannot be parsed safely."""


class CandidateContractError(IDFRepairError):
    """A candidate violates the finite patch contract."""


class CandidateApplicationError(IDFRepairError):
    """A valid-looking candidate cannot be applied to its bound state."""


class RuntimeDiscoveryError(IDFRepairError):
    """No matching EnergyPlus runtime can be selected."""


class RuntimeProcessError(IDFRepairError):
    """EnergyPlus could not execute as a process."""


class SessionStateError(IDFRepairError):
    """A session transition or answer is invalid."""


class ModelContractError(IDFRepairError):
    """A model response or tool request violates its strict schema."""
