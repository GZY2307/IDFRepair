# Reproducibility

The active public result is the frozen Formal V2 Final100 evaluation. The
repair method, Final membership, predictions, certificates, and score are
read-only. Reproduction in this release means validating frozen identities,
rebuilding public metadata, running tests, and exercising the public API; it
does not mean running a second Final.

## Environment

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

Python 3.10 or newer is required. EnergyPlus is optional for unit tests and is
never bundled. Dynamic validation requires an official executable and the
exact IDD matching the tested IDF version.

## Frozen headline

```bash
python scripts/public_reproduce_formal_v2.py --json
```

The command reads only `reports/semantic_graph_final/main_results.json` and
`reports/post_final/frozen_evidence_guard.json`. It verifies that the method was
not changed after Final and reports the frozen counts without importing the
repair runtime.

## Validation

```bash
python -m pytest -q
python -m compileall -q src tools scripts tests
git diff --check
```

The release audit additionally scans secrets, large files, local absolute
paths, forbidden raw assets, symlinks, and fresh Git history. A fresh clone is
installed and tested without access to the source worktree.

## External data

DOE prototype models and weather data are retrieved from their official source
URLs. This repository provides manifests, topology fingerprints, and
qualification procedures rather than redistributing raw models or EPW files.

The user-authored terminal OSM inputs used by the occupancy feasibility study
are not distributed. Public occupancy reports contain only non-reversible
aggregate counts, hashes, assumptions, and scenario results.

See [the detailed public-release protocol](docs/reproducibility/public_release.md).
