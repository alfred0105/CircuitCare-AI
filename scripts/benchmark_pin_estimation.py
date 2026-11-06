#!/usr/bin/env python3
"""Run the lightweight pin hypothesis engine on synthetic or supplied component maps."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from circuitcare.vision.pin_estimation import estimate_component, estimate_component_map


def synthetic_fixtures() -> list[tuple[dict[str, Any], np.ndarray, list[list[float]]]]:
    fixtures = []
    cases = [
        ("horizontal", [42, 56, 82, 68], [[42, 56], [82, 56], [82, 68], [42, 68]],
         [[38, 62], [86, 62]]),
        ("vertical", [55, 42, 67, 82], [[55, 42], [67, 42], [67, 82], [55, 82]],
         [[61, 38], [61, 86]]),
        ("rotated", [50, 50, 78, 78], [[50, 58], [58, 50], [78, 70], [70, 78]],
         [[51, 51], [77, 77]]),
    ]
    for name, bbox, polygon, expected in cases:
        image = Image.new("RGB", (128, 128), (24, 35, 40))
        draw = ImageDraw.Draw(image)
        # Pale metallic pads are rendered outside a dark component body.
        for x, y in expected:
            draw.rectangle((x - 3, y - 3, x + 3, y + 3), fill=(220, 220, 220))
        if name == "rotated":
            draw.polygon(polygon, fill=(45, 45, 45))
        else:
            draw.rectangle((bbox[0], bbox[1], bbox[2], bbox[3]), fill=(45, 45, 45))
        fixtures.append(({"component_id": f"synthetic-{name}", "component_type": "resistor",
                          "bbox_xyxy": bbox, "polygon_xy": polygon,
                          "source_image_ids": [f"synthetic-photo-{name}"]},
                         np.asarray(image), expected))
    return fixtures


def evaluate_synthetic(fixtures: list[tuple[dict[str, Any], np.ndarray, list[list[float]]]],
                       tolerance_px: float = 8.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    outputs = []
    errors = []
    tp = fp = fn = 0
    started = time.perf_counter()
    for component, image, truth_points in fixtures:
        estimate = estimate_component(component, board_side="TOP", image_rgb=image).to_dict()
        terminals = estimate["terminals"]
        predicted_points = [row["position_xy"] for row in terminals if row["position_status"] == "OBSERVED_TERMINAL"]
        unmatched = set(range(len(predicted_points)))
        for truth in truth_points:
            candidates = [(float(np.linalg.norm(np.asarray(point) - np.asarray(truth))), index)
                          for index, point in enumerate(predicted_points) if index in unmatched]
            if candidates:
                distance, index = min(candidates)
                if distance <= tolerance_px:
                    tp += 1
                    unmatched.remove(index)
                    errors.append(distance)
                    continue
            fn += 1
        fp += len(unmatched)
        outputs.append(estimate)
    elapsed_ms = (time.perf_counter() - started) * 1000
    metrics = {"evaluation_status": "SYNTHETIC_FIXTURE_ONLY",
        "terminal_localization_tolerance_px": tolerance_px,
        "terminal_precision": tp / max(tp + fp, 1), "terminal_recall": tp / max(tp + fn, 1),
        "terminal_true_positive_count": tp, "terminal_false_positive_count": fp,
        "terminal_false_negative_count": fn,
        "localization_error_px_mean": float(np.mean(errors)) if errors else None,
        "localization_error_px_p95": float(np.percentile(errors, 95)) if errors else None,
        "package_classification_accuracy": "NOT_EVALUATED",
        "pin_number_assignment_accuracy": "NOT_EVALUATED",
        "real_pcb_accuracy": "NOT_EVALUATED",
        "component_count": len(fixtures), "runtime_ms_total": elapsed_ms,
        "runtime_ms_per_component": elapsed_ms / max(len(fixtures), 1)}
    return outputs, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", choices=("synthetic",))
    source.add_argument("--component-map", type=Path,
        help="Component Map JSON with an optional embedded canonical PNG for each board side")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.fixture == "synthetic":
        fixtures = synthetic_fixtures()
        components, metrics = evaluate_synthetic(fixtures)
        result = {"schema_version": "circuitcare.pcb-pin-benchmark.v1",
            "evaluation_status": metrics["evaluation_status"], "input_kind": "SYNTHETIC_FIXTURE",
            "metrics": metrics, "components": components,
            "limitations": ["Synthetic geometry does not measure real PCB accuracy.",
                "The heuristic appearance score is not a calibrated probability.",
                "Electrical connectivity and pin functions are not evaluated."]}
    else:
        component_map = json.loads(args.component_map.read_text(encoding="utf-8"))
        started = time.perf_counter()
        hypotheses = estimate_component_map(component_map)
        runtime_ms = (time.perf_counter() - started) * 1000
        result = {"schema_version": "circuitcare.pcb-pin-benchmark.v1",
            "evaluation_status": "NOT_EVALUATED_NO_PIN_GROUND_TRUTH",
            "input_kind": "COMPONENT_MAP", "runtime_ms_total": runtime_ms,
            "metrics": {"terminal_precision": "NOT_EVALUATED", "terminal_recall": "NOT_EVALUATED",
                "terminal_count_accuracy": "NOT_EVALUATED", "localization_error_px": "NOT_EVALUATED",
                "package_classification_accuracy": "NOT_EVALUATED", "pin_number_assignment_accuracy": "NOT_EVALUATED"},
            "pin_hypotheses": hypotheses}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema_version", "evaluation_status", "input_kind", "metrics")},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
