# Airport Occupancy Literature Reality Check

**Scope:** targeted primary-source check, not a systematic review  
**Sources checked:** 2019–2026  
**Last verified:** 2026-08-17

## Decision first

Changing morning, midday, and evening People counts and observing an energy
simulation is **not novel**. Airport studies already couple flight-informed or
agent-based passenger flow to zone-wise building-energy models, resolve
sub-hourly and one-minute dynamics, estimate sensible and latent gains, compare
zone loads, and use predicted occupancy in HVAC and ventilation control.

Accordingly, this project makes no claim to the first dynamic airport
occupancy simulation, the first passenger-flow/energy coupling, or a new
passenger-flow model. Its bounded technical contribution is an **IDF-native occupancy scenario compiler** that reuses an already verified
**People→Zone→HVAC** semantic mapping to construct auditable counterfactuals
with the same passenger-hours. Whether that workflow yields a paper case or
only a demo depends on model qualification and simulation evidence.

## Evidence map

### Dynamic schedules and building-energy coupling were established by 2019

Sinha, Ali, and Rajasekar coupled an AnyLogic agent-based passenger model to an
OpenStudio/EnergyPlus terminal model. The model contained 68 thermal zones;
zone-wise occupancy schedules were generated at one-minute resolution, a
typical-day Ideal Loads calculation was reported at one-minute resolution, and
an annual cooling calculation was reported at ten-minute resolution. The paper
also compared ABM-derived schedules with flight-schedule occupancy and examined
zone load/peak behavior. This directly overlaps any broad claim based only on
“dynamic People schedules change airport loads.” [Sinha et al. (2019), IBPSA
Building Simulation, DOI 10.26868/25222708.2019.211133](https://doi.org/10.26868/25222708.2019.211133).

### Occupancy heat-gain dynamics were resolved beyond fixed W/person by 2021

Sinha, Ali, and Rajasekar used field measurements and surveys to validate an
agent-based model of arrival/departure movement, service time, discretionary
activities, dwell time, and zone occupancy in a mid-sized Indian terminal.
They coupled those trajectories to thermo-physiological calculations to derive
zone- and operation-period-specific sensible and latent heat-gain profiles.
Thus, merely varying occupancy and reporting sensible/latent People gains is
also established work. [Sinha et al. (2021), *Building and Environment* 204,
108147](https://doi.org/10.1016/j.buildenv.2021.108147).

### Large-terminal spatiotemporal distribution and IES coupling were
demonstrated by 2022

Gu, Xie, Huang, Ma, and Liu represented passenger processes in 14
characteristic zones of Beijing Daxing International Airport using flight
schedules. They validated the distribution model against airport operational
data and AnyLogic, then supplied the passenger flows to IES energy simulation
and compared them with a traditional calculation. Their published results
included zone-dependent heating/cooling-load differences and a different
annual design consumption. This overlaps claims based on zone-by-zone schedule
generation, spatial redistribution, flight-bank timing, and whole-building
energy impact. [Gu et al. (2022), *Sustainable Cities and Society* 78,
103619](https://doi.org/10.1016/j.scs.2021.103619).

### Recent work extends occupancy into prediction and closed-loop control

- Ma, Wang, Sun, Wang, and Gu integrated mathematical/AnyLogic passenger-flow
  prediction with occupant-based model predictive control for an airport
  baggage-claim air-handling system and evaluated a cooling-season simulation.
  [Ma et al. (2024), *Sustainable Energy Technologies and Assessments* 65,
  103790](https://doi.org/10.1016/j.seta.2024.103790).
- Cong et al. combined field survey data, agent-based modelling, building
  energy modelling, high-resolution spatiotemporal occupancy, and time-series
  clustering to evaluate cooling control and comfort. [Cong et al. (2025),
  *Building and Environment* 274,
  112781](https://doi.org/10.1016/j.buildenv.2025.112781).
- Tang et al. integrated flight-schedule-driven agent-based passenger
  simulation, a physical ventilation model, and coordinated multi-zone
  optimization for energy, flexibility, and indoor-air-quality control. This
  is direct prior art for occupant-centric ventilation rather than just
  internal-gain sensitivity. [Tang et al. (2025), *Building and Environment*
  276, 112829](https://doi.org/10.1016/j.buildenv.2025.112829).
- The 2026 airport-specific review by Ma, Sun, Wang, and Gu organizes work on
  passenger-flow prediction, indoor environmental quality, energy systems,
  and occupant–environment–energy closed loops. It reinforces that the broad
  coupling space is mature and that absolute “first” language is not
  supportable here. [Ma et al. (2026), *Renewable and Sustainable Energy
  Reviews* 226, 116287](https://doi.org/10.1016/j.rser.2025.116287).

## Collision matrix

| Potential claim | Prior evidence | Decision for this project |
|---|---|---|
| Dynamic airport occupancy affects loads | ABM/BEM coupling in 2019 and later | Established; not novel |
| One-minute or sub-hourly schedules | One-minute typical-day calculation in 2019 | Established; not novel |
| Zone-wise passenger schedules | 2019 zone-wise EnergyPlus and 2022 14-zone IES work | Established; not novel |
| Activity-dependent sensible/latent gains | 2021 transient thermo-physiological analysis | Established; not novel |
| Flight-informed spatiotemporal prediction | 2022 mathematical model; 2024–2025 control studies | Established; not novel |
| Occupancy-driven HVAC/ventilation control | 2024 MPC and 2025 multi-zone ventilation optimization | Established; not novel |
| Same passenger-hours counterfactuals compiled from an existing IDF | Not identified as a standalone contribution in this targeted check | A scoped comparison design, not an absolute novelty claim |
| Reuse of repair-time People→Zone→HVAC semantic relations | Project-specific workflow capability | Bounded downstream workflow contribution |

## What remains worth testing

The defensible question is narrower than passenger-flow prediction:

> Given a fixed, version-bound EnergyPlus artifact, can a deterministic
> compiler use source-backed People→Zone→HVAC relations to generate temporal
> and spatial counterfactuals with the same passenger-hours, and can the
> resulting zone/load differences be attributed without fabricating missing
> HVAC mechanisms?

This comparison controls total occupancy exposure and changes only its timing,
location, or both. It may clarify peak timing, peak magnitude, zone
heterogeneity, and (when present) outdoor-air/HVAC mechanisms. It does not
claim to predict real passengers without flight, gate, service-time, or sensor
data.

## Model-specific consequence

The audited user-authored terminal artifact has People and thermal zones but
no original AirLoop, PlantLoop, or ZoneHVAC equipment. A derived Ideal Loads
model can demonstrate schedule compilation and thermal-load mechanisms, but it
cannot establish real fan, pump, coil, DCV, or terminal HVAC energy behavior.
Under the preregistered gate, such results remain demo evidence even if the
same-passenger-hours contrasts are numerically nonzero.

## EnergyPlus semantic boundary

The compiler is bound to EnergyPlus 23.1 semantics. The official schema states
that `People` may target a Zone, ZoneList, Space, or SpaceList and identifies
the number schedule, three design-population methods, radiant and sensible
fractions, activity schedule, and CO₂ generation fields. It also requires a
`Schedule:File` to contain 8760–8784 hours of data. [EnergyPlus 23.1 epJSON
schema](https://energyplus.readthedocs.io/en/v23.1.0/schema.html).

Output names are not assumed from another version. EnergyPlus documents that
the RDD is specific to the actual input and is available only after at least a
semi-successful run; this project therefore performs an RDD discovery pass and
requests only exact returned names. [EnergyPlus 23.1 Output Details and
Examples](https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v23.1.0/OutputDetailsAndExamples.pdf).

## Claim ledger

| Claim | Supported by | Does not support |
|---|---|---|
| Ordinary early/midday/evening occupancy sensitivity is not novel | 2019–2025 primary studies above | That every possible controlled contrast has already been published |
| The proposed compiler can enforce same passenger-hours | Deterministic code/tests and emitted-file conservation checks | Real passenger prediction or causal operational savings |
| The current derivative can expose thermal-load response | Stable EnergyPlus Ideal Loads baseline | Original terminal HVAC electricity or control performance |
| Occupancy is independent of paper readiness | Frozen repair evidence and admission protocol | Using a weak demo to strengthen repair-method novelty |

## Search boundary

This was a targeted reality check of the specified papers and directly adjacent
2024–2026 airport work, not a PRISMA review or exhaustive novelty search.
Consequently, the document deliberately avoids `first`, `unprecedented`, and
exhaustive absence claims. All URLs above were checked on 2026-08-17.
