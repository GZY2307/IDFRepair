'''
解析 EnergyPlus EMS 对象，并建立数据符号表与可调用对象图。

normalize_ems_name(): 生成大小写无关的 EMS 标识。
parse_ems_statement(): 提取 Erl 语句中的读、写和调用关系。
parse_ems(): 解析八类核心 EMS 对象。
build_ems_symbols(): 建立全局、局部和未解析符号索引。
build_ems_calls(): 建立 CallingManager、Program 和 Subroutine 调用图。
'''

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping

from idfrepair.io.idf import canonical, parse_idf


EMS_OBJECT_TYPES = frozenset({
    "energymanagementsystem:program",
    "energymanagementsystem:subroutine",
    "energymanagementsystem:globalvariable",
    "energymanagementsystem:sensor",
    "energymanagementsystem:actuator",
    "energymanagementsystem:internalvariable",
    "energymanagementsystem:outputvariable",
    "energymanagementsystem:programcallingmanager",
})
_TOKEN = re.compile(r"(?<![@A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)")
_OPCODE = re.compile(r"^\s*([A-Za-z]+)\b\s*(.*)$")
_CONTROL_WORDS = frozenset({
    "set", "run", "if", "elseif", "else", "endif", "while", "endwhile",
    "return", "true", "false", "null", "and", "or", "not", "then",
})
_BUILTIN_NAMES = frozenset({
    "pi", "dayofmonth", "dayofweek", "dayofyear", "hour", "minute",
    "currenttime", "currentenvironment", "actualdateandtime", "actualtime",
    "warmupflag", "sunisup", "holiday", "dst", "systemtimestep",
    "zonetimestep", "year", "month",
})


def normalize_ems_name(name: str) -> str:
    '''规范化 EMS 标识的大小写和空白，不执行近似拼写折叠。'''
    return canonical(name).replace(" ", "")


def _tokens(expression: str) -> tuple[str, ...]:
    '''提取 Erl 表达式中的用户数据符号，并排除控制词和内置量。'''
    values: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(expression):
        value = match.group(1)
        key = normalize_ems_name(value)
        if key in _CONTROL_WORDS or key in _BUILTIN_NAMES or key in seen:
            continue
        seen.add(key)
        values.append(value)
    return tuple(values)


def parse_ems_statement(statement: str, field_index: int) -> dict[str, Any]:
    '''
    解析一条 Erl 字段的操作码、赋值目标、读取符号和 RUN 目标。

    :param statement: Program 或 Subroutine 中的完整 Erl 字段。
    :param field_index: 语句在所属 IDF 对象中的一基字段位置。
    :return: 保留原始语句位置的结构化关系。
    '''
    text = statement.strip()
    match = _OPCODE.match(text)
    opcode = match.group(1).upper() if match else ""
    body = match.group(2).strip() if match else text
    target = ""
    reads: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    parse_error = None
    if opcode == "SET":
        assignment = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", body)
        if assignment:
            target = assignment.group(1)
            reads = _tokens(assignment.group(2))
        else:
            parse_error = "malformed_set_statement"
    elif opcode == "RUN":
        call = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\b", body)
        if call:
            calls = (call.group(1),)
        else:
            parse_error = "malformed_run_statement"
    elif opcode in {"IF", "ELSEIF", "WHILE", "RETURN"}:
        reads = _tokens(body)
    elif opcode in {"ELSE", "ENDIF", "ENDWHILE"}:
        pass
    elif text:
        reads = _tokens(text)
        parse_error = "unsupported_erl_opcode"
    return {
        "field_index": field_index,
        "text": text,
        "opcode": opcode,
        "target": target,
        "reads": reads,
        "calls": calls,
        "parse_error": parse_error,
    }


def parse_ems(idf_text: str) -> dict[str, Any]:
    '''
    解析八类核心 EMS 对象，并保留每个定义和引用的 IDF 字段身份。

    :param idf_text: 当前故障侧 IDF 正文。
    :return: EMS 对象、程序、管理器和解析问题。
    '''
    document = parse_idf(idf_text)
    objects: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for obj in document.objects:
        object_type = canonical(obj.object_type)
        if object_type not in EMS_OBJECT_TYPES:
            continue
        values = [field.value.strip() for field in obj.fields]
        kind = object_type.split(":", 1)[-1]
        name = values[0] if values else ""
        row: dict[str, Any] = {
            "object_id": f"ems:{kind}#{obj.index}:{normalize_ems_name(name)}",
            "object_index": obj.index,
            "object_type": obj.object_type,
            "kind": kind,
            "name": name,
            "normalized_name": normalize_ems_name(name),
            "fields": tuple(values),
            "statements": (),
            "defined_symbols": (),
            "referenced_symbols": (),
            "manager_calls": (),
        }
        if kind in {"program", "subroutine"}:
            statements = tuple(
                parse_ems_statement(value, field_index)
                for field_index, value in enumerate(values[1:], start=2)
                if value
            )
            row["statements"] = statements
            issues.extend({
                "object_id": row["object_id"],
                "field_index": statement["field_index"],
                "statement": statement["text"],
                "issue": statement["parse_error"],
            } for statement in statements if statement["parse_error"])
        elif kind == "globalvariable":
            row["defined_symbols"] = tuple(value for value in values if value)
        elif kind in {"sensor", "actuator", "internalvariable"}:
            row["defined_symbols"] = (name,) if name else ()
        elif kind == "outputvariable":
            row["referenced_symbols"] = (values[1],) if len(values) > 1 and values[1] else ()
        elif kind == "programcallingmanager":
            row["manager_calls"] = tuple(value for value in values[2:] if value)
        objects.append(row)
    return {
        "schema_version": "idfrepair.ems.parse.v1",
        "status": "OK" if not issues else "PARSED_WITH_ISSUES",
        "objects": tuple(objects),
        "programs": tuple(row for row in objects if row["kind"] == "program"),
        "subroutines": tuple(row for row in objects if row["kind"] == "subroutine"),
        "calling_managers": tuple(
            row for row in objects if row["kind"] == "programcallingmanager"
        ),
        "issues": tuple(issues),
    }


