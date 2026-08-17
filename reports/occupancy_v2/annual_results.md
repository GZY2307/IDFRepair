# Annual room-aware IdealLoads results

**Run status:** 9/9 PASS; zero Severe/Fatal.
**Schedule resolution:** 15 minutes; **reported peak resolution:** hourly.
**Gate:** PASS — R runtime 772.5 s,
output 1.094 GiB,
projected suite 9.846 GiB.

| Scenario | Person-h million | Heating GWhₜₕ | Δ vs R | Cooling GWhₜₕ | Δ vs R | Heat peak MWₜₕ | Heat peak time | Cool peak MWₜₕ | Cool peak time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_s | 32.592 | 16.526 | -15.43% | 6.322 | -7.89% | 9.764 | 01/18  05:00:00 | 11.264 | 08/02  16:00:00 |
| baseline_r | 44.617 | 19.541 | +0.00% | 6.863 | +0.00% | 11.263 | 01/18  05:00:00 | 12.769 | 08/02  17:00:00 |
| public_morning | 44.617 | 19.432 | -0.56% | 6.752 | -1.62% | 11.062 | 01/18  03:00:00 | 12.905 | 08/02  16:00:00 |
| public_midday | 44.617 | 19.541 | +0.00% | 6.863 | +0.00% | 11.263 | 01/18  05:00:00 | 12.769 | 08/02  17:00:00 |
| public_evening | 44.617 | 19.419 | -0.62% | 6.683 | -2.62% | 11.247 | 01/18  05:00:00 | 12.780 | 08/02  17:00:00 |
| public_perimeter | 44.617 | 19.547 | +0.03% | 6.879 | +0.23% | 11.263 | 01/18  05:00:00 | 12.766 | 08/02  17:00:00 |
| public_core | 44.617 | 19.550 | +0.05% | 6.877 | +0.20% | 11.263 | 01/18  05:00:00 | 12.766 | 08/02  17:00:00 |
| entrance_2_lead | 44.617 | 19.536 | -0.02% | 6.859 | -0.06% | 11.261 | 01/18  05:00:00 | 12.774 | 08/02  17:00:00 |
| entrance_3_lead | 44.617 | 19.539 | -0.01% | 6.863 | +0.00% | 11.261 | 01/18  05:00:00 | 12.774 | 08/02  17:00:00 |

At matched annual person-hours, whole-building heating changes by at most
-0.62% and cooling by at most -2.62%. The largest category
cooling-energy contrast is `terminal_hall` / `public_evening`
(-3.86%); the largest category cooling-peak contrast is
`dining` / `public_morning`, 786.62 to
966.64 kWₜₕ (+22.89%).

Annual compact outputs omit OA, temperature, RH and unmet-time series to satisfy the
size gate; those diagnostics are available in all 42 seasonal runs. Annual values are
controlled IdealLoads thermal demand, not calibrated utility energy. Each controlled
15-minute representative-day profile is repeated across all 365 calendar days; this is
not a weekday/weekend/holiday airport operations model.
