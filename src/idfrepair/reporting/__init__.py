"""Stable JSON reports for CLI, API, and evaluation consumers."""

from idfrepair.reporting.schema import REPORT_SCHEMA_VERSION, validate_report
from idfrepair.reporting.session_report import build_session_report, write_session_report

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "build_session_report",
    "validate_report",
    "write_session_report",
]
