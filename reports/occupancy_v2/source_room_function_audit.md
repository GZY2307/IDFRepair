# Source room-function and People audit

**Audit status:** `SOURCE_ROOM_MAPPING_VALIDATED`

## Source-preserving audit boundary

This is a source-preserving audit of **Terminal Model A**. The OSM was
loaded read-only through OpenStudio; its SHA-256 was identical before and
after the audit. No source or derived OSM is distributed with this report.

## Identity and completeness

- Source SHA-256: `6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb`
- Runtime: OpenStudio 3.6.1 / OSM 3.6.1
- Spaces: **304**
- ThermalZones: **305**
- Orphan zones: **1** (xbrestroom2)
- Unknown or multi-token Spaces: **0**
- Metadata conflicts: **1**
- Non-People source snapshot: `59a1a217c9ad12fcf4dd8ba2b02c9df560c23c0957ce9cc1aef9388205ac00e3` (7496 objects)

## Six source-name categories

| Category | Spaces | Floor area (m²) | Design people | people/m² | m²/person | Defaulted SpaceType |
|---|---:|---:|---:|---:|---:|---:|
| terminal_hall | 126 | 150117.49 | 8079.256 | 0.05382 | 18.581 | 126 |
| office | 69 | 20239.357 | 1036.447 | 0.051209 | 19.528 | 1 |
| commerce_retail | 51 | 13348.413 | 1772.554 | 0.132791 | 7.531 | 5 |
| dining | 22 | 4713.507 | 507.358 | 0.107639 | 9.29 | 0 |
| restroom | 27 | 7190.123 | 773.938 | 0.107639 | 9.29 | 0 |
| breakroom | 9 | 1516.693 | 81.628 | 0.05382 | 18.581 | 9 |

Classification uses only the case-insensitive `hall`, `office`,
`commerce`, `dining`, `restroom`, and `breakroom` tokens in
`OS:Space.Name`. Geometry and airport conventions do not create
check-in, gate, baggage, security, arrivals, or departures labels.

## Why the historical translated grouping is not a room-function result

The Building default SpaceType is `189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8`.
It is inherited by **141** Spaces
whose source-name room functions are mixed. Therefore a translated People
group based on this archetype is not an airport room-function group.

| Category | Effective SpaceTypes | People method(s) | Number schedule(s) | Activity schedule(s) | OA definition(s) |
|---|---|---|---|---|---|
| terminal_hall | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area | Large Office Bldg Occ | Large Office Activity | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 Ventilation |
| office | 189.1-2009 - Office - ClosedOffice - CZ4-8 1 <br> 189.1-2009 - Office - IT_Room - CZ1-3 <br> 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area | Large Office Bldg Occ <br> Office Misc Occ <br> Office Work Occ | Large Office Activity <br> Office Activity | 189.1-2009 - Office - ClosedOffice - CZ4-8 Ventilation <br> 189.1-2009 - Office - IT_Room - CZ1-3 Ventilation <br> 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 Ventilation |
| commerce_retail | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 <br> Retail Retail | People/Area | Large Office Bldg Occ <br> RetailStandalone BLDG_OCC_SCH | Large Office Activity <br> RetailStandalone ACTIVITY_SCH | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 Ventilation <br> Retail Retail Ventilation |
| dining | Office Dining | People/Area | OfficeLarge BLDG_OCC_SCH | OfficeMedium ACTIVITY_SCH | Office Dining Ventilation |
| restroom | 189.1-2009 - Office - Restroom - CZ4-8 | People/Area | Office Misc Occ | Office Activity | 189.1-2009 - Office - Restroom - CZ4-8 Ventilation |
| breakroom | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 | People/Area | Large Office Bldg Occ | Large Office Activity | 189.1-2009 - Office - WholeBuilding - Lg Office - CZ4-8 Ventilation |

## Metadata conflicts

| Source Space | Name category | Explicit SpaceType | Status | Conflict |
|---|---|---|---|---|
| z-u-office-11 | office | 189.1-2009 - Office - IT_Room - CZ1-3 | SOURCE_METADATA_CONFLICT | office_name_vs_it_room_space_type |

## People → Zone → HVAC boundary

Every classified Space retains its explicit source ThermalZone identity. The source contains **0** zone-equipment assignments in the audited model. Absence of source AirLoop/PlantLoop topology is not repaired 
by inference; later thermal-demand experiments use a separately labelled 
IdealLoads derivative only.

## Interpretation guard

These values describe source metadata, not measured airport operations.
The reference derivative may replace only People fields supported by the
evidence registry. Lighting, equipment, infiltration, constructions,
geometry, SpaceTypes, and source OA remain unchanged in the main People-only
comparison.
