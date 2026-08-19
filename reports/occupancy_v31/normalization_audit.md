# Airport Occupancy V3.1 — Normalization Audit

Status: `PASS`

The source-static default-day target is **585,765.751350 public person-hours/day** and **26,510.855700 staff person-hours/day**. All 25 preregistered normalized timing realizations independently match these two integrals. Maximum relative errors are 2.325e-14 (public) and 9.606e-16 (staff), against the `1e-8` gate.

`BEM_REFERENCE_NORMALIZED` is the paper-primary scale. It changes only the public/staff cohort weights; agent classes, route/access semantics, dwell, choices, and timing transforms are frozen. `AIRPORT_WIDE_STRESS_CONTEXT` remains a historical secondary visualization/scalability experiment.

## Scale comparison

| Metric | BEM_REFERENCE_NORMALIZED | AIRPORT_WIDE_STRESS_CONTEXT | BEM / stress |
|---|---:|---:|---:|
| public_person_hours | 585,765.7513 | 151,895.5773 | 3.8564 |
| whole_building_15min_peak | 40,643.8583 | 12,888.9238 | 3.1534 |
| spaces_over_1_design_reference_seed40015 | 182.0000 | 132.0000 | 1.3788 |
| maximum_design_ratio_seed40015 | 34.5836 | 8.9592 | 3.8601 |
| domestic_waiting_peak_seed40015 | 27,152.6359 | 7,034.1705 | 3.8601 |
| baggage_claim_peak_seed40015 | 4,656.7842 | 1,206.3880 | 3.8601 |
| commercial_restaurant_restroom_peak_seed40015 | 1,000.1476 | 259.0985 | 3.8601 |

The source-model public integral is larger than the old airport-wide stress mapping. Therefore the historical 895.9% flag cannot be explained as a simple consequence of a larger airport-total scale; it reflects the interaction of route concentration and local source design references. V3.1 retains the normalized overload envelope rather than changing ABM parameters.
