"""用真实 OpenStudio runtime 验证源模型审计的只读与 provenance 边界。"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from idfrepair.analysis.occupancy_room_aware.source_audit import (
    render_source_audit,
    validate_source_audit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = (
    PROJECT_ROOT / "scripts" / "occupancy_room_aware" / "audit_terminal_model.rb"
)
OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")
REAL_AUDIT_CSV = (
    PROJECT_ROOT / "reports" / "occupancy_v2" / "source_room_function_audit.csv"
)
REAL_AUDIT_MD = PROJECT_ROOT / "reports" / "occupancy_v2" / "source_room_function_audit.md"


def _require_openstudio() -> Path:
    if not OPENSTUDIO.is_file():
        pytest.skip("OpenStudio CLI is not installed")
    return OPENSTUDIO


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_fixture(tmp_path: Path) -> Path:
    """生成同时覆盖 defaulted、explicit、conflict 与 orphan 的最小 OSM。"""

    source = tmp_path / "fixture.osm"
    generator = tmp_path / "generate_audit_fixture.rb"
    generator.write_text(
        """model = OpenStudio::Model::Model.new
building = model.getBuilding

always_on = OpenStudio::Model::ScheduleConstant.new(model)
always_on.setName('Fixture People Fraction')
always_on.setValue(1.0)
activity = OpenStudio::Model::ScheduleConstant.new(model)
activity.setName('Fixture Activity')
activity.setValue(120.0)

default_type = OpenStudio::Model::SpaceType.new(model)
default_type.setName('Fixture Large Office Default')
building.setSpaceType(default_type)
default_definition = OpenStudio::Model::PeopleDefinition.new(model)
default_definition.setName('Fixture Default People Definition')
default_definition.setPeopleperSpaceFloorArea(0.05)
default_definition.setFractionRadiant(0.31)
default_definition.setSensibleHeatFraction(0.55)
default_definition.setCarbonDioxideGenerationRate(3.9e-8)
default_people = OpenStudio::Model::People.new(default_definition)
default_people.setName('Fixture Default People')
default_people.setNumberofPeopleSchedule(always_on)
default_people.setActivityLevelSchedule(activity)
default_people.setSpaceType(default_type)
default_oa = OpenStudio::Model::DesignSpecificationOutdoorAir.new(model)
default_oa.setName('Fixture Default OA')
default_oa.setOutdoorAirMethod('Sum')
default_oa.setOutdoorAirFlowperPerson(0.003)
default_oa.setOutdoorAirFlowperFloorArea(0.0004)
default_type.setDesignSpecificationOutdoorAir(default_oa)

it_type = OpenStudio::Model::SpaceType.new(model)
it_type.setName('189.1-2009 - Office - IT_Room - CZ1-3')
it_definition = OpenStudio::Model::PeopleDefinition.new(model)
it_definition.setName('Fixture IT People Definition')
it_definition.setNumberofPeople(2.0)
it_people = OpenStudio::Model::People.new(it_definition)
it_people.setName('Fixture IT People')
it_people.setNumberofPeopleSchedule(always_on)
it_people.setActivityLevelSchedule(activity)
it_people.setSpaceType(it_type)

zone_a = OpenStudio::Model::ThermalZone.new(model)
zone_a.setName('Fixture Hall Zone')
hall = OpenStudio::Model::Space.new(model)
hall.setName('P1-hall-1')
hall.setThermalZone(zone_a)

zone_b = OpenStudio::Model::ThermalZone.new(model)
zone_b.setName('Fixture Office Zone')
office = OpenStudio::Model::Space.new(model)
office.setName('z-u-office-11')
office.setThermalZone(zone_b)
office.setSpaceType(it_type)

orphan = OpenStudio::Model::ThermalZone.new(model)
orphan.setName('xbrestroom2')

raise 'save_failed' unless model.save(OpenStudio::Path.new(ARGV.fetch(0)), true)
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_require_openstudio()), str(generator), str(source)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return source


