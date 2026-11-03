"""Stable public entry point for trained PCB component detection."""

from __future__ import annotations

from typing import Any

from circuitcare.vision.detector_backend import run_detector
from circuitcare.vision.detection_postprocess import PCB_MODEL_CLASSES

CORRECTABLE_CLASSES = (*PCB_MODEL_CLASSES, "unknown_component")


def detect_components(image: Any, model_path: str, *, confidence_threshold: float = 0.25,
                      iou_threshold: float = 0.45) -> dict[str, Any]:
    """Run the configured trained PCB object detector; this is not contour detection."""
    return run_detector(image, model_path, confidence_threshold=confidence_threshold,
                         iou_threshold=iou_threshold)


def apply_detection_corrections(detections: list[dict[str, Any]],
                                corrections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return corrected copies while preserving model predictions as separate evidence."""
    result = []
    used_references: set[str] = set()
    for detection in detections:
        correction = corrections.get(detection["detection_id"], {})
        row = dict(detection)
        row["predicted_class"] = detection.get("predicted_class", detection["class_name"])
        corrected_class = correction.get("corrected_class")
        if corrected_class:
            if corrected_class not in CORRECTABLE_CLASSES:
                raise ValueError(f"지원하지 않는 수정 부품 종류입니다: {corrected_class}")
            row["corrected_class"] = corrected_class
        else:
            row["corrected_class"] = None
        row["predicted_reference"] = detection.get("predicted_reference", detection.get("reference"))
        confirmed_reference = str(correction.get("confirmed_reference") or "").strip().upper() or None
        if confirmed_reference and correction.get("reference_confirmed"):
            if confirmed_reference in used_references:
                raise ValueError(f"KiCad Reference {confirmed_reference}가 여러 검출에 중복 지정되었습니다.")
            used_references.add(confirmed_reference)
            row["confirmed_reference"] = confirmed_reference
            row["verification_source"] = "user_manual_confirmation"
            row["identification_status"] = "user_confirmed"
        else:
            row["confirmed_reference"] = None
            row["verification_source"] = None
            row["identification_status"] = "rejected" if correction.get("rejected") else "suggested" if correction.get("confirmed_reference") else "unmatched"
        row["is_rejected"] = bool(correction.get("rejected"))
        if not row["is_rejected"]:
            result.append(row)
    return result


def add_manual_detection(detections: list[dict[str, Any]], *, class_name: str,
                         bbox_xyxy: list[float], image_size: tuple[int, int]) -> dict[str, Any]:
    if class_name not in CORRECTABLE_CLASSES:
        raise ValueError(f"지원하지 않는 부품 종류입니다: {class_name}")
    x1, y1, x2, y2 = map(float, bbox_xyxy)
    width, height = image_size
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("수동 Bounding Box가 이미지 경계 안의 유효한 사각형이 아닙니다.")
    used = {row["detection_id"] for row in detections}
    number = len(detections) + 1
    detection_id = f"manual_{number:04d}"
    while detection_id in used:
        number += 1
        detection_id = f"manual_{number:04d}"
    return {"detection_id": detection_id, "class_name": class_name, "confidence": None,
            "bbox_xyxy": [x1, y1, x2, y2], "source": "user_manual_addition", "model_id": None,
            "reference": None, "identification_status": "class_candidate", "predicted_class": None}
