# Airport Occupancy V3 — Occupancy Results

## Technical summary

The directed ABM changes **where and when** a fixed daily public occupancy
integral appears. For each seed, all five timing cases retain exactly matched
public and staff person-hours. Across the 30 stochastic seeds, public
person-hours/day have a median of
151,895.6 (range
151,266.0–
152,351.2); staff person-hours/day
remain 26,510.9. The median
whole-building 15-minute peak rises from 12,888.9 in the spread case to
37,126.8, 36,972.0, and
33,744.6 in the concentrated morning, midday, and
evening cases. These are controlled stress distributions, not ordinary
morning/noon/evening head-count sensitivity and not measured airport forecasts.

## Same passenger-hours produce different peaks

| Timing scenario | Public person-hours/day P50 | Peak P10 | Peak P50 | Peak P90 |
|---|---:|---:|---:|---:|
| Baseline spread | 151,895.6 | 12,632.4 | 12,888.9 | 13,239.5 |
| Morning bank | 151,895.6 | 36,562.7 | 37,126.8 | 37,599.1 |
| Midday bank | 151,895.6 | 36,578.9 | 36,972.0 | 37,820.7 |
| Evening bank | 151,895.6 | 33,208.7 | 33,744.6 | 34,508.8 |
| Double bank | 151,895.6 | 20,522.5 | 21,225.9 | 21,803.0 |

Relative to the spread median, the morning, midday, evening, and double-bank
median peaks are 2.88x,
2.87x,
2.62x, and
1.65x. Figure
`figures/timing_profiles_seed40015.png` shows the complete 96-point profiles,
while `figures/timing_peak_uncertainty.png` shows the 30-seed P10–P90 intervals.

## Function-level concentration is explicit

The baseline domestic-waiting peak has a median of
7,228.3 occupants across the 30 seeds (P10
6,985.0, P90 7,493.1). The category, region, and
HVAC-group rows in `occupancy_results.csv` preserve the same statistics without
publishing Space names; exact Space-level uncertainty stays in the private
analysis directory.

## Volume and dwell change different mechanisms

The volume matrix changes passenger arrivals while keeping staff fixed. Its
whole-building peak median spans 8,322.5–17,658.9
from 0.50x to 1.50x. The gate-wait matrix holds the route structure and volume
fixed; its median peak spans 10,638.1–15,237.5.
The paired panels in `figures/volume_and_dwell_sensitivity.png` keep these two
mechanisms separate.

## Interpretation limit

The official 2025 airport-wide passenger total provides throughput context, but
mapping that airport-wide total into this simplified second-floor BEM is a
controlled Level-2 assumption rather than measured floor, route, gate, or
15-minute demand. The source static People schedules retain the staff target.
Dwell, choice, class mix, and timing-bank shapes remain
`CONTROLLED_NOT_MEASURED`; therefore these results support mechanism and
sensitivity analysis only. Energy conclusions are reported separately after
EnergyPlus stability and output-contract checks.
