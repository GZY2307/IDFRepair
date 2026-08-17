# Room Function Registry

**Status:** `SOURCE_BACKED_SIX_CATEGORY_REGISTRY`

The registry binds each of 304 source Spaces to one room category using only
an explicit `OS:Space.Name` token. It does not infer airport subfunctions from
geometry, orientation, adjacency, or convention. Values marked Tier C are
controlled and not measured.

Source alias: Terminal Model A · SHA-256 `6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb`

| Category | Spaces | Area (m²) | Source design people | Proposed People model | Schedule evidence | Confidence | Auto-fill |
|---|---:|---:|---:|---|---|---|---|
| terminal_hall | 126 | 150117.49 | 8079.256 | one explicit People object per Space; PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK | 15-minute controlled public profile; temporal/spatial redistribution target [TIER_C_CONTROLLED_NOT_MEASURED] | REJECTED_AMBIGUOUS_TRANSFER | false |
| office | 69 | 20239.357 | 1036.447 | one explicit People object per Space; 6 m2/person | 15-minute staff workday profile; bitwise fixed in public scenarios [TIER_C_CONTROLLED_NOT_MEASURED] | HIGH_PROJECT_SPECIFIC | true |
| commerce_retail | 51 | 13348.413 | 1772.554 | one explicit People object per Space; 5 m2/person | 15-minute controlled operating/public-demand profile; unsplit public-facing class [TIER_C_CONTROLLED_NOT_MEASURED] | HIGH_PROJECT_SPECIFIC | true |
| dining | 22 | 4713.507 | 507.358 | one explicit People object per Space; 2.5 m2/person | 15-minute controlled meal-period profile; unsplit public-facing class [TIER_C_CONTROLLED_NOT_MEASURED] | HIGH_PROJECT_SPECIFIC | true |
| restroom | 27 | 7190.123 | 773.938 | one explicit People object per Space; PRESERVE_SOURCE_DESIGN_COUNT_FALLBACK | 15-minute bounded profile linked to public presence; no dwell-time claim [TIER_C_CONTROLLED_NOT_MEASURED] | REJECTED_MISSING_DWELL_EVIDENCE | false |
| breakroom | 9 | 1516.693 | 81.628 | one explicit People object per Space; 3.7161216 m2/person | 15-minute intermittent staff break profile; bitwise fixed in public scenarios [TIER_C_CONTROLLED_NOT_MEASURED] | MEDIUM_STANDARD_DEFAULT | true |

## Current source metadata and proposed evidence

| Category | Current SpaceType(s) | Current People density | Current schedule(s) | Activity evidence | Main OA | Reference OA |
|---|---|---|---|---|---|---|
| terminal_hall | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area=0.05381955 | Large Office Bldg Occ | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | DO_NOT_AUTOFILL |
| office | 189.1-2009 - Office - ClosedOffice - CZ4-8 1 <br> 189.1-2009 - Office - IT_Room - CZ1-3 <br> 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area=0.05112857 <br> People/Area=0.05381955 | Large Office Bldg Occ <br> Office Misc Occ <br> Office Work Occ | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | PROJECT_HVAC_NOTES_SJSM05: 0.00833333 m3/s-person |
| commerce_retail | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 <br> Retail Retail | People/Area=0.05381955 <br> People/Area=0.16145866 | Large Office Bldg Occ <br> RetailStandalone BLDG_OCC_SCH | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | PROJECT_HVAC_NOTES_SJSM05: 0.00833333 m3/s-person |
| dining | Office Dining | People/Area=0.1076391 | OfficeLarge BLDG_OCC_SCH | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | PROJECT_HVAC_NOTES_SJSM05: 0.00694444 m3/s-person |
| restroom | 189.1-2009 - Office - Restroom - CZ4-8 | People/Area=0.1076391 | Office Misc Occ | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | DO_NOT_AUTOFILL |
| breakroom | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area=0.05381955 | Large Office Bldg Occ | preserve source activity/heat/CO2 fields [TIER_A_SOURCE_BACKED] | preserve source OA in People-only S/R comparison | ASHRAE_62_1_2022_AB: 0.0003 m3/s-m2 <br> ASHRAE_62_1_2022_AB: 0.0025 m3/s-person |

## Unresolved assumptions

- `terminal_hall` — Source room subtype and operational flow are unresolved; source design count is retained as capacity fallback.
- `office` — Staff attendance is controlled, not measured; one IT_Room metadata conflict retains source People parameters.
- `commerce_retail` — Customer/staff composition and operating records are unavailable.
- `dining` — Diner/staff composition and meal demand are unavailable.
- `restroom` — No occupancy dwell model; documented exhaust cannot be mapped to source HVAC topology.
- `breakroom` — Standard default is not measured airport staff utilization.

The per-Space source audit remains authoritative for the one office/IT_Room
metadata conflict. The reference derivative does not overwrite that row's
People definition parameters.
