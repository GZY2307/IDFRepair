# IDFRepair post-Final research-claim map

This map converts the frozen implementation, Formal Final evidence, literature collision audit, observability audit, native-diagnostics comparison, and public-artifact gate into paper-safe claims. It is not manuscript prose and does not change the method or score.

## Safe to lead with

### 1. Version-bound, repair-grade EnergyPlus HVAC semantic projection

**Safe wording.** IDFRepair projects an existing IDF through the exact EnergyPlus IDD into typed HVAC relations with exact field identity, ordered membership, directed ports, compound-flow forms (`DIRECT`, `SPLIT`, `MERGE`, `MULTI_CIRCUIT`, `COUPLED_MULTI_STREAM`), evidence completeness, and source provenance suitable for guarded repair.

**Evidence.** `FieldRef`, `ObjectRef`, `PortRule`/`ExtensiblePortRule`, `FlowTransition`, and `CompoundFlowProjection` retain IDD token/name, object occurrence, source span, direction, medium, stream/circuit, rule version, and applicability. Unsupported or partial evidence cannot be promoted to complete. The frozen method identity is `3b9ad944…f2928d`.

**Boundary.** This is an EnergyPlus-specific projection and engineering composition. Do not call it the first BEM knowledge graph, the first HVAC topology representation, or a universal ontology.

### 2. Target-free, IDF-internal semantic debugging on an admitted frontier

**Safe wording.** For internally observable and supported relations, the production API localizes faults from the current IDF plus exact IDD only, without a clean model, family/locator hint, mutation oracle, drawing, equipment schedule, RAG corpus, or EnergyPlus error log.

**Evidence.** The public `scan_model(document, idd)` and `repair_model(text, idd)` boundaries scan the whole model against a frozen constraint registry. The native baseline shows exact repairs in all 6/6 D0/D1 cases where EnergyPlus diagnostics either provide no target evidence or fail to localize the mutated relation.

**Boundary.** “IDF-internal only” applies only to the admitted observable/recoverable frontier. The 15 frozen insufficient cases are actually O1 but missed by a wrapper-projection/applicability gap; external design-intent semantics can still be O4 and are not recoverable by this method.

### 3. Recoverability-aware joint minimum semantic repair with uniqueness-gated commit

**Safe wording.** For each conservative conflict component whose candidate domains are complete and finite, IDFRepair exhaustively searches within frozen bounds for the lexicographically minimum compatible semantic edit set `(semantic actions, touched fields)`, rebuilds and rescans the whole model, and commits only a unique semantic optimum; multiple non-equivalent equal optima cause abstention.

**Evidence.** Candidate domains are explicitly `COMPLETE`, `INCOMPLETE_UNSUPPORTED`, or `TRUNCATED`; candidate reads are materialized as field/relation preconditions; each objective level is either fully enumerated or rejected before prefix sampling; closure must remove the target hard violations without changing residual violations or creating new admitted hard violations. Formal connected multi is 10/10 and ambiguity is 10/10 correct abstention.

**Boundary.** Minimum constraint repair, alternative repairs, conflict graphs, ASP/ILP, and graph repair are prior art. The contribution is the EnergyPlus/BEM-specific evidence, edit semantics, and safe composition—not a new generic optimization theory.

### 4. Safety-governed, source-held-out evaluation of exact restoration

**Safe wording.** The frozen Final100 evaluates relation recovery and safety separately across ten unseen qualified source topologies, eight prototypes, three corpora, five relation classes, connected and independent multi-faults, ambiguity controls, and clean controls.

**Evidence.** Formal contract remains 81/100; support coverage 78/95; conditional automatic repair 66/66; overall automatic repair 66/95; 0 wrong modifications, 0 unsafe commits, 0 partial-as-full, 0 process failures, 95/95 non-target preservation, 10/10 ambiguity abstention, and 71/71 design-day validation for committed repairs plus clean controls. Frozen Greedy records 55/100, 19 wrong modifications, 10 unsafe commits, and 0/10 ambiguity.

**Boundary.** This is a controlled source-held-out mutation benchmark, not a natural-error prevalence estimate or proof of production safety. Lin et al. already provide injected SHACL/Brick repair evaluation, so exact-recovery benchmarking itself is not new.

## Supporting claims

