'''发现并驱动完全离线的本地 Qwen/MLX 选择器进程。

inspect_qwen_runtime(): 校验本地基础模型、adapter 和隔离 Python 运行时。
QwenPlannerBackend: 复用一个已加载模型的 JSON Lines 子进程并严格解析输出。
'''

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping, TextIO
from uuid import uuid4

from idfrepair.domain.errors import ModelContractError
from idfrepair.models.selector import (
    SelectorDecision, format_selector_prompt, parse_selector_decision,
)


SUPPORTED_MODELS = {
    "qwen3-1.7b": "Qwen/Qwen3-1.7B",
    "qwen3-8b": "Qwen/Qwen3-8B",
}
_MODEL_ENV = {
    "qwen3-1.7b": ("IDFREPAIR_QWEN3_1_7B_BASE", "IDFREPAIR_QWEN3_1_7B_ADAPTER"),
    "qwen3-8b": ("IDFREPAIR_QWEN3_8B_BASE", "IDFREPAIR_QWEN3_8B_ADAPTER"),
}
_BASE_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json")
_ADAPTER_FILES = ("adapter_config.json", "adapters.safetensors")


@dataclass(frozen=True, slots=True)
class QwenRuntimeStatus:
    '''描述推理前的本地资产与 MLX 依赖可用性。'''

    model: str
    base_model_id: str
    base_path: str | None
    adapter_path: str | None
    runtime_python: str | None
    available: bool
    reasons: tuple[str, ...] = ()
    runtime_versions: Mapping[str, str] | None = None
    offline_only: bool = True

    def to_dict(self) -> dict[str, object]:
        '''返回不会触发模型下载或加载的运行时清点结果。'''
        return {
            "adapter_path": self.adapter_path,
            "available": self.available,
            "base_model_id": self.base_model_id,
            "base_path": self.base_path,
            "model": self.model,
            "offline_only": True,
            "reasons": list(self.reasons),
            "runtime_python": self.runtime_python,
            "runtime_versions": dict(self.runtime_versions or {}),
        }


@dataclass(frozen=True, slots=True)
class QwenSelection:
    '''封装一次真实生成、严格解析和运行时度量。'''

    decision: SelectorDecision
    record: Mapping[str, Any]


def _configured_path(value: str | Path | None, environment_name: str) -> Path | None:
    '''只把显式路径或环境变量解释为本地目录，不接受模型仓库标识符。'''
    raw = value if value is not None else os.environ.get(environment_name)
    if raw is None or str(raw).strip() == "":
        return None
    return Path(raw).expanduser().resolve()


def _runtime_path(value: str | Path | None) -> Path | None:
    '''解析隔离 Python；默认仅在当前解释器已安装 MLX 时使用它。'''
    raw = value if value is not None else os.environ.get("IDFREPAIR_MLX_PYTHON")
    if raw is not None and str(raw).strip():
        path = Path(raw).expanduser()
        return path if path.is_absolute() else path.absolute()
    if importlib.util.find_spec("mlx") is not None and importlib.util.find_spec("mlx_lm") is not None:
        return Path(sys.executable).resolve()
    return None


def _check_directory(path: Path | None, required: tuple[str, ...], prefix: str) -> list[str]:
    '''检查目录和冻结文件集合，同时拒绝可能触发远程解析的缺失路径。'''
    if path is None:
        return [f"{prefix}_path_not_configured"]
    if not path.is_absolute() or not path.is_dir():
        return [f"{prefix}_directory_not_found"]
    reasons = [f"{prefix}_file_missing:{name}" for name in required if not (path / name).is_file()]
    if prefix == "base" and not tuple(path.glob("*.safetensors")):
        reasons.append("base_safetensors_missing")
    return reasons


