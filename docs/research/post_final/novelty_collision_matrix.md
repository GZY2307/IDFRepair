# 截至 2026-08-17 的相近工作与创新碰撞审计

## 审计口径

本审计只把出版社/DOI 页面、作者机构全文、正式 preprint 和官方 repository 当作核心证据。`NR` 表示所核材料未报告，不能反推为“绝对不存在”。“Exact source write-back”特指对既有 IDF 的已识别字段做 guarded source-span patch，并保存非目标内容；重新生成或序列化 IDF/RDF 不计入该能力。“Multi-fault”区分“一个案例里有多个错误”与“算法联合求解相互依赖的故障”。

审计结论不是“没有碰撞”，而是：广义 BEM semantic debugging、HVAC knowledge graph/topology、SHACL validation/repair、LLM EnergyPlus generation/debugging、minimum graph repair、property-graph joint repair 和 Brick exact-recovery benchmark 均有直接先行工作。当前可辩护空间只能是 **EnergyPlus-specific composition**：existing IDF + exact-version IDD、带 provenance 的类型化关系/复合流投影、内部证据门控的完整有限 edit domain、有界联合最小搜索、非等价等最优解即 abstain、guarded field patch、全局 closure，以及分离的 EnergyPlus 验证。

## 总矩阵

完整逐字段版本见同目录的 `novelty_collision_matrix.csv`。

