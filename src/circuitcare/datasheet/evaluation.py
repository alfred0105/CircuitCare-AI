"""One-to-one benchmark metrics for rule and rule-plus-LLM ratings."""

from typing import Any
import unicodedata


def score_extractions(ground_truth: list[dict[str, Any]], predictions: list[dict[str, Any]], *, latency_seconds: float | None = None) -> dict[str, Any]:
    if not ground_truth:
        return {"status": "NOT_EVALUATED", "ground_truth_count": 0, "candidate_count": len(predictions),
                "precision": None, "recall": None, "f1": None, "value_accuracy": None,
                "unit_accuracy": None, "rating_kind_accuracy": None, "condition_accuracy": None,
                "page_evidence_accuracy": None, "table_context_accuracy": None}
    unmatched = set(range(len(predictions)))
    matched = []
    for truth in ground_truth:
        candidates = [index for index in unmatched if truth.get("rating_key") == predictions[index].get("rating_key")
                      and (not truth.get("document_id") or not predictions[index].get("document_id")
                           or truth.get("document_id") == predictions[index].get("document_id"))]
        if not candidates:
            continue
        index = max(candidates, key=lambda value: _match_score(truth, predictions[value]))
        matched.append((truth, predictions[index]))
        unmatched.remove(index)
    correct = []
    for truth, prediction in matched:
        correct.append({
            "value": _number_equal(truth.get("value"), prediction.get("normalized_value")),
            "unit": truth.get("unit") == prediction.get("normalized_unit"),
            "kind": truth.get("rating_kind") == prediction.get("rating_kind"),
            "condition": _conditions_equal(truth.get("conditions", {}), prediction.get("conditions", {})),
            "evidence": truth.get("pdf_page_index") == prediction.get("pdf_page_index") and (
                _quote_in_page(prediction.get("source_text", ""), truth.get("evidence_text", ""))
                or _quote_in_page(truth.get("evidence_text", ""), prediction.get("source_text", ""))),
            "table_context": _table_context_equal(truth.get("table_context"), prediction.get("table_context")),
            "candidate": (_number_equal(truth.get("value"), prediction.get("normalized_value"))
                and truth.get("unit") == prediction.get("normalized_unit")
                and truth.get("rating_kind") == prediction.get("rating_kind")),
        })
    predicted = len(predictions)
    true_positive = sum(bool(row["candidate"]) for row in correct)
    precision = true_positive / predicted if predicted else None
    recall = true_positive / len(ground_truth)
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and precision + recall else (0.0 if precision == 0 else None)
    def ratio(key: str) -> float | None:
        applicable = [row for row in correct if row[key] is not None]
        return sum(bool(row[key]) for row in applicable) / len(applicable) if applicable else None
    rejected = sum(prediction.get("evidence_status") in {"SOURCE_MISMATCH", "SOURCE_NOT_FOUND", "SOURCE_AMBIGUOUS"}
                   for prediction in predictions)
    return {"status": "MEASURED", "ground_truth_count": len(ground_truth), "candidate_count": predicted,
            "matched_by_rating_key": len(matched), "true_positive_count": true_positive,
            "precision": precision, "recall": recall, "f1": f1,
            "value_accuracy": ratio("value"), "unit_accuracy": ratio("unit"),
            "rating_kind_accuracy": ratio("kind"), "condition_accuracy": ratio("condition"),
            "page_evidence_accuracy": ratio("evidence"), "table_context_accuracy": ratio("table_context"),
            "unsupported_claim_rate": 1.0 - precision if precision is not None else None,
            "source_verification_rejection_rate": rejected / predicted if predicted else None,
            "latency_seconds": latency_seconds,
            "condition_evaluable_count": sum(row["condition"] is not None for row in correct),
            "evidence_evaluable_count": sum(row["evidence"] is not None for row in correct)}


def _number_equal(expected: Any, actual: Any) -> bool:
    try:
        value, candidate = float(expected), float(actual)
        return abs(value - candidate) <= max(1e-9, abs(value) * 1e-6)
    except (TypeError, ValueError):
        return False


def _match_score(truth: dict[str, Any], prediction: dict[str, Any]) -> tuple[int, ...]:
    return (
        int(_number_equal(truth.get("value"), prediction.get("normalized_value"))),
        int(truth.get("unit") == prediction.get("normalized_unit")),
        int(truth.get("rating_kind") == prediction.get("rating_kind")),
        int(truth.get("pdf_page_index") == prediction.get("pdf_page_index")),
        int(_conditions_equal(truth.get("conditions", {}), prediction.get("conditions", {})) is True),
        int(_table_context_equal(truth.get("table_context"), prediction.get("table_context")) is True),
    )


def _conditions_equal(expected: dict[str, Any], actual: dict[str, Any]) -> bool | None:
    keys = [key for key in ("temperature_c", "duration", "polarity") if expected.get(key) is not None]
    if not keys:
        return None
    return all(expected.get(key) == actual.get(key) for key in keys)


def _quote_in_page(expected: str, actual: str) -> bool:
    return bool(expected and actual and _normalize(expected) in _normalize(actual))


def _normalize(text: str) -> str:
    return " ".join("".join(char for char in text if unicodedata.category(char) != "Cf").split()).casefold()


def _table_context_equal(expected: Any, actual: Any) -> bool | None:
    if expected is None:
        return None
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    aliases = {"row_label": "row_label", "variant": "variant", "column": "column_header", "cell": "cell_text"}
    for key, actual_key in aliases.items():
        actual_value = actual.get(actual_key, actual.get(key, ""))
        if key in expected and _normalize(str(expected.get(key, ""))) != _normalize(str(actual_value)):
            return False
    return True
