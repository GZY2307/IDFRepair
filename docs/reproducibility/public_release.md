# Public release reproducibility protocol

## Scope

This protocol reproduces the public software package, frozen headline summary,
tests, and fresh-clone smoke. It never runs Formal V2 inference or scoring and
never constructs a replacement Final dataset.

## Supported environment

- Python 3.10 or newer.
- EnergyPlus 24.1 for the frozen Final dynamic-validation boundary.
- EnergyPlus 22.1 and 24.1 exact IDDs for the audited compound-flow projection
  rules.
- OpenStudio and EnergyPlus binaries are external and are not stored in Git.

Create an isolated environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

## Frozen evidence verification

Print the compact result directly from frozen evidence:

```bash
python scripts/public_reproduce_formal_v2.py
python scripts/public_reproduce_formal_v2.py --json
```

Expected headline values are Formal V2 Final100 `81/100`, support `78/95`,
conditional automatic repair `66/66`, and overall automatic repair `66/95`.
The same summary verifies zero wrong modifications, zero partial-as-full, zero
process failures, and `95/95` non-target preservation.

## Minimal API smoke

Use a small redistributable IDF and the exact official IDD for its declared
EnergyPlus version. The public `scan_model` and `repair_model` functions accept
no target model, record ID, mutation family, locator, or expected edit.

```bash
python -m pytest -q tests/semantic_graph_v2/test_runtime.py \
  tests/semantic_graph_v2/test_scanner.py
```

## Full public checks

```bash
python -m pytest -q
python -m compileall -q src tools scripts tests
git diff --check
python -m tools.public_release.audit --root . --include-git-history
```

The audit rejects credentials, server configuration, private-oracle payloads,
raw terminal or DOE models, EPW files, EnergyPlus outputs, binaries, model
weights, literature PDFs, local absolute paths, symlinks, files over 10 MB, and
trees over 50 MB.

## Public benchmark material

Raw DOE prototype IDFs are not copied into the repository. The public material
records official retrieval URLs, source identities, version qualification,
topology fingerprints, fault-operator definitions, and compact frozen result
summaries. This is sufficient to inspect membership and methodology without
redistributing upstream models under an assumed license.

## Fresh-clone gate

The release is created from an allowlist in a new Git object database. A local
clone and then a GitHub clone must each pass installation, imports, unit tests,
compileall, frozen metric reproduction, secret/path/size scans, and Git diff
checks. The private development repository and its historical remote are not
present in either clone.

## Occupancy boundary

The airport occupancy workflow is downstream analysis. It receives explicit
local model paths at runtime, writes only derived copies, and publishes no raw
OSM, IDF, EPW, or simulation workspace. Same-passenger-hours scenarios use a
15-minute resolution; volume sensitivity is reported separately.
