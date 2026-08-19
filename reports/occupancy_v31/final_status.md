# Airport Occupancy V3.1 — Final Status

Status: `AIRPORT_V31_DEMO_ONLY`

## Evidence closure

| Item | Final result |
|---|---|
| Source public person-hours/day | 585,765.751350 |
| Source staff person-hours/day | 26,510.855700 |
| Normalized realizations | 25/25 pass |
| Maximum public/staff relative error | 2.325e-14 / 9.606e-16 |
| Normalized/stress public person-hour ratio | 3.8564 |
| Source-static maximum design-reference ratio | 1.000 |
| Normalized baseline maximum ratio | 43.274 |
| Normalized baseline Space-time ratio >1 | 35,112/132,480 (26.50%) |
| Sizing fields before / applied / unresolved | 3,944 / 3,036 / 908 |
| Fixed-HVAC gate | `FIXED_OPERATION_INCOMPLETE` |
| Seasonal physical processes | planned 52, passed 52 |
| Seasonal period identities | planned 78, passed 78 |
| EnergyPlus errors | 0 Severe, 0 Fatal; 870–871 Warning/process |
| Annual matrix | planned 6, run 0, skipped by fixed-operation gate |
| Passenger-flow changes in V3.1 | none |
| Claim status | controlled, source-constrained, not measured |

## Main seasonal medians

`BASELINE_SPREAD − SOURCE_STATIC`:

| Period | Facility | Fan | Pump | District cooling | District heating | Peak HVAC | Cooling unmet |
|---|---:|---:|---:|---:|---:|---:|---:|
| Winter | -3.39% | -1.10% | -15.66% | +3.85% | -12.03% | -0.76% | 0.00 h |
| Summer | -0.42% | -3.89% | -3.25% | -3.50% | +25.16% | -2.16% | +15.00 h |
| Shoulder | +0.11% | +1.16% | +3.30% | +1.50% | +13.13% | +5.11% | +3.50 h |

The summer and winter percentages with a zero reference are intentionally not
reported. Heating occupied unmet time is zero at the paired median in all
three periods; winter has a 0.05 h five-seed mean because one realization has
0.25 h.

## Timing-bank mechanism

The strongest whole-building mechanism occurs for shoulder
`MIDDAY_BANK − BASELINE_SPREAD`: +1.04% facility, +12.42% fan, +11.69% pump,
+9.14% district cooling, +25.66% district heating, and +79.07% peak HVAC. The
largest registered local examples include a +209.591 kW shoulder baggage-claim
Zone cooling peak, a -0.817 °C shoulder domestic-waiting mean-temperature
change, and a +15.621 m3/s domestic-waiting outdoor-air change. Across the 14
AirLoops, the same shoulder comparison reaches +515.127 kW cooling interval
peak on the maximum-effect loop and +51.877 kg/s outdoor-air peak on another
maximum-effect loop. Public aliases intentionally replace system names.

## Autosizing confound

For the preregistered shoulder seed-40015 baseline/midday pair, the partial
common-reference versus per-scenario-autosized deltas are respectively:

- facility electricity: +1.05% versus +2.71%;
- fan electricity: +12.48% versus +30.80%;
- pump electricity: +11.69% versus +42.87%;
- district cooling: +9.14% versus +35.11%;
- district heating: +25.66% versus +110.13%;
- peak HVAC: +79.07% versus +50.66%.

This confirms that scenario-specific autosizing materially confounds the old
energy deltas. It does not rescue the partial reference as a fully fixed
system.

## Permanent disposition

No annual substitute was run, no ABM parameter was tuned, and no passenger-flow
function was added. Occupancy development stops at V3.1. Formal semantic repair
and Final100 remain outside this work and are not rerun. The Energy and
Buildings paper proceeds without depending on this airport occupancy case.

## GitHub disposition

The public staging repository has existing Draft PR #1 on
`codex/airport-abm-v3 → main`. V3.1 is staged only on that branch after a fresh
clone passes the full public test suite, synthetic ABM run, compilation,
allowlist scan, and archive inspection. The PR remains Draft; no replacement PR
or merge is created.
