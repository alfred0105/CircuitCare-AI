"""PCB-first F2 workbench shell with real intake images and an evidence-neutral panel."""

from __future__ import annotations

from typing import Any

from circuitcare.frontend.models import ProjectContext
from circuitcare.frontend.state import (
    INTAKE_IMAGES_KEY, INTAKE_PROJECT_KEY, clear_intake_draft,
    reset_intake_for_new_project,
)
from circuitcare.frontend.workbench_state import (
    ACTIVE_PHOTO_KEY, SCREEN_KEY, SELECTION_KEY, VIEW_ZOOM_KEY,
    VIEW_TRANSFORM_KEY, enter_workbench, update_selection,
)
from circuitcare.vision.image_loader import ImageLoadError, load_board_image


def _style(st: Any) -> None:
    st.markdown("""<style>
    [data-testid="stMainBlockContainer"] { max-width:none; padding:1rem 1.5rem 2rem; }
    .cc-wb-header { display:flex; align-items:center; gap:.6rem; color:#e9eef4; font-weight:700; font-size:1.1rem; }
    .cc-wb-subtle { color:#9aa9b8; font-size:.82rem; }
    [data-testid="stVerticalBlockBorderWrapper"]:has(.cc-inspection-marker) { position:sticky; top:1rem; }
    [class*="st-key-cc_viewer_canvas"] { overflow:auto; max-height:calc(100vh - 15rem); background:#101820; border:1px solid #334252; border-radius:8px; padding:.5rem; }
    div[role="radiogroup"] label { border:1px solid #334252; border-radius:6px; padding:.35rem .8rem; }
    @media (max-width:900px) { [data-testid="stMainBlockContainer"] { padding:.8rem; } }
    @media (max-width:700px) { .cc-viewer-canvas { max-height:60vh; } }
    </style>""", unsafe_allow_html=True)


def _render_pcb(st: Any, project: ProjectContext, photos: list[dict[str, Any]]) -> None:
    records = {item.image_id: item for item in project.image_records}
    valid = [item for item in photos if item.get("image_id") in records and isinstance(item.get("data"), bytes)]
    if not valid:
        st.info("PCB 사진 없음")
        return
    ids = [item["image_id"] for item in valid]
    selected_id = st.session_state.get(ACTIVE_PHOTO_KEY)
    if selected_id not in ids:
        selected_id = ids[0]
    selected = st.selectbox(
        "원본 사진", ids, index=ids.index(selected_id),
        format_func=lambda image_id: _photo_label(records[image_id], ids.index(image_id) + 1),
        key="circuitcare_v2_photo_choice",
    )
    if selected != selected_id:
        update_selection(st.session_state, active_photo_id=selected)
    record = records[selected]
    image_data = next(item["data"] for item in valid if item["image_id"] == selected)
    st.caption(f"{record.filename or 'PCB 사진'} · {record.side} / {record.capture_type} · {record.image_dimensions[0]}×{record.image_dimensions[1]} px")
    zoom = st.slider("확대", min_value=1.0, max_value=2.5, step=0.1,
                     key=VIEW_ZOOM_KEY, label_visibility="collapsed")
    try:
        image = load_board_image(image_data).image
    except ImageLoadError:
        st.error("사진을 표시할 수 없습니다.")
        return
    width = min(1600, max(480, int(720 * zoom)))
    st.session_state[VIEW_TRANSFORM_KEY] = {
        "scale": zoom, "offset_x": 0.0, "offset_y": 0.0,
        "image_width": image.width, "image_height": image.height,
        "coordinate_frame": "source_image_px",
    }
    with st.container(key="cc_viewer_canvas"):
        st.image(image, width=width)
    st.caption("사진별 보기 · 다중 사진 정합은 미실행")


