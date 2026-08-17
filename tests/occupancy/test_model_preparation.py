"""验证 OpenStudio terminal model preparation 的源只读边界。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "occupancy" / "prepare_terminal_model.rb"
INVENTORY_SCRIPT = PROJECT_ROOT / "scripts" / "run_airport_occupancy.py"
COUPLING_REPORT = PROJECT_ROOT / "reports" / "occupancy" / "people_hvac_coupling_audit.md"
OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")


def _require_openstudio() -> Path:
    if not OPENSTUDIO.is_file():
        pytest.skip("OpenStudio CLI is not installed")
    return OPENSTUDIO


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_model(tmp_path: Path, *, include_orphan_zone: bool = False) -> Path:
    """用当前 OpenStudio runtime 生成一个无私有资产的最小 OSM。"""

    executable = _require_openstudio()
    model_path = tmp_path / "fixture.osm"
    generator = tmp_path / "generate_fixture.rb"
    program = """model = OpenStudio::Model::Model.new
zone = OpenStudio::Model::ThermalZone.new(model)
zone.setName('Fixture Zone')
space = OpenStudio::Model::Space.new(model)
space.setName('Fixture Space')
space.setThermalZone(zone)
definition = OpenStudio::Model::PeopleDefinition.new(model)
definition.setName('Fixture People Definition')
definition.setNumberofPeople(10.0)
people = OpenStudio::Model::People.new(definition)
people.setName('Fixture People')
people.setSpace(space)
"""
    if include_orphan_zone:
        program += """orphan = OpenStudio::Model::ThermalZone.new(model)
orphan.setName('Orphan Zone Without Spaces')
"""
    program += "raise 'save_failed' unless model.save(OpenStudio::Path.new(ARGV.fetch(0)), true)\n"
    generator.write_text(
        program,
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(executable), str(generator), str(model_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert model_path.is_file()
    return model_path


def _prepare(source: Path, output: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(_require_openstudio()),
            str(PREPARE_SCRIPT),
            "--input",
            str(source),
            "--output-dir",
            str(output),
            "--mode",
            mode,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_preparation_rejects_same_input_and_output_path(tmp_path: Path) -> None:
    """输出目录等于源 OSM path 时必须在读取/保存模型前失败。"""

    source = tmp_path / "model.osm"
    source.write_text("not loaded", encoding="utf-8")

    result = _prepare(source, source, "translate")

    assert result.returncode != 0
    assert "output_must_not_equal_source" in result.stdout + result.stderr
    assert source.read_text(encoding="utf-8") == "not loaded"


def test_translate_preserves_source_and_records_provenance(tmp_path: Path) -> None:
    """翻译只写派生 IDF，并记录 runtime、计数与前后 source hash。"""

    source = _make_model(tmp_path)
    before = _sha256(source)

    result = _prepare(source, tmp_path / "translated", "translate")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(source) == before
    provenance = json.loads((tmp_path / "translated" / "provenance.json").read_text())
    assert provenance["source_sha256_before"] == before
    assert provenance["source_sha256_after"] == before
    assert provenance["source_unchanged"] is True
    assert provenance["mode"] == "translate"
    assert provenance["openstudio_version"].startswith("3.6.1")
    assert provenance["before_counts"]["spaces"] == 1
    assert provenance["before_counts"]["thermal_zones"] == 1
    assert provenance["before_counts"]["people"] == 1
    assert provenance["synthetic_hvac_demo"] is False
    assert (tmp_path / "translated" / "derived.idf").is_file()
    assert not (tmp_path / "translated" / "derived.osm").exists()


def test_ideal_loads_exists_only_in_derived_copy(tmp_path: Path) -> None:
    """synthetic Ideal Loads 可补到派生 OSM，但源 OSM hash 与对象仍不变。"""

    source = _make_model(tmp_path)
    before = _sha256(source)

    result = _prepare(source, tmp_path / "ideal", "ideal-loads-demo")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(source) == before
    provenance = json.loads((tmp_path / "ideal" / "provenance.json").read_text())
    assert provenance["synthetic_hvac_demo"] is True
    assert provenance["synthetic_ideal_loads_added"] == 1
    assert provenance["after_counts"]["ideal_loads"] == 1
    assert provenance["after_counts"]["real_zone_equipment"] == 0
    assert (tmp_path / "ideal" / "derived.osm").is_file()
    assert (tmp_path / "ideal" / "derived.idf").is_file()


def test_ideal_loads_skips_orphan_zone_dropped_by_forward_translation(
    tmp_path: Path,
) -> None:
    """无 Space 的 Zone 会被 translator 丢弃，因此不得留下 orphan Ideal Loads。"""

    source = _make_model(tmp_path, include_orphan_zone=True)

    result = _prepare(source, tmp_path / "ideal", "ideal-loads-demo")

    assert result.returncode == 0, result.stdout + result.stderr
    provenance = json.loads((tmp_path / "ideal" / "provenance.json").read_text())
    assert provenance["before_counts"]["thermal_zones"] == 2
    assert provenance["synthetic_ideal_loads_added"] == 1
    assert provenance["synthetic_zones_skipped_no_spaces"] == 1
    assert provenance["after_counts"]["ideal_loads"] == 1


def test_inventory_cli_uses_public_aliases_and_qualifies_missing_hvac(
    tmp_path: Path,
) -> None:
    """公开 inventory/report 只用中性 alias，并把无 HVAC 基线限为 demo。"""

    source = _make_model(tmp_path)
    before = _sha256(source)
    report = tmp_path / "terminal_model_inventory.md"
    qualification = tmp_path / "baseline_qualification.md"
    result = subprocess.run(
        [
            "python",
            str(INVENTORY_SCRIPT),
            "inventory",
            "--model",
            str(source),
            "--workspace",
            str(tmp_path / "workspace"),
            "--report",
            str(report),
            "--qualification-report",
            str(qualification),
            "--openstudio",
            str(_require_openstudio()),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(source) == before
    inventory_text = report.read_text(encoding="utf-8")
    qualification_text = qualification.read_text(encoding="utf-8")
    assert "Terminal Model A" in inventory_text
    assert "OpenStudio 3.6.1" in inventory_text
    assert "OSM 3.6.1" in inventory_text
    assert "#<OpenStudio" not in inventory_text
    assert "People definitions" in inventory_text
    assert "Schedules" in inventory_text
    assert source.name not in inventory_text
    assert str(tmp_path) not in inventory_text
    assert "user-authored" in inventory_text
    assert "NO_REAL_HVAC" in qualification_text
    assert "DEMO_DERIVATIVE_ELIGIBLE" in qualification_text
    assert "OCCUPANCY_CASE_ADMIT" not in qualification_text


def test_baseline_cli_exposes_version_bound_inputs() -> None:
    """baseline 子命令必须显式接收 weather、EnergyPlus 与 IDD 身份。"""

    result = subprocess.run(
        ["python", str(INVENTORY_SCRIPT), "baseline", "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "--weather" in result.stdout
    assert "--energyplus" in result.stdout
    assert "--idd" in result.stdout
    assert "--source-model" in result.stdout


def test_coupling_report_has_no_unrendered_template_placeholders() -> None:
    """提交的真实审计报告必须渲染全部计数，不能泄露模板表达式。"""

    text = COUPLING_REPORT.read_text(encoding="utf-8")

    assert "{ideal_provenance" not in text
    assert "29 People instances and 28 People definitions" in text
