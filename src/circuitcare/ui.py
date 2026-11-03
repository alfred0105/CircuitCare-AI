"""Local Streamlit dashboard joining the existing CircuitCare analysis stages."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from circuitcare.conversation import answer_question
from circuitcare.datasheet.datasheet_ui import render_datasheet_tab
from circuitcare.datasheet.rating_adapter import apply_approved_rating, reassess_existing_risk
from circuitcare.datasheet.rating_review import find_applications
from circuitcare.diagnosis_ai import run_diagnosis
from circuitcare.evidence_builder import build_evidence
from circuitcare.graph import build_graph, direct_candidates, find_paths, to_dot
from circuitcare.local_llm import LocalLLMError, OllamaClient
from circuitcare.netlist import load_netlist
from circuitcare.repair_advisor import build_repair_advice


ROOT = Path(__file__).resolve().parents[2]
DEMO_HYPOTHESES = ROOT / "data/diagnosis/demo_hypotheses.json"
MEASUREMENTS = ROOT / "data/diagnosis/demo_measurements.json"
CASES = {
    "Regulator + divider + switch (cached demo)": {
        "netlist": "tests/fixtures/fault_demo_netlist.xml", "fault": "U1", "fault_type": "regulator_output_rise", "value": "8",
        "fault_types": ["regulator_output_rise", "regulator_output_drop"],
        "base": "data/circuits/fault_demo.cir", "mapping": "data/circuits/fault_demo_mapping.json", "probes": "data/circuits/fault_demo_probes.json", "ratings": "data/component_specs/fault_demo_ratings.json",
        "cached": "data/fault_scenarios/overvoltage_demo/simulation_results/fault_u1_regulator_output_rise", "prior": "data/diagnosis/prior_results",
    },
    "Independent resistor divider (evaluation circuit A)": {
        "netlist": "tests/fixtures/divider_netlist.xml", "fault": "R1", "fault_type": "resistance_drift", "value": "10k",
        "fault_types": ["resistance_drift", "resistor_open", "resistor_short"],
        "base": "data/circuits/divider.cir", "mapping": "data/circuits/divider_mapping.json", "probes": "data/circuits/divider_probes.json", "ratings": "data/component_specs/divider_ratings.json",
        "cached": "data/evaluations/divider/simulation_results/fault_r1_resistance_drift", "prior": None,
    },
    "Independent RC charging circuit (evaluation circuit B)": {
        "netlist": "tests/fixtures/rc_netlist.xml", "fault": "RCHARGE", "fault_type": "resistance_drift", "value": "100k",
        "fault_types": ["resistance_drift", "resistor_open", "resistor_short"],
        "base": "data/circuits/rc_charge.cir", "mapping": "data/circuits/rc_charge_mapping.json", "probes": "data/circuits/rc_charge_probes.json", "ratings": "data/component_specs/rc_charge_ratings.json",
        "cached": "data/evaluations/rc_charge/simulation_results/fault_rcharge_resistance_drift", "prior": None,
    },
}


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="CircuitCare AI", page_icon="🔧", layout="wide")
    st.title("CircuitCare AI")
    st.caption("로컬 회로 고장 영향 분석 · 정격 스트레스 평가 · Bayesian 진단 · 근거 기반 수리 지원")
    st.info("연결 그래프는 후보 경로만 나타냅니다. 시뮬레이션은 손상을 확정하지 않으며, 위험 순위와 Posterior는 실제 고장 확률이 아닙니다.")

    case_name = st.sidebar.selectbox("회로 데이터셋", list(CASES), key="case_name")
    case = CASES[case_name]
    netlist_path = ROOT / case["netlist"]
    circuit = load_netlist(netlist_path)
    fault_options = {
        "Regulator + divider + switch (cached demo)": ["U1"],
        "Independent resistor divider (evaluation circuit A)": ["R1", "R2"],
        "Independent RC charging circuit (evaluation circuit B)": ["RCHARGE", "RBLEED"],
    }[case_name]
    selected_fault = st.sidebar.selectbox("고장 부품", fault_options, index=fault_options.index(case["fault"]) if case["fault"] in fault_options else 0)
    fault_type = st.sidebar.selectbox("고장 유형", case["fault_types"], index=case["fault_types"].index(case["fault_type"]), key=f"fault_type_{case_name}")
    needs_value = fault_type in {"resistance_drift", "regulator_output_rise", "regulator_output_drop"}
    fault_value = st.sidebar.text_input("고장 파라미터 (SPICE 숫자 표기)", value=case["value"] if fault_type == case["fault_type"] else ("10k" if fault_type == "resistance_drift" else "8"), disabled=not needs_value, key=f"fault_value_{case_name}_{fault_type}")
    context_key = _analysis_context_key(case_name, case, selected_fault, fault_type, fault_value if needs_value else None)
    bayesian_supported = _supports_bayesian_demo(case_name, selected_fault, fault_type, fault_value if needs_value else None)
    if st.session_state.get("analysis_context_key") != context_key:
        for key in list(st.session_state):
            if key.startswith("what_if_voltage_"):
                st.session_state.pop(key, None)
        for key in ("live_result_dir", "diagnosis_result", "measurements", "last_advisor", "live_error",
                    "what_if_result", "what_if_result_key", "what_if_measurements", "what_if_context_key",
                    "what_if_node", "what_if_voltage", "what_if_sigma"):
            st.session_state.pop(key, None)
        st.session_state.analysis_context_key = context_key
        st.session_state.measurements = []
    st.sidebar.caption(f"선택한 고장 모델: {fault_type} · 파라미터: {fault_value if needs_value else '해당 없음'}")
    st.sidebar.caption("시연 데이터는 저장된 결과이며, 새 시뮬레이션은 버튼을 눌렀을 때만 실행합니다.")

    run_col, state_col = st.sidebar.columns(2)
    state_display = state_col.empty()
    run_live = run_col.button("ngspice 실행", disabled=not _command_exists("ngspice"), use_container_width=True)
    live_matches = bool(st.session_state.get("live_result_dir")) and st.session_state.get("live_context_key") == context_key
    if not live_matches:
        st.session_state.pop("live_result_dir", None)
        live_used = False
        if selected_fault == case["fault"] and fault_type == case["fault_type"] and fault_value == case["value"]:
            result_dir = ROOT / case["cached"]
        else:
            result_dir = ROOT / "data/no_cached_results" / case_name.replace(" ", "_") / selected_fault
    else:
        result_dir = Path(st.session_state["live_result_dir"])
        live_used = True
    if run_live:
        if needs_value and not _valid_parameter(fault_value):
            st.sidebar.error("파라미터는 양수 숫자 또는 10k 같은 SPICE 숫자 표기만 허용합니다.")
            st.stop()
        state_display.markdown("🟡 RUNNING")
        st.session_state.simulation_status = "RUNNING"
        st.session_state.pop("live_result_dir", None)
        st.session_state.pop("live_context_key", None)
        st.session_state.pop("last_advisor", None)
        for key in list(st.session_state):
            if key.startswith("what_if_voltage_"):
                st.session_state.pop(key, None)
        for key in ("what_if_result", "what_if_result_key", "what_if_measurements", "what_if_context_key",
                    "what_if_voltage", "what_if_node", "what_if_sigma"):
            st.session_state.pop(key, None)
        live_used = False
        result_dir = ROOT / case["cached"] if _is_cached_case(case, selected_fault, fault_type, fault_value, needs_value) else ROOT / "data/no_cached_results" / case_name.replace(" ", "_") / selected_fault
        slug = {"U1": "regulator_8v", "R1": "divider_r1_drift", "RCHARGE": "rc_rcharge_drift"}.get(selected_fault, "scenario")
        output = ROOT / "data/ui_runs" / f"{slug}-{time.time_ns()}"
        cmd = [sys.executable, "-m", "circuitcare.cli", "--netlist", str(netlist_path), "--fault", selected_fault,
               "--fault-type", fault_type, "--spice-base", str(ROOT / case["base"]),
               "--spice-mapping", str(ROOT / case["mapping"]), "--output", str(output), "--simulate", "--probes", str(ROOT / case["probes"]),
               "--ratings", str(ROOT / case["ratings"]), "--assess-risk"]
        if needs_value:
            cmd.extend(["--fault-value", fault_value])
        with st.spinner("Fault Injection → ngspice → stress/rating assessment 실행 중…"):
            try:
                completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
                result_dir = _validate_live_result(completed, output, selected_fault, fault_type)
                st.session_state.live_result_dir = str(result_dir)
                st.session_state.live_context_key = context_key
                st.session_state.pop("live_error", None)
                st.session_state.pop("last_advisor", None)
                st.session_state.simulation_status = "SUCCESS"
                st.success("새 시뮬레이션 완료")
                st.rerun()
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                details = str(exc)
                if isinstance(exc, SimulationRunError):
                    details = exc.details
                st.session_state.live_error = details
                st.session_state.simulation_status = "FAILED"
                live_used = False
                st.error(f"시뮬레이션 실패 · 성공 결과로 등록하지 않았습니다.\n\n{details}")
    comparison_path = result_dir / "comparison.json"
    risk_path = result_dir / "risk_assessment.json"
    stress_path = result_dir / "component_stress.json"
    comparison = _json_if_exists(comparison_path)
    risk = _json_if_exists(risk_path)
    stress = _json_if_exists(stress_path)
    base_risk = risk
    component_mapping = _json_if_exists(ROOT / case["mapping"])
    stress_signature = hashlib.sha256(stress_path.read_bytes()).hexdigest() if stress_path.is_file() else None
    applied_key = f"datasheet_applied_{context_key}"
    applied_ratings = st.session_state.get(applied_key)
    if applied_ratings is None and stress_signature and risk.get("scenario_id"):
        applied_ratings = find_applications(ROOT / "data/private/datasheet_ai/applied_ratings.json",
            circuit_path=case["netlist"], scenario_id=risk["scenario_id"], stress_sha256=stress_signature)
        if applied_ratings:
            st.session_state[applied_key] = applied_ratings
    if applied_ratings and risk and stress:
        try:
            applied_specs = json.loads((ROOT / case["ratings"]).read_text(encoding="utf-8"))
            for application in applied_ratings:
                record = application["record"]
                applied_specs = apply_approved_rating(applied_specs, record,
                    component_ref=application["component_ref"], selected_reference=application["component_ref"],
                    mpn_match_status=record["mpn_match_status"], conditions_compatible=application["conditions_compatible"])
            risk = reassess_existing_risk(risk, stress, applied_specs, component_mapping)
        except (OSError, ValueError, KeyError, TypeError):
            st.session_state.pop(f"datasheet_applied_{context_key}", None)
    is_cached_selection = _is_cached_case(case, selected_fault, fault_type, fault_value, needs_value)
    status = _simulation_status(live_used, st.session_state.get("live_error"), is_cached_selection)
    if status != "RUNNING":
        st.session_state.simulation_status = status
        state_display.markdown({
            "SUCCESS": "🟢 SUCCESS · Live Simulation",
            "FAILED": "🔴 FAILED" + (" · Cached fallback" if is_cached_selection else ""),
            "CACHED": "🔵 CACHED · 저장된 시연 결과",
            "NOT_RUN": "⚪ NOT_RUN · 분석 준비 · 미실행",
        }[status])
    st.sidebar.markdown("🟢 ngspice 사용 가능" if _command_exists("ngspice") else "🟠 ngspice 없음 · 저장 결과 조회 가능")
    client, models = _ollama_models()
    st.sidebar.markdown("🟢 Local LLM" if client else "🟡 Deterministic Fallback · Ollama 연결 불가")

    tabs = st.tabs(["분석 개요", "회로 및 고장", "SPICE 파형", "2차 손상 위험", "Bayesian 진단", "로컬 LLM 수리 지원", "PCB 사진 인식", "데이터시트 AI", "AI 고장 가설 분석", "수리 이력 및 AI 학습", "AI 성능 평가"])
    with tabs[0]:
        what_if_result = _render_analysis_overview(
            st, circuit=circuit, case_name=case_name, case=case, context_key=context_key,
            failed_component=selected_fault, fault_type=fault_type, fault_value=fault_value,
            risk=risk, comparison=comparison, status=status, bayesian_supported=bayesian_supported,
        )
    with tabs[1]:
        st.subheader("회로 및 고장 설정")
        st.write(f"**선택 회로:** {case_name}  ·  **고장 후보:** {selected_fault} / {fault_type} = {fault_value if needs_value else '—'}")
        candidates = direct_candidates(circuit, selected_fault)
        paths = find_paths(circuit, selected_fault, max_hops=2)
        graph = build_graph(circuit)
        st.graphviz_chart(to_dot(graph, selected_fault, paths), use_container_width=True)
        ref = st.selectbox("부품 연결 정보", list(circuit.components), key="component_detail")
        st.json({"component": next(vars(item) for item in circuit.components.values() if item.ref == ref),
                 "connections": [{"pin": item.pin, "net": item.net} for item in circuit.connections if item.ref == ref],
                 "direct_candidates": [{"reference": item.target_ref, "shared_nets": item.shared_nets, "evidence": item.evidence_level} for item in candidates],
                 "path_candidate_count": len(paths), "graph_note": "연결 기반 후보 경로이며 손상 전파/실제 손상을 증명하지 않습니다."})
        if not case.get("mapping") or not (ROOT / case["mapping"]).is_file():
            st.warning("KiCad XML만 확인 가능합니다. 명시적 SPICE mapping/model이 없어 물리 시뮬레이션을 지원하지 않습니다.")
        st.caption(f"넷리스트: `{case['netlist']}` · 파형/위험 데이터 출처: `{comparison_path.relative_to(ROOT) if comparison_path.exists() else case['cached']}`")

    with tabs[2]:
        st.subheader("정상 / 고장 SPICE 전압 비교")
        if comparison and comparison.get("simulation_success"):
            nodes = list(comparison.get("voltage_nodes", {}))
            if nodes:
                node = st.selectbox("전압 노드", nodes)
                csv_path = result_dir / "comparison.csv"
                rows = _csv_rows(csv_path)
                baseline_key, fault_key = f"baseline_V({node})_V", f"fault_V({node})_V"
                if rows and baseline_key in rows[0] and fault_key in rows[0]:
                    import pandas as pd
                    st.line_chart(pd.DataFrame({"시간 (s)": [float(row["time_s"]) for row in rows], "정상 (V)": [float(row[baseline_key]) for row in rows], "고장 (V)": [float(row[fault_key]) for row in rows]}).set_index("시간 (s)"))
                stats = comparison["voltage_nodes"][node]
                cols = st.columns(4)
                cols[0].metric("정상 마지막 전압", f"{stats['baseline']['last']:.4g} V")
                cols[1].metric("고장 마지막 전압", f"{stats['fault']['last']:.4g} V")
                cols[2].metric("전압 변화", f"{stats['delta_fault_minus_baseline']['last']:+.4g} V")
                cols[3].metric("샘플 수", str(comparison.get("time_range_s", {}).get("samples", "—")))
            else:
                st.warning("비교 가능한 전압 노드가 없습니다.")
            if stress:
                st.caption("지원되는 부품 전류·전력 변화 (없거나 미지원인 값은 —)")
                st.dataframe(_stress_table(stress), use_container_width=True, hide_index=True)
        else:
            st.warning("저장된 비교 결과가 없습니다. 명시적 SPICE 모델/매핑이 준비되지 않으면 이 단계는 지원되지 않습니다.")

    with tabs[3]:
        st.subheader("2차 스트레스 및 정격 비교")
        if risk:
            st.caption("EXCEEDED / NEAR_LIMIT는 설정 정격과 계산 스트레스 비교입니다. WITHIN_LIMIT는 평가한 정격 항목 한정이며 부품 정상 상태나 실제 손상을 뜻하지 않습니다. UNKNOWN은 안전 판정이 아닙니다.")
            st.dataframe(_risk_table(risk), use_container_width=True, hide_index=True)
            st.caption("점수는 점검 우선순위 지표(확률 아님). 정격 출처는 evidence note를 펼쳐 확인하세요.")
            with st.expander("위험 보고서 JSON"):
                st.json(risk)
        else:
            st.info("이 회로에는 위험 평가 결과가 저장되어 있지 않습니다.")

    with tabs[4]:
        st.subheader("Bayesian 진단")
        if bayesian_supported:
            st.caption("저장된 U1 3/6/8 V 시나리오 Bayesian 데모입니다. 현재 ngspice 실행에서 계산한 진단 결과와는 별도로 표시합니다. 가상 측정은 simulated_demo로 구분됩니다.")
            measurements = st.session_state.setdefault("measurements", [])
            current = st.session_state.get("diagnosis_result") or (_run_diagnosis(measurements) if measurements else _load_diagnosis(case))
            if st.button("저장된 7.9 V simulated_demo 측정으로 예시 갱신"):
                with MEASUREMENTS.open(encoding="utf-8") as handle:
                    sample = json.load(handle)["measurements"][0]
                measurements = _upsert_measurement(measurements, sample)
                st.session_state.measurements = measurements
                current = _run_diagnosis(measurements)
                st.session_state.diagnosis_result = current
                st.session_state.pop("last_advisor", None)
            with st.form("measurement_form"):
                node = st.selectbox("측정 노드", current["diagnosis"].get("available_measurement_nodes", []), index=0)
                value = st.number_input("측정 전압 (V)", value=7.9, format="%.4f")
                uncertainty = st.number_input("불확실도 σ (V)", min_value=0.0001, value=0.2, format="%.4f")
                source = st.selectbox("출처", ["user_measurement", "simulated_demo"], help="실제 계측값을 직접 입력한 경우에만 user_measurement를 선택하세요.")
                submitted = st.form_submit_button("측정 추가 후 재계산")
            if submitted:
                measurements = _upsert_measurement(measurements, {"node": node, "value": value, "unit": "V", "uncertainty": uncertainty, "source": source})
                st.session_state.measurements = measurements
                current = _run_diagnosis(measurements)
                st.session_state.diagnosis_result = current
                st.session_state.pop("last_advisor", None)
            if measurements:
                st.caption("같은 노드를 다시 입력하면 기존 값을 교체합니다.")
                st.dataframe(measurements, use_container_width=True, hide_index=True)
            if st.button("측정값 초기화"):
                measurements = []
                st.session_state.measurements = []
                current = _run_diagnosis([])
                st.session_state.diagnosis_result = current
                st.session_state.pop("last_advisor", None)
            diagnosis = current["diagnosis"]
            if diagnosis.get("model_mismatch"):
                st.error("Model mismatch: 현재 측정값을 설정된 시뮬레이션 가설이 설명하지 못합니다. 최상위 posterior를 확정 진단으로 해석하지 마세요.")
            posterior_rows = diagnosis.get("posterior", [])
            st.dataframe([{ "가설": row["hypothesis_id"], "부품": row["component_ref"], "Prior weight": row["prior_weight"], "Posterior (conditional)": row["posterior"], "측정 출처": ", ".join(sorted({item.get("source", "") for item in diagnosis.get("used_measurements", [])})) or "측정 전"} for row in posterior_rows], use_container_width=True, hide_index=True)
            if diagnosis.get("top_hypothesis", {}).get("posterior") == 1.0:
                st.warning("Posterior 1.0은 현재 가설 집합과 측정 모델에 조건부인 값이며 실제 고장 확률 100%를 의미하지 않습니다.")
            rec = current["recommendations"].get("recommended_measurement")
            st.write("**다음 정보량 기반 측정 후보:**", rec.get("node") if rec else current["recommendations"].get("recommendation_status", "없음"))
            st.caption("추천 없음은 추가 점검이 불필요하다는 뜻이 아닙니다. 측정 안전성 승인이 아닙니다.")
            with st.expander("진단 JSON"):
                st.json(diagnosis)
        else:
            st.info("이 회로에 연결된 Bayesian 가설 모델이 없습니다. U1 3/6/8 V 시나리오가 준비된 기본 데모에서만 Bayesian 갱신을 활성화합니다.")

    with tabs[5]:
        st.subheader("로컬 LLM 수리 지원")
        if client and models:
            names = [item.get("name") for item in models if item.get("name")]
            selected_model = st.selectbox("설치된 로컬 모델", names, index=names.index("gemma4:12b") if "gemma4:12b" in names else 0)
            st.caption("질문을 제출할 때만 로컬 모델을 호출합니다. 추론 중 다른 분석 단계는 다시 실행하지 않습니다.")
        else:
            selected_model = None
            st.warning("Ollama를 사용할 수 없습니다. 결정론적 점검 안내와 분석 결과는 계속 사용할 수 있습니다.")
        with st.form("chat_form"):
            question = st.text_input("회로에 대해 질문", placeholder="C1을 왜 먼저 점검해야 해?")
            # Keep submit enabled: Streamlit form values are not synchronized to
            # Python until submission, so dynamically disabling this button
            # based on the text input would make the form impossible to submit.
            ask = st.form_submit_button("질문 제출")
        if ask:
            diagnosis, inspection, recommendations = _advisor_inputs(case) if bayesian_supported else ({}, {}, {})
            active_diagnosis = st.session_state.get("diagnosis_result")
            if active_diagnosis and bayesian_supported:
                diagnosis, inspection, recommendations = active_diagnosis["diagnosis"], active_diagnosis["inspection_ranking"], active_diagnosis["recommendations"]
            evidence = build_evidence(diagnosis, inspection, recommendations, risk or {}, stress or {}, source_files={"diagnosis": case.get("prior") or "unavailable", "risk_assessment": str(risk_path), "component_stress": str(stress_path)})
            advice = build_repair_advice(evidence, question)
            evidence["recommendations"] = advice["recommended_checks"]
            start = time.perf_counter()
            if client and selected_model:
                with st.spinner("로컬 Ollama 모델 응답 생성 중…"):
                    try:
                        result = answer_question(client, selected_model, question, evidence, advice)
                    except (LocalLLMError, ValueError) as exc:
                        result = {"status": "failed", "error": str(exc), "fallback_used": True}
            else:
                result = {"status": "skipped", "fallback_used": True}
            result["elapsed_seconds"] = round(time.perf_counter() - start, 3)
            result["fallback_used"] = result.get("status") != "success"
            if result["fallback_used"]:
                result["fallback_explanation"] = _fallback_text(evidence)
            active_measurements = st.session_state.get("measurements", []) if bayesian_supported else []
            st.session_state.last_advisor = {
                "analysis_context_key": context_key,
                "measurement_set_id": _measurement_set_id(active_measurements),
                "simulation_result_id": _simulation_result_id(result_dir),
                "result": result,
                "evidence": evidence,
                "advice": advice,
            }
        saved = st.session_state.get("last_advisor")
        active_measurements = st.session_state.get("measurements", []) if bayesian_supported else []
        if saved and not _advisor_matches(saved, context_key, active_measurements, result_dir):
            st.session_state.pop("last_advisor", None)
            saved = None
        if saved:
            result = saved["result"]
            st.caption(f"상태: {result['status']} · 응답 시간: {result['elapsed_seconds']} s · " + ("Deterministic Fallback" if result["fallback_used"] else f"Local LLM · {result.get('model', selected_model)}"))
            if result.get("validation_error"):
                st.caption(f"LLM 응답 검증 사유: {result['validation_error']}")
            elif result.get("error"):
                st.caption(f"로컬 모델 오류: {result['error']}")
            if result.get("response"):
                st.markdown(result["response"]["answer"])
                with st.expander("Facts / Assumptions / Recommendations / Unknowns"):
                    st.json(result["response"])
            else:
                st.info(result.get("fallback_explanation", "결정론적 안내를 구성할 수 없습니다."))
            with st.expander("근거 자료 (Evidence IDs)"):
                st.json(saved["evidence"])
            st.download_button("수리 조언 JSON", json.dumps({"repair_advice": saved["advice"], "llm_explanation": result, "evidence": saved["evidence"]}, ensure_ascii=False, indent=2), "repair_advice.json", "application/json")

    with tabs[6]:
        from circuitcare.vision_ui import render_vision_tab

        render_vision_tab(
            st,
            netlist_component_refs=sorted(circuit.components),
            risk_assessment=risk,
            risk_path=str(risk_path.relative_to(ROOT)) if risk_path.exists() else "unavailable",
            failed_component=selected_fault,
            fault_type=fault_type,
            context_key=hashlib.sha256(repr(context_key).encode()).hexdigest()[:16],
            current_result_status=status,
            inspection_ranking=(what_if_result or {}).get("inspection_ranking"),
            selected_component=st.session_state.get(f"fault_map_component_{hashlib.sha256(repr(context_key).encode()).hexdigest()[:10]}"),
        )
    with tabs[7]:
        render_datasheet_tab(st, root=ROOT, circuit=circuit,
            context_key=hashlib.sha256(repr(context_key).encode()).hexdigest()[:16], case=case,
            risk=base_risk, stress=stress, client=client, models=models,
            stress_signature=stress_signature,
            applied_records=applied_ratings,
            current_risk=risk if applied_ratings and risk.get("reassessment_source") else None)
    with tabs[8]:
        from circuitcare.fault_ai_ui import render_fault_ai_tab
        render_fault_ai_tab(st, root=ROOT, circuit=circuit, case_name=case_name, case=case,
                            client=client, models=models,
                            context_key=hashlib.sha256(repr(context_key).encode()).hexdigest()[:16])
    with tabs[9]:
        from circuitcare.repair_feedback_ui import render_repair_feedback_tab
        state_id = hashlib.sha256(repr(context_key).encode()).hexdigest()[:16]
        fault_state = st.session_state.get(f"fault_ai_state_{state_id}")
        render_repair_feedback_tab(st, root=ROOT,
            circuit_context={"circuit_id": case_name, "circuit_family": case_name,
                "circuit_hash": hashlib.sha256(netlist_path.read_bytes()).hexdigest(),
                "component_refs": sorted(circuit.components)},
            fault_state=fault_state)
    with tabs[10]:
        from circuitcare.benchmark_ui import render_benchmark_tab
        render_benchmark_tab(st, root=ROOT)

    _downloads(st, case, result_dir, comparison, risk, st.session_state.get("diagnosis_result"), selected_fault, fault_type, fault_value if needs_value else None)


def _load_diagnosis(case: dict) -> dict:
    base = ROOT / case["prior"]
    return {"diagnosis": _json_if_exists(base / "diagnosis.json"), "inspection_ranking": _json_if_exists(base / "inspection_ranking.json"), "recommendations": _json_if_exists(base / "measurement_recommendations.json")}


def _render_analysis_overview(st, *, circuit, case_name, case, context_key, failed_component,
                              fault_type, fault_value, risk, comparison, status, bayesian_supported):
    """Unified read-only overview plus an isolated simulated-demo What-if preview."""
    from circuitcare.visualization.fault_map import build_fault_map, fault_map_json, render_fault_map_dot

    st.subheader("고장 영향 후보 지도 및 진단 개요")
    st.caption("지도는 Component–Net 연결 후보를 나타내며 실제 회로도 배치나 방향성 있는 손상 전파도가 아닙니다. 정격 스트레스와 Bayesian 점검 순위는 별도 근거입니다.")
    risk_rows = (risk or {}).get("secondary_candidates", [])
    exceeded_count = sum(row.get("risk_level") == "EXCEEDED" for row in risk_rows) if risk else None
    baseline_top = None
    baseline_inspection = None
    if bayesian_supported:
        base_result = _load_diagnosis(case)
        baseline_inspection = next(iter(base_result.get("inspection_ranking", {}).get("prior_weighted_inspection_order", [])), None)
    cards = st.columns(4)
    cards[0].metric("선택 고장 부품", failed_component)
    cards[1].metric("시뮬레이션 상태", status)
    cards[2].metric("정격 초과 후보", str(exceeded_count) if exceeded_count is not None else "UNAVAILABLE")
    cards[3].metric("Prior 점검 후보", baseline_inspection.get("component_ref") if baseline_inspection else "UNAVAILABLE")
    st.caption(f"회로: {case_name} · 고장 조건: {fault_type} / {fault_value or '—'} · 손상 확정: 아니요")

    what_if_result = None
    if bayesian_supported:
        st.markdown("### Bayesian What-if — 가상 측정 미리보기")
        st.warning("이 컨트롤은 `simulated_demo` 가상 측정만 계산합니다. 기존 실측 기록, SPICE 결과, 정격 위험도, 수리 이력은 변경하지 않습니다. 실제 측정값으로 저장할 수 없습니다.")
        context_id = hashlib.sha256(repr(context_key).encode()).hexdigest()[:16]
        node_options = _load_diagnosis(case).get("diagnosis", {}).get("available_measurement_nodes", ["VOUT"])
        if "VOUT" in node_options:
            node_options = ["VOUT", *[item for item in node_options if item != "VOUT"]]
        controls = st.columns([2, 2, 2, 1])
        node = controls[0].selectbox("측정 노드", node_options, key="what_if_node", index=0)
        if node == "VOUT":
            voltage_min, voltage_max, voltage_default = 2.0, 9.0, 7.9
        else:
            from circuitcare.diagnosis_data import load_diagnosis_data
            hypotheses, _ = load_diagnosis_data(DEMO_HYPOTHESES)
            prediction_values = [hypothesis.predicted_measurements[node] for hypothesis in hypotheses
                                 if node in hypothesis.predicted_measurements]
            voltage_min = max(0.0, float(int(min(prediction_values) - 1)))
            voltage_max = float(int(max(prediction_values) + 2))
            voltage_default = min(voltage_max, max(voltage_min, (min(prediction_values) + max(prediction_values)) / 2))
        voltage_key = f"what_if_voltage_{node}"
        voltage = controls[1].slider("가상 전압 (V)", min_value=voltage_min, max_value=voltage_max, step=0.1,
                                     value=float(st.session_state.get(voltage_key, voltage_default)), key=voltage_key)
        sigma = controls[2].number_input("불확실도 σ (V)", min_value=0.01, max_value=5.0, step=0.1,
                                        value=float(st.session_state.get("what_if_sigma", 0.2)), key="what_if_sigma")
        if controls[3].button("초기화", key=f"what_if_reset_{context_id}"):
            for key in list(st.session_state):
                if key.startswith("what_if_voltage_"):
                    st.session_state.pop(key, None)
            for key in ("what_if_result", "what_if_result_key", "what_if_measurements", "what_if_context_key",
                        "what_if_sigma", "what_if_node"):
                st.session_state.pop(key, None)
            st.rerun()
        state_key = (context_key, node, float(voltage), float(sigma))
        if st.session_state.get("what_if_result_key") != state_key:
            started = time.perf_counter()
            virtual_measurement = {"node": node, "value": float(voltage), "unit": "V",
                                   "uncertainty": float(sigma), "source": "simulated_demo"}
            result = _run_diagnosis([virtual_measurement])
            st.session_state.what_if_measurements = [virtual_measurement]
            st.session_state.what_if_context_key = context_key
            st.session_state.what_if_result = result
            st.session_state.what_if_result_key = state_key
            st.session_state.what_if_elapsed_seconds = round(time.perf_counter() - started, 4)
        what_if_result = st.session_state.what_if_result
        diagnosis = what_if_result["diagnosis"]
        if diagnosis.get("model_mismatch"):
            st.error("MODEL MISMATCH · 설정된 가설이 이 측정값을 잘 설명하지 못합니다. 상위 가설을 진단 결론으로 강조하지 않습니다.")
        posterior = diagnosis.get("posterior", [])
        prior_rows = _load_diagnosis(case).get("diagnosis", {}).get("posterior", [])
        prior_by_id = {row["hypothesis_id"]: row.get("prior_weight", 0.0) for row in prior_rows}
        chart_rows = [{"가설": row["hypothesis_id"], "Prior": prior_by_id.get(row["hypothesis_id"], 0.0),
                       "What-if posterior": row["posterior"]} for row in posterior]
        if chart_rows:
            import pandas as pd
            st.bar_chart(pd.DataFrame(chart_rows).set_index("가설"), y_label="조건부 가중치")
            if diagnosis.get("model_mismatch"):
                st.caption(f"가상 입력: {node}={voltage:.1f} V, σ={sigma:.2f} V · 모델 불일치로 최상위 가설을 강조하지 않습니다. · 계산 {st.session_state.get('what_if_elapsed_seconds', 0):.4f} s")
            else:
                top = max(posterior, key=lambda row: row["posterior"])
                st.caption(f"가상 입력: {node}={voltage:.1f} V, σ={sigma:.2f} V · 상위 가설: {top['hypothesis_id']} ({top['posterior']:.4f}, 설정 가설 집합에 조건부) · 계산 {st.session_state.get('what_if_elapsed_seconds', 0):.4f} s")
        st.caption(diagnosis.get("probability_interpretation", "Posterior는 설정 가설 집합에 조건부이며 실제 고장 확률이 아닙니다."))
        changes = what_if_result["inspection_ranking"].get("rank_changes_after_measurements", [])
        if changes:
            st.markdown("**점검 우선순위 변화** (Bayesian 가중 점검 지수; 전기적 위험 등급과 별개)")
            st.dataframe([{"부품": row["component_ref"], "Prior 순위": row["prior_rank"],
                           "What-if 순위": row["posterior_rank"], "순위 변화 (+ 상승)": row["rank_change"],
                           "Prior 점검 지수": row["prior_weighted_priority_score"],
                           "What-if 점검 지수": row["posterior_weighted_priority_score"]} for row in changes],
                         hide_index=True, use_container_width=True)
        recommendation = what_if_result["recommendations"].get("recommended_measurement")
        if recommendation:
            st.write(f"**다음 정보량 기반 측정 후보:** {recommendation['node']} · 정보 이득 {recommendation['expected_information_gain_nats']:.4f} nats")
        else:
            st.write("**다음 정보량 기반 측정 후보:** 설정된 미측정 노드 중 의미 있는 후보 없음")
        st.caption("추천 후보가 없다는 것은 점검이 불필요하다는 의미가 아닙니다.")
    else:
        st.info("What-if Bayesian 데모는 저장된 U1 3/6/8 V 가설이 연결된 기본 회로·고장 조건에서만 사용할 수 있습니다.")

    ranking = what_if_result.get("inspection_ranking") if what_if_result else None
    view_mode = st.radio("지도 보기", ["Connection View", "Electrical Stress View", "Inspection Priority View"],
                         horizontal=True, key=f"fault_map_mode_{hashlib.sha256(repr(context_key).encode()).hexdigest()[:10]}")
    refs = list(circuit.components)
    selected = st.selectbox("영향 경로를 강조할 부품", refs, index=refs.index(failed_component), key=f"fault_map_component_{hashlib.sha256(repr(context_key).encode()).hexdigest()[:10]}")
    payload = build_fault_map(circuit, failed_component, risk_assessment=risk,
                              inspection_ranking=ranking, selected_component=selected,
                              view_mode=view_mode, max_hops=max(1, len(circuit.components) - 1))
    payload["analysis_context"] = {"circuit": case["netlist"], "failed_component": failed_component,
                                   "fault_type": fault_type, "fault_parameter": fault_value,
                                   "simulation_status": status,
                                   "scenario_id": (risk or {}).get("scenario_id"),
                                   "context_id": hashlib.sha256(repr(context_key).encode()).hexdigest()[:16]}
    payload["visualization_version"] = "phase13-v1"
    st.graphviz_chart(render_fault_map_dot(payload), use_container_width=True)
    if view_mode == "Electrical Stress View":
        st.caption("색상: 보라 Known Failed · 빨강 EXCEEDED · 주황 NEAR_LIMIT · 파랑 WITHIN_LIMIT · 회색 UNKNOWN. 정격 초과는 설정 정격과 시뮬레이션 스트레스의 비교이며 실제 손상 확정이 아닙니다.")
    elif view_mode == "Inspection Priority View":
        st.caption("색상은 posterior 가중 점검 지수 구간, #숫자는 순위입니다. Bayesian 조정 후에도 실제 순위는 그대로일 수 있습니다. SPICE 정격 위험과 별개이며 손상 확률이 아닙니다.")
    else:
        st.caption("보라색은 사용자가 선택한 고장 부품, 파랑은 연결 후보, 회색은 선택 경로 밖 부품입니다. Net 연결은 전력 흐름 방향을 뜻하지 않습니다.")
    detail = next(row for row in payload["nodes"] if row["component_ref"] == selected)
    st.markdown(f"#### {selected} 상세 근거")
    st.json({**detail, "connection_paths": [row for row in payload["paths"] if row["target_ref"] == selected],
             "risk_metrics": next((row.get("metrics", {}) for row in risk_rows if row.get("component_ref") == selected), {}),
             "stress_changes_with_what_if": False,
             "unknowns": ["실제 손상 여부", "미모델링 전기 변수", "구성되지 않은 정격"]})
    st.download_button("영향 지도 JSON 다운로드", fault_map_json(payload), "fault_map_data.json", "application/json",
                       key=f"fault_map_json_{context_id if bayesian_supported else 'none'}")
    st.download_button("영향 지도 DOT 다운로드", render_fault_map_dot(payload), "fault_influence_map.dot", "text/vnd.graphviz",
                       key=f"fault_map_dot_{hashlib.sha256(repr(context_key).encode()).hexdigest()[:12]}")
    if what_if_result:
        export_diagnosis = {key: value for key, value in what_if_result["diagnosis"].items()
                            if key not in {"diagnosis_file", "inspection_ranking_file", "recommendation_file", "measurements_file"}}
        what_if_export = {"analysis_context": payload["analysis_context"], "measurement_source": "simulated_demo",
                          "what_if_measurement": {"node": node, "value_v": voltage, "sigma_v": sigma},
                          "diagnosis": export_diagnosis,
                          "inspection_ranking": what_if_result["inspection_ranking"],
                          "recommendation": what_if_result["recommendations"],
                          "electrical_stress_recomputed": False, "damage_confirmed": False}
        st.download_button("What-if 결과 JSON 다운로드", json.dumps(what_if_export, ensure_ascii=False, indent=2),
                           "what_if_diagnosis.json", "application/json", key=f"what_if_download_{context_id}")
    if st.button("현재 지도와 What-if 결과를 로컬 저장", key=f"fault_map_save_{hashlib.sha256(repr(context_key).encode()).hexdigest()[:12]}"):
        target = ROOT / "data" / "visualizations"
        target.mkdir(parents=True, exist_ok=True)
        (target / "fault_map_data.json").write_text(fault_map_json(payload), encoding="utf-8")
        (target / "fault_influence_map.dot").write_text(render_fault_map_dot(payload), encoding="utf-8")
        if what_if_result:
            (target / "what_if_diagnosis.json").write_text(json.dumps(what_if_export, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success("분석 지도와 가상 진단 결과를 로컬에 저장했습니다.")
    return what_if_result


def _run_diagnosis(measurements: list[dict]) -> dict:
    with tempfile.TemporaryDirectory(prefix="circuitcare-ui-") as tmp:
        measurement_path = Path(tmp) / "measurements.json"
        measurement_path.write_text(json.dumps({"measurements": measurements}), encoding="utf-8")
        result = run_diagnosis(DEMO_HYPOTHESES, measurement_path, Path(tmp) / "results")
        return {"diagnosis": result["diagnosis"], "inspection_ranking": result["inspection_ranking"], "recommendations": result["recommendations"]}


class SimulationRunError(RuntimeError):
    def __init__(self, details: str):
        self.details = details
        super().__init__(details)


def _analysis_context_key(case_name: str, case: dict, fault: str, fault_type: str, fault_value: str | None) -> tuple:
    files = []
    for name in ("netlist", "base", "mapping", "probes", "ratings", "prior"):
        value = case.get(name)
        if not value:
            continue
        path = ROOT / value
        try:
            stat = path.stat()
            identity = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            identity = (str(path.resolve()), None, None)
        files.append((name, identity))
    context_paths = [("what_if_hypotheses", DEMO_HYPOTHESES)]
    if case.get("cached"):
        for result_key in ("comparison.json", "component_stress.json", "risk_assessment.json"):
            context_paths.append((f"cached_{result_key}", ROOT / case["cached"] / result_key))
    if case.get("prior"):
        prior_dir = ROOT / case["prior"]
        for result_key in ("diagnosis.json", "inspection_ranking.json", "measurement_recommendations.json"):
            context_paths.append((f"prior_{result_key}", prior_dir / result_key))
    try:
        hypotheses = json.loads(DEMO_HYPOTHESES.read_text(encoding="utf-8")).get("hypotheses", [])
    except (OSError, json.JSONDecodeError):
        hypotheses = []
    for index, hypothesis in enumerate(hypotheses):
        for key, filename in (("simulation_source", "comparison.json"), ("risk_assessment_source", "risk_assessment.json")):
            source = Path(hypothesis[key])
            source = source if source.is_absolute() else DEMO_HYPOTHESES.parent / source
            context_paths.append((f"hypothesis_{index}_{key}", source / filename if source.is_dir() else source))
    for name, path in context_paths:
        try:
            stat = path.stat()
            identity = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            identity = (str(path.resolve()), None, None)
        files.append((name, identity))
    return (case_name, fault, fault_type, fault_value, tuple(files))


def _supports_bayesian_demo(case_name: str, fault: str, fault_type: str, fault_value: str | None) -> bool:
    return (case_name == "Regulator + divider + switch (cached demo)"
            and fault == "U1" and fault_type == "regulator_output_rise" and fault_value == "8")


def _is_cached_case(case: dict, fault: str, fault_type: str, fault_value: str, needs_value: bool) -> bool:
    return (fault == case["fault"] and fault_type == case["fault_type"]
            and (not needs_value or fault_value == case["value"]))


def _simulation_status(live_matches: bool, live_error: str | None, is_cached_selection: bool) -> str:
    if live_matches:
        return "SUCCESS"
    if live_error:
        return "FAILED"
    return "CACHED" if is_cached_selection else "NOT_RUN"


def _measurement_set_id(measurements: list[dict]) -> str:
    serialized = json.dumps(measurements, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _simulation_result_id(result_dir: Path) -> tuple:
    identity = [str(result_dir.resolve())]
    for name in ("comparison.json", "component_stress.json", "risk_assessment.json"):
        path = result_dir / name
        try:
            stat = path.stat()
            identity.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            identity.append((name, None, None))
    return tuple(identity)


def _advisor_matches(saved: dict, context_key: tuple, measurements: list[dict], result_dir: Path) -> bool:
    return (saved.get("analysis_context_key") == context_key
            and saved.get("measurement_set_id") == _measurement_set_id(measurements)
            and saved.get("simulation_result_id") == _simulation_result_id(result_dir))


def _upsert_measurement(measurements: list[dict], measurement: dict) -> list[dict]:
    updated = list(measurements)
    node = str(measurement["node"])
    for index, existing in enumerate(updated):
        if str(existing.get("node", "")).casefold() == node.casefold():
            updated[index] = measurement
            return updated
    updated.append(measurement)
    return updated


def _validate_live_result(completed: subprocess.CompletedProcess, output: Path, fault: str, fault_type: str) -> Path:
    if completed.returncode != 0:
        raise SimulationRunError(_simulation_error_details(completed, output))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SimulationRunError(f"CLI JSON을 읽을 수 없습니다: {exc}\n{_simulation_error_details(completed, output)}") from exc
    scenario = payload.get("fault_scenario", {})
    scenario_id = f"FAULT_{fault}_{fault_type}".upper()
    report = scenario.get("simulation_analysis", {})
    if (scenario.get("component_ref") != fault or scenario.get("fault_type") != fault_type
            or scenario.get("scenario_id") != scenario_id or scenario.get("simulation_status") != "success"
            or report.get("simulation_status") != "success"
            or report.get("simulation_run_status") != {"baseline": "success", "fault": "success"}):
        raise SimulationRunError(f"CLI 출력이 현재 고장 조건의 성공 결과와 일치하지 않습니다.\n{_simulation_error_details(completed, output)}")
    result_dir = output / "simulation_results" / f"fault_{fault.lower()}_{fault_type}"
    paths = {name: result_dir / f"{name}.json" for name in ("comparison", "component_stress", "risk_assessment")}
    if not all(path.is_file() for path in paths.values()):
        raise SimulationRunError(f"필요한 새 결과 파일이 부족합니다: {', '.join(p.name for p in paths.values() if not p.is_file())}\n{_simulation_error_details(completed, output)}")
    try:
        comparison, stress, risk = (json.loads(paths[key].read_text(encoding="utf-8")) for key in ("comparison", "component_stress", "risk_assessment"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SimulationRunError(f"결과 JSON을 읽을 수 없습니다: {exc}\n{_simulation_error_details(completed, output)}") from exc
    if (comparison.get("simulation_success") is not True or comparison.get("scenario_id") != scenario_id
            or stress.get("simulation_success") is not True or stress.get("fault_type") != fault_type
            or risk.get("simulation_status") != "success" or risk.get("scenario_id") != scenario_id
            or risk.get("failed_component") != fault or risk.get("fault_type") != fault_type):
        raise SimulationRunError(f"결과 파일 상태 또는 고장 조건이 일치하지 않습니다.\n{_simulation_error_details(completed, output)}")
    return result_dir


def _simulation_error_details(completed: subprocess.CompletedProcess, output: Path) -> str:
    stderr = (completed.stderr or "").strip()[-3000:] or "(stderr 없음)"
    logs = sorted(output.rglob("*.log")) if output.exists() else []
    log_text = ", ".join(str(path) for path in logs) if logs else f"{output}/simulation_results/의 ngspice 로그를 확인하세요."
    return f"종료 코드: {completed.returncode}\nstderr:\n{stderr}\nngspice 로그: {log_text}"


def _advisor_inputs(case: dict) -> tuple[dict, dict, dict]:
    if case.get("prior"):
        return _load_diagnosis(case).values()
    return {}, {}, {}


def _ollama_models():
    try:
        client = OllamaClient(timeout_seconds=180)
        return client, client.list_models()
    except (LocalLLMError, ValueError):
        return None, []


def _json_if_exists(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _csv_rows(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _risk_table(risk: dict) -> list[dict]:
    result = []
    for row in risk.get("secondary_candidates", []):
        metric = row.get("dominant_metric")
        metric_key = {"voltage": "max_abs_voltage_v", "current": "max_current_a", "power": "max_power_w"}.get(metric)
        detail = row.get("metrics", {}).get(metric_key, {}) if metric_key else {}
        result.append({"부품": row.get("component_ref"), "등급": row.get("risk_level"), "사용률": detail.get("utilization_ratio"), "스트레스": detail.get("measured_stress"), "정격": detail.get("rated_limit"), "단위": detail.get("unit"), "점검순위": row.get("priority_rank"), "점수 (확률 아님)": row.get("priority_score"), "정격 출처": (detail.get("rating_source") or {}).get("note"), "미평가": "; ".join(v.get("reason", "") for v in row.get("metrics", {}).values() if v.get("reason"))})
    for row in risk.get("excluded_candidates", []):
        result.append({"부품": row.get("component_ref"), "등급": "EXCLUDED", "미평가": row.get("reason")})
    return result


def _stress_table(stress: dict) -> list[dict]:
    rows = []
    for item in stress.get("components", []):
        base, fault, delta = item.get("baseline", {}), item.get("fault", {}), item.get("delta_fault_minus_baseline", {})
        rows.append({"부품": item.get("component_ref"), "상태": item.get("status"), "전압 변화 (V)": (delta.get("voltage_v") or {}).get("last"), "전류 변화 (A)": (delta.get("current_a") or {}).get("last"), "전력 변화 (W)": (delta.get("power_w") or {}).get("last"), "미지원 항목": "; ".join((item.get("unsupported_metrics") or {}).values())})
    return rows


def _downloads(st, case, result_dir, comparison, risk, diagnosis, selected_fault, fault_type, fault_value):
    with st.expander("결과 내보내기"):
        summary = {"circuit": case["netlist"], "fault": {"component": selected_fault, "fault_type": fault_type, "parameter": fault_value}, "simulation_source": "live" if "ui_runs" in str(result_dir) else ("cached" if comparison else "unsupported_or_not_run"), "comparison": comparison or None, "risk_assessment": risk or None, "bayesian_diagnosis": diagnosis.get("diagnosis") if diagnosis else None, "damage_confirmed": False, "limitations": ["Simulation does not confirm damage.", "Ratings and demo observations may be assumptions.", "UNKNOWN is not safe."]}
        st.download_button("전체 분석 요약 JSON", json.dumps(summary, ensure_ascii=False, indent=2), "circuitcare_summary.json", "application/json")
        if risk:
            st.download_button("정격 위험 보고서 JSON", json.dumps(risk, ensure_ascii=False, indent=2), "risk_assessment.json", "application/json")
        if diagnosis:
            st.download_button("Bayesian 진단 JSON", json.dumps(diagnosis["diagnosis"], ensure_ascii=False, indent=2), "diagnosis.json", "application/json")
        csv_path = result_dir / "comparison.csv"
        if csv_path.is_file():
            st.download_button("시뮬레이션 CSV", csv_path.read_bytes(), "comparison.csv", "text/csv")
        report = ["# CircuitCare AI Analysis", "", f"- Circuit: {case['netlist']}", f"- Fault: {selected_fault} / {fault_type} / {fault_value or 'n/a'}", f"- Simulation source: {'live' if 'ui_runs' in str(result_dir) else ('cached' if comparison else 'unsupported or not run')}", "- Ratings are explicit inputs; demo assumptions are not datasheet facts.", "- UNKNOWN does not mean safe; priority scores are not failure probabilities.", "- Physical damage is not confirmed."]
        st.download_button("통합 Markdown 보고서", "\n".join(report), "circuitcare_report.md", "text/markdown")


def _command_exists(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def _valid_parameter(value: str) -> bool:
    match = re.fullmatch(r"\s*((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([pnumkKMG]?)\s*", value)
    if not match:
        return False
    multiplier = {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}[match.group(2)]
    try:
        return float(match.group(1)) * multiplier > 0
    except ValueError:
        return False


def _fallback_text(evidence: dict) -> str:
    order = evidence.get("analysis_context", {}).get("inspection_order", [])
    if order:
        return f"결정론적 결과에서 {order[0].get('component_ref')}는 우선 점검 후보입니다. 실제 손상은 확인되지 않았습니다. 수치와 가정은 아래 Evidence 자료를 확인하세요."
    return "저장된 분석으로 특정 부품의 상태를 판정할 수 없습니다. 정격과 측정 근거를 확인하세요."


if __name__ == "__main__":
    main()
