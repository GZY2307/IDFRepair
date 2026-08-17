# V2.2 compound-flow IR

## Scope

The V2.2 canonical IR adds a conservative flow-topology projection above the
existing atomic `PortRef` facts.  It does not replace field provenance, typed
identity, relation records, or V2.1 scanners.  The schema identity is
`idfrepair.semantic-graph-v2.ir.v2`; the new `flow_projections` field is
appended to `ModelIR` so existing positional field order remains stable.

## Records

`FlowTransition` retains the owning `ObjectRef` (and therefore the object
source span), exact inlet/outlet `PortRef` records, air/water medium, a closed
stream role, circuit identity, primary/auxiliary traversal role, projection
rule ID, exact IDD version, and applicability.  `CompoundFlowProjection`
groups transitions under one of:

- `DIRECT`: exactly one inlet and one outlet;
- `SPLIT`: exactly one inlet and one or more outlets;
- `MERGE`: one or more inlets and exactly one outlet;
- `MULTI_CIRCUIT`: at least two distinct one-to-one circuits;
- `COUPLED_MULTI_STREAM`: at least two distinct one-to-one semantic
  interfaces.

The closed stream roles are `direct`, `distribution`, `return`, `supply`,
`exhaust`, `secondary`, `outdoor_to_mixed`, and `return_to_relief`.

Completeness is derived, not trusted from a caller-supplied flag.  A complete
projection requires topology-specific cardinality, one primary traversal,
complete transitions, one object and medium per fact, exact version agreement,
unique port identities, unique nonblank projected nodes, distinct stream roles
for multi-stream forms, and no extraction issue.  Structurally contradictory
complete records raise immediately; incomplete source evidence is retained
with explicit issue codes.

## IDD-bound extensible extraction

`ExtensiblePortRule` binds one object type and one audited IDD version to the
exact `\begin-extensible` token/name, group width, repeated role, medium, and
port group.  Extraction begins at `IDDObject.extensible_start` and visits only
fields actually present in the parsed object.  `semantic_field_at()` maps each
repetition to the begin-group template slot; it never cycles from the end of a
pre-expanded IDD display range.  This preserves exact source field index/span
even beyond a pre-expanded tail.

Blank declared members become `extensible_port_blank_member` issues.  A wrong
begin token/name, group-width mismatch, unsupported version, absent required
port, or duplicate projected node cannot produce a complete projection.  No
`A3..A500` enumeration or node-name substring inference is used.

## Versioned production frontier

Every new compound atomic rule and projection rule is a separate singleton for
EnergyPlus 22.1 or 24.1.  Registry construction rejects overlapping
`(object type, field token, version)` identities.  The sensible/latent heat
exchanger demonstrates why token identity and source position are separate:
its supply inlet remains official token A3, at parsed field 12 in 22.1 and
field 8 in 24.1.

| Object | Form | Primary transition | Retained auxiliary transition |
|---|---|---|---|
| `AirLoopHVAC:ZoneSplitter` | SPLIT | A2 -> extensible A3+ | -- |
| `AirLoopHVAC:SupplyPlenum` | SPLIT | A4 -> extensible A5+ | A3 zone node excluded |
| `AirLoopHVAC:ZoneMixer` | MERGE | extensible A3+ -> A2 | -- |
| `AirLoopHVAC:ReturnPlenum` | MERGE | extensible A6+ -> A4 | A3/A5 excluded |
| `OutdoorAir:Mixer` | COUPLED_MULTI_STREAM | A3 -> A2 | A5 -> A4 |
| `HeatExchanger:AirToAir:SensibleAndLatent` | MULTI_CIRCUIT | A3 -> A4 | A5 -> A6 |
| `HeatExchanger:AirToAir:FlatPlate` | MULTI_CIRCUIT | A5 -> A6 | A7 -> A8 |

All exact one-inlet/one-outlet atomic groups outside these owned compound types
also receive an additive `DIRECT` projection.  A document/IDD version mismatch
blocks compound projections and is recorded as an extraction issue.

## Admission boundary

This IR closes the representation gap without making every projection an
admitted repair scope. AirPath is admitted only for its four audited
split/merge object types. OA is admitted only for normal-context Mixer-only
and sensible/latent-HX-to-Mixer lists; FlatPlate remains projection-capable but
outside the corpus-backed SAFE_AUTO frontier. A proposed HX-to-Mixer list edit
must close both the primary supply/outdoor traversal and the reverse
relief/exhaust traversal. An auxiliary-only inconsistency with no closing list
alternative abstains instead of being mislocalized as an EquipmentList fault.
