import subprocess
from pathlib import Path

from circuitcare.dashboard.analysis_loader import load_analysis_snapshot
from circuitcare.dashboard.session_state import (
    analysis_context_keys_to_clear,
    reconcile_analysis_context,
    simulation_context_keys_to_clear,
)
from circuitcare.dashboard.simulation_controller import (
    SimulationRequest,
    build_simulation_command,
    execute_simulation_request,
)
from circuitcare.dashboard.workspace_adapter import build_analysis_records
from circuitcare.vision.ui_context import VisionViewContext


def test_analysis_context_invalidation_keeps_unrelated_state() -> None:
    state = {
        "analysis_context_key": "circuit-a",
        "live_result_dir": "/tmp/a",
        "what_if_voltage_VOUT": 7.9,
        "vision_active_image": "image-a",
        "unrelated_setting": True,
    }
    assert analysis_context_keys_to_clear(list(state)) == {
        "live_result_dir", "what_if_voltage_VOUT",
    }
    assert reconcile_analysis_context(state, "circuit-b") is True
    assert "live_result_dir" not in state
    assert "what_if_voltage_VOUT" not in state
    assert state["vision_active_image"] == "image-a"
    assert state["unrelated_setting"] is True
    assert state["measurements"] == []
    assert reconcile_analysis_context(state, "circuit-b") is False


def test_simulation_start_clears_only_live_and_preview_state() -> None:
    existing = ["live_result_dir", "live_context_key", "last_advisor",
                "what_if_result", "what_if_voltage_VOUT", "vision_active_image"]
    assert simulation_context_keys_to_clear(existing) == set(existing) - {"vision_active_image"}


def test_analysis_loader_accepts_verified_cache_and_blocks_unverified_cache(tmp_path: Path) -> None:
    current = {"fingerprint_sha256": "a" * 64}
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "comparison.json").write_text('{"scenario_id":"S1"}', encoding="utf-8")
    (result_dir / "risk_assessment.json").write_text('{"scenario_id":"S1"}', encoding="utf-8")
    (result_dir / "component_stress.json").write_text('{"simulation_success":true}', encoding="utf-8")
    # Missing a manifest is fail-closed even when result JSON is readable.
    blocked = load_analysis_snapshot(result_dir=result_dir, current_fingerprint=current,
                                     live_used=False, live_error=None, cached_selection=True)
    assert blocked.status == "PROVENANCE_UNVERIFIED"
    assert blocked.comparison == blocked.risk == blocked.stress == {}

    for filename in ("comparison.json", "risk_assessment.json", "component_stress.json"):
        import hashlib
        digest = hashlib.sha256((result_dir / filename).read_bytes()).hexdigest()
        if filename == "comparison.json":
            digests = {filename: digest}
        else:
            digests[filename] = digest
    import json
    manifest = {"fingerprint": current, "result_sha256": digests}
    (result_dir / "simulation_context.json").write_text(json.dumps(manifest), encoding="utf-8")
    verified = load_analysis_snapshot(result_dir=result_dir, current_fingerprint=current,
                                      live_used=False, live_error=None, cached_selection=True)
    assert verified.status == "CACHED_SIMULATION"
    assert verified.integrity == "VERIFIED"
    assert verified.comparison["scenario_id"] == "S1"


def test_analysis_loader_blocks_stale_and_damaged_results(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "comparison.json").write_text('{"scenario_id":"S1"}', encoding="utf-8")
    snapshot = load_analysis_snapshot(result_dir=result_dir,
        current_fingerprint={"fingerprint_sha256": "b" * 64}, live_used=False,
        live_error=None, cached_selection=True)
    assert snapshot.status == "PROVENANCE_UNVERIFIED"
    assert snapshot.comparison == {}
    (result_dir / "risk_assessment.json").write_text("not-json", encoding="utf-8")
    damaged = load_analysis_snapshot(result_dir=result_dir,
        current_fingerprint={"fingerprint_sha256": "b" * 64}, live_used=False,
        live_error="ngspice failed", cached_selection=True)
    assert damaged.status == "FAILED"
    assert damaged.risk == {}


