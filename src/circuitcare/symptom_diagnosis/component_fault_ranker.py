"""Rank detected component instances separately from fault-mode hypotheses."""

from __future__ import annotations

from typing import Any

from circuitcare.symptom_diagnosis.measurement_evaluator import evaluate_component_measurements
from circuitcare.symptom_diagnosis.fault_hypothesis_validator import validate_component_hypothesis


def rank_component_candidates(
    *, hypotheses: list[dict[str, Any]], components: list[dict[str, Any]],
    functional_blocks: list[dict[str, Any]], observations: list[dict[str, Any]] | None,
    measurements: list[dict[str, Any]] | None, knowledge: dict[str, Any],
    confirmed_component_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return Top-3 fault candidates only for IDs confirmed present on this PCB."""
    confirmed_ids = {str(value) for value in (confirmed_component_ids or [])}
    block_by_id = {str(row.get("component_id")): row for row in functional_blocks}
    modes = knowledge.get("fault_modes", {}).get("fault_modes", {})
    tests = knowledge.get("test_catalog", {}).get("tests", {})
    assessments = evaluate_component_measurements(measurements)
    observed = [row for row in (observations or []) if isinstance(row, dict)]
    results: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        mode = modes.get(hypothesis.get("fault_id"), {})
        if mode.get("level") not in {"component", "functional_block"}:
            continue
        fault_id = str(hypothesis.get("fault_id"))
        required_roles = set(mode.get("functional_roles", []))
        eligible = []
        for part in components:
            component_id = str(part.get("component_id") or "")
            block = block_by_id.get(component_id, {})
            assessment = assessments.get((component_id, fault_id), {})
            validation = validate_component_hypothesis(
                mode=mode, component=part, confirmed_component_ids=confirmed_ids,
                component_block=block, component_observations=observed,
                has_validated_measurement=assessment.get("status") in {"TEST_NORMAL", "TEST_ABNORMAL"},
            )
            if validation["eligible"]:
                eligible.append(part)
        if not eligible:
            continue
        targeted_ids: set[str] = set()
        for row in observed:
            component_id = str(row.get("component_id") or "")
            code, value = str(row.get("code") or ""), row.get("value")
            supports = code in (mode.get("supporting_evidence", {}) if value is True
                                else mode.get("supporting_evidence_when_false", {}))
            opposes = code in (mode.get("opposing_evidence", {}) if value is True
                               else mode.get("opposing_evidence_when_false", {}))
            if component_id and (supports or opposes):
                targeted_ids.add(component_id)
        targeted_ids.update(component_id for component_id, measured_fault in assessments
                            if measured_fault == fault_id)
        # Do not break ties between same-mode instances using alphabetical IDs.
        if len(eligible) > 1 and not targeted_ids:
            continue
        if targeted_ids:
            eligible = [part for part in eligible if str(part.get("component_id")) in targeted_ids]
        for part in eligible:
            component_id = str(part.get("component_id") or "")
            part_type = str(part.get("component_type", part.get("label", "unknown"))).casefold()
            if not component_id:
                continue
            block = block_by_id.get(component_id, {})
            candidate_roles = set(block.get("candidate_blocks", []))
            confirmed_roles = set(part.get("confirmed_functional_roles", []))
            role_match = bool(required_roles & confirmed_roles) if required_roles else False
            specific = [row for row in observed if str(row.get("component_id") or "") == component_id]
            supporting: list[str] = []
            opposing: list[str] = []
            for row in specific:
                code, value = str(row.get("code") or ""), row.get("value")
                if value is True and code in mode.get("supporting_evidence", {}):
                    supporting.append(code)
                elif value is False and code in mode.get("supporting_evidence_when_false", {}):
                    supporting.append(f"{code}=false")
                elif value is True and code in mode.get("opposing_evidence", {}):
                    opposing.append(code)
                elif value is False and code in mode.get("opposing_evidence_when_false", {}):
                    opposing.append(f"{code}=false")
            assessment = assessments.get((component_id, fault_id))
            score = float(hypothesis.get("score", 0.0))
            if role_match:
                score += 1.25
            score += 3.0 * len(supporting) - 3.0 * len(opposing)
            marking = str(part.get("ocr_marking") or part.get("marking") or "").strip()
            designator = component_id.split("-", 1)[0].upper()
            if marking:
                score += 0.25
            if assessment and assessment.get("status") == "TEST_ABNORMAL":
                score += 8.0
            elif assessment and assessment.get("status") == "TEST_NORMAL":
                score = max(0.1, score - 8.0)
            if score <= 0:
                continue
            status = (assessment or {}).get("status", "SUSPECTED")
            visual_status = "INCONCLUSIVE" if status == "INCONCLUSIVE" else status
            role_evidence = block.get("role_evidence", {})
            evidence = list(dict.fromkeys([
                *hypothesis.get("supporting_evidence", []),
                *(f"부품별 지지 근거: {code}" for code in sorted(supporting)),
                *(f"부품별 반대 근거: {code}" for code in sorted(opposing)),
                *(text for role in sorted(candidate_roles & required_roles)
                  for text in role_evidence.get(role, [])),
                *([f"실크스크린: {', '.join(block.get('nearby_silkscreen', []))}"]
                  if block.get("nearby_silkscreen") else []),
                *([f"각인: {marking}"] if marking else []),
                *([assessment.get("reason", "")] if assessment and assessment.get("reason") else []),
            ]))
            results.append({
                "component_id": component_id, "component_type": part_type,
                "candidate_rank": 0, "rank": 0, "fault_hypothesis": hypothesis["fault_id"],
                "fault_id": hypothesis["fault_id"],
                "fault_title": hypothesis.get("title", hypothesis["fault_id"]),
                "score": round(score, 2), "status": visual_status, "visual_status": visual_status,
                "measurement_status": status,
                "solder_status": "NOT_ASSESSED", "evidence": evidence,
                "supporting_evidence": list(hypothesis.get("supporting_evidence", [])) + supporting,
                "opposing_evidence": list(hypothesis.get("opposing_evidence", [])) + opposing,
                "requires_measurement": status in {"SUSPECTED", "INCONCLUSIVE"},
                "recommended_tests": [tests[test_id].get("question", tests[test_id].get("name", test_id))
                                       for test_id in mode.get("recommended_tests", [])
                                       if test_id in tests],
                "evidence_ids": list(dict.fromkeys(str(row.get("id") or row.get("observation_id"))
                                                    for row in specific if row.get("id") or row.get("observation_id"))),
                "designator_prefix": designator,
            })

    results.sort(key=lambda row: (-row["score"], row["component_id"], row["fault_hypothesis"]))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in results:
        if row["component_id"] in seen:
            continue
        seen.add(row["component_id"])
        row["candidate_rank"] = len(selected) + 1
        row["rank"] = len(selected) + 1
        selected.append(row)
        if len(selected) >= max(0, limit):
            break
    return selected


def rank_joint_candidates(
    *, hypotheses: list[dict[str, Any]], component_candidates: list[dict[str, Any]],
    observations: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep solder/board candidates separate; promote only with direct evidence."""
    direct_codes = {"VISIBLE_SOLDER_DAMAGE", "CONNECTOR_MOVEMENT_AFFECTS"}
    direct = [code for code in direct_codes if observations.get(code) is True]
    all_component_tests_normal = bool(component_candidates) and all(
        row.get("measurement_status") == "TEST_NORMAL" for row in component_candidates
    )
    candidates = []
    for row in hypotheses:
        if row.get("level") != "board":
            continue
        fault_id = str(row.get("fault_id", ""))
        if fault_id not in {"SOLDER_JOINT_FAILURE", "PCB_TRACE_OPEN", "UNKNOWN_CONNECTION_FAILURE"}:
            continue
        if not direct and not all_component_tests_normal:
            continue
        candidates.append({
            "fault_id": fault_id, "title": row.get("title", fault_id),
            "score": row.get("score", 0), "status": "UNVERIFIED_CANDIDATE",
            "evidence": [*(f"직접 관측: {code}" for code in direct),
                         *( ["관련 소자 가설의 등록 검사값은 기준 범위 내"] if all_component_tests_normal else [])],
            "related_component_ids": [item["component_id"] for item in component_candidates],
        })
    return candidates
