"""Session-state helpers for frontend intake drafts; no persistent storage."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from circuitcare.frontend.models import ProjectContext

INTAKE_IMAGES_KEY = "circuitcare_v2_images"
INTAKE_PROJECT_KEY = "circuitcare_v2_project"
INTAKE_UPLOAD_BATCH_KEY = "circuitcare_v2_upload_batch"


def clear_intake_draft(state: MutableMapping[str, Any]) -> None:
    state.pop(INTAKE_PROJECT_KEY, None)


def draft_is_current(state: MutableMapping[str, Any], fingerprint: str) -> bool:
    project = state.get(INTAKE_PROJECT_KEY)
    return isinstance(project, ProjectContext) and project.input_fingerprint == fingerprint