def test_analysis_loader_rejects_valid_manifest_for_different_context(tmp_path: Path) -> None:
    import hashlib
    import json

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    contents = {name: '{"scenario_id":"S1"}' for name in
                ("comparison.json", "risk_assessment.json", "component_stress.json")}
    digests = {}
    for name, content in contents.items():
        (result_dir / name).write_text(content, encoding="utf-8")
        digests[name] = hashlib.sha256(content.encode()).hexdigest()
    (result_dir / "simulation_context.json").write_text(json.dumps({
        "fingerprint": {"fingerprint_sha256": "a" * 64}, "result_sha256": digests,
    }), encoding="utf-8")
    stale = load_analysis_snapshot(result_dir=result_dir,
        current_fingerprint={"fingerprint_sha256": "b" * 64}, live_used=False,
        live_error=None, cached_selection=True)
    assert stale.status == "STALE"
    assert stale.integrity == "STALE"
    assert stale.comparison == stale.risk == stale.stress == {}


def test_simulation_controller_builds_absolute_command_and_optional_fault_value(tmp_path: Path) -> None:
    command = build_simulation_command(
        python_executable="python", project_root=tmp_path,
        netlist=tmp_path / "input.xml", case={"base": "base.cir", "mapping": "map.json",
            "probes": "probes.json", "ratings": "ratings.json"},
        component_ref="R1", fault_type="resistance_drift", output_dir=tmp_path / "out",
        fault_value="13k",
    )
    assert command[command.index("--netlist") + 1] == str((tmp_path / "input.xml").resolve())
    assert command[command.index("--fault-value") + 1] == "13k"
    no_value = build_simulation_command(
        python_executable="python", project_root=tmp_path, netlist=tmp_path / "input.xml",
        case={"base": "base.cir", "mapping": "map.json", "probes": "probes.json", "ratings": "ratings.json"},
        component_ref="U1", fault_type="open", output_dir=tmp_path / "out", fault_value=None,
    )
    assert "--fault-value" not in no_value


def test_simulation_controller_normalizes_success_failure_and_timeout(monkeypatch, tmp_path: Path) -> None:
    import circuitcare.dashboard.simulation_controller as controller

    request = SimulationRequest(command=("python",), output_dir=tmp_path / "out",
        component_ref="R1", fault_type="open", fault_value=None, case={})
    monkeypatch.setattr(controller, "execute_simulation", lambda *args, **kwargs: tmp_path / "result")
    success = execute_simulation_request(request)
    assert success.status == "SUCCESS" and success.result_dir == tmp_path / "result"

    for error in (RuntimeError("failed"), subprocess.TimeoutExpired(["python"], 1)):
        def fail(*args, error=error, **kwargs):
            raise error
        monkeypatch.setattr(controller, "execute_simulation", fail)
        outcome = execute_simulation_request(request)
        assert outcome.status == "FAILED"
        assert outcome.error


def test_workspace_adapter_preserves_analysis_status_contract() -> None:
    ws_context = {"circuit_hash": "c" * 64, "input_hashes": {"netlist": "n"}}
    active = {"generated_at": "2026-11-04T00:00:00Z"}
    records = build_analysis_records(workspace_context=ws_context, active_workspace=active,
        comparison={"scenario_id": "S1"}, risk={"scenario_id": "S1"},
        status="CACHED_SIMULATION")
    assert [row["analysis_type"] for row in records] == [
        "circuit_validation", "graph_analysis", "spice_fault_comparison", "risk_assessment"]
    assert records[2]["status"] == "COMPLETE"
    assert records[2]["scenario_id"] == records[3]["scenario_id"] == "S1"


def test_vision_overlay_requires_manifest_verification_for_live_and_cached() -> None:
    base = {"context_key": "c", "netlist_component_refs": ("R1",), "risk_assessment": {"scenario_id": "S1"},
            "risk_path": "risk_assessment.json", "failed_component": "R1", "fault_type": "resistance_drift",
            "result_integrity": "VERIFIED", "inspection_ranking": None, "selected_component": None}
    assert VisionViewContext(**base, simulation_status="SUCCESS").overlay_risk is not None
    assert VisionViewContext(**base, simulation_status="CACHED_SIMULATION").overlay_risk is not None
    for status in ("STALE", "PROVENANCE_UNVERIFIED", "FAILED", "NOT_RUN", "CACHED"):
        context = VisionViewContext(**base, simulation_status=status)
        assert context.overlay_risk is None
    assert VisionViewContext(**{**base, "result_integrity": "STALE"},
                             simulation_status="SUCCESS").overlay_risk is None
