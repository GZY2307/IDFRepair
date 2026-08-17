# Public Reproducibility Smoke

Status: `PASSED`

## Answer

The clean public candidate is installable, its selected public test suite passes,
and its compact Formal V2 headline metrics reproduce from the frozen evidence.
This smoke reads and validates the frozen result artifacts; it does not generate
new Final predictions, rescore Final100, or alter production repair semantics.

Candidate environment: macOS arm64, Python 3.12.1. Total recorded phase time was
12.399 seconds. Durations are diagnostic rather than performance claims.

## Phase record

| Phase | Result | Return code | Duration (s) | Key evidence |
|---|---:|---:|---:|---|
| Frozen metric reproduction | PASS | 0 | 0.035 | Formal V2 Final100 `81/100`; method-modified flag false |
| Selected public pytest | PASS | 0 | 6.261 | 189 passed |
| Compile package/tools/scripts/tests | PASS | 0 | 0.358 | No compile error |
| Build wheel without package dependencies | PASS | 0 | 2.662 | `idfrepair` wheel built |
| Create clean smoke environment | PASS | 0 | 1.867 | Environment created with available system packages |
| Install built wheel | PASS | 0 | 0.992 | Installed successfully |
| Import installed package | PASS | 0 | 0.086 | Package and frozen semantic namespace import |
| Run installed CLI help | PASS | 0 | 0.123 | CLI parser loads and lists commands |
| Git whitespace check | PASS | 0 | 0.015 | No diff error |

## Frozen metric output

| Metric | Reproduced value |
|---|---:|
| Formal V2 Final100 | 81/100 |
| Support | 78/95 |
| Conditional automatic repair | 66/66 |
| Overall automatic repair | 66/95 |
| Ambiguity handling | 10/10 |
| Wrong modification | 0 |
| Partial-as-full | 0 |
| Process failure | 0 |
| Non-target preservation | 95/95 |
| Joint vs Greedy contract | 81 vs 55 |
| Joint vs Greedy wrong modification | 0 vs 19 |
| Joint vs Greedy ambiguity | 10/10 vs 0/10 |

The reproduced method identity is
`3b9ad9447995f2b78313ca996a6a2ef2fa7711692054be184f470ea083f2928d`.

## Scope and limitations

The public smoke covers the publishable software and compact evidence. Raw DOE
models, private scoring material, raw terminal OSM files, weather, runtime
binaries, and simulation run directories are deliberately absent. Accordingly,
the repository publishes the controlled occupancy compiler, tests, protocol,
figures, and compact scenario results, but not a redistributable terminal model
or a claim that the airport case can be rerun without separately supplied model,
weather, OpenStudio, and EnergyPlus assets.

The release process repeats the same audit and smoke from a new clone of the
public GitHub repository. That post-push check is the final distribution-level
gate.
