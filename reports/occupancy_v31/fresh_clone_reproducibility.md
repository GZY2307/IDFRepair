# Airport Occupancy V3.1 — Fresh-Clone Reproducibility

Status: `PASS_PUBLIC_STAGING_TREE`

The existing `codex/airport-abm-v3` branch was cloned into an empty temporary
directory before any V3.1 file was staged. Only the explicit V3.1 public
allowlist was overlaid; no private model, weather, SQL, mapping, agent record,
or workstation path was copied.

Validation in that isolated tree:

| Check | Result |
|---|---|
| Full available pytest suite | 418 passed, 3 skipped |
| Airport ABM plus public-release subset | 163 passed, 3 skipped |
| Synthetic five-agent-class ABM | PASS; 5 spawned, 5 terminal, 0 active, 0 violations |
| Python compilation | PASS |
| Whitespace/error-marker diff check | PASS |
| V3.1 review package allowlist/content/archive audit | PASS |
| Review package members | 63 allowlisted public files |

The three skips are integration checks that require authorized private source
inputs. They are controlled by environment variables and do not embed local
paths. The synthetic/public suite exercises normalization, conservation,
capacity reporting, fixed-sizing audit logic, no-clipping/no-resizing gates,
seasonal registries, paired statistics, historical V3 preservation, and review
packaging without private data.

This is a public-code reproducibility check. It does not reproduce the private
EnergyPlus matrix because the source model and weather are intentionally not
distributed.
