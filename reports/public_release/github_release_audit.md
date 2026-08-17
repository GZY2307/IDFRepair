# GitHub Public-Release Audit

Status: `READY_FOR_PUBLIC_PUSH`

## Decision

The release candidate is eligible for a new public repository at
`GZY2307/IDFRepair`. It is an allowlist-built tree with a fresh one-commit Git
history; no history or remote configuration is copied from the existing private
development repository. The historical `GZY2307/Test1` repository is out of
scope and remains unchanged.

No secret, private-data, absolute-path, symlink, oversized-file, or oversized-tree
blocker was found in the qualified candidate or its complete reachable history.

## Target and identity checks

| Check | Result |
|---|---|
| GitHub account | Authenticated as `GZY2307` |
| Target repository before release | `GZY2307/IDFRepair` did not exist |
| Required visibility | Public |
| Source history reused | No |
| Private development remote modified | No |
| Default branch | `main` |

## Qualified candidate

The pre-report qualification snapshot contained 335 allowlisted source members,
11,804,224 bytes, and had content digest
`94c50a29a5340fe5d9106444514d8fd573b7ca1d57a35ece1b714c3e057306a4`.
The generated `public_manifest.json` is the authoritative inventory for the final
candidate, including these audit reports.

The public tree contains package source, selected tests, reproducibility tools,
compact frozen evidence, occupancy analysis code, scenario summaries, and paper
readiness documentation. It intentionally excludes the two user-authored terminal
OSM source models.

## Security and privacy gates

| Gate | Result | Evidence |
|---|---:|---|
| Explicit path allowlist | PASS | Every staged member is accepted by `tools/public_release/policy.py` |
| Frozen evidence guard | PASS | All protected source and Final evidence hashes match |
| Tree secret scan | PASS | 0 findings |
| Reachable-history secret scan | PASS | 0 findings |
| Local absolute-path scan | PASS | 0 findings |
| Symlink scan | PASS | 0 findings |
| Maximum file size | PASS | No file exceeds 10 MiB |
| Maximum tree size | PASS | Candidate remains below 50 MiB |
| Fresh-history policy | PASS | New root commit only; no development history imported |

The credential scanner covers high-risk credential assignments, common provider
token formats, and private-key material without echoing matched values. Domain
identifiers such as zone lookup keys and parser tokens are not treated as
credentials.

## Explicit exclusions

- raw terminal OSM files and all unreviewed IDF inputs;
- raw weather and EnergyPlus output files;
- DOE raw models, private oracle/scorer material, server configuration, and
  credential files;
- runtime binaries, model weights, caches, virtual environments, raw run trees,
  literature PDFs, archives, and Git bundles.

The source-code package `src/idfrepair/models/` is included because it contains
Python integration code, not model data. Repository-root `models/` remains
blocked, and model/weight suffixes remain blocked globally.

## Reproducibility gate

The candidate passed frozen-metric reproduction, 191 selected public tests,
bytecode compilation, wheel build, isolated wheel installation, installed-package
imports, installed CLI help, and Git whitespace validation. See
`reproducibility_smoke.md` for the phase record.

## Release condition

The candidate may be pushed only to the newly created `GZY2307/IDFRepair`
repository. Any later tree/history audit finding is release-blocking. Force push,
history mirroring, and publication of the raw terminal models are not authorized.
