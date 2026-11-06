from circuitcare.frontend.intake import create_project_context
from circuitcare.frontend.state import INTAKE_PROJECT_KEY, clear_intake_draft, draft_is_current


def test_session_draft_is_fingerprint_scoped_and_clear_keeps_other_inputs():
    image = {
        "image_id": "image-1", "filename": "board.png", "sha256": "abc123",
        "role": "unknown", "media_type": "image/png",
    }
    project = create_project_context(images=[image], symptom_category="unknown", symptom_description=None)
    state = {INTAKE_PROJECT_KEY: project, "symptom": "unknown", "photos": [image]}

    assert draft_is_current(state, project.input_fingerprint)
    assert not draft_is_current(state, "changed-inputs")
    clear_intake_draft(state)
    assert INTAKE_PROJECT_KEY not in state
    assert state["symptom"] == "unknown"
    assert state["photos"] == [image]
