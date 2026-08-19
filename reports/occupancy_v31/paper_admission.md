# Airport Occupancy V3.1 — Paper Admission

Final decision: `AIRPORT_V31_DEMO_ONLY`

## Gate audit

| Gate | Evidence | Result |
|---|---|---|
| Exact BEM normalization | 25/25 public/staff profiles pass; maximum relative errors 2.325e-14 and 9.606e-16 | PASS |
| Stress/primary separation | Historical throughput retained only as `AIRPORT_WIDE_STRESS_CONTEXT` | PASS |
| Source-static control | Three source-static seasonal identities included | PASS |
| Fixed-sizing completeness | 3,036/3,944 fields applied; 908 unresolved, including critical water-coil-controller flow | FAIL |
| People-only scenario derivation | Common protected reference; no route/HVAC/control/DCV change | PASS |
| Seasonal denominator | 75/75 dynamic and 3/3 static period identities pass | PASS |
| EnergyPlus stability | 52/52 processes, 0 Severe, 0 Fatal; no seed replacement | PASS |
| Paired statistics | n=5 for every registered dynamic comparison | PASS |
| Annual evidence | Gate required six cases; fixed-operation failure caused planned 6, run 0 | FAIL BY PREREGISTERED RULE |
| No post-result tuning | No dwell, choice, route, timing, or cohort parameter changed after energy results | PASS |
| Beyond “more people means more load” | Same-person-hour timing changed seasonal peak, fan, pump, heating/cooling, local temperatures, and Zone/AirLoop loads | PASS |
| Local/system evidence | All 14 AirLoops and registered public functions aggregated | PASS |
| Calibration boundary | All unsupported passenger inputs remain `CONTROLLED_NOT_MEASURED` | PASS |

## Why the result remains Demo

The fixed-sizing hard gate is decisive. Critical maximum-actuated-flow fields
remain autosized, so the seasonal matrix cannot establish a fixed installed
HVAC operational response. The preregistered annual experiment consequently
cannot run.

The normalized capacity envelope is also unsuitable as a paper-primary airport
baseline: 205 of 276 People-supported Spaces exceed the source design reference
in at least one baseline interval, 26.50% of baseline Space-time observations
exceed 1.0, and the maximum ratio is 43.274. Timing variants reach maxima from
49.583 to 67.881. These are retained source-design stress flags, not physical
capacity or safety claims.

## What the seasonal evidence does show

All 78 period identities are numerically stable. Relative to source static, the
dynamic baseline changes winter district heating by a median -12.03%, summer
district cooling by -3.50%, and shoulder peak HVAC electricity by +5.11%, while
daily public/staff person-hours remain matched. Within the dynamic model, the
shoulder MIDDAY bank changes facility electricity by +1.04%, fan electricity
by +12.42%, pump electricity by +11.69%, district cooling by +9.14%, district
heating by +25.66%, and peak HVAC electricity by +79.07% versus spread.

These are nontrivial temporal/spatial redistribution mechanisms, but their
interpretation is limited to the supplied BEM under controlled schedules and a
partially fixed sizing reference.

## Literature-relative claim

Liu et al. used on-site passenger/service-point surveys; Gu et al. validated
against airport operation data and AnyLogic; Sinha et al. used field-observed
service/walking inputs or field validation. V3.1 does not have equivalent local
occupant-density or trajectory validation. It is a source/process-constrained
BEM occupancy compiler, not a measured Daxing passenger model.

## Manuscript consequence

The occupancy work is permanently limited to GitHub/demo use and may be cited
only as an illustrative downstream mechanism with its failed fixed-operation
gate visible. It must not become an Energy and Buildings result subsection,
must not delay the semantic-repair manuscript, and must not trigger V4.
