# Airport Occupancy V3 — Public Model Validation Summary

Status: `PASS_BASE_MODEL`

The current user-supplied Level-2 OpenStudio model was opened read-only. V3
analysis and People schedules were written only to private derivatives. The
Formal V2 repair implementation and Final100 evaluation were neither modified
nor rerun.

| Validation item | Result |
|---|---:|
| OpenStudio runtime | 3.6.1 |
| Spaces / Thermal Zones | 304 / 304 |
| Draft validity errors | 0 |
| Forward-translation errors | 0 |
| AirLoops / PlantLoops | 14 / 2 |
| Four-pipe fan coils | 75 |
| Zone exhaust fans | 27 |
| Heat-recovery units | 7 |
| IdealLoads | 0 |
| Mechanical-ventilation controllers | 14 |
| Controllers with DCV enabled | 0 |

Independent EnergyPlus 23.1 gates covered source summer and winter design
days plus a seven-day Beijing weather smoke. All three completed with zero
Severe and Fatal errors, zero node/branch failures, and zero occupied unmet
hours in those baseline gates. Existing model warnings are disclosed in the
private audit and were not silently repaired by the occupancy study.

The source has 13 SpaceType-level People definitions. People-only derivatives
expand them to 276 direct-Space People objects without changing protected
building/HVAC objects or adding IdealLoads. Twenty-eight Spaces without a
source People capacity remain flow-only and receive no invented BEM heat gain
or per-person outdoor air.

This summary intentionally excludes the raw model, derived models, private
paths, exact room mapping, coordinates, weather, and drawings.
