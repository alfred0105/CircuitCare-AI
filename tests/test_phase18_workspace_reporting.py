from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuitcare.reporting.exporters import export_bundle, export_html, export_json, export_markdown
from circuitcare.reporting.report_builder import classify_parameter_grid_coverage
from circuitcare.reporting.report_builder import build_diagnostic_snapshot
from circuitcare.models import Circuit
from circuitcare.reporting.report_validator import validate_report, verify_bundle
from circuitcare.workspace.context import build_workspace_context, store_uploaded_netlist
from circuitcare.workspace.provenance import artifact_record
from circuitcare.workspace.session import reconcile_session_workspace
from circuitcare.workspace.state_validator import stale_analysis_records
from circuitcare.workspace.workflow import workflow_steps


def _report(tmp_path: Path) -> dict:
    return {
        "schema_version": "circuitcare-diagnosis-report-v1",
        "generated_at": "2026-11-04T00:00:00Z",
        "workspace": {"workspace_id": "ws-1"},
        "circuit": {"hash": "a" * 64, "name": "demo"},
        "evidence": [{"evidence_id": "EV1", "evidence_type": "SPICE_SIMULATION"}],
        "findings": [{"finding_id": "F1", "source_evidence_ids": ["EV1"]}],
        "secondary_damage_risk": {"damage_confirmed": False},
        "limitations": ["Synthetic demo only."],
        "reproducibility": {"git_sha": "abc"},
    }


def test_workspace_hash_and_session_invalidation(tmp_path: Path) -> None:
    netlist = tmp_path / "board.xml"
    model = tmp_path / "model.cir"
    netlist.write_text("<netlist/>")
    model.write_text("R1 a b 1k")
    first = build_workspace_context(circuit_id="board", netlist_path=netlist,
                                    input_paths={"spice_model": model}, fault={"ref": "U1"})
    state = {}
    reconcile_session_workspace(state, {**first.to_dict(), "component_refs": ["U1", "R1"]})
    model.write_text("R1 a b 2k")
    changed = build_workspace_context(circuit_id="board", netlist_path=netlist,
                                      input_paths={"spice_model": model}, fault={"ref": "U1"})
    current = reconcile_session_workspace(state, {**changed.to_dict(), "component_refs": ["R1"]})
    assert first.workspace_id != changed.workspace_id
    assert "spice_fault_comparison" in current["invalidated_analyses"]
    assert "component_reference_context" in current["invalidated_analyses"]
    assert "graph_analysis" not in current["invalidated_analyses"]


def test_dependency_scoped_stale_checks() -> None:
    records = [
        {"analysis_type": "spice_fault_comparison", "status": "COMPLETE",
         "circuit_hash": "same", "input_hashes": {"mapping": "old", "ratings": "r1"}},
        {"analysis_type": "bayesian_diagnosis", "status": "COMPLETE",
         "circuit_hash": "same", "input_hashes": {"prior": "p1"}},
    ]
    result = stale_analysis_records(records, current_circuit_hash="same",
                                    current_input_hashes={"mapping": "new", "ratings": "r1", "prior": "p1"})
    assert result[0]["status"] == "STALE"
    assert result[1]["status"] == "COMPLETE"


def test_parameter_grid_report_distinguishes_in_grid_and_off_grid() -> None:
    candidates = [{"component_ref": "R1", "fault_type": "resistance_drift",
                   "parameters": {"fault_resistance": "2k"}},
                  {"component_ref": "R1", "fault_type": "resistance_drift",
                   "parameters": {"fault_resistance": "500"}}]
    assert classify_parameter_grid_coverage(component_ref="R1", fault_type="resistance_drift",
        fault_parameter="2k", rule_candidates=candidates)["status"] == "CATALOG_CONTAINS_EXACT_PARAMETER"
    off_grid = classify_parameter_grid_coverage(component_ref="R1", fault_type="resistance_drift",
        fault_parameter="1.37k", rule_candidates=candidates)
    assert off_grid["status"] == "EXACT_FAULT_PARAMETER_NOT_IDENTIFIED"
    assert classify_parameter_grid_coverage(component_ref="R2", fault_type="resistance_drift",
        fault_parameter="1.37k", rule_candidates=candidates)["status"] == "NOT_EVALUATED"


def test_report_exports_and_bundle_hash_verification(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert validate_report(report, expected_circuit_hash="a" * 64) == []
    assert "circuitcare-diagnosis-report-v1" in export_json(report)
    assert "손상 확정 여부: 아니요" in export_markdown(report)
    assert "<!doctype html>" in export_html(report)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"value": 1}))
    bundle = export_bundle(report, root=tmp_path, selected_artifacts={"measurements.json": evidence})
    manifest = verify_bundle(bundle)
    assert "evidence/measurements.json" in manifest["artifacts"]


