# Room-aware Fresh-Clone Reproducibility Smoke

Status: `PASSED_LOCAL_FRESH_CLONE`

The local fresh clone of the allowlist-built, single-root public candidate passed all
nine smoke phases. No raw private terminal asset was supplied to or required by this
smoke. The audited local root was
`f7f90c020987d9afcefd26edd79709181e962ecf`.

| Phase | Result | Evidence |
|---|---:|---|
| Frozen metric reproduction | PASS | Formal V2 Final100 `81/100`; scoring runs `1`; method-modified flag `false` |
| Selected public pytest | PASS | `288 passed` |
| Bytecode compilation | PASS | package, tools, scripts and tests compiled |
| Wheel build | PASS | `idfrepair-1.0.0` built without package dependencies |
| Clean environment creation | PASS | isolated smoke environment created |
| Wheel installation | PASS | built wheel installed |
| Installed import | PASS | `idfrepair` and `idfrepair.semantic_graph_v2` imported |
| Installed CLI | PASS | `idfrepair --help` completed |
| Git whitespace gate | PASS | `git diff --check` returned zero |

The tree plus complete reachable-history sensitive-information audit was executed
before the smoke mutated the clone with build caches and returned zero findings. The
Room-aware tests cover source-backed classification, source byte preservation,
People-only derivatives, S/R provenance, person-hour conservation, output
reconciliation, interval timestamp semantics, 3D payload mapping, paper admission and
atomic review packaging.

The smoke ran outside the private repository tree with no inherited `PYTHONPATH`.
This prevents a parent `.gitignore` or local `src/idfrepair.egg-info` from making an
apparently clean install pass for the wrong reason.

This is a code/evidence reproducibility gate, not a redistributable terminal-model
simulation. Re-running the private airport case still requires separately supplied
OSM, weather, OpenStudio and EnergyPlus assets.
