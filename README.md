# IDFRepair

IDFRepair is a recoverability-aware semantic debugging and deterministic repair
framework for existing EnergyPlus IDF models. It projects version-bound HVAC
relations into a typed semantic representation, detects cross-object structural
inconsistencies, and applies bounded minimum semantic edits only when the
repair is uniquely supported by internal model evidence.

[中文说明](README_zh.md)

## Frozen Formal V2 result

Formal V2 was frozen before its one-shot Final100 evaluation. The method,
membership, predictions, and scores are read-only; this public release does not
rerun or tune Final.

| Metric | Frozen result |
|---|---:|
| Formal V2 Final100 contract | **81/100** |
| Supported repair targets | **78/95** |
| Conditional automatic repair | **66/66** |
| Overall automatic repair | **66/95** |
| Ambiguity decisions | **10/10** |
| Wrong modifications | **0** |
| Partial repairs reported complete | **0** |
| Process failures | **0** |
| Non-target preservation | **95/95** |

The frozen Joint solver and Greedy comparison separate recovery from unsafe
commit behavior:

| Comparison | Joint | Greedy |
|---|---:|---:|
| Contract-correct decisions | **81** | 55 |
| Wrong modifications | **0** | 19 |
| Ambiguity contract | **10/10** | 0/10 |

These are benchmark-scoped results, not a claim that arbitrary IDF errors are
automatically recoverable. EnergyPlus execution validates a committed artifact;
it is not used as a semantic oracle during repair.

## Method

The frozen pipeline is:

```text
existing IDF + exact IDD
  -> version-bound typed ports and compound-flow relations
  -> target-free whole-model constraint scan
  -> complete finite semantic edit domains
  -> conflict-component joint minimum search
  -> unique-optimum gate or safe abstention
  -> guarded source-span write-back
  -> global semantic closure
  -> separate EnergyPlus execution validation
```

The supported relation frontier covers Branch paths, Loop/Connector structure,
Zone equipment ownership, AirPath relations, and OutdoorAir equipment paths.
Unsupported, incomplete, truncated, or equally optimal interpretations are not
silently committed.

## Installation

Python 3.10 or newer is required. EnergyPlus is an external dependency and is
not downloaded or bundled by this repository.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

## Minimal semantic diagnosis and repair

Bind the IDF to the exact EnergyPlus IDD used by that model:

```python
from pathlib import Path

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import repair_model, scan_model

idf_text = Path("model.idf").read_text(encoding="utf-8-sig")
idd = parse_idd(Path("/path/to/Energy+.idd").read_text(encoding="utf-8"))
document = parse_idf(idf_text)

diagnosis = scan_model(document, idd)
outcome = repair_model(idf_text, idd)
print(diagnosis.violations)
print(outcome.status, outcome.output_text)
```

The API accepts only the current IDF and exact IDD. It does not accept a clean
target, mutation family, locator, private oracle, or expected edit.

## Reproduce the headline metrics

This command reads the frozen result and guard files. It does not import the
repair runtime, generate predictions, or score a new Final:

```bash
python scripts/public_reproduce_formal_v2.py
python scripts/public_reproduce_formal_v2.py --json
```

## Tests

```bash
python -m pytest -q
python -m compileall -q src tools scripts tests
git diff --check
```

See [public reproducibility](docs/reproducibility/public_release.md) for the
version boundary, public benchmark construction, security gates, and
fresh-clone procedure.

## Airport occupancy extension

The occupancy namespace is a downstream analysis workflow, not a new repair
method. It extracts People→Zone→HVAC relations, generates deterministic
15-minute scenarios, and compares temporal and spatial redistribution while
holding passenger-hours constant. Volume sensitivity is reported separately.
The two user-authored terminal OSM source files and all raw derivatives remain
private and are represented publicly only by aggregate inventories and hashes.

## Repository map

- `src/idfrepair/semantic_graph_v2/`: frozen semantic projection and repair.
- `src/idfrepair/analysis/occupancy/`: isolated downstream occupancy analysis.
- `tests/`: unit, safety, frozen-regression, and reproduction tests.
- `scripts/`: public metric and occupancy entry points.
- `docs/research/`: method identity, claim boundary, and occupancy research.
- `datasets/manifests/`: source URLs, fingerprints, and qualification metadata;
  no raw DOE models are redistributed.
- `reports/`: compact frozen and downstream evidence.

## Scope and citation

The defensible contribution is the EnergyPlus-specific composition of
version-bound semantic projection, IDF-internal evidence, bounded joint minimum
repair, uniqueness-aware safe abstention, guarded exact write-back, and global
closure. It is not the first HVAC knowledge graph, general graph repair method,
or automated EnergyPlus model generator.

Citation metadata are provided in [CITATION.cff](CITATION.cff). The code is
available under the [MIT License](LICENSE). Third-party EnergyPlus and DOE
assets retain their own licenses and are not bundled here.
