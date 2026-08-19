# Airport Occupancy V3 — ABM Validation

## Result

All 600 pre-registered seed–scenario runs passed the hard route and
conservation gate. The run set contains 20 scenarios and
30 seeds per scenario (`40001..40030`).

| Check | Result |
|---|---:|
| Representative agents simulated | 3,300,000 |
| Spawned | 3,300,000 |
| Boarded/exited/staff-terminal | 3,300,000 |
| Active after horizon | 0 |
| Hard violations | 0 |
| Invalid routes | 0 |
| Passenger-through-office violations | 0 |

The equality `spawned = terminal` and zero final active agents establishes
agent conservation for this experiment matrix. Validation also enforces
domestic-departure boarding, domestic-arrival baggage-before-exit,
domestic-transfer no-baggage behavior, international Level-1 boundary exit,
role-specific access, detour return to anchor, and boarding deadlines.

## Claim boundary

Passing these checks proves internal route logic and bookkeeping consistency;
it does not validate controlled dwell/choice inputs or forecast measured airport
throughput. Every scenario therefore remains `CONTROLLED_NOT_MEASURED`.
