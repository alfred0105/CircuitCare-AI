from __future__ import annotations

from pathlib import Path
import hashlib
import io

import pytest
from PIL import Image

from circuitcare.frontend.intake import create_project_context
from circuitcare.frontend.state import INTAKE_IMAGES_KEY, INTAKE_PROJECT_KEY


def test_v2_flag_routes_to_real_entry_screen(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    project_root = Path(__file__).parents[1]
    monkeypatch.setenv("CIRCUITCARE_UI_V2", "1")
    app = AppTest.from_file(str(project_root / "src/circuitcare/ui.py"), default_timeout=30).run()

    assert not app.exception
    assert any("새 PCB 진단" in item.value for item in app.markdown)
    assert any(button.label == "예제 회로 체험" for button in app.button)
    assert any(button.label == "진단 시작" for button in app.button)

    app.radio[0].set_value("overheating").run()
    app.text_area[0].set_value("전원 연결 후 보드가 뜨거워짐").run()
    assert app.radio[0].value == "overheating"
    assert app.text_area[0].value == "전원 연결 후 보드가 뜨거워짐"

    demo_button = next(button for button in app.button if button.label == "예제 회로 체험")
    demo_button.click().run()
    assert not app.exception
    assert any(selectbox.label == "회로 데이터셋" for selectbox in app.selectbox)


def test_default_entry_keeps_legacy_ui_when_v2_flag_is_unset(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    project_root = Path(__file__).parents[1]
    monkeypatch.delenv("CIRCUITCARE_UI_V2", raising=False)
    app = AppTest.from_file(str(project_root / "src/circuitcare/ui.py"), default_timeout=30).run()

    assert not app.exception
    # The existing demo case chooser is still present on the legacy route.
    assert any(selectbox.label == "회로 데이터셋" for selectbox in app.selectbox)


def test_existing_project_draft_shows_prepared_state_without_claiming_analysis(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    image = Image.new("RGB", (40, 30), "blue")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    raw = stream.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    record = {
        "image_id": digest[:20], "sha256": digest, "filename": "board.png",
        "data": raw, "role": "unknown", "media_type": "image/png",
        "width": 40, "height": 30,
    }
    project = create_project_context(
        images=[record], symptom_category="unknown", symptom_description=None,
    )
    project_root = Path(__file__).parents[1]
    monkeypatch.setenv("CIRCUITCARE_UI_V2", "1")
    app = AppTest.from_file(str(project_root / "src/circuitcare/ui.py"), default_timeout=30)
    app.session_state[INTAKE_IMAGES_KEY] = [record]
    app.session_state[INTAKE_PROJECT_KEY] = project
    app.run()

    assert not app.exception
    assert any("프로젝트 생성 완료 · 진단 미실행" in item.value for item in app.success)
    assert any("통합 Viewer는 다음 단계에서 연결" in item.value for item in app.info)


def test_photo_upload_role_assignment_and_start_create_session_project(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    def png(color: str) -> bytes:
        image = Image.new("RGB", (64, 48), color)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()

    project_root = Path(__file__).parents[1]
    monkeypatch.setenv("CIRCUITCARE_UI_V2", "1")
    app = AppTest.from_file(str(project_root / "src/circuitcare/ui.py"), default_timeout=30).run()
    app.file_uploader[0].set_value([
        ("front.png", png("red"), "image/png"),
        ("detail.png", png("blue"), "image/png"),
    ]).run()

    assert not app.exception
    assert len(app.session_state[INTAKE_IMAGES_KEY]) == 2
    assert all(item["role"] == "unknown" for item in app.session_state[INTAKE_IMAGES_KEY])
    assert next(button for button in app.button if button.label == "진단 시작").disabled is False

    app.selectbox[0].set_value("front").run()
    assert app.session_state[INTAKE_IMAGES_KEY][0]["role"] == "front"
    app.radio[0].set_value("overheating").run()
    app.text_area[0].set_value("  전원을 켜면   과열됨  ").run()
    next(button for button in app.button if button.label == "진단 시작").click().run()

    assert not app.exception
    project = app.session_state[INTAKE_PROJECT_KEY]
    assert project.symptom_category == "overheating"
    assert project.symptom_description == "전원을 켜면 과열됨"
    assert project.image_records[0].side == "front"
    assert project.input_fingerprint
    assert any("프로젝트 생성 완료 · 진단 미실행" in item.value for item in app.success)


def test_photo_removal_preserves_symptom_input(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    image = Image.new("RGB", (32, 24), "green")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    project_root = Path(__file__).parents[1]
    monkeypatch.setenv("CIRCUITCARE_UI_V2", "1")
    app = AppTest.from_file(str(project_root / "src/circuitcare/ui.py"), default_timeout=30).run()
    app.file_uploader[0].set_value(("board.png", stream.getvalue(), "image/png")).run()
    app.radio[0].set_value("power_failure").run()
    next(button for button in app.button if button.label == "사진 제거").click().run()

    assert not app.exception
    assert app.session_state[INTAKE_IMAGES_KEY] == []
    assert app.radio[0].value == "power_failure"
    assert next(button for button in app.button if button.label == "진단 시작").disabled

