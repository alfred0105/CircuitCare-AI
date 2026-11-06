import base64
import io
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from circuitcare.vision.pin_estimation import estimate_component, estimate_component_map
from circuitcare.vision.pin_estimation.overlay_contract import terminal_overlay_contract
from circuitcare.vision.pin_estimation.pin_estimator import PinHypothesisService


def _component(**overrides):
    row = {"component_id": "component-r1", "component_type": "resistor",
           "bbox_xyxy": [40, 55, 80, 65], "polygon_xy": [[40, 55], [80, 55], [80, 65], [40, 65]],
           "source_image_ids": ["photo-top-1"], "measurement_history_refs": ["measurement-7"]}
    row.update(overrides)
    return row


def test_two_terminal_horizontal_vertical_and_rotated_geometry_is_canonical():
    horizontal = estimate_component(_component())
    assert [terminal.position_status for terminal in horizontal.terminals] == ["GEOMETRY_ESTIMATED"] * 2
    assert horizontal.terminals[0].position_xy[0] < 40
    assert horizontal.terminals[1].position_xy[0] > 80
    assert all(terminal.pin_number is None and terminal.pin_function == "UNKNOWN_FUNCTION"
               for terminal in horizontal.terminals)

    vertical = estimate_component(_component(bbox_xyxy=[55, 40, 65, 80],
        polygon_xy=[[55, 40], [65, 40], [65, 80], [55, 80]]))
    assert vertical.terminals[0].position_xy[1] < 40
    assert vertical.terminals[1].position_xy[1] > 80

    rotated = estimate_component(_component(bbox_xyxy=[50, 50, 78, 78],
        polygon_xy=[[50, 58], [58, 50], [78, 70], [70, 78]]))
    assert rotated.terminals[0].position_xy[0] < 64
    assert rotated.terminals[1].position_xy[0] > 64
    assert rotated.terminals[0].position_xy[1] < 64
    assert rotated.terminals[1].position_xy[1] > 64
    assert all(item.coordinate_frame == "CANONICAL_IMAGE_PIXEL" for item in rotated.terminals)


def test_visible_pad_appearance_is_separated_from_geometric_estimate():
    image = np.zeros((120, 140, 3), dtype=np.uint8)
    image[55:66, 50:71] = (35, 35, 35)
    image[57:64, 42:50] = (220, 220, 220)
    image[57:64, 71:79] = (220, 220, 220)
    result = estimate_component(_component(bbox_xyxy=[50, 55, 71, 66],
        polygon_xy=[[50, 55], [71, 55], [71, 66], [50, 66]]), image_rgb=image)
    assert any(item.position_status == "OBSERVED_TERMINAL" for item in result.terminals)
    assert result.electrical_connectivity == "NOT_EVALUATED"
    assert "UNKNOWN_POLARITY" not in result.warnings


@pytest.mark.parametrize("component_type", ["capacitor", "inductor", "diode", "fuse"])
def test_supported_two_terminal_types_keep_polarity_unassigned(component_type):
    result = estimate_component(_component(component_type=component_type))
    assert len(result.terminals) == 2
    assert all(row.pin_number is None and row.pin_function == "UNKNOWN_FUNCTION" for row in result.terminals)
    if component_type == "diode":
        assert "UNKNOWN_POLARITY; anode/cathode not inferred without polarity evidence" in result.warnings


@pytest.mark.parametrize("package_hint,pin_count,expected", [
    ("SOT-23", 3, ("SOT_23_CANDIDATE", 3)),
    ("SOIC-8", 8, ("SOIC_8_CANDIDATE", 8)),
    ("DIP-8", 8, ("DIP_8_CANDIDATE", 8)),
    ("QFP-32", 32, ("QFP_32_CANDIDATE", 32)),
])
def test_multipin_package_hypotheses_generate_unnumbered_geometry(package_hint, pin_count, expected):
    result = estimate_component(_component(component_type="integrated_circuit",
        package_hint=package_hint, pin_count=pin_count))
    candidate = next(row for row in result.package_hypotheses if row.package_type == expected[0])
    assert candidate.terminal_count == expected[1]
    assert len(candidate.terminals) == expected[1]
    assert all(item.pin_number is None and item.pin_function == "UNKNOWN_FUNCTION" for item in candidate.terminals)
    assert candidate.pin1_candidate["status"] == "UNRESOLVED"


