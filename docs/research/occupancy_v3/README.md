# Airport Occupancy V3

Airport Occupancy V3 is a generic, access-constrained directed discrete-event
agent-based occupancy compiler for OpenStudio/EnergyPlus workflows. It turns
validated passenger and staff events into 15-minute Space-level People
schedules while preserving the source building and HVAC model.

The public material contains:

- the evidence-tiered graph, routing, dwell, event, validation, schedule, and
  EnergyPlus output modules under `src/idfrepair/analysis/airport_abm/`;
- a geometry-free five-class fixture under `examples/airport_abm_v3/`;
- focused unit tests that need no private airport model;
- aggregate method, uncertainty, energy, visualization, and admission reports.

The public material does not contain raw or derived OSM/IDF models, weather,
drawings, exact airport room mappings, coordinates, raw simulation directories,
or measured passenger data.

## Synthetic smoke test

```bash
python examples/airport_abm_v3/run_synthetic.py \
  --fixture examples/airport_abm_v3/synthetic_terminal.json
```

Expected result: `PASS`, five terminal agents, zero active agents, and zero
violations. The fixture is a software demonstration, not an airport forecast.

## Scientific boundary

Airport ABM, dynamic occupancy schedules, discretionary activity models, and
BEM coupling are established methods. V3's bounded contribution is the
source-constrained OSM/IDF integration: model-derived room/HVAC semantics,
separate Passenger/Staff access, explicit off-model boundaries, People-only
schedule compilation, and controlled comparisons of equal passenger-hours
under different temporal and spatial distributions.
