"""Overlay-ready terminal data using the component map canonical image frame."""

from __future__ import annotations

from typing import Any


def terminal_overlay_contract(pin_map: dict[str, Any]) -> dict[str, Any]:
    overlays = []
    for side, side_record in pin_map.get("sides", {}).items():
        for component in side_record.get("components", []):
            terminal_sources = [(None, terminal) for terminal in component.get("terminals", [])]
            for package in component.get("package_hypotheses", []):
                terminal_sources.extend((package.get("package_type"), terminal)
                    for terminal in package.get("terminals", []))
            for package_type, terminal in terminal_sources:
                overlays.append({"board_side": side, "component_id": component.get("component_id"),
                    "terminal_id": terminal.get("terminal_id"),
                    "package_type": package_type,
                    "position_xy": terminal.get("position_xy"),
                    "coordinate_frame": terminal.get("coordinate_frame"),
                    "position_status": terminal.get("position_status"),
                    "evidence": terminal.get("evidence", []),
                    "review_required": terminal.get("review_required", True),
                    "connectivity_status": "NOT_EVALUATED"})
            for package in component.get("package_hypotheses", []):
                for candidate in package.get("observed_pad_candidates", []):
                    overlays.append({"board_side": side, "component_id": component.get("component_id"),
                        "terminal_id": None, "package_type": package.get("package_type"),
                        "position_xy": candidate.get("position_xy"),
                        "coordinate_frame": component.get("coordinate_frame"),
                        "position_status": candidate.get("position_status"),
                        "evidence": candidate.get("evidence", []),
                        "review_required": candidate.get("review_required", True),
                        "connectivity_status": "NOT_EVALUATED"})
    return {"schema_version": "circuitcare.pcb-terminal-overlay.v1",
            "source_pin_hypothesis_schema_version": pin_map.get("schema_version"),
            "overlays": overlays,
            "electrical_connectivity": "NOT_EVALUATED"}
