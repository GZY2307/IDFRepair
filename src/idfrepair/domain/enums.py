"""Finite public enumerations for the repair protocol."""

from enum import Enum


class TextEnum(str, Enum):
    """A Python 3.10-compatible string enumeration."""

    def __str__(self) -> str:
        return self.value


class RepairStatus(TextEnum):
    VALID = "VALID"
    REPAIRED = "REPAIRED"
    NEEDS_INPUT = "NEEDS_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"
    PROCESS_FAILED = "PROCESS_FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    LIMIT_REACHED = "LIMIT_REACHED"


class RepairMode(TextEnum):
    ANALYZE_ONLY = "analyze-only"
    SAFE_AUTO = "safe-auto"
    ASSISTED = "assisted"
    INTERACTIVE = "interactive"


class RiskLevel(TextEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def order(self) -> int:
        return {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}[self]


class Provenance(TextEnum):
    DETERMINISTIC = "DETERMINISTIC"
    RETRIEVAL = "RETRIEVAL"
    MODEL_PROPOSED = "MODEL_PROPOSED"
    USER_SELECTED = "USER_SELECTED"
    USER_SUPPLIED = "USER_SUPPLIED"


class OperationKind(TextEnum):
    INSERT_DELIMITER = "insert_delimiter"
    REPLACE_FIELD = "replace_field"
    INSERT_FIELD = "insert_field"
    DELETE_FIELD = "delete_field"
    RENAME_REFERENCE = "rename_reference"
    REPLACE_VERTICES = "replace_vertices"
    INSERT_OBJECT = "insert_object"
    DELETE_OBJECT = "delete_object"
    REPLACE_OBJECT = "replace_object"
    UPDATE_VERSION = "update_version"


class QuestionType(TextEnum):
    CHOOSE_CANDIDATE = "choose_candidate"
    ENTER_FIELD_VALUE = "enter_field_value"
    CHOOSE_REFERENCE = "choose_reference"
    CHOOSE_OBJECT = "choose_object"
    CONFIRM_VERSION = "confirm_version"
    PROVIDE_EXTERNAL_FILE = "provide_external_file"
    CONFIRM_GEOMETRY = "confirm_geometry"
    SELECT_REPAIR_FAMILY = "select_repair_family"


class ValidationStage(TextEnum):
    STATIC = "static"
    SEMANTIC = "semantic"
    ENERGYPLUS = "energyplus"
    TRANSITION = "transition"
    FINAL = "final"
