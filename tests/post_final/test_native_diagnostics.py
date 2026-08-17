from tools.analysis.post_final_native_diagnostics import parse_err_messages


def test_parse_err_messages_keeps_severity_and_continuation_text() -> None:
    """Catch a parser that drops EnergyPlus continuation lines."""

    text = """Program Version,EnergyPlus, Version 24.1.0
   ** Warning ** Unrelated warning.
   ** Severe  ** Invalid Component Name="MISSING OA SYSTEM"
   **   ~~~   ** Entered in Branch="MAIN AIR LOOP BRANCH".
   **  Fatal  ** Errors found in getting input.
   ************* EnergyPlus Terminated--Fatal Error Detected.
"""

    messages = parse_err_messages(text)

    assert [(row.severity, row.text) for row in messages] == [
        ("WARNING", "Unrelated warning."),
        (
            "SEVERE",
            'Invalid Component Name="MISSING OA SYSTEM" '
            'Entered in Branch="MAIN AIR LOOP BRANCH".',
        ),
        ("FATAL", "Errors found in getting input."),
    ]


def test_parse_err_messages_does_not_promote_summary_lines() -> None:
    """Catch a parser that turns count summaries into new diagnostics."""

    text = """   ** Severe  ** Node Connection Error for object BRANCH.
   ************* There was 1 severe error; 0 warnings.
"""

    messages = parse_err_messages(text)

    assert len(messages) == 1
    assert messages[0].severity == "SEVERE"
    assert messages[0].text == "Node Connection Error for object BRANCH."