| Work | Input / evidence | Representation / constraints | Repair / safety | Validation | 与 IDFRepair 的碰撞 | 仍可区分的边界 |
|---|---|---|---|---|---|---|
| Yun & Seo 2026, *Energy and Buildings* 117786 | 1 个 ECO2-OD `.ECL2`、857 variables、24 张建筑/机电图纸、manual/codes/schema、multimodal evidence | 表/对象解析、vector-store RAG、supervisor + 4 agents；无形式化 graph constraint | 对 52 个 injected semantic errors（23 types）给 correction direction/value 与证据报告；不直接 patch 模型；无有限域、minimum、tie test | 1 个真实卫生中心模型；39 trainees、10 system runs；非 EnergyPlus | 直接碰撞“BEM semantic debugging”和 multi-error diagnosis | external manuals/drawings/RAG/multimodal report 与 IDF+IDD-only deterministic exact repair 不同 |
| Wang et al. 2024, *Energy and Buildings* 115035 | IFC4/Revit BIM、几何、ports、asset data、manuals/drawings、baseline IDF | Brick RDF knowledge graph；geometry relation checking、topology-quality rules、DFS paths | 人工按图纸加/删 graph links，再由 derived graph 生成/丰富 IDF；无 minimum/uniqueness | EnergyPlus 9.5；大型大学建筑；与实测 EUI 对比 | 碰撞 HVAC graph/topology、EnergyPlus mapping、BIM2BEM generation | 上游 BIM source truth 与 derived-model generation，不是 existing-IDF internal repair |
| Wang et al. 2026, *Applied Energy* 127171 | imperfect federated IFC/BIM、manuals、drawings、BMS/bills、preliminary architectural IDF | Brick/FSO RDF；SHACL/pySHACL hierarchical Terminal–Zone/Air Loop/Water Loop completeness | SHACL localization 后 graph enrichment；案例仍需 manual validation/link editing；生成 Ideal Load/Partial Match/Perfect Match IDFs；一般自动 repair 留作 future work | EnergyPlus 23.2；约 8,800 m² 建筑；energy bills/BMS comparison | 最接近的 topology-completeness/SHACL collision | 未实现 existing EnergyPlus IDF 的 target-free minimum field repair、equal-optimum abstention、non-target preservation |
| Zhang et al. 2025, *Energy and Buildings* 115116 | natural-language building description、initial geometry/zones IDF、IDD、EnergyPlus `.err` | 4-agent workflow、923 object agents/templates；object-level IDF | LLM 根据 `.err` 反复重生成错误对象直到无错误；无 finite domain/minimum/tie abstention | EnergyPlus 22.2；iUnit case；error-free stop | 碰撞 agentic IDF generation/debugging、IDD 与 `.err` feedback | generative/stochastic object regeneration，不是 typed internal constraints 或 exact relation oracle |
| Jiang et al. 2024, EPlus-LLM | natural language + training/prompt data | T5 sequence generation | 生成模型，不是既有 faulty IDF repair；详细 minimum/ambiguity 为 NR | EnergyPlus API；abstract-level supported-case metrics | 碰撞自动 EnergyPlus IDF generation | 无 existing-IDF relation localization、bounded exact repair 或 guarded patch 证据 |
| Jiang et al. 2025, EPlus-LLMv2 | natural-language complex cases、约 490k training samples、fixed companion IDF | LoRA fine-tuned LLM | 生成内容并拼接 companion IDF；无 formal repair safety | EnergyPlus 9.6 model-card workflow；402 tests 为论文归因结果 | 进一步阻断“LLM 能生成复杂 EnergyPlus 模型”的新颖性 | generation，不是 semantic restoration |
| Lee & Yoon 2026, *Energy and Buildings* 117688 | urban-building data、legal standards、street-view evidence、five-category knowledge | knowledge-based multi-agent workflow；细节按 abstract 限定 | 包含 iterative error debugging，但 exact repair/minimum/ambiguity/write-back 未由 abstract 建立 | abstract 报告 270 个 Seoul buildings、14 LLMs | 碰撞 knowledge-based multi-agent end-to-end BEM service | 不能据 abstract 推断其实现了 finite typed minimum repair；IDFRepair 不应反向夸大差异 |
| Li, Xu & Hong 2025/2026, EnergyPlus-MCP + MCP workflow | existing IDF、weather、user objectives、可选 BEM/web knowledge | Eppy + NetworkX/Graphviz；35 structured tools；agent JSON calls | 可 inspect/edit/save/run existing IDF；无 finite candidate minimum、equal-optimum gate 或 source-span preservation | EnergyPlus 25.1；retrofit/variant simulations | 阻断“首个 agent 修改并运行 existing IDF”及 HVAC visualization | 是 general tool/agent workflow，不是 exact semantic-restoration contract |
| Ahmetaj et al. 2025, TGDK | RDF graph + non-recursive SHACL shapes/targets | SHACL-to-ASP/clingo | additions/deletions；`#minimize` 支持 cardinality/weighted minimum；可有多个 stable-model repairs；不因 tie abstain | SHACL test/Wikidata-derived evaluation；无 EnergyPlus | 决定性阻断“首次 minimum graph repair / SHACL repair / alternative repair enumeration” | 无 EnergyPlus/IDD evidence、IDF source patch 或 unique-minimum auto-commit policy |
| Lin et al. 2025, arXiv 2507.22419 | clean RDF graph + SHACL manifest + injected VIO + validation report；含 Brick 1.3 | RDF/SHACL；LLM 输出 SPARQL updates | 评估 syntax/validity/relaxed/exact isomorphism；无 edit minimum/equal-optimum gate | Brick 含 8 个 ASHRAE G36 manifests、144 cases；无 EnergyPlus | 阻断“首次 systematic injected graph violations / Brick repair / exact graph recovery metric” | 无 existing-IDF source semantics、joint bounded uniqueness safety 或 EnergyPlus execution |
| Spinrath et al. 2026, PVLDB | property graph + restricted PG-Constraints + optional weights | error queries、witness sets、global conflict hypergraph | deletion-only node/edge/label repair；ILP weighted/cardinality optimum，另有 greedy；ties 不触发 abstention | ICIJ/legislative/Coreutils/LDBC graphs；无 EnergyPlus | 阻断 property-graph constraint repair、conflict-hypergraph joint repair、generic optimal repair | 无 typed field substitution、EnergyPlus provenance、exact hidden-relation oracle 或 guarded IDF patch |
| Pachera et al. 2025, TODS | property graph + denial constraints + users | repair dependency graph、query detection | user-centric distributed repair choices；本审计仅有 abstract-level method evidence | graph/user-study evaluation | 阻断 broad user-centric graph-repair novelty | 非 deterministic IDF-internal restoration |
| Terdalkar et al. 2025 | property graphs、constraints/context、6 open-source LLMs | LLM graph-repair evaluation | generative graph repairs、cost/quality comparison | generic graph datasets | 阻断“首个 LLM property-graph repair” | 无 EnergyPlus/IDD finite repair composition |

