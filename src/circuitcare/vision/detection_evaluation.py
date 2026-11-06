"""Deterministic detection metrics and board-aware annotation manifest checks."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

import numpy as np

ANNOTATION_STATUSES = {"REVIEWED_GROUND_TRUTH", "DRAFT_ANNOTATION", "MODEL_PSEUDO_LABEL", "UNRESOLVED"}
DATASET_SPLITS = {"development", "training", "validation", "sealed_test"}
MIN_CLASS_SUPPORT_FOR_REPORTING = 10


def box_iou_xyxy(first: list[float] | np.ndarray, second: list[float] | np.ndarray) -> float:
    a, b = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if a.shape != (4,) or b.shape != (4,) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return 0.0
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return float(intersection / max(area_a + area_b - intersection, 1e-12))


def validate_board_splits(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reject a board or identical image hash assigned to multiple splits."""
    errors = []
    board_splits: dict[str, set[str]] = defaultdict(set)
    hash_splits: dict[str, set[str]] = defaultdict(set)
    image_ids: set[str] = set()
    for index, row in enumerate(records):
        image_id, board_id, split = row.get("image_id"), row.get("board_id"), row.get("split")
        if not image_id or not board_id or split not in DATASET_SPLITS:
            errors.append({"index": index, "code": "MISSING_ID_OR_INVALID_SPLIT"})
            continue
        image_id = str(image_id)
        if image_id in image_ids:
            errors.append({"index": index, "code": "DUPLICATE_IMAGE_ID", "image_id": image_id})
        image_ids.add(image_id)
        board_splits[str(board_id)].add(str(split))
        digest = row.get("image_sha256")
        if digest:
            hash_splits[str(digest)].add(str(split))
    for board_id, splits in board_splits.items():
        if len(splits) > 1:
            errors.append({"code": "BOARD_SPLIT_LEAKAGE", "board_id": board_id, "splits": sorted(splits)})
    for digest, splits in hash_splits.items():
        if len(splits) > 1:
            errors.append({"code": "IMAGE_HASH_SPLIT_LEAKAGE", "image_sha256": digest, "splits": sorted(splits)})
    return {"status": "VALID" if not errors else "LEAKAGE_OR_MANIFEST_ERROR",
            "image_count": len(image_ids), "board_count": len(board_splits), "errors": errors}


def validate_annotation_manifest(manifest: dict[str, Any], *, class_names: list[str]) -> dict[str, Any]:
    """Validate annotation provenance, coordinate bounds, and board grouping."""
    errors = []
    images = manifest.get("images") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != "circuitcare.component-annotation.v1"
            or not isinstance(images, list)):
        return {"status": "INVALID_MANIFEST", "errors": [{"code": "UNSUPPORTED_SCHEMA_OR_IMAGES"}]}
    split_rows = []
    counts = defaultdict(int)
    reviewed = 0
    for image_index, image in enumerate(images):
        required = ("image_id", "board_id", "board_revision", "board_side", "split", "image_sha256", "image_size_px")
        missing = [key for key in required if image.get(key) is None]
        if missing:
            errors.append({"image_index": image_index, "code": "MISSING_IMAGE_PROVENANCE", "fields": missing})
            continue
        width, height = image["image_size_px"] if len(image["image_size_px"]) == 2 else (0, 0)
        if image["board_side"] not in {"TOP", "BOTTOM"} or width <= 0 or height <= 0:
            errors.append({"image_id": image["image_id"], "code": "INVALID_SIDE_OR_IMAGE_SIZE"})
        split_rows.append({"image_id": image["image_id"], "board_id": image["board_id"],
                           "split": image["split"], "image_sha256": image["image_sha256"]})
        component_ids = set()
        for annotation_index, row in enumerate(image.get("annotations", [])):
            location = {"image_id": image["image_id"], "annotation_index": annotation_index}
            for key in ("component_id", "class", "bbox_xyxy", "occlusion_state", "small_component",
                        "annotation_status", "reviewer", "source"):
                if row.get(key) is None:
                    errors.append({**location, "code": "MISSING_ANNOTATION_FIELD", "field": key})
            if row.get("class") not in class_names:
                errors.append({**location, "code": "UNSUPPORTED_CLASS", "class": row.get("class")})
            status = row.get("annotation_status")
            if status not in ANNOTATION_STATUSES:
                errors.append({**location, "code": "INVALID_ANNOTATION_STATUS", "status": status})
            counts[str(status)] += 1
            if status == "REVIEWED_GROUND_TRUTH":
                reviewed += 1
            component_id = row.get("component_id")
            if component_id and component_id in component_ids:
                errors.append({**location, "code": "DUPLICATE_COMPONENT_ID_IN_IMAGE", "component_id": component_id})
            if component_id:
                component_ids.add(component_id)
            box = row.get("bbox_xyxy")
            try:
                x1, y1, x2, y2 = map(float, box)
                valid_box = all(math.isfinite(value) for value in (x1, y1, x2, y2)) and 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
            except (TypeError, ValueError):
                valid_box = False
            if not valid_box:
                errors.append({**location, "code": "INVALID_BOUNDING_BOX"})
    split_check = validate_board_splits(split_rows)
    errors.extend(split_check["errors"])
    if not manifest.get("dataset_source") or not manifest.get("dataset_license"):
        errors.append({"code": "MISSING_DATASET_PROVENANCE"})
    return {"status": "VALID" if not errors else "INVALID_OR_SPLIT_LEAKAGE",
            "image_count": len(images), "reviewed_ground_truth_count": reviewed,
            "annotation_status_counts": dict(counts), "board_split": split_check, "errors": errors,
            "scoreable_status": ("READY_REVIEWED_LABELS" if not errors and reviewed == sum(counts.values())
                                 and sum(counts.values()) > 0 else
                                 "BLOCKED_UNREVIEWED_ANNOTATIONS" if not errors and reviewed else
                                 "BLOCKED_NO_REVIEWED_GROUND_TRUTH")}


