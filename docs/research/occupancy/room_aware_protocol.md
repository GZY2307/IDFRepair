# Room-aware airport occupancy protocol

**Protocol status:** `CONTROLLED_NOT_MEASURED`

## Scope and baselines

Baseline S preserves every source design People total, schedule, activity, heat
fraction, CO2 field, and OA definition while aggregating results by the six
source-name room categories. Baseline R is a People-only reference derivative:
it makes People explicit per Space and changes design density only where the
evidence registry permits. Neither baseline represents measured operations.
IdealLoads additions are synthetic thermal-demand endpoints, not real HVAC.

## Occupant classes

- `public`: terminal_hall only; eligible for 0.5–1.5 volume scaling.
- `staff`: office and breakroom; staff fixed in all public counterfactuals.
- `public-facing-unsplit`: commerce_retail and dining; no invented customer/staff split.
- `public-linked-bounded`: restroom; linked to public presence without a dwell-time claim.

Whole-building integrals are `person-hours`. `Passenger-hours` is reserved for
the explicit terminal_hall public class; unsplit categories are reported
separately.

## Fifteen-minute reference profiles

All profiles are Tier C controlled shapes. Their values are design-capacity
fractions at 15-minute resolution; they are not flight-derived predictions.

| Category | Steps/day | Minimum | Maximum | Equivalent full-occupancy hours/day | SHA-256 |
|---|---:|---:|---:|---:|---|
| terminal_hall | 96 | 0.0300 | 0.6200 | 7.2550 | `d956a06ae13b1feb549a1a1d14b1161e3e9c8e8511f4cbad0adc1ae677005330` |
| office | 96 | 0.0100 | 0.8500 | 8.6300 | `653432dadc29d24d906ea58ec0325034317283bc0a0e17d11d97c855b5443883` |
| commerce_retail | 96 | 0.0100 | 0.7000 | 7.6100 | `b66bd23d3672c15c6cd8041de10764ef1901abb4576221c7e302cfd4c5c97498` |
| dining | 96 | 0.0100 | 0.8800 | 6.2050 | `6660b16f9d53017d8b45619e27e193517912176291debf8f4dd8d2a5bb295efd` |
| restroom | 96 | 0.0208 | 0.1525 | 2.0762 | `39ba47b7b0f036ec51af03dbc43063be4c25a70eb58c4301e2a7ca353651066f` |
| breakroom | 96 | 0.0100 | 0.7200 | 3.3850 | `1f60a190687e7c11eec69e9e976327c51ba7d933ab8771e5dc5e82ae401d855c` |

## Controlled scenario matrix

1. Baseline R seeds `z-u-hall-2` and `z-u-hall-3` at phase zero. Public
   Spaces in the reciprocal paired-surface Zone graph use controlled
   15/30/45-minute occupancy-response phases by within-region hop tercile.
   These phases are not walking times or measured passenger trajectories;
   office/breakroom staff are not entrance-delayed.
2. `public_morning`, `public_midday`, and `public_evening` circularly shift
   each already-phased public-dynamic Space by −4, 0, and +4 hours. Each
   Space's 96-value multiset and person-hours are identical; office/breakroom arrays
   are the same immutable objects in all three cases.
3. `entrance_2_lead` and `entrance_3_lead` are reciprocal regional cases:
   one entrance region leads by 30 minutes while the other lags by 30 minutes.
   Every Space retains its exact 96-value multiset and person-hours.
4. `public_perimeter` and `public_core` redistribute each category's timestep
   count only among Spaces of that same category. Ranking uses source geometry
   exterior-area/floor-area ratio solely as a controlled physical exposure
   grouping. Geometry is not used for room-function classification.
5. `public_volume_0.50` through `public_volume_1.50` scale terminal_hall only.
   Office, breakroom, commerce, dining, and restroom remain unchanged because
   their staff/customer decomposition is unavailable.

Conservation tolerance is 1e-9 person-hours for temporal cases and 1e-9
persons per category-timestep for spatial allocation. Every allocation is
bounded by its per-Space design People count.

## Simulation periods and outputs

- Winter controlled day: 15 January (Beijing CSWD weather).
- Summer controlled day: 15 July.
- Shoulder controlled day: 15 April.
- Annual: 1 January–31 December at 15-minute schedules if the gate below passes.

Outputs are reconciled at Space/category/building level: occupant count and
density, person-hours, People sensible/latent/radiant gains, IdealLoads
heating/cooling demand and peaks, temperature/RH where available, OA-related
IdealLoads variables where available, and unmet time. Missing EnergyPlus
variables are labelled unavailable, never imputed.

## `ANNUAL_RUNTIME_GATE`

Annual runs proceed only after all retained seasonal cases finish with zero
Fatal/Severe errors, exact source/freeze hashes, complete CSV outputs, and
category reconciliation. A profiled annual Baseline R must project no more
than 30 minutes and 2 GB per run, available disk must exceed 2.5 times the
projected suite footprint, and concurrency is capped at two processes.

## Interpretation boundary

Temporal and spatial cases test distribution effects at matched integrals;
volume cases are ordinary sensitivity checks and are not treated as novelty.
No case is calibrated to flight, Wi-Fi, staff roster, or measured HVAC data.
The official Daxing Level-2 plan supplies spatial context only and does not
authorize invented check-in, gate, baggage, door, or HVAC labels in the OSM.
A whole-building or local result is reported only within this controlled
IdealLoads boundary.
