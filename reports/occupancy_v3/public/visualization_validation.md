# Airport Occupancy V3 — Visualization Validation

Status: `PASS_CONTROLLED_DEMO`

## Integrated workbench result

The private V3 payload and a People-only IDF derivative were loaded in the
existing IDFRepair 3D workbench. The source OSM remained read-only. Occupancy is
still an optional local layer on top of the IDF geometry; loading or clearing it
does not replace the model session.

| Check | Result |
|---|---:|
| IDF geometry surfaces | 2,629 |
| Fenestration surfaces | 396 |
| Mapped Spaces | 304 |
| V3 schema and 96 × 15 min intervals | PASS |
| All + five agent-class filters | PASS |
| Count, people/m², and source-capacity modes | PASS |
| Values above 100% source capacity use red | PASS |
| Combined chart and direct time scrub | PASS |
| Separate real heating and cooling series | PASS |
| Details close persists during playback | PASS |
| Details show/hide and control-bar minimize | PASS |
| Draggable details DOM/pointer contract | PASS |
| Hover outside a room returns whole-model details | PASS |

The local-data buttons share the same dimensions and are placed in the session
action bar rather than inside the 3D viewport. The former optional-JSON and
Space/scenario status strings are absent. On a loaded desktop session, the
issue navigator, model view, and inspector use the extended workbench height;
the result section follows below them.

## Exact Space-edge flow layer

The previous function-centroid arrows were removed. The viewer now consumes
`space_edge_flows`, preserving source node, target node, source Space, target
Space, agent class, evidence layer, condition, door instances, roles, and
off-model-boundary direction. It does not merge geographically separate edges
that happen to share a function pair.

At `12:30–12:45` for the fixed-seed baseline payload, browser inspection found:

| Active edge item | Count |
|---|---:|
| Total rendered items | 205 |
| Explicit OSM Door edges | 6 |
| Controlled process-abstraction edges | 156 |
| Incoming/outgoing model-boundary markers | 43 |
| Missing geometry anchors | 0 |
| Collapsed short arrows | 0 |

Explicit Door edges are solid, controlled process edges are dashed, and virtual
entry/exit nodes are one-sided boundary markers. These graphics show directed
semantic/process transitions, not measured passenger trajectories.

## Occupancy and load interaction

The chart cursor, time label, room colours, exact edge flows, and detail table
update from the same interval index. The fixed-seed baseline SQL supplied both
thermal series; at the inspected interval the whole-model detail reported
`0.75 / 5,588.44 kWth` for heating/cooling. Closing the detail table and starting
playback left it closed; the bottom `Details` button reopened it. Minimizing the
bottom controls retained the play button, current time, details button, and
compact scrubber.

When the pointer has no room intersection or leaves the render canvas, the
detail card shows the whole-model aggregate instead of retaining the last room.
The card can be repositioned only within the canvas and above the bottom
controls.

## Claim boundary

Space colour represents controlled ABM occupancy at the selected interval.
Arrow width represents controlled edge flow per 15 minutes. Individual
passenger dots are deliberately absent because the source does not resolve
measured walking trajectories. This validation proves local payload/viewer
integration and evidence-layer display; it does not validate real passenger
positions, observed route choice, or airport throughput.