def _probe_runtime(path: Path | None) -> tuple[dict[str, str], list[str]]:
    '''在不加载权重的独立解释器中确认 MLX、MLX-LM 和 safetensors。'''
    if path is None:
        return {}, ["mlx_runtime_not_configured"]
    if not path.is_file() or not os.access(path, os.X_OK):
        return {}, ["mlx_runtime_not_executable"]
    script = (
        "import json,importlib.metadata as m;"
        "print(json.dumps({'mlx':m.version('mlx'),'mlx_lm':m.version('mlx-lm'),"
        "'safetensors':m.version('safetensors')},sort_keys=True))"
    )
    environment = {**os.environ, **_offline_environment()}
    try:
        result = subprocess.run(
            [str(path), "-c", script],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}, ["mlx_runtime_probe_failed"]
    if result.returncode != 0:
        return {}, ["mlx_runtime_import_failed"]
    try:
        versions = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {}, ["mlx_runtime_probe_invalid"]
    if not isinstance(versions, dict):
        return {}, ["mlx_runtime_probe_invalid"]
    return {str(key): str(value) for key, value in versions.items()}, []


def inspect_qwen_runtime(
    model: str,
    *,
    base_path: str | Path | None = None,
    adapter_path: str | Path | None = None,
    runtime_python: str | Path | None = None,
) -> QwenRuntimeStatus:
    '''校验本地路径与运行时依赖；该操作不会加载权重或访问网络。'''
    if model not in SUPPORTED_MODELS:
        raise ValueError("unsupported_qwen_model")
    base_environment, adapter_environment = _MODEL_ENV[model]
    base = _configured_path(base_path, base_environment)
    adapter = _configured_path(adapter_path, adapter_environment)
    runtime = _runtime_path(runtime_python)
    reasons = _check_directory(base, _BASE_FILES, "base")
    reasons.extend(_check_directory(adapter, _ADAPTER_FILES, "adapter"))
    versions, runtime_reasons = _probe_runtime(runtime)
    reasons.extend(runtime_reasons)
    return QwenRuntimeStatus(
        model=model,
        base_model_id=SUPPORTED_MODELS[model],
        base_path=str(base) if base else None,
        adapter_path=str(adapter) if adapter else None,
        runtime_python=str(runtime) if runtime else None,
        available=not reasons,
        reasons=tuple(reasons),
        runtime_versions=versions,
    )


def _offline_environment() -> dict[str, str]:
    '''返回禁止 Hugging Face、Transformers 和遥测网络访问的环境变量。'''
    return {
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }


