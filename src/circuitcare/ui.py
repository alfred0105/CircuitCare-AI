"""Local Streamlit dashboard joining the existing CircuitCare analysis stages."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from circuitcare.conversation import answer_question
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
    st.sidebar.caption(f"선택한 고장 모델: {fault_type} · 파라미터: {fault_value if needs_value else '해당 없음'}")
    st.sidebar.caption("시연 데이터는 저장된 결과이며, 새 시뮬레이션은 버튼을 눌렀을 때만 실행합니다.")

    run_col, state_col = st.sidebar.columns(2)
    run_live = run_col.button("ngspice 실행", disabled=not _command_exists("ngspice"), use_container_width=True)
    live_matches = bool(st.session_state.get("live_result_dir")) and st.session_state.get("live_case") == case_name and st.session_state.get("live_fault") == selected_fault and st.session_state.get("live_fault_type") == fault_type and st.session_state.get("live_fault_value") == fault_value
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
        slug = {"U1": "regulator_8v", "R1": "divider_r1_drift", "RCHARGE": "rc_rcharge_drift"}.get(selected_fault, "scenario")
        output = ROOT / "data/ui_runs" / slug
        cmd = [sys.executable, "-m", "circuitcare.cli", "--netlist", str(netlist_path), "--fault", selected_fault,
               "--fault-type", fault_type, "--spice-base", str(ROOT / case["base"]),
               "--spice-mapping", str(ROOT / case["mapping"]), "--output", str(output), "--simulate", "--probes", str(ROOT / case["probes"]),
               "--ratings", str(ROOT / case["ratings"]), "--assess-risk"]
        if needs_value:
            cmd.extend(["--fault-value", fault_value])
        with st.spinner("Fault Injection → ngspice → stress/rating assessment 실행 중…"):
            try:
                completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120, check=True)
                json.loads(completed.stdout)
                st.session_state.live_result_dir = str(output / "simulation_results" / f"fault_{selected_fault.lower()}_{fault_type}")
                st.session_state.live_case = case_name
                st.session_state.live_fault = selected_fault
                st.session_state.live_fault_type = fault_type
                st.session_state.live_fault_value = fault_value
                st.success("새 시뮬레이션 완료")
                st.rerun()
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
                st.error(f"시뮬레이션 실패: {exc}")
    comparison_path = result_dir / "comparison.json"
    risk_path = result_dir / "risk_assessment.json"
    stress_path = result_dir / "component_stress.json"
    comparison = _json_if_exists(comparison_path)
    risk = _json_if_exists(risk_path)
    stress = _json_if_exists(stress_path)
    is_cached_selection = selected_fault == case["fault"] and fault_type == case["fault_type"] and fault_value == case["value"]
    state_col.markdown("🟢 Live Simulation" if live_used else ("🔵 Cached Simulation Result" if is_cached_selection else "⚪ 분석 준비 · 미실행"))
    st.sidebar.markdown("🟢 ngspice 사용 가능" if _command_exists("ngspice") else "🟠 ngspice 없음 · 저장 결과 조회 가능")
    client, models = _ollama_models()
    st.sidebar.markdown("🟢 Local LLM" if client else "🟡 Deterministic Fallback · Ollama 연결 불가")

    tabs = st.tabs(["회로 및 고장", "SPICE 파형", "2차 손상 위험", "Bayesian 진단", "로컬 LLM 수리 지원"])
    with tabs[0]:
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
        if not case.get("mapping") or not Path(case.get("mapping", "")).exists():
            st.warning("KiCad XML만 확인 가능합니다. 명시적 SPICE mapping/model이 없어 물리 시뮬레이션을 지원하지 않습니다.")
        st.caption(f"넷리스트: `{case['netlist']}` · 파형/위험 데이터 출처: `{comparison_path.relative_to(ROOT) if comparison_path.exists() else case['cached']}`")

    with tabs[1]:
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

    with tabs[2]:
        st.subheader("2차 스트레스 및 정격 비교")
        if risk:
            st.caption("EXCEEDED / NEAR_LIMIT는 설정 정격과 계산 스트레스 비교입니다. WITHIN_LIMIT는 평가한 정격 항목 한정이며 부품 정상 상태나 실제 손상을 뜻하지 않습니다. UNKNOWN은 안전 판정이 아닙니다.")
            st.dataframe(_risk_table(risk), use_container_width=True, hide_index=True)
            st.caption("점수는 점검 우선순위 지표(확률 아님). 정격 출처는 evidence note를 펼쳐 확인하세요.")
            with st.expander("위험 보고서 JSON"):
                st.json(risk)
        else:
            st.info("이 회로에는 위험 평가 결과가 저장되어 있지 않습니다.")

    with tabs[3]:
        st.subheader("Bayesian 진단")
        if case.get("prior"):
            current = st.session_state.get("diagnosis_result") or _load_diagnosis(case)
            if st.button("저장된 7.9 V simulated_demo 측정으로 예시 갱신"):
                with MEASUREMENTS.open(encoding="utf-8") as handle:
                    sample = json.load(handle)["measurements"][0]
                current = _run_diagnosis(sample)
                st.session_state.diagnosis_result = current
            with st.form("measurement_form"):
                node = st.selectbox("측정 노드", current["diagnosis"].get("available_measurement_nodes", []), index=0)
                value = st.number_input("측정 전압 (V)", value=7.9, format="%.4f")
                uncertainty = st.number_input("불확실도 σ (V)", min_value=0.0001, value=0.2, format="%.4f")
                source = st.selectbox("출처", ["user_measurement", "simulated_demo"], help="실제 계측값을 직접 입력한 경우에만 user_measurement를 선택하세요.")
                submitted = st.form_submit_button("측정 추가 후 재계산")
            if submitted:
                current = _run_diagnosis({"node": node, "value": value, "unit": "V", "uncertainty": uncertainty, "source": source})
                st.session_state.diagnosis_result = current
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

    with tabs[4]:
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
            diagnosis, inspection, recommendations = _advisor_inputs(case)
            active_diagnosis = st.session_state.get("diagnosis_result")
            if active_diagnosis and case.get("prior"):
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
            st.session_state.last_advisor = {"result": result, "evidence": evidence, "advice": advice}
        saved = st.session_state.get("last_advisor")
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

    _downloads(st, case, result_dir, comparison, risk, st.session_state.get("diagnosis_result"), selected_fault, fault_type, fault_value if needs_value else None)


def _load_diagnosis(case: dict) -> dict:
    base = ROOT / case["prior"]
    return {"diagnosis": _json_if_exists(base / "diagnosis.json"), "inspection_ranking": _json_if_exists(base / "inspection_ranking.json"), "recommendations": _json_if_exists(base / "measurement_recommendations.json")}


def _run_diagnosis(measurement: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="circuitcare-ui-") as tmp:
        measurement_path = Path(tmp) / "measurements.json"
        measurement_path.write_text(json.dumps({"measurements": [measurement]}), encoding="utf-8")
        result = run_diagnosis(DEMO_HYPOTHESES, measurement_path, Path(tmp) / "results")
        return {"diagnosis": result["diagnosis"], "inspection_ranking": result["inspection_ranking"], "recommendations": result["recommendations"]}


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
