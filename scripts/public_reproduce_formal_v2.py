#!/usr/bin/env python3
"""只读汇总冻结 Formal V2 Final100 公开指标。

build_summary(): 从冻结结果和 guard 构造紧凑公开指标。
main(): 以表格或 JSON 输出指标，不导入 repair runtime。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def _ratio(value: object) -> str:
    """把含 numerator/denominator 的冻结字段格式化为原始计数比。"""

    if not isinstance(value, dict):
        raise ValueError("frozen_ratio_must_be_object")
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise ValueError("frozen_ratio_counts_must_be_integers")
    return f"{numerator}/{denominator}"


def build_summary(root: Path = ROOT) -> dict[str, object]:
    """读取并交叉核对冻结结果，返回不触发推理或评分的公开摘要。"""

    results = json.loads(
        (root / "reports/semantic_graph_final/main_results.json").read_text(
            encoding="utf-8"
        )
    )
    guard = json.loads(
        (root / "reports/post_final/frozen_evidence_guard.json").read_text(
            encoding="utf-8"
        )
    )
    if results.get("final_size") != 100 or guard.get("final_size") != 100:
        raise ValueError("formal_v2_final_size_mismatch")
    if guard.get("scoring_runs") != 1:
        raise ValueError("formal_v2_scoring_run_count_changed")
    if results.get("method_modified_after_final") is not False:
        raise ValueError("formal_v2_method_modified")
    strata = results.get("strata")
    greedy = results.get("greedy")
    if not isinstance(strata, dict) or not isinstance(greedy, dict):
        raise ValueError("frozen_result_sections_missing")
    return {
        "schema_version": "idfrepair.formal-v2-public-summary.v1",
        "formal_v2_final100": _ratio(results["overall_contract"]),
        "support": _ratio(results["support_coverage"]),
        "conditional_auto_repair": _ratio(results["conditional_automatic_repair"]),
        "overall_auto_repair": _ratio(results["overall_automatic_repair"]),
        "ambiguity": _ratio(strata["ambiguity"]),
        "wrong_modification": results["wrong_modification_count"],
        "partial_as_full": results["partial_as_full_count"],
        "process_failure": results["process_failure_count"],
        "non_target_preservation": (
            f"{results['non_target_preserved_count']}/"
            f"{results['non_target_preservation_denominator']}"
        ),
        "joint_vs_greedy_contract": (
            f"{results['overall_contract']['numerator']} vs "
            f"{greedy['contract_correct']}"
        ),
        "joint_vs_greedy_wrong_modification": (
            f"{results['wrong_modification_count']} vs "
            f"{greedy['wrong_modification_count']}"
        ),
        "joint_vs_greedy_ambiguity": (
            f"{strata['ambiguity']['numerator']}/{strata['ambiguity']['denominator']}"
            f" vs {greedy['ambiguity_contract_correct']}/"
            f"{strata['ambiguity']['denominator']}"
        ),
        "method_identity": guard["method_identity"],
        "method_modified_after_final": results["method_modified_after_final"],
        "scoring_runs": guard["scoring_runs"],
    }


def _parser() -> argparse.ArgumentParser:
    """构造只读指标入口的参数解析器。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """输出冻结指标并返回成功状态。"""

    args = _parser().parse_args(argv)
    summary = build_summary(args.root)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
