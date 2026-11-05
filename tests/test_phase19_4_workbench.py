from __future__ import annotations

from pathlib import Path

import pytest


def test_workbench_navigation_uses_korean_eda_areas_and_keeps_routes():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[1] / "src/circuitcare/ui.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["active_analysis_view"] == "회로도 Workbench"
    assert any("회로도" in item.options for item in app.radio)
    assert any("부품 상세" in item.value for item in app.markdown)
    initial_case = next(item for item in app.selectbox if item.key == "case_name").value

    next(item for item in app.button if item.label == "파형 상세").click().run()
    assert not app.exception
    assert app.session_state["active_analysis_view"] == "SPICE 파형"
    next(item for item in app.radio if item.key == "main_area").set_value("회로도").run()
    assert not app.exception

    analysis = next(item for item in app.radio if item.key == "main_area")
    analysis.set_value("분석").run()
    assert not app.exception
    assert app.session_state["active_analysis_view"] in {"분석 개요", "SPICE 파형", "2차 손상 위험"}
    advanced = next(item for item in app.button if item.label == "AI 성능 평가")
    advanced.click().run()
    assert not app.exception
    assert app.session_state["active_analysis_view"] == "AI 성능 평가"
    assert app.session_state["workbench_area"] == "고급 도구"

    next(item for item in app.button if item.label == "다중 사진 PCB 복원").click().run()
    assert not app.exception
    assert app.session_state["active_analysis_view"] == "다중 사진 PCB 복원"
    assert any("PCB 사진 여러 장 추가" in item.label for item in app.file_uploader)

    assert next(item for item in app.selectbox if item.key == "case_name").value == initial_case


def test_korean_status_labels_preserve_internal_codes():
    from circuitcare.dashboard.navigation import korean_status

    assert korean_status("EXCEEDED") == "설정 정격 초과"
    assert korean_status("UNKNOWN") == "미평가"
