# V2.2 outdoor-air EquipmentList semantics

## Context and support boundary

`V2-OA-EQUIPMENT-PATH-010` now binds an ordinary
`AirLoopHVAC:OutdoorAirSystem` to its EquipmentList, ControllerList, and unique
`Controller:OutdoorAir`. The controller's official relief, return, mixed, and
actuator/outdoor node fields are retained as exact read-only topology anchors.
Controller repair remains frozen.

An OutdoorAirSystem owned by
`AirLoopHVAC:DedicatedOutdoorAirSystem` is classified as dedicated context.
It is not required to contain an `OutdoorAir:Mixer` and is outside this
constraint's hard applicability. Ambiguous ownership, unresolved controllers,
partial typed-reference groups, unsupported members, or incomplete compound
projections also abstain.

The present admitted component vocabulary is `OutdoorAir:Mixer` and
`HeatExchanger:AirToAir:SensibleAndLatent`. A version-bound FlatPlate
projection exists in the IR, but the audited development corpus contains no
FlatPlate EquipmentList occurrence, so it remains outside OA SAFE_AUTO
applicability rather than being admitted on projection tests alone.

## Coupled traversal closure

For a normal context, exactly one Mixer must be the final declared member.
Its primary transition is outdoor-air inlet to mixed-air outlet; its auxiliary
transition is return-air inlet to relief-air outlet. Both are checked against
the four controller anchor nodes.

Upstream heat recovery objects retain two circuits. Their primary transitions
must connect forward in EquipmentList order into the Mixer. Their auxiliary
exhaust/relief transitions must connect in reverse order from the Mixer relief
side. Thus a list is not closed when only the primary chain matches: a broken
auxiliary node remains a violation and cannot be committed as a partial repair.

## Candidate completeness

The scanner exhaustively evaluates, within the supported bounded scope:

- every single-slot typed replacement from the complete supported-object
  universe; and
- every permutation of the current resolved members, with a hard bound of
  seven members.

Only alternatives that close the controller anchors, primary traversal, and
reverse auxiliary traversal are exposed. Candidate generation materializes
the corresponding typed-reference or ordered type/name field edits and guards
all source and projection evidence. Multiple equal alternatives abstain;
unsupported or unbounded scopes never become complete candidate domains.

No string similarity, prototype name, mutation operator, clean donor, or
oracle is available to the production scanner or candidate generator.

An auxiliary inconsistency with no closing EquipmentList type/name/order
alternative is not itself a hard list-field invariant. The scanner abstains in
that case; it uses the relief circuit only as required evidence for a proposed
list repair. This prevents a component-internal or controller-node fault from
being mislocalized as an EquipmentList edit.

## Admission status

Final Node 4 decision: `PROMOTE_SAFE_AUTO` for normal-context Mixer-only and
sensible/latent-HX-to-Mixer scopes. The 30-clean gate covered 220 OA lists with
zero findings, and the independent extension supplied exact typed and order
repairs across multiple prototypes/topologies with zero wrong modification or
partial-as-full result. DOAS, FlatPlate, unsupported members, incomplete
projection, unresolved controller, duplicate identity, and no-closing-list-
alternative scopes remain abstentions.
