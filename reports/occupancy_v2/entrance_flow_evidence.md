# Entrance-seeded room-aware occupancy flow

**Status:** `CONTROLLED_NOT_MEASURED`
**Entrance seeds:** `z-u-hall-2`, `z-u-hall-3` (explicit user-provided source-model annotation)
**Interpretation:** occupancy-response phases, not passenger trajectories or walking time

The source-preserving Baseline R IDF yields 873
reciprocal paired-surface relations and 639 unique
Zone-to-Zone adjacency edges. All 304 Space/Zone pairs form one connected semantic
graph. A breadth-first hop count from the two declared entrances assigns each room to
its nearer entrance; an area-weighted source floor centroid breaks equal-hop ties.
No door, gate, check-in, baggage, security, or real-HVAC route is inferred.

| Entrance Space | Source Zone | Assigned seed | Hops | Phase min | Region Spaces |
| --- | --- | --- | --- | --- | --- |
| z-u-hall-2 | zuhall2 | z-u-hall-2 | 0 | 0 | 152 |
| z-u-hall-3 | zuhall3 | z-u-hall-3 | 0 | 0 | 152 |

| Phase steps | Spaces | Controlled phase min |
| --- | --- | --- |
| 0 | 80 | 0 |
| 1 | 90 | 15 |
| 2 | 77 | 30 |
| 3 | 57 | 45 |

Public-dynamic rooms are divided into near/middle/far hop terciles within each entrance
region and shifted by 15/30/45 minutes; the two entrance Spaces stay at phase zero.
Office and breakroom staff profiles are not entrance-delayed. Circular shifts preserve
the exact 96-value multiset and therefore every Space's daily person-hours. Reciprocal
`entrance_2_lead` / `entrance_3_lead` cases then lead one region by 30 minutes and lag
the other by 30 minutes, preserving every Space and whole-building integral.

## External spatial context and limits

The [China Southern Beijing Daxing Airport guide](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/1dpdb182j8mei.shtml)
identifies Level 2 as a mixed domestic departure/arrival, international-arrival,
transfer, and domestic baggage-claim level; its [official Level-2 plan](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/resource/94bd66d86448bed879eec31183612977.PNG)
shows the multi-arm spatial context. The [Beijing municipal airport introduction](https://zdzqgw.beijing.gov.cn/zqfw/bjdxgjjc/bjdxgjjcjs/202410/t20241012_3917907.html)
independently describes the five-pier form and Level-2 domestic-arrival function.
These sources motivate multiple time/space streams only; they do not map this simplified
OSM's rooms to airport operational functions. Sources accessed 2026-08-18.

The coordinate-free review mapping is `entrance_flow_mapping.csv`. Exact centroids
remain in the private derived topology and are excluded from public distribution.
