'''定义模型只能在有限目录中作答的关闭世界选择协议。

format_selector_prompt(): 构造不含评分器或 gold 的紧凑提示。
parse_selector_decision(): 严格验证三个字段及目录成员资格。
'''

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping

from idfrepair.domain.errors import ModelContractError


OUTPUT_TYPES = frozenset({
    "ROOT_FAMILY", "TARGET_ID", "TOOL_NAME", "MODEL_DECISION",
})
PROMPT_INSTRUCTION = (
    "Return exactly one compact JSON object with keys output_type,value,evidence_codes. "
    "Select only a supplied identifier; no prose.\n"
)


@dataclass(frozen=True, slots=True)
class SelectorDecision:
    '''封装一个经过目录成员校验的模型决定。'''

    output_type: str
    value: str
    evidence_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        '''返回稳定且可直接审计的 JSON 结构。'''
        return {
            "output_type": self.output_type,
            "value": self.value,
            "evidence_codes": list(self.evidence_codes),
        }


def format_selector_prompt(task: str, visible: Mapping[str, Any]) -> str:
    '''生成与本地选择器训练契约一致的无截断紧凑提示。'''
    payload = {"task": task, **dict(visible)}
    return (
        PROMPT_INSTRUCTION
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\nJSON:"
    )


def parse_selector_decision(
    value: str | Mapping[str, Any],
    *,
    expected_output_type: str,
    allowed_values: Iterable[str],
) -> SelectorDecision:
    '''只接受完整 JSON、冻结字段和当前提示显式提供的标识符。'''
    if expected_output_type not in OUTPUT_TYPES:
        raise ValueError("selector_output_type_unknown")
    if isinstance(value, str):
        try:
            payload = json.loads(value.strip())
        except (json.JSONDecodeError, TypeError) as exc:
            raise ModelContractError("selector_invalid_json") from exc
    else:
        payload = dict(value)
    if not isinstance(payload, Mapping) or set(payload) != {
        "output_type", "value", "evidence_codes",
    }:
        raise ModelContractError("selector_fields_invalid")
    if payload.get("output_type") != expected_output_type:
        raise ModelContractError("selector_output_type_mismatch")
    selected = payload.get("value")
    if not isinstance(selected, str) or selected not in frozenset(allowed_values):
        raise ModelContractError("selector_value_outside_catalog")
    evidence = payload.get("evidence_codes")
    if (
        not isinstance(evidence, list)
        or not 1 <= len(evidence) <= 8
        or len(evidence) != len(set(evidence))
        or not all(
            isinstance(item, str)
            and item
            and all(character.isupper() or character.isdigit() or character == "_" for character in item)
            for item in evidence
        )
    ):
        raise ModelContractError("selector_evidence_codes_invalid")
    return SelectorDecision(expected_output_type, selected, tuple(evidence))


__all__ = [
    "OUTPUT_TYPES",
    "PROMPT_INSTRUCTION",
    "SelectorDecision",
    "format_selector_prompt",
    "parse_selector_decision",
]
