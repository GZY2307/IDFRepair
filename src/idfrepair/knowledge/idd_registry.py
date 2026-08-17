'''
发现、校验并解析本机可用的 EnergyPlus IDD 版本注册表。

inventory_idd(): 读取单个 IDD 的版本、摘要和结构统计。
discover_idds(): 在显式目录中发现并登记 Energy+.idd。
resolve_registry(): 将内存映射或 JSON 注册表解析为版本绑定 schema。
'''

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from idfrepair.knowledge.idd import IDDSchema, parse_idd


_VERSION = re.compile(r"!\s*IDD[_ ]Version\s+([0-9]+(?:\.[0-9]+)+)", re.I)


def _file_sha(path: Path) -> str:
    '''分块计算本地 IDD 文件摘要。'''
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_idd(path: Path | str) -> dict[str, Any]:
    '''
    读取一个 IDD 文件并生成版本、摘要和结构统计。

    :param path: 明确的本地 Energy+.idd 路径。
    :return: 不含可变运行状态的库存记录。
    '''
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    text = target.read_text(encoding="utf-8", errors="replace")
    schema = parse_idd(text)
    match = _VERSION.search(text[:16384])
    version = match.group(1) if match else schema.version
    return {
        "version": version,
        "idd_path": str(target),
        "idd_sha256": _file_sha(target),
        "byte_count": target.stat().st_size,
        "object_count": len(schema.objects),
        "field_count": sum(len(obj.fields) for obj in schema.objects.values()),
        "source": {"kind": "local_discovery"},
    }


def discover_idds(search_roots: Sequence[Path | str]) -> dict[str, Any]:
    '''
    在显式受控目录及其一级子目录发现 IDD，不执行全盘扫描。

    :param search_roots: 调用方授权的安装目录或单个 IDD 文件。
    :return: 按版本和摘要排序的注册表及发现错误。
    '''
    candidates: set[Path] = set()
    for value in search_roots:
        root = Path(value).expanduser()
        if root.is_file() and root.name.casefold() in {"energy+.idd", "energyplus.idd"}:
            candidates.add(root.resolve())
        elif root.is_dir():
            for name in ("Energy+.idd", "EnergyPlus.idd"):
                direct = root / name
                if direct.is_file():
                    candidates.add(direct.resolve())
            candidates.update(path.resolve() for path in root.glob("*/Energy+.idd") if path.is_file())
    entries = []
    errors = []
    for path in sorted(candidates):
        try:
            entries.append(inventory_idd(path))
        except (OSError, ValueError) as exc:
            errors.append({"idd_path": str(path), "error": str(exc)})
    entries.sort(key=lambda row: (version_key(str(row["version"])), row["idd_sha256"]))
    return {
        "schema_version": "idfrepair.idd.registry.v1",
        "entries": entries,
        "versions": sorted({row["version"] for row in entries}, key=version_key),
        "errors": errors,
    }


def version_key(value: str) -> tuple[int, ...]:
    '''把点分版本转换为稳定数字排序键。'''
    try:
        return tuple(int(part) for part in value.split(".") if part != "")
    except ValueError:
        return ()


def _schema(value: Any, expected_sha256: str | None = None) -> IDDSchema | None:
    '''将 schema、IDD 正文、路径或注册条目解析为只读 IDD schema。'''
    if isinstance(value, IDDSchema):
        schema = value
    elif isinstance(value, Mapping):
        path_value = value.get("idd_path")
        text_value = value.get("idd_text")
        if path_value:
            path = Path(str(path_value)).expanduser().resolve()
            if not path.is_file():
                return None
            if value.get("idd_sha256") and _file_sha(path) != value["idd_sha256"]:
                return None
            schema = parse_idd(path.read_text(encoding="utf-8", errors="replace"))
        elif isinstance(text_value, str):
            schema = parse_idd(text_value)
        else:
            return None
    elif isinstance(value, str):
        candidate = Path(value).expanduser()
        if "\n" not in value and candidate.is_file():
            schema = parse_idd(candidate.read_text(encoding="utf-8", errors="replace"))
        else:
            schema = parse_idd(value)
    else:
        return None
    if expected_sha256 and schema.sha256 != expected_sha256:
        return None
    return schema


def resolve_registry(value: Any) -> dict[str, IDDSchema]:
    '''
    将调用方提供的版本映射或注册表条目解析为唯一版本 schema。

    摘要不匹配、重复版本内容不一致或文件缺失时，该版本不会进入结果。
    '''
    rows: dict[str, IDDSchema] = {}
    ambiguous: set[str] = set()
    if isinstance(value, Mapping) and isinstance(value.get("entries"), Sequence):
        values = [
            (str(row.get("version", "")), row)
            for row in value["entries"] if isinstance(row, Mapping)
        ]
    elif isinstance(value, Mapping):
        values = [(str(version), item) for version, item in value.items()]
    else:
        return {}
    for version, item in values:
        if not version:
            continue
        expected = str(item.get("idd_sha256")) if isinstance(item, Mapping) and item.get("idd_sha256") else None
        schema = _schema(item, expected)
        if schema is None:
            continue
        if version in rows and rows[version].sha256 != schema.sha256:
            ambiguous.add(version)
        else:
            rows[version] = schema
    for version in ambiguous:
        rows.pop(version, None)
    return rows


__all__ = ["discover_idds", "inventory_idd", "resolve_registry", "version_key"]
