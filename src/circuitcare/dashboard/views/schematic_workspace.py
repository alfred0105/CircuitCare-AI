"""Schematic-first workspace with the existing connectivity view as fallback."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from circuitcare.graph import direct_candidates, find_paths_result
from circuitcare.schematic.exporter import export_schematic
from circuitcare.schematic.identity import map_component_refs, read_symbol_identities


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
                               root: Path, comparison_path: Path, simulation_status: str) -> None:
    st.subheader("회로도 작업공간")
    context_token = hashlib.sha256(case_name.encode()).hexdigest()[:12]
    uploaded = st.file_uploader("KiCad 회로도 (.kicad_sch)", type=["kicad_sch"], key=f"schematic_source_{context_token}")
    schematic_path = None
    if uploaded is not None:
        try:
            schematic_path = _store_schematic(uploaded.getvalue(), root)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    elif case.get("schematic"):
        candidate = (root / case["schematic"]).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file():
            schematic_path = candidate

    nav, canvas, inspector = st.columns([1, 3, 1.2], gap="small")
    refs = sorted(circuit.components)
    state_key = f"schematic_selected_{context_token}"
    if st.session_state.get("schematic_case") != case_name:
        st.session_state["schematic_case"] = case_name
        st.session_state.pop(state_key, None)
    with nav:
        st.caption(f"회로 · {case_name}")
        st.caption(f"분석 Context · {selected_fault} / {fault_type} / {fault_value or '—'}")
        query = st.text_input("부품 검색", key=f"schematic_search_{state_key}").strip().casefold()
        filtered = [ref for ref in refs if query in ref.casefold()]
        current = st.session_state.get(state_key, selected_fault)
        options = filtered or refs
        index = options.index(current) if current in options else 0
        component_ref = st.selectbox("부품", options, index=index, key=f"schematic_component_{state_key}")
        st.session_state[state_key] = component_ref
        st.caption("시트 · / (상위 시트는 파일 선택 후 표시)")

    status = "NOT_EVALUATED"
    svg = None
    mapping: dict[str, dict] = {}
    if schematic_path is not None:
        try:
            identities, missing_sheets = read_symbol_identities(schematic_path, project_root=root)
            mapping = map_component_refs(refs, identities)
            result = export_schematic(schematic_path, project_root=root,
                                      cache_root=root / "data" / "schematic_svg_cache")
            if result.status == "EXPORTED" and result.svg_paths:
                paths = result.svg_paths
                with nav:
                    page = st.selectbox("시트 페이지", range(1, len(paths) + 1), key=f"schematic_page_{result.cache_key}")
                svg = paths[page - 1]
                status = "SVG_EXPORTED"
                with canvas:
                    st.caption(f"시트 {page} · KiCad CLI SVG · {schematic_path.relative_to(root)}")
                    st.image(str(svg), output_format="SVG", use_container_width=True)
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
        paths = find_paths_result(circuit, component_ref, max_hops=2)
        st.markdown(f"**{item.ref}** · {item.value or '값 없음'}")
        st.caption(item.library_id or "Library ID 없음")
        st.write("**연결 Net**")
        for conn in circuit.connections:
            if conn.ref == component_ref:
                st.caption(f"{conn.pin} → {conn.net}")
        identity = mapping.get(component_ref, {"status": "UNVERIFIED_MAPPING"})
        st.caption(f"회로도 매칭 · {identity.get('status', 'UNVERIFIED_MAPPING')}")
        for instance in identity.get("symbol_instances", []):
            st.caption(f"UUID · {instance['symbol_uuid']} · unit {instance['unit']} · {instance['sheet_path']}")
        st.write("**연결 분석 후보**")
        for candidate in candidates:
            st.caption(f"{candidate.target_ref} · {', '.join(candidate.shared_nets)}")
        st.caption(f"경로 검색 · {paths.status} · {len(paths.paths)}개 후보 경로")
        st.write("**Simulation**")
        st.caption(f"상태 · {simulation_status if comparison_path.exists() else status}")
        st.caption("실제 SPICE 검증 여부 · " + ("확인된 기존 결과" if comparison_path.exists() else "NOT_EVALUATED"))
        st.caption("연결 후보는 손상이나 전기적 위험의 증거가 아닙니다.")
