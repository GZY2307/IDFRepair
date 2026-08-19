# Airport Occupancy V3.1 — Scientific Gap Audit

Status: `GAPS_REGISTERED_BEFORE_LONG_ENERGYPLUS_RUNS`

## Frozen V3 evidence

The historical V3 matrix remains 20 scenarios × 30 seeds = 600 runs, 3.3 million representative agents, with zero conservation failures, invalid routes, passenger-through-office paths, and isolation violations. This proves software/process consistency only; it does not validate measured Daxing trajectories, gate shares, dwell distributions, or passenger forecasts.

The access graph remains a directed functional/process abstraction: 49 reciprocal physical Door pairs, 48 unique Space connections, 76 passenger and 96 staff explicit-Door directed edges, 2,990 passenger and 1,300 staff functional abstraction edges, and zero of 1,278 thermal-adjacency candidates admitted to routing. No route behavior is changed in V3.1.

## Closed experiment gaps

- Primary scale registered as `BEM_REFERENCE_NORMALIZED`: 585,765.751350 public and 26,510.855700 staff person-hours/day.
- Historical airport-total mapping permanently relabelled `AIRPORT_WIDE_STRESS_CONTEXT`; its public reports are retained without overwrite.
- `SOURCE_STATIC` is the primary control and retains the source OSM People schedules.
- The current one-seed shoulder evidence remains mechanism demo only until the fixed-sizing and 78-period seasonal gates pass.
- EnergyPlus uncertainty will be described as ABM stochastic-realization sensitivity, never measured uncertainty.

## Claim boundary

The model is a source/process-constrained BEM occupancy compiler, not physical pedestrian microsimulation. BEM design-People ratios are stress references, not safety or operational capacity. No post-result parameter tuning, DCV activation, trajectory refinement, or new passenger-flow feature is permitted.
