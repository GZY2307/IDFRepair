# Simulation relevance and evidence boundary

## Existing design-day evidence

No EnergyPlus run was added for this post-Final audit. The existing frozen outputs show:

| Population | Passed | Failed | Severe | Fatal |
|---|---:|---:|---:|---:|
| 95 faulty repair targets | 4 | 91 | 208 | 91 |
| 5 faulty-side clean controls | 5 | 0 | 0 | 0 |
| 66 automatic repaired outputs + 5 clean controls | 71 | 0 | 0 | 0 |

The 95 faulty repair-target logs also contain 1,527 warnings. The 71 validated outputs contain 4,023 warnings inherited largely from source models, so a successful run is not being redefined as “no warnings”; the executable recovery criterion is zero Severe/Fatal and successful completion.

All four runnable faulty repair targets are in the 50-case single-fault stratum (`fv2-0042`, `fv2-0044`, `fv2-0048`, `fv2-0050`). Thus the frozen statement “4/50 single repair faults can run” and the all-target statement “4/95 repair targets can run” are both true. The other 91 faults are largely structural inconsistencies rejected during input, node, topology, or HVAC initialization.

All 66 automatically repaired artifacts and all five clean controls passed the existing EnergyPlus 24.1 design-day validation (71/71). Ten unique artifacts were executed and 61 record validations reused hash-identical cached artifacts. This demonstrates executable recovery for every committed repair in the frozen Final; it does not convert EnergyPlus into an oracle for the intended design.

## Annual subset

The annual subset of ten records was frozen before V2 inference and was not replaced after outcomes were known. Existing results show:

- Repaired artifacts are hash-identical to their clean counterpart in 10/10 selected cases.
- Clean and repaired annual simulations are both comparable in 7/10 cases; the remaining three source-clean models also fail, so no energy comparison is possible for them.
- Across the seven comparable cases, all nine reported annual metrics have zero relative error (7/7 within 0.1% and 1%; maximum error 0).
- Only one faulty artifact is annually comparable with its clean model, and its nine metrics also have zero difference.

The annual evidence therefore verifies exact controlled restoration where execution is possible. It does not establish a general non-zero energy-impact or WBR effect. `final_status.json` correctly retains `wbr_count = 0`.

No post-hoc annual experiment was added for the other runnable faulty singles. Selecting or promoting cases after seeing their outcomes would weaken the preregistered evidence and, given the existing zero-difference runnable example, would not resolve the missing non-zero impact claim.

## Scientific interpretation

The frozen method primarily targets structural semantic inconsistencies in Branch/node paths, Loop/Connector membership, Zone equipment ownership, SupplyPath/ReturnPath membership, and OutdoorAirSystem compound flow. Many such inconsistencies prevent EnergyPlus from constructing a valid simulation graph, so their practical consequence is initialization failure rather than a subtle wrong-but-runnable energy result.

This is still simulation-relevant: restoring an executable, internally coherent model is a necessary step before energy analysis. But the evidence boundary must remain explicit:

- **Established:** 91/95 faulty repair targets are rejected by EnergyPlus; every committed repair and control passes design-day validation; the preselected comparable annual repairs reproduce clean results exactly.
- **Not established:** a broad distribution of non-zero energy bias for runnable structural faults, recovery of hidden design intent, or correctness beyond the admitted frozen semantic frontier.
- **Role of EnergyPlus:** downstream executable validation, never candidate generation or solver feedback in the frozen inference.

Accordingly, the paper should motivate the method as deterministic structural semantic debugging and safe repair of existing IDF artifacts, not as a WBR estimator.

