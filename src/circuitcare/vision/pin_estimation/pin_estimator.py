"""Independent pin/terminal hypothesis service for existing component maps."""

from __future__ import annotations

import base64
import binascii
import io
import math
from copy import deepcopy
from typing import Any

import numpy as np
from PIL import Image

from .geometry import component_axis, multipin_positions, terminal_pair
from .package_hypotheses import package_candidates
from .pad_candidates import extract_pad_candidates, extract_perimeter_pad_candidates
from .models import PackageHypothesis, PinHypothesis, TerminalHypothesis


SCHEMA_VERSION = "circuitcare.pcb-pin-hypothesis.v1"
CANONICAL_FRAME = "CANONICAL_IMAGE_PIXEL"
SUPPORTED_CANONICAL_FRAMES = {CANONICAL_FRAME, "MOSAIC_PIXEL"}
TWO_TERMINAL_TYPES = {"resistor", "capacitor", "inductor", "diode", "fuse", "two_terminal_fuse"}


def estimate_component(component: dict[str, Any], *, board_side: str = "UNKNOWN",
                       image_rgb: np.ndarray | None = None,
                       coordinate_frame: str = CANONICAL_FRAME) -> PinHypothesis:
    """Estimate terminal locations while keeping pin number/function unassigned."""
    if not isinstance(component, dict):
        return _unresolved("", "unknown", board_side, coordinate_frame, "INVALID_COMPONENT_RECORD")
    component_id = component.get("component_id")
    component_id = component_id if isinstance(component_id, str) and component_id else "UNIDENTIFIED_COMPONENT"
    kind = str(component.get("component_type", "unknown")).strip().lower()
    warnings = []
    bbox = _valid_box(component.get("bbox_xyxy"))
    if bbox is None:
        return _unresolved(component_id, kind, board_side, coordinate_frame, "INVALID_COMPONENT_BBOX",
                           component=component)
    if not isinstance(coordinate_frame, str) or coordinate_frame not in SUPPORTED_CANONICAL_FRAMES:
        return _unresolved(component_id, kind, board_side, coordinate_frame, "UNSUPPORTED_COORDINATE_FRAME",
                           component=component)
    identity_status = component.get("identity_match_status")
    if isinstance(identity_status, str) and identity_status in {"IDENTITY_AMBIGUOUS", "IDENTITY_CONFLICT"}:
        return _unresolved(component_id, kind, board_side, coordinate_frame,
            f"BLOCKED_{identity_status}; terminal geometry not fused", component=component)

    if image_rgb is not None and (not isinstance(image_rgb, np.ndarray) or image_rgb.ndim != 3
                                  or image_rgb.shape[2] < 3):
        warnings.append("INVALID_IMAGE_ARRAY; image cues skipped")
        image_rgb = None
    axis = component_axis(component)
    if axis is None:
        return _unresolved(component_id, kind, board_side, coordinate_frame, "INVALID_COMPONENT_GEOMETRY",
                           component=component)
    center, major, half_length, half_width = axis
    aspect = half_length / max(half_width, 1e-9)
    hypotheses = []
    top_level_terminals = []

    if kind in TWO_TERMINAL_TYPES or (kind in {"crystal", "crystal_resonator"}
                                      and component.get("pin_count", component.get("terminal_count")) == 2):
        candidates = extract_pad_candidates(image_rgb, component) if image_rgb is not None else []
        terminal_specs = _pair_with_visible_pads(component, candidates)
        terminals = tuple(_terminal(spec, coordinate_frame) for spec in terminal_specs)
        hypotheses.append(PackageHypothesis(
            package_type="TWO_TERMINAL_SMD_CANDIDATE", terminal_count=2,
            evidence=("COMPONENT_TYPE", "BODY_LONG_AXIS") + (("LOCAL_PAD_APPEARANCE_CANDIDATES",) if candidates else ()),
            side_terminal_counts=(), terminals=terminals))
        top_level_terminals = list(terminals)
        if not terminal_specs:
            warnings.append("BODY_AXIS_AMBIGUOUS; two-terminal positions unresolved")
        if kind == "diode":
            warnings.append("UNKNOWN_POLARITY; anode/cathode not inferred without polarity evidence")
    else:
        candidates = package_candidates(component)
        if not candidates:
            warnings.append("UNSUPPORTED_COMPONENT_TYPE")
        for package_type, terminal_count, side_counts, evidence, hidden in candidates:
            package_evidence = [evidence]
            if aspect >= 1.35:
                package_evidence.append("BODY_ASPECT_RATIO")
            else:
                package_evidence.append("BODY_GEOMETRY")
            pin1 = _pin1_candidate(component)
            if pin1 is None:
                pin1 = {"status": "UNRESOLVED", "evidence": ["NO_CONFIRMED_PIN1_MARKER"]}
            terminal_rows = [] if hidden or not side_counts else multipin_positions(component, package_type, side_counts)
            terminals = tuple(_terminal(row, coordinate_frame) for row in terminal_rows)
            visible_pad_candidates = (extract_perimeter_pad_candidates(image_rgb, component)
                                      if image_rgb is not None and not hidden else [])
            hypotheses.append(PackageHypothesis(package_type=package_type,
                terminal_count=terminal_count, evidence=tuple(package_evidence),
                side_terminal_counts=side_counts, pin1_candidate=pin1, terminals=terminals,
                observed_pad_candidates=tuple(visible_pad_candidates)))
        warnings.append("PACKAGE_AND_PIN_NUMBERS_REMAIN_HYPOTHESES")
        warnings.append("PIN_FUNCTIONS_UNKNOWN_UNLESS_EXACT_PART_METADATA_IS_VERIFIED")
        if kind in {"connector", "header"}:
            warnings.append("CONNECTOR_EDGE_ORIENTATION_UNVERIFIED")

    status = "HYPOTHESES_READY" if hypotheses else "UNRESOLVED"
    return PinHypothesis(component_id=component_id, component_type=kind,
        board_side=board_side if isinstance(board_side, str) and board_side in {"TOP", "BOTTOM"} else "UNKNOWN",
        source_image_ids=tuple(_string_list(component.get("source_image_ids"))),
        coordinate_frame=coordinate_frame, component_bbox_xyxy=bbox,
        package_hypotheses=tuple(hypotheses), terminals=tuple(top_level_terminals), status=status,
        electrical_connectivity="NOT_EVALUATED",
        measurement_history_refs=tuple(_string_list(component.get("measurement_history_refs"))),
        warnings=tuple(dict.fromkeys(warnings)))


