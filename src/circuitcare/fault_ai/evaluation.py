"""Transparent candidate and ranked-result metrics for labeled fault cases."""

from typing import Any


def score_fault_cases(cases: list[dict[str, Any]], predictions: dict[str, list[dict[str, Any]]], *, top_k=(1, 3)) -> dict[str, Any]:
    if not cases:
        return {"status": "NOT_EVALUATED", "case_count": 0, "candidate_precision": None,
                "candidate_recall": None, "top_k_accuracy": {str(k): None for k in top_k},
                "precision_at_k": {str(k): None for k in top_k}}
    expected_count = predicted_count = true_positive = executable = hallucinated_refs = 0
    top_hits = {k: 0 for k in top_k}
    top_denominators = {k: 0 for k in top_k}
    precision_at_k_sum = {k: 0.0 for k in top_k}
    per_case = []
    for case in cases:
        case_id = case["case_id"]
        truth_rows = case.get("ground_truth", [])
        outputs = predictions.get(case_id, [])
        expected = {(item["component_ref"], item["fault_type"], _parameters(item.get("parameters", {}))) for item in truth_rows}
        observed = {(item.get("component_ref"), item.get("fault_type"), _parameters(item.get("parameters", {}))) for item in outputs}
        hits = expected & observed
        expected_count += len(expected)
        predicted_count += len(outputs)
        true_positive += len(hits)
        executable += sum(item.get("validation_status") == "VALIDATED_EXECUTABLE" for item in outputs)
        hallucinated_refs += sum(item.get("validation_status") == "INVALID_REFERENCE" for item in outputs)
        ordered = sorted(outputs, key=lambda item: (item.get("evidence_rank") is None, item.get("evidence_rank") or 0))
        ranked = [item for item in ordered if item.get("evidence_rank") is not None]
        if truth_rows and ranked:
            for k in top_k:
                top_denominators[k] += 1
                top_rows = ranked[:k]
                hits_at_k = sum((item.get("component_ref"), item.get("fault_type"), _parameters(item.get("parameters", {}))) in expected for item in top_rows)
                top_hits[k] += int(hits_at_k > 0)
                precision_at_k_sum[k] += hits_at_k / min(k, len(top_rows))
        per_case.append({"case_id": case_id, "truth_count": len(expected), "candidate_count": len(outputs),
                         "correct_candidate_count": len(hits), "ranked_candidate_count": len(ranked),
                         "correct_rank": next((item.get("evidence_rank") for item in ranked
                             if (item.get("component_ref"), item.get("fault_type"), _parameters(item.get("parameters", {}))) in expected), None)})
    precision = true_positive / predicted_count if predicted_count else None
    recall = true_positive / expected_count if expected_count else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else (0.0 if precision == 0 and recall == 0 else None)
    attempted = [item for rows in predictions.values() for item in rows if item.get("simulation_status") in {"SIMULATION_SUCCESS", "SIMULATION_FAILED"}]
    simulation_successes = sum(item.get("simulation_status") == "SIMULATION_SUCCESS" for item in attempted)
    unsupported = sum(item.get("validation_status") != "VALIDATED_EXECUTABLE" for rows in predictions.values() for item in rows)
    runtimes = [float(item["simulation_seconds"]) for item in attempted if isinstance(item.get("simulation_seconds"), (int, float))]
    return {"status": "MEASURED_SYNTHETIC" if any(case.get("truth_source") == "synthetic_fault" for case in cases) else "MEASURED",
            "case_count": len(cases), "ground_truth_count": expected_count, "candidate_count": predicted_count,
            "correct_candidate_count": true_positive, "candidate_precision": precision, "candidate_recall": recall,
            "candidate_f1": f1, "executable_hypothesis_rate": executable / predicted_count if predicted_count else None,
            "unsupported_proposal_rate": unsupported / predicted_count if predicted_count else None,
            "hallucinated_reference_rate": hallucinated_refs / predicted_count if predicted_count else None,
            "top_k_accuracy": {str(k): top_hits[k] / top_denominators[k] if top_denominators[k] else None for k in top_k},
            "precision_at_k": {str(k): precision_at_k_sum[k] / top_denominators[k] if top_denominators[k] else None for k in top_k},
            "top_k_evaluated_cases": {str(k): top_denominators[k] for k in top_k},
            "simulation_attempt_count": len(attempted), "simulation_success_count": simulation_successes,
            "simulation_success_rate": simulation_successes / len(attempted) if attempted else None,
            "mean_simulation_runtime_seconds": sum(runtimes) / len(runtimes) if runtimes else None,
            "per_case": per_case}


def _parameters(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    result = []
    for key, item in value.items():
        try:
            normalized = f"{float(item):.12g}"
        except (TypeError, ValueError):
            normalized = str(item).strip().casefold()
        result.append((str(key), normalized))
    return tuple(sorted(result))
