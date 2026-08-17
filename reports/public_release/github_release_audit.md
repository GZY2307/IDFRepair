# GitHub Public-Release Audit

Status: `PUBLIC_RELEASED`

## Decision

The allowlist-built Room-aware release is public at
`https://github.com/GZY2307/IDFRepair`. The repository retains only its prior
public-release root and public-only follow-up commits; no history or remote
configuration was copied from the private development repository. The historical
`GZY2307/Test1` repository remained out of scope and unchanged.

The repository was unexpectedly `PRIVATE` before this update. Its existing complete
reachable history was audited first with zero findings, the new candidate was pushed
and independently fresh-cloned, and only then was visibility restored to `PUBLIC`.

## Target and identity checks

| Check | Result |
|---|---|
| GitHub account | Authenticated as `GZY2307` |
| Published repository | `https://github.com/GZY2307/IDFRepair` |
| Verified visibility | Public; anonymous HTTPS Git access succeeded |
| Private development history reused | No |
| Prior public-only history retained | Yes |
| Private development remote modified | No |
| Default branch | `main` |
| Room-aware content-qualified commit | `7ae88ea87a1c2290891cfd28f55d47da04582535` |
| Room-aware content-qualified tag | `v1.1.0` |

## Qualified candidate

The final content candidate before the report-only closure contained 408 allowlisted
source members, 17,593,250 bytes, and content digest
`f2190313a57dcf217fe8180b78b81342e76543db339c762aa54c494ddf6bdef2`.
The generated `public_manifest.json` is the authoritative inventory.

The public tree contains package source, selected tests, reproducibility tools,
compact frozen evidence, room-aware occupancy analysis code, coordinate-free entrance
mapping, scenario summaries, figures and paper-readiness documentation. It
intentionally excludes both user-authored terminal OSM source models.

## Security and privacy gates

| Gate | Result | Evidence |
|---|---:|---|
| Explicit path allowlist | PASS | Every staged member is accepted by `tools/public_release/policy.py` |
| Frozen evidence guard | PASS | All protected source and Final evidence hashes match |
| Tree secret scan | PASS | 0 findings |
| Reachable-history secret scan | PASS | 0 findings across all four content commits |
| Local absolute-path scan | PASS | 0 findings |
| Symlink scan | PASS | 0 findings |
| Maximum file size | PASS | No file exceeds 10 MiB |
| Maximum tree size | PASS | Candidate remains below 50 MiB |
| Public-only history policy | PASS | Existing release-only root retained; no development history imported |
| GitHub fresh-clone audit | PASS | 0 tree/history findings at `v1.1.0` |

Generated `*.egg-info` / `*.dist-info`, test caches and wheel build trees are blocked
from staging. The credential scanner covers high-risk assignments, common provider
token formats and private-key material without echoing matched values.

## Explicit exclusions

- raw terminal OSM files and all unreviewed IDF inputs;
- raw weather and EnergyPlus output files;
- construction drawings, private oracle/scorer material, server configuration and
  credential files;
- runtime binaries, model weights, caches, virtual environments, raw run trees,
  literature PDFs, archives and Git bundles.

The source-code package `src/idfrepair/models/` is included because it contains Python
integration code, not model data. Repository-root `models/` remains blocked.

## Reproducibility gate

The GitHub fresh clone passed frozen-metric reproduction, 288 selected public tests,
bytecode compilation, wheel build, isolated wheel installation, installed-package
imports, installed CLI help and Git whitespace validation. Formal V2/Final100 was
read and verified only; it was not regenerated or rescored.

## Release closure

The Room-aware content release is commit `7ae88ea` / tag `v1.1.0`. The subsequent
`v1.1.1` tag adds only this closed audit report, the refreshed reproducibility record
and regenerated public manifest. Force push, private-history mirroring and publication
of the raw terminal models remain prohibited.
