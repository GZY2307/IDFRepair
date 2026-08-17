# Room-aware Public-Release Staging Audit

Status: `PASSED_LOCAL_FRESH_HISTORY`

## Scope

This addendum qualifies the Room-aware Airport Occupancy extension for the existing
IDFRepair public-release policy. It does not claim that this candidate has been pushed
to GitHub. The private development repository and its remotes were not modified.

## Qualified pre-closure candidate

| Check | Result |
|---|---:|
| Allowlisted source members | 408 |
| Generated manifest included in Git tree | 1 |
| Total allowlisted bytes | 17,592,752 |
| Content snapshot SHA-256 | `7c955c3626c86b2b65ddc64beded268438cbb7f8ec5ef7f987dde82c3ff7d8c0` |
| Fresh root commit | `f7f90c020987d9afcefd26edd79709181e962ecf` |
| Candidate tree findings | 0 |
| Complete reachable-history findings | 0 |
| Symlinks | 0 |
| Raw terminal OSM / IDF / EPW | 0 |

The allowlist now includes the room-aware source, tests, protocols, compact reports,
figures and local-viewer code. It still excludes raw OSM models, derived IDFs, weather,
construction drawings, EnergyPlus run trees, credentials and private development
history. Generated `*.egg-info` / `*.dist-info` metadata is also excluded so wheel
installation is exercised from the built artifact rather than a source-tree residue.
Formal V2/Final100 files are accepted only after the existing frozen-hash guard passes.

The generated `public_manifest.json` remains the authoritative inventory for the
closure candidate; the numbers above describe the independently audited pre-closure
snapshot used to establish the fresh-history gate.