def _occurrence(
    row: Mapping[str, Any], symbol: str, role: str, *,
    field_index: int, statement: Mapping[str, Any] | None = None,
    scope: str = "global",
) -> dict[str, Any]:
    '''生成可回溯到对象和字段的 EMS 符号出现位置。'''
    value = {
        "symbol": symbol,
        "normalized_symbol": normalize_ems_name(symbol),
        "role": role,
        "scope": scope,
        "object_id": row["object_id"],
        "object_index": row["object_index"],
        "object_type": row["object_type"],
        "field_index": field_index,
    }
    if statement is not None:
        value.update({"statement": statement["text"], "opcode": statement["opcode"]})
    return value


def build_ems_symbols(idf_text: str) -> dict[str, Any]:
    '''
    建立 EMS 全局与局部数据符号表，定位重复定义和未解析引用。

    SET 首次写入仅在当前 callable 内建立局部符号；显式对象定义始终属于全局作用域。

    :param idf_text: 当前故障侧 IDF 正文。
    :return: 定义、读写、重复项和未解析位置的完整索引。
    '''
    parsed = parse_ems(idf_text)
    definitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    local_defs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    reads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    writes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed["objects"]:
        for offset, symbol in enumerate(row["defined_symbols"], start=1):
            key = normalize_ems_name(symbol)
            if key:
                definitions[key].append(_occurrence(
                    row, symbol, f"{row['kind']}_definition", field_index=offset,
                ))
    for row in parsed["objects"]:
        if row["kind"] not in {"program", "subroutine"}:
            continue
        scope = str(row["object_id"])
        for statement in row["statements"]:
            target = str(statement["target"])
            if not target:
                continue
            key = normalize_ems_name(target)
            target_scope = "global" if key in definitions else scope
            if target_scope != "global" and not local_defs[(scope, key)]:
                local_defs[(scope, key)].append(_occurrence(
                    row, target, "local_definition", field_index=statement["field_index"],
                    statement=statement, scope=scope,
                ))
            writes[key].append(_occurrence(
                row, target, "write", field_index=statement["field_index"],
                statement=statement, scope=target_scope,
            ))
    unresolved: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed["objects"]:
        if row["kind"] in {"program", "subroutine"}:
            scope = str(row["object_id"])
            for statement in row["statements"]:
                for symbol in statement["reads"]:
                    key = normalize_ems_name(symbol)
                    occurrence = _occurrence(
                        row, symbol, "read", field_index=statement["field_index"],
                        statement=statement, scope=("global" if key in definitions else scope),
                    )
                    if key in definitions or (scope, key) in local_defs:
                        reads[key].append(occurrence)
                    else:
                        unresolved[key].append(occurrence)
        for symbol in row["referenced_symbols"]:
            key = normalize_ems_name(symbol)
            occurrence = _occurrence(
                row, symbol, "output_reference", field_index=2,
            )
            if key in definitions:
                reads[key].append(occurrence)
            else:
                unresolved[key].append(occurrence)
    all_keys = sorted(
        set(definitions) | set(reads) | set(writes) | set(unresolved)
        | {key for _, key in local_defs}
    )
    symbols = []
    for key in all_keys:
        local = [
            occurrence for (scope, local_key), values in local_defs.items()
            if local_key == key for occurrence in values
        ]
        symbols.append({
            "normalized_symbol": key,
            "definitions": tuple(definitions.get(key, ())),
            "local_definitions": tuple(local),
            "reads": tuple(reads.get(key, ())),
            "writes": tuple(writes.get(key, ())),
            "unresolved_occurrences": tuple(unresolved.get(key, ())),
            "ambiguous_global_definition": len(definitions.get(key, ())) > 1,
        })
    return {
        "schema_version": "idfrepair.ems.symbols.v1",
        "status": "OK" if not unresolved and all(len(v) == 1 for v in definitions.values()) else "SYMBOL_ISSUES_FOUND",
        "symbols": tuple(symbols),
        "global_symbols": {key: tuple(values) for key, values in sorted(definitions.items())},
        "local_symbols": {
            f"{scope}|{key}": tuple(values)
            for (scope, key), values in sorted(local_defs.items())
        },
        "undefined_symbols": tuple({
            "normalized_symbol": key,
            "spellings": tuple(sorted({row["symbol"] for row in values})),
            "occurrences": tuple(values),
            "reason": "no_exact_visible_definition",
        } for key, values in sorted(unresolved.items())),
        "duplicate_symbols": tuple({
            "normalized_symbol": key,
            "definitions": tuple(values),
        } for key, values in sorted(definitions.items()) if len(values) > 1),
        "parser_issues": parsed["issues"],
    }


