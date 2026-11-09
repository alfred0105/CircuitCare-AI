"""Version-scoped diagnosis overlay state shared by the panel and PCB viewer."""

from __future__ import annotations

from typing import Any


def build_overlay_state(
    *, project_id: str, board_id: str | None, component_map_version: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Create a project/board/map-scoped overlay payload with at most three parts."""
    candidates = result.get("component_candidates", [])[:3]
    return {
        "project_id": project_id,
        "board_id": board_id,
        "component_map_version": component_map_version,
        "diagnosis_id": result.get("diagnosis_id"),
        "input_fingerprint": result.get("input_fingerprint"),
        "components": {str(row["component_id"]): row for row in candidates},
        "joint_candidates": result.get("joint_candidates", []),
    }


def current_overlay_candidates(
    value: Any, *, project_id: str, board_id: str | None,
    component_map_version: str | None,
) -> dict[str, dict[str, Any]]:
    """Return candidates only when the board and component map still match."""
    if isinstance(value, list):  # Legacy session state from the previous viewer bridge.
        return {str(component_id): {"visual_status": "SUSPECTED"} for component_id in value}
    if not isinstance(value, dict):
        return {}
    # Also accept the old direct ID → candidate mapping for live sessions.
    if "components" not in value:
        return value
    if value.get("project_id") != project_id or value.get("board_id") != board_id:
        return {}
    if value.get("component_map_version") != component_map_version:
        return {}
    candidates = value.get("components")
    return candidates if isinstance(candidates, dict) else {}
