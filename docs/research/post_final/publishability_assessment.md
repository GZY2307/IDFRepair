# Post-Final publishability assessment

## Decision

**Novelty collision status: B — DISTINCT_COMPOSITION_WITH_OVERLAP.**

**Energy and Buildings publishability: REASONABLE, with narrow positioning and material limitations.**

**Evidence-closure status: `EVIDENCE_CLOSED_READY_WITHOUT_REALPUBLIC`.**

The literature audit did not find a published method that demonstrates the same full combination of existing EnergyPlus IDF input, exact-version IDD semantics, IDF-internal evidence only, target-free whole-model relation localization, provenance-bearing finite edit domains, bounded joint minimum field repair, non-equivalent equal-optimum abstention, guarded source write-back, and whole-model closure. It did find strong prior art for every broad ingredient—BEM semantic debugging, HVAC topology/knowledge graphs, SHACL validation and repair, LLM-based EnergyPlus generation/debugging, and minimum/joint graph repair. The publishable unit is therefore the EnergyPlus-specific composition and evidence contract, not a new general graph-repair theory.

## One-sentence answer to the supervisor

> 本项目基于 EnergyPlus 版本绑定的类型化 HVAC 关系投影，将既有 IDF 中分散的节点、设备、Branch、Loop、Zone equipment 与复合气流关系转换为带精确字段 provenance 的 canonical semantic IR；随后以跨对象结构约束定位 IDF 内部不一致，在完整有限候选域上对冲突分量执行有界最小语义编辑搜索，只有最优 repair 在语义层唯一时才原子写回，否则保留输入并请求更多证据，最后通过全模型语义闭包与独立 EnergyPlus 运行验证。

This answer maps directly to frozen production code. It is not regular-expression replacement, typo correction, error-log replay, benchmark locator use, or LLM generation.

## Where the work overlaps

### Yun & Seo 2026

The direct overlap is the research problem: semantic debugging of building energy models with multiple injected semantic errors. Yun and Seo use modeling manuals/codes, an ECO2-OD schema/model, 24 drawings, multimodal extraction, RAG, and supervised specialist agents to produce a diagnostic/corrective report for 52 errors in one actual building model. IDFRepair instead studies exact repair of an existing EnergyPlus artifact using only the current IDF and IDD, with deterministic finite domains, uniqueness-gated commit, and exact write-back. These are different evidence conditions and outputs; neither result supports superiority on the other's task.

### Wang et al. 2024

The overlap is HVAC topology, graph semantics, relation checking, and EnergyPlus mapping. Wang et al. construct HVAC topology from IFC/BIM geometry and additional engineering evidence, form a Brick knowledge graph, and generate/enrich a BEM. This decisively prevents any “first HVAC graph/topology” claim. IDFRepair's remaining distinction is repair of an already-authored IDF from internal redundancy, at exact source fields, rather than deriving a model from an upstream BIM graph.

### Wang et al. 2026

This is the closest topology-completeness collision. It uses Brick/FSO, SHACL, hierarchical Terminal–Zone/Air Loop/Water Loop checks, BIM-derived enrichment, and downstream bills/BMS comparison. It already establishes systematic HVAC topology validation and enrichment. The audited demonstration does not implement target-free minimum source-field repair of an existing IDF, complete finite edit domains, equal-optimum abstention, or non-target source preservation. The distinction is real but narrower than “semantic topology repair versus no repair.”

### LLM-BEM and EnergyPlus-agent line

Zhang et al., EPlus-LLM/v2, Lee and Yoon, and EnergyPlus-MCP cover natural-language generation, agent planning, iterative `.err` feedback, structured IDF editing/running, and knowledge/RAG workflows. IDFRepair cannot claim first automated IDF generation/debugging or first agent editing of an existing IDF. Its different contract is deterministic internal-evidence restoration with explicit candidate completeness, minimum/uniqueness proof, guarded patching, and no prompt/model stochasticity during inference.

### Generic graph repair

Ahmetaj et al. already provide SHACL repair via ASP with minimum additions/deletions and multiple repairs; recent property-graph work uses conflict structures and optimal/greedy repair. Minimum graph repair, constraint repair, alternative repairs, and joint repair are not original theories here. IDFRepair specializes those ideas to EnergyPlus object/field semantics and makes unique-optimum safe commit plus exact source preservation part of the artifact contract.

## Evidence adequacy

