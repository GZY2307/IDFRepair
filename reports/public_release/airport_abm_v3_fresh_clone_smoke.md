# Airport ABM V3 fresh-clone reproduction

Status: **PASSED**

Date: 2026-08-19

Remote branch: `codex/airport-abm-v3`

## Clean reproduction procedure

The pushed branch was cloned into a new temporary directory with depth 1. A
new Python 3.12 virtual environment was created outside the repository, and the
package plus its declared test extra were installed from `pyproject.toml`.

```bash
git clone --depth 1 --branch codex/airport-abm-v3 \
  git@github.com:GZY2307/IDFRepair.git <fresh-clone>
python -m venv <fresh-venv>
<fresh-venv>/bin/python -m pip install -e '.[test]'
```

## Results

```bash
<fresh-venv>/bin/python examples/airport_abm_v3/run_synthetic.py \
  --fixture examples/airport_abm_v3/synthetic_terminal.json
# status=PASS; spawned=5; terminal=5; active=0; violations=0

<fresh-venv>/bin/python -m pytest -q -p no:cacheprovider
# 387 passed in 26.63s

node --check src/idfrepair/web/static/app.js
node --check src/idfrepair/web/static/epshape-viewer.js
node --check src/idfrepair/web/static/occupancy-viewer-state.js
node --check src/idfrepair/web/static/viewer-bridge.js
# all passed

<fresh-venv>/bin/python -m tools.public_release.audit \
  --root . --include-git-history
# status=PASSED; blocking_count=0
```

The final repository worktree was clean after removing only generated editable
install metadata. No OSM, IDF, EPW, CAD/TIFF, ZIP, raw EnergyPlus output, local
user path, credential, or symlink was present.

## Reproduction boundary

The fresh clone reproduces the generic directed ABM engine, synthetic fixture,
schedule compiler, public viewer contracts, report calculations, package
policy, and security tests. It intentionally cannot reproduce the private
terminal geometry, exact room mapping, derived People models, weather runs, or
raw EnergyPlus simulations. Those results are represented only by audited
aggregate reports, and the paper-admission decision remains demo-only.
