"""冻结 V2 方法的独立 Formal Final 评估入口。

select_membership(): 按预注册配额确定性选择 Final membership。
assert_runtime_manifest(): 验证 runtime 侧字段隔离与 opaque identity。
"""

from .builder import Candidate, FinalEdit, choose_final_size, select_membership
from .seals import assert_runtime_manifest, sha256_file

__all__ = [
    "Candidate",
    "FinalEdit",
    "assert_runtime_manifest",
    "choose_final_size",
    "select_membership",
    "sha256_file",
]