## 五组重点核对

### A. Yun & Seo 2026

核到的正式证据是：[DOI](https://doi.org/10.1016/j.enbuild.2026.117786) 与[官方代码仓库](https://github.com/woo-seung/BEM-semantic-debugging)。文章记录在本次审计日已经可访问，但卷期页显示 2026-10-01；本文档将它作为 online-available close work，不把未来卷期日期伪装成审计日前纸本出版。

其 evidence 并非 model-only：建模手册与 codes 被索引用于 RAG，24 张图纸通过 multimodal agent 提取证据，ECO2-OD schema/模型也参与检查。一个 actual building model 被注入 52 个 semantic errors，覆盖 23 个 error types；多 agent 负责 manual analysis、model inspection、evidence extraction 和 report writing。输出是包含错误、依据与 corrective measure 的 report，不是修改后的 `.ECL2`/IDF。没有建立 complete finite edit domain、lexicographic minimum、equal-optimum counting 或 ambiguity→no-commit。

因此共同研究问题确为 **BEM semantic debugging**，不能回避；差异只能写成 evidence condition 与 repair contract 的差异，不能写成对方“没有语义”。

### B. Wang et al. 2024

[UCL 正式全文](https://discovery.ucl.ac.uk/10200308/1/1-s2.0-S0378778824011514-main.pdf)表明输入是 BIM/IFC、几何、ports 与其他工程资料，方法先构造 geometry-induced Brick KG，再形成 informative HVAC topology 和 BEM-oriented topology，最后生成/丰富 EnergyPlus 模型。HVAC topology、graph semantic representation 与 EnergyPlus mapping 已明确先行；“用图表示 HVAC”绝不能作为本项目独有创新。

其问题定位发生在 derived BIM/KG，实际 case 的 link corrections 由使用者结合 drawing/manual validation 完成；它没有对一个既有 faulty IDF 的字段执行 ambiguity-aware minimum repair。

### C. Wang et al. 2026

[Applied Energy/UCL 全文](https://discovery.ucl.ac.uk/id/eprint/10218516/1/1-s2.0-S0306261925019014-main.pdf)明确使用 ontology、Brick/FSO、SHACL validation 和 hierarchical Terminal–Zone/Air Loops/Water Loops rules，从 imperfect BIM topology 生成 Ideal Load、Partial Match、Perfect Match BEM，并用 bills/BMS 做 downstream comparison。

它已经完成了 HVAC topology completeness 的系统化表示、验证、localization 与 enrichment workflow；不能声称 IDFRepair 首次做 topology completeness 或 SHACL HVAC validation。但审核到的 demonstrated repair 仍是 BIM-derived graph 的补全/改链并生成 BEM，一般自动 graph repair 被列为后续方向；未见现有 EnergyPlus IDF 内部关系的完整候选 field-domain、minimum edit、multiple equal minima 检查、source-span patch 或 non-target preservation。因此它没有完成与冻结 IDFRepair 完全相同的“existing-IDF target-free minimum safe repair”，但两者在结构语义和 topology validation 上高度重合。

### D. LLM-BEM / EnergyPlus agent line

[Zhang et al.](https://www.osti.gov/servlets/purl/2480816)把 building description 转成 EnergyPlus model，并由 debugging agent 读取 `.err`、定位 class/object、重生成 object、重跑直到 error-free；[EPlus-LLMv2 官方 model card](https://huggingface.co/EPlus-LLM/EPlus-LLMv2/blob/main/README.md)记录 fine-tuned natural-language generation；[EnergyPlus-MCP](https://github.com/LBNL-ETA/EnergyPlus-MCP)已公开 existing-IDF inspection/edit/run tools。故不能声称“首次自动生成/调试 IDF”“首次 agent 修改并运行现有 IDF”。

可区分之处不是“不使用 AI”本身，而是：冻结 IDFRepair inference 不读取 prompt、manual、drawing 或 `.err`；候选域与 search bounds 明确；commit 需要一个 unique non-equivalent optimum；写回由 old-value/relation snapshot guard 保护；semantic oracle 与 EnergyPlus runnable 分开。

### E. Generic graph repair

[Ahmetaj et al.](https://doi.org/10.4230/TGDK.3.3.1)已经把 SHACL repair 编译为 ASP，支持 additions/deletions、cardinality/weighted minimum 与多个 repairs；[Spinrath et al.](https://doi.org/10.14778/3797919.3797929)已经在 PG-Constraints 上使用 error queries、conflict hypergraph 和 ILP/greedy 做跨 violations 的 deletion repair。minimal/optimal graph repair、constraint violation repair、multiple repairs 和 joint graph repair 都不是本项目的理论首创。

因此禁止“首次提出最小图修复”“首次利用图约束自动修复”“首次联合图冲突修复”。本项目只能主张 EnergyPlus/BEM-specific semantics、source artifact contract、安全 admission 与 evaluation composition。

## Candidate contribution ratings

| Candidate contribution | Rating | 可安全使用的表述 | 边界 |
|---|---|---|---|
| 1. Version-bound EnergyPlus HVAC semantic projection | **STRONG** | 对 existing IDF 采用 exact-version IDD field identity、typed ports、ordered membership、`DIRECT/SPLIT/MERGE/MULTI_CIRCUIT/COUPLED_MULTI_STREAM` 与 exact provenance，形成所选关系的 repair-grade projection | 作为具体实现/组合贡献；不要写“首次 knowledge graph/HVAC topology”，也不做 universal priority claim |
| 2. IDF-internal evidence-only semantic debugging | **STRONG** | 在 admitted internally observable/recoverable frontier 内，仅用 faulty/current IDF + exact IDD 进行 target-free localization 与 repair | 只覆盖 admitted frontier；不能写“所有 BEM error 都无需 external evidence” |
| 3. Recoverability-aware joint minimum semantic repair | **DEFENSIBLE** | complete finite candidate domain + dependency/conflict components + bounded exact lexicographic minimum + non-equivalent equal optimum→abstain | minimum/alternative graph repair已有 prior art；贡献是 EnergyPlus-specific composition 与 unique-minimum safety policy |
| 4. Safety-governed source-held-out evaluation | **DEFENSIBLE** | source-held-out Final100 分离 exact relation recovery、non-target preservation、connected/independent、ambiguity、clean controls、EnergyPlus validation，并与 frozen greedy 比较安全性 | Lin 已有 injected SHACL/Brick exact recovery；这是 evaluation contribution，不是单独的通用算法创新 |
| Supporting capability: guarded source-span write-back | **STRONG** | field old value + relation snapshot preconditions、source-span patch、non-target preservation | 只能声称本系统实现并验证；不能泛化为所有程序变换领域首次 |

## 禁止或收窄的 claims

| Claim | Rating | 原因 |
|---|---|---|
| 首次 knowledge graph / HVAC topology for BEM | **DO_NOT_CLAIM** | Wang 2024/2026 直接先行 |
| 首次 SHACL HVAC topology validation/repair | **DO_NOT_CLAIM** | Wang 2026 + Ahmetaj generic SHACL repair |
| 首次 minimum graph repair / constraint repair | **DO_NOT_CLAIM** | Ahmetaj、Spinrath 直接先行 |
| 首次 systematic injected graph violation 或 exact graph recovery benchmark | **DO_NOT_CLAIM** | Lin 2025 已覆盖 SHACL VIO、Brick 与 exact isomorphism；另有 2026 SWJ under-review watch item |
| 首次 automated EnergyPlus/IDF generation/debugging | **DO_NOT_CLAIM** | EPlus-LLM/v2、Zhang、Lee & Yoon、EnergyPlus-MCP 均碰撞 |
| 首次 agent 修改并模拟 existing IDF | **DO_NOT_CLAIM** | EnergyPlus-MCP 与 2026 MCP workflow |
| 自动修复任意 HVAC graph | **WEAK** | 实证仅为冻结、admitted relation frontier |
| 无需任何 external evidence | **WEAK** | 只对 internally observable/recoverable cases 成立 |
| EnergyPlus success 证明 semantic correctness | **DO_NOT_CLAIM** | wrong-yet-runnable semantics 存在；relation oracle 与 executable validity 必须分离 |

## 当前 watch item 与剩余不确定性

Lin et al. 的 [“A Formal Diagnostic Framework for Graph Repair Systems”官方投稿页](https://www.semantic-web-journal.net/content/formal-diagnostic-framework-graph-repair-systems)在审计日仍标记 under review、无 final DOI，因此只作为 collision watch，不作为已发表优先权。其从 compliant graph 系统注入 violations 并评价 repair systems 的方向进一步要求本项目放弃 broad benchmark-first wording。

Lee & Yoon 2026、Liu et al. 2026、Pachera et al. 2025 和部分 EPlus-LLM 细节只获得 abstract/model-card-level evidence，未核到的字段保持 `NR`。本审计支持 scoped differentiation，不支持 “first ever”；绝对 priority 需要另行注册的 systematic review。

## Primary-source ledger

- Yun & Seo 2026：[DOI](https://doi.org/10.1016/j.enbuild.2026.117786)，[official repository](https://github.com/woo-seung/BEM-semantic-debugging)。
- Wang et al. 2024：[DOI](https://doi.org/10.1016/j.enbuild.2024.115035)，[UCL record/full text](https://discovery.ucl.ac.uk/id/eprint/10200308/)。
- Wang et al. 2026：[DOI](https://doi.org/10.1016/j.apenergy.2025.127171)，[UCL record/full text](https://discovery.ucl.ac.uk/id/eprint/10218516/)。
- Zhang et al. 2025：[DOI](https://doi.org/10.1016/j.enbuild.2024.115116)，[OSTI full text](https://www.osti.gov/servlets/purl/2480816)。
- EPlus-LLM：[DOI](https://doi.org/10.1016/j.apenergy.2024.123431)。EPlus-LLMv2：[DOI](https://doi.org/10.1016/j.autcon.2025.106223)，[official model card](https://huggingface.co/EPlus-LLM/EPlus-LLMv2/blob/main/README.md)。
- Lee & Yoon 2026：[DOI](https://doi.org/10.1016/j.enbuild.2026.117688)。
- EnergyPlus-MCP：[DOI](https://doi.org/10.1016/j.softx.2025.102367)，[official repository](https://github.com/LBNL-ETA/EnergyPlus-MCP)。MCP workflow：[DOI](https://doi.org/10.1080/19401493.2026.2653969)。
- Ahmetaj et al. 2025：[DOI](https://doi.org/10.4230/TGDK.3.3.1)，[official repository](https://github.com/robert-david/shacl-repairs)。
- Lin et al. 2025：[arXiv](https://arxiv.org/abs/2507.22419)。
- Spinrath et al. 2026：[DOI](https://doi.org/10.14778/3797919.3797929)，[formal preprint](https://arxiv.org/abs/2602.05503)，[artifact](https://doi.org/10.5281/zenodo.18301604)。
- Pachera et al. 2025：[DOI](https://doi.org/10.1145/3709735)。Terdalkar et al. 2025：[DOI](https://doi.org/10.1145/3735546.3735859)，[formal preprint](https://arxiv.org/abs/2507.03410)。
