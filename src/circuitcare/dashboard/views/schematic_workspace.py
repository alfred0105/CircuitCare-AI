"""Schematic-first workspace with the existing connectivity view as fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from circuitcare.graph import direct_candidates, find_paths_result
from circuitcare.schematic.electrical_equivalence import verify_schematic_netlist
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
from circuitcare.schematic.measurement_geometry import build_measurement_anchors
from circuitcare.schematic.overlay import (
    build_fault_overlay,
    build_measurement_overlay,
    build_risk_overlay,
)
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


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def render_schematic_workspace(st: Any, *, circuit: Any, case_name: str, case: dict,
                               selected_fault: str, fault_type: str, fault_value: str | None,
                               root: Path, comparison_path: Path, simulation_status: str,
                               simulation_integrity: str, risk_assessment: dict,
                               comparison: dict, analysis_snapshot: Any,
                               current_fingerprint: dict, bayesian_supported: bool,
                               analysis_context_key: Any) -> None:
    fingerprint = {
        "case": case_name,
        "components": [(ref, item.value, item.library_id) for ref, item in sorted(circuit.components.items())],
        "connections": sorted((conn.ref, conn.pin, conn.net) for conn in circuit.connections),
    }
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode())
    schematic_path = None
    upload_token = hashlib.sha256(case_name.encode()).hexdigest()[:12]
    uploaded = st.sidebar.file_uploader(
        "KiCad 회로도 (.kicad_sch)", type=["kicad_sch"],
        key=f"schematic_source_{upload_token}", max_upload_size=20,
    )
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
    netlist_path = Path(case["netlist"])
    if not netlist_path.is_absolute():
        netlist_path = root / netlist_path
    try:
        digest.update(netlist_path.resolve(strict=True).read_bytes())
    except OSError:
        digest.update(b"unavailable-netlist")
    context_key = digest.hexdigest()
    context_token = context_key[:16]
    state_key = f"schematic_inspected_{context_token}"
    navigation_key = f"schematic_navigation_{context_token}"
    initial_ref = st.session_state.get(state_key)
    if initial_ref not in circuit.components:
        initial_ref = selected_fault if selected_fault in circuit.components else min(circuit.components)

    nav, canvas, inspector = st.columns([0.85, 3.0, 1.4], gap="small")
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
    equivalence = None
    mapping: dict[str, dict] = {}
    overlay_mode = "기본"
    overlay_payload: dict | None = None
    measurement_recommendation: dict | None = None
    measurement_anchors = None
    measurement_source = "NONE"
    measurement_set_id = None
    measurement_bundle: dict = {}
    diagnosis = {}
    inspection_ranking = {}
    if schematic_path is not None:
        try:
            equivalence = verify_schematic_netlist(
                schematic_path, netlist_path, project_root=root,
                cache_root=root / "data" / "schematic_equivalence_cache",
            )
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
                interaction_geometry = geometry
                if equivalence is None or equivalence.status != "VERIFIED_EQUIVALENT":
                    reason = equivalence.message if equivalence else "Equivalence check unavailable"
                    interaction_geometry = GeometryResult(
                        "UNVERIFIED_GEOMETRY",
                        f"Electrical equivalence {equivalence.status if equivalence else 'NOT_VERIFIED'}: {reason}",
                        view_box,
                    )
                    regions = []
                asset_key = f"{result.cache_key}:{svg_path.name}"
                with canvas:
                    mode_key = f"schematic_overlay_mode_{context_token}"
                    overlay_mode = st.radio(
                        "회로도 보기",
                        ["기본", "연결 후보", "전기적 위험", "측정·점검"],
                        horizontal=True,
                        key=mode_key,
                    )
                    if overlay_mode == "연결 후보":
                        overlay_payload = build_fault_overlay(
                            circuit=circuit, failed_component=selected_fault,
                            geometry=interaction_geometry,
                            electrical_equivalence=equivalence.status if equivalence else "NOT_VERIFIED",
                            context_id=context_key, asset_key=asset_key,
                        )
                    elif overlay_mode == "전기적 위험":
                        overlay_payload = build_risk_overlay(
                            circuit=circuit, failed_component=selected_fault, fault_type=fault_type,
                            fault_value=fault_value, risk=risk_assessment, comparison=comparison,
                            simulation_status=simulation_status,
                            simulation_integrity=simulation_integrity,
                            manifest=getattr(analysis_snapshot, "manifest", {}),
                            current_fingerprint=current_fingerprint, geometry=interaction_geometry,
                            electrical_equivalence=equivalence.status if equivalence else "NOT_VERIFIED",
                            context_id=context_key, asset_key=asset_key,
                        )
                    elif overlay_mode == "측정·점검":
                        diagnosis_state = st.session_state.get("diagnosis_result") or {}
                        diagnosis_state_id = hashlib.sha256(repr(analysis_context_key).encode()).hexdigest()[:16]
                        state_measurements = st.session_state.get("measurements", [])
                        from circuitcare.workspace.measurement_provenance import (
                            measurement_set_sha256,
                        )
                        current_measurement_set = measurement_set_sha256(state_measurements)
                        state_is_current = (
                            diagnosis_state.get("analysis_context_id") == diagnosis_state_id
                            and diagnosis_state.get("measurement_set_sha256") == current_measurement_set
                        )
                        if state_is_current:
                            measurement_bundle = diagnosis_state
                        elif bayesian_supported and not state_measurements and case.get("prior"):
                            prior_root = root / case["prior"]
                            measurement_bundle = {
                                "diagnosis": _json_object(prior_root / "diagnosis.json"),
                                "inspection_ranking": _json_object(prior_root / "inspection_ranking.json"),
                                "recommendations": _json_object(prior_root / "measurement_recommendations.json"),
                            }
                        if bayesian_supported and measurement_bundle:
                            diagnosis = measurement_bundle.get("diagnosis", {})
                            inspection_ranking = measurement_bundle.get("inspection_ranking", {})
                            used = diagnosis.get("used_measurements", [])
                            sources = {str(item.get("source", "")) for item in used if isinstance(item, dict)}
                            measurement_source = next(iter(sources)) if len(sources) == 1 else (
                                "prior_only" if not used else "mixed_sources"
                            )
                            measurement_set_id = current_measurement_set if state_is_current else "prior_only"
                            recommendation = measurement_bundle.get("recommendations", {}).get("recommended_measurement")
                            if recommendation:
                                measurement_recommendation = dict(recommendation)
                                if geometry.status == "VERIFIED_GEOMETRY":
                                    measurement_anchors = build_measurement_anchors(
                                        node=str(recommendation.get("node", "")), circuit=circuit,
                                        schematic_path=schematic_path, project_root=root,
                                        geometry=geometry,
                                    )
                        overlay_payload = build_measurement_overlay(
                            circuit=circuit, failed_component=selected_fault,
                            geometry=interaction_geometry,
                            electrical_equivalence=equivalence.status if equivalence else "NOT_VERIFIED",
                            context_id=context_key, asset_key=asset_key,
                            support_status="VERIFIED_CURRENT_CONTEXT" if bayesian_supported and measurement_bundle else "NOT_SUPPORTED",
                            source_class=measurement_source,
                            measurement_set_id=measurement_set_id,
                            recommendation=measurement_recommendation,
                            anchors=measurement_anchors,
                            inspection_ranking=inspection_ranking,
                            model_mismatch=bool(diagnosis.get("model_mismatch")),
                        )
                    if overlay_payload:
                        if overlay_payload.get("status") == "BLOCKED":
                            st.info(f"이 보기의 Overlay가 비활성화되었습니다. {overlay_payload.get('reason')}")
                        elif overlay_payload.get("status") == "UNVERIFIED_MEASUREMENT_LOCATION":
                            st.info(f"측정 추천은 정보 패널에서만 확인할 수 있습니다. 위치 검증 결과: {overlay_payload.get('reason')}")
                        elif overlay_payload.get("reason"):
                            st.caption(str(overlay_payload["reason"]))
                        if overlay_mode == "연결 후보" and overlay_payload.get("status") == "READY":
                            path_status = overlay_payload.get("path_search", {}).get("status", "UNKNOWN")
                            st.caption(f"보라: 사용자 고장 가정 · 파랑: 연결 후보 (손상 증거 아님) · 배선은 표시하지 않음 · 경로 검색: {path_status}")
                        elif overlay_mode == "전기적 위험" and overlay_payload.get("status") == "READY":
                            st.caption("정격 비교 결과입니다. EXCEEDED/NEAR_LIMIT는 실제 손상 확정이 아니며, WITHIN_LIMIT는 평가된 Metric에만 적용됩니다.")
                        elif overlay_mode == "측정·점검" and overlay_payload.get("status") == "READY":
                            st.caption("측정 핀은 논리적 회로도 후보이며 PCB에서 안전하거나 접근 가능한 프로브 위치를 보증하지 않습니다. 점검 점수는 손상 확률이 아닙니다.")
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
                                                                    geometry=interaction_geometry,
                                                                    context_key=context_key,
                                                                    asset_key=asset_key)
                            prior_sequence = int(st.session_state.get(f"last_seq_{viewer_key}", 0))
                            event_sequence = event.get("event_seq")
                            if not valid or type(event_sequence) is not int or event_sequence <= prior_sequence:
                                st.session_state[f"selection_error_{viewer_key}"] = reason
                                return
                            st.session_state[f"last_seq_{viewer_key}"] = event_sequence
                            st.session_state[f"last_event_{viewer_key}"] = event.get("event_id")
                            st.session_state[state_key] = event["component_ref"]
                            st.session_state[f"schematic_component_{context_token}"] = event["component_ref"]
                            st.session_state[navigation_key] = int(st.session_state.get(navigation_key, 0)) + 1

                        viewer_result = render_interactive_viewer(
                            st, svg=svg, asset_key=asset_key, view_box=view_box,
                            geometry_status=interaction_geometry.status,
                            overlay=overlay_payload,
                            regions=[{"component_ref": item.component_ref, "symbol_uuid": item.symbol_uuid,
                                      "sheet_path": item.sheet_path, "unit": item.unit,
                                      "polygon": [list(point) for point in item.polygon]} for item in regions],
                            selected_ref=component_ref,
                            navigation_id=int(st.session_state.get(navigation_key, 0)),
                            context_key=context_key,
                            event_sequence_seed=int(st.session_state.get(f"last_seq_{viewer_key}", 0)),
                            key=viewer_key,
                            on_selection_change=handle_viewer_selection,
                        )
                    if viewer_result is None:
                        st.image(str(svg_path), output_format="SVG", use_container_width=True)
                        st.caption("Pan/Zoom Viewer를 사용할 수 없어 SVG 정적 보기로 표시합니다.")
                    else:
                        selection_error = st.session_state.pop(f"selection_error_{viewer_key}", None)
                        if selection_error:
                            st.warning(f"회로도 선택 이벤트를 거부했습니다: {selection_error}")
                        eq_status = equivalence.status if equivalence else "NOT_VERIFIED"
                        st.caption(f"Electrical equivalence · {eq_status} · "
                                   f"{equivalence.message if equivalence else 'Schematic unavailable'}")
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
            mode_key = f"schematic_overlay_mode_{context_token}"
            overlay_mode = st.radio(
                "분석 보기",
                ["기본", "연결 후보", "전기적 위험", "측정·점검"],
                horizontal=True,
                key=mode_key,
            )
            if overlay_mode == "측정·점검":
                # Bayesian evidence can be useful in the inspector without a
                # schematic, but no physical or page coordinate is inferred.
                from circuitcare.workspace.measurement_provenance import (
                    measurement_set_sha256,
                )

                diagnosis_state = st.session_state.get("diagnosis_result") or {}
                diagnosis_state_id = hashlib.sha256(repr(analysis_context_key).encode()).hexdigest()[:16]
                state_measurements = st.session_state.get("measurements", [])
                state_is_current = (
                    diagnosis_state.get("analysis_context_id") == diagnosis_state_id
                    and diagnosis_state.get("measurement_set_sha256") == measurement_set_sha256(state_measurements)
                )
                if state_is_current:
                    measurement_bundle = diagnosis_state
                elif bayesian_supported and not state_measurements and case.get("prior"):
                    prior_root = root / case["prior"]
                    measurement_bundle = {
                        "diagnosis": _json_object(prior_root / "diagnosis.json"),
                        "inspection_ranking": _json_object(prior_root / "inspection_ranking.json"),
                        "recommendations": _json_object(prior_root / "measurement_recommendations.json"),
                    }
                if bayesian_supported and measurement_bundle:
                    diagnosis = measurement_bundle.get("diagnosis", {})
                    inspection_ranking = measurement_bundle.get("inspection_ranking", {})
                    used = diagnosis.get("used_measurements", [])
                    sources = {str(item.get("source", "")) for item in used if isinstance(item, dict)}
                    measurement_source = next(iter(sources)) if len(sources) == 1 else (
                        "prior_only" if not used else "mixed_sources"
                    )
                    measurement_set_id = "current_measurements" if state_is_current else "prior_only"
                    measurement_recommendation = measurement_bundle.get("recommendations", {}).get(
                        "recommended_measurement"
                    )
                st.info("검증된 KiCad 회로도가 없어 측정 위치는 회로도에 표시하지 않습니다. 추천은 정보 패널의 Node 이름으로만 제공합니다.")

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
        st.markdown("#### Inspector")
        st.markdown(f"**{item.ref}** · {item.value or '값 없음'}")
        st.caption(item.library_id or "Library ID 없음")
        st.caption(f"FAULT SOURCE · {selected_fault}    INSPECTED · {component_ref}")
        st.divider()
        st.caption("SUMMARY · 현재 회로의 연결 및 회로도 매칭")
        st.write("**연결 Net**")
        for conn in circuit.connections:
            if conn.ref == component_ref:
                st.caption(f"{conn.pin} → {conn.net}")
        identity = mapping.get(component_ref, {"status": "UNVERIFIED_MAPPING"})
        if equivalence is not None:
            st.caption(f"회로도/넷리스트 정합성 · {equivalence.status} · {equivalence.message}")
        st.caption(f"점검 선택 · {component_ref} · 고장 원인 {selected_fault} (별도 상태)")
        st.caption(f"회로도 매칭 · {identity.get('status', 'UNVERIFIED_MAPPING')}")
        for instance in identity.get("symbol_instances", []):
            st.caption(f"UUID · {instance['symbol_uuid']} · unit {instance['unit']} · {instance['sheet_path']}")
        st.write("**연결 분석 후보**")
        for candidate in candidates:
            st.caption(f"{candidate.target_ref} · {', '.join(candidate.shared_nets)}")
        st.caption(f"경로 검색 · {path_search.status} · {len(path_search.paths)}개 후보 경로")
        marker = next((row for row in (overlay_payload or {}).get("markers", [])
                       if row.get("component_ref") == component_ref), None)
        if overlay_mode == "연결 후보":
            st.write("**연결 후보 Overlay 근거**")
            if marker:
                st.caption(f"종류 · {marker.get('label')} · evidence {marker.get('evidence_level')}")
                if marker.get("hop_count") is not None:
                    st.caption(f"Hop · {marker['hop_count']} · 공유 Net · {', '.join(marker.get('shared_nets', [])) or '없음'}")
                for path in marker.get("paths", []):
                    st.caption(f"경로 · {' → '.join(path.get('path', []))} · {', '.join(path.get('nets', []))}")
            else:
                st.caption("현재 부품의 연결 후보 Overlay가 없습니다.")
        elif overlay_mode == "전기적 위험":
            st.write("**현재 Simulation Risk 근거**")
            if marker and marker.get("kind") == "RISK":
                st.caption(f"Risk · {marker.get('risk_level')} · 순위 {marker.get('priority_rank', '—')} · 점검 지수 {marker.get('priority_score', '—')} (확률 아님)")
                st.caption(f"주요 Metric · {marker.get('dominant_metric') or '미확인'} · 근거 · {marker.get('evidence_level')}")
                for metric_name, metric in marker.get("metrics", {}).items():
                    st.caption(f"{metric_name} · 상태 {metric.get('status', 'unknown')} · 스트레스 {metric.get('measured_stress', '—')} {metric.get('unit', '')} · 기준 {metric.get('rated_limit', '—')} · 사용률 {metric.get('utilization_ratio', '—')}")
                    source = metric.get("rating_source") or {}
                    if source:
                        st.caption(f"정격 출처 · {source.get('type', 'unknown')} · {source.get('note', '')}")
                if risk_assessment.get("reassessment_source"):
                    st.caption(f"현재 정격 재평가 출처 · {risk_assessment['reassessment_source']}")
            elif overlay_payload and overlay_payload.get("status") == "BLOCKED":
                st.caption(f"Risk 사용 차단 · {overlay_payload.get('reason')}")
            else:
                st.caption("현재 부품에 검증된 Risk 행이 없습니다.")
        elif overlay_mode == "측정·점검":
            st.write("**측정·점검 근거**")
            if measurement_recommendation:
                st.caption(f"추천 Node · {measurement_recommendation.get('node')} · 유형 {measurement_recommendation.get('measurement_type')} ({measurement_recommendation.get('unit')})")
                st.caption(f"출처 · {measurement_source} · 정보 이득 {measurement_recommendation.get('expected_information_gain_nats', '—')} nats · 불확실도 출처 {measurement_recommendation.get('uncertainty_source', 'unknown')}")
                if measurement_anchors and measurement_anchors.anchors:
                    st.caption("논리적 핀 후보 · " + ", ".join(
                        f"{row['component_ref']}.{row['pin']}" for row in measurement_anchors.anchors))
                elif measurement_anchors:
                    st.caption(f"위치 상태 · {measurement_anchors.status} · {measurement_anchors.message}")
            elif not bayesian_supported:
                st.caption("현재 회로/고장 조건에 지원되는 Bayesian 측정 모델이 없습니다.")
            else:
                st.caption("현재 Context에 사용할 수 있는 측정 추천이 없습니다.")
            if svg is None:
                st.caption("회로도 Geometry가 검증되지 않아 화면상의 측정 핀 후보는 없습니다.")
            if diagnosis.get("model_mismatch"):
                st.warning("Model mismatch: 순위와 추천 위치가 차단되었습니다.")
            rank_rows = (inspection_ranking.get("prior_weighted_inspection_order", [])
                         if measurement_source == "prior_only" else
                         inspection_ranking.get("posterior_weighted_inspection_order", []))
            rank_row = next((row for row in rank_rows if row.get("component_ref") == component_ref), None)
            if rank_row:
                score = rank_row.get("posterior_weighted_priority_score",
                                     rank_row.get("prior_weighted_priority_score"))
                st.caption(f"점검 순위 {rank_row.get('priority_rank', '—')} · 점수 {score if score is not None else '—'} (가설 집합 조건부, 손상 확률 아님) · 근거 범위 {rank_row.get('posterior_evidence_coverage', '—')}")
        st.write("**Simulation**")
        st.caption(f"상태 · {simulation_status}")
        st.caption(f"SPICE 검증 · {spice_verification_label(simulation_status, simulation_integrity)}")
        st.caption(f"SVG Export 상태 · {status}")
        st.caption("연결 후보는 손상이나 전기적 위험의 증거가 아닙니다.")
        action_col, report_col = st.columns(2, gap="small")
        if action_col.button("파형 상세", key=f"workbench_waveform_{context_token}", use_container_width=True):
            st.session_state["workbench_navigation_target"] = "SPICE 파형"
            st.rerun()
        if report_col.button("보고서", key=f"workbench_report_{context_token}", use_container_width=True):
            st.session_state["workbench_navigation_target"] = "분석 개요"
            st.rerun()
