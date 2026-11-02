"""Single-question conversation turn and output grounding validation."""

import re
from typing import Any

from .llm_prompts import build_messages
from .local_llm import OllamaClient

_NUMBERS = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?%?")
_EVIDENCE_ID = re.compile(r"\bE\d{3,}\b")
_REQUIRED_ARRAYS = ("facts", "assumptions", "recommendations", "unknowns")


def answer_question(client: OllamaClient, model: str, question: str, evidence: dict[str, Any], repair_advice: dict[str, Any]) -> dict[str, Any]:
    response = client.chat_json(model, build_messages(question, evidence, repair_advice))
    content = response["content"]
    reason = validate_explanation(content, evidence, question=question)
    return {
        "status": "success" if reason is None else "rejected",
        "question": question,
        "model": response["model"],
        "model_info": response["model_info"],
        "json_mode": response["json_mode"],
        "response": content if reason is None else None,
        "rejected_response": content if reason is not None else None,
        "validation_error": reason,
        "validation": {"evidence_ids_checked": True, "numeric_claims_checked": True},
        "inference": {key: response.get(key) for key in ("done", "done_reason", "total_duration_ns", "eval_count")},
    }


def validate_explanation(content: dict[str, Any], evidence: dict[str, Any], *, question: str = "") -> str | None:
    if not isinstance(content.get("answer"), str) or not content["answer"].strip():
        return "The JSON response is missing a non-empty answer."
    for key in _REQUIRED_ARRAYS:
        if not isinstance(content.get(key), list):
            return f"The JSON response field {key!r} must be an array."
    valid_ids = {item["evidence_id"] for item in evidence.get("facts", []) if item.get("evidence_id")}
    texts = [content["answer"]]
    for key in _REQUIRED_ARRAYS:
        for item in content[key]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                return f"Every {key} item must contain a text string."
            cited = item.get("evidence_ids")
            if not isinstance(cited, list) or any(identifier not in valid_ids for identifier in cited):
                return f"The response contains a missing or unknown evidence ID in {key}."
            if key == "facts" and not cited:
                return "Every factual response item must cite at least one evidence ID."
            texts.append(item["text"])
    demo_rating_ids = {
        item.get("evidence_id") for item in evidence.get("facts", [])
        if item.get("source_type") == "demo_assumption" and "rating" in item.get("metric", "")
    }
    response_citations = {
        identifier for key in _REQUIRED_ARRAYS for item in content[key] for identifier in item.get("evidence_ids", [])
    }
    if demo_rating_ids & response_citations and not any(
        any(token in item["text"].casefold() for token in ("시연용", "시연 가정", "가정값", "demo assumption", "not manufacturer-verified", "데이터시트 검증"))
        for item in content["assumptions"]
    ):
        return "The response did not identify a demo-assumption rating as unverified."
    if any("damage has not been confirmed" in str(item).casefold() or "손상" in str(item) for item in evidence.get("unknowns", [])):
        if not any(
            "손상" in item["text"] and any(word in item["text"] for word in ("미확인", "확인되지", "확정되지", "판단할 수 없", "아닙니다"))
            or "damage" in item["text"].casefold() and any(word in item["text"].casefold() for word in ("not confirmed", "not established", "unknown"))
            for item in content["unknowns"]
        ):
            return "The response did not state that physical damage remains unconfirmed."
    joined = "\n".join(texts)
    if _contains_unsupported_safety_claim(joined):
        return "The response makes an unsupported claim of confirmed damage or safety."
    unknown_ids = set(_EVIDENCE_ID.findall(joined)) - valid_ids
    if unknown_ids:
        return "The response cites an unknown evidence ID."
    if not (set(_EVIDENCE_ID.findall(content["answer"])) & valid_ids):
        return "The answer must cite at least one supplied evidence ID."
    allowed = _numeric_evidence_values(evidence)
    # A number quoted from the user's question may be repeated to answer or correct it;
    # it remains marked as user input and is not treated as a calculated fact.
    allowed.extend(float(token.rstrip("%")) for token in _NUMBERS.findall(question))
    scrubbed = _EVIDENCE_ID.sub("", joined)
    for token in _NUMBERS.findall(scrubbed):
        numeric_text = token.rstrip("%")
        try:
            number = float(numeric_text)
        except ValueError:
            continue
        if not any(abs(number - value) <= max(1e-9, abs(value) * 1e-8) for value in allowed):
            return f"The response contains an unsupported numeric claim: {token}"
    return None


def _numeric_evidence_values(value: Any) -> list[float]:
    output = []
    if isinstance(value, bool) or value is None:
        return output
    if isinstance(value, (int, float)):
        output.append(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            output.extend(_numeric_evidence_values(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(_numeric_evidence_values(item))
    return output


def _contains_unsupported_safety_claim(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    forbidden = (
        "손상이확정되었습니다", "손상이확인되었습니다", "손상된상태입니다", "손상되었습니다",
        "고장이확정되었습니다", "고장으로확정되었습니다", "확실히고장났습니다",
        "정상으로확인되었습니다", "안전하다고확인되었습니다", "100%고장입니다", "100%손상입니다",
    )
    return any(phrase in normalized for phrase in forbidden)
