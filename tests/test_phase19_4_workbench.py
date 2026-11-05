from __future__ import annotations

from pathlib import Path

import pytest


def test_workbench_is_default_and_analysis_navigation_preserves_circuit_context():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[1] / "src/circuitcare/ui.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    selector = next(item for item in app.selectbox if item.key == "active_analysis_view")
    assert selector.value == "회로도 Workbench"
    initial_case = next(item for item in app.selectbox if item.key == "case_name").value
    assert any("Inspector" in item.value for item in app.markdown)
    next(item for item in app.button if item.label == "파형 상세").click().run()
    assert not app.exception
    assert next(item for item in app.selectbox if item.key == "active_analysis_view").value == "SPICE 파형"

    selector = next(item for item in app.selectbox if item.key == "active_analysis_view")
    selector.select("AI 성능 평가").run()
    assert not app.exception
    selector = next(item for item in app.selectbox if item.key == "active_analysis_view")
    assert selector.value == "AI 성능 평가"
    assert any("CircuitCare AI" in item.value for item in app.markdown)

    selector.select("회로도 Workbench").run()
    assert not app.exception
    assert next(item for item in app.selectbox if item.key == "case_name").value == initial_case
    assert any("FAULT SOURCE" in item.value and "INSPECTED" in item.value for item in app.caption)
    next(item for item in app.button if item.label == "보고서").click().run()
    assert not app.exception
    assert next(item for item in app.selectbox if item.key == "active_analysis_view").value == "분석 개요"
