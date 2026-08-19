# Airport Occupancy V3 — Paper Admission Decision

Decision: `DEMO_ONLY_DO_NOT_BLOCK_ENERGY_AND_BUILDINGS`

## Admitted claims

- The implementation can compile a source-constrained directed passenger/staff
  ABM into Space-level People schedules without changing the source model.
- Equal BEM passenger-hours with different temporal/spatial distributions can
  produce different Zone/AirLoop/HVAC responses in a controlled mechanism test.
- Exact Space-edge visualization, overload signalling, and real EnergyPlus load
  curves work in the existing IDFRepair viewer.

## Not admitted to the paper result set

- measured Daxing passenger trajectories, route shares, dwell times, gate use,
  floor coverage, or 15-minute demand;
- calibrated commercial, dining, restroom, or staff behavior;
- claims of airport energy savings or operational optimization;
- seasonal or annual HVAC conclusions from the current fixed-seed shoulder-day
  demonstration;
- novelty based on ordinary morning/noon/evening head-count sensitivity.

The current EnergyPlus comparison has only one paired seed and one shoulder
day. The occupancy extension therefore remains a software/method Demo and
supplementary research direction. It must not delay, alter, or reopen the
frozen Formal V2 semantic-repair method or Final100 evaluation.