class QwenPlannerBackend:
    '''通过一个持久 MLX 子进程执行确定性三束关闭世界选择。'''

    def __init__(
        self,
        model: str,
        *,
        base_path: str | Path | None = None,
        adapter_path: str | Path | None = None,
        runtime_python: str | Path | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.status = inspect_qwen_runtime(
            model,
            base_path=base_path,
            adapter_path=adapter_path,
            runtime_python=runtime_python,
        )
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("model_timeout_must_be_positive")
        self._process: subprocess.Popen[str] | None = None
        self._log: TextIO | None = None
        self._lock = threading.Lock()
        self.runtime_metadata: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        '''表示静态资产和 Python 依赖是否满足启动条件。'''
        return self.status.available

    def _read_line(self, timeout: float) -> str:
        '''在有限时间内读取一个工作进程协议行。'''
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("model_worker_not_started")
        ready, _, _ = select.select([process.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError("model_worker_response_timeout")
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"model_worker_exited:{process.poll()}:{self._log_tail()}")
        return line

    def _log_tail(self) -> str:
        '''读取隔离临时日志尾部，避免把模型日志混入 JSON 协议。'''
        if self._log is None:
            return ""
        try:
            self._log.flush()
            self._log.seek(0)
            return self._log.read()[-4000:]
        except OSError:
            return ""

    def start(self) -> Mapping[str, Any]:
        '''加载一次模型和 adapter，并验证所有 LoRA 张量名称与形状。'''
        if not self.available:
            raise RuntimeError("model_runtime_unavailable:" + ";".join(self.status.reasons))
        if self._process is not None and self._process.poll() is None:
            return self.runtime_metadata
        assert self.status.runtime_python is not None
        assert self.status.base_path is not None
        assert self.status.adapter_path is not None
        self._log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        source_root = str(Path(__file__).resolve().parents[2])
        environment = {**os.environ, **_offline_environment()}
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_root if not existing_pythonpath else source_root + os.pathsep + existing_pythonpath
        )
        command = [
            self.status.runtime_python,
            "-m", "idfrepair.models.mlx_worker",
            "--model", self.status.model,
            "--base", self.status.base_path,
            "--adapter", self.status.adapter_path,
        ]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            text=True,
            bufsize=1,
            env=environment,
        )
        try:
            payload = json.loads(self._read_line(self.timeout_seconds))
        except Exception:
            self.close()
            raise
        if not isinstance(payload, dict) or payload.get("event") != "ready" or not payload.get("ok"):
            detail = payload.get("error") if isinstance(payload, dict) else "invalid_ready_event"
            self.close()
            raise RuntimeError(f"model_worker_start_failed:{detail}")
        self.runtime_metadata = dict(payload.get("runtime", {}))
        return self.runtime_metadata

    def select(
        self,
        *,
        task: str,
        visible: Mapping[str, Any],
        expected_output_type: str,
        allowed_values: Iterable[str],
        max_tokens: int = 96,
    ) -> QwenSelection:
        '''真实生成三束响应，并选择首个满足 schema 与当前目录的结果。'''
        allowed = tuple(sorted(set(str(item) for item in allowed_values)))
        if not allowed:
            raise ModelContractError("selector_catalog_empty")
        prompt = format_selector_prompt(task, visible)
        request_id = uuid4().hex
        with self._lock:
            self.start()
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("model_worker_not_started")
            request = {
                "request_id": request_id,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "beams": 3,
            }
            started = time.perf_counter()
            try:
                process.stdin.write(
                    json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n",
                )
                process.stdin.flush()
                payload = json.loads(self._read_line(self.timeout_seconds))
            except Exception:
                # A timeout or transport failure leaves the worker free to emit a
                # late response for this request.  Reusing that process would make
                # the next request consume the stale response and desynchronise the
                # JSON Lines protocol, so fail closed and force a clean reload.
                self.close()
                raise
            wall_seconds = time.perf_counter() - started
            if not isinstance(payload, dict) or payload.get("request_id") != request_id:
                self.close()
                raise RuntimeError("model_worker_protocol_mismatch")
            if not payload.get("ok"):
                raise RuntimeError(f"model_generation_failed:{payload.get('error', 'unknown')}")
            texts = payload.get("texts")
            if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
                self.close()
                raise RuntimeError("model_worker_texts_invalid")
        failures: list[str] = []
        decision: SelectorDecision | None = None
        selected_beam: int | None = None
        for index, text in enumerate(texts):
            try:
                decision = parse_selector_decision(
                    text,
                    expected_output_type=expected_output_type,
                    allowed_values=allowed,
                )
                selected_beam = index
                break
            except ModelContractError as exc:
                failures.append(str(exc))
        if decision is None:
            raise ModelContractError("selector_all_beams_invalid:" + ",".join(failures))
        record = {
            "allowed_value_count": len(allowed),
            "decision": decision.to_dict(),
            "finish_reason": payload.get("finish_reason"),
            "generated_tokens_all_beams": payload.get("generated_tokens"),
            "input_tokens": payload.get("input_tokens"),
            "model": self.status.model,
            "offline_only": True,
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
            "request_id": request_id,
            "runtime": dict(self.runtime_metadata),
            "schema_failures_before_selection": failures,
            "selected_beam": selected_beam,
            "task": task,
            "wall_seconds": wall_seconds,
        }
        return QwenSelection(decision, record)

    def close(self) -> None:
        '''终止本地工作进程并关闭只位于临时目录的诊断日志。'''
        process = self._process
        self._process = None
        if process is not None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> "QwenPlannerBackend":
        '''在上下文中显式加载工作进程。'''
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        '''退出上下文时释放模型统一内存。'''
        self.close()


__all__ = [
    "QwenPlannerBackend",
    "QwenRuntimeStatus",
    "QwenSelection",
    "SUPPORTED_MODELS",
    "inspect_qwen_runtime",
]
