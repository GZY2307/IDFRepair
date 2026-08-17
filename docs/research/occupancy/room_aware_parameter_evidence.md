# Room-aware occupancy parameter evidence

**Decision:** four design densities have evidence adequate for Baseline R;
two densities remain `DO_NOT_AUTOFILL`. Main Baseline S/R comparisons preserve
source OA, activity, heat fractions, CO2 fields, geometry, and non-People loads.

## Evidence tiers

- `TIER_A_SOURCE_BACKED`: exact OSM field retained without reinterpretation.
- `TIER_B_STANDARD_OR_LITERATURE_BACKED`: same-project engineering note or
  authoritative standard used in a labelled reference derivative.
- `TIER_C_CONTROLLED_NOT_MEASURED`: deterministic scenario input only.
- `DO_NOT_AUTOFILL`: evidence is absent or does not resolve the source category.

## Adopted and rejected inputs

| Category | Parameter | Adopted value | Tier | Scope | Source / locator | Decision boundary |
|---|---|---:|---|---|---|---|
| office | design_density_m2_per_person | 6 m2/person | TIER_B_STANDARD_OR_LITERATURE_BACKED | BASELINE_R_PEOPLE_ONLY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 办公 | Measured staff attendance or an operational schedule. |
| commerce_retail | design_density_m2_per_person | 5 m2/person | TIER_B_STANDARD_OR_LITERATURE_BACKED | BASELINE_R_PEOPLE_ONLY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 一般商业 | A separate customer/staff split or measured operating demand. |
| dining | design_density_m2_per_person | 2.5 m2/person | TIER_B_STANDARD_OR_LITERATURE_BACKED | BASELINE_R_PEOPLE_ONLY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 餐厅 | Observed meal demand, dwell time, or staff/customer composition. |
| breakroom | design_density_m2_per_person | 3.7161216 m2/person | TIER_B_STANDARD_OR_LITERATURE_BACKED | BASELINE_R_PEOPLE_ONLY | ASHRAE_62_1_2022_AB; Table 6-1, General — Break rooms, 25 persons/1000 ft2 | Measured staff break attendance or airport-specific utilization. |
| terminal_hall | design_density_m2_per_person | DO_NOT_AUTOFILL | DO_NOT_AUTOFILL | PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, multiple non-equivalent hall rows | Selecting one point density for every source-labelled hall. |
| restroom | design_density_m2_per_person | DO_NOT_AUTOFILL | DO_NOT_AUTOFILL | PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK | SOURCE_OSM_AUDIT; Terminal Model A room audit; restroom label without a dwell model | Treating an office restroom template as measured passenger occupancy. |
| office | outdoor_air_per_person_m3_s_person | 0.00833333 m3/s-person | TIER_B_STANDARD_OR_LITERATURE_BACKED | REFERENCE_OA_IDEALLOADS_SENSITIVITY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 办公, 30 m3/(h-person) | Source AirLoop topology, DCV controls, or measured ventilation energy. |
| commerce_retail | outdoor_air_per_person_m3_s_person | 0.00833333 m3/s-person | TIER_B_STANDARD_OR_LITERATURE_BACKED | REFERENCE_OA_IDEALLOADS_SENSITIVITY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 一般商业, 30 m3/(h-person) | Source AirLoop topology, DCV controls, or measured ventilation energy. |
| dining | outdoor_air_per_person_m3_s_person | 0.00694444 m3/s-person | TIER_B_STANDARD_OR_LITERATURE_BACKED | REFERENCE_OA_IDEALLOADS_SENSITIVITY | PROJECT_HVAC_NOTES_SJSM05; SJSM page 05, section 4.2, row 餐厅, 25 m3/(h-person) | Source AirLoop topology, DCV controls, or measured ventilation energy. |
| breakroom | outdoor_air_per_person_m3_s_person | 0.0025 m3/s-person | TIER_B_STANDARD_OR_LITERATURE_BACKED | REFERENCE_OA_IDEALLOADS_SENSITIVITY | ASHRAE_62_1_2022_AB; Table 6-1, General — Break rooms, Rp=2.5 L/(s-person) | Actual terminal OA delivery or demand control. |
| breakroom | outdoor_air_per_area_m3_s_m2 | 0.0003 m3/s-m2 | TIER_B_STANDARD_OR_LITERATURE_BACKED | REFERENCE_OA_IDEALLOADS_SENSITIVITY | ASHRAE_62_1_2022_AB; Table 6-1, General — Break rooms, Ra=0.3 L/(s-m2) | Actual terminal OA delivery or demand control. |
| restroom | exhaust_air_changes_per_hour | 15 1/h | TIER_B_STANDARD_OR_LITERATURE_BACKED | DOCUMENTED_NOT_IMPLEMENTED | PROJECT_HVAC_NOTES_SJSM06; SJSM page 06, mechanical ventilation table, employee/public restroom | Synthesizing exhaust equipment or source HVAC topology in the simplified OSM. |

The three same-project density values (office 6, general commerce 5, dining
2.5 m²/person) come from construction-note page 05, section 4.2. The breakroom
reference converts ASHRAE's 25 persons/1000 ft² to
3.716122 m²/person. The hall source label does not
resolve the multiple documented hall rows, whose densities span 2–10
m²/person; selecting one value would be unsupported. Restroom occupancy lacks
a source dwell model. The 15 h⁻¹ restroom exhaust note is documented but not
implemented because the simplified OSM does not map source HVAC topology.

## Local source-document provenance

Only extracted facts and hashes are recorded; raw TIFF/DWG material is excluded
from Git and the review package.

