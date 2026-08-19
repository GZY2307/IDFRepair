# Airport Occupancy V3 — Stochastic Uncertainty

## Result

Thirty pre-registered seeds were retained for every scenario. The table
reports seed uncertainty in the 15-minute whole-building peak; it does not
represent uncertainty in measured airport behavior.

| Scenario | Family | P10 | P50 | P90 | Minimum | Maximum |
|---|---|---:|---:|---:|---:|---:|
| Baseline spread | timing | 12,632.4 | 12,888.9 | 13,239.5 | 12,523.7 | 13,489.6 |
| Morning bank | timing | 36,562.7 | 37,126.8 | 37,599.1 | 36,421.3 | 38,471.5 |
| Midday bank | timing | 36,578.9 | 36,972.0 | 37,820.7 | 36,557.6 | 38,582.1 |
| Evening bank | timing | 33,208.7 | 33,744.6 | 34,508.8 | 32,586.7 | 35,023.5 |
| Double bank | timing | 20,522.5 | 21,225.9 | 21,803.0 | 20,126.6 | 21,994.5 |
| Departure dominant | composition | 14,575.1 | 14,919.2 | 15,470.9 | 14,277.1 | 15,838.9 |
| Arrival dominant | composition | 9,500.0 | 9,676.7 | 9,979.2 | 9,434.9 | 10,193.6 |
| Transfer dominant | composition | 12,822.4 | 13,178.9 | 13,653.8 | 12,748.3 | 14,118.6 |
| International boundary | composition | 8,206.5 | 8,451.9 | 8,641.0 | 8,145.3 | 8,758.9 |
| 0.50x | volume | 8,052.6 | 8,322.5 | 8,565.6 | 7,742.9 | 8,647.4 |
| 0.75x | volume | 10,354.8 | 10,610.7 | 10,862.9 | 10,284.4 | 11,156.7 |
| 1.00x | volume | 12,632.4 | 12,888.9 | 13,239.5 | 12,523.7 | 13,489.6 |
| 1.25x | volume | 14,928.1 | 15,270.0 | 15,817.7 | 14,739.4 | 16,214.0 |
| 1.50x | volume | 17,271.4 | 17,658.9 | 18,335.2 | 16,884.1 | 18,674.4 |
| Short wait | dwell | 10,410.1 | 10,638.1 | 10,944.1 | 10,301.7 | 11,307.6 |
| Medium wait | dwell | 12,632.4 | 12,888.9 | 13,239.5 | 12,523.7 | 13,489.6 |
| Long wait | dwell | 14,798.4 | 15,237.5 | 15,598.2 | 14,674.5 | 15,757.6 |
| Detour Low | discretionary | 12,642.8 | 12,982.9 | 13,300.6 | 12,462.3 | 13,778.9 |
| Detour Base | discretionary | 12,632.4 | 12,888.9 | 13,239.5 | 12,523.7 | 13,489.6 |
| Detour High | discretionary | 12,701.1 | 13,006.7 | 13,250.5 | 12,535.6 | 13,375.6 |

## Robustness boundary

The timing cases are paired by seed and exactly matched on BEM public and
staff person-hours. Seed spread therefore reflects stochastic route, gate,
dwell, and detour realization under fixed controlled inputs. Parameter
uncertainty is represented separately by the dwell, volume, composition, and
discretionary sensitivity families; no posterior calibration or energy-result
tuning was performed.
