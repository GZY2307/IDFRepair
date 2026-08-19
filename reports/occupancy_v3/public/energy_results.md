# Airport Occupancy V3 — EnergyPlus Results

Status: `PASS_CONTROLLED_REPRESENTATIVE_DAY_DEMO`

## Result boundary

All results use the source HVAC topology and control sequence; no IdealLoads or demand-controlled ventilation was added. District cooling and heating are building-side boundary quantities, not central-plant production energy. Timing cases are controlled distributions with equal public/staff person-hours, not measured forecasts.
This report is a fixed-seed, one-day shoulder-period mechanism demonstration. It is not a seasonal or annual result and is not admitted as an Energy and Buildings paper result.

## Building results

### Shoulder

| Scenario | Facility kWh | Fan kWh | Pump kWh | Cooling boundary kWh | Heating boundary kWh | Peak HVAC kW | Cooling unmet h | Heating unmet h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dynamic spread | 110,341.63 | 7,902.22 | 501.76 | 52,706.33 | 38,914.71 | 420.54 | 0.00 | 0.00 |
| Morning bank | 110,455.23 | 8,008.11 | 509.48 | 53,568.16 | 39,784.18 | 424.32 | 0.00 | 0.00 |
| Midday bank | 110,917.52 | 8,431.32 | 548.55 | 57,116.32 | 46,746.71 | 449.75 | 0.25 | 0.00 |
| Evening bank | 110,971.36 | 8,485.85 | 547.87 | 57,468.41 | 46,447.75 | 444.36 | 0.00 | 0.00 |
| Double bank | 110,506.52 | 8,055.82 | 513.06 | 53,954.70 | 40,448.41 | 425.89 | 0.00 | 0.00 |

Fixed-seed paired timing effect relative to the dynamic spread case:

| Timing case | Pairs | Facility electricity | Fan electricity | Cooling boundary | Heating boundary | Peak HVAC demand |
|---|---:|---:|---:|---:|---:|---:|
| Morning bank | 1 | 113.61 (0.10%) | 105.89 (1.34%) | 861.83 (1.64%) | 869.47 (2.23%) | 3.78 (0.90%) |
| Midday bank | 1 | 575.89 (0.52%) | 529.10 (6.70%) | 4,409.99 (8.37%) | 7,832.00 (20.13%) | 29.21 (6.95%) |
| Evening bank | 1 | 629.73 (0.57%) | 583.63 (7.39%) | 4,762.08 (9.04%) | 7,533.04 (19.36%) | 23.82 (5.66%) |
| Double bank | 1 | 164.90 (0.15%) | 153.60 (1.94%) | 1,248.37 (2.37%) | 1,533.71 (3.94%) | 5.35 (1.27%) |

## Maximum AirLoop redistribution effects

For each timing case, period, and system metric, the table selects the AirLoop with the largest absolute paired change. With multiple seeds this is the paired median; with one pair it is an explicit fixed-seed demo value. The selection is made from all 14 source AirLoops; it is not a whole-building meter duplicated across loops.

| Period | Timing case | Pairs | Metric | AirLoop | Paired difference | Paired percent |
|---|---|---:|---|---|---:|---:|
| Shoulder | Morning bank | 1 | Fan electricity (kWh) | SE-VAV | 49.91 | 5.25% |
| Shoulder | Morning bank | 1 | Peak outdoor air (kg/s) | SW-VAV | 4.37 | 8.01% |
| Shoulder | Morning bank | 1 | Air-system cooling interval peak (kW) | SE-VAV | 38.30 | 4.18% |
| Shoulder | Morning bank | 1 | Air-system heating interval peak (kW) | SE-VAV | 42.28 | 5.68% |
| Shoulder | Midday bank | 1 | Fan electricity (kWh) | SW-VAV | 128.13 | 22.94% |
| Shoulder | Midday bank | 1 | Peak outdoor air (kg/s) | SE-VAV | 14.89 | 13.19% |
| Shoulder | Midday bank | 1 | Air-system cooling interval peak (kW) | SE-VAV | 132.99 | 14.52% |
| Shoulder | Midday bank | 1 | Air-system heating interval peak (kW) | SE-VAV | 95.43 | 12.81% |
| Shoulder | Evening bank | 1 | Fan electricity (kWh) | SW-VAV | 123.08 | 22.03% |
| Shoulder | Evening bank | 1 | Peak outdoor air (kg/s) | SW-VAV | 12.09 | 22.15% |
| Shoulder | Evening bank | 1 | Air-system cooling interval peak (kW) | SW-VAV | 112.80 | 21.64% |
| Shoulder | Evening bank | 1 | Air-system heating interval peak (kW) | SE-VAV | 100.17 | 13.45% |
| Shoulder | Double bank | 1 | Fan electricity (kWh) | NE-VAV | 31.57 | 6.25% |
| Shoulder | Double bank | 1 | Peak outdoor air (kg/s) | NE-VAV | 3.03 | 6.11% |
| Shoulder | Double bank | 1 | Air-system cooling interval peak (kW) | NE-VAV | 28.76 | 6.07% |
| Shoulder | Double bank | 1 | Air-system heating interval peak (kW) | NE-VAV | 37.98 | 7.99% |

## Interpretation limits

The source model uses autosized equipment. EnergyPlus therefore repeats sizing for each People-only derivative; this preserves the source model fields but means comparisons are not a fixed installed-capacity experiment. The OSM also keeps demand-controlled ventilation disabled, so occupancy timing affects internal gains, zone loads, and existing control responses rather than introducing a new occupancy-driven outdoor-air controller. Results support controlled mechanism and sensitivity analysis, not measured airport energy savings.
