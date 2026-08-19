# Airport Occupancy V3 — Public Agent Route Registry

This registry publishes process order without airport room identifiers.

| Agent class | Functional lifecycle | Terminal state |
|---|---|---|
| Domestic departure | departure boundary → public/central process → domestic waiting → optional anchor-return detour | board and leave model |
| Domestic arrival | domestic waiting → mixed/public process → domestic baggage → arrival boundary | out |
| Domestic transfer | domestic waiting → mixed/public process → a different domestic waiting group | board; no baggage |
| International arrival | Level-2 international arrival → international process → vertical boundary | off-model Level-1 immigration |
| Staff | staff boundary → assigned office → optional staff activity → assigned office → staff boundary | staff exit |

Only the domestic-waiting function can be a domestic gate endpoint. Concourse
is transit. International arrival does not use Level-2 domestic baggage because
the official process continues to Level 1 outside this model. Staff routing is
independent from passenger routing.

Gate selection uses source design capacity as a controlled weight. Dwell,
choice, class mix, and flight-bank timing are `CONTROLLED_NOT_MEASURED`; none
is presented as a measured airport distribution.
