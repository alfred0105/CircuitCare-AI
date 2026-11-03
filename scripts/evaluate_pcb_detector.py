#!/usr/bin/env python3
"""Evaluate the optional ONNX detector against a labeled YOLO-format validation split."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image

from circuitcare.vision.detection_evaluation import evaluate_detections
from circuitcare.vision.detection_postprocess import PCB_MODEL_CLASSES
from circuitcare.vision.component_detector import detect_components


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True, help="labeled validation image directory")
    parser.add_argument("--labels", type=Path, required=True, help="YOLO label directory with matching image stems")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "pcb_component_detector.onnx")
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    parser.add_argument("--confidence", type=float, default=0.25)
    args = parser.parse_args()
    image_files = sorted(path for path in args.images.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not image_files:
        parser.error(f"No labeled images found in {args.images}")
    ground_truth, predictions, elapsed = {}, {}, []
    first_start = time.perf_counter()
    with Image.open(image_files[0]) as opened:
        warmup_image = opened.convert("RGB")
    detect_components(warmup_image, str(args.model), confidence_threshold=args.confidence)
    first_call_elapsed_ms = (time.perf_counter() - first_start) * 1000
    for path in image_files:
        label_path = args.labels / f"{path.stem}.txt"
        if not label_path.is_file():
            parser.error(f"Missing label file for {path.name}: {label_path}")
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        rows = []
        for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 5:
                parser.error(f"Invalid YOLO label at {label_path}:{line_number}")
            class_id, cx, cy, box_w, box_h = int(parts[0]), *map(float, parts[1:])
            if not 0 <= class_id < len(PCB_MODEL_CLASSES):
                parser.error(f"Class index outside model taxonomy at {label_path}:{line_number}")
            rows.append({"class_id": class_id,
                         "bbox_xyxy": [(cx - box_w / 2) * width, (cy - box_h / 2) * height,
                                       (cx + box_w / 2) * width, (cy + box_h / 2) * height]})
        ground_truth[path.name] = rows
        started = time.perf_counter()
        result = detect_components(image, str(args.model), confidence_threshold=args.confidence)
        elapsed.append((time.perf_counter() - started) * 1000)
        predictions[path.name] = result["detections"]
    metrics = evaluate_detections(ground_truth, predictions, class_names=list(PCB_MODEL_CLASSES),
                                  confidence_threshold=args.confidence)
    output = {"dataset": {"images_dir": str(args.images.resolve()), "labels_dir": str(args.labels.resolve()),
                          "image_count": len(image_files), "labeled_object_count": sum(map(len, ground_truth.values())),
                          "license_declared_by_source": "CC BY 4.0", "source": "wangshnegqi/pcb-component-detection-dataset-yolo"},
              "model": result["model"], "runtime": result["runtime"], "input_size_px": result["input_size_px"],
              "first_call_model_load_and_inference_ms": first_call_elapsed_ms,
              "mean_cpu_inference_ms_per_image_after_model_load": statistics.mean(elapsed),
              "median_cpu_inference_ms_per_image_after_model_load": statistics.median(elapsed),
              "metrics": metrics, "predictions": predictions}
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "predictions"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