def _audit(source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(_require_openstudio()),
            str(AUDIT_SCRIPT),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_auditor_preserves_source_and_captures_exact_provenance(tmp_path: Path) -> None:
    source = _make_fixture(tmp_path)
    before = _sha256(source)
    output = tmp_path / "audit.json"

    result = _audit(source, output)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(source) == before
    audit = json.loads(output.read_text(encoding="utf-8"))
    assert audit["schema_version"] == "idfrepair.room-aware-source-audit.v1"
    assert audit["source_alias"] == "Terminal Model A"
    assert "source_path" not in audit
    assert audit["source_sha256_before"] == before
    assert audit["source_sha256_after"] == before
    assert audit["source_unchanged"] is True
    assert audit["openstudio_version"].startswith("3.6.1")
    assert len(audit["non_people_snapshot_sha256"]) == 64


def test_auditor_distinguishes_defaulted_metadata_orphans_and_conflicts(
    tmp_path: Path,
) -> None:
    source = _make_fixture(tmp_path)
    output = tmp_path / "audit.json"

    result = _audit(source, output)

    assert result.returncode == 0, result.stdout + result.stderr
    audit = json.loads(output.read_text(encoding="utf-8"))
    rows = {row["source_space_name"]: row for row in audit["spaces"]}
    hall = rows["P1-hall-1"]
    office = rows["z-u-office-11"]
    assert audit["space_count"] == 2
    assert audit["thermal_zone_count"] == 3
    assert audit["orphan_zones"] == ["xbrestroom2"]
    assert audit["category_counts"] == {"office": 1, "terminal_hall": 1}
    assert hall["room_category"] == "terminal_hall"
    assert hall["space_type_defaulted"] is True
    assert hall["explicit_space_type"] is None
    assert hall["effective_space_type"] == "Fixture Large Office Default"
    assert hall["people_sources"][0]["source_kind"] == "building_default_space_type"
    assert hall["people_sources"][0]["definition"]["method"] == "People/Area"
    assert hall["people_sources"][0]["count_schedule"] == "Fixture People Fraction"
    assert hall["people_sources"][0]["activity_schedule"] == "Fixture Activity"
    assert hall["oa_defaulted"] is True
    assert hall["oa"]["flow_per_person_m3_s_person"] == pytest.approx(0.003)
    assert hall["oa"]["flow_per_area_m3_s_m2"] == pytest.approx(0.0004)
    assert office["space_type_defaulted"] is False
    assert office["explicit_space_type"].endswith("IT_Room - CZ1-3")
    assert office["metadata_status"] == "SOURCE_METADATA_CONFLICT"
    assert office["room_category"] == "office"
    assert "office_name_vs_it_room_space_type" in office["metadata_conflicts"]


def test_auditor_fails_closed_on_unknown_or_multi_token_space(tmp_path: Path) -> None:
    source = _make_fixture(tmp_path)
    text = source.read_text(encoding="utf-8")
    text = text.replace("P1-hall-1", "P1-hall-office-1", 1)
    source.write_text(text, encoding="utf-8")
    output = tmp_path / "audit.json"

    result = _audit(source, output)

    assert result.returncode != 0
    assert "space_classification_rejected" in result.stdout + result.stderr
    assert not output.exists()


def test_source_audit_renderer_emits_compact_csv_and_explanatory_markdown(
    tmp_path: Path,
) -> None:
    source = _make_fixture(tmp_path)
    audit_json = tmp_path / "audit.json"
    result = _audit(source, audit_json)
    assert result.returncode == 0, result.stdout + result.stderr
    audit = json.loads(audit_json.read_text(encoding="utf-8"))
    csv_path = tmp_path / "source_room_function_audit.csv"
    markdown_path = tmp_path / "source_room_function_audit.md"

    summary = render_source_audit(
        audit,
        csv_path=csv_path,
        markdown_path=markdown_path,
    )

    assert summary["space_count"] == 2
    assert summary["default_archetype_mixed_space_count"] == 1
    csv_text = csv_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "source_space_name,room_category" in csv_text
    assert "P1-hall-1,terminal_hall" in csv_text
    assert "SOURCE_METADATA_CONFLICT" in csv_text
    assert "People → Zone → HVAC" in markdown
    assert "Source-preserving audit" in markdown
    assert "Fixture Large Office Default" in markdown
    assert str(tmp_path) not in markdown
    assert str(tmp_path) not in csv_text


def test_source_audit_validator_rejects_inconsistent_totals(tmp_path: Path) -> None:
    source = _make_fixture(tmp_path)
    audit_json = tmp_path / "audit.json"
    result = _audit(source, audit_json)
    assert result.returncode == 0, result.stdout + result.stderr
    audit = json.loads(audit_json.read_text(encoding="utf-8"))
    audit["category_counts"]["terminal_hall"] = 2

    with pytest.raises(ValueError, match="category_count_mismatch"):
        validate_source_audit(audit)


def test_committed_real_source_audit_has_exact_304_space_contract() -> None:
    with REAL_AUDIT_CSV.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 304
    assert len({row["source_space_name"] for row in rows}) == 304
    assert Counter(row["room_category"] for row in rows) == {
        "terminal_hall": 126,
        "office": 69,
        "commerce_retail": 51,
        "dining": 22,
        "restroom": 27,
        "breakroom": 9,
    }
    conflicts = [
        row
        for row in rows
        if row["metadata_status"] == "SOURCE_METADATA_CONFLICT"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["source_space_name"] == "z-u-office-11"
    markdown = REAL_AUDIT_MD.read_text(encoding="utf-8")
    assert "inherited by **141** Spaces" in markdown
    assert "6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb" in markdown
    assert "/" + "Users/" not in markdown
