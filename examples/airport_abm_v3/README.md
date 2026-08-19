# Airport ABM V3 synthetic fixture

This geometry-free example exercises all five agent classes against a small
directed process graph. It contains no airport room names, coordinates,
measured passenger data, building model, weather file, or HVAC inputs.

Run it from the repository root:

```bash
python examples/airport_abm_v3/run_synthetic.py \
  --fixture examples/airport_abm_v3/synthetic_terminal.json
```

The result must report `PASS`, five spawned and terminal agents, zero active
agents, and zero validation violations. The fixture demonstrates software
behavior only; it is not a calibrated airport-flow case.
