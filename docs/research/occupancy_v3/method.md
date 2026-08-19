# Airport Occupancy V3 Method

## Method position

Airport Occupancy V3 uses an **access-constrained directed discrete-event
agent-based model with semi-Markov dwell times**. Its purpose is to compile
role-specific passenger and staff events into 15-minute Space-level People
schedules for an existing OpenStudio/EnergyPlus model. It is not a pedestrian
collision, evacuation, queue, or measured passenger-forecast model.

The contribution boundary is deliberately narrow. Airport ABM, dynamic
occupancy schedules, discretionary-activity modelling, and BEM coupling are
established research areas. V3 contributes an OSM/IDF-native compiler that:

1. derives functional room and HVAC group semantics from the same audited model;
2. separates source facts, official process evidence, user restrictions, and
   controlled assumptions;
3. applies distinct Passenger and Staff access graphs;
4. converts validated events directly to Space-level EnergyPlus People schedules;
5. reuses the model's People → Space/Zone → HVAC relations for output grouping.

## Two-level directed graph

The model combines a `FunctionalProcessGraph` and a `SpaceAccessGraph`.

- The functional graph constrains the order of airport processes, including
  off-model boundary states.
- The Space graph realizes only transitions allowed by the functional graph.
- Reciprocal OSM Door objects are strong access evidence.
- User/source-supported functional corridor rules are explicit abstractions.
- Thermal adjacency alone remains non-walkable by default.

Passenger routing excludes office, breakroom, and information-room shortcuts.
Staff use an independent graph that permits assigned work and break spaces but
still requires an access edge. Commercial, dining, and restroom visits are
bounded optional detours; each consumes an existing time budget and returns to
the exact route anchor.

## Agent lifecycles

- `DOMESTIC_DEPARTURE`: departure boundary → public/central process → domestic
  waiting pier → optional anchor-return detour → board and leave the model.
- `DOMESTIC_ARRIVAL`: domestic waiting pier → mixed/public process → domestic
  baggage claim → arrival boundary → out.
- `DOMESTIC_TRANSFER`: arrival pier → mixed/public process → a different
  departure pier → board; domestic baggage is excluded by default.
- `INTERNATIONAL_ARRIVAL`: Level-2 international arrival → international/vertical
  transition → `OFF_MODEL_LEVEL1_IMMIGRATION`. The Level-1 immigration and
  international baggage process is outside the model.
- `STAFF`: staff boundary → assigned office → optional staff break → return to
  the assigned office → staff exit boundary.

Every agent has one location at a time. Events are simulated in continuous
minutes, and visits/flows are integrated into 96 non-negative 15-minute bins.
Weighted representative agents reconcile to source-model People person-hours;
the weights do not convert controlled agents into observed airport passengers.

## People schedule compilation

The source OSM is read-only. A private derivative removes the 13 inherited
SpaceType-level People instances and creates one explicit People object for each
of the 276 source-supported Spaces. Each direct People object retains the source
design capacity and definition while its number schedule reads the matching ABM
column. Twenty-eight flow-only Spaces remain visible to the ABM but receive no
invented People capacity.

The derivative gate checks:

- no People double counting;
- exact source design-capacity reconciliation within the documented source-area
  rounding envelope;
- unchanged Spaces, Zones, Lights, equipment, outdoor-air specifications,
  constructions, HVAC topology, setpoints, and controls;
- unchanged 14 AirLoops, 2 PlantLoops, 75 four-pipe fan coils, 27 exhaust fans,
  and 7 heat-recovery units;
- zero added IdealLoads;
- successful OpenStudio forward translation.

No demand-controlled ventilation is enabled. The existing mechanical
ventilation control sequence remains the primary experiment boundary.

## Validation and inference boundary

All scenarios must pass conservation, terminal-state, route, role, isolation,
detour-return, and deadline checks before schedule compilation. Thirty seeds per
scenario quantify stochastic variation; controlled dwell, choice, class mix,
and flight-bank timing are explored through separate sensitivity families.

The method supports descriptive mechanism and controlled sensitivity claims.
It does not establish real passenger trajectories, current gate allocation,
measured throughput, calibrated dwell distributions, or causal HVAC savings.

## Relation to prior work

- [Sinha et al. (2019)](https://doi.org/10.26868/25222708.2019.211133) couples
  airport passenger ABM schedules to HVAC demand.
- [Liu et al. (2019)](https://doi.org/10.1016/j.buildenv.2019.03.011) uses field
  inputs and agent simulation to study passenger distribution and airport HVAC.
- [Sinha et al. (2021)](https://doi.org/10.1016/j.buildenv.2021.108147) evaluates
  dynamic sensible and latent occupancy heat gains.
- [Gu et al. (2022)](https://doi.org/10.1016/j.scs.2021.103619) links
  spatiotemporal passenger distribution to terminal energy simulation.
- [Mekić et al. (2021)](https://doi.org/10.3390/aerospace8060162) models airport
  discretionary activities and their dependence on available time.

V3 therefore does not claim the first airport ABM, first dynamic occupancy
schedule, first discretionary model, or first BEM coupling.