def _photo_label(record: Any, number: int) -> str:
    side = {"front": "앞면", "back": "뒷면", "unknown": "미지정"}[record.side]
    role = {
        "full_view": "전체", "close_up": "확대", "oblique": "비스듬히",
        "marking_detail": "부품 표기", "unknown": "미지정",
    }[record.capture_type]
    return f"{side} {number} · {role}"


def render_inspection_panel(st: Any, project: ProjectContext) -> None:
    with st.container(border=True):
        st.markdown('<span class="cc-inspection-marker"></span>', unsafe_allow_html=True)
        st.markdown("### 전체 진단")
        st.info("진단 미실행")
        st.caption(f"사진 · {len(project.image_records)}장")
        symptom = {
            "power_failure": "전원 불량", "output_anomaly": "출력 이상",
            "overheating": "과열", "intermittent_operation": "간헐적 작동",
            "unknown": "증상 불명",
        }.get(project.symptom_category or "unknown", "증상 불명")
        st.caption(f"증상 · {symptom}")
        if project.symptom_description:
            st.caption(project.symptom_description)
        st.divider()
        st.markdown("**부품** · 미선택")
        st.markdown("**측정값** · 없음")
        st.markdown("**다음 점검** · 분석 데이터 없음")


def render_workbench_shell(st: Any, project: ProjectContext) -> None:
    """Render PCB/schematic tabs and a fixed desktop inspection column."""
    _style(st)
    selection = st.session_state.get(SELECTION_KEY)
    if getattr(selection, "project_id", None) != project.project_id:
        enter_workbench(st.session_state, project)

    title, edit, new = st.columns([5, 1, 1])
    with title:
        st.markdown('<div class="cc-wb-header">CircuitCare AI</div>', unsafe_allow_html=True)
        st.caption(f"{project.project_id[:8]} · 사진 {len(project.image_records)}장 · 진단 미실행")
    if edit.button("입력 수정", use_container_width=True, key="cc_v2_workbench_edit"):
        st.session_state["circuitcare_v2_edit_project_id"] = project.project_id
        st.session_state["circuitcare_v2_edit_board_id"] = project.board_id
        clear_intake_draft(st.session_state)
        st.session_state[SCREEN_KEY] = "entry"
        st.session_state.pop(SELECTION_KEY, None)
        st.session_state.pop("circuitcare_v2_photo_choice", None)
        st.session_state.pop(VIEW_ZOOM_KEY, None)
        st.rerun()
    if new.button("새 프로젝트", use_container_width=True, key="cc_v2_workbench_new"):
        reset_intake_for_new_project(st.session_state)
        st.session_state[SCREEN_KEY] = "entry"
        st.rerun()

    left, right = st.columns([3.6, 1.25], gap="medium")
    with left:
        pcb_tab, schematic_tab = st.tabs(
            ["PCB", "회로도"], key="circuitcare_v2_active_tab",
            default="PCB", on_change="rerun",
        )
        active_tab = st.session_state.get("circuitcare_v2_active_tab", "PCB")
        update_selection(st.session_state, active_tab="pcb" if active_tab == "PCB" else "schematic")
        with pcb_tab:
            if active_tab == "PCB":
                _render_pcb(st, project, st.session_state.get(INTAKE_IMAGES_KEY, []))
        with schematic_tab:
            if active_tab == "회로도":
                _render_schematic(st, project)
    with right:
        render_inspection_panel(st, project)


def _render_schematic(st: Any, project: ProjectContext) -> None:
    source = project.circuit_source
    if not source:
        st.info("회로도 없음")
        st.caption("설계 자료 추가")
        return
    if source.get("source_type") == "kicad_schematic":
        st.info("KiCad 회로도 자료가 있습니다.")
        st.caption("원본 Viewer는 이 화면에 아직 연결되지 않았습니다.")
    elif source.get("source_type") == "kicad_xml_netlist":
        st.info("회로도 레이아웃 없음")
        st.caption("XML Netlist는 연결 데이터이며 원본 회로도 배치를 포함하지 않습니다.")
    else:
        st.info("지원되지 않는 설계 자료")
