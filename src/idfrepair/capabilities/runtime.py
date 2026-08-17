'''
验证 Provider 所依赖的 exact EnergyPlus、IDD 与可选 RDD 身份。

runtime_capability(): 对一个 CandidateContext 执行失败关闭的 runtime 自检。
'''

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from idfrepair.runtime.discovery import normalize_version


_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RuntimeCapability:
    '''封装 exact runtime 自检的逐项布尔证据。'''

    passed: bool
    energyplus_version: str
    executable_bound: bool
    idd_bound: bool
    version_bound: bool
    rdd_bound: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        '''返回可序列化的能力证据。'''
        return {
            "energyplus_version": self.energyplus_version,
            "executable_bound": self.executable_bound,
            "idd_bound": self.idd_bound,
            "passed": self.passed,
            "rdd_bound": self.rdd_bound,
            "reasons": list(self.reasons),
            "version_bound": self.version_bound,
        }


def runtime_capability(context: Any, *, require_rdd: bool = False) -> RuntimeCapability:
    '''要求 runtime version、executable SHA 与当前 IDD SHA 精确一致。'''
    identity = context.runtime_identity
    version = str(identity.get("energyplus_version") or "")
    executable_sha = str(identity.get("energyplus_executable_sha256") or "")
    runtime_idd_sha = str(identity.get("idd_sha256") or "")
    context_idd_sha = str(context.idd_sha256)
    version_bound = bool(
        version
        and normalize_version(version) == normalize_version(str(context.version))
    )
    executable_bound = bool(_SHA256.fullmatch(executable_sha))
    idd_bound = bool(
        _SHA256.fullmatch(runtime_idd_sha)
        and runtime_idd_sha.casefold() == context_idd_sha.casefold()
    )
    rdd_bound = bool(getattr(context.rdd, "text", "").strip())
    reasons = []
    if not version_bound:
        reasons.append("runtime_version_mismatch")
    if not executable_bound:
        reasons.append("runtime_executable_identity_missing")
    if not idd_bound:
        reasons.append("runtime_idd_identity_mismatch")
    if require_rdd and not rdd_bound:
        reasons.append("runtime_rdd_unavailable")
    return RuntimeCapability(
        passed=not reasons,
        energyplus_version=version,
        executable_bound=executable_bound,
        idd_bound=idd_bound,
        version_bound=version_bound,
        rdd_bound=rdd_bound,
        reasons=tuple(reasons),
    )


__all__ = ["RuntimeCapability", "runtime_capability"]