def estimate_component_map(component_map: dict[str, Any]) -> dict[str, Any]:
    """Produce a side-separated pin hypothesis map from a serialized component map."""
    if not isinstance(component_map, dict):
        raise ValueError("component_map must be a mapping")
    output_sides = {}
    side_records = component_map.get("sides")
    if not isinstance(side_records, dict):
        side_records = {}
    for side in ("TOP", "BOTTOM"):
        side_record = side_records.get(side)
        if not isinstance(side_record, dict):
            continue
        image = _decode_canonical_image(side_record.get("canonical_image"))
        canonical_record = side_record.get("canonical_image")
        frame = canonical_record.get("coordinate_frame", "MOSAIC_PIXEL") if isinstance(canonical_record, dict) else "MOSAIC_PIXEL"
        if not isinstance(frame, str) or frame not in SUPPORTED_CANONICAL_FRAMES:
            frame = "MOSAIC_PIXEL"
        rows = []
        for component in side_record.get("components", []):
            if not isinstance(component, dict):
                rows.append(_unresolved("", "unknown", side, CANONICAL_FRAME,
                    "INVALID_COMPONENT_RECORD").to_dict())
                continue
            row = estimate_component(component, board_side=side, image_rgb=image,
                                     coordinate_frame=frame).to_dict()
            row["identity_match_status"] = component.get("identity_match_status", "UNRESOLVED")
            rows.append(row)
        output_sides[side] = {"coordinate_frame": frame, "components": rows}
    return {"schema_version": SCHEMA_VERSION, "board_id": component_map.get("board_id"),
            "source_component_map_schema_version": component_map.get("schema_version"),
            "sides": output_sides, "electrical_connectivity": "NOT_EVALUATED",
            "status": "PARTIAL_HYPOTHESES_READY" if output_sides else "NO_COMPONENT_SIDES",
            "limitations": ["Terminal positions are observed appearance candidates or geometry estimates.",
                "Pin numbers and functions are not asserted without supporting evidence.",
                "Electrical connectivity is not evaluated."]}


