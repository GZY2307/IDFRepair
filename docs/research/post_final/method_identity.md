# IDFRepair V2 的技术方法身份

## 正式回答

本项目基于 **EnergyPlus 版本绑定的类型化 HVAC 关系投影**：先把 IDF 中分散的节点、设备、Branch、Loop、Zone equipment 与复合气流关系转换为带精确字段 provenance 的 canonical semantic IR，再用跨对象结构约束定位内部不一致，并在完整有限候选域上对冲突分量执行有界、穷举式最小语义编辑搜索；只有最优 edit set 在语义层唯一时才原子写回，否则保留输入并请求更多证据，最后以全模型语义闭包和冻结评估流程中的 EnergyPlus 执行验证结果。

这一定义与 2026-08-17 验证通过的冻结方法身份 `3b9ad944…f2928d` 对应。它描述的是已经实现并用于 Formal V2 Final 的方法，不是论文包装，也不扩张为通用 graph-repair 理论。

## 实现链

| 阶段 | 实际实现 | 科学作用与安全条件 |
|---|---|---|
| EnergyPlus IDF + exact IDD | `repair_model(text, idd)` 只接收当前 IDF 文本与 IDD；`object_ref_from_idf` 把字段绑定到 IDD token/name、对象 occurrence 与 source span | 把“同一字符串”提升为版本和字段语义已知的事实；文档声明版本与 IDD 不一致时不构造 compound projection |
| Version-bound port projection | `PortRule` / `ExtensiblePortRule` 按 object type、EnergyPlus 版本、精确 field token/name 声明 role、medium、group；未注册 node 字段留在 unsupported evidence | 不用字段名子串猜 inlet/outlet；不完整 extensible group 不能被当作完整端口证据 |
| Canonical typed relation / compound-flow IR | `FieldRef`、`ObjectRef`、`PortRef`、typed identity、Branch/Loop/AirPath/OA/Zone relations；`CompoundFlowProjection` 将端口组成 `DIRECT`、`SPLIT`、`MERGE`、`MULTI_CIRCUIT` 或 `COUPLED_MULTI_STREAM` transition | 保存对象 occurrence、规范化身份、方向、介质、circuit/stream、projection rule/version 及精确字段 lineage；complete 状态由结构不变量和完整 source-backed ports 导出 |
| Target-free whole-model scan | `build_model_ir` 构造整模型不可变 snapshot；`scan_ir` 遍历 production registry 的全部适用 evaluator；公开边界 `scan_model(document, idd)` 不接收 family、locator、oracle 或 expected edit | 只让 `ADMIT_SAFE_AUTO` 约束成为 hard violation；detect-only 或证据不完整的 scope 不驱动编辑 |
| Typed semantic edit domain | 每个 hard `Violation` 由注册的 generator 产生 `CandidateSet`；domain 显式标为 `COMPLETE`、`INCOMPLETE_UNSUPPORTED` 或 `TRUNCATED` | 唯一性只能在完整有限域上声称；无证据候选、动态候选域或截断域会停止自动修复 |
| Dependency/conflict components | `build_conflict_components` 以 latent factor、read/write、field provenance 与 materialized precondition 的交集构造保守 connected components | 需要联合推理的 violations 在一个分量内求解；不共享依赖的故障可独立证明 |
| Bounded joint minimum repair | `SolverLimits` 固定最大 violations、candidate edits、semantic edits 和 evaluated sets；每一 semantic-cost 层先确认能完整枚举，再穷举全部组合并重建、重扫模型 | 目标为 `(语义动作数, 触及字段数)` 的字典序最小值；不会采样 objective level 的前缀，也不会接受只关闭部分目标的 patch |
| Edit-set uniqueness / abstention | 同一最优 objective 上按 semantic signature 去重；若有两个非等价最优 edit set，decision 为 `AMBIGUOUS`；域不完整、搜索界超出或无 closing set 时分别 `UNSUPPORTED`、`SEARCH_EXHAUSTED` 或 `NEEDS_INPUT` | 自动写回不是“找到一个可行解”即可，而是必须证明完整域内只有一个最优语义解释 |
| Exact guarded write-back | `SemanticEdit` 同时携带 `FieldValuePrecondition` 与 `RelationStatePrecondition`；应用前检查对象 type/name/index、原字段值和原 document snapshot；按 source span 反向替换 | 写回是原子、old-value guarded 的精确字段 patch，未触及 bytes 保持不变；冲突写、stale candidate 和 no-op 均拒绝 |
| Global semantic closure | 分量解合并后重新 parse、重建全模型 IR、重扫全部 active hard constraints；最终 violation set 必须恰等于已明确保留的 unresolved set，且不得出现新 hard violation | 防止局部修复破坏别的关系，防止 partial-as-full |
| EnergyPlus execution validation | 生产 repair API 结束于语义闭包；Formal 冻结 harness 对 66 个自动修复结果与 5 个 clean controls 执行 EnergyPlus，71/71 通过，无 severe/fatal | 这是独立的外部执行证据，不被伪装成 solver 内部约束，也不回馈候选选择 |

主要代码锚点：