| Evidence question | Result | Assessment |
|---|---|---|
| Is the implemented method identity clear? | Exact IDD projection → typed IR → whole-model constraints → finite domains → conflict components → bounded minimum/uniqueness → guarded patch → closure | Strong |
| Does the Formal evidence reconcile? | 100/100 membership/runtime/oracle/prediction/certificate/score IDs reconcile; frozen headline 81/100 | Strong |
| Is supported automatic repair safe on the benchmark? | 66/66 conditional exact repair; 0 wrong/unsafe/partial/process; 95/95 non-target preservation | Strong within scope |
| Does joint/abstention add evidence over greedy? | 81 vs 55 contract; ambiguity 10 vs 0; wrong 0 vs 19; unsafe 0 vs 10 | Strong composition evidence, not factorial attribution |
| Is there value beyond EnergyPlus diagnostics? | 6/6 exact repair in D0/D1; 53/80 in D2; native D3 only 9/95 | Strong for repair-target determination, while acknowledging native localization |
| Are insufficient cases true unobservable negatives? | No; 15/15 are O1 unique typed-reference contradictions missed by support/applicability | Material benchmark limitation; Formal 0/15 unchanged |
| Are observable failures understood? | 2 applicability misses, 1 search-bound refusal, 1 genuine ambiguity | Strong failure attribution |
| Is executable recovery shown? | 71/71 automatic outputs + controls pass design-day | Strong downstream validation |
| Is energy-impact evidence broad? | 7 comparable annual repairs exactly match clean; only one faulty comparison, no non-zero WBR | Limited |
| Is a natural public case study available? | 3 evaluable artifacts in 2 issue families, below gate 5 | Insufficient; no study run |

## Main risks for an Energy and Buildings submission

1. **Composition novelty rather than foundational novelty.** Reviewers may regard typed projection plus bounded repair as an engineering integration. The paper must make the exact EnergyPlus semantics, evidence/recoverability contract, and safe artifact transformation technically concrete.
2. **Controlled mutations dominate the evaluation.** The Final has strong causal control and source holdout, but the strict public search could not support a five-case external study. Do not blur synthetic source-held-out evidence with natural fault prevalence.
3. **The preregistered insufficient stratum is not what its name claimed.** All 15 are internally observable O1 cases, and the frozen method misses them. This must be disclosed as an operator-construction/support-frontier mismatch while retaining 0/15 and 81/100.
4. **Coverage is finite and visibly incomplete.** Two AirLoop BranchList misses and one candidate-cap refusal expose scope/bound limits; the ReturnPath case demonstrates genuine ambiguity. These are useful scientific boundaries, not reasons for post-Final tuning.
5. **Energy evidence is restoration, not impact.** Most faults prevent simulation; annual comparable repairs exactly restore clean outputs, but there is no broad non-zero WBR evidence.
6. **Closest works are recent.** Yun & Seo and Wang 2026 require precise problem/evidence separation. Broad “semantic debugging,” “topology validation,” or “knowledge graph repair” novelty wording would likely fail review.
7. **Generalization is source-clustered.** Ten unseen topologies and eight prototypes are useful, but relation/prototype results vary and the frozen cluster interval should accompany aggregate accuracy.

## Why the project can now enter the paper phase

The technical method is identifiable, the collision boundary is explicit, the frozen benchmark and safety claims reconcile, the 19 failures have evidence-based explanations, native diagnostics have an independent comparator, and the public-case scarcity has been measured under a strict gate rather than hidden. No discovered paper duplicates the complete EnergyPlus-specific composition. The remaining gaps affect claim width and limitations, not whether a coherent method exists.

The appropriate next action is therefore to write the paper with narrowed claims. Further error-family development, solver tuning, rescoring, or a second Final would weaken the frozen evidence. A future public case may be added only if a naturally published faulty/fixed artifact independently satisfies the same gate; it should not block manuscript drafting.

## Final positioning

The safest EnB positioning is:

> deterministic, evidence-gated semantic restoration of existing EnergyPlus HVAC relations from IDF-internal redundancy, with version-bound projection, exact source provenance, joint minimum repair, and explicit ambiguity abstention.

The submission should present graph representation and minimum repair as foundations, lead with the EnergyPlus-specific projection and recoverability contract, retain the unmodified 81/100 Formal result, and state the absence of a sufficiently large natural public case study as a limitation.