- `SJSM page 03`: `36cf0feeb7e9c6fe8e798641b338446561bb709559c6ffc177f11e12d0defedf` — same terminal project identity and scale.
- `SJSM page 05`: `2589f13221cc7bfcf874182f702b8a3646e1348506ea7128bb6922a5dc4adb11` — section 4.2 room design table.
- `SJSM page 06`: `236a34c4ce7c0770fe5ccfd0dca6a63970ac128b3542136b6dcc04415cd8966c` — restroom exhaust design note.
- `SJSM page 07`: `1c9e49cd35f4c5fd082a0c020480e076c90bff40f836b0bbf582536efa7b34b6` — system-type descriptions.

Page 07 establishes that real project HVAC design documentation exists, but the
simplified second-floor OSM contains no AirLoop or PlantLoop mapping to those
systems. The resulting status is `REAL_HVAC_DESIGN_EVIDENCE_PRESENT` with
`HVAC_TOPOLOGY_UNRESOLVED`; no source-backed real HVAC is synthesized.

## EnergyPlus and ventilation semantics

EnergyPlus 23.1 defines the People count method, Number of People Schedule, Activity Level Schedule, Fraction Radiant, autocalculated sensible fraction, and CO2 generation fields in its [official Input Output Reference](https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v23.1.0/InputOutputReference.pdf).
The derivative therefore preserves the source heat/CO2 fields and changes only
the explicitly registered People count and controlled schedule.

[ASHRAE 62.1-2022 Addendum ab](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20addenda/62_1_2022_ab_20231031.pdf) supplies the general
break-room defaults used above and reference ventilation rates. Its
transportation-waiting default is not applied to the unresolved hall label.
Reference OA changes, where attempted, are isolated as
`REFERENCE_OA_IDEALLOADS_SENSITIVITY`; they are not a real-HVAC case and do not
authorize DCV.

## Airport occupancy literature ledger

| Source | Prior contribution supported by verified metadata/abstract | Not transferred to this case |
|---|---|---|
| [Kapil Sinha et al. (2019)](https://doi.org/10.26868/25222708.2019.211133) — An Agent-based Dynamic Occupancy Schedule Model for Prediction of HVAC Energy Demand in an Airport Terminal Building | Airport zone occupancy profiles can differ and can be coupled to energy simulation. | The profile or calibration of Terminal Model A. |
| [Xiaochen Liu et al. (2019)](https://doi.org/10.1016/j.buildenv.2019.03.011) — Analysis of passenger flow and its influences on HVAC systems: An agent based simulation in a Chinese hub airport terminal | Passenger distributions can be heterogeneous in time and space and affect occupancy-linked OA demand. | A transferable passenger density, route, or HVAC response for this simplified OSM. |
| [Kapil Sinha et al. (2021)](https://doi.org/10.1016/j.buildenv.2021.108147) — Evaluating the dynamics of occupancy heat gains in a mid-sized airport terminal through agent-based modelling | Occupancy heat gains may vary dynamically and by terminal zone. | Direct transfer of metabolic, sensible, or latent values as facts for this terminal. |
| [Xianliang Gu et al. (2022)](https://doi.org/10.1016/j.scs.2021.103619) — Prediction of the spatiotemporal passenger distribution of a large airport terminal and its impact on energy simulation | Zone-resolved spatiotemporal passenger distributions can alter simulated terminal loads. | The source-room mapping or occupancy observations for Terminal Model A. |
| [Xianliang Gu et al. (2022)](https://doi.org/10.1177/1420326X221074222) — A spatiotemporal passenger distribution model for airport terminal energy simulation | Operational-data-informed zone schedules and annual energy coupling have established precedent. | Use of that airport's schedules as measured data for this model. |
| [Kai Ma et al. (2024)](https://doi.org/10.1016/j.seta.2024.103790) — Model predictive control for thermal comfort and energy optimization of an air handling unit system in airport terminals using occupant feedback | Occupant-based terminal control has been evaluated on a validated air-handling-unit model. | A real control system, MPC result, or HVAC topology for Terminal Model A. |
| [Mingyang Cong et al. (2025)](https://doi.org/10.1016/j.buildenv.2025.112781) — Evaluating and optimizing energy and comfort performance in airport cooling systems through dynamic occupancy modeling and time-series clustering | High-resolution spatiotemporal occupancy and zoning have current airport BEM precedent. | A cluster model or cooling system transferable without source topology and data. |
| [Hao Tang et al. (2025)](https://doi.org/10.1016/j.buildenv.2025.112829) — Enhancing occupant-centric ventilation control in airport terminals: A predictive optimization framework integrating agent-based simulation | Multi-zone occupant-centric airport ventilation control is established prior work. | Permission to invent DCV, controls, or real equipment in Terminal Model A. |
| [Kai Ma et al. (2026)](https://doi.org/10.1016/j.rser.2025.116287) — Dynamic occupants, indoor environmental quality, and energy systems control at airports: A systematic review | Dynamic airport occupancy, IEQ, and energy-control coupling form an established research field. | A novelty claim for dynamic airport occupancy or occupancy-driven HVAC. |

Together, these studies establish passenger-flow, zone-schedule, heat-gain,
energy-simulation, MPC, and occupant-centric ventilation precedents. This
case therefore makes no claim of being the first dynamic airport occupancy
or occupancy–HVAC study. Its bounded contribution is an OSM/IDF-native,
provenance-aware downstream workflow whose room mapping fails closed and
whose counterfactuals conserve person-hours.

## Claim boundary

The construction-note values are project design inputs, not measured
occupancy. Literature examples provide method precedent, not calibration
data. Baseline R is a controlled reference derivative, and every seasonal or
annual result remains an IdealLoads thermal-demand simulation rather than a
calibrated terminal energy result.
