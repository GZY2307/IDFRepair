# Terminal Baseline Qualification

Primary controlled candidate: **Terminal Model A** (selected by source-backed zone and People counts, not by filename).

| Gate | Result |
|---|---|
| Source byte identity | PASS |
| Translated without fatal translator errors | PASS |
| Has ThermalZones | PASS |
| Has People objects | PASS |
| Has weather assignment | PASS |
| Has original real HVAC | FAIL |

## Qualification: `NO_REAL_HVAC`

The source model cannot support claims about original terminal HVAC electricity, fan, pump, coil, outdoor-air, or DCV response. A derived Ideal Loads system may be used only for thermal-load mechanics and is classified `DEMO_DERIVATIVE_ELIGIBLE`. It cannot upgrade the evidence to a real terminal HVAC case.

Occupancy weakness does not block the frozen semantic-repair paper; the occupancy extension remains an independent downstream evaluation.
