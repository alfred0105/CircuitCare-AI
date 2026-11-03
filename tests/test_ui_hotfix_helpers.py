import subprocess

import pytest

from circuitcare.ui import (
    SimulationRunError,
    _analysis_context_key,
    _advisor_matches,
    _measurement_set_id,
    _simulation_result_id,
    _simulation_status,
    _supports_bayesian_demo,
    _upsert_measurement,
    _validate_live_result,
)


def test_ui_context_and_measurement_updates_are_isolated():
    case = {"netlist": "tests/fixtures/divider_netlist.xml", "mapping": "data/circuits/divider_mapping.json"}
    first = _analysis_context_key("divider", case, "R1", "resistance_drift", "10k")
    changed_fault = _analysis_context_key("divider", case, "R2", "resistance_drift", "10k")
    changed_value = _analysis_context_key("divider", case, "R1", "resistance_drift", "20k")
    assert first != changed_fault != changed_value

    measurements = _upsert_measurement([], {"node": "VOUT", "value": 7.9, "source": "simulated_demo"})
    measurements = _upsert_measurement(measurements, {"node": "LOAD", "value": 3.95, "source": "simulated_demo"})
    measurements = _upsert_measurement(measurements, {"node": "vout", "value": 7.8, "source": "user_measurement"})
    assert [item["node"] for item in measurements] == ["vout", "LOAD"]
    assert measurements[0]["value"] == 7.8


def test_ui_does_not_activate_nonzero_subprocess_result(tmp_path):
    completed = subprocess.CompletedProcess(["python", "-m", "circuitcare.cli"], -11, "", "ngspice segfault")
    with pytest.raises(SimulationRunError, match="종료 코드: -11"):
        _validate_live_result(completed, tmp_path, "R1", "resistance_drift")


def test_ui_status_and_saved_advice_follow_current_analysis(tmp_path):
    measurements = [{"node": "VOUT", "value": 7.9, "unit": "V", "source": "simulated_demo"}]
    context = ("regulator", "U1", "regulator_output_rise", "8")
    saved = {
        "analysis_context_key": context,
        "measurement_set_id": _measurement_set_id(measurements),
        "simulation_result_id": _simulation_result_id(tmp_path),
    }
    assert _advisor_matches(saved, context, measurements, tmp_path)
    assert not _advisor_matches(saved, context, [], tmp_path)
    assert _simulation_status(False, "ngspice failed", True) == "FAILED"
    assert _simulation_status(False, None, True) == "CACHED"
    assert _simulation_status(False, None, False) == "NOT_RUN"
    assert _simulation_status(True, None, False) == "SUCCESS"


def test_ui_only_exposes_bayesian_for_its_matching_regulator_demo():
    case = "Regulator + divider + switch (cached demo)"
    assert _supports_bayesian_demo(case, "U1", "regulator_output_rise", "8")
    assert not _supports_bayesian_demo(case, "U1", "regulator_output_drop", "3")
    assert not _supports_bayesian_demo("Independent resistor divider (evaluation circuit A)", "R1", "resistance_drift", "10k")
