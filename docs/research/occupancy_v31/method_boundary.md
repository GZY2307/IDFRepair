# Airport Occupancy V3.1 Method Boundary

## Purpose

V3.1 closes evidence gaps around an already frozen airport occupancy compiler.
It does not extend passenger behavior. The V3 agent classes, business
processes, Passenger and Staff access graphs, semi-Markov dwell families,
discretionary anchor-return mechanism, route families, and 15-minute compiler
are unchanged.

The scientific question is limited to whether a source-model-matched daily
People integral, redistributed in time and among Spaces, produces stable and
interpretable Zone/HVAC sensitivity. It is not a passenger forecast, physical
pedestrian simulation, or operational calibration.

## Evidence classes

| Evidence class | Use in V3.1 | Claim boundary |
|---|---|---|
| Source-model fact | People definitions, default-day schedules, Space/Zone/HVAC bindings, equipment/control inventory | BEM inputs only |
| Official process evidence | Direction and off-model process boundaries retained from V3 | Process abstraction, not a measured route |
| Controlled input | Dwell, choices, timing transforms, class composition, cohort weights | `CONTROLLED_NOT_MEASURED` |
| EnergyPlus output | Response of the supplied BEM under the registered schedules | Model sensitivity, not utility or field measurement |

The source design-People count is only a BEM design-occupancy reference. A
ratio above 100% is a source-design stress flag; it is not fire-code capacity,
terminal operating capacity, or a safety assessment.

## Two deliberately separate scales

`BEM_REFERENCE_NORMALIZED` is the V3.1 primary scale. Public and staff cohort
weights are independently scaled until their default-day person-hours equal
the source People schedules. The scale does not change any route, dwell,
choice, or timing parameter.

`AIRPORT_WIDE_STRESS_CONTEXT` is the historical V3 secondary scale. It keeps
the airport-wide annual-average throughput mapping only for stress
visualization and software-scalability context. It is not a Level-2 observed
flow and is never used as the V3.1 primary energy baseline.

The normalized source target is larger than the historical stress mapping.
Consequently, overload cannot be dismissed as an artifact of mapping an
airport-wide total into the model. It is the interaction of a large source
People integral, directed route concentration, and small local BEM design
references. V3.1 reports this outcome without clipping or tuning it away.

## SOURCE_STATIC control and People-only derivatives

`SOURCE_STATIC` is the unmodified source People schedule control. Every
dynamic derivative retains the source People definitions and design values and
changes only People schedules. Twenty-eight flow-only Spaces remain available
to routing but receive no invented People capacity.

The existing People → Space → Thermal Zone → HVAC relations supply the
function, region, HVAC-group, AirLoop, and Zone aggregations. No new HVAC,
IdealLoads, DCV, setpoint, construction, or control logic is introduced.

## Fixed-sizing interpretation boundary

The source-static model was sized once. OpenStudio `applySizingValues()` was
then evaluated, and SQL-available values were copied only into fields that were
originally autosized on a fresh source copy. Topology, controls, schedules,
constructions, and non-People loads remained protected.

The audit left critical water-coil-controller flow fields unresolved. The hard
gate is therefore `FIXED_OPERATION_INCOMPLETE`. Seasonal results are retained
as design/sizing sensitivity from a common partially fixed reference. They are
not called fixed installed-HVAC operational response. The registered annual
matrix is skipped rather than guessing values or reverting to per-scenario
autosizing.

## Literature validation gap

The literature check was repeated against publisher/proceedings records:

- [Liu et al. (2019)](https://www.sciencedirect.com/science/article/pii/S0360132319301659)
  performed on-site surveys of passenger movements and service counters and
  used those inputs in an agent simulation of a Chinese hub terminal.
- [Gu et al. (2022)](https://www.sciencedirect.com/science/article/pii/S2210670721008830)
  modeled 14 characteristic terminal zones and validated its distribution
  model against airport operation data and AnyLogic results before coupling to
  IES energy simulation.
- [Sinha et al. (2019)](https://publications.ibpsa.org/proceedings/bs/2019/papers/BS2019_211133.pdf)
  used an airport-authority flight schedule and field-observed processing-time
  and walking-speed distributions in an AnyLogic-to-OpenStudio/EnergyPlus
  workflow.
- [Sinha et al. (2021)](https://www.sciencedirect.com/science/article/pii/S0360132321005485)
  reports an occupant-density/profile model validated with field surveys and a
  thermo-physiological sensible/latent heat-gain treatment.

V3.1 has source-model and process constraints but no local passenger counts,
tracked trajectories, observed dwell distributions, gate shares, or measured
occupant-density validation. It therefore cannot claim the validation level of
those studies, the first airport ABM/BEM coupling, or a real Daxing passenger
distribution.

## Permanent stop rule

The failed fixed-operation gate and extreme normalized local concentration set
the final status to `AIRPORT_V31_DEMO_ONLY`. No V4, new route model, flight
scraping, queue/social-force layer, DCV study, or parameter tuning follows from
this work. The semantic-repair manuscript proceeds independently.