def evaluate_detections(ground_truth_by_image: dict[str, list[dict[str, Any]]],
                        predictions_by_image: dict[str, list[dict[str, Any]]], *,
                        class_names: list[str], iou_threshold: float = 0.5,
                        confidence_threshold: float = 0.25,
                        confidence_thresholds: list[float] | None = None,
                        small_object_area_px2: float = 32.0 * 32.0) -> dict[str, Any]:
    """Class-aware, one-to-one detection metrics at fixed IoU and confidence cuts."""
    per_class: dict[str, Any] = {}
    iou_sweep = [round(value, 2) for value in np.arange(0.5, 0.951, 0.05)]
    ap_by_iou: dict[float, list[float]] = defaultdict(list)
    for class_id, class_name in enumerate(class_names):
        truths = [row for rows in ground_truth_by_image.values() for row in rows if int(row["class_id"]) == class_id]
        gt_count = len(truths)
        predictions = _class_predictions(predictions_by_image, class_name)
        for threshold in iou_sweep:
            ap = _average_precision_for_iou(ground_truth_by_image, predictions, class_id, threshold)
            if gt_count:
                ap_by_iou[threshold].append(ap)
        tp, fp = _count_at_threshold(ground_truth_by_image, predictions_by_image, class_id,
                                     class_name, confidence_threshold, iou_threshold)
        small_gt = [row for row in truths if _box_area(row["bbox_xyxy"]) <= small_object_area_px2]
        small_tp = _count_small_true_positives(ground_truth_by_image, predictions_by_image, class_id,
            class_name, confidence_threshold, iou_threshold, small_object_area_px2)
        per_class[class_name] = {"ground_truth_count": gt_count,
            "support_status": "INSUFFICIENT_SUPPORT" if gt_count < MIN_CLASS_SUPPORT_FOR_REPORTING else "MEASURED",
            "minimum_support_for_reporting": MIN_CLASS_SUPPORT_FOR_REPORTING,
            "prediction_count": len(predictions),
            "true_positive_count": tp, "false_positive_count": fp, "false_negative_count": gt_count - tp,
            "precision_at_confidence_threshold": tp / max(tp + fp, 1) if gt_count or predictions else None,
            "recall_at_confidence_threshold": tp / gt_count if gt_count else None,
            "ap50": _average_precision_for_iou(ground_truth_by_image, predictions, class_id, iou_threshold)
                if gt_count else None,
            "small_object_ground_truth_count": len(small_gt),
            "small_object_recall_at_confidence_threshold": small_tp / len(small_gt) if small_gt else None}
    valid_ap50 = [row["ap50"] for row in per_class.values() if row["ap50"] is not None]
    map_by_iou = {f"{threshold:.2f}": float(np.mean(values)) if values else None
                  for threshold, values in ap_by_iou.items()}
    sweep_thresholds = confidence_thresholds or [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60]
    threshold_curve = []
    for threshold in sweep_thresholds:
        tp, fp, gt = _aggregate_counts(ground_truth_by_image, predictions_by_image,
                                       class_names, threshold, iou_threshold)
        threshold_curve.append({"confidence_threshold": threshold, "true_positives": tp,
            "false_positives": fp, "false_negatives": gt - tp,
            "precision": tp / max(tp + fp, 1), "recall": tp / max(gt, 1),
            "f1": 2 * tp / max(2 * tp + fp + gt - tp, 1)})
    total_tp, total_fp, total_gt = _aggregate_counts(ground_truth_by_image, predictions_by_image,
        class_names, confidence_threshold, iou_threshold)
    return {"images_evaluated": len(ground_truth_by_image), "iou_threshold": iou_threshold,
        "confidence_threshold_for_precision_recall": confidence_threshold,
        "precision": total_tp / max(total_tp + total_fp, 1), "recall": total_tp / max(total_gt, 1),
        "f1": 2 * total_tp / max(2 * total_tp + total_fp + total_gt - total_tp, 1),
        "true_positive_count": total_tp, "false_positive_count": total_fp,
        "false_negative_count": total_gt - total_tp,
        "map50": float(np.mean(valid_ap50)) if valid_ap50 else None,
        "map50_95": float(np.mean([value for value in map_by_iou.values() if value is not None]))
            if any(value is not None for value in map_by_iou.values()) else None,
        "map_by_iou_threshold": map_by_iou, "confidence_threshold_curve": threshold_curve,
        "small_object_area_px2_cutoff": small_object_area_px2,
        "classes": per_class,
        "note": "Scores apply only to supplied annotations/split. They are not board-independent without verified board-group provenance."}


