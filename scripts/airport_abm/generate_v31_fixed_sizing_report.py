#!/usr/bin/env python3
"""Publish an aggregate, model-value-free Airport ABM V3.1 sizing audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.fixed_sizing import (  # noqa: E402
    evaluate_fixed_sizing_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-audit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sizing-warning-count", required=True, type=int)
    parser.add_argument("--sizing-severe-count", required=True, type=int)
    parser.add_argument("--sizing-fatal-count", required=True, type=int)
    args = parser.parse_args()

    private = json.loads(Path(args.private_audit).read_text(encoding="utf-8"))
    decision = evaluate_fixed_sizing_audit(private)
    public = {
        "schema_version": "idfrepair.airport-fixed-sizing-public-audit.v31",
        "status": decision.status,
        "source_static_sizing": {
            "completed": args.sizing_severe_count == 0 and args.sizing_fatal_count == 0,
            "warning_count": args.sizing_warning_count,
            "severe_count": args.sizing_severe_count,
            "fatal_count": args.sizing_fatal_count,
        },
        "source_unchanged": bool(private["source_unchanged"]),
        "protected_objects_unchanged": bool(
            private["protected_objects_unchanged"]
        ),
        "autosizable_fields_before": int(private["autosizable_fields_before"]),
        "autosized_values_available": int(private["autosized_values_available"]),
        "values_applied": int(private["values_applied"]),
        "autosizable_fields_unresolved": int(
            private["autosizable_fields_unresolved"]
        ),
        "unresolved_critical_fields": decision.unresolved_critical_fields,
        "categories": private["categories"],
        "object_types": private["object_types"],
        "unresolved_fields": private.get("unresolved_fields", []),
        "forward_translation_warning_count": int(
            private["forward_translation_warning_count"]
        ),
        "forward_translation_error_count": int(
            private["forward_translation_error_count"]
        ),
        "decision_reasons": list(decision.reasons),
        "claim_boundary": "DESIGN_SIZING_SENSITIVITY_NOT_FIXED_OPERATION",
        "private_values_included": False,
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "fixed_sizing_audit.json").write_text(
        json.dumps(public, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Airport Occupancy V3.1 — Fixed-sizing completeness audit",
        "",
        f"Hard-gate status: `{decision.status}`",
        "",
        "The source-static model was sized once and OpenStudio `Model::applySizingValues()` was evaluated on a separate model copy. A second fresh source copy received only values for fields that were originally autosized; the original source remained read-only and topology, controls, schedules, constructions, and loads were unchanged.",
        "",
        f"The sizing run completed with {args.sizing_warning_count} warnings, {args.sizing_severe_count} Severe errors, and {args.sizing_fatal_count} Fatal errors. Of {public['autosizable_fields_before']:,} originally autosized fields, {public['values_applied']:,} received explicit sizing values and {public['autosizable_fields_unresolved']:,} remained unresolved.",
        "",
        "| Category | Before | Available | Applied | Unresolved |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, row in sorted(public["categories"].items()):
        lines.append(
            f"| {category} | {row['before']:,} | {row['available']:,} | {row['applied']:,} | {row['unresolved']:,} |"
        )
    lines.extend(
        [
            "",
            "## Unresolved fields",
            "",
            "| Object type | Field predicate | Count |",
            "|---|---|---:|",
        ]
    )
    for row in public["unresolved_fields"]:
        lines.append(
            f"| {row['object_type']} | `{row['field']}` | {row['count']:,} |"
        )
    lines.extend(
        [
            "",
            "The unresolved water-coil-controller maximum actuated flow fields are critical flow fields. The comparison therefore fails the fixed-operation hard gate. Any downstream run made from the partial reference is reported only as design/sizing sensitivity, not as a fixed installed-HVAC operational response. No missing values were guessed or written merely to pass the gate.",
            "",
            "This public audit contains counts and field identities only. It excludes the source model, sizing SQL, explicit equipment values, room mapping, coordinates, IDF, and weather file.",
            "",
        ]
    )
    (output / "fixed_sizing_audit.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps({"status": decision.status, "output_dir": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
