# Airport Occupancy V3.1 — Fixed-sizing completeness audit

Hard-gate status: `FIXED_OPERATION_INCOMPLETE`

The source-static model was sized once and OpenStudio `Model::applySizingValues()` was evaluated on a separate model copy. A second fresh source copy received only values for fields that were originally autosized; the original source remained read-only and topology, controls, schedules, constructions, and loads were unchanged.

The sizing run completed with 409 warnings, 0 Severe errors, and 0 Fatal errors. Of 3,944 originally autosized fields, 3,036 received explicit sizing values and 908 remained unresolved.

| Category | Before | Available | Applied | Unresolved |
|---|---:|---:|---:|---:|
| Air terminal | 74 | 74 | 74 | 0 |
| AirLoop | 14 | 14 | 14 | 0 |
| Coil | 1,577 | 1,577 | 1,577 | 0 |
| Fan | 89 | 89 | 89 | 0 |
| FourPipeFanCoil | 375 | 225 | 225 | 150 |
| HeatExchanger | 7 | 7 | 7 | 0 |
| Other critical HVAC | 870 | 112 | 112 | 758 |
| OutdoorAir | 14 | 14 | 14 | 0 |
| PlantLoop | 4 | 4 | 4 | 0 |
| Pump | 4 | 4 | 4 | 0 |
| VAV terminal | 916 | 916 | 916 | 0 |

## Unresolved fields

| Object type | Field predicate | Count |
|---|---|---:|
| OS_Controller_WaterCoil | `isControllerConvergenceToleranceAutosized` | 379 |
| OS_Controller_WaterCoil | `isMaximumActuatedFlowAutosized` | 379 |
| OS_ZoneHVAC_FourPipeFanCoil | `isMaximumSupplyAirTemperatureInHeatingModeAutosized` | 75 |
| OS_ZoneHVAC_FourPipeFanCoil | `isMinimumSupplyAirTemperatureInCoolingModeAutosized` | 75 |

The unresolved water-coil-controller maximum actuated flow fields are critical flow fields. The comparison therefore fails the fixed-operation hard gate. Any downstream run made from the partial reference is reported only as design/sizing sensitivity, not as a fixed installed-HVAC operational response. No missing values were guessed or written merely to pass the gate.

This public audit contains counts and field identities only. It excludes the source model, sizing SQL, explicit equipment values, room mapping, coordinates, IDF, and weather file.
