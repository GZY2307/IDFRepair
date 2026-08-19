# Airport ABM V3 public-release staging audit

Status: **PASSED**

## Scope

The repository public-release builder was run from the explicit allowlist with
the frozen Formal V2 guard enabled. The resulting no-history staging tree
contains 505 regular files and 19,546,033 uncompressed bytes.

The separate lightweight Airport ABM V3 review archive contains 101 allowlisted
project files (103 ZIP members including its README and embedded manifest) and
is 956,628 compressed bytes.

## Security and distribution boundary

- Repository-tree audit: 0 blocking findings.
- Lightweight-package content audit: PASS.
- Raw or derived OSM/IDF: excluded.
- EPW, CAD, TIFF/PDF, raw EnergyPlus runs and agent-level records: excluded.
- Exact private room mapping and coordinates: excluded.
- Credentials, local user paths and symlinks: none detected.
- The two user-authored source OSM files remain private and read-only.

## V3 public contents

The staging tree contains the generic directed ABM engine, synthetic terminal
fixture, schedule compiler, public tests, aggregate reports, current figures,
and the integrated 3D occupancy viewer. It excludes superseded seasonal proxy
figures and the private model-audit integration test.

The public policy explicitly admits only the reviewed V3 report/figure/test
surface. Private directories and raw building/weather asset suffixes remain
denylisted.

## Commands

```bash
python -m tools.public_release.build_staging --destination <staging-tree>
python -m tools.public_release.audit --root <staging-tree>
pytest -q tests/airport_abm tests/public_release
```

Fresh-clone results are recorded separately after the staged branch is pushed.
