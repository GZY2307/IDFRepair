# People–Zone–HVAC Coupling Audit

This audit reuses the frozen semantic relation representation through an adapter; it does not modify the Formal V2 method or rerun Final100.

## Source-backed mapping

- The user-authored OSM contains 29 People instances and 28 People definitions.
- OpenStudio aggregates them into 6 translated People/SpaceList groups. Neutral group sizes are [141, 46, 22, 67, 27, 1]; together they cover 304 translated Zones.
- Original source-backed Zone→HVAC relations: 0/304 served Zones.
- Synthetic derivative Zone→Ideal Loads relations: 304/304 served Zones.
- DesignSpecification:OutdoorAir objects: 5; Controller:MechanicalVentilation objects: 0; AirLoopHVAC objects: 0.
- The derivative adds 304 Ideal Loads systems and skips 1 orphan Zone with no Space. These systems are synthetic demo equipment.

No zone-function labels (check-in, security, gate, arrivals, and so on) are inferred from opaque object names.

## Exact EnergyPlus 23.1 RDD availability

| Mechanism/output family | Availability |
|---|---|
| People occupant count | `available` |
| Zone People occupant count | `available` |
| People sensible/latent/radiant gains | `available` |
| Zone temperature/humidity | `available` |
| Synthetic Ideal Loads thermal response | `available` |
| Synthetic Ideal Loads outdoor-air response | `available` |
| Original fan electricity | `unavailable` |
| Original pump electricity | `unavailable` |
| Original AirLoop/DCV response | `unavailable` |

Unavailable means the mechanism is not established by this model/runtime; it is not a numeric zero. Facility electricity reported by an Ideal Loads demo is not original terminal HVAC electricity.

## Baseline smoke

- Status: `PASS`.
- EnergyPlus: `EnergyPlus, Version 23.1.0-87ed9199d4`.
- Runtime SHA-256: `9832298eb181205db921b2c3d40dc2e89f12793c963e0f3177e1fd7bd8534382`.
- IDD SHA-256: `d171e0583cd43c8c0abe39a5ffcf95d7100f4ec6809c887963e25c9cbcfe1df3`.
- Weather SHA-256: `c5a000246fd9c838eefeea8ddaa808bc1ed349ea33ced3f620f24f8ccebd2a3e`.
- Derived baseline IDF SHA-256: `b9077d023553e44bfe890bd35cf2d960cd7516b02bccc93db086ea50e58b1060`.
- Return/severe/fatal: 0/0/0; CSV available: true.

The successful smoke qualifies only the synthetic thermal-load execution path. It does not qualify a real airport HVAC energy case.
