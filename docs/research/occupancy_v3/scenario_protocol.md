# Airport Occupancy V3 Scenario Protocol

## Pre-registered comparison basis

The primary question is whether **different temporal and spatial distributions
under the same daily passenger-hours** change Zone and HVAC loads. The primary
timing comparison therefore fixes, for every matched seed:

- airport-wide external context mapped to the representative public cohort:
  53.61 million/year, or about 146,877 passenger movements/day;
- staff BEM target: 26,510.85570 person-hours/day;
- the controlled class mix, route, dwell, detour decision, and public cohort
  weight for the matched seed;
- staff route and dwell distribution;
- People definitions and design capacities;
- source constructions, equipment, OA specifications, setpoints, HVAC topology,
  and control sequence.

Only passenger event timing and the consequent directed Space occupancy change.
The resulting public person-hours are matched across timing cases, but are no
longer forced to the source static-People integral. The source public integral
is retained as a BEM reference, not re-labelled as passenger arrivals.

## ABM matrix

| Family | Scenarios | Controlled change |
|---|---|---|
| Static versus dynamic | source static People; `BASELINE_SPREAD` | Dynamic directed distribution under an explicit airport-wide context mapping |
| Timing | baseline, morning, midday, evening, double | 0.82 flight-bank mixture with a retained 24-hour tail and matched person-hours |
| Composition | departure, arrival, transfer, international-boundary dominant | Class mix at fixed controlled total public count |
| Volume | 0.50, 0.75, 1.00, 1.25, 1.50x | Passenger arrivals only; staff fixed |
| Dwell | short, medium, long | Domestic gate-wait support |
| Discretionary | low, baseline, high | Optional bounded detour probability |

Each of the 20 scenarios uses seeds `40001..40030`. Any hard validation failure
marks the seed–scenario `ABM_INVALID` and excludes it from BEM coupling.

## EnergyPlus selection fixed before results

- Seasonal seeds: `40003, 40009, 40015, 40021, 40027`.
- Annual master seed: `40015`.
- Winter sizing period: source winter design day.
- Summer sizing period: source summer design day.
- Shoulder weather period: 15 April 2006, Beijing weather.
- Annual weather period: 1 January–31 December 2006, Beijing weather.

Seasonal coupling covers baseline spread, morning, midday, evening, and double
for all five fixed seeds. The annual runtime gate covers the source static case,
ABM baseline, morning, midday, and evening cases at the pre-registered master
seed. No seed is chosen after viewing an energy difference.

## Metrics

Whole-building outputs include facility electricity, fan electricity, pump
electricity, DistrictCooling and DistrictHeating boundary energy, peak HVAC
electric demand, and occupied unmet hours. System outputs include AirLoop fan
energy and outdoor-air mass flow. Space/Zone outputs include occupancy, People
heat gains, sensible heating/cooling energy, temperature, relative humidity,
and available outdoor-air flow.

The DistrictCooling and DistrictHeating meters define the plant boundary. They
are not interpreted as measured airport utility bills or individual chiller and
boiler production efficiency.

## Analysis rules

1. Report 30-seed mean, P10, P50, P90, minimum, and maximum for ABM peaks.
2. Verify exact matched person-hours for timing scenarios before comparison.
3. Keep volume, dwell, composition, and discretionary effects in separate
   families; do not pool them as ordinary head-count sensitivity.
4. Report whole-building and AirLoop/region/function results together.
5. Preserve zero-DCV source behavior; no occupancy-result tuning is permitted.
6. Label all unsupported inputs and resulting forecasts
   `CONTROLLED_NOT_MEASURED`.
7. Use only successful EnergyPlus runs with zero Severe and zero Fatal errors.
8. Treat the official total as airport-wide scale context: never report it as a
   measured Level-2, route, gate, or 15-minute flow.

## Admission rule

The occupancy case can enter the main Energy and Buildings manuscript only as a
downstream application if the new-model baseline, directed graph, ABM hard gate,
People compilation, seasonal simulations, selected annual simulations, system
metrics, visualization, and controlled claim boundary all pass. If results are
common-sense-only, unstable, or dependent on unsupported parameters, the case is
`AIRPORT_ABM_SUPPLEMENT_ONLY` or `AIRPORT_ABM_DEMO_ONLY` and must not block the
semantic-repair manuscript.
