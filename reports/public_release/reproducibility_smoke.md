# Public Reproducibility Smoke

Status: `PASSED_GITHUB_FRESH_CLONE`

## Answer

The GitHub fresh clone at Room-aware content commit
`7ae88ea87a1c2290891cfd28f55d47da04582535` is installable, its selected public test
suite passes, and the compact Formal V2 headline metrics reproduce from frozen
evidence. The smoke did not generate new Final predictions, rescore Final100, or alter
production repair semantics.

Fresh-clone environment: macOS arm64, Python 3.12.1. Total recorded phase time was
46.367 seconds. Durations are diagnostic rather than performance claims.

## Phase record

| Phase | Result | Return code | Duration (s) | Key evidence |
|---|---:|---:|---:|---|
| Frozen metric reproduction | PASS | 0 | 0.074 | Formal V2 Final100 `81/100`; method-modified flag false |
| Selected public pytest | PASS | 0 | 25.547 | 288 passed, including room-aware and distribution invariants |
| Compile package/tools/scripts/tests | PASS | 0 | 0.620 | No compile error |
| Build wheel without package dependencies | PASS | 0 | 14.142 | `idfrepair` wheel built |
| Create clean smoke environment | PASS | 0 | 3.370 | Environment created outside the repository |
| Install built wheel | PASS | 0 | 2.214 | Installed successfully from the built wheel |
| Import installed package | PASS | 0 | 0.148 | Package and frozen semantic namespace import |
| Run installed CLI help | PASS | 0 | 0.224 | CLI parser loads and lists commands |
| Git whitespace check | PASS | 0 | 0.028 | No diff error |

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

The public smoke covers publishable software and compact evidence. Raw terminal OSM,
weather, construction drawings, runtime binaries and simulation run directories are
deliberately absent. Re-running the private airport case therefore requires separately
supplied model, weather, OpenStudio and EnergyPlus assets.

## Distribution-level check

A GitHub fresh clone resolved to `7ae88ea`; its complete reachable history and tree had
zero findings and all nine smoke phases passed. Anonymous HTTPS Git access then
resolved the same `HEAD` and the annotated `v1.1.0` tag. The subsequent `v1.1.1` tag
adds only the closed audit record and regenerated manifest.
