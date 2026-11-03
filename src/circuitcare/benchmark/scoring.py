"""Hierarchical diagnosis and physics-ranking metrics."""

from __future__ import annotations

import math
from typing import Any


def score_hypothesis_levels(cases: list[dict[str, Any]], truths: dict[str, list[dict[str, Any]]],
                            predictions: dict[str, list[dict[str, Any]]], *, parameter_tolerance: float = 1e-9) -> dict[str, Any]:
    if parameter_tolerance < 0 or not math.isfinite(parameter_tolerance):
        raise ValueError("parameter_tolerance must be finite and non-negative")
    levels = {name: {"tp": 0, "fp": 0, "fn": 0} for name in ("component", "fault_mode", "exact_hypothesis")}
    case_rows = []
    eligible_cases = 0
    candidate_total = executable_total = invalid_reference_total = duplicate_total = 0
    for case in cases:
        case_id = str(case["case_id"])
        expected = truths.get(case_id, [])
        proposals = predictions.get(case_id, [])
        supported = case.get("ground_truth_supported", True)
        if not supported:
            case_rows.append({"case_id": case_id, "status": "UNSUPPORTED_GROUND_TRUTH"})
            continue
        eligible_cases += 1
        candidate_total += len(proposals)
        executable_total += sum(row.get("validation_status") == "VALIDATED_EXECUTABLE" for row in proposals)
        invalid_reference_total += sum(row.get("validation_status") == "INVALID_REFERENCE" for row in proposals)
        identities = [_identity(row) for row in proposals]
        duplicate_total += len(identities) - len(set(identities))
        exact_matches = {level: _match_count(expected, proposals, level, parameter_tolerance)
                         for level in levels}
        item = {"case_id": case_id, "status": "SCORED", "candidate_count": len(proposals),
                "correct": exact_matches}
        for level, hits in exact_matches.items():
            levels[level]["tp"] += hits
            levels[level]["fp"] += max(0, len(proposals) - hits)
            levels[level]["fn"] += max(0, len(expected) - hits)
        parameter_errors = _parameter_errors(expected, proposals, parameter_tolerance)
        item["parameter_errors"] = parameter_errors
        case_rows.append(item)
    return {"status": "MEASURED" if eligible_cases else "NOT_EVALUATED", "case_count": len(cases),
            "supported_case_count": eligible_cases,
            "candidate_count": candidate_total,
            "executable_candidate_count": executable_total,
            "unsupported_candidate_rate": (candidate_total - executable_total) / candidate_total if candidate_total else None,
            "invalid_reference_rate": invalid_reference_total / candidate_total if candidate_total else None,
            "duplicate_hypothesis_rate": duplicate_total / candidate_total if candidate_total else None,
            "levels": {name: _rates(values) for name, values in levels.items()},
            "parameter_error": _summarize([error["relative_error"] for row in case_rows
                                           for error in row.get("parameter_errors", [])]),
            "per_case": case_rows}


def score_ranked_hypotheses(cases: list[dict[str, Any]], truths: dict[str, list[dict[str, Any]]],
                            ranked: dict[str, list[dict[str, Any]]], *, ks=(1, 3)) -> dict[str, Any]:
    if not cases:
        return {"status": "NOT_EVALUATED", "case_count": 0, "top_k_accuracy": {str(k): None for k in ks},
                "mean_reciprocal_rank": None, "coverage": None}
    counts = {k: 0 for k in ks}
    reciprocal_ranks = []
    covered = 0
    per_case = []
    for case in cases:
        case_id = str(case["case_id"])
        if not case.get("ground_truth_supported", True):
            per_case.append({"case_id": case_id, "status": "UNSUPPORTED_GROUND_TRUTH"})
            continue
        truth = truths.get(case_id, [])
        rows = ranked.get(case_id, [])
        expected = {_identity(row) for row in truth}
        first_rank = next((index for index, row in enumerate(rows, 1) if _identity(row) in expected), None)
        covered += int(bool(rows))
        if first_rank:
            reciprocal_ranks.append(1 / first_rank)
        for k in ks:
            counts[k] += int(first_rank is not None and first_rank <= k)
        per_case.append({"case_id": case_id, "status": "SCORED", "ranked_count": len(rows),
                         "correct_rank": first_rank})
    n = sum(row["status"] == "SCORED" for row in per_case)
    return {"status": "MEASURED" if n else "NOT_EVALUATED", "case_count": n,
            "top_k_accuracy": {str(k): counts[k] / n if n else None for k in ks},
            "mean_reciprocal_rank": sum(reciprocal_ranks) / n if n else None,
            "coverage": covered / n if n else None, "per_case": per_case}


def _identity(row: dict[str, Any]) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    params = tuple(sorted((str(k), _normal(v)) for k, v in row.get("parameters", {}).items()))
    return str(row.get("component_ref", "")), str(row.get("fault_type", "")), params


def _normal(value: Any) -> str:
    try:
        return f"{float(value):.12g}"
    except (TypeError, ValueError):
        return str(value).strip().casefold()


def _match_count(expected, predicted, level, tolerance):
    remaining = list(predicted)
    hits = 0
    for truth in expected:
        index = next((i for i, row in enumerate(remaining) if _matches(truth, row, level, tolerance)), None)
        if index is not None:
            hits += 1
            remaining.pop(index)
    return hits


def _matches(truth, prediction, level, tolerance):
    if truth.get("component_ref") != prediction.get("component_ref"):
        return False
    if level == "component":
        return True
    if truth.get("fault_type") != prediction.get("fault_type"):
        return False
    if level == "fault_mode":
        return True
    expected, found = truth.get("parameters", {}), prediction.get("parameters", {})
    if set(expected) != set(found):
        return False
    for key, target in expected.items():
        try:
            a, b = float(target), float(found[key])
            if not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > tolerance * max(abs(a), abs(b), 1.0):
                return False
        except (TypeError, ValueError):
            if str(target).casefold() != str(found[key]).casefold():
                return False
    return True


def _parameter_errors(expected, predictions, tolerance):
    errors = []
    for truth in expected:
        match = next((row for row in predictions if row.get("component_ref") == truth.get("component_ref")
                      and row.get("fault_type") == truth.get("fault_type")), None)
        if not match:
            continue
        for key, target in truth.get("parameters", {}).items():
            try:
                actual, desired = float(match["parameters"][key]), float(target)
                relative = abs(actual - desired) / max(abs(desired), tolerance, 1e-15)
            except (KeyError, TypeError, ValueError):
                continue
            errors.append({"component_ref": truth.get("component_ref"), "parameter": key,
                           "actual": actual, "expected": desired, "relative_error": relative})
    return errors


def _rates(value):
    precision = value["tp"] / (value["tp"] + value["fp"]) if value["tp"] + value["fp"] else None
    recall = value["tp"] / (value["tp"] + value["fn"]) if value["tp"] + value["fn"] else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else 0.0 if precision is not None and recall is not None else None
    return {**value, "precision": precision, "recall": recall, "f1": f1}


def _summarize(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "mae": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {"count": len(values), "mean": sum(values) / len(values), "median": median,
            "mae": sum(values) / len(values)}
