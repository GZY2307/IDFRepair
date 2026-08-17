# Seasonal room-aware IdealLoads results

**Run status:** 42/42 PASS; zero Severe/Fatal.
**Resolution:** 15-minute explicit Wednesdays (15 Jan, 15 Jul, 15 Apr).
**Boundary:** thermal demand under IdealLoads, not calibrated airport energy.

## Whole-building contrasts

| Period | Scenario | Person-h | Heating kWh | Δ vs R | Cooling kWh | Δ vs R |
| --- | --- | --- | --- | --- | --- | --- |
| winter | baseline_s | 115,063.23 | 141,711.27 | -17.86% | 1,815.29 | +17.94% |
| winter | baseline_r | 122,239.72 | 172,518.00 | +0.00% | 1,539.12 | +0.00% |
| winter | public_morning | 122,239.72 | 172,541.68 | +0.01% | 1,551.94 | +0.83% |
| winter | public_evening | 122,239.72 | 172,466.78 | -0.03% | 1,515.30 | -1.55% |
| winter | public_perimeter | 122,239.72 | 172,530.68 | +0.01% | 1,548.84 | +0.63% |
| winter | public_core | 122,239.72 | 172,513.23 | -0.00% | 1,530.16 | -0.58% |
| winter | entrance_2_lead | 122,239.72 | 172,517.35 | -0.00% | 1,538.80 | -0.02% |
| winter | entrance_3_lead | 122,239.72 | 172,518.70 | +0.00% | 1,540.10 | +0.06% |
| summer | baseline_s | 115,063.23 | 0.00 | — | 83,229.54 | -10.55% |
| summer | baseline_r | 122,239.72 | 0.00 | — | 93,043.38 | +0.00% |
| summer | public_morning | 122,239.72 | 0.00 | — | 91,201.50 | -1.98% |
| summer | public_evening | 122,239.72 | 0.00 | — | 93,409.49 | +0.39% |
| summer | public_perimeter | 122,239.72 | 0.00 | — | 93,087.18 | +0.05% |
| summer | public_core | 122,239.72 | 0.00 | — | 93,183.56 | +0.15% |
| summer | entrance_2_lead | 122,239.72 | 0.00 | — | 93,025.43 | -0.02% |
| summer | entrance_3_lead | 122,239.72 | 0.00 | — | 93,032.52 | -0.01% |
| shoulder | baseline_s | 115,063.23 | 22,492.01 | -16.54% | 12,085.32 | +10.78% |
| shoulder | baseline_r | 122,239.72 | 26,949.76 | +0.00% | 10,909.74 | +0.00% |
| shoulder | public_morning | 122,239.72 | 25,772.60 | -4.37% | 10,882.10 | -0.25% |
| shoulder | public_evening | 122,239.72 | 25,772.42 | -4.37% | 10,609.05 | -2.76% |
| shoulder | public_perimeter | 122,239.72 | 26,970.18 | +0.08% | 10,929.50 | +0.18% |
| shoulder | public_core | 122,239.72 | 26,885.95 | -0.24% | 10,972.18 | +0.57% |
| shoulder | entrance_2_lead | 122,239.72 | 26,928.36 | -0.08% | 10,875.58 | -0.31% |
| shoulder | entrance_3_lead | 122,239.72 | 26,933.77 | -0.06% | 10,877.12 | -0.30% |

At identical person-hours, the largest seasonal whole-building energy contrast is
shoulder `public_morning` heating (-4.37%).

## Category and zone contrasts

| Period | Scenario | Category | Metric | R baseline | Scenario | Δ |
| --- | --- | --- | --- | --- | --- | --- |
| summer | public_evening | dining | cooling_peak_kw | 535.46 | 696.83 | +30.14% |
| summer | public_morning | dining | cooling_peak_kw | 535.46 | 680.04 | +27.00% |
| shoulder | public_morning | terminal_hall | heating_peak_kw | 2,038.20 | 1,817.84 | -10.81% |
| shoulder | public_morning | commerce_retail | heating_peak_kw | 413.86 | 370.69 | -10.43% |
| shoulder | public_morning | dining | heating_kwh | 1,694.14 | 1,538.65 | -9.18% |
| shoulder | public_evening | commerce_retail | heating_kwh | 3,058.87 | 2,787.82 | -8.86% |
| shoulder | public_evening | dining | heating_kwh | 1,694.14 | 1,546.12 | -8.74% |
| shoulder | public_morning | dining | heating_peak_kw | 227.02 | 207.36 | -8.66% |
| shoulder | public_evening | terminal_hall | cooling_kwh | 3,782.68 | 3,510.38 | -7.20% |
| shoulder | public_morning | terminal_hall | heating_kwh | 12,470.40 | 11,648.97 | -6.59% |
| shoulder | public_morning | commerce_retail | heating_kwh | 3,058.87 | 2,859.35 | -6.52% |
| shoulder | public_evening | terminal_hall | heating_kwh | 12,470.40 | 11,725.34 | -5.97% |

Largest absolute category cooling-peak contrast: `dining` /
`summer` / `public_evening`,
535.46 to 696.83 kWₜₕ
(+30.14%). The largest absolute zone cooling-peak
contrast among baselines ≥1 kW is `z-l-dining-1` (dining),
`summer` / `public_perimeter`: Δ
-37.47 kWₜₕ (-28.10%).
The largest zone cooling-energy contrast is the same Space under
`public_core`: Δ 326.93 kWh
(+23.72%).
These are modeled contrasts, not statistically estimated effects.

## Ordinary volume sensitivity

Only terminal-hall public occupancy is scaled. This is a robustness/demo axis, not novelty.

| Period | Hall multiplier | Total person-h | Heating Δ | Cooling Δ |
| --- | --- | --- | --- | --- |
| winter | 0.50× hall | 92,932.22 | +1.25% | -0.08% |
| winter | 0.75× hall | 107,585.97 | +0.63% | -0.04% |
| winter | 1.00× hall | 122,239.72 | +0.00% | +0.00% |
| winter | 1.25× hall | 136,893.47 | -0.63% | +0.04% |
| winter | 1.50× hall | 151,547.22 | -1.25% | +0.08% |
| summer | 0.50× hall | 92,932.22 | — | -3.16% |
| summer | 0.75× hall | 107,585.97 | — | -1.60% |
| summer | 1.00× hall | 122,239.72 | — | +0.00% |
| summer | 1.25× hall | 136,893.47 | — | +1.59% |
| summer | 1.50× hall | 151,547.22 | — | +3.17% |
| shoulder | 0.50× hall | 92,932.22 | +1.05% | -6.56% |
| shoulder | 0.75× hall | 107,585.97 | +0.52% | -3.34% |
| shoulder | 1.00× hall | 122,239.72 | +0.00% | +0.00% |
| shoulder | 1.25× hall | 136,893.47 | -0.51% | +3.49% |
| shoulder | 1.50× hall | 151,547.22 | -1.01% | +7.19% |

## OA and indoor-state diagnostics

- R OA mass-flow peak in shoulder = 217.576 kg/s; it is unchanged across R temporal/spatial/volume cases because DCV is not enabled.
- Summer evening OA cooling differs from R by +2.63%; this is IdealLoads OA conditioning, not fan/control energy.
- Shoulder R area-weighted mean = 21.733 °C and 34.996% RH.
- Heating and cooling unmet zone-hours = 0.0 in every retained seasonal case.