- `src/idfrepair/semantic_graph_v2/ports.py:33-123`：版本绑定的 exact port registry。
- `src/idfrepair/semantic_graph_v2/ir.py:130-282`：字段 provenance、typed ports 与 compound flow structures。
- `src/idfrepair/semantic_graph_v2/build_ir.py:637-733`：target-free whole-model IR 构建。
- `src/idfrepair/semantic_graph_v2/registry.py:42-59,104-242`：constraint/evidence/admission 声明与 production frontier。
- `src/idfrepair/semantic_graph_v2/scan.py:1624-1676`：适用性门控与整模型扫描边界。
- `src/idfrepair/semantic_graph_v2/candidates.py:46-70,637-725`：候选域 completeness 与生成分派。
- `src/idfrepair/semantic_graph_v2/edits.py:45-108,173-251`：field/relation preconditions 与精确写回。
- `src/idfrepair/semantic_graph_v2/solver.py:39-44,141-214,254-397`：冲突分量、有界完整枚举、最小性和唯一性。
- `src/idfrepair/semantic_graph_v2/runtime.py:124-278`：scan → candidates → joint solve → guarded write-back → global closure。

## 形式化描述

令冻结 production registry 对当前模型产生 hard violations 集合 (V)。对每个 (v_i\in V)，candidate generator 返回有限语义编辑域 (\Omega_i) 及 completeness 状态。只有某个 conflict component (C\subseteq V) 的所有相关 (\Omega_i) 均为完整域，solver 才考虑自动提交。

在 (C) 内，令 (\Delta) 是从候选编辑并集选出的兼容集合，(F(\Delta)) 为被修改的不同 IDF 字段集合。实现求解：

\[
\underset{\Delta}{\operatorname{lexmin}}\;
\left(|\Delta|_{\mathrm{semantic}},\ |F(\Delta)|\right)
\]

约束与代码一致：

1. 每个选中编辑的 field-value 与 relation-snapshot precondition 在原 faulty snapshot 上成立；
2. 所选编辑不存在冲突字段写入，且共同作用可被原子应用；
3. 重建 whole-model graph 后，component 中的 hard violations 全部关闭；
4. component 外原有 hard violations 原样保留；
5. 不产生新的 admitted hard violation。

solver 按 semantic edit count 从 1 到冻结上限逐层枚举；只有某一层能在剩余 evaluation budget 中被完整枚举时才检查该层。找到第一层 closing sets 后，再取 distinct-field cost 最小者。若同一最优 objective 存在第二个非等价语义 edit set (\Delta'\)，则返回 `AMBIGUOUS/NEEDS_INPUT` 路径而不 commit；只有一个等价类时才返回 `UNIQUE_REPAIR`。

因此，该方法是 **EnergyPlus-specific、证据门控的 bounded exact semantic repair procedure**。它没有声称新的通用 graph-repair 理论，也没有实现或声称 CP-SAT、ASP、ILP 或通用最小模型修复算法的创新。

## 当前 support frontier

冻结 registry 文档化 19 个约束，其中 production scanner 激活 12 个 `ADMIT_SAFE_AUTO` hard constraints 与 2 个 detect-only constraints。SAFE_AUTO frontier 覆盖五类关系：Branch path、Loop/Connector、Zone equipment、AirPath 和 OutdoorAir equipment path。其 admission 不是“对象属于某类即可”，而同时要求 exact-version port/projection support、relation-local evidence completeness、完整候选域、全 objective-level 枚举、最优 edit-set 唯一以及全局 closure。

显式边界同样是方法的一部分：缺失 Branch member、删除 duplicate member、controller intent、Zone priority、controller sensor equality、parallel middle order 等不能由当前 IDF 内部证据唯一决定的语义，不被强行自动修复。Formal 15 个 insufficient cases 也不因 benchmark 的 oracle 存在而自动变成可观察；它们将在独立可观测性审计中按 IDF-only 证据重新分类，但 Formal 的 `0/15` 评分保持冻结。

## 它不是什么

- **不是正则表达式替换。** 正则/字符串层无法产生 IDD token、object occurrence、port role、flow circuit、relation completeness、preconditions 和 whole-model closure；实际写回只在上述语义证明完成后才使用 source span。
- **不是 typo correction。** 候选不是由字符串相似度生成，而来自 current model 中类型、端口、成员集合、边界、ownership 与 directed-flow 的结构证据。
- **不是照抄 EnergyPlus ERR。** `repair_model` 的输入没有 ERR；Formal inference 在 EnergyPlus validation 之前一次性完成。ERR 只在本轮 post-Final baseline 中作为独立 comparator 使用。
- **不是 benchmark family/locator 驱动。** production API 只接收 current IDF text、exact IDD、可选 constraint registry 和固定 solver limits；没有 record ID、operator、fault family、locator 或 oracle 参数。
- **不是 LLM 直接生成 IDF。** 核心为 deterministic parse/projection/constraint/enumeration/write-back；没有 prompt、retrieval、model inference 或自由文本 patch 生成。

## 证据解释边界

Formal Final 的 `81/100` 是 preregistered contract accuracy，不等于任意建筑模型错误的普遍修复率。`78/95` 是该冻结 benchmark 中被 production frontier 支持的 repair-target coverage；在 66 个既满足 support 又满足唯一完整域并被自动提交的案例中，`66/66` 正确。整体 repair-target automatic repair 为 `66/95`。安全性证据为 0 wrong modification、0 unsafe commit、0 partial-as-full、10/10 ambiguity correct abstention、95/95 non-target preservation。以上数字均由 `reports/post_final/formal_final_reconciliation.json` 只读复核，没有重跑 inference、评分或生成第二个 Final。