def test_hidden_lead_qfn_does_not_claim_visible_terminals_and_pin1_stays_candidate():
    component = _component(component_type="integrated_circuit", package_hint="QFN", pin_count=16,
        pin1_marker_candidate={"position_xy": [43, 57], "evidence": ["SILK_DOT_APPEARANCE"]})
    result = estimate_component(component)
    candidate = result.package_hypotheses[0]
    assert candidate.package_type == "QFN_CANDIDATE"
    assert candidate.terminals == ()
    assert candidate.pin1_candidate["status"] == "UNVERIFIED_CANDIDATE"


def test_multilead_package_returns_separate_visual_pad_candidates():
    image = np.zeros((128, 128, 3), dtype=np.uint8)
    image[56:72, 44:84] = (50, 50, 50)
    for x in (48, 58, 68, 78):
        image[51:56, x - 2:x + 3] = (215, 215, 215)
        image[72:77, x - 2:x + 3] = (215, 215, 215)
    result = estimate_component(_component(component_type="integrated_circuit", package_hint="SOIC-8",
        pin_count=8, bbox_xyxy=[44, 56, 84, 72],
        polygon_xy=[[44, 56], [84, 56], [84, 72], [44, 72]]), image_rgb=image)
    candidate = next(row for row in result.package_hypotheses if row.package_type == "SOIC_8_CANDIDATE")
    assert candidate.observed_pad_candidates
    assert all(row["position_status"] == "OBSERVED_TERMINAL" for row in candidate.observed_pad_candidates)
    assert all(row["review_required"] for row in candidate.observed_pad_candidates)


def test_connector_with_external_terminals_uses_candidate_layout_only():
    result = estimate_component(_component(component_type="connector", pin_count=4))
    candidate = result.package_hypotheses[0]
    assert candidate.package_type == "EXTERNAL_CONNECTOR_TERMINALS_CANDIDATE"
    assert len(candidate.terminals) == 4
    assert all(item.position_status == "GEOMETRY_ESTIMATED" for item in candidate.terminals)


@pytest.mark.parametrize("box", [None, [1, 2, 3], [1, 2, 3, 4, 5], [3, 2, 1, 4],
                                  [0, 0, float("nan"), 2], [0, 0, float("inf"), 2]])
def test_invalid_component_box_returns_unresolved(box):
    result = estimate_component(_component(bbox_xyxy=box))
    assert result.status == "UNRESOLVED"
    assert result.terminals == ()


def test_unknown_crystal_terminal_count_does_not_assume_two_pins():
    result = estimate_component(_component(component_type="crystal"))
    assert result.package_hypotheses[0].package_type == "CRYSTAL_PIN_COUNT_UNRESOLVED"
    assert result.terminals == ()


def test_square_two_terminal_body_does_not_invent_a_major_axis():
    result = estimate_component(_component(bbox_xyxy=[50, 50, 70, 70],
        polygon_xy=[[50, 50], [70, 50], [70, 70], [50, 70]]))
    assert result.terminals == ()
    assert "BODY_AXIS_AMBIGUOUS; two-terminal positions unresolved" in result.warnings


