#!/usr/bin/env python3
"""Report PCB detection metrics separately from reviewed empty-board/breadboard false positives."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PIL import Image
from circuitcare.vision.component_detector import detect_components


def evaluate_negatives(model: Path, review_manifest: Path, *, confidence: float, nms_iou: float) -> dict:
    review = json.loads(review_manifest.read_text())
    grouped = defaultdict(list)
    for row in review["images"]:
        if not row.get("hard_negative_eligible"):
            continue
        image_path = ROOT / "data" / "component_training" / row["image_path"]
        start = time.perf_counter()
        result = detect_components(Image.open(image_path).convert("RGB"), str(model),
                                   confidence_threshold=confidence, iou_threshold=nms_iou)
        elapsed_ms = (time.perf_counter() - start) * 1000
        detections = result.get("detections", [])
        grouped[row["image_type"]].append({"image_id": row["image_id"],
            "board_group_id": row.get("board_group_id"), "false_positive_count": len(detections),
            "has_false_positive": bool(detections), "inference_latency_ms": elapsed_ms})
    metrics = {}
    for domain in ("BARE_PCB", "BREADBOARD"):
        rows = grouped[domain]
        n = len(rows)
        metrics[domain] = {"image_count": n,
            "image_level_false_positive_rate": sum(row["has_false_positive"] for row in rows) / n if n else None,
            "mean_false_positives_per_image": sum(row["false_positive_count"] for row in rows) / n if n else None,
            "total_false_positives": sum(row["false_positive_count"] for row in rows),
            "status": "MEASURED_REVIEWED_EMPTY_IMAGES" if n else "NO_REVIEWED_IMAGES",
            "per_image": rows}
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--evaluation-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    args = parser.parse_args()
    if not args.model.is_file(): parser.error(f"model does not exist: {args.model}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    positive_output = args.output.with_name(args.output.stem + "-positive-pcb.json")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_pcb_detector.py"),
        "--dataset-manifest", str(args.evaluation_manifest), "--model", str(args.model),
        "--confidence", str(args.confidence), "--nms-iou", str(args.nms_iou),
        "--output", str(positive_output)], check=True, capture_output=True, text=True)
    positive = json.loads(positive_output.read_text())
    negatives = evaluate_negatives(args.model, args.review_manifest,
                                   confidence=args.confidence, nms_iou=args.nms_iou)
    report = {"status": "DEVELOPMENT_ONLY_BOARD_GROUP_VALIDATION",
        "confidence_threshold": args.confidence, "nms_iou_threshold": args.nms_iou,
        "positive_pcb": {"evaluation_status": positive["evaluation_status"],
            "image_count": positive["dataset"]["image_count"],
            "manual_board_group_count": len({row.get("board_id") for row in
                positive["dataset"]["input_fingerprints"].values() if row.get("board_id")}),
            "metrics": positive["metrics"],
            "latency": positive["steady_per_image_latency_ms"],
            "peak_process_rss_bytes": positive["peak_process_rss_bytes"]},
        "reviewed_empty_domain_metrics": negatives,
        "limits": ["Source annotations are not independently adjudicated.",
            "Board groups are manual visual groups, not source-verified physical board IDs.",
            "No sealed independent test split is available."]}
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"output": str(args.output.resolve()), "positive_image_count": positive["dataset"]["image_count"],
                      "negative_counts": {k: v["image_count"] for k, v in negatives.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
