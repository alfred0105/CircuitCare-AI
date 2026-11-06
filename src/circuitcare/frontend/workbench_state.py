"""Session-scoped workbench navigation and viewer state."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from circuitcare.frontend.models import ProjectContext, SelectionState

SCREEN_KEY = "circuitcare_v2_screen"
SELECTION_KEY = "circuitcare_v2_selection"
ACTIVE_PHOTO_KEY = "circuitcare_v2_active_photo_id"
VIEW_ZOOM_KEY = "circuitcare_v2_view_zoom"
VIEW_TRANSFORM_KEY = "circuitcare_v2_view_transform"


def enter_workbench(state: MutableMapping[str, Any], project: ProjectContext) -> SelectionState:
    """Initialize PCB-first state without carrying a previous project's selection."""
    selection = SelectionState(
        project_id=project.project_id,
        board_id=project.board_id,
        active_tab="pcb",
        active_photo_id=project.image_records[0].image_id if project.image_records else None,
    )
    state[SCREEN_KEY] = "workbench"
    state[SELECTION_KEY] = selection
    state[ACTIVE_PHOTO_KEY] = selection.active_photo_id
    state[VIEW_ZOOM_KEY] = 1.0
    state[VIEW_TRANSFORM_KEY] = {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0}
    return selection


def update_selection(state: MutableMapping[str, Any], **changes: Any) -> SelectionState:
    """Update one project's immutable selection snapshot."""
    current = state.get(SELECTION_KEY)
    project = state.get("circuitcare_v2_project")
    if not isinstance(project, ProjectContext):
        raise ValueError("Workbench 프로젝트가 없습니다.")
    if not isinstance(current, SelectionState) or current.project_id != project.project_id:
        current = enter_workbench(state, project)
    values = {name: getattr(current, name) for name in current.__dataclass_fields__}
    values.update(changes)
    updated = SelectionState(**values)
    state[SELECTION_KEY] = updated
    if "active_photo_id" in changes:
        state[ACTIVE_PHOTO_KEY] = changes["active_photo_id"]
    return updated
