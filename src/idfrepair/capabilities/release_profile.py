'''
加载唯一公共 Release Profile，并封闭所有未授权发布开关。

load_release_profile(): 校验文件 SHA、冻结身份、模式映射和全部 false 门禁。
release_profile_path(): 在源码树或离线 wheel 数据目录中定位同一配置。
'''

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from idfrepair.capabilities.models import SupportStatus
from idfrepair.domain.enums import RepairMode


EXPECTED_RELEASE_PROFILE_SHA256 = (
    "0fc97c3adb79c0a989c52fef963d57a57f484558a1b4e11a15eb292d9c2b1a9e"
)
EXPECTED_SUPPORT_REGISTRY_SHA256 = (
    "b5b2fec3cef6a580fca9735ce360dc0ae88713967c2b5e61e8c2a6445bc03c3f"
)
RELEASE_PROFILE_ID = "idfrepair.research_release.v1"
_FALSE_FLAGS = frozenset({
    "production_enabled",
    "automatic_repair_release_authorized",
    "model_enabled",
    "model_retraining_authorized",
    "model_product_integration_authorized",
    "repair_memory_candidate_generation_enabled",
    "repair_memory_release_authorized",
    "case_retrieval_candidate_generation_enabled",
    "paired_geometry_enabled",
    "geometry_snap_enabled",
    "geometry_four_point_enabled",
    "final_external_evaluation_authorized",
})


def _config_candidates(name: str) -> tuple[Path, ...]:
    '''返回源码 checkout 与 wheel data-files 的固定只读位置。'''
    source = Path(__file__).resolve().parents[3] / "configs" / name
    installed = Path(sys.prefix).resolve() / "idfrepair" / "configs" / name
    return source, installed


def release_profile_path() -> Path:
    '''定位唯一 Release Profile，不接受 CLI 或环境变量覆盖。'''
    for path in _config_candidates("release_profile.json"):
        if path.is_file():
            return path
    raise ValueError("SUPPORT_REGISTRY_INVALID:release_profile_missing")


def support_registry_path() -> Path:
    '''定位唯一 Support Registry，不接受 CLI 或环境变量覆盖。'''
    for path in _config_candidates("support_registry.json"):
        if path.is_file():
            return path
    raise ValueError("SUPPORT_REGISTRY_INVALID:support_registry_missing")


def support_registry_schema_path() -> Path:
    '''定位随源码和 wheel 一起交付的 JSON Schema。'''
    for path in _config_candidates("support_registry.schema.json"):
        if path.is_file():
            return path
    raise ValueError("SUPPORT_REGISTRY_INVALID:support_registry_schema_missing")


def _read_frozen_json(path: Path, expected_sha256: str, label: str) -> Mapping[str, Any]:
    '''按原始文件字节验证 SHA 后读取 JSON 对象。'''
    content = path.read_bytes()
    if sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f"SUPPORT_REGISTRY_INVALID:{label}_sha256_mismatch")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SUPPORT_REGISTRY_INVALID:{label}_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"SUPPORT_REGISTRY_INVALID:{label}_not_object")
    return payload


@dataclass(frozen=True, slots=True)
class ReleaseProfile:
    '''封装所有公共入口共享的冻结发布配置。'''

    release_profile_id: str
    support_registry_sha256: str
    mode_support_statuses: Mapping[RepairMode, frozenset[SupportStatus]]
    payload: Mapping[str, Any]
    sha256: str

    def allowed_statuses(self, mode: RepairMode) -> frozenset[SupportStatus]:
        '''返回模式允许生成候选的支持状态集合。'''
        return self.mode_support_statuses[mode]

    def to_dict(self) -> dict[str, Any]:
        '''返回原始冻结配置并附加自身 SHA。'''
        return {**dict(self.payload), "release_profile_sha256": self.sha256}


def load_release_profile() -> ReleaseProfile:
    '''加载并严格验证 public Release Profile 的固定身份和禁用开关。'''
    payload = _read_frozen_json(
        release_profile_path(), EXPECTED_RELEASE_PROFILE_SHA256, "release_profile",
    )
    if payload.get("schema_version") != "idfrepair.release_profile.v1":
        raise ValueError("SUPPORT_REGISTRY_INVALID:release_profile_schema_version")
    if payload.get("release_profile_id") != RELEASE_PROFILE_ID:
        raise ValueError("SUPPORT_REGISTRY_INVALID:release_profile_id")
    if payload.get("support_registry_sha256") != EXPECTED_SUPPORT_REGISTRY_SHA256:
        raise ValueError("SUPPORT_REGISTRY_INVALID:registry_identity_mismatch")
    for name in _FALSE_FLAGS:
        if payload.get(name) is not False:
            raise ValueError(f"SUPPORT_REGISTRY_INVALID:release_flag_enabled:{name}")
    if payload.get("assisted_geometry_enabled") is not True:
        raise ValueError("SUPPORT_REGISTRY_INVALID:assisted_geometry_flag")
    expected_modes = {
        RepairMode.ANALYZE_ONLY: frozenset(),
        RepairMode.SAFE_AUTO: frozenset({SupportStatus.SAFE_AUTO}),
        RepairMode.ASSISTED: frozenset({SupportStatus.SAFE_AUTO, SupportStatus.ASSISTED}),
        RepairMode.INTERACTIVE: frozenset({
            SupportStatus.SAFE_AUTO,
            SupportStatus.ASSISTED,
            SupportStatus.INTERACTIVE,
        }),
    }
    raw_modes = payload.get("mode_support_statuses")
    if not isinstance(raw_modes, Mapping):
        raise ValueError("SUPPORT_REGISTRY_INVALID:mode_support_statuses")
    actual_modes: dict[RepairMode, frozenset[SupportStatus]] = {}
    try:
        for mode in RepairMode:
            values = raw_modes[mode.value]
            if not isinstance(values, list):
                raise TypeError(mode.value)
            actual_modes[mode] = frozenset(SupportStatus(str(row)) for row in values)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("SUPPORT_REGISTRY_INVALID:mode_support_statuses") from exc
    if actual_modes != expected_modes:
        raise ValueError("SUPPORT_REGISTRY_INVALID:mode_support_policy_changed")
    return ReleaseProfile(
        release_profile_id=RELEASE_PROFILE_ID,
        support_registry_sha256=EXPECTED_SUPPORT_REGISTRY_SHA256,
        mode_support_statuses=actual_modes,
        payload=payload,
        sha256=EXPECTED_RELEASE_PROFILE_SHA256,
    )


__all__ = [
    "EXPECTED_RELEASE_PROFILE_SHA256",
    "EXPECTED_SUPPORT_REGISTRY_SHA256",
    "RELEASE_PROFILE_ID",
    "ReleaseProfile",
    "load_release_profile",
    "release_profile_path",
    "support_registry_path",
    "support_registry_schema_path",
]
