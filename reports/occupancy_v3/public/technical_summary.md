# Airport Occupancy V3 — Technical Summary

Status: `PASS_CONTROLLED_DEMO`

## What is complete

- The current Level-2 terminal source remained read-only; People schedules were
  created only in private derivatives.
- A directed discrete-event ABM separates domestic departure, domestic arrival,
  domestic transfer, international arrival, and staff lifecycles.
- Passenger and staff access graphs are distinct. Passenger routes cannot use
  office shortcuts. International arrival terminates at an explicit off-model
  Level-1 boundary rather than domestic baggage claim.
- Commercial, restaurant, and restroom visits are optional, time-budgeted
  detours that return to the original route anchor.
- All 600 scenario–seed runs conserve agents and pass the route/isolation gates.
- The browser uses 96 × 15-minute Space occupancy, exact Space-edge flows,
  source-capacity overload colours, and real EnergyPlus heating/cooling series.

## Throughput and occupancy boundary

The official 2025 airport-wide total corresponds to about 146,877 passenger
movements/day. Applying that aggregate to the simplified Level-2 BEM is a
declared controlled mapping, not a measured floor count. Across 30 seeds, the
baseline public BEM person-hours median is 151,895.6/day and staff person-hours
are 26,510.9/day. The five timing cases match these integrals seed by seed.

The median whole-model 15-minute peak changes from 12,888.9 in the spread case
to 37,126.8, 36,972.0, 33,744.6, and 21,225.9 for the morning, midday, evening,
and double-bank cases. This is the intended same-passenger-hours temporal and
spatial redistribution test; it is not an ordinary low/medium/high occupancy
sensitivity.

## Service rooms, night flow, and overload display

For the fixed-seed baseline display, 16 of 51 commercial Spaces, 6 of 22
restaurant Spaces, and 4 of 27 restroom Spaces receive a reachable optional
detour. Their aggregate peaks are 170.36, 97.43, and 87.90 occupants. Unreached
service rooms are not filled merely because the terminal is busy; without an
admitted access edge, doing so would invent circulation evidence.

The 24-hour controlled profile is non-zero overnight. Maximum displayed counts
for `00:00–05:00` are 86.58 at the departure boundary, 21.87 in commercial,
29.39 in restaurant, 29.20 in restroom, and 2,000.63 in domestic waiting.
For `21:00–24:00`, the corresponding maxima are 140.45, 53.01, 25.95, 27.40,
and 5,906.90. These values demonstrate periodic night handling; they are not
measured airport night demand.

Among Spaces with source-supported People capacity, 132 exceed 100% in at
least one controlled interval and the maximum ratio is 895.9%. The viewer maps
every value above 100% to red rather than leaving it green. This is a stress
flag, not proof that the source capacity is a fire-code or operational limit.

## Representative-day HVAC mechanism demo

Five fixed-seed shoulder-day EnergyPlus 23.1 runs completed with zero Severe
and Fatal errors. They preserve the source HVAC topology and add no IdealLoads
or demand-controlled ventilation. Relative to the spread case:

| Timing case | Facility electricity | Fan electricity | Cooling boundary | Heating boundary | Peak HVAC electricity |
|---|---:|---:|---:|---:|---:|
| Morning bank | +0.10% | +1.34% | +1.64% | +2.23% | +0.90% |
| Midday bank | +0.52% | +6.70% | +8.37% | +20.13% | +6.95% |
| Evening bank | +0.57% | +7.39% | +9.04% | +19.36% | +5.66% |
| Double bank | +0.15% | +1.94% | +2.37% | +3.94% | +1.27% |

This is a one-seed, one-day mechanism demonstration. It does not replace a
paired multi-seed seasonal/annual experiment and is not admitted as an Energy
and Buildings result.

## Publication boundary

The public package contains code, a geometry-free synthetic fixture, aggregate
tables, and method/validation reports. It excludes raw or derived OSM/IDF,
weather, exact Space mapping, coordinates, drawings, raw agents, SQL outputs,
and private paths.
