"""Small, deterministic object-detection metrics for labeled YOLO datasets."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def box_iou_xyxy(first: list[float] | np.ndarray, second: list[float] | np.ndarray) -> float:
    a, b = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return float(intersection / max(area_a + area_b - intersection, 1e-12))


def evaluate_detections(ground_truth_by_image: dict[str, list[dict[str, Any]]],
                        predictions_by_image: dict[str, list[dict[str, Any]]], *,
                        class_names: list[str], iou_threshold: float = 0.5,
                        confidence_threshold: float = 0.25) -> dict[str, Any]:
    """Report single-threshold P/R and interpolated AP@IoU for each labeled class."""
    per_class: dict[str, Any] = {}
    for class_id, class_name in enumerate(class_names):
        gt_count = sum(1 for rows in ground_truth_by_image.values() for row in rows if int(row["class_id"]) == class_id)
        predictions = []
        for image_id, rows in predictions_by_image.items():
            for row in rows:
                if row.get("model_class_candidate", row.get("predicted_class", row["class_name"])) == class_name:
                    predictions.append((float(row["confidence"]), image_id, row["bbox_xyxy"]))
        predictions.sort(key=lambda row: row[0], reverse=True)
        matched: dict[str, set[int]] = defaultdict(set)
        true_positive, false_positive = [], []
        for confidence, image_id, box in predictions:
            candidates = [(index, gt) for index, gt in enumerate(ground_truth_by_image.get(image_id, []))
                          if int(gt["class_id"]) == class_id and index not in matched[image_id]]
            best = max(candidates, key=lambda pair: box_iou_xyxy(box, pair[1]["bbox_xyxy"]), default=None)
            if best and box_iou_xyxy(box, best[1]["bbox_xyxy"]) >= iou_threshold:
                matched[image_id].add(best[0])
                true_positive.append(1)
                false_positive.append(0)
            else:
                true_positive.append(0)
                false_positive.append(1)
        tp = np.cumsum(true_positive, dtype=float)
        fp = np.cumsum(false_positive, dtype=float)
        recalls = tp / max(gt_count, 1)
        precisions = tp / np.maximum(tp + fp, 1e-12)
        ap = _average_precision(recalls, precisions) if gt_count else None
        # Recount at the configured confidence cutoff with one-to-one matches.
        p_tp, p_fp = _count_at_threshold(ground_truth_by_image, predictions_by_image, class_id,
                                         class_name, confidence_threshold, iou_threshold)
        precision = p_tp / max(p_tp + p_fp, 1)
        recall = p_tp / max(gt_count, 1)
        per_class[class_name] = {"ground_truth_count": gt_count, "prediction_count": len(predictions),
                                 "precision_at_confidence_threshold": precision if gt_count or predictions else None,
                                 "recall_at_confidence_threshold": recall if gt_count else None,
                                 "ap50": ap}
    valid_aps = [row["ap50"] for row in per_class.values() if row["ap50"] is not None]
    return {"images_evaluated": len(ground_truth_by_image), "iou_threshold": iou_threshold,
            "confidence_threshold_for_precision_recall": confidence_threshold,
            "precision": _aggregate_threshold(ground_truth_by_image, predictions_by_image, class_names,
                                              confidence_threshold, iou_threshold)[0],
            "recall": _aggregate_threshold(ground_truth_by_image, predictions_by_image, class_names,
                                           confidence_threshold, iou_threshold)[1],
            "map50": float(np.mean(valid_aps)) if valid_aps else None, "classes": per_class,
            "note": "Dataset validation split; not an independent board-level test unless its split provenance confirms that."}


def _average_precision(recalls: np.ndarray, precisions: np.ndarray) -> float:
    mrec = np.concatenate(([0.0], recalls, [1.0]))
    mpre = np.concatenate(([1.0], precisions, [0.0]))
    mpre = np.maximum.accumulate(mpre[::-1])[::-1]
    changes = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[changes + 1] - mrec[changes]) * mpre[changes + 1]))


def _count_at_threshold(gt_by_image, preds_by_image, class_id, class_name, confidence_threshold, iou_threshold):
    tp = fp = 0
    matched: dict[str, set[int]] = defaultdict(set)
    all_preds = sorted(((float(row["confidence"]), image_id, row["bbox_xyxy"])
                        for image_id, rows in preds_by_image.items() for row in rows
                        if row.get("model_class_candidate", row.get("predicted_class", row["class_name"])) == class_name
                        and float(row["confidence"]) >= confidence_threshold), reverse=True)
    for _, image_id, box in all_preds:
        candidates = [(index, gt) for index, gt in enumerate(gt_by_image.get(image_id, []))
                      if int(gt["class_id"]) == class_id and index not in matched[image_id]]
        best = max(candidates, key=lambda pair: box_iou_xyxy(box, pair[1]["bbox_xyxy"]), default=None)
        if best and box_iou_xyxy(box, best[1]["bbox_xyxy"]) >= iou_threshold:
            matched[image_id].add(best[0])
            tp += 1
        else:
            fp += 1
    return tp, fp


def _aggregate_threshold(gt_by_image, preds_by_image, class_names, confidence_threshold, iou_threshold):
    total_tp = total_fp = total_gt = 0
    for class_id in range(len(class_names)):
        tp, fp = _count_at_threshold(gt_by_image, preds_by_image, class_id, class_names[class_id],
                                     confidence_threshold, iou_threshold)
        total_tp += tp
        total_fp += fp
        total_gt += sum(int(row["class_id"]) == class_id for rows in gt_by_image.values() for row in rows)
    return total_tp / max(total_tp + total_fp, 1), total_tp / max(total_gt, 1)
