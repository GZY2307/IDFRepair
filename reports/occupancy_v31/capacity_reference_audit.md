# Airport Occupancy V3.1 — BEM Design-Occupancy Reference Audit

The denominator is every source-People-supported Space × 15-minute interval × preregistered seed. `SOURCE_STATIC` has one deterministic profile; dynamic cases use all five seasonal seeds. Ratios are not clipped. The reference is a BEM design-occupancy input, not a fire-code, safety, operational, or physical capacity.

| Scenario | Seeds | Spaces | Space-time intervals | Spaces ever >1.0 | >1.0 | >1.5 | >2.0 | P50 | P90 | P95 | P99 | Maximum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SOURCE_STATIC | 1 | 276 | 26,496 | 0 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0.900 | 1.000 | 1.000 | 1.000 | 1.000 |
| BASELINE_SPREAD | 5 | 276 | 132,480 | 205 | 35,112 (26.50%) | 24,986 (18.86%) | 16,669 (12.58%) | 0.000 | 2.320 | 3.131 | 5.177 | 43.274 |
| MORNING_BANK | 5 | 276 | 132,480 | 217 | 21,110 (15.93%) | 15,700 (11.85%) | 11,926 (9.00%) | 0.000 | 1.811 | 4.673 | 10.359 | 59.169 |
| MIDDAY_BANK | 5 | 276 | 132,480 | 217 | 20,959 (15.82%) | 15,620 (11.79%) | 11,896 (8.98%) | 0.000 | 1.811 | 4.733 | 10.408 | 67.881 |
| EVENING_BANK | 5 | 276 | 132,480 | 217 | 21,114 (15.94%) | 15,703 (11.85%) | 11,946 (9.02%) | 0.000 | 1.811 | 4.680 | 10.368 | 59.169 |
| DOUBLE_BANK | 5 | 276 | 132,480 | 213 | 27,808 (20.99%) | 21,651 (16.34%) | 16,577 (12.51%) | 0.000 | 2.532 | 4.115 | 7.087 | 49.583 |

The companion CSV contains the same envelope grouped by function, region, public HVAC-group alias, and scenario. Source HVAC labels are not published. Any local overload is retained for the admission decision; no gate assignment, flight bank, dwell, or occupancy value was changed to reduce it.
