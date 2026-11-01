from pathlib import Path

import pytest

from circuitcare.graph import direct_candidates
from circuitcare.netlist import load_netlist


FIXTURE = Path(__file__).parent / "fixtures" / "simple_kicad_netlist.xml"


def test_kicad_netlist_parses_components_and_connections():
    circuit = load_netlist(FIXTURE)
    assert len(circuit.components) == 5
    assert circuit.components["U1"].value == "Regulator"
    assert circuit.components["C3"].library_id == "Device:C"
    assert any(x.ref == "U2" and x.pin == "1" and x.net == "VOUT" for x in circuit.connections)


def test_finding_candidates_does_not_claim_damage():
    circuit = load_netlist(FIXTURE)
    results = direct_candidates(circuit, "U1")
    by_ref = {x.target_ref: x for x in results}
    assert set(by_ref) == {"J1", "U2", "C3"}
    assert "VOUT" in by_ref["U2"].shared_nets
    assert by_ref["C3"].evidence_level == "connectivity_only"
    assert "R4" not in by_ref  # not electrically directly connected


def test_unknown_failure_ref_rejected():
    with pytest.raises(ValueError, match="Unknown component"):
        direct_candidates(load_netlist(FIXTURE), "U99")
