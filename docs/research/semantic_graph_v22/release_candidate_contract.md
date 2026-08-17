# Semantic Graph V2.2 release-candidate contract

## Frozen method boundary

V2.2 closes the current relation-engine mainline at canonical IR schema
`idfrepair.semantic-graph-v2.ir.v2`.  The method remains target-free: production
scan, candidate generation, conflict construction, bounded solving, and global
closure consume only the current IDF and its exact EnergyPlus IDD.  Benchmark
operator, oracle, prototype, file-name, and source-membership hints are outside
the runtime API.

The release-candidate boundary contains the already admitted Branch,
Loop/Connector, and Zone relations plus these compound-flow frontiers:

- SupplyPath members projected as version-bound `SPLIT` transitions for
  `AirLoopHVAC:ZoneSplitter` and `AirLoopHVAC:SupplyPlenum`;
- ReturnPath members projected as version-bound `MERGE` transitions for
  `AirLoopHVAC:ZoneMixer` and `AirLoopHVAC:ReturnPlenum`;
- normal `AirLoopHVAC:OutdoorAirSystem` equipment paths containing
  `OutdoorAir:Mixer` alone or
  `HeatExchanger:AirToAir:SensibleAndLatent` followed by
  `OutdoorAir:Mixer`;
- the Mixer's outdoor-to-mixed primary stream and return-to-relief auxiliary
  stream, and the heat exchanger's supply and exhaust circuits.

Within that boundary, AirPath constraint `V2-AIRPATH-TYPED-MEMBER-009` and OA
constraint `V2-OA-EQUIPMENT-PATH-010` are `ADMIT_SAFE_AUTO`.  Their admission is
limited by exact object type, exact 22.1/24.1 IDD field identity, complete
projection, resolved member identity, complete candidate enumeration, and
whole-model closure.  It is not a declaration that every EnergyPlus AirPath or
OA component is supported.

## Compound-flow evidence contract

Atomic `PortRef` facts are promoted only by an exact object/version/token/name
registry match.  Repeated ports additionally require the official IDD
begin-extensible field and group width.  A `CompoundFlowProjection` is complete
only when every topology-specific transition satisfies required cardinality,
nonblank and unique exact nodes, one object and medium, matching rule/version,
and complete transition provenance.

The supported forms are `DIRECT`, `SPLIT`, `MERGE`, `MULTI_CIRCUIT`, and
`COUPLED_MULTI_STREAM`.  A transition records object identity, input and output
ports, medium, stream/circuit, primary or auxiliary traversal role, rule ID,
rule version, and applicability.  An enum value alone can never certify
completeness.

AirPath validation traverses the entire declared member sequence.  OA primary
traversal follows the official EquipmentList order; Controller:OutdoorAir A5
anchors the inlet of the first pretreat component, while Mixer mixed, return,
and relief nodes provide the other controller anchors.  Reverse auxiliary
closure is positive evidence for a proposed HX/Mixer repair.  It is not
universalized into a standalone hard invariant for every legal OA equipment
list.

## Candidate and commit contract

Candidate completeness means complete enumeration of the admitted semantic
domain, not merely finding one plausible edit.  Typed replacements enumerate
all exact-type identities; compound OA order edits enumerate all complete
permutations within the bounded admitted list.  Unsupported objects,
unresolved identities, incomplete projections, missing controller context,
DedicatedOutdoorAirSystem cases, or unbounded/ambiguous scopes abstain.

Every candidate materializes exact field-value and relation-state
preconditions for all provenance it read.  Search is exact and bounded.  The
objective minimizes `(semantic edit count, distinct field edit count)` and
uniqueness is computed after deduplicating identical field effects.  A repair
is committed only after reparsing, rebuilding IR, and confirming that global
hard-violation closure matches the independently solved components.

Default bounds are eight violations per conflict component, 24 candidate
semantic edits, four selected semantic edits, and 256 evaluated edit sets.
Crossing a bound returns `SEARCH_EXHAUSTED`; nonunique minima return
`NEEDS_INPUT`.  Neither state permits a first-found commit.

## Explicit exclusions and stopping rule

- `HeatExchanger:AirToAir:FlatPlate` has a rigorous compound projection but no
  observed DOE admission frontier in this development corpus, so OA automatic
  repair abstains on it.
- DedicatedOutdoorAirSystem projection/repair, generic unsupported AirPath/OA
  components, and arbitrary auxiliary-circuit rewiring remain outside scope.
- Controller ownership remains detect-only and controller actuator repair
  remains rejected; controller fields are read-only OA context.
- No new Branch simple-component port rule is admitted in V2.2.  The frontier
  audit identifies a future shortlist, but this release does not chase the
  frozen benchmark score or widen the user-authorized Air/OA scope.
- Geometry, sizing, schedules, loads, efficiencies, external intent, LLM/RAG,
  and additional fault families remain frozen.

With zero hard false positives on the 30 qualified clean topologies, complete
candidate domains and zero wrong/partial-as-full commits on the independent
extension set, preserved frozen V2.1 membership, and the recorded regression
and dynamic gates, the method stops expanding.  The next task may verify this
freeze and run the sealed Formal Final once; it must not tune the method from
that Final.
