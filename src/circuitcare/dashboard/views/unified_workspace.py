"""PCB-first F2 workbench shell with real intake images and an evidence-neutral panel."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from typing import Any

from circuitcare.frontend.models import ProjectContext
from circuitcare.frontend.state import (
    INTAKE_IMAGES_KEY, INTAKE_PROJECT_KEY, clear_intake_draft,
    reset_intake_for_new_project,
)
from circuitcare.frontend.workbench_state import (
    ACTIVE_PHOTO_KEY, MODE_KEY, SCREEN_KEY, SELECTION_KEY, VIEW_ZOOM_KEY,
    VIEW_TRANSFORM_KEY, enter_workbench, update_selection,
)
from circuitcare.frontend.viewer_geometry import requested_view_transform
from circuitcare.schematic.exporter import export_schematic
from circuitcare.schematic.geometry import read_svg_view_box
from circuitcare.schematic.viewer import render_interactive_viewer
from circuitcare.vision.image_loader import ImageLoadError, load_board_image


def _style(st: Any) -> None:
    st.markdown("""<style>
    [data-testid="stMainBlockContainer"] { max-width:none; padding:1rem 1.5rem 2rem; }
    .cc-wb-header { display:flex; align-items:center; gap:.6rem; color:#e9eef4; font-weight:700; font-size:1.1rem; }
    .cc-wb-subtle { color:#9aa9b8; font-size:.82rem; }
    [data-testid="stVerticalBlockBorderWrapper"]:has(.cc-inspection-marker) { position:sticky; top:1.25rem; align-self:start; }
    [class*="st-key-cc_viewer_canvas"] { overflow:auto; max-height:calc(100vh - 15rem); background:#101820; border:1px solid #334252; border-radius:8px; padding:.5rem; }
    div[role="radiogroup"] label { border:1px solid #334252; border-radius:6px; padding:.35rem .8rem; }
    @media (max-width:900px) { [data-testid="stMainBlockContainer"] { padding:.8rem; } }
    @media (max-width:900px) {
      .st-key-cc_workbench_body [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
      .st-key-cc_workbench_body [data-testid="column"] { flex:1 1 100%; width:100%; min-width:100%; }
      [data-testid="stVerticalBlockBorderWrapper"]:has(.cc-inspection-marker) { position:static; }
    }
    @media (max-width:700px) { [class*="st-key-cc_viewer_canvas"] { max-height:60vh; } }
    </style>""", unsafe_allow_html=True)


def _render_pcb(st: Any, project: ProjectContext, photos: list[dict[str, Any]]) -> None:
    records = {item.image_id: item for item in project.image_records}
    valid = [item for item in photos if item.get("image_id") in records and isinstance(item.get("data"), bytes)]
    if not valid:
        st.info("PCB 사진 없음")
        if st.button("사진 추가", key="cc_v2_preview_add_photo", use_container_width=True):
            st.session_state["circuitcare_v2_edit_project_id"] = project.project_id
            st.session_state["circuitcare_v2_edit_board_id"] = project.board_id
            clear_intake_draft(st.session_state)
            st.session_state[SCREEN_KEY] = "entry"
            st.session_state.pop(SELECTION_KEY, None)
            st.session_state.pop("circuitcare_v2_photo_choice", None)
            st.session_state.pop(VIEW_ZOOM_KEY, None)
            st.rerun()
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
    size = record.image_dimensions
    if size:
        st.caption(f"{record.filename or 'PCB 사진'} · {record.side} / {record.capture_type} · {size[0]}×{size[1]} px")
    else:
        st.caption(f"{record.filename or 'PCB 사진'} · {record.side} / {record.capture_type}")
    zoom = st.slider("확대", min_value=1.0, max_value=2.5, step=0.1,
                     key=VIEW_ZOOM_KEY, label_visibility="collapsed")
    try:
        loaded = load_board_image(image_data)
        image = loaded.image
    except ImageLoadError:
        st.error("사진을 표시할 수 없습니다.")
        return
    width = min(1600, max(320, int(720 * zoom)))
    st.session_state[VIEW_TRANSFORM_KEY] = requested_view_transform(
        source_size=loaded.original_size,
        display_size=(width, max(1, round(width * image.height / image.width))),
        active_photo_id=selected,
    )
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


def render_inspection_panel(st: Any, project: ProjectContext, *, preview: bool = False) -> None:
    with st.container(border=True):
        st.markdown('<span class="cc-inspection-marker"></span>', unsafe_allow_html=True)
        st.markdown("### 전체 진단")
        if preview:
            st.info("미리보기 · 진단 미실행")
        else:
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
        enter_workbench(
            st.session_state, project,
            preview=st.session_state.get(MODE_KEY) == "PREVIEW_ONLY",
        )

    title, add_photo, edit, new = st.columns([5, 1, 1, 1])
    with title:
        st.markdown('<div class="cc-wb-header">CircuitCare AI</div>', unsafe_allow_html=True)
        st.caption(f"{project.project_id[:8]} · 사진 {len(project.image_records)}장 · 진단 미실행")
    if add_photo.button("사진 추가", use_container_width=True, key="cc_v2_workbench_add_photo"):
        st.session_state["circuitcare_v2_edit_project_id"] = project.project_id
        st.session_state["circuitcare_v2_edit_board_id"] = project.board_id
        clear_intake_draft(st.session_state)
        st.session_state[SCREEN_KEY] = "entry"
        st.session_state.pop(SELECTION_KEY, None)
        st.session_state.pop("circuitcare_v2_photo_choice", None)
        st.session_state.pop(VIEW_ZOOM_KEY, None)
        st.rerun()
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

    preview = st.session_state.get(MODE_KEY) == "PREVIEW_ONLY"
    with st.container(key="cc_workbench_body"):
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
                    _render_schematic(
                        st, project, st.session_state.get("circuitcare_v2_circuit_bytes"),
                    )
        with right:
            render_inspection_panel(st, project, preview=preview)


def _render_schematic(st: Any, project: ProjectContext, circuit_bytes: bytes | None = None) -> None:
    source = project.circuit_source
    if not source:
        st.info("회로도 없음")
        st.caption("설계 자료 추가")
        return
    if source.get("source_type") == "kicad_schematic":
        st.info("KiCad 회로도 자료가 있습니다.")
        raw = circuit_bytes
        if not raw:
            st.warning("회로도 파일 데이터를 찾을 수 없습니다. 입력을 다시 확인하세요.")
            return
        try:
            pages = _export_schematic_pages(raw, source.get("filename") or "uploaded.kicad_sch")
        except (OSError, ValueError) as exc:
            st.warning(f"회로도 Viewer를 열 수 없습니다 · {exc}")
            return
        if not pages:
            st.warning("KiCad SVG Export 결과가 없습니다.")
            return
        page_names = [page[0] for page in pages]
        page_name = st.selectbox("회로도 페이지", page_names, key="circuitcare_v2_schematic_page") if len(pages) > 1 else page_names[0]
        _, svg, view_box = next(page for page in pages if page[0] == page_name)
        context_key = hashlib.sha256(raw).hexdigest()
        rendered = render_interactive_viewer(
            st, svg=svg, asset_key=f"f2-{context_key}-{page_name}", view_box=view_box,
            geometry_status="UNVERIFIED_GEOMETRY", regions=[], overlay=None,
            selected_ref="", navigation_id=0, context_key=context_key,
            event_sequence_seed=0, key=f"cc-v2-schematic-{context_key[:12]}",
            on_selection_change=lambda *_: None,
        )
        if rendered is None:
            st.html(svg, width="stretch")
        st.caption("KiCad 원본 SVG · PCB 정합 및 진단 미실행")
    elif source.get("source_type") == "kicad_xml_netlist":
        st.info("회로도 레이아웃 없음")
        st.caption("XML Netlist는 연결 데이터이며 원본 회로도 배치를 포함하지 않습니다.")
    else:
        st.info("지원되지 않는 설계 자료")


def _export_schematic_pages(raw: bytes, filename: str) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """Reuse the bounded existing KiCad SVG exporter inside an ephemeral project root."""
    if not raw or len(raw) > 20_000_000:
        raise ValueError("회로도 파일 크기를 확인해 주세요.")
    project_root = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory(prefix="cc-f2-schematic-", dir=project_root) as temporary:
        temp_root = Path(temporary)
        source_path = temp_root / Path(filename).name
        if source_path.suffix != ".kicad_sch":
            source_path = source_path.with_suffix(".kicad_sch")
        source_path.write_bytes(raw)
        result = export_schematic(
            source_path, project_root=temp_root, cache_root=temp_root / "svg-cache",
        )
        if result.status != "EXPORTED":
            raise ValueError(result.message)
        pages = []
        for svg_path in result.svg_paths:
            view_box = read_svg_view_box(svg_path)
            if view_box is None:
                continue
            pages.append((svg_path.name, svg_path.read_text(encoding="utf-8"), view_box))
        return pages