| Claim | Evidence | Required qualifier |
|---|---|---|
| Compound-flow representation closes OA/AirPath semantics beyond one-inlet/one-outlet objects | Version-bound transitions and primary/auxiliary coupled streams are carried into complete projections | Only registered versions, objects, streams, and topologies are supported |
| Joint multi-fault closure is implemented and effective on the frozen cases | Connected 10/10, independent 10/10; every candidate combination is rebuilt and rescanned | Not a factorial proof of every solver submechanism |
| Guarded exact source write-back preserves non-target content | Old field value, object identity, relation snapshot, and source span guards; 95/95 non-target preservation | System implementation claim, not universal novelty |
| Unique-optimum abstention materially improves safety over greedy selection | Ambiguity 10/10 versus 0/10; unsafe commits 0 versus 10 | Uniqueness and abstention effects are bundled |
| Committed repairs recover executable EnergyPlus models | 66 repairs + 5 controls pass design-day, zero Severe/Fatal | Execution is downstream validation, not semantic oracle |
| Existing-IDF constraints add information beyond native diagnostics | Exact repair in 6/6 D0/D1 and 53/80 D2 cases | D3 diagnostics can already state nine targets; do not dismiss native diagnostics |

## Limitations only

- The method covers a frozen, admitted subset of Branch path, Loop/Connector, Zone equipment, Supply/ReturnPath, and OutdoorAirSystem EquipmentList relations, not all EnergyPlus objects or semantic errors.
- Formal contract is 81/100 and must remain so. Support coverage is 78/95, not 95/95.
- The intended `insufficient_evidence` negative controls were not internally unobservable: all 15 artifacts are O1 unique typed-reference contradictions. Their preregistered 0/15 score remains, and the generator/coverage mismatch must be disclosed.
- Two AirLoop BranchList cases are localization/applicability misses; one Loop case is conservatively blocked by a 25-versus-24 candidate bound; one ReturnPath case is a genuine equal-optimum ambiguity.
- The strict public-artifact search found only three evaluable artifact cases in two issue families, all OA EquipmentList order, so no frozen RealPublic study was run.
- The annual evidence has seven clean/repaired comparable cases with exact equality, but only one faulty/clean comparable case and no non-zero WBR effect. The method should be framed around structural validity and executable recovery.
- External design intent, omitted equipment, deletion/insertion semantics, unsupported port projections, and private drawings/schedules remain outside the demonstrated frontier.
- Clustered and prototype-level performance varies; the 81% point estimate should be accompanied by the frozen source-cluster interval and per-class results.

## Do not claim

| Prohibited claim | Why it is unsafe |
|---|---|
| First knowledge graph or HVAC topology for BEM | Wang et al. 2024/2026 and Brick-based work directly precede it |
| First SHACL/topology validation or graph-constraint repair | Wang 2026 and generic SHACL repair precede it |
| First minimum, optimal, or joint graph repair | Ahmetaj et al., Spinrath et al., and broader repair literature precede it |
| First systematic injected graph violations or exact graph recovery benchmark | Lin et al. already evaluate injected SHACL/Brick repair |
| First automatic EnergyPlus generation/debugging or existing-IDF agent editing | EPlus-LLM/v2, Zhang et al., EnergyPlus-MCP, and multi-agent workflows precede it |
| All semantic errors can be repaired from IDF alone | Only internally observable, supported, complete, uniquely recoverable cases qualify |
| EnergyPlus success proves intended semantic correctness | Four injected target faults run; runnable validity and intended relation are distinct |
| Production-safe or generally deployable | Evidence is frozen research-scope evaluation with a limited public natural-artifact sample |
| Better than Yun & Seo on their task | Evidence conditions, artifact types, outputs, and evaluation designs differ |
| The 15 insufficient cases justify a higher post-hoc Final score | They expose benchmark/coverage limitations but the Formal score remains 81/100 |

## Recommended contribution set

Use three method contributions plus one evaluation contribution:

1. A version-bound, provenance-preserving EnergyPlus HVAC semantic projection for selected existing-IDF relations, including compound flow.
2. An IDF-internal, target-free constraint scanner that admits repair only when evidence and candidate domains are complete.
3. A recoverability-aware joint minimum repair procedure with materialized preconditions, equal-optimum uniqueness testing, safe abstention, and whole-model closure.
4. A safety-governed source-held-out evaluation separating support, exact repair, abstention, preservation, executable recovery, and native-diagnostic capability.

## Recommended narrative order

Lead with the problem condition—debugging an existing EnergyPlus IDF when the model contains enough redundant structural evidence—then the version-bound projection, then evidence/completeness admission, then joint minimum repair and uniqueness, and finally the safety-oriented evaluation. Present graph representation and minimum repair as adopted foundations. Discuss Yun & Seo and Wang et al. as adjacent but different evidence/problem settings, not as weaker alternatives.

