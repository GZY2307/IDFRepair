# Baseline R — room-aware reference

**Status:** `ROOM_AWARE_REFERENCE_CONTROLLED_NOT_MEASURED`
**Derived OSM SHA-256:** `f21696e719c620bf036ed4f536ea7b9959545d778b5705bea1d1333ebc0b78cf`
**Derived IDF SHA-256:** `a94538ecdfdc72353f02c01440277411b0035a991333a33922e3d595c3f42d11`

Baseline R creates one explicit People object per Space and 304 IdealLoads endpoints.
It does not change SpaceType, lighting, equipment, infiltration, main-study OA,
geometry, construction or source zone semantics. Protected-object before/after hashes
are both `8e95fa691368a41c79d0004e98a773ce34d8c4d413aafe40e4ab27feeb4fa9b7`;
`non_people_fields_modified = 0`.

| Category | Source design people | R design people | Capacity Δ | Day person-h | Annual person-h |
| --- | --- | --- | --- | --- | --- |
| terminal_hall | 8,079.26 | 8,079.26 | +0.00% | 58,615.00 | 21,394,476.06 |
| office | 1,036.45 | 3,316.47 | +219.98% | 28,621.12 | 10,446,709.90 |
| commerce_retail | 1,772.55 | 2,669.68 | +50.61% | 20,316.28 | 7,415,443.89 |
| dining | 507.36 | 1,885.40 | +271.61% | 11,698.92 | 4,270,107.19 |
| restroom | 773.94 | 773.94 | +0.00% | 1,606.84 | 586,494.89 |
| breakroom | 81.63 | 408.14 | +400.00% | 1,381.55 | 504,265.63 |

## Parameter decisions

- Tier B project-note densities: office 6, commerce 5 and dining 2.5 m²/person.
- Tier B standard density: breakroom 3.7161216 m²/person.
- `DO_NOT_AUTOFILL`: hall density (non-equivalent source rows) and restroom density (no dwell model); source counts remain capacity fallbacks.
- `z-u-office-11` is flagged `SOURCE_METADATA_CONFLICT`. Its source design count,
  activity, Fraction Radiant, sensible fraction and CO₂ rate are retained, while its
  source People number schedule is deliberately replaced by the controlled office
  profile. The conflict is not treated as resolved.
- Tier A retained: activity, Fraction Radiant, autocalculated sensible fraction, CO₂ generation and main-study OA definitions.
- Tier C controlled/not measured: all six 15-minute profile shapes.
- Documented reference OA rates and 15 ACH restroom exhaust are not implemented in the main S/R comparison; no source-backed real-HVAC topology was synthesized.

## Occupant-class accounting and S/R contrast

Representative-day R contains 58,615.00 terminal-hall passenger-h,
30,002.67 staff person-h, 32,015.21
public-facing-unsplit person-h and 1,606.84 public-linked person-h,
total 122,239.72 person-h. Reference capacity changes from
12,251.18 to 17,132.89
people. Day person-hours change from 115,063.23 to
122,239.72; annual person-hours from
32,592,469.43 to 44,617,497.56.
This is an assumption contrast, not evidence that the source airport was underoccupied.
