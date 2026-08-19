# Airport Occupancy Method Comparison

| Dimension | Historical V2 demo | V3 directed ABM |
|---|---|---|
| Source model | Older simplified terminal model | Current read-only Level-2 terminal OSM |
| Entry assumption | Two historical hall entries | Role-specific departure, arrival, international, and staff boundaries |
| Topology | Reciprocal paired-surface adjacency and BFS phase | Directed functional-process graph plus evidence-tiered Space access graph |
| Individual agents | None | Five agent classes with one-location conservation |
| Direction | 15/30/45-minute response phase | Explicit process order and directed transitions |
| Dwell | Category schedule phase | Controlled semi-Markov dwell distributions |
| Domestic departure | No boarding state | Waiting-pier endpoint, optional anchor-return detour, then board/disappear |
| Domestic arrival | No baggage-before-exit rule | Pier → public/mixed process → domestic baggage → arrival exit |
| Domestic transfer | Not represented | Pier-to-pier route with no default baggage claim |
| International arrival | Not represented | Level-2 international route → off-model Level-1 boundary |
| Staff | Fixed category schedule | Independent Staff access graph and work/break lifecycle |
| Discretionary activity | Category profile | Time-budgeted commercial/dining/restroom detour returning to route anchor |
| People coupling | Historical category schedules | Explicit Space People schedules preserving source design capacities |
| HVAC | Historical IdealLoads feasibility | Existing 14 AirLoops, 2 PlantLoops, FCUs, exhaust, heat recovery, and district boundaries |
| Output role | Thermal-demand demo | Whole-building, Zone, AirLoop, OA, fan/pump, district boundary, and unmet metrics |
| Scientific claim | Feasibility visualization | Source-constrained mechanism and controlled sensitivity analysis |

V2 remains a historical demo only. Its entry choice and BFS phases are not used
as passenger trajectories, V3 priors, or EnergyPlus schedules. V3 also remains
distinct from continuous-space pedestrian microsimulation: it targets the
minimum event and access detail needed to compile auditable BEM occupancy.
