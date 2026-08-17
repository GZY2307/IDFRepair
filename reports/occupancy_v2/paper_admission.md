# Paper admission decision

## Final status: `OCCUPANCY_CASE_PAPER_READY`

| Criterion | Result | Evidence |
| --- | --- | --- |
| Source-backed mapping | PASS | 304/304 exact name-token categories |
| Parameter provenance | PASS | Tier A/B/C plus DO_NOT_AUTOFILL |
| Baselines | PASS | S and R both retained and distinguished |
| Simulation stability | PASS | 42 seasonal + 9 annual; zero Severe/Fatal |
| Local explanatory value | PASS | Season +30.14%; annual +22.89% cooling peaks; qualifying effects=19 |
| 3D visualization | PASS | 304 Spaces, 96 steps, five snapshots |
| HVAC boundary | PASS | IdealLoads only; no real topology invented |
| Frozen-method isolation | PASS | efbd22cd185db678edafb4fb5d44286fcc529aa6be12146ee7188fc54d084d4b |

The case is suitable for one short **Downstream application / terminal occupancy sensitivity** subsection and one main-text figure, with the registry, scenario matrix, category tables and 3D snapshots in supplementary material. Formal V2 semantic repair remains the only primary method.

## Bounded finding

At matched person-hours, whole-building annual heating/cooling changes remain modest
(-0.62% / -2.62% at their largest), while
category cooling peaks respond more strongly. The largest annual category contrast is
`dining` / `public_morning` at
+22.89%; the seasonal maximum is
`dining` / `public_evening` at
+30.14%. This supports a local-versus-aggregate
workflow insight, not passenger-flow theory or real-HVAC energy validation.

## Permitted positioning

> A downstream, IDF/OSM-native, provenance-aware scenario workflow on an already
> semantically audited building model.

The differentiators are fail-closed source-label mapping, parameter-level provenance,
person-hour-conserving counterfactuals, reuse of People→Zone→IdealLoads relations and
time-resolved 3D reconciliation. Dynamic airport occupancy, zone schedules, occupancy
heat gains, MPC and occupant-centric ventilation are established prior work.

Recommended manuscript footprint: one setup paragraph, one matched-person-hours figure
(`figures/same_person_hours_effects.png`), one local-versus-whole paragraph and an
explicit IdealLoads limitation. If editorial space is tight, move the case intact to the
Supplement; it must not block the Energy and Buildings paper.

The admission state is computed, not hard-coded. A non-volume temporal/spatial local
effect must pass both the predeclared relative threshold (10%) and absolute threshold
(20 kW for a peak or 100 kWh for zone/category energy), with baseline floors of 50 kW
or 100 kWh. Ordinary public-volume sensitivity is ineligible for this decision.

## Freeze attestation

- Formal V2 aggregate SHA-256: `efbd22cd185db678edafb4fb5d44286fcc529aa6be12146ee7188fc54d084d4b` (expected `efbd22cd185db678edafb4fb5d44286fcc529aa6be12146ee7188fc54d084d4b`).
- Historical occupancy aggregate SHA-256: `99d378b7b0cb5a4e86eea42cfdf933e7d1dac3d5b1cb2fd7259f80238f6ea171` (expected `99d378b7b0cb5a4e86eea42cfdf933e7d1dac3d5b1cb2fd7259f80238f6ea171`).
- Neither tree was edited or regenerated.