def test_component_map_keeps_top_bottom_component_and_measurement_identity():
    image = Image.new("RGB", (120, 120), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode()
    cmap = {"schema_version": "circuitcare.pcb-component-map.v1", "board_id": "board-1", "sides": {
        "TOP": {"canonical_image": {"coordinate_frame": "MOSAIC_PIXEL", "image_png_base64": encoded},
            "components": [_component()]},
        "BOTTOM": {"canonical_image": {"coordinate_frame": "MOSAIC_PIXEL", "image_png_base64": encoded},
            "components": [_component(component_id="component-c1", component_type="capacitor")]}}}
    result = estimate_component_map(cmap)
    assert set(result["sides"]) == {"TOP", "BOTTOM"}
    top_component = result["sides"]["TOP"]["components"][0]
    assert top_component["component_id"] == "component-r1"
    assert top_component["measurement_history_refs"] == ["measurement-7"]
    assert top_component["terminals"][0]["position_xy"][0] < 40
    assert result["electrical_connectivity"] == "NOT_EVALUATED"
    json.dumps(result)
    overlay = terminal_overlay_contract(result)
    assert overlay["overlays"][0]["board_side"] == "TOP"
    assert overlay["overlays"][0]["connectivity_status"] == "NOT_EVALUATED"


def test_manual_terminal_edit_is_a_copy_and_keeps_measurement_history():
    source = estimate_component_map({"board_id": "b", "sides": {"TOP": {
        "components": [_component()], "canonical_image": {"coordinate_frame": "MOSAIC_PIXEL"}}}})
    service = PinHypothesisService()
    edited = service.apply_manual_edits(source, [{"component_id": "component-r1", "terminal_id": "terminal_a",
        "position_xy": [17, 63], "pin_number": "1", "pin_function": "ANODE"}], reviewer_id="reviewer-1")
    terminal = edited["sides"]["TOP"]["components"][0]["terminals"][0]
    assert terminal["position_status"] == "MANUAL_CONFIRMED"
    assert terminal["pin_number"] == "1" and terminal["pin_function"] == "ANODE"
    assert terminal["function_status"] == "USER_CONFIRMED"
    assert source["sides"]["TOP"]["components"][0]["terminals"][0]["position_status"] == "GEOMETRY_ESTIMATED"
    assert edited["sides"]["TOP"]["components"][0]["measurement_history_refs"] == ["measurement-7"]
    with pytest.raises(ValueError, match="reviewer_id"):
        service.apply_manual_edits(source, [], reviewer_id="")


def test_manual_package_terminal_edit_targets_one_package_hypothesis():
    source = estimate_component_map({"board_id": "b", "sides": {"TOP": {
        "components": [_component(component_type="integrated_circuit", pin_count=8)],
        "canonical_image": {"coordinate_frame": "MOSAIC_PIXEL"}}}})
    edited = PinHypothesisService().apply_manual_edits(source, [{
        "component_id": "component-r1", "package_type": "SOIC_8_CANDIDATE",
        "terminal_id": "side_a_long_01", "position_xy": [20, 30], "pin_number": "1",
    }], reviewer_id="reviewer-1")
    package = next(row for row in edited["sides"]["TOP"]["components"][0]["package_hypotheses"]
                   if row["package_type"] == "SOIC_8_CANDIDATE")
    pin = package["terminals"][0]
    assert pin["position_status"] == "MANUAL_CONFIRMED"
    assert pin["coordinate_frame"] == "MOSAIC_PIXEL"
    assert pin["pin_number"] == "1"
    assert pin["review_provenance"]["reviewer_id"] == "reviewer-1"


def test_invalid_coordinate_frame_fails_closed():
    result = estimate_component(_component(), coordinate_frame="PCB_DESIGN_MM")
    assert result.status == "UNRESOLVED"
    assert result.warnings == ("UNSUPPORTED_COORDINATE_FRAME",)


@pytest.mark.parametrize("identity_status", ["IDENTITY_AMBIGUOUS", "IDENTITY_CONFLICT"])
def test_uncertain_component_identity_blocks_merged_terminal_geometry(identity_status):
    result = estimate_component(_component(identity_match_status=identity_status))
    assert result.status == "UNRESOLVED"
    assert result.terminals == ()
    assert result.warnings[0].startswith(f"BLOCKED_{identity_status}")