def _class_predictions(predictions_by_image, class_name):
    rows = []
    for image_id, predictions in predictions_by_image.items():
        for row in predictions:
            predicted_class = row.get("model_class_candidate", row.get("predicted_class", row["class_name"]))
            if predicted_class == class_name:
                rows.append((float(row["confidence"]), image_id, row["bbox_xyxy"]))
    return sorted(rows, key=lambda row: row[0], reverse=True)


def _average_precision_for_iou(gt_by_image, predictions, class_id, iou_threshold):
    gt_count = sum(int(row["class_id"]) == class_id for rows in gt_by_image.values() for row in rows)
    if not gt_count:
        return 0.0
    matched: dict[str, set[int]] = defaultdict(set)
    tp, fp = [], []
    for _, image_id, box in predictions:
        candidates = [(index, gt) for index, gt in enumerate(gt_by_image.get(image_id, []))
                      if int(gt["class_id"]) == class_id and index not in matched[image_id]]
        best = max(candidates, key=lambda pair: box_iou_xyxy(box, pair[1]["bbox_xyxy"]), default=None)
        if best and box_iou_xyxy(box, best[1]["bbox_xyxy"]) >= iou_threshold:
            matched[image_id].add(best[0]); tp.append(1); fp.append(0)
        else:
            tp.append(0); fp.append(1)
    cumulative_tp = np.cumsum(tp, dtype=float)
    cumulative_fp = np.cumsum(fp, dtype=float)
    return _average_precision(cumulative_tp / gt_count, cumulative_tp / np.maximum(cumulative_tp + cumulative_fp, 1e-12))


def _average_precision(recalls: np.ndarray, precisions: np.ndarray) -> float:
    mrec = np.concatenate(([0.0], recalls, [1.0]))
    mpre = np.concatenate(([1.0], precisions, [0.0]))
    mpre = np.maximum.accumulate(mpre[::-1])[::-1]
    changes = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[changes + 1] - mrec[changes]) * mpre[changes + 1]))


def _count_at_threshold(gt_by_image, preds_by_image, class_id, class_name, confidence_threshold, iou_threshold):
    matched: dict[str, set[int]] = defaultdict(set)
    rows = sorted(((float(row["confidence"]), image_id, row["bbox_xyxy"])
                   for image_id, detections in preds_by_image.items() for row in detections
                   if row.get("model_class_candidate", row.get("predicted_class", row["class_name"])) == class_name
                   and float(row["confidence"]) >= confidence_threshold), reverse=True)
    tp = fp = 0
    for _, image_id, box in rows:
        candidates = [(index, gt) for index, gt in enumerate(gt_by_image.get(image_id, []))
                      if int(gt["class_id"]) == class_id and index not in matched[image_id]]
        best = max(candidates, key=lambda pair: box_iou_xyxy(box, pair[1]["bbox_xyxy"]), default=None)
        if best and box_iou_xyxy(box, best[1]["bbox_xyxy"]) >= iou_threshold:
            matched[image_id].add(best[0]); tp += 1
        else:
            fp += 1
    return tp, fp


def _aggregate_counts(gt_by_image, preds_by_image, class_names, confidence_threshold, iou_threshold):
    total_tp = total_fp = total_gt = 0
    for class_id, class_name in enumerate(class_names):
        tp, fp = _count_at_threshold(gt_by_image, preds_by_image, class_id, class_name,
                                     confidence_threshold, iou_threshold)
        total_tp += tp; total_fp += fp
        total_gt += sum(int(row["class_id"]) == class_id for rows in gt_by_image.values() for row in rows)
    return total_tp, total_fp, total_gt


def _box_area(box):
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


def _count_small_true_positives(gt_by_image, preds_by_image, class_id, class_name,
                                confidence_threshold, iou_threshold, area_limit):
    tp = 0
    for image_id, predictions in preds_by_image.items():
        eligible = [gt for gt in gt_by_image.get(image_id, []) if int(gt["class_id"]) == class_id
                    and _box_area(gt["bbox_xyxy"]) <= area_limit]
        if not eligible:
            continue
        matches = set()
        rows = sorted((row for row in predictions if row.get("model_class_candidate",
            row.get("predicted_class", row["class_name"])) == class_name
            and float(row["confidence"]) >= confidence_threshold),
            key=lambda row: float(row["confidence"]), reverse=True)
        for prediction in rows:
            candidates = [(index, gt) for index, gt in enumerate(eligible) if index not in matches]
            best = max(candidates, key=lambda pair: box_iou_xyxy(prediction["bbox_xyxy"], pair[1]["bbox_xyxy"]), default=None)
            if best and box_iou_xyxy(prediction["bbox_xyxy"], best[1]["bbox_xyxy"]) >= iou_threshold:
                matches.add(best[0]); tp += 1
    return tp
