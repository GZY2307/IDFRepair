# V2.2 AirPath topology semantics

## Supported relation frontier

`V2-AIRPATH-TYPED-MEMBER-009` now evaluates a member-induced compound-flow
graph rather than requiring every component to expose one inlet/outlet pair.
The admitted object vocabulary is deliberately closed:

- `AirLoopHVAC:SupplyPath`: `AirLoopHVAC:ZoneSplitter` and
  `AirLoopHVAC:SupplyPlenum`;
- `AirLoopHVAC:ReturnPath`: `AirLoopHVAC:ZoneMixer` and
  `AirLoopHVAC:ReturnPlenum`.

Each referenced object must have exactly one complete, version-bound V2.2
projection. Partial typed-reference groups, duplicate identities, unsupported
members, incomplete projections, or an incomplete supported-object universe
make the scope inapplicable. They do not create a hard fault.

## Graph closure

The scanner expands each member's primary transition into directed node
edges. A SupplyPath is closed when its declared inlet boundary is the unique
source of an acyclic graph and every projected node is reachable from it. A
ReturnPath is closed when its declared outlet boundary is the unique sink and
every projected node can reach it. This preserves split and merge structure;
declaration order is not treated as a physical series order.

The current member objects must be distinct and their induced edge sets must
not be duplicates. A clean `ZoneSplitter -> SupplyPlenum` or
`ReturnPlenum -> ZoneMixer` topology therefore remains valid in either
declaration order while still requiring a single connected flow graph.

## Candidate completeness

For each member slot, the candidate generator enumerates every unique object
occurrence of an allowed type with a complete projection. It substitutes one
typed reference at a time, excludes duplicate object reuse, and retains every
substitution whose full member-induced graph closes. Candidate records carry
exact type/name field edits plus guards for all relation, projection, and
source-field reads.

The domain is declared complete only when all allowed object occurrences have
unique identity and complete projections. One closing substitution is
eligible for unique repair, two equal closing substitutions produce
`NEEDS_INPUT`, and an unsupported or incomplete scope abstains before a hard
violation is emitted. No object-name similarity or benchmark target is used.

## Admission status

Final Node 4 decision: `PROMOTE_SAFE_AUTO`. The gate covered all 30 qualified
clean topologies with zero findings, plus independent extension mutations
across multiple prototypes and topology fingerprints. Every emitted candidate
domain was complete; unique repairs closed globally without wrong edits, while
two equal ReturnPath alternatives abstained. The promotion does not widen the
closed object vocabulary or admit partial projections.