class PinHypothesisService:
    """Stable interface for CLI, API and frontend consumers."""

    def estimate(self, component_map: dict[str, Any]) -> dict[str, Any]:
        return estimate_component_map(component_map)

    def apply_manual_edits(self, hypothesis_map: dict[str, Any], edits: list[dict[str, Any]], *,
                           reviewer_id: str) -> dict[str, Any]:
        """Return a copy with explicit terminal confirmations/additions preserved."""
        result = deepcopy(hypothesis_map)
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValueError("reviewer_id is required for manual pin edits")
        components = {row.get("component_id"): row
            for side in result.get("sides", {}).values() for row in side.get("components", [])}
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError("each edit must be a mapping")
            component = components.get(edit.get("component_id"))
            if component is None:
                raise ValueError(f"Unknown component_id: {edit.get('component_id')!r}")
            point = edit.get("position_xy")
            try:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ValueError
                x, y = map(float, point)
            except (TypeError, ValueError):
                raise ValueError("position_xy must be two finite canonical-image coordinates") from None
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("position_xy must be two finite canonical-image coordinates")
            terminal_id = edit.get("terminal_id")
            package_type = edit.get("package_type")
            terminals = component.setdefault("terminals", [])
            if package_type is not None:
                package = next((item for item in component.get("package_hypotheses", [])
                                if item.get("package_type") == package_type), None)
                if package is None:
                    raise ValueError(f"Unknown package hypothesis: {package_type!r}")
                terminals = package.setdefault("terminals", [])
            terminal = next((item for item in terminals if item.get("terminal_id") == terminal_id), None)
            if terminal is None and package_type is None and not component.get("terminals"):
                matches = [(candidate, item) for candidate in component.get("package_hypotheses", [])
                    for item in candidate.get("terminals", []) if item.get("terminal_id") == terminal_id]
                if len(matches) == 1:
                    package, terminal = matches[0]
                    terminals = package["terminals"]
                elif len(matches) > 1:
                    raise ValueError("package_type is required when terminal_id appears in multiple package hypotheses")
            if terminal is None and not edit.get("add_terminal"):
                raise ValueError(f"Unknown terminal_id: {terminal_id!r}")
            if terminal is None:
                terminal = {"terminal_id": str(terminal_id or f"manual_terminal_{len(terminals) + 1}"),
                    "pin_number": None, "pin_function": "UNKNOWN_FUNCTION", "evidence": []}
                terminals.append(terminal)
            coordinate_frame = terminal.get("coordinate_frame", CANONICAL_FRAME)
            if coordinate_frame not in SUPPORTED_CANONICAL_FRAMES:
                raise ValueError(f"Unsupported terminal coordinate frame: {coordinate_frame!r}")
            terminal.update({"position_xy": [x, y], "coordinate_frame": coordinate_frame,
                "position_status": "MANUAL_CONFIRMED", "review_required": False,
                "review_provenance": {"reviewer_id": reviewer_id.strip(),
                    "reviewed_at": edit.get("reviewed_at"), "review_method": "MANUAL_CANONICAL_COORDINATE_EDIT"},
                "evidence": list(dict.fromkeys([*terminal.get("evidence", []), "USER_CONFIRMED_TERMINAL_LOCATION"]))})
            if edit.get("pin_number") is not None:
                terminal["pin_number"] = str(edit["pin_number"])
            if edit.get("pin_function") is not None:
                terminal["pin_function"] = str(edit["pin_function"])
                terminal["function_status"] = "USER_CONFIRMED"
        result["electrical_connectivity"] = "NOT_EVALUATED"
        return result


