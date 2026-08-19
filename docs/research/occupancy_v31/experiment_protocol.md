# Airport Occupancy V3.1 Experiment Protocol

## Frozen registries

The dynamic scenarios are `BASELINE_SPREAD`, `MORNING_BANK`, `MIDDAY_BANK`,
`EVENING_BANK`, and `DOUBLE_BANK`. The seasonal seeds are exactly 40003,
40009, 40015, 40021, and 40027. The annual master seed is 40015. No failed or
unfavorable seed is replaced.

Winter and summer are the two frozen source design periods. Shoulder is the
registered 15 April 2006 Beijing weather day. The weather file itself remains
private.

## Normalization gate

For each scenario and seed, public and staff representative-agent weights are
solved independently so that:

```text
sum(15-minute public occupancy) × 0.25 h = source public person-hours/day
sum(15-minute staff occupancy) × 0.25 h = source staff person-hours/day
```

The relative-error gate is `1e-8`. Counts and schedule fractions are never
clipped. All 25 registered realizations must pass before BEM coupling.

## Comparisons

The primary comparison is `BASELINE_SPREAD − SOURCE_STATIC`. It tests the
effect of replacing the source static/template distribution with a directed
dynamic distribution while preserving daily public and staff person-hours.

The secondary paired comparisons are each timing bank minus
`BASELINE_SPREAD`. They retain the same seed and daily person-hours and test
temporal/spatial concentration rather than ordinary head-count sensitivity.

The historical airport-wide run is reported only beside the normalized scale
for context; its public V3 artifacts are not overwritten or rerun.

## Capacity-reference audit

The denominator is every source-People-supported Space × 96 intervals × every
registered seed. For source static there is one deterministic profile. For
each dynamic case there are five profiles. The audit reports counts above 1.0,
1.5, and 2.0; P50, P90, P95, P99, and maximum; and companion groupings by
function, region, HVAC group, and scenario.

## Sizing and protected-object gate

The source-static BEM receives one complete sizing run. The sizing SQL is
associated with a separate OpenStudio model and `applySizingValues()` is
called. A fresh source copy receives only SQL-available values for originally
autosized fields. Source and protected-object comparisons then verify that
topology, controls, schedules, constructions, loads, and the zero-DCV state did
not change.

The audit records fields before, values available, values applied, and fields
unresolved by category and object type. Any unresolved critical capacity or
flow field sets `FIXED_OPERATION_INCOMPLETE`; values are never guessed to pass
the gate.

## Seasonal EnergyPlus denominator

The registered denominator is:

```text
5 scenarios × 5 seeds × 3 periods = 75 dynamic period identities
SOURCE_STATIC × 3 periods         =  3 static period identities
total                              = 78 period identities
```

One design-day process contains both winter and summer environments, while one
weather process contains shoulder. The physical process count is therefore 52.
Each record contains run identity, return code, Warning/Severe/Fatal counts,
wall time, occupied unmet hours, and output-period status. Only return code 0,
zero Severe, zero Fatal, and the expected output period pass.

Execution uses bounded concurrency and private completion markers based on run
identity, input size/modified time, and valid outputs. No hash is embedded in a
model or program.

## Statistics and metrics

Every dynamic comparison is paired by the five frozen seeds. Reports include
n, mean and median difference, minimum, maximum, and empirical P10/P90. These
are controlled ABM stochastic-realization sensitivities, not measured
uncertainty or statistical significance.

Whole-building metrics are facility, fan, and pump electricity; district
cooling/heating boundary energy; peak HVAC electric demand; and occupied unmet
hours. District meters are building-side boundaries, not central-plant
production.

All 14 AirLoops contribute fan energy, mean/peak outdoor-air mass flow,
heating/cooling energy, and interval peaks. Function/Zone aggregation includes
occupancy, sensible/latent/radiant People gains, sensible heating/cooling,
temperature, relative humidity, and available outdoor-air flow.

## Autosizing-confound check

Only shoulder seed 40015, `BASELINE_SPREAD` and `MIDDAY_BANK`, are compared
between the common partially fixed reference and per-scenario autosizing. This
is a diagnostic of sizing confounding, not a second matrix.

## Annual gate

The six registered annual cases are `SOURCE_STATIC` plus all five dynamic
scenarios at seed 40015. They run only if normalization, complete fixed sizing,
protected-object, and seasonal stability gates all pass. With
`FIXED_OPERATION_INCOMPLETE`, the exact registered action is planned 6, run 0;
no shorter substitute, alternate seed, or autosized annual case is allowed.

## Admission rule

`AIRPORT_V31_PAPER_SUBSECTION_READY` requires a complete fixed-operation gate,
the seasonal and annual matrices, nontrivial local/system evidence, and the
controlled claim boundary. `SUPPLEMENT_READY` still requires complete fixed
sizing. Unreliable fixed sizing or unexplained extreme normalized
concentration forces `AIRPORT_V31_DEMO_ONLY` and permanently ends occupancy
method development.
