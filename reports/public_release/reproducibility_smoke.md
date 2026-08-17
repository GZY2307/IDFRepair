# Public Reproducibility Smoke

Status: `PASSED_GITHUB_FRESH_CLONE`

## Answer

The clean public candidate is installable, its selected public test suite passes,
and its compact Formal V2 headline metrics reproduce from the frozen evidence.
This smoke reads and validates the frozen result artifacts; it does not generate
new Final predictions, rescore Final100, or alter production repair semantics.

Fresh-clone environment: macOS arm64, Python 3.12.1. Total recorded phase time
was 12.810 seconds. Durations are diagnostic rather than performance claims.

## Phase record

| Phase | Result | Return code | Duration (s) | Key evidence |
|---|---:|---:|---:|---|
| Frozen metric reproduction | PASS | 0 | 0.032 | Formal V2 Final100 `81/100`; method-modified flag false |
| Selected public pytest | PASS | 0 | 6.591 | 191 passed, including Git-ignore and byte-preservation distribution invariants |
| Compile package/tools/scripts/tests | PASS | 0 | 0.365 | No compile error |
| Build wheel without package dependencies | PASS | 0 | 2.679 | `idfrepair` wheel built |
| Create clean smoke environment | PASS | 0 | 1.867 | Environment created with available system packages |
| Install built wheel | PASS | 0 | 1.026 | Installed successfully |
| Import installed package | PASS | 0 | 0.085 | Package and frozen semantic namespace import |
| Run installed CLI help | PASS | 0 | 0.136 | CLI parser loads and lists commands |
| Git whitespace check | PASS | 0 | 0.029 | No diff error |

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

## Distribution-level check

An HTTPS clone of public tag `v1.0.1` resolved to commit
`480e68ba484fccd79ea92c68043b40251a8cb3b1`. The fresh clone contained both
release commits, passed the full tree and reachable-history audit with zero
findings, and passed all nine smoke phases listed above. The subsequent
`v1.0.2` tag adds only this closed audit report and its regenerated manifest.
