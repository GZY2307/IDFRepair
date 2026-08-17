'''
提供目录、ZIP 和多 IDF 输入的隔离批量修复入口。
'''

from idfrepair.batch.runner import (
    BatchInput, BatchResult, discover_inputs, discover_uploaded_inputs, run_batch,
)

__all__ = [
    "BatchInput", "BatchResult", "discover_inputs", "discover_uploaded_inputs", "run_batch",
]