def test_report_snapshot_portable_paths_and_simulated_observation_are_labelled(tmp_path: Path) -> None:
    circuit = Circuit(components={}, connections=[])
    workspace = {"workspace_id": "ws", "circuit_id": "demo", "circuit_hash": "a" * 64,
                 "netlist_path": "demo.xml", "input_hashes": {}, "validation_status": "READY"}
    report = build_diagnostic_snapshot(root=tmp_path, workspace=workspace, circuit=circuit,
        fault={"component_ref": "U1", "fault_type": "regulator_output_rise", "parameter": "8"},
        simulation_status="SUCCESS", comparison={"scenario_id": "S1", "baseline": {"circuit": "/private/tmp/base.cir"}},
        risk_assessment={"risk_assessment_json": "/private/tmp/risk_assessment.json"},
        observations=[{"node": "VOUT", "value": 7.9, "source": "simulated_demo"}])
    assert report["spice_verification"]["comparison"]["baseline"]["circuit"] == "base.cir"
    assert report["secondary_damage_risk"]["risk_assessment_json"] == "risk_assessment.json"
    assert report["fault_or_symptom"]["observation_classification"] == "SYNTHETIC_DEMO"
    assert report["evidence"][1]["evidence_type"] == "HEURISTIC_ESTIMATE"


def test_export_security_rejects_paths_outside_root_and_unknown_names(tmp_path: Path) -> None:
    report = _report(tmp_path)
    other = tmp_path.parent / "private.txt"
    other.write_text("private")
    with pytest.raises(ValueError, match="inside"):
        export_bundle(report, root=tmp_path, selected_artifacts={"measurements.json": other})
    local = tmp_path / "allowed.json"
    local.write_text("{}")
    with pytest.raises(ValueError, match="approved"):
        export_bundle(report, root=tmp_path, selected_artifacts={"../private.txt": local})


def test_provenance_and_report_validator_fail_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "spice.json"
    artifact.write_text("{}")
    record = artifact_record(artifact, workspace_root=tmp_path,
                             evidence_type="SPICE_SIMULATION", verification_status="RECORDED")
    assert record["path"] == "spice.json"
    with pytest.raises(ValueError, match="inside"):
        artifact_record(tmp_path.parent / "private.txt", workspace_root=tmp_path,
                        evidence_type="USER_REPORTED_OBSERVATION", verification_status="RECORDED")
    report = _report(tmp_path)
    report["findings"][0]["source_evidence_ids"] = ["MISSING"]
    assert "MISSING_FINDING_EVIDENCE:F1" in validate_report(report)
    report["evidence"][0]["circuit_hash"] = "b" * 64
    assert "CROSS_CIRCUIT_EVIDENCE:EV1" in validate_report(report)


def test_uploaded_netlist_is_content_addressed_private_and_rejects_dtd(tmp_path: Path) -> None:
    stored = store_uploaded_netlist(b"<export><components/></export>", workspace_root=tmp_path)
    assert stored.parent.parts[-3:] == ("private", "workspaces", "netlists")
    assert stored.name.endswith(".xml")
    assert store_uploaded_netlist(b"<export><components/></export>", workspace_root=tmp_path) == stored
    with pytest.raises(ValueError, match="DTD or entity"):
        store_uploaded_netlist(b"<!DOCTYPE export><export/>", workspace_root=tmp_path)
    with pytest.raises(ValueError, match="25 MiB"):
        store_uploaded_netlist(b"", workspace_root=tmp_path)


def test_workflow_shows_spice_failure_without_blocking_report() -> None:
    steps = workflow_steps(circuit_status="READY", graph_ready=True,
                           fault_status="COMPLETE", spice_status="FAILED", report_ready=True)
    assert steps[3]["status"] == "FAILED"
    assert steps[4]["status"] == "READY"


def test_streamlit_app_keeps_original_tabs_and_displays_workspace_reports() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[1] / "src/circuitcare/ui.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    labels = [tab.label for tab in app.tabs]
    assert "분석 개요" in labels and "AI 성능 평가" in labels
    assert any(button.label == "Evidence Bundle ZIP" for button in app.download_button)
    selector = next(item for item in app.selectbox if item.key == "case_name")
    selector.select("KiCad XML 업로드 (연결 그래프 전용)").run()
    assert not app.exception
    assert any("KiCad XML을 올리면" in item.value for item in app.info)
