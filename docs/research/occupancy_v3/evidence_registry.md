# Airport Occupancy V3 Evidence Registry

## Evidence tiers

| Tier | Meaning | Permitted use |
|---|---|---|
| `SOURCE_MODEL_FACT` | Directly parsed from the read-only OSM | Room function, People capacity, Zone/HVAC binding, explicit Door |
| `SOURCE_DRAWING_FACT` | Visible in user-provided architectural/HVAC material | Building/HVAC partition or equipment context only |
| `OFFICIAL_PROCESS_EVIDENCE` | Published airport/airline process description | Functional sequence and off-model floor boundary |
| `USER_RESTRICTION` | Explicit route or publication constraint | Directed access and blocked-edge configuration |
| `LITERATURE_METHOD` | Established peer-reviewed method | Method choice and claim boundary |
| `CONTROLLED_NOT_MEASURED` | Pre-registered experiment input without local measurement | Dwell, choice, timing, class mix, and sensitivity only |

## Source model and drawing evidence

The current Level-2 terminal OSM supplies Space functions, People definitions,
explicit Doors, Thermal Zones, 14 AirLoops, 2 PlantLoops, 75 four-pipe fan coils,
27 exhaust fans, 7 heat-recovery units, and the People → Space/Zone → HVAC
bindings. The model contains zero IdealLoads and its mechanical-ventilation
controllers have demand-controlled ventilation disabled.

The user-provided TIFF/DWG material supports building partition, HVAC zoning,
system design, and room-design context. The audit did not locate a passenger
circulation drawing. Its formal finding is `FLOW_DETAIL_NOT_PRESENT_IN_TIFF`;
HVAC partition lines are never converted into walking edges.

## Official process evidence

The [China Southern Daxing airport guide](https://www.csair.com/sg/en/tourguide/airport_service/airports_info/domestic/1e0urvhl3bead.shtml)
places domestic departure, domestic arrival, domestic baggage, transfer, and
international arrival on Level 2, while international immigration and baggage
claim are on Level 1. This supports an international-arrival vertical boundary
instead of an invented Level-2 domestic-baggage path. The airline's
[Daxing transfer process](https://www.csair.com/tw/zh/tourguide/airport_service/transfers/beijing/transferProcess_dx/)
provides additional process-order context.

## Airport-wide throughput context and controlled model mapping

The Beijing municipal government reported 53.61 million passengers at Daxing
in 2025, an annual-average context of about 146,877 passenger movements/day
([source](https://www.beijing.gov.cn/gongkai/shuju/sjjd/202601/t20260103_4393186.html)).
The 2025 summer peak period averaged 154,300 passengers and 981 flights/day
([source](https://www.beijing.gov.cn/ywdt/gqrd/202509/t20250903_4189882.html)).
These are airport-wide aggregates, not Level-2 counts. V3 maps the annual
average onto its simplified Level-2 route cohort only as a declared
`CONTROLLED_NOT_MEASURED` demonstration assumption; it does not infer a floor
coverage rate, class split, gate count, 15-minute profile, or dwell time.

An official airline release includes a scheduled Osaka–Daxing arrival at
00:30/01:30, which is sufficient to reject a hard zero overnight assumption
but not to estimate an overnight passenger rate
([source](https://assets.kansai-airports.co.jp/dfc31804-e-kn.pdf)). V3 therefore
uses class-specific controlled 24-hour probability windows and periodic
cross-midnight integration; timing-bank scenarios retain an 18% baseline tail.

## Literature evidence and overlap

| Study | Evidence used here | What V3 does not claim |
|---|---|---|
| Sinha et al. 2019, Building Simulation | Airport ABM → dynamic occupancy schedule → HVAC coupling | First airport ABM/BEM coupling |
| Liu et al. 2019, *Building and Environment* | Field-informed passenger distribution can materially alter local HVAC/OA demand | Local field validation |
| Sinha et al. 2021, *Building and Environment* | Dynamic sensible/latent gains vary by activity and location | Thermophysiological calibration |
| Gu et al. 2022, *Sustainable Cities and Society* | Spatiotemporal terminal distribution affects zone energy results | First spatial energy coupling |
| Mekić et al. 2021, *Aerospace* | Discretionary activity depends on free-time budget and process constraints | Cognitive activity-choice model |

## Controlled registry

The following are never presented as measured Daxing inputs:

- 2,400 domestic-departure, 1,600 domestic-arrival, 600 domestic-transfer,
  400 international-arrival, and 500 staff representative agents/day;
- 5-minute process transit;
- 60–90-minute baseline domestic gate wait and its 30–60/90–120 sensitivities;
- 45–75-minute transfer wait and 20-minute baggage dwell;
- 0.35 baseline discretionary probability, 15-minute visit, and 0.05/0.80
  low/high sensitivities;
- 480-minute controlled staff work dwell and controlled break behavior;
- capacity-weighted gate assignment;
- morning, midday, evening, and double-bank timing transforms;
- all within-day probability weights and the 0.82 bank-mixture fraction;
- composition and 0.50–1.50x passenger-volume sensitivities.

None of these values is adjusted after viewing EnergyPlus results.
