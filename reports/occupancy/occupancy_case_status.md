# Airport Occupancy Admission Status

## Final status: `OCCUPANCY_DEMO_ONLY`

| Admission gate | Result |
|---|---|
| Terminal provenance clear | PASS |
| Stable annual baseline | FAIL |
| People/Zone spatial difference | PASS |
| Original real HVAC present | FAIL |
| Same-passenger-hours reproducible | PASS |
| Interpretable distribution response | PASS |
| Frozen repair method unchanged | PASS |

The controlled compiler and synthetic Ideal Loads path is stable, but the source contains no original real HVAC and no stable annual real-HVAC baseline. Those failures are non-waivable for `OCCUPANCY_CASE_ADMIT`.

The spatial/temporal result is evaluated separately from the volume control. A commonplace 'more people, more load' trend cannot promote this status.

Frozen Formal V2 method identity: `3b9ad9447995f2b78313ca996a6a2ef2fa7711692054be184f470ea083f2928d`. Final100 was not rerun.