def _pair_with_visible_pads(component: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predicted = terminal_pair(component)
    if not candidates or len(predicted) != 2:
        return predicted
    axis = component_axis(component)
    if axis is None:
        return predicted
    _, _, _, half_width = axis
    remaining = list(candidates)
    for row in predicted:
        target = np.asarray(row["position_xy"], dtype=np.float64)
        if not remaining:
            break
        nearest = min(remaining, key=lambda candidate: float(np.linalg.norm(
            np.asarray(candidate["position_xy"], dtype=np.float64) - target)))
        distance = float(np.linalg.norm(np.asarray(nearest["position_xy"]) - target))
        if distance <= max(5.0, half_width * 1.5):
            row["position_xy"] = nearest["position_xy"]
            row["position_status"] = "OBSERVED_TERMINAL"
            row["evidence"] = [*nearest["evidence"], "NEAR_EXPECTED_TWO_TERMINAL_END"]
            row["heuristic_score"] = nearest["appearance_score"]
            row["score_kind"] = nearest["score_kind"]
            remaining.remove(nearest)
    return predicted


def _terminal(row: dict[str, Any], frame: str) -> TerminalHypothesis:
    return TerminalHypothesis(terminal_id=row["terminal_id"], pin_number=None,
        pin_function="UNKNOWN_FUNCTION", position_xy=tuple(map(float, row["position_xy"])),
        coordinate_frame=frame, position_status=row["position_status"],
        evidence=tuple(row.get("evidence", [])), review_required=True,
        heuristic_score=row.get("heuristic_score"), score_kind=row.get("score_kind", "RULE_BASED_NOT_CALIBRATED"))


def _pin1_candidate(component: dict[str, Any]) -> dict[str, Any] | None:
    marker = component.get("pin1_marker_candidate")
    if not isinstance(marker, dict) or not marker.get("evidence"):
        return None
    try:
        x, y = map(float, marker["position_xy"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return {"position_xy": [x, y], "status": "UNVERIFIED_CANDIDATE",
            "evidence": list(marker["evidence"]), "review_required": True}


def _valid_box(value: Any) -> tuple[float, float, float, float] | None:
    try:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        values = tuple(map(float, value))
        x1, y1, x2, y2 = values
    except (TypeError, ValueError):
        return None
    return values if all(map(math.isfinite, values)) and x1 < x2 and y1 < y2 else None


def _decode_canonical_image(record: Any) -> np.ndarray | None:
    if not isinstance(record, dict) or not isinstance(record.get("image_png_base64"), str):
        return None
    try:
        payload = base64.b64decode(record["image_png_base64"], validate=True)
        with Image.open(io.BytesIO(payload)) as image:
            if image.width <= 0 or image.height <= 0 or image.width > 12000 or image.height > 12000 \
                    or image.width * image.height > 40_000_000:
                return None
            return np.asarray(image.convert("RGB"))
    except (binascii.Error, OSError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _unresolved(component_id: str, kind: str, side: str, frame: str, warning: str,
                component: dict[str, Any] | None = None) -> PinHypothesis:
    return PinHypothesis(component_id=component_id or "UNIDENTIFIED_COMPONENT", component_type=kind,
        board_side=side if isinstance(side, str) and side in {"TOP", "BOTTOM"} else "UNKNOWN",
        source_image_ids=tuple(_string_list((component or {}).get("source_image_ids"))),
        coordinate_frame=frame, component_bbox_xyxy=_valid_box((component or {}).get("bbox_xyxy")),
        package_hypotheses=(), terminals=(), status="UNRESOLVED",
        electrical_connectivity="NOT_EVALUATED", warnings=(warning,))
