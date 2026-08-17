# Controlled Airport Occupancy Scenario Protocol

**Protocol version:** 1.0  
**Frozen before comparative scenario interpretation:** 2026-08-17  
**Default temporal resolution:** 15-minute  
**Evidence class:** controlled synthetic-HVAC demo unless every admission gate
is later satisfied

## 1. Purpose and non-purpose

The experiment tests how different temporal and neutral spatial distributions
affect zone and synthetic Ideal Loads response under the **same passenger-hours**. It is not a passenger-flow forecast, flight-bank
reconstruction, queue model, agent-based model, or claim about actual airport
operations. No check-in, security, concourse, gate, baggage, or arrivals label
is inferred from opaque model object names.

The occupancy extension is downstream of the frozen Formal V2 repair work. It
does not alter repair semantics, does not rerun Final100, and does not block the
Energy and Buildings paper.

## 2. Input and provenance boundary

- The two user-authored OSM inputs are read-only and are not an open dataset.
- No raw OSM, translated raw IDF, EPW, or EnergyPlus run directory is publicly
  distributed.
- Source SHA-256 is verified before and after every OpenStudio preparation.
- All schedule, output-request, RunPeriod, and Ideal Loads changes are written
  only to explicitly derived artifacts.
- The zoned model is the controlled candidate; the unzoned companion is an
  upstream geometry/space comparison and is not silently promoted.
- The original zoned model has no real HVAC. Ideal Loads added to 304 Zones is
  synthetic demo equipment; one orphan Zone with no Space is skipped.

## 3. Version-bound People semantics

The experiment uses EnergyPlus 23.1 and reads People fields by exact IDD name:
target Zone/ZoneList/Space/SpaceList, `Number of People Schedule Name`, one of
`People`, `People/Area`, or `Area/Person`, activity schedule, fraction radiant,
sensible fraction, and CO₂ generation rate. Schedule replacement is guarded by
the original object index, field index, old value, and source span.

Formal scenarios use `Schedule:File`, not an EMS People actuator. Each daily
profile has 96 items and is repeated for 365 days, producing **365 × 96** rows;
the object declares **8760** hours and 15 minutes per item as required by the
EnergyPlus 23.1 IDD. The CSV and derived IDF use stable names, fixed decimal
format, and SHA-256 identities.

## 4. Baseline

`existing_baseline` retains the translated source People schedules. The
baseline day is evaluated through EnergyPlus at 15-minute resolution. The
exact `Schedule Value` and expanded People occupant-count outputs are the
reference for each translated People group. Unrounded group design populations
are recovered from their positive-timestep ratios; EIO supplies expanded-zone
counts only. The profile is not replaced with an office template.

Baseline qualification requires return code 0, no Severe or Fatal errors, RDD
and CSV availability, exact runtime/IDD/weather/input hashes, and unchanged
source bytes. A qualified synthetic baseline still does not establish real
HVAC response.

## 5. Temporal redistribution

The following controlled profiles are generated from positive deterministic
templates and scaled to the baseline daily integral:

| Scenario | Dominant window(s) |
|---|---|
| `morning_peak` | 05:00–09:00 |
| `midday_peak` | 11:00–15:00 |
| `evening_peak` | 17:00–22:00 |
| `double_peak` | 05:00–09:00 and 17:00–22:00 |

Every temporal profile must be finite and nonnegative. The compiled daily
passenger-hours must match the baseline within relative tolerance **1e-9**,
calculated again from the exact 12-decimal values emitted to CSV. A scenario
that violates conservation is not run.

## 6. Neutral spatial redistribution

OpenStudio aggregates the source People instances into six translated
People/SpaceList groups covering 141, 46, 22, 67, 27, and 1 Zones. Until an
explicit user-authored terminal-function mapping is supplied, these are named
`neutral_group_01` through `neutral_group_06`.

Spatial scenarios redistribute the aggregate baseline occupancy across these
neutral groups using declared weight vectors. The implementation preserves the
total at every 15-minute timestep, not only the daily integral. Planned
contrasts are:

- `spatial_concentrated`: occupancy weighted toward the two largest neutral
  groups;
- `spatial_distributed`: equalized by occupancy fraction relative to each
  neutral group's translated design count;
- `spatiotemporal_combined`: each spatial vector crossed with the four frozen
  temporal profiles.

Profiles that require negative occupancy, non-finite values, unresolved People
targets, or unsupported capacity assumptions are rejected and remain visible
as failed cases.

## 7. Separate volume sensitivity

Volume controls are **0.50x**, **0.75x**, **1.00x**, **1.25x**, and **1.50x**
of the baseline profile. They intentionally change passenger-hours and are
reported in a separate table. They cannot be used as evidence for the
distribution contribution and cannot convert a commonplace occupancy-volume
sensitivity into a novelty claim.

## 8. RDD-bound outputs and mechanisms

An initial discovery pass generates the exact EnergyPlus 23.1 RDD. Only names
present in that RDD are requested in the final run. The analysis seeks:

- People and Zone People occupant count;
- People sensible, latent, radiant, convective, and total heat-gain energy;
- Zone temperature, humidity, predicted load, and air-system sensible load;
- synthetic Ideal Loads heating/cooling energy and rate;
- synthetic Ideal Loads outdoor-air energy and flow;
- facility demand, unmet time, fan energy, pump energy, ventilation, and CO₂
  only when the exact RDD exposes them.

Missing outputs are recorded as `unavailable`, never as numeric zero. A
synthetic Ideal Loads or facility-demand value is not interpreted as original
terminal fan, pump, coil, AirLoop, or DCV energy.

## 9. Prespecified metrics

For every run, record input and output hashes, runtime identity, return code,
elapsed time, Severe/Fatal counts, and availability. For each supported
mechanism, report:

- daily occupancy/passenger-hours and conservation error;
- peak magnitude and clock time;
- integrated heating/cooling or heat-gain energy;
- peak and integrated difference from `existing_baseline`;
- zone heterogeneity and zone-by-time distributions;
- synthetic outdoor-air contribution separately from internal heat gains;
- unmet time and indoor state when available.

Comparisons use absolute values and baseline deltas; no statistical
significance is invented for deterministic single-run scenarios.

## 10. Failure and sensitivity rules

- A timeout, nonzero return, Severe/Fatal error, missing CSV/RDD, conservation
  failure, or invalid numeric is reported and not silently dropped.
- No alternative office, renamed public model, or replacement weather file is
  substituted for a failed terminal case.
- A 5-minute resolution may be run only as a declared sensitivity after the
  15-minute protocol succeeds; a one-minute annual sweep is out of scope.
- If source schedules cannot be resolved without guessing, temporal results
  remain a compiler demonstration rather than an operational comparison.

## 11. Admission rule

`OCCUPANCY_CASE_ADMIT` would require user-authored terminal provenance, a
stable baseline, spatially distinct People, original real HVAC response,
reproducible same-passenger-hours scenarios, and a mechanistically
interpretable nontrivial effect. Synthetic Ideal Loads alone can never meet
that gate.

The current expected upper bound is `OCCUPANCY_DEMO_ONLY`. `OCCUPANCY_NO_GO`
is used if even the controlled compiler/thermal-load path is unstable or
meaningless. Either outcome does not block or downgrade the already frozen
semantic-repair paper.

## 12. Reporting boundary

Public artifacts contain code, tests, hashes, compact aggregate tables, and
non-sensitive figures only. Raw OSM/IDF/weather/run outputs and object names
that could disclose the private modelling artifact remain local. All language
must distinguish observation, controlled comparison, interpretation, and
untested mechanism.
