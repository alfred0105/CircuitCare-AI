"""Streamlit interaction for constrained fault proposals and explicit SPICE runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .fault_ai.fault_catalog import generate_rule_candidates
from .fault_ai.hypothesis_generator import merge_candidates
from .fault_ai.hypothesis_validator import validate_hypotheses
from .fault_ai.hypothesis_ranking import conditional_bayesian_update, rank_hypotheses
from .fault_ai.llm_hypothesis import propose_hypotheses
from .fault_ai.simulation_bridge import preflight_candidates, simulate_selected
from .fault_ai.observation_matcher import compare_observations


def render_fault_ai_tab(st: Any, *, root: Path, circuit: Any, case_name: str, case: dict[str, Any],
                        client: Any, models: list[dict[str, Any]], context_key: str) -> None:
    st.subheader("AI 고장 가설 분석")
    st.caption("규칙과 로컬 LLM은 후보를 제안하고, 기존 Fault Injector와 ngspice가 제한된 모델을 검증합니다. 일치 결과는 실제 고장 확정이 아닙니다.")
    mapping = _read_json(root / case["mapping"])
    probes = _read_json(root / case["probes"])
    base_path = root / case["base"]
    spice_text = base_path.read_text(encoding="utf-8")
    supported_nodes = [str(node) for node in probes.get("voltage_nodes", [])]
    llm_names = [item.get("name") for item in models if item.get("name")]
    chosen_model = st.selectbox("가설 생성 로컬 모델", llm_names, key=f"fault_ai_model_{context_key}") if client and llm_names else None
    st.caption(f"회로: {case_name} · 부품 {len(circuit.components)}개 · 명시 매핑 {len(mapping)}개 · Probe 노드 {len(supported_nodes)}개")
    with st.form(f"fault_ai_form_{context_key}"):
        symptom = st.text_area("관측 증상", placeholder="예: VOUT가 기대값보다 높게 측정됨", max_chars=2000)
        cols = st.columns(4)
        node = cols[0].selectbox("측정 노드", supported_nodes, key=f"fault_ai_node_{context_key}") if supported_nodes else ""
        value = cols[1].number_input("측정값 (V)", value=0.0, format="%.6g", key=f"fault_ai_value_{context_key}")
        uncertainty = cols[2].number_input("불확실도 (V, 알면 입력)", min_value=0.0, value=0.0, format="%.6g", key=f"fault_ai_sigma_{context_key}")
        source = cols[3].selectbox("측정 출처", ["실제 측정", "시뮬레이션", "가상 데모"], key=f"fault_ai_source_{context_key}")
        generate = st.form_submit_button("규칙 기반 후보 생성")
        generate_llm = st.form_submit_button("로컬 AI 가설 제안", disabled=not (client and chosen_model))
    state_key = f"fault_ai_state_{context_key}"
    if generate or generate_llm:
        observations = []
        if node and (value != 0.0 or symptom.strip()):
            observations.append({"node": node, "value": float(value), "unit": "V",
                                 "uncertainty": float(uncertainty) if uncertainty > 0 else None,
                                 "source": source, "measurement_mode": "final_sample"})
        candidates = generate_rule_candidates(circuit, mapping, spice_text, observations)
        candidates = preflight_candidates(candidates, component_refs=set(circuit.components),
                                          component_mapping=mapping, spice_text=spice_text)
        state = {"observations": observations, "symptom": symptom, "rule_candidates": candidates,
                 "hypotheses": candidates, "llm_metadata": None, "context_key": context_key}
        if generate_llm:
            components = [{"ref": c.ref, "value": c.value, "library_id": c.library_id,
                           "nets": list(circuit.component_nets.get(c.ref, ())),
                           "spice_mapping": {"model_type": mapping[c.ref].get("model_type"), "available": True}
                           if c.ref in mapping else {"available": False}}
                          for c in circuit.components.values()]
            try:
                proposed = propose_hypotheses(client, chosen_model, circuit_id=case_name,
                    components=components, observations=observations, symptoms=symptom,
                    executable_catalog=candidates)
                llm_rows = validate_hypotheses(proposed["hypotheses"], component_refs=set(circuit.components),
                    component_mapping=mapping, spice_text=spice_text, allowed_catalog=candidates)
                state["hypotheses"] = merge_candidates(candidates, llm_rows)
                state["llm_metadata"] = {k: proposed.get(k) for k in ("model", "model_info", "prompt_version", "latency_seconds", "json_mode")}
            except (ValueError, RuntimeError, OSError) as exc:
                state["llm_metadata"] = {"status": "failed", "error": str(exc)}
        st.session_state[state_key] = state
    state = st.session_state.get(state_key)
    if not state or state.get("context_key") != context_key:
        st.info("증상과 측정값을 입력하고 후보 생성 버튼을 누르세요. SPICE는 별도 실행 버튼에서만 작동합니다.")
        _render_eval_section(st, root)
        return
    if state.get("llm_metadata"):
        st.write("**로컬 LLM:**", state["llm_metadata"])
    rows = state["hypotheses"]
    summary = {"규칙 후보": len(state["rule_candidates"]), "전체 후보": len(rows),
               "사전검증 통과": sum(row.get("validation_status") == "VALIDATED_EXECUTABLE" for row in rows),
               "실행 실패/미지원": sum(row.get("validation_status") != "VALIDATED_EXECUTABLE" for row in rows)}
    st.json(summary)
    if rows:
        st.dataframe([{"가설 ID": r.get("hypothesis_id"), "부품": r.get("component_ref"),
                       "고장 유형": r.get("fault_type"), "출처": r.get("generation_method"),
                       "사전검증": r.get("validation_status"), "설명": r.get("reason", ""),
                       "미지원 사유": "; ".join(r.get("validation_reasons", []))}
                      for r in rows], use_container_width=True, hide_index=True)
    executable = [row for row in rows if row.get("validation_status") == "VALIDATED_EXECUTABLE"]
    run_key = f"fault_ai_run_{context_key}"
    ids = [row["hypothesis_id"] for row in executable]
    selected = st.multiselect("ngspice 실행 가설 (최대 5개)", ids, default=ids[:min(3, len(ids))], key=f"fault_ai_select_{context_key}")
    if st.button("선택 가설을 ngspice로 검증", key=f"fault_ai_simulate_{context_key}", disabled=not selected):
        with st.spinner("기존 Fault Injector와 ngspice로 선택된 가설을 실행 중…"):
            results = simulate_selected(rows, selected_ids=selected, max_runs=5, base_netlist=base_path,
                component_mapping=mapping, probes=probes, observations=state["observations"], timeout_seconds=60)
        state["hypotheses"] = rank_hypotheses(results)
        state["bayesian_result"] = conditional_bayesian_update(state["hypotheses"], state["observations"])
        st.session_state[state_key] = state
        st.session_state[run_key] = time.time()
    for row in rank_hypotheses(state["hypotheses"]):
        with st.expander(f"{row.get('evidence_rank') or '—'} · {row['component_ref']} · {row['fault_type']} · {row.get('simulation_status', 'SIMULATION_NOT_RUN')}"):
            st.json(row)
            try:
                from circuitcare.visualization.fault_map import build_fault_map, render_fault_map_dot
                fault_map = build_fault_map(circuit, row["component_ref"], selected_component=row["component_ref"])
                st.graphviz_chart(render_fault_map_dot(fault_map))
            except (KeyError, ValueError):
                pass
    bayes = state.get("bayesian_result")
    if bayes:
        with st.expander("기존 Bayesian 엔진 · 조건부 비교"):
            if bayes.get("status") == "ACTIVE_CONDITIONAL":
                st.write("**조건부 가설 순위:**")
                st.dataframe(bayes.get("posterior", []), use_container_width=True, hide_index=True)
                st.caption(bayes.get("probability_interpretation", ""))
            else:
                st.info(bayes.get("reason", "Bayesian 업데이트를 적용할 수 없습니다."))
    _render_eval_section(st, root)


def _render_eval_section(st: Any, root: Path) -> None:
    with st.expander("개발자용 평가 상태"):
        for label, relative in (("Fault Hypothesis Evaluation", "evaluation/fault_hypothesis/results/metrics.json"),
                                ("Datasheet Extraction Benchmark", "evaluation/datasheet_extraction/results/comparison.json")):
            result = _read_json(root / relative)
            st.markdown(f"**{label}**")
            st.json(result or {"status": "NOT_EVALUATED", "reason": "No evaluation result has been recorded."})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
