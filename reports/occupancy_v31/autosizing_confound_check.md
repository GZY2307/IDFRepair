# Airport Occupancy V3.1 — Autosizing confound check

Status: `PASS_PRESELECTED_TWO_CASE_CHECK`

Only shoulder, seed 40015, BASELINE_SPREAD and MIDDAY_BANK were run under both sizing treatments. `PARTIAL_APPLYSIZING_OPERATION` uses the common partially fixed reference with new sizing disabled; `AUTOSIZED_PER_SCENARIO` repeats sizing for each People derivative. Because 908 fields remained unresolved, the first treatment is not a valid fully fixed installed system.

| Metric | Partial baseline | Partial midday | Partial delta | Partial % | Autosized baseline | Autosized midday | Autosized delta | Autosized % | Partial/autosized delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Facility electricity | 111,312.915 | 112,478.619 | 1,165.704 | 1.05% | 111,541.084 | 114,567.958 | 3,026.874 | 2.71% | 0.385 |
| Fan electricity | 8,818.073 | 9,918.646 | 1,100.573 | 12.48% | 9,032.617 | 11,814.766 | 2,782.149 | 30.80% | 0.396 |
| Pump electricity | 557.198 | 622.329 | 65.131 | 11.69% | 570.822 | 815.547 | 244.725 | 42.87% | 0.266 |
| District cooling boundary | 60,358.929 | 65,873.086 | 5,514.157 | 9.14% | 62,300.932 | 84,173.080 | 21,872.148 | 35.11% | 0.252 |
| District heating boundary | 36,097.100 | 45,360.677 | 9,263.576 | 25.66% | 37,700.712 | 79,222.383 | 41,521.671 | 110.13% | 0.223 |
| Peak HVAC electricity | 484.622 | 867.809 | 383.187 | 79.07% | 473.427 | 713.241 | 239.815 | 50.66% | 1.598 |
| Cooling occupied unmet hours | 4.250 | 5.000 | 0.750 | 17.65% | 0.250 | 1.000 | 0.750 | 300.00% | 1.000 |
| Heating occupied unmet hours | 0.000 | 0.000 | 0.000 | — | 0.000 | 0.000 | 0.000 | — | — |

Scenario-specific autosizing materially changes several MIDDAY-minus-baseline deltas, so the old autosized-per-scenario result cannot be interpreted as a fixed-system response. This two-case check diagnoses confounding only; it is not a second experiment matrix.