def _cycles(nodes: tuple[str, ...], adjacency: Mapping[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    '''从批准的调用边中提取旋转规范化的稳定环路身份。'''
    found: set[tuple[str, ...]] = set()
    active: list[str] = []
    complete: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            body = active[active.index(node):]
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            found.add(min(rotations))
            return
        if node in complete:
            return
        active.append(node)
        for target in adjacency.get(node, ()):
            visit(target)
        active.pop()
        complete.add(node)

    for node in nodes:
        visit(node)
    return tuple(tuple((*cycle, cycle[0])) for cycle in sorted(found))


def build_ems_calls(idf_text: str) -> dict[str, Any]:
    '''
    建立 CallingManager 到 Program、RUN 到 Subroutine 的类型化调用图。

    缺失、多定义和角色冲突只形成问题记录，不形成可达边。

    :param idf_text: 当前故障侧 IDF 正文。
    :return: 节点、批准边、问题边、环路和可达闭包。
    '''
    parsed = parse_ems(idf_text)
    callables = (*parsed["programs"], *parsed["subroutines"])
    definitions: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in callables:
        definitions[row["normalized_name"]].append(row)
    nodes = tuple({
        "node_id": row["object_id"],
        "kind": row["kind"],
        "name": row["name"],
        "normalized_name": row["normalized_name"],
        "object_index": row["object_index"],
    } for row in (*callables, *parsed["calling_managers"]))
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    role_conflicts: list[dict[str, Any]] = []

    def add_call(
        source: Mapping[str, Any], target_name: str, relation: str,
        expected_kind: str, field_index: int, statement: str | None = None,
    ) -> None:
        key = normalize_ems_name(target_name)
        targets = definitions.get(key, [])
        location = {"object_index": source["object_index"], "field_index": field_index}
        if statement is not None:
            location["statement"] = statement
        issue = {
            "source_id": source["object_id"],
            "target_name": target_name,
            "normalized_target": key,
            "relation": relation,
            "expected_kind": expected_kind,
            "location": location,
        }
        compatible = [target for target in targets if target["kind"] == expected_kind]
        if not targets:
            unresolved.append({**issue, "reason": "callable_not_defined"})
        elif len(targets) > 1 or len(compatible) > 1:
            ambiguous.append({
                **issue,
                "candidate_target_ids": tuple(target["object_id"] for target in targets),
                "reason": "multiple_callable_definitions",
            })
        elif len(compatible) != 1:
            role_conflicts.append({
                **issue,
                "defined_kinds": tuple(sorted({target["kind"] for target in targets})),
                "reason": "callable_role_conflict",
            })
        else:
            target = compatible[0]
            edges.append({
                **issue,
                "target_id": target["object_id"],
                "source_name": source["name"],
                "resolved_target_name": target["name"],
            })

    for manager in parsed["calling_managers"]:
        for field_index, name in enumerate(manager["manager_calls"], start=3):
            add_call(manager, name, "manager_invokes_program", "program", field_index)
    for row in callables:
        for statement in row["statements"]:
            for name in statement["calls"]:
                add_call(
                    row, name, "run_invokes_subroutine", "subroutine",
                    statement["field_index"], statement["text"],
                )
    adjacency_lists: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency_lists[edge["source_id"]].append(edge["target_id"])
    adjacency = {key: tuple(values) for key, values in adjacency_lists.items()}
    entry_ids = {
        edge["target_id"] for edge in edges
        if edge["relation"] == "manager_invokes_program"
    }
    reachable = set(entry_ids)
    frontier = list(entry_ids)
    while frontier:
        source = frontier.pop()
        for target in adjacency.get(source, ()):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    return {
        "schema_version": "idfrepair.ems.calls.v1",
        "status": "OK" if not (unresolved or ambiguous or role_conflicts) else "CALL_GRAPH_ISSUES_FOUND",
        "nodes": nodes,
        "edges": tuple(edges),
        "unresolved_calls": tuple(unresolved),
        "ambiguous_calls": tuple(ambiguous),
        "call_role_conflicts": tuple(role_conflicts),
        "cycles": _cycles(tuple(row["object_id"] for row in callables), adjacency),
        "entry_program_ids": tuple(sorted(entry_ids)),
        "reachable_callable_ids": tuple(sorted(reachable)),
    }


__all__ = [
    "EMS_OBJECT_TYPES", "build_ems_calls", "build_ems_symbols",
    "normalize_ems_name", "parse_ems", "parse_ems_statement",
]
