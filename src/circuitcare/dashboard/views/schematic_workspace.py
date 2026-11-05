"""Schematic-first workspace with the existing connectivity view as fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from circuitcare.graph import direct_candidates, find_paths_result
from circuitcare.schematic.exporter import export_schematic
from circuitcare.schematic.geometry import (
    GeometryResult,
    build_symbol_geometry,
    read_svg_view_box,
)
from circuitcare.schematic.identity import (
    discover_schematic_files,
    map_component_refs,
    read_symbol_identities,
)
from circuitcare.schematic.interaction import validate_selection_event
from circuitcare.schematic.viewer import render_interactive_viewer


def spice_verification_label(status: str, integrity: str) -> str:
    """Describe trusted simulation status only when both provenance signals agree."""
    if status == "SUCCESS" and integrity == "VERIFIED":
        return "VERIFIED · Live Simulation"
    if status == "CACHED_SIMULATION" and integrity == "VERIFIED":
        return "VERIFIED · Cached Simulation"
    return f"NOT VERIFIED · {status} / {integrity}"


def _store_schematic(raw: bytes, root: Path) -> Path:
    if not raw or len(raw) > 20_000_000:
        raise ValueError("회로도 파일은 20 MB 이하이어야 합니다.")
    if not raw.lstrip().startswith(b"(kicad_sch"):
        raise ValueError("KiCad S-expression 회로도 형식이 아닙니다.")
    folder = root / "data" / "schematic_uploads"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    target = folder / f"{digest}.kicad_sch"
    if not target.exists():
        target.write_bytes(raw)
    return target


def render_schematic_workspace(st: Any, *, circuit: Any, case_name: str, case: dict,
                               selected_fault: str, fault_type: str, fault_value: str | None,
                               root: Path, comparison_path: Path, simulation_status: str,
                               simulation_integrity: str) -> None:
    st.subheader("회로도 작업공간")
    fingerprint = {
        "case": case_name,
        "components": [(ref, item.value, item.library_id) for ref, item in sorted(circuit.components.items())],
        "connections": sorted((conn.ref, conn.pin, conn.net) for conn in circuit.connections),
    }
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode())
    schematic_path = None
    upload_token = hashlib.sha256(case_name.encode()).hexdigest()[:12]
    uploaded = st.file_uploader("KiCad 회로도 (.kicad_sch)", type=["kicad_sch"], key=f"schematic_source_{upload_token}")
    # Include the actual schematic bytes in the selection scope, including child sheets.
    if uploaded is not None:
        try:
            schematic_path = _store_schematic(uploaded.getvalue(), root)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    elif case.get("schematic"):
        candidate = (root / case["schematic"]).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file():
            schematic_path = candidate

    if schematic_path is not None:
        try:
            source_files, _ = discover_schematic_files(schematic_path, project_root=root)
            for source_file in source_files:
                digest.update(source_file.relative_to(root.resolve()).as_posix().encode())
                digest.update(source_file.read_bytes())
        except (OSError, ValueError):
            digest.update(schematic_path.name.encode())
    else:
        digest.update(b"no-kicad-schematic")
    context_key = digest.hexdigest()
    context_token = context_key[:16]
    state_key = f"schematic_inspected_{context_token}"
    navigation_key = f"schematic_navigation_{context_token}"
    initial_ref = st.session_state.get(state_key)
    if initial_ref not in circuit.components:
        initial_ref = selected_fault if selected_fault in circuit.components else min(circuit.components)

    nav, canvas, inspector = st.columns([1, 3, 1.2], gap="small")
    refs = sorted(circuit.components)
    query = ""
    component_ref = initial_ref
    with nav:
        st.caption(f"회로 · {case_name}")
        st.caption(f"분석 Context · {selected_fault} / {fault_type} / {fault_value or '—'}")
        query = st.text_input("부품 검색", key=f"schematic_search_{state_key}").strip().casefold()
        filtered = [ref for ref in refs if query in ref.casefold()]
        if not filtered:
            st.info("검색한 Reference가 현재 회로에 없습니다.")
        else:
            widget_key = f"schematic_component_{context_token}"
            if widget_key not in st.session_state or st.session_state.get(widget_key) not in filtered:
                st.session_state[widget_key] = initial_ref if initial_ref in filtered else filtered[0]
            component_ref = st.selectbox("부품 검색 결과", filtered, key=widget_key)
            if component_ref != st.session_state.get(state_key):
                st.session_state[state_key] = component_ref
                st.session_state[navigation_key] = int(st.session_state.get(navigation_key, 0)) + 1

    status = "NOT_EVALUATED"
    svg = None
    svg_path = None
    view_box = None
    geometry = GeometryResult("UNVERIFIED_GEOMETRY", "회로도 geometry를 사용할 수 없습니다.")
    mapping: dict[str, dict] = {}
    if schematic_path is not None:
        try:
            identities, missing_sheets = read_symbol_identities(schematic_path, project_root=root)
            mapping = map_component_refs(refs, identities)
            if missing_sheets:
                mapping = {ref: {"component_ref": ref, "status": "INCOMPLETE_PROJECT"}
                           for ref in refs}
            result = export_schematic(schematic_path, project_root=root,
                                      cache_root=root / "data" / "schematic_svg_cache")
            if result.status == "EXPORTED" and result.svg_paths:
                svg_paths = result.svg_paths
                with nav:
                    page_names = [item.name for item in svg_paths]
                    page_key = f"schematic_page_{context_token}"
                    if st.session_state.get(page_key) not in page_names:
                        st.session_state[page_key] = page_names[0]
                    page_name = st.selectbox("회로도 페이지", page_names, key=page_key)
                svg_path = next(item for item in svg_paths if item.name == page_name)
                svg = svg_path.read_text(encoding="utf-8")
                status = "SVG_EXPORTED"
                geometry = build_symbol_geometry(schematic_path, result.svg_paths, project_root=root)
                view_box = geometry.view_box or read_svg_view_box(svg_path)
                allowed_refs = set(refs)
                regions = [region for region in geometry.regions if region.component_ref in allowed_refs]
                if len(regions) != len(geometry.regions):
                    geometry = GeometryResult("UNVERIFIED_GEOMETRY", "Schematic Reference does not match the current netlist", view_box)
                    regions = []
                asset_key = f"{result.cache_key}:{svg_path.name}"
                with canvas:
                    st.caption(f"KiCad CLI SVG · {schematic_path.relative_to(root)} · {svg_path.name}")
                    viewer_key = f"schematic_viewer_{context_token}_{hashlib.sha256(svg_path.name.encode()).hexdigest()[:8]}"
                    viewer_result = None
                    if view_box is not None:
                        def handle_viewer_selection() -> None:
                            current = st.session_state.get(viewer_key)
                            event = getattr(current, "selection", None)
                            if not isinstance(event, dict) or event.get("event_id") == st.session_state.get(f"last_event_{viewer_key}"):
                                return
                            valid, reason = validate_selection_event(event, component_refs=set(refs),
                                                                    geometry=geometry, context_key=context_key)
                            st.session_state[f"last_event_{viewer_key}"] = event.get("event_id")
                            if not valid:
                                st.session_state[f"selection_error_{viewer_key}"] = reason
                                return
                            st.session_state[state_key] = event["component_ref"]
                            st.session_state[f"schematic_component_{context_token}"] = event["component_ref"]
                            st.session_state[navigation_key] = int(st.session_state.get(navigation_key, 0)) + 1

                        viewer_result = render_interactive_viewer(
                            st, svg=svg, asset_key=asset_key, view_box=view_box,
                            geometry_status=geometry.status,
                            regions=[{"component_ref": item.component_ref, "symbol_uuid": item.symbol_uuid,
                                      "sheet_path": item.sheet_path, "unit": item.unit,
                                      "polygon": [list(point) for point in item.polygon]} for item in regions],
                            selected_ref=component_ref,
                            navigation_id=int(st.session_state.get(navigation_key, 0)),
                            context_key=context_key, key=viewer_key,
                            on_selection_change=handle_viewer_selection,
                        )
                    if viewer_result is None:
                        st.image(str(svg_path), output_format="SVG", use_container_width=True)
                        st.caption("Pan/Zoom Viewer를 사용할 수 없어 SVG 정적 보기로 표시합니다.")
                    else:
                        selection_error = st.session_state.pop(f"selection_error_{viewer_key}", None)
                        if selection_error:
                            st.warning(f"회로도 선택 이벤트를 거부했습니다: {selection_error}")
                        st.caption(f"Symbol Geometry · {geometry.status} · {geometry.message}")
            else:
                with canvas:
                    st.warning(f"회로도 Export를 사용할 수 없습니다 ({result.status}). {result.message}")
            if missing_sheets:
                st.warning("누락되거나 허용 경로 밖인 하위 시트: " + ", ".join(missing_sheets))
        except (OSError, ValueError) as exc:
            with canvas:
                st.error(f"회로도 확인 실패: {exc}")
    else:
        with canvas:
            st.info("실제 KiCad 회로도 파일이 선택되지 않았습니다. 아래 연결 화면은 XML 넷리스트에서 만든 논리 연결 그래프이며 실제 회로도 배치를 나타내지 않습니다.")

    if svg is None:
        from circuitcare.dashboard.views.circuit import render_circuit_view
        with canvas:
            render_circuit_view(st, circuit=circuit, case_name=case_name, case=case,
                                selected_fault=selected_fault, fault_type=fault_type,
                                fault_value=fault_value, root=root, comparison_path=comparison_path)

    with inspector:
        item = circuit.components[component_ref]
        candidates = direct_candidates(circuit, component_ref)
        path_search = find_paths_result(circuit, component_ref, max_hops=2)
        st.markdown(f"**{item.ref}** · {item.value or '값 없음'}")
        st.caption(item.library_id or "Library ID 없음")
        st.write("**연결 Net**")
        for conn in circuit.connections:
            if conn.ref == component_ref:
                st.caption(f"{conn.pin} → {conn.net}")
        identity = mapping.get(component_ref, {"status": "UNVERIFIED_MAPPING"})
        st.caption(f"점검 선택 · {component_ref} · 고장 원인 {selected_fault} (별도 상태)")
        st.caption(f"회로도 매칭 · {identity.get('status', 'UNVERIFIED_MAPPING')}")
        for instance in identity.get("symbol_instances", []):
            st.caption(f"UUID · {instance['symbol_uuid']} · unit {instance['unit']} · {instance['sheet_path']}")
        st.write("**연결 분석 후보**")
        for candidate in candidates:
            st.caption(f"{candidate.target_ref} · {', '.join(candidate.shared_nets)}")
        st.caption(f"경로 검색 · {path_search.status} · {len(path_search.paths)}개 후보 경로")
        st.write("**Simulation**")
        st.caption(f"상태 · {simulation_status}")
        st.caption(f"SPICE 검증 · {spice_verification_label(simulation_status, simulation_integrity)}")
        st.caption(f"SVG Export 상태 · {status}")
        st.caption("연결 후보는 손상이나 전기적 위험의 증거가 아닙니다.")
