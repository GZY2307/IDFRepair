# Daxing Level-2 entrance-flow evidence boundary

**Status:** `CONTROLLED_NOT_MEASURED`  
**Model annotation:** `z-u-hall-2` and `z-u-hall-3` are the two entrances  
**Annotation authority:** model author, explicitly supplied 2026-08-18

## What the external floor plan supports

- The [China Southern Beijing Daxing Airport guide](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/1dpdb182j8mei.shtml)
  identifies Level 2 as a mixed domestic departure/arrival, international-arrival,
  transfer, and domestic baggage-claim level.
- China Southern's [official Level-2 plan](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/resource/94bd66d86448bed879eec31183612977.PNG)
  shows the multi-arm Level-2 spatial context. The locally reviewed reference image
  was 2000 × 1200 pixels with SHA-256
  `df4c8ffe04a8b08efb753577c601fca3f56f4093f5310551bf5fd1aa9b27dbfb`.
- The [Beijing municipal Daxing Airport introduction](https://zdzqgw.beijing.gov.cn/zqfw/bjdxgjjc/bjdxgjjcjs/202410/t20241012_3917907.html)
  independently describes the five-pier form and the Level-2 domestic-arrival
  function.

These sources were accessed 2026-08-18. They support using more than one controlled
spatiotemporal stream, but they do **not** map the simplified source OSM's rooms to
check-in, gates, baggage, security, doors, passenger itineraries, or real HVAC.

## Source-model topology actually used

The private Baseline R derivative retains the source People→Space→Zone relations. Its
304 Space/Zone pairs yield one connected graph from 873 reciprocal paired-surface
relations and 639 unique Zone adjacency edges. The two user-confirmed entrance Spaces
split the model into two deterministic regions of 152 Spaces each. Breadth-first Zone
hops select the nearer entrance; area-weighted source floor centroids only break
equal-hop ties.

For public-dynamic rooms, within-region hop terciles create 15, 30, and 45 minute
**occupancy-response phases**. The two entrance Spaces remain at the 0-minute phase. Office and
breakroom staff schedules remain unshifted. The phase distribution is:

| Controlled phase | Space count | Interpretation |
|---:|---:|---|
| 0 min | 80 | two entrances plus 78 staff Spaces |
| 15 min | 90 | near public-response band |
| 30 min | 77 | middle public-response band |
| 45 min | 57 | far public-response band |

The phases are not walking times. Every schedule change is a circular shift, so each
Space retains its exact 96 values and person-hours. Reciprocal `entrance_2_lead` and
`entrance_3_lead` cases lead one region by 30 minutes and lag the other by 30 minutes,
again preserving every Space and whole-building integral.

Exact centroids and direct distances remain private. The public mapping contains only
Space/category, entrance region, adjacency hops, response band, and the interpretation
boundary.
