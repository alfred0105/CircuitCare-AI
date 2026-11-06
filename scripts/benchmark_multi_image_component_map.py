#!/usr/bin/env python3
"""Reproducible synthetic smoke benchmark; not real-board accuracy evaluation."""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from circuitcare.vision.reconstruction.multi_image_component_map import (
    CaptureRole, MultiImageComponentMapService, PhotoInput,
)


def run() -> dict:
    rng = np.random.default_rng(216)
    pixels = rng.integers(0, 256, (420, 660, 3), dtype=np.uint8)
    source = np.asarray(Image.fromarray(pixels).filter(ImageFilter.GaussianBlur(0.8))).copy()
    crops = (source[:, :420], source[:, 120:540], source[:, 240:660])
    encoded = []
    for crop in crops:
        buffer = io.BytesIO()
        Image.fromarray(crop).save(buffer, format="PNG")
        encoded.append(buffer.getvalue())
    service = MultiImageComponentMapService()
    session = service.ingest("synthetic-board", [
        PhotoInput(encoded[0], "TOP", CaptureRole.REFERENCE, "view-a.png"),
        PhotoInput(encoded[1], "TOP", CaptureRole.OVERVIEW, "view-b.png"),
        PhotoInput(encoded[2], "TOP", CaptureRole.CLOSEUP, "view-c.png"),
    ])
    start = time.perf_counter()
    result = service.build_map(session)
    elapsed = time.perf_counter() - start
    side = result["sides"]["TOP"]
    records = {record["photo_id"]: record for record in side["registrations"]}
    errors = []
    for photo, dx in zip(session.photos, (0, 120, 240)):
        matrix = np.asarray(records[photo.photo_id]["transform_moving_to_canonical"])
        predicted = matrix @ np.array([0.0, 200.0, 1.0])
        predicted = predicted[:2] / predicted[2]
        errors.append(float(np.linalg.norm(predicted - np.array([dx, 200.0]))))
    expected_canvas = [660, 420]
    return {
        "schema_version": "circuitcare.phase21.2.synthetic-benchmark.v1",
        "track": "SYNTHETIC_GEOMETRY_ONLY_NOT_REAL_PHOTO_ACCURACY",
        "seed": 216, "input_views": 3, "input_size_px": [420, 420],
        "known_crop_offsets_px": [0, 120, 240],
        "registration_status_counts": _count(record["status"] for record in records.values()),
        "registered_inlier_ratios": [record["inlier_ratio"] for record in records.values()],
        "registered_rmse_px": [record["rmse_px"] for record in records.values()],
        "registered_p95_reprojection_error_px": [record["p95_reprojection_error_px"] for record in records.values()],
        "known_translation_error_px": errors,
        "mosaic_size_px": side["canonical_image"]["image_size_px"],
        "expected_mosaic_size_px": expected_canvas,
        "expected_scene_coverage_ratio": min(1.0, side["canonical_image"]["image_size_px"][0]
                                             * side["canonical_image"]["image_size_px"][1]
                                             / (expected_canvas[0] * expected_canvas[1])),
        "runtime_seconds": elapsed,
        "component_detection_metrics": "NOT_EVALUATED_NO_INDEPENDENT_ANNOTATIONS",
        "fault_overlay": "UNIT_TESTED_WITH_INJECTED_DETECTIONS_ONLY",
        "host_timing_note": "One local run; timings are diagnostic and not a performance guarantee.",
    }


def _count(values):
    result = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/benchmarks/phase21_2/synthetic_summary.json"))
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
