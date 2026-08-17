# IDFRepair

IDFRepair 是面向已有 EnergyPlus IDF 模型的可恢复性感知语义调试与确定性修复
框架。系统把版本绑定的 HVAC 关系投影为类型化语义表示，检测跨对象结构不一致，
并且只在文件内部证据唯一支持修复时执行有界最小语义编辑。

[English](README.md)

## 冻结 Formal V2 结果

Formal V2 在一次性 Final100 评测前已经冻结。方法、membership、prediction 与
score 均为只读；本次公开发布不会重跑或调优 Final。

| 指标 | 冻结结果 |
|---|---:|
| Formal V2 Final100 contract | **81/100** |
| 支持的 repair targets | **78/95** |
| 条件自动修复 | **66/66** |
| 整体自动修复 | **66/95** |
| ambiguity 判断 | **10/10** |
| wrong modification | **0** |
| partial-as-full | **0** |
| process failure | **0** |
| non-target preservation | **95/95** |

冻结的 Joint solver 与 Greedy 基线对比如下：

| 对比 | Joint | Greedy |
|---|---:|---:|
| contract 正确 | **81** | 55 |
| wrong modification | **0** | 19 |
| ambiguity contract | **10/10** | 0/10 |

这些数字只适用于冻结 benchmark，不能解释为任意 IDF 错误的通用修复率。
EnergyPlus 运行用于验证已提交产物，不在修复推理中充当语义 oracle。

## 方法

冻结流程为：

```text
已有 IDF + 精确 IDD
  -> 版本绑定的 typed ports 与 compound-flow relations
  -> target-free whole-model constraint scan
  -> 完整有限 semantic edit domain
  -> conflict-component joint minimum search
  -> unique-optimum gate 或安全 abstention
  -> guarded source-span write-back
  -> global semantic closure
  -> 独立 EnergyPlus execution validation
```

当前 relation frontier 覆盖 Branch path、Loop/Connector、Zone equipment、
AirPath 与 OutdoorAir equipment path。unsupported、证据不完整、候选域截断或存在
非等价等最优解释时，系统不会静默提交修改。

## 安装

需要 Python 3.10 或更高版本。EnergyPlus 是外部依赖，本仓库不会下载或分发其
二进制文件。

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

## 最小语义诊断与修复

必须把 IDF 绑定到该模型使用的精确 EnergyPlus IDD：

```python
from pathlib import Path

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import repair_model, scan_model

idf_text = Path("model.idf").read_text(encoding="utf-8-sig")
idd = parse_idd(Path("/path/to/Energy+.idd").read_text(encoding="utf-8"))
document = parse_idf(idf_text)

diagnosis = scan_model(document, idd)
outcome = repair_model(idf_text, idd)
print(diagnosis.violations)
print(outcome.status, outcome.output_text)
```

公开 API 只接收当前 IDF 与精确 IDD，不接收 clean target、mutation family、
locator、私有 oracle 或 expected edit。

## 复现 headline 指标

以下命令只读取冻结 result 与 guard，不导入 repair runtime、不生成 prediction，
也不为 Final 重新评分：

```bash
python scripts/public_reproduce_formal_v2.py
python scripts/public_reproduce_formal_v2.py --json
```

## 测试

```bash
python -m pytest -q
python -m compileall -q src tools scripts tests
git diff --check
```

版本边界、公开 benchmark 构建、安全门和 fresh-clone 流程见
[公开复现说明](docs/reproducibility/public_release.md)。

## 航站楼 occupancy 扩展

occupancy namespace 是下游分析流程，不是新的 repair method。它提取
People→Zone→HVAC 关系，生成确定性的 15 分钟场景，并在 passenger-hours 相同的
前提下比较时间与空间重分布。人数总量敏感性单独报告。两个用户自建航站楼 OSM
原文件及所有 raw derivatives 均保持私有，公开内容只包含聚合 inventory 与哈希。

## 目录

- `src/idfrepair/semantic_graph_v2/`：冻结语义投影与修复。
- `src/idfrepair/analysis/occupancy/`：隔离的下游 occupancy 分析。
- `tests/`：单元、安全、冻结回归和复现测试。
- `scripts/`：公开指标与 occupancy 入口。
- `docs/research/`：方法身份、claim 边界和 occupancy 研究。
- `datasets/manifests/`：source URL、fingerprint 与 qualification metadata；不复制
  DOE raw model。
- `reports/`：紧凑冻结证据与下游结果。

## 范围与引用

可辩护的贡献是 EnergyPlus-specific composition：version-bound semantic
projection、IDF-internal evidence、bounded joint minimum repair、
uniqueness-aware safe abstention、guarded exact write-back 与 global closure。
本项目不主张首个 HVAC knowledge graph、通用 graph repair 或自动 EnergyPlus
模型生成器。

引用信息见 [CITATION.cff](CITATION.cff)。代码采用 [MIT License](LICENSE)。
EnergyPlus 与 DOE 第三方资产保留各自许可证，本仓库不捆绑这些资产。
