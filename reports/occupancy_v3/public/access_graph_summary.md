# Airport Occupancy V3 — Public Access-Graph Summary

The private terminal mapping was compiled into separate Passenger and Staff
graphs. This public summary reports evidence layers and function-level behavior
only; it contains no exact room mapping or coordinates.

| Audit item | Passenger graph | Staff graph |
|---|---:|---:|
| Directed explicit-Door edges | 76 | 96 |
| Directed functional abstractions | 2,990 | 1,300 |
| Directed thermal-adjacency candidates | 1,278 | 1,278 |
| Routable edges | 3,066 | 1,396 |
| Thermal candidates admitted to routing | 0 | 0 |

The OSM contains 49 reciprocal physical Door pairs forming 48 unique
Space-to-Space connections. One Space pair contains two distinct physical
doors; this is why the two counts differ.

All 11 registered reachability/isolation assertions passed. In functional
terms, the graph establishes:

- departure boundary → public spine → all four domestic waiting-pier groups →
  boarding boundary;
- domestic waiting → public spine → domestic baggage → arrival boundary;
- domestic gate-to-gate transfer without baggage;
- international Level-2 arrival → international process → off-model Level-1
  boundary, without domestic baggage;
- passenger paths that cannot traverse office, breakroom, or information-room
  functions;
- a separate Staff graph with access to assigned work functions.

Commercial, restaurant, and restroom nodes are optional destinations only.
They are not mandatory shortcuts and every accepted detour returns to its
original route anchor. Functional edges remain labelled abstractions; they are
not represented as measured walking trajectories.
