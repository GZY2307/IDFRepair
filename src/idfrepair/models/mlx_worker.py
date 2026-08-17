'''在隔离 Python 中加载一次 MLX 模型并提供有界 JSON Lines 推理。

该模块只接受绝对本地目录，启动时逐张量验证 adapter，且从不解析远程
模型标识符。标准输出专用于协议，加载日志写入标准错误。
'''

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any


class WorkerError(RuntimeError):
    '''表示模型加载、adapter 校验或确定性生成失败。'''


def _sha256_file(path: Path) -> str:
    '''流式计算大型权重文件摘要，不复制模型资产。'''
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_directory(value: str, required: tuple[str, ...]) -> Path:
    '''拒绝非绝对或缺失目录，防止库把输入解释为远程仓库。'''
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise WorkerError("model_path_must_be_absolute")
    path = raw.resolve()
    if not path.is_dir():
        raise WorkerError("model_directory_not_found")
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise WorkerError("model_files_missing:" + ",".join(missing))
    return path


def validate_loaded_adapter(model: Any, adapter_dir: Path) -> dict[str, Any]:
    '''逐键比较 adapter safetensors 与已加载 MLX 参数树的名称和形状。'''
    from mlx.utils import tree_flatten
    from safetensors import safe_open

    parameters = dict(tree_flatten(model.parameters()))
    expected: dict[str, tuple[int, ...]] = {}
    adapter_path = adapter_dir / "adapters.safetensors"
    with safe_open(adapter_path, framework="numpy") as stream:
        for key in stream.keys():
            expected[key] = tuple(stream.get_slice(key).get_shape())
    actual = {
        key: tuple(value.shape)
        for key, value in parameters.items()
        if ".lora_" in key
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = {
        key: {"actual": actual[key], "expected": expected[key]}
        for key in sorted(set(expected) & set(actual))
        if expected[key] != actual[key]
    }
    if missing or extra or mismatched:
        raise WorkerError(json.dumps({
            "extra": extra,
            "missing": missing,
            "shape_mismatch": mismatched,
        }, sort_keys=True))
    return {
        "adapter_tensor_count": len(expected),
        "adapter_weights_sha256": _sha256_file(adapter_path),
        "loaded_lora_tensor_count": len(actual),
        "tensor_membership_match": True,
        "tensor_shape_match": True,
    }


def _top_indices(mx: Any, scores: Any, count: int) -> list[tuple[float, int]]:
    '''以分数和 token 索引稳定排序返回一维数组前若干项。'''
    count = min(count, int(scores.size))
    indices = mx.argpartition(-scores, kth=count - 1, axis=-1)[:count]
    values = scores[indices]
    mx.eval(indices, values)
    rows = [(float(score), int(index)) for score, index in zip(
        values.tolist(), indices.tolist(), strict=True,
    )]
    return sorted(rows, key=lambda item: (-item[0], item[1]))


def _repeat_cache(mx: Any, prompt_cache: list[Any], beams: int) -> None:
    '''把单样本提示缓存复制为并行束。'''
    for cache in prompt_cache:
        state = cache.state
        if not isinstance(state, tuple) or len(state) != 2:
            raise WorkerError("unsupported_mlx_cache_state")
        cache.state = tuple(mx.repeat(value, beams, axis=0) for value in state)


def _select_cache(mx: Any, prompt_cache: list[Any], parents: list[int]) -> None:
    '''按父束索引重排 KV 缓存，避免束之间交叉污染。'''
    indices = mx.array(parents)
    for cache in prompt_cache:
        cache.state = tuple(mx.take(value, indices, axis=0) for value in cache.state)


def beam_generate(
    model: Any,
    tokenizer: Any,
    prompt: str,
    *,
    max_tokens: int = 96,
    beams: int = 3,
) -> dict[str, Any]:
    '''执行确定性三束搜索，保留完整提示并显式报告长度终止。'''
    import mlx.core as mx
    from mlx_lm.models.cache import make_prompt_cache

    if beams != 3:
        raise WorkerError("only_three_beams_supported")
    if not 1 <= max_tokens <= 192:
        raise WorkerError("max_tokens_out_of_range")
    token_ids = tokenizer.encode(prompt, add_special_tokens=True)
    if not token_ids or len(token_ids) > 1024:
        raise WorkerError(f"untruncated_prompt_budget_invalid:{len(token_ids)}")
    eos_ids = set(tokenizer.eos_token_ids)
    prompt_cache = make_prompt_cache(model)
    started = time.perf_counter()

    logits = model(mx.array(token_ids)[None], cache=prompt_cache)[:, -1, :]
    logits = logits.astype(mx.float32)
    log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    initial = _top_indices(mx, log_probs[0], beams * 2)
    sequences: list[list[int]] = []
    scores: list[float] = []
    finished: list[tuple[float, list[int]]] = []
    for rank, (score, token) in enumerate(initial):
        if token in eos_ids:
            if rank < beams:
                finished.append((score, [token]))
        elif len(sequences) < beams:
            sequences.append([token])
            scores.append(score)
    if len(sequences) != beams:
        raise WorkerError("beam_initialization_failed")
    _repeat_cache(mx, prompt_cache, beams)

    finish_reason = "length"
    while max(len(item) for item in sequences) < max_tokens:
        last_tokens = mx.array([[item[-1]] for item in sequences])
        logits = model(last_tokens, cache=prompt_cache)[:, -1, :].astype(mx.float32)
        log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        total = log_probs + mx.array(scores)[:, None]
        vocabulary = int(total.shape[-1])
        candidates = _top_indices(mx, total.reshape(-1), beams * 2)
        next_sequences: list[list[int]] = []
        next_scores: list[float] = []
        parents: list[int] = []
        for rank, (score, flat_index) in enumerate(candidates):
            parent, token = divmod(flat_index, vocabulary)
            candidate = sequences[parent] + [token]
            if token in eos_ids:
                if rank < beams:
                    finished.append((score, candidate))
            elif len(next_sequences) < beams:
                next_sequences.append(candidate)
                next_scores.append(score)
                parents.append(parent)
            if len(next_sequences) == beams and len(finished) >= beams:
                break
        if len(finished) >= beams:
            finish_reason = "stop"
            break
        if len(next_sequences) != beams:
            raise WorkerError("beam_continuation_failed")
        _select_cache(mx, prompt_cache, parents)
        sequences, scores = next_sequences, next_scores
        mx.eval([cache.state for cache in prompt_cache])

    pool = list(finished)
    if len(pool) < beams:
        pool.extend(zip(scores, sequences, strict=True))
    ranked = sorted(
        pool,
        key=lambda item: (-(item[0] / max(1, len(item[1]))), item[1]),
    )[:beams]
    token_sequences = tuple(tuple(item[1]) for item in ranked)
    texts = tuple(
        tokenizer.decode(list(tokens), skip_special_tokens=True).strip()
        for tokens in token_sequences
    )
    return {
        "elapsed_seconds": time.perf_counter() - started,
        "finish_reason": finish_reason,
        "generated_tokens": sum(len(item) for item in token_sequences),
        "input_tokens": len(token_ids),
        "texts": texts,
    }


def _load(model_name: str, base: Path, adapter: Path) -> tuple[Any, Any, dict[str, Any]]:
    '''加载本地基础模型和 adapter，并返回可审计的运行时身份。'''
    import mlx.core as mx
    import mlx_lm
    import psutil
    from mlx_lm import load
    from mlx_lm.utils import load_tokenizer

    adapter_configuration = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
    expected = {"qwen3-1.7b": "Qwen/Qwen3-1.7B", "qwen3-8b": "Qwen/Qwen3-8B"}[model_name]
    adapter_identity = adapter_configuration.get("base_model_id", adapter_configuration.get("model"))
    if adapter_identity != expected:
        raise WorkerError("adapter_base_model_identity_mismatch")
    process = psutil.Process()
    rss_before = process.memory_info().rss
    mx.clear_cache()
    mx.reset_peak_memory()
    started = time.perf_counter()
    with redirect_stdout(sys.stderr):
        loaded_model, _ = load(str(base), adapter_path=str(adapter))
        tokenizer = load_tokenizer(str(base))
    adapter_validation = validate_loaded_adapter(loaded_model, adapter)
    mx.eval(loaded_model.parameters())
    return loaded_model, tokenizer, {
        "adapter_validation": adapter_validation,
        "api_fallback_used": False,
        "load_seconds": time.perf_counter() - started,
        "mlx": mx.__version__,
        "mlx_lm": mlx_lm.__version__,
        "model": model_name,
        "offline_only": True,
        "peak_metal_bytes": int(mx.get_peak_memory()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "rss_after_load_bytes": process.memory_info().rss,
        "rss_before_bytes": rss_before,
    }


def _parser() -> argparse.ArgumentParser:
    '''构造只接受本地路径的工作进程参数。'''
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("qwen3-1.7b", "qwen3-8b"), required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--adapter", required=True)
    return parser


def main() -> int:
    '''加载模型后持续处理请求，单次失败不会伪装成模型决定。'''
    arguments = _parser().parse_args()
    try:
        base = _local_directory(arguments.base, ("config.json", "tokenizer.json"))
        adapter = _local_directory(
            arguments.adapter, ("adapter_config.json", "adapters.safetensors"),
        )
        model, tokenizer, runtime = _load(arguments.model, base, adapter)
    except Exception as exc:
        print(json.dumps({
            "error": f"{type(exc).__name__}:{exc}",
            "event": "ready",
            "ok": False,
        }, ensure_ascii=False, sort_keys=True), flush=True)
        return 2
    print(json.dumps({
        "event": "ready", "ok": True, "runtime": runtime,
    }, ensure_ascii=False, sort_keys=True), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = beam_generate(
                model,
                tokenizer,
                str(request["prompt"]),
                max_tokens=int(request.get("max_tokens", 96)),
                beams=int(request.get("beams", 3)),
            )
            response = {
                **result,
                "ok": True,
                "request_id": str(request["request_id"]),
            }
        except Exception as exc:
            response = {
                "error": f"{type(exc).__name__}:{exc}",
                "ok": False,
                "request_id": (
                    str(request.get("request_id", "unknown"))
                    if isinstance(locals().get("request"), dict) else "unknown"
                ),
            }
        print(json.dumps(response, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkerError", "beam_generate", "main", "validate_loaded_adapter"]
