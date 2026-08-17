# GitHub Public-Release Audit

Status: `PUBLIC_RELEASED`

## Decision

The allowlist-built release is public at
`https://github.com/GZY2307/IDFRepair`. Its Git history began from a new root;
no history or remote configuration was copied from the existing private
development repository. The historical `GZY2307/Test1` repository remained out
of scope and unchanged.

No secret, private-data, absolute-path, symlink, oversized-file, or oversized-tree
blocker was found in the qualified candidate or its complete reachable history.

## Target and identity checks

| Check | Result |
|---|---|
| GitHub account | Authenticated as `GZY2307` |
| Target repository before release | `GZY2307/IDFRepair` did not exist |
| Published repository | `https://github.com/GZY2307/IDFRepair` |
| Verified visibility | Public |
| Source history reused | No |
| Private development remote modified | No |
| Default branch | `main` |
| Content-qualified commit | `480e68ba484fccd79ea92c68043b40251a8cb3b1` |
| Distribution-qualified tag | `v1.0.1` |

## Qualified candidate

The final content qualification snapshot before this report-only closure contained
338 allowlisted source members, 11,812,913 bytes, and had content digest
`80fe15b4e7672c2afd2a5b625ba60e524525e4a5b8a5fae2af74e49700e7be16`.
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
| Fresh-history policy | PASS | New release-only root; no development history imported |
| GitHub fresh-clone audit | PASS | 0 tree/history findings at `v1.0.1` |

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

The GitHub fresh clone passed frozen-metric reproduction, 191 selected public tests,
bytecode compilation, wheel build, isolated wheel installation, installed-package
imports, installed CLI help, and Git whitespace validation. See
`reproducibility_smoke.md` for the phase record.

## Release closure

The content-qualified public distribution is commit `480e68b` / tag `v1.0.1`.
This final report/manifest closure is released as `v1.0.2`; it changes no repair,
occupancy, test, or frozen evidence content. Any later tree/history audit finding
remains release-blocking. Force push, history mirroring, and publication of the
raw terminal models are not authorized.
