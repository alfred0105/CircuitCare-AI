from pathlib import Path

import pytest

from circuitcare.schematic.identity import map_component_refs, read_symbol_identities

ROOT = Path(__file__).resolve().parents[1]


def test_reads_symbol_identity_and_marks_reference_mapping():
    identities, missing = read_symbol_identities(
        ROOT / "tests/fixtures/identity_minimal.kicad_sch", project_root=ROOT)
    assert not missing
    mapped = map_component_refs(["R1", "R2"], identities)
    assert mapped["R1"]["status"] == "VERIFIED_REFERENCE"
    assert mapped["R1"]["symbol_instances"][0]["symbol_uuid"] == "ed693198-4ec1-4cbe-a345-ec57389d31e4"
    assert mapped["R1"]["symbol_instances"][0]["unit"] == 1
    assert mapped["R2"]["match_count"] == 0


def test_rejects_schematic_outside_project(tmp_path):
    outside = tmp_path / "outside.kicad_sch"
    outside.write_text("(kicad_sch)", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the project root"):
        read_symbol_identities(outside, project_root=ROOT)
