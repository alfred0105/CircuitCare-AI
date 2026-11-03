"""Streamlit review workflow for local datasheet rating candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_validator import validate_candidate
from .pdf_loader import DatasheetError, extract_pdf_tables, load_pdf
from .rating_extractor import find_rating_candidates
from .rating_review import save_review, save_application, load_reviews
from .rating_adapter import RatingApplicationError, apply_approved_rating, reassess_existing_risk


def render_datasheet_tab(st: Any, *, root: Path, circuit: Any, context_key: str, case: dict[str, Any],
                         risk: dict[str, Any], stress: dict[str, Any], client: Any,
                         models: list[dict[str, Any]], stress_signature: str | None = None,
                         applied_records: list[dict[str, Any]] | None = None,
                         current_risk: dict[str, Any] | None = None) -> None:
    st.subheader("데이터시트 AI · 근거 확인 후 정격 검토")
    st.caption("로컬 PDF와 loopback Ollama만 사용합니다. AI 제안은 사실이 아니며, PDF 원문·부품 모델·조건을 확인하고 승인하기 전에는 Rating Engine에 적용되지 않습니다.")
    references = list(circuit.components)
    component_ref = st.selectbox("KiCad Reference", references, key=f"ds_ref_{context_key}")
    component = circuit.components[component_ref]
    st.write(f"**선택 부품:** {component_ref} · KiCad Value `{component.value}` · Library `{component.library_id}` · Footprint `{component.footprint or '미기록'}` · KiCad datasheet `{component.datasheet or '미기록'}`")
    left, right = st.columns(2)
    with left:
        manufacturer = st.text_input("제조사", key=f"ds_mfr_{context_key}")
        mpn = st.text_input("Manufacturer Part Number (MPN)", key=f"ds_mpn_{context_key}")
        revision = st.text_input("문서 Revision (선택)", key=f"ds_rev_{context_key}")
        uploaded = st.file_uploader("데이터시트 PDF", type=["pdf"], max_upload_size=25, key=f"ds_pdf_{context_key}")
    with right:
        st.write("현재 활성 SPICE 스트레스와 저장된 위험 결과")
        st.write({"simulation_success": stress.get("simulation_success"),
                  "scenario_id": risk.get("scenario_id"), "risk_available": bool(risk),
                  "active_rating_source": "현재 시나리오 JSON" if risk else "없음"})
        current_rating = next((row for row in risk.get("rating_checks", []) if row.get("component_ref") == component_ref), None)
        if current_rating:
            st.write("현재 설정 정격")
            st.json(current_rating)
        active_for_selected = next((row for row in (applied_records or [])
                                     if row.get("component_ref") == component_ref), None)
        if active_for_selected:
            st.success(f"이 Reference에는 승인 정격이 활성화되어 있습니다 · {active_for_selected['record'].get('manufacturer')} {active_for_selected['record'].get('mpn')} · SHA-256 {active_for_selected['record'].get('source_document_sha256')}")
        st.caption("시뮬레이션 스트레스/파형은 고정된 입력입니다. 승인 정격을 비교할 때 SPICE를 다시 실행하지 않습니다.")
    if uploaded is None:
        st.info('PDF 처리에는 선택 의존성이 필요합니다: `python -m pip install -e ".[datasheet]"`')
        return
    raw_pdf = uploaded.getvalue()
    try:
        document = load_pdf(raw_pdf, uploaded.name)
        document["tables"] = extract_pdf_tables(raw_pdf)
    except DatasheetError as exc:
        st.error(str(exc))
        return
    st.json({"filename": document["filename"], "sha256": document["sha256"], "size_bytes": document["size_bytes"],
             "page_count": document["page_count"], "metadata": document["metadata"],
             "text_status": document["text_status"], "pages_with_text": document["pages_with_text"],
             "tables_found": len(document["tables"]), "manufacturer": manufacturer, "mpn": mpn, "revision": revision})
    if document["text_status"] == "OCR_REQUIRED":
        st.warning("이미지 기반 또는 텍스트가 없는 PDF입니다. OCR을 자동 실행하지 않았습니다. 이 환경의 선택 OCR 기능은 데이터시트 텍스트 추출용으로 구성되지 않아 수동 텍스트 PDF가 필요합니다.")
        return
    model_names = [item.get("name") or item.get("model") for item in models if item.get("name") or item.get("model")]
    model_name = None
    if client and model_names:
        model_name = st.selectbox("로컬 Ollama 모델", model_names, key=f"ds_model_{context_key}_{component_ref}")
    extraction_model = model_name
    model_meta = next((item for item in models if (item.get("name") or item.get("model")) == model_name), {}) if model_name else {}
    model_digest = model_meta.get("digest")
    state_id = ":".join((context_key, component_ref, document["sha256"], manufacturer.strip(), mpn.strip(), revision.strip(), model_name or "rule-only", model_digest or "no-digest", "datasheet-rating-json-v1"))
    state_key = f"datasheet_state_{state_id}"
    if st.session_state.get("datasheet_active_state") != state_id:
        st.session_state["datasheet_active_state"] = state_id
        initial_candidates = find_rating_candidates(document["pages"], document["tables"])
        saved_reviews = load_reviews(root / "data/private/datasheet_ai/review_history.json",
            sha256=document["sha256"], mpn=mpn.strip(), reference=component_ref, revision=revision.strip(),
            extraction_model=extraction_model, model_digest=model_digest)
        reviewed_by_source = {}
        for record in saved_reviews:
            original = record.get("original_candidate") or record
            reviewed_by_source[(original.get("rating_key"), original.get("pdf_page_index"), original.get("source_text"))] = record
        initial_review_state = {}
        for index, candidate in enumerate(initial_candidates):
            match = reviewed_by_source.get((candidate.get("rating_key"), candidate.get("pdf_page_index"), candidate.get("source_text")))
            if match:
                initial_review_state[str(index)] = match
        st.session_state[state_key] = {"document": document, "candidates": initial_candidates,
                                       "llm": None, "reviews": initial_review_state}
    ds_state = st.session_state[state_key]
    candidates = ds_state["candidates"]
    if not candidates:
        st.warning("지원되는 Voltage / Current / Power 정격 후보가 규칙 탐색에서 발견되지 않았습니다. 정격을 임의 생성하지 않습니다.")
    else:
        st.write("로컬 LLM 제안 — 아직 승인되지 않음" if any(row.get("extraction_method") == "local_ollama" for row in candidates)
                 else "규칙 기반 후보 — 아직 승인되지 않음")
        st.dataframe([{"정격": row["rating_type"], "값": row["raw_value"], "종류": row["rating_kind"],
                       "페이지(0부터)": row["pdf_page_index"], "근거": row["source_text"],
                       "표 행·열 문맥": row.get("table_context")} for row in candidates], hide_index=True)
    if client and models and model_name:
        if st.button("로컬 LLM으로 정격 구조화", disabled=not candidates, key=f"ds_extract_{context_key}"):
            try:
                from .llm_extractor import extract_with_local_llm
                with st.spinner("PDF에서 후보가 발견된 페이지만 로컬 LLM으로 분석 중…"):
                    ds_state["llm"] = extract_with_local_llm(client, model_name, manufacturer=manufacturer, mpn=mpn,
                                                             candidates=candidates, pages=document["pages"],
                                                             tables=document["tables"])
                llm_rows = ds_state["llm"]["ratings"]
                ds_state["candidates"] = [_attach_document(validate_candidate({**row, "source_document_sha256": document["sha256"]}, document["pages"],
                                                                                manufacturer=manufacturer, mpn=mpn), document)
                                           for row in llm_rows]
                for row in ds_state["candidates"]:
                    row["llm_model"] = ds_state["llm"].get("model")
                    row["llm_model_info"] = ds_state["llm"].get("model_info")
                    row["llm_model_digest"] = (ds_state["llm"].get("model_info") or {}).get("digest")
                    row["llm_total_duration_ns"] = ds_state["llm"].get("total_duration_ns")
                    row["extraction_prompt_version"] = "datasheet-rating-json-v1"
                saved_reviews = load_reviews(root / "data/private/datasheet_ai/review_history.json",
                    sha256=document["sha256"], mpn=mpn.strip(), reference=component_ref,
                    revision=revision.strip(), extraction_model=ds_state["llm"].get("model"),
                    model_digest=(ds_state["llm"].get("model_info") or {}).get("digest"))
                reviewed_by_source = {}
                for record in saved_reviews:
                    original = record.get("original_candidate") or record
                    reviewed_by_source[(original.get("rating_key"), original.get("pdf_page_index"), original.get("source_text"))] = record
                ds_state["reviews"] = {str(index): reviewed_by_source[(row.get("rating_key"), row.get("pdf_page_index"), row.get("source_text"))]
                    for index, row in enumerate(ds_state["candidates"])
                    if (row.get("rating_key"), row.get("pdf_page_index"), row.get("source_text")) in reviewed_by_source}
                st.rerun()
            except Exception as exc:
                st.error(f"로컬 LLM 추출 실패 · 기존 규칙 후보는 유지됩니다: {exc}")
        if ds_state.get("llm"):
            st.caption(f"로컬 Ollama 모델: {ds_state['llm'].get('model')} · 처리시간 ns: {ds_state['llm'].get('total_duration_ns')}")
    else:
        st.info("Ollama가 연결되지 않았거나 모델이 없습니다. 규칙 후보와 수동 검토 기능은 계속 사용할 수 있습니다.")
    candidates = ds_state["candidates"]
    if not candidates:
        return
    labels = [f"{row['rating_type']} · {row['raw_value']} · p.{row['pdf_page_index'] + 1} · {row.get('extraction_method')}" for row in candidates]
    selected_index = st.selectbox("검토할 정격 후보", range(len(candidates)), format_func=lambda index: labels[index], key=f"ds_candidate_{state_id}")
    selected = candidates[selected_index]
    source_page = document["pages"][selected["pdf_page_index"]]
    st.markdown("**PDF 페이지 원문 (일부)**")
    st.code(source_page["text"][:12000] or "텍스트가 없습니다.")
    with st.expander("표 추출 결과 (행/열 보존)"):
        page_tables = [table for table in document["tables"] if table["page_index"] == selected["pdf_page_index"]]
        if page_tables:
            for table in page_tables:
                st.caption(f"페이지 {table['page_index'] + 1} · 표 {table['table_index'] + 1}")
                st.dataframe(table["rows"], hide_index=True)
        else:
            st.info("이 페이지에서 표를 찾지 못했습니다. 문장 기반 후보만 검토하세요.")
    source_status = selected.get("evidence_status")
    st.write({"evidence_status": source_status or "PENDING_REVIEW", "raw_value": selected.get("raw_value"),
              "normalized_value": selected.get("normalized_value"), "normalized_unit": selected.get("normalized_unit"),
              "rating_kind": selected.get("rating_kind"), "conditions": selected.get("conditions"),
              "source_text": selected.get("source_text"), "source_page_index": selected.get("pdf_page_index"),
              "manufacturer": manufacturer, "mpn": mpn, "revision": revision,
              "llm_model": (ds_state.get("llm") or {}).get("model") if selected.get("extraction_method") == "local_ollama" else None})
    if selected.get("table_context"):
        st.caption("표 기반 후보는 숫자 인용뿐 아니라 동일 표의 행·열·부품 모델 문맥을 함께 검토합니다.")
        st.json({"table_context": selected["table_context"]})
    if selected.get("evidence_status") in {None, "PENDING_REVIEW"}:
        selected = _attach_document(validate_candidate({**selected, "source_document_sha256": document["sha256"]}, document["pages"],
                                                       manufacturer=manufacturer, mpn=mpn), document)
        candidates[selected_index] = selected
        source_status = selected["evidence_status"]
        st.warning(f"근거 검사 상태: {source_status} · {', '.join(selected.get('match_notes', [])) or '페이지 원문과 값/단위 일치'}")
    else:
        st.info(f"근거 검사 상태: {source_status} · {', '.join(selected.get('match_notes', [])) or '페이지 원문과 값/단위 일치'}")
    component_match = st.checkbox(f"이 PDF의 제조사 모델 {mpn or '(MPN 입력 필요)'}가 실제 {component_ref} 부품이라는 점을 확인했습니다.",
                                  key=f"ds_match_{state_id}")
    conditions_fit = st.checkbox("데이터시트 적용 조건(온도/연속·펄스/전압 기준)이 현재 회로와 시뮬레이션 조건에 적합함을 확인했습니다.",
                                  key=f"ds_conditions_{state_id}")
    condition_note = st.text_area("조건 검토 메모 (문서에 명시되지 않은 조건을 적용할 때 근거를 기록)", key=f"ds_condition_note_{state_id}")
    source_text = st.text_area("원문 인용 수정 (수정하면 출처 일치 상태가 다시 확인되어야 함)", value=selected.get("source_text", ""), key=f"ds_evidence_{state_id}_{selected_index}")
    unit_options = {"max_abs_voltage_v": ["V", "mV", "kV"], "max_current_a": ["A", "mA", "µA"],
                    "max_power_w": ["W", "mW", "µW"]}[selected["rating_key"]]
    unit_scale = {"V": 1.0, "mV": 1e-3, "kV": 1e3, "A": 1.0, "mA": 1e-3, "µA": 1e-6,
                  "W": 1.0, "mW": 1e-3, "µW": 1e-6}
    default_unit = selected["normalized_unit"]
    display_value = float(selected["normalized_value"]) / unit_scale[default_unit]
    edit_cols = st.columns(3)
    unit = edit_cols[0].selectbox("검토 단위", unit_options, index=unit_options.index(default_unit), key=f"ds_unit_{state_id}_{selected_index}")
    value = edit_cols[1].number_input("검토 수치", min_value=0.000000001, value=display_value, format="%.9g", key=f"ds_value_{state_id}_{selected_index}")
    rating_kind = edit_cols[2].selectbox("정격 적용 종류", ["continuous", "peak", "absolute_max", "unknown"],
        index=["continuous", "peak", "absolute_max", "unknown"].index(selected.get("rating_kind") if selected.get("rating_kind") in {"continuous", "peak", "absolute_max", "unknown"} else "unknown"),
        key=f"ds_kind_{state_id}_{selected_index}")
    review_cols = st.columns(3)
    if review_cols[0].button("승인 기록", key=f"ds_approve_{state_id}_{selected_index}"):
        revised = {**selected, "source_text": source_text, "raw_value": f"{value:g} {unit}",
                   "normalized_value": float(value) * unit_scale[unit], "normalized_unit": unit_options[0],
                   "rating_kind": rating_kind, "rating_kind_source": "user_reviewed",
                   "condition_review_note": condition_note.strip(),
                   "source_document_sha256": document["sha256"],
                   "manufacturer": manufacturer.strip(), "mpn": mpn.strip(), "component_reference": component_ref,
                   "document_revision": revision.strip(), "human_approved": True, "review_decision": "approved",
                   "mpn_match_status": "MPN_CONFIRMED" if _mpn_in_pdf(mpn, document) else ("USER_ASSERTED_PART_MATCH" if component_match else "PART_MATCH_UNCERTAIN"),
                   "conditions_compatible_user_confirmed": conditions_fit}
        revised = validate_candidate(revised, document["pages"], manufacturer=manufacturer, mpn=mpn)
        if not revised["manufacturer"] or not revised["mpn"]:
            st.error("제조사와 실제 제조사 MPN을 입력해야 합니다.")
        elif revised["evidence_status"] not in {"SOURCE_MATCHED", "CONDITION_INCOMPLETE"}:
            st.error("원문/수정값 검증 상태가 승인 가능한 값이 아닙니다. 적용을 막았습니다.")
        elif revised["evidence_status"] == "CONDITION_INCOMPLETE" and not revised.get("condition_review_note"):
            st.error("문서에 적용 조건이 충분히 나오지 않습니다. 근거가 있는 조건 검토 메모를 먼저 작성하세요.")
        elif not component_match:
            st.error("KiCad Reference와 실제 MPN의 일치 확인이 필요합니다.")
        else:
            saved = save_review({**revised, "decision": "approved"}, root / "data/private/datasheet_ai/review_history.json")
            ds_state.setdefault("reviews", {})[str(selected_index)] = saved
            st.success("사용자 승인 이력을 로컬에 기록했습니다. 아직 적용 전입니다.")
    if review_cols[1].button("거절 기록", key=f"ds_reject_{state_id}_{selected_index}"):
        saved = save_review({**selected, "component_reference": component_ref, "manufacturer": manufacturer,
                             "mpn": mpn, "source_document_sha256": document["sha256"], "decision": "rejected"},
                            root / "data/private/datasheet_ai/review_history.json")
        ds_state.setdefault("reviews", {})[str(selected_index)] = saved
        st.warning("거절 이력을 기록했습니다.")
    if review_cols[2].button("문서 미검증 수동 입력으로 보관", key=f"ds_manual_{state_id}_{selected_index}"):
        manual = {**selected, "component_reference": component_ref, "manufacturer": manufacturer.strip(),
                  "mpn": mpn.strip(), "source_document_sha256": document["sha256"],
                   "original_candidate": {key: selected.get(key) for key in ("rating_key", "rating_type", "rating_kind", "normalized_value", "normalized_unit", "source_text", "table_context", "pdf_page_index")},
                  "raw_value": f"{value:g} {unit}", "normalized_value": float(value) * unit_scale[unit],
                  "normalized_unit": unit_options[0], "rating_kind": rating_kind,
                  "decision": "manual_input", "extraction_status": "manual_user_input",
                  "evidence_status": source_status, "human_approved": False,
                  "record_note": "User-entered/edited value is not verified as a datasheet fact and cannot be applied by the datasheet adapter."}
        save_review(manual, root / "data/private/datasheet_ai/review_history.json")
        st.info("비검증 수동 입력 이력을 별도로 저장했습니다. 데이터시트 정격으로 표시하거나 기존 위험도에 적용하지 않았습니다.")
    approved = ds_state.get("reviews", {}).get(str(selected_index))
    if approved and approved.get("decision") == "approved":
        if not risk or not stress:
            st.warning("현재 선택한 시나리오에 SPICE 스트레스/위험 결과가 없어 재평가할 수 없습니다.")
        elif st.button("승인 정격 적용 및 위험 재평가", key=f"ds_apply_{state_id}_{selected_index}"):
            try:
                applied_specs = apply_approved_rating(_specs_for_case(root, case), approved, component_ref=component_ref,
                    selected_reference=component_ref, mpn_match_status=approved.get("mpn_match_status", "PART_MATCH_UNCERTAIN"),
                    conditions_compatible=conditions_fit)
                applied_risk = reassess_existing_risk(risk, stress, applied_specs, _mapping_for_case(root, case))
                save_application({"record": approved, "conditions_compatible": conditions_fit,
                                  "component_ref": component_ref, "stress_signature": stress_signature,
                                  "circuit_path": case["netlist"], "scenario_id": risk.get("scenario_id")},
                                 root / "data/private/datasheet_ai/applied_ratings.json")
                st.session_state.pop(f"datasheet_applied_{context_key}", None)
                st.success("기존 SPICE 결과를 재사용해 Rating Engine을 다시 계산했습니다. SPICE 재실행은 하지 않았습니다.")
                st.rerun()
            except RatingApplicationError as exc:
                st.error(str(exc))
    active = current_risk
    if active:
        st.subheader("변경 전 / 현재 활성 평가")
        old = _risk_row(risk, component_ref)
        new = _risk_row(active, component_ref)
        st.dataframe([_comparison_row("기존 정격", old), _comparison_row("승인 데이터시트 정격", new)], hide_index=True)
        st.caption("정격의 출처·조건만 재평가합니다. 파형, SPICE 스트레스, 측정값, PCB 좌표/검출 상자는 변경하지 않습니다.")
        st.write({"이전 등급": old.get("risk_level"), "현재 등급": new.get("risk_level"),
                  "이전 점수 / 순위": [old.get("priority_score"), old.get("priority_rank")],
                  "현재 점수 / 순위": [new.get("priority_score"), new.get("priority_rank")],
                  "점수 의미": "결정론적 점검 우선순위 지수이며 손상 확률이 아닙니다."})
        if active.get("reassessment_source"):
            st.json({"reassessment_source": active["reassessment_source"], "simulation_rerun": active.get("simulation_rerun"),
                     "rating_check": next((row for row in active.get("rating_checks", []) if row.get("component_ref") == component_ref), None)})
            if st.button("승인 정격 적용 해제", key=f"ds_unapply_{state_id}_{component_ref}"):
                save_application({"event": "revoked", "component_ref": component_ref,
                                  "circuit_path": case["netlist"], "scenario_id": active.get("scenario_id"),
                                  "stress_signature": stress_signature},
                                 root / "data/private/datasheet_ai/applied_ratings.json")
                st.session_state.pop(f"datasheet_applied_{context_key}", None)
                st.rerun()


def _attach_document(candidate: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    candidate["source_document_sha256"] = document["sha256"]
    return candidate


def _mpn_in_pdf(mpn: str, document: dict[str, Any]) -> bool:
    return bool(mpn.strip()) and any(mpn.casefold() in page["text"].casefold() for page in document["pages"])


def _specs_for_case(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    return json.loads((root / case["ratings"]).read_text(encoding="utf-8"))


def _mapping_for_case(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    return json.loads((root / case["mapping"]).read_text(encoding="utf-8"))


def _risk_row(report: dict[str, Any], reference: str) -> dict[str, Any]:
    if not report:
        return {"component_ref": reference, "risk_level": "UNKNOWN", "priority_rank": None, "priority_score": None, "dominant_metric": None}
    return next((row for row in report.get("secondary_candidates", []) if row.get("component_ref") == reference),
                {"component_ref": reference, "risk_level": "UNKNOWN", "priority_rank": None, "priority_score": None, "dominant_metric": None})


def _comparison_row(label: str, row: dict[str, Any]) -> dict[str, Any]:
    metric = {"voltage": "max_abs_voltage_v", "current": "max_current_a", "power": "max_power_w"}.get(row.get("dominant_metric"))
    values = row.get("metrics", {}).get(metric, {}) if metric else {}
    return {"평가": label, "등급": row.get("risk_level"), "사용률": values.get("utilization_ratio"),
            "정격": values.get("rated_limit"), "단위": values.get("unit"), "점수": row.get("priority_score"),
            "순위": row.get("priority_rank"), "정격 출처": (values.get("rating_source") or {}).get("type")}
