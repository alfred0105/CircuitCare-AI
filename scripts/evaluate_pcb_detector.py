#!/usr/bin/env python3
"""Evaluate single-view or tiled ONNX predictions against YOLO-format labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image

from circuitcare.vision.component_detector import detect_components, detect_components_tiled
from circuitcare.vision.detection_evaluation import evaluate_detections
from circuitcare.vision.detection_postprocess import PCB_MODEL_CLASSES
from circuitcare.vision.detector_backend import model_file_info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True, help="labeled validation image directory")
    parser.add_argument("--labels", type=Path, required=True, help="YOLO label directory, matching image stems")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "pcb_component_detector.onnx")
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    parser.add_argument("--confidence", type=float, default=0.25, help="reported operating confidence threshold")
    parser.add_argument("--mode", choices=("single", "tiled"), default="single")
    parser.add_argument("--tile-size", type=int, default=1536)
    parser.add_argument("--tile-overlap", type=int, default=320)
    parser.add_argument("--confidence-sweep", type=float, nargs="*",
                        default=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60])
    args = parser.parse_args()
    if not 0 <= args.confidence <= 1 or any(not 0 <= value <= 1 for value in args.confidence_sweep):
        parser.error("confidence thresholds must be between 0 and 1")
    model = model_file_info(args.model)
    if model["status"] != "READY":
        parser.error(f"Model unavailable: {model['path']}")
    image_files = sorted(path for path in args.images.iterdir()
                         if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not image_files:
        parser.error(f"No labeled images found in {args.images}")
    ground_truth, predictions, latencies, fingerprints = {}, {}, [], {}
    inference_threshold = min([0.001, args.confidence, *args.confidence_sweep])
    infer = detect_components if args.mode == "single" else detect_components_tiled
    infer_options = {"confidence_threshold": inference_threshold}
    if args.mode == "tiled":
        infer_options.update(tile_size_px=args.tile_size, tile_overlap_px=args.tile_overlap)
    with Image.open(image_files[0]) as opened:
        warmup_image = opened.convert("RGB")
    warmup_start = time.perf_counter()
    warmup = infer(warmup_image, args.model, **infer_options)
    warmup_elapsed_ms = (time.perf_counter() - warmup_start) * 1000
    model_info = warmup.get("model") or model
    for path in image_files:
        label_path = args.labels / f"{path.stem}.txt"
        if not label_path.is_file():
            parser.error(f"Missing label file for {path.name}: {label_path}")
        image_bytes = path.read_bytes()
        label_bytes = label_path.read_bytes()
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        rows = []
        for line_number, line in enumerate(label_bytes.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 5:
                parser.error(f"Invalid YOLO label at {label_path}:{line_number}")
            try:
                class_id, cx, cy, box_w, box_h = int(parts[0]), *map(float, parts[1:])
            except ValueError:
                parser.error(f"Invalid numeric YOLO label at {label_path}:{line_number}")
            if not 0 <= class_id < len(PCB_MODEL_CLASSES):
                parser.error(f"Class index outside model taxonomy at {label_path}:{line_number}")
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < box_w <= 1 and 0 < box_h <= 1):
                parser.error(f"Normalized box outside image bounds at {label_path}:{line_number}")
            if not (0 <= cx - box_w / 2 < cx + box_w / 2 <= 1
                    and 0 <= cy - box_h / 2 < cy + box_h / 2 <= 1):
                parser.error(f"Bounding box corners outside image bounds at {label_path}:{line_number}")
            rows.append({"class_id": class_id,
                "bbox_xyxy": [(cx - box_w / 2) * width, (cy - box_h / 2) * height,
                              (cx + box_w / 2) * width, (cy + box_h / 2) * height]})
        ground_truth[path.name] = rows
        start = time.perf_counter()
        result = infer(image, args.model, **infer_options)
        latencies.append((time.perf_counter() - start) * 1000)
        predictions[path.name] = result["detections"]
        fingerprints[path.name] = {"image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                                   "label_sha256": hashlib.sha256(label_bytes).hexdigest(),
                                   "image_size_px": [width, height], "ground_truth_count": len(rows),
                                   "prediction_count": len(result["detections"])}
    # Per-view residual diagnostics are useful, but image filenames do not
    # establish independent Board IDs or a board-held-out evaluation split.
    per_image = {}
    for image_id in image_files:
        name = image_id.name
        per_image[name] = evaluate_detections({name: ground_truth[name]}, {name: predictions[name]},
            class_names=list(PCB_MODEL_CLASSES), confidence_threshold=args.confidence,
            confidence_thresholds=[args.confidence])
    metrics = evaluate_detections(ground_truth, predictions, class_names=list(PCB_MODEL_CLASSES),
        confidence_threshold=args.confidence, confidence_thresholds=args.confidence_sweep)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = int(peak_rss if sys.platform == "darwin" else peak_rss * 1024)
    source_commit = None
    for directory in (args.images.resolve(), *args.images.resolve().parents):
        try:
            source_commit = subprocess.run(["git", "-C", str(directory), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True).stdout.strip()
            break
        except (OSError, subprocess.CalledProcessError):
            continue
    output = {
        "schema_version": "circuitcare.pcb-detector-evaluation.v2",
        "status": "SOURCE_SPLIT_MEASURED_BOARD_GENERALIZATION_UNVERIFIED",
        "dataset": {"source": "wangshnegqi/pcb-component-detection-dataset-yolo",
            "source_url": "https://github.com/wangshnegqi/pcb-component-detection-dataset-yolo",
            "source_commit": source_commit, "split": "val", "split_method": "SOURCE_PROVIDED_IMAGE_SPLIT",
            "board_level_group_ids": "NOT_PROVIDED_BY_SOURCE", "board_split_leakage": "NOT_EVALUATED",
            "annotation_status": "SOURCE_PROVIDED_UNADJUDICATED", "license": "CC BY 4.0 (source-declared)",
            "image_count": len(image_files), "labeled_object_count": sum(map(len, ground_truth.values())),
            "class_mapping": [{"class_id": index, "class_name": name, "mapping": "IDENTITY"}
                              for index, name in enumerate(PCB_MODEL_CLASSES)],
            "input_fingerprints": fingerprints},
        "model": model_info, "runtime": "onnxruntime-cpu", "inference_mode": args.mode,
        "inference_configuration": {"model_input_size_px": 960, "tile_size_px": args.tile_size if args.mode == "tiled" else None,
            "tile_overlap_px": args.tile_overlap if args.mode == "tiled" else None,
            "raw_prediction_confidence_floor": inference_threshold,
            "reported_confidence_threshold": args.confidence,
            "confidence_threshold_sweep": args.confidence_sweep},
        "first_call_model_load_and_inference_ms": warmup_elapsed_ms,
        "steady_per_image_latency_ms": {"mean": statistics.mean(latencies),
            "median": statistics.median(latencies), "p95": float(__import__("numpy").percentile(latencies, 95)),
            "image_count": len(latencies)},
        "peak_process_rss_bytes": peak_rss_bytes,
        "peak_memory_note": "Process peak RSS includes Python and imported libraries; it is not isolated to ONNX inference.",
        "metrics": metrics, "per_image_metrics": per_image,
        "predictions": predictions,
        "limits": ["Source-provided validation labels were not independently re-reviewed.",
            "The source does not provide board IDs, so same-board leakage and board-level generalization cannot be established.",
            "Source annotations are boxes and classes only; reviewed occlusion, small-component, and identity labels are absent."],
    }
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items()
                      if key not in {"predictions", "per_image_metrics"}}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
