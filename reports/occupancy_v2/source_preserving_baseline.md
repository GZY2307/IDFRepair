# Baseline S — source-preserving

**Status:** `SOURCE_PRESERVING_IDEALLOADS_BASELINE`
**Boundary:** controlled thermal-load baseline, not measured airport operation.

Baseline S retains the source design People totals, schedules, activity, heat/CO₂
parameters, non-People loads, OA definitions, geometry, constructions and zone
semantics. It adds 304 IdealLoads endpoints solely for thermal-demand comparison.
The source OSM remains byte-identical at `6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb`.

| Category | Spaces | Area m² | Source design people | Day person-h | Annual person-h |
| --- | --- | --- | --- | --- | --- |
| terminal_hall | 126 | 150,117.49 | 8,079.26 | 82,408.41 | 22,896,611.74 |
| office | 69 | 20,239.36 | 1,036.45 | 9,638.87 | 2,661,314.16 |
| commerce_retail | 51 | 13,348.41 | 1,772.55 | 13,336.38 | 4,353,612.78 |
| dining | 22 | 4,713.51 | 507.36 | 4,667.69 | 1,282,498.66 |
| restroom | 27 | 7,190.12 | 773.94 | 4,179.27 | 1,167,099.05 |
| breakroom | 9 | 1,516.69 | 81.63 | 832.60 | 231,333.04 |

## Occupant-class accounting

Representative-day totals are 82,408.41 terminal-hall passenger-h,
10,471.48 staff person-h, 18,004.08
commerce+dining public-facing-unsplit person-h, and 4,179.27
public-linked restroom person-h; whole building = 115,063.23 person-h.

## Thermal and HVAC boundary

- Winter IdealLoads: 141,711.27 kWh heating and 1,815.29 kWh cooling.
- Annual IdealLoads: 16,526.35 MWh heating and 6,321.85 MWh cooling.
- Source counts remain 29 People and 28 PeopleDefinition objects; 304 IdealLoads systems are derivative-only.
- Source AirLoop = 0, PlantLoop = 0, real zone equipment = 0.

Baseline S preserves source semantics; it does not endorse the inherited Large Office
schedule as true airport operation.
