"""Public command line interface for the IDFRepair Unified Engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from idfrepair.capabilities.reporting import capabilities_payload, capabilities_text
from idfrepair.config import EngineConfig
from idfrepair.domain.enums import RepairMode, RepairStatus
from idfrepair.domain.errors import IDFRepairError, RuntimeDiscoveryError
from idfrepair.domain.models import RepairOutcome
from idfrepair.engine.orchestrator import UnifiedEngine
from idfrepair.io.idf import parse_idf
from idfrepair.io.workspace import SessionWorkspace
from idfrepair.memory.database import MemoryDatabase
from idfrepair.memory.import_export import export_rules, import_rules
from idfrepair.memory.learning import template_fingerprint
from idfrepair.memory.models import RepairRule
from idfrepair.memory.repository import RuleRepository
from idfrepair.batch.runner import BatchInput, BatchResult, discover_inputs, run_batch
from idfrepair.reporting.session_report import build_session_report, write_session_report
from idfrepair.runtime.cache import EnergyPlusCache
from idfrepair.runtime.discovery import RuntimeSpec, discover_runtimes, normalize_version, select_runtime
from idfrepair.runtime.energyplus import EnergyPlusRunner
from idfrepair.validation.terminal_safety import repaired_artifact_allowed


SUCCESS = frozenset({RepairStatus.VALID, RepairStatus.REPAIRED})


def _existing_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file_not_found:{value}")
    return path.resolve()


def _weather_path(value: str) -> Path:
    """Defer weather asset validation to the shared runtime readiness gate."""

    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="idfrepair",
        description="Bounded transactional repair for EnergyPlus IDF files.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0a1")
    commands = parser.add_subparsers(dest="command", required=True)

    diagnose = commands.add_parser("diagnose", help="Run EnergyPlus and report structured error roots.")
    _add_runtime_arguments(diagnose)
    diagnose.add_argument("input", type=_existing_file)
    diagnose.add_argument("--report", type=Path, required=True)

    repair = commands.add_parser("repair", help="Search for a bounded, validated repair.")
    _add_runtime_arguments(repair)
    repair.add_argument("input", type=_existing_file)
    repair.add_argument("--mode", choices=[mode.value for mode in RepairMode], default=RepairMode.SAFE_AUTO.value)
    repair.add_argument("--max-rounds", type=int, default=6)
    repair.add_argument("--max-candidates-per-root", type=int, default=3)
    repair.add_argument("--max-energyplus-runs", type=int, default=20)
    repair.add_argument("--max-backtracks", type=int, default=1)
    repair.add_argument("--max-wall-time", type=float, default=600.0)
    repair.add_argument("--model", default="none", help=argparse.SUPPRESS)
    repair.add_argument("--model-base", type=Path, help=argparse.SUPPRESS)
    repair.add_argument("--model-adapter", type=Path, help=argparse.SUPPRESS)
    repair.add_argument("--model-runtime-python", type=Path, help=argparse.SUPPRESS)
    repair.add_argument("--approve-candidate", action="append", default=[])
    repair.add_argument("--output", type=Path, required=True)
    repair.add_argument("--report", type=Path, required=True)

    serve = commands.add_parser("serve", help="Start the local FastAPI and browser interface.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--session-root", type=Path)

    capabilities = commands.add_parser(
        "capabilities", help="Inspect the frozen Support Registry and Release Profile.",
    )
    capabilities.add_argument("--format", choices=("json", "text"), default="text")
    capabilities.add_argument("--locale", choices=("zh-CN", "en"), default="zh-CN")
    capabilities.add_argument("--family")

    rules = commands.add_parser("rules", help="Manage local Repair Memory rules.")
    rules.add_argument("--database", type=Path, default=Path("idfrepair-memory.sqlite3"))
    rule_commands = rules.add_subparsers(dest="rules_command", required=True)
    list_rules = rule_commands.add_parser("list", help="List or search rules.")
    list_rules.add_argument("--search")
    list_rules.add_argument("--rule-set")
    show_rule = rule_commands.add_parser("show", help="Show one rule.")
    show_rule.add_argument("rule_id")
    create_rule = rule_commands.add_parser("create", help="Create a rule from JSON or YAML.")
    create_rule.add_argument("file", type=_existing_file)
    for command in ("enable", "disable", "delete", "clone"):
        item = rule_commands.add_parser(command, help=f"{command.title()} one rule.")
        item.add_argument("rule_id")
    export_command = rule_commands.add_parser("export", help="Export rules as JSON/YAML 1.2.")
    export_command.add_argument("path", type=Path)
    export_command.add_argument("--rule-set")
    import_command = rule_commands.add_parser("import", help="Import a validated rule document.")
    import_command.add_argument("path", type=_existing_file)
    import_command.add_argument("--rule-set")

    batch = commands.add_parser("batch", help="Repair directories, ZIP archives, or multiple IDF files.")
    _add_runtime_arguments(batch)
    batch.add_argument("inputs", nargs="+", type=Path)
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--mode", choices=[mode.value for mode in RepairMode], default=RepairMode.SAFE_AUTO.value)
    batch.add_argument("--max-rounds", type=int, default=6)
    batch.add_argument("--max-candidates-per-root", type=int, default=3)
    batch.add_argument("--max-energyplus-runs", type=int, default=20)
    batch.add_argument("--max-backtracks", type=int, default=1)
    batch.add_argument("--max-wall-time", type=float, default=600.0)
    batch.add_argument("--model", default="none", help=argparse.SUPPRESS)
    batch.add_argument("--model-base", type=Path, help=argparse.SUPPRESS)
    batch.add_argument("--model-adapter", type=Path, help=argparse.SUPPRESS)
    batch.add_argument("--model-runtime-python", type=Path, help=argparse.SUPPRESS)
    batch.add_argument("--memory-database", type=Path)
    batch.add_argument("--rule-set", default="default")
    batch.add_argument("--project-id")
    return parser


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--epw", type=_weather_path)
    parser.add_argument("--dependency", action="append", type=_existing_file, default=[])
    parser.add_argument("--energyplus", type=Path, help="EnergyPlus home or executable path.")
    parser.add_argument("--energyplus-version", help="Explicit target version when the IDF has no Version object.")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--timeout", type=int, default=120)


def select_input_runtime(
    text: str,
    *,
    explicit: Path | None,
    requested_version: str | None,
) -> RuntimeSpec:
    document = parse_idf(text)
    version = requested_version or document.version
    runtimes = discover_runtimes(explicit, include_defaults=explicit is None)
    if not runtimes:
        raise RuntimeDiscoveryError("runtime_not_found")
    if version:
        return select_runtime(version, runtimes)
    if len(runtimes) != 1:
        raise RuntimeDiscoveryError("input_version_missing_and_runtime_not_unique")
    return runtimes[0]


def _read_input(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom


def _write_output(path: Path, text: str, *, bom: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def _admitted_output_path(path: Path, outcome: RepairOutcome) -> Path:
    '''Prevent non-admitted bytes from occupying an explicit repaired name.'''
    if repaired_artifact_allowed(outcome):
        return path
    lowered = path.stem.casefold()
    for suffix in ("-repaired", "_repaired"):
        if lowered.endswith(suffix):
            return path.with_name(
                path.stem[:-len(suffix)] + "-unchanged" + path.suffix
            )
    return path


def _configuration(args: argparse.Namespace, *, diagnose: bool) -> EngineConfig:
    if not diagnose and (
        getattr(args, "model", "none") != "none"
        or getattr(args, "model_base", None) is not None
        or getattr(args, "model_adapter", None) is not None
        or getattr(args, "model_runtime_python", None) is not None
    ):
        raise ValueError("model_component_not_release_authorized")
    return EngineConfig(
        mode=RepairMode.ANALYZE_ONLY if diagnose else RepairMode(args.mode),
        max_rounds=1 if diagnose else args.max_rounds,
        max_candidates_per_root=1 if diagnose else args.max_candidates_per_root,
        max_total_energyplus_runs=2 if diagnose else args.max_energyplus_runs,
        max_backtracks=0 if diagnose else args.max_backtracks,
        max_wall_time=60.0 if diagnose else args.max_wall_time,
        model="none" if diagnose else args.model,
        model_base_path=(
            None if diagnose or getattr(args, "model_base", None) is None
            else str(args.model_base.expanduser().resolve())
        ),
        model_adapter_path=(
            None if diagnose or getattr(args, "model_adapter", None) is None
            else str(args.model_adapter.expanduser().resolve())
        ),
        model_runtime_python=(
            None if diagnose or getattr(args, "model_runtime_python", None) is None
            else str(args.model_runtime_python.expanduser().absolute())
        ),
        timeout_seconds=args.timeout,
    )


def _execute(args: argparse.Namespace, *, diagnose: bool) -> int:
    text, bom = _read_input(args.input)
    runtime = select_input_runtime(
        text,
        explicit=args.energyplus,
        requested_version=args.energyplus_version,
    )
    config = _configuration(args, diagnose=diagnose)
    workspace = SessionWorkspace.create(args.workspace)
    runner = EnergyPlusRunner(
        runtime,
        workspace=workspace,
        weather=args.epw,
        dependencies=args.dependency,
        timeout_seconds=config.timeout_seconds,
        cache=EnergyPlusCache(args.cache),
    )
    engine = UnifiedEngine(
        runner,
        runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
        config=config,
        context_metadata={
            "target_version": normalize_version(runtime.version),
            "model_energyplus_feedback": config.model != "none",
        },
    )
    approved = () if diagnose else tuple(args.approve_candidate)
    outcome = engine.repair_text(text, approved_candidate_ids=approved)
    report = build_session_report(
        session_id=workspace.root.name.removeprefix("idfrepair-"),
        input_name=args.input.name,
        input_text=text,
        outcome=outcome,
        configuration=config,
        runtime_identity=runtime.identity,
        support_registry_audit=engine.support_registry_audit(),
        input_had_utf8_bom=bom,
        output_has_utf8_bom=bom,
    )
    write_session_report(args.report.resolve(), report)
    output_path = None
    if not diagnose:
        output_path = _admitted_output_path(args.output.resolve(), outcome)
        _write_output(output_path, outcome.output_text, bom=bom)
    print(json.dumps({
        "energyplus_runs": outcome.energyplus_runs,
        "final_status": outcome.status.value,
        "output": None if output_path is None else str(output_path),
        "production_enabled": False,
        "report": str(args.report.resolve()),
        "session_id": report["session_id"],
    }, ensure_ascii=False, sort_keys=True))
    if diagnose:
        return 4 if outcome.status is RepairStatus.PROCESS_FAILED else 0
    if outcome.status in SUCCESS:
        return 0
    if outcome.status is RepairStatus.NEEDS_INPUT:
        return 2
    if outcome.status is RepairStatus.PROCESS_FAILED:
        return 4
    return 3


def _rule_payload(path: Path) -> dict[str, object]:
    '''读取单条 JSON 或 YAML 规则文件，YAML 运行时缺失时明确拒绝。'''
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("yaml_runtime_not_installed; use JSON") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("rule_file_must_contain_object")
    return payload


def _rules(args: argparse.Namespace) -> int:
    '''执行规则 CRUD、复制、搜索及导入导出命令。'''
    repository = RuleRepository(MemoryDatabase(args.database))
    command = args.rules_command
    if command == "list":
        result: object = [
            rule.to_dict() for rule in repository.list_rules(
                search=args.search, rule_set_id=args.rule_set,
            )
        ]
    elif command == "show":
        result = repository.get_rule(args.rule_id).to_dict()
    elif command == "create":
        result = repository.create_rule(RepairRule.from_mapping(_rule_payload(args.file))).to_dict()
    elif command == "enable":
        result = repository.set_enabled(args.rule_id, True).to_dict()
    elif command == "disable":
        result = repository.set_enabled(args.rule_id, False).to_dict()
    elif command == "delete":
        repository.delete_rule(args.rule_id)
        result = {"deleted": args.rule_id}
    elif command == "clone":
        result = repository.clone_rule(args.rule_id).to_dict()
    elif command == "export":
        result = {"path": str(export_rules(repository, args.path.resolve(), rule_set_id=args.rule_set))}
    elif command == "import":
        result = {"created_rule_ids": import_rules(repository, args.path, rule_set_id=args.rule_set)}
    else:
        raise ValueError("unknown_rules_command")
    print(json.dumps({"result": result, "production_enabled": False}, ensure_ascii=False, sort_keys=True))
    return 0


def _execute_batch(args: argparse.Namespace) -> int:
    '''发现并执行批量 IDF，单文件异常不会污染其他 workspace。'''
    inputs = discover_inputs(tuple(args.inputs))
    config = _configuration(args, diagnose=False)
    repository = (
        RuleRepository(MemoryDatabase(args.memory_database))
        if args.memory_database is not None else None
    )

    def callback(record: BatchInput, workspace_path: Path) -> BatchResult:
        runtime = select_input_runtime(
            record.text,
            explicit=args.energyplus,
            requested_version=args.energyplus_version,
        )
        workspace = SessionWorkspace(workspace_path)
        runner = EnergyPlusRunner(
            runtime,
            workspace=workspace,
            weather=args.epw,
            dependencies=args.dependency,
            timeout_seconds=config.timeout_seconds,
            cache=EnergyPlusCache(workspace.safe_path("cache")),
        )
        metadata: dict[str, object] = {
            "target_version": normalize_version(runtime.version),
            "batch_id": args.output_dir.name,
            "project_id": args.project_id or record.source_identity,
            "template_fingerprint": template_fingerprint(record.text),
            "selected_rule_set_id": args.rule_set,
            "model_energyplus_feedback": config.model != "none",
        }
        if repository is not None:
            metadata["rule_repository"] = repository
        engine = UnifiedEngine(
            runner,
            runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
            config=config,
            context_metadata=metadata,
        )
        outcome = engine.repair_text(record.text)
        report = build_session_report(
            session_id=record.record_id,
            input_name=record.logical_name,
            input_text=record.text,
            outcome=outcome,
            configuration=config,
            runtime_identity=runtime.identity,
            support_registry_audit=engine.support_registry_audit(),
        )
        return BatchResult(outcome, report)

    summary = run_batch(
        inputs,
        args.output_dir,
        callback,
        configuration=config.to_dict(),
        rule_set_id=args.rule_set,
    )
    print(json.dumps({
        "batch_summary": str(args.output_dir.resolve() / "batch_summary.json"),
        "counts": summary["counts"],
        "production_enabled": False,
    }, ensure_ascii=False, sort_keys=True))
    if summary["counts"]["failed"]:
        return 3
    if summary["counts"]["needs_input"]:
        return 2
    return 0


def _capabilities(args: argparse.Namespace) -> int:
    '''输出唯一 Release Profile 的机器可读或本地化只读视图。'''
    payload = capabilities_payload(family=args.family)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(capabilities_text(payload, args.locale))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        capabilities_payload()
        if args.command == "diagnose":
            return _execute(args, diagnose=True)
        if args.command == "repair":
            return _execute(args, diagnose=False)
        if args.command == "serve":
            try:
                import uvicorn
            except ImportError as exc:
                raise RuntimeError("web_dependencies_not_installed") from exc
            from idfrepair.api.app import create_app

            uvicorn.run(create_app(session_root=args.session_root), host=args.host, port=args.port)
            return 0
        if args.command == "capabilities":
            return _capabilities(args)
        if args.command == "rules":
            return _rules(args)
        if args.command == "batch":
            return _execute_batch(args)
    except (IDFRepairError, OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(json.dumps({
            "error": str(exc),
            "error_type": type(exc).__name__,
            "production_enabled": False,
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 4
    parser.error("unknown_command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
