#!/usr/bin/env python3
"""Attempt and record per-side image-to-KiCad registration for pinned PRISM.

Without separately supplied, independently checked point correspondences the
tool records REGISTRATION_UNVERIFIED; it never treats board detection or
training-point fit as validation.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from circuitcare.vision.reconstruction.coordinate_frames import (
    CalibrationPoint, CoordinateFrame, TransformType, fit_transform,
)
from circuitcare.vision.reconstruction.anchor_detection import detect_dark_round_anchors
from circuitcare.vision.reconstruction.anchor_matching import extract_design_anchors, match_anchors
from circuitcare.vision.reconstruction.dataset_bundle import build_prism_bundle
from circuitcare.vision.reconstruction.ground_truth import summarize_reference_geometry
from circuitcare.vision.reconstruction.registration_visualization import (
    save_registration_overlay, save_top_bottom_comparison,
)
from circuitcare.vision.reconstruction.prism_dataset import (
    PRISM_COMMIT, SAMPLES, load_references, load_sample, validate_inventory,
)
from circuitcare.vision.board_detector import detect_board_candidates
from circuitcare.vision.reconstruction.copper_segmentation import (
    detect_pad_via_candidates, segment_visible_copper,
)

PRIORITY = ("Simple", "Divider", "Crossover", "Groundplane", "Meander")
SIDES = ("TOP", "BOTTOM")


def _points(records: list[dict[str, Any]], role: str, side: str) -> list[CalibrationPoint]:
    result = []
    for row in records:
        evidence = str(row.get("evidence", "")).strip()
        if not evidence:
            raise ValueError(f"{role} point {row.get('point_id')} must declare evidence")
        result.append(CalibrationPoint(
            point_id=str(row["point_id"]),
            source_xy=(float(row["x_mm"]), float(row["y_mm"])),
            target_xy=(float(row["u_px"]), float(row["v_px"])),
            source_frame=CoordinateFrame.KICAD_DESIGN,
            target_frame=CoordinateFrame.IMAGE_RAW,
            board_side=side, evidence=evidence, role=role,
            review_status=str(row.get("review_status", "NOT_REVIEWED")),
        ))
    return result


def _report_path(path: Path) -> str:
    """Keep artifact references portable when they live inside the repository."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _image_feature_diagnostics(image_path: Path, sample_name: str, side: str) -> dict[str, Any]:
    """Run image-only candidates as diagnostics; do not promote them to anchors."""
    try:
        image = Image.open(image_path).convert("RGB")
        arr = np.asarray(image)
        board = detect_board_candidates(image)
        mask = segment_visible_copper(arr, board_side="TOP" if side == "TOP" else "BOTTOM").mask
        pad_candidates = detect_pad_via_candidates(
            arr, photo_id=f"p21.1-{sample_name}-{side}",
            board_side="front" if side == "TOP" else "back", copper_mask=mask,
        )
        return {
            "status": "CANDIDATES_ONLY_NOT_CORRESPONDENCES",
            "board_candidate_count": len(board.get("candidates", [])),
            "pad_via_candidate_count": len(pad_candidates),
            "image_only": True,
            "usable_calibration_correspondences": 0,
            "note": "Candidate detections were not independently matched to design points.",
        }
    except Exception as exc:  # Keep and report each image failure independently.
        return {"status": "FEATURE_DIAGNOSTIC_FAILED", "error": f"{type(exc).__name__}: {exc}",
                "image_only": True, "usable_calibration_correspondences": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=ROOT / "data/external/prism")
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "data/benchmarks/phase21_1_1")
    parser.add_argument("--output", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", choices=SAMPLES)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--points-json", type=Path,
                        help="Optional reviewed correspondences keyed by sample then TOP/BOTTOM")
    parser.add_argument("--mode", choices=("AUTO_REGISTRATION", "MANUAL_CALIBRATION"),
                        default="AUTO_REGISTRATION")
    parser.add_argument("--ransac-threshold-px", type=float, default=2.0)
    parser.add_argument("--acceptance-threshold-px", type=float,
                        help="Predeclared max held-out error; without it validation remains unverified")
    parser.add_argument("--design-assisted", action="store_true",
                        help="Record that matching design geometry is an allowed input")
    args = parser.parse_args()
    if not args.all and not args.sample:
        parser.error("Choose --sample or --all")
    try:
        inventory = validate_inventory(args.dataset_root, parse_references=False)
        if inventory["ready_samples"] != len(SAMPLES):
            parser.error(f"Pinned PRISM inventory must contain all 12 samples; found {inventory['ready_samples']}")
        commit = subprocess.run(["git", "-C", str(args.dataset_root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        if commit != PRISM_COMMIT:
            parser.error(f"PRISM commit mismatch: expected {PRISM_COMMIT}, got {commit}")
        point_payload = json.loads(args.points_json.read_text(encoding="utf-8")) if args.points_json else {}
        samples = (list(PRIORITY) + [name for name in SAMPLES if name not in PRIORITY]
                   if args.all else [args.sample])
        artifact_dir = args.artifact_dir.expanduser().resolve()
        rows = []
        for sample_name in samples:
            sample = load_sample(args.dataset_root, sample_name)
            refs = load_references(args.dataset_root, sample_name)
            bundle = build_prism_bundle(args.dataset_root, sample_name)
            sides = {}
            for side, image_path in (("TOP", sample.top_image), ("BOTTOM", sample.bottom_image)):
                side_started = time.perf_counter()
                size = list(Image.open(image_path).size)
                side_points = point_payload.get(sample_name, {}).get(side, {})
                calibration = _points(side_points.get("calibration", []), "CALIBRATION", side)
                validation = _points(side_points.get("validation", []), "VALIDATION", side)
                automatic_result = None
                image_anchors = []
                design_anchors = []
                row: dict[str, Any] = {
                    "registration_status": "REGISTRATION_UNVERIFIED",
                    "verification_status": "REGISTRATION_UNVERIFIED",
                    "reason": ("MANUAL_CORRESPONDENCES_NOT_PROVIDED"
                               if args.mode == "MANUAL_CALIBRATION" and not calibration else None),
                    "board_side": side,
                    "image_size_px": size,
                    "image_feature_diagnostics": _image_feature_diagnostics(image_path, sample_name, side),
                    "calibration_point_count": len(calibration),
                    "validation_point_count": len(validation),
                    "fit_error_px": None,
                    "median_error_px": None,
                    "p95_error_px": None,
                    "inlier_count": 0,
                    "inlier_ratio": None,
                    "transform": None,
                    "design_assisted": bool(args.design_assisted),
                    "image_only_status": "NOT_VERIFIED",
                    "design_assisted_status": "NOT_VERIFIED",
                }
                if args.mode == "AUTO_REGISTRATION":
                    try:
                        image_anchors, detected_size = detect_dark_round_anchors(
                            image_path, photo_id=f"prism-{sample_name}-{side.lower()}",
                            board_side=side,
                        )
                        design_anchors = extract_design_anchors(
                            refs["expected_geometry"], board_side=side,
                        )
                        automatic_result = match_anchors(
                            design_anchors, image_anchors, board_side=side,
                            image_size_px=detected_size,
                        )
                        side_dir = artifact_dir / "anchors"
                        side_dir.mkdir(parents=True, exist_ok=True)
                        anchor_path = side_dir / f"{sample_name}_{side}.json"
                        anchor_path.write_text(json.dumps({
                            "image_anchors": [anchor.to_dict() for anchor in image_anchors],
                            "design_anchors": [anchor.to_dict() for anchor in design_anchors],
                            "experiment_track": "DESIGN_ASSISTED_REGISTRATION",
                        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                        match_path = artifact_dir / "matches" / f"{sample_name}_{side}.json"
                        match_path.parent.mkdir(parents=True, exist_ok=True)
                        match_path.write_text(json.dumps(automatic_result.to_dict(), indent=2,
                                                         ensure_ascii=False) + "\n", encoding="utf-8")
                        overlay_path = artifact_dir / "overlays" / f"{sample_name}_{side}_registration.png"
                        save_registration_overlay(
                            image_path, overlay_path, image_anchors=image_anchors,
                            design_anchors=design_anchors, result=automatic_result,
                        )
                        row.update({
                            "registration_status": automatic_result.status,
                            "verification_status": automatic_result.status,
                            "reason": automatic_result.reason,
                            "calibration_point_count": automatic_result.candidate_count,
                            "validation_point_count": 0,
                            "fit_error_px": (automatic_result.transform.fit_error_px
                                             if automatic_result.transform else None),
                            "mean_error_px": automatic_result.mean_residual_px,
                            "median_error_px": automatic_result.median_residual_px,
                            "rmse_error_px": automatic_result.rmse_residual_px,
                            "p95_error_px": automatic_result.p95_residual_px,
                            "max_error_px": automatic_result.max_residual_px,
                            "error_data_scope": "AUTO_MATCHED_INLIERS_TRAINING_ONLY_NOT_HELD_OUT",
                            "inlier_count": len(automatic_result.matches),
                            "review_flags": list(automatic_result.review_flags),
                            "inlier_ratio": automatic_result.inlier_ratio,
                            "candidate_match_count": automatic_result.candidate_count,
                            "candidate_transform_count": automatic_result.candidate_transform_count,
                            "design_anchor_count": automatic_result.design_anchor_count,
                            "image_anchor_count": automatic_result.image_anchor_count,
                            "spatial_coverage": automatic_result.spatial_coverage,
                            "transform_stability_px": automatic_result.transform_stability_px,
                            "orientation": automatic_result.orientation,
                            "matching_reason": automatic_result.reason,
                            "transform": automatic_result.transform.to_dict()
                                         if automatic_result.transform else None,
                            "matches": [match.to_dict() for match in automatic_result.matches],
                            "anchor_file": _report_path(anchor_path),
                            "match_file": _report_path(match_path),
                            "overlay_file": _report_path(overlay_path),
                            "design_assisted": True,
                            "image_only_status": "CANDIDATES_ONLY",
                            "design_assisted_status": automatic_result.status,
                        })
                    except (ValueError, OSError, KeyError, TypeError) as exc:
                        row.update(
                            registration_status="REGISTRATION_FAILED",
                            verification_status="REGISTRATION_FAILED",
                            reason=f"{type(exc).__name__}: {exc}",
                        )
                elif calibration:
                    try:
                        transform, metrics = fit_transform(
                            calibration, board_side=side,
                            source_frame=CoordinateFrame.KICAD_DESIGN,
                            target_frame=CoordinateFrame.IMAGE_RAW,
                            validation_points=validation,
                            ransac_threshold_px=args.ransac_threshold_px,
                            acceptance_threshold_px=args.acceptance_threshold_px,
                            transform_type=TransformType.HOMOGRAPHY,
                        )
                        row.update({
                            "registration_status": transform.verification_status.value,
                            "verification_status": transform.verification_status.value,
                            "reason": "INDEPENDENT_VALIDATION_NOT_PROVIDED" if not validation else None,
                            "fit_error_px": transform.fit_error_px,
                            "median_error_px": metrics["held_out_error_target_units"]["median"],
                            "p95_error_px": metrics["held_out_error_target_units"]["p95"],
                            "inlier_count": transform.inlier_count,
                            "inlier_ratio": transform.inlier_ratio,
                            "transform": transform.to_dict(),
                            "metrics": metrics,
                        })
                        if transform.verification_status.value == "REGISTRATION_FAILED":
                            row["reason"] = "HELD_OUT_ERROR_EXCEEDS_PREDECLARED_THRESHOLD"
                    except (ValueError, KeyError, TypeError) as exc:
                        row.update(registration_status="REGISTRATION_FAILED",
                                   verification_status="REGISTRATION_FAILED",
                                   reason=f"{type(exc).__name__}: {exc}")
                row["runtime_seconds"] = time.perf_counter() - side_started
                sides[side] = row
            top_result = None
            bottom_result = None
            # Recover match ID sets from side records rather than sharing loop-local variables.
            for side_name, side_row in sides.items():
                ids = {match.get("design_anchor_id") for match in side_row.get("matches", [])}
                if side_name == "TOP":
                    top_result = ids
                else:
                    bottom_result = ids
            common_anchor_count = len((top_result or set()) & (bottom_result or set()))
            save_top_bottom_comparison(
                sample.top_image, sample.bottom_image,
                artifact_dir / "overlays" / f"{sample_name}_top_bottom_unregistered.png",
            )
            rows.append({
                "sample_id": sample_name,
                "board_revision": "NOT_AVAILABLE",
                "dataset_hash": sample.dataset_hash,
                "input_hashes": sample.input_hashes,
                "reference_geometry": summarize_reference_geometry(refs["expected_geometry"]),
                "bundle": bundle.to_dict(),
                "sides": sides,
                "attempt_scope": ("DESIGN_ASSISTED" if args.design_assisted else args.mode),
                "top_bottom_comparison": {
                    "shared_design_anchor_matches": common_anchor_count,
                    "coordinate_consistency_status": "NOT_VERIFIED",
                    "note": "A side-by-side view and shared design anchor IDs do not independently validate TOP/BOTTOM transforms.",
                },
                "independent_physical_board_data": "NOT_AVAILABLE_PRISM_RENDERED_SYNTHETIC_CASE",
            })
            print(f"{sample_name}: TOP={sides['TOP']['registration_status']} BOTTOM={sides['BOTTOM']['registration_status']}", flush=True)
        report = {
            "schema": "phase21.1.1-registration-attempt-v1",
            "dataset_source": "https://github.com/KamMalinski/PRISM",
            "prism_commit": commit,
            "circuitcare_commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                                  capture_output=True, text=True).stdout.strip(),
            "circuitcare_worktree_dirty": bool(subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()),
            "calibration_mode": args.mode,
            "experiment_track": "DESIGN_ASSISTED_REGISTRATION" if args.mode == "AUTO_REGISTRATION" or args.design_assisted else "MANUAL_CALIBRATION",
            "thresholds": {"ransac_threshold_px": args.ransac_threshold_px,
                           "acceptance_threshold_px": args.acceptance_threshold_px},
            "automatic_matching_configuration": {
                "image_anchor_detector": "dark connected components, circularity >= 0.35, gray < 28",
                "design_anchor_types": ["through-hole pads", "vias"],
                "scale_search_px_per_mm": [1.0, 80.0],
                "pair_distance_scale_tolerance": 0.015,
                "scale_histogram_bins": 720,
                "ransac_model": "AFFINE",
                "ransac_threshold_px": 2.0,
                "match_tolerance_px": "max(3.5, 0.006 * min(image_width_px, image_height_px))",
                "bottom_mirror": "searched as a negative-determinant similarity candidate; never forced",
                "track": "DESIGN_ASSISTED_REGISTRATION",
            },
            "samples_requested": len(rows), "sample_results": rows,
            "summary": {
                "top_bottom_pairs": sum(len(row["sides"]) for row in rows),
                "verified_registrations": sum(
                    side["registration_status"] == "VERIFIED"
                    for row in rows for side in row["sides"].values()),
                "unverified_registrations": sum(
                    side["registration_status"] != "VERIFIED"
                    for row in rows for side in row["sides"].values()),
                "failed_registrations": sum(
                    side["registration_status"] == "REGISTRATION_FAILED"
                    for row in rows for side in row["sides"].values()),
                "automatic_matches_found": sum(
                    side.get("candidate_match_count", 0) > 0
                    for row in rows for side in row["sides"].values()),
                "candidate_correspondences": sum(
                    side.get("candidate_match_count", 0)
                    for row in rows for side in row["sides"].values()),
                "geometric_inliers": sum(
                    side.get("inlier_count", 0)
                    for row in rows for side in row["sides"].values()),
                "transforms_generated": sum(
                    side.get("transform") is not None
                    for row in rows for side in row["sides"].values()),
                "auto_estimated_unverified": sum(
                    side["registration_status"] == "AUTO_ESTIMATED_UNVERIFIED"
                    for row in rows for side in row["sides"].values()),
                "manual_review_required": sum(
                    side["registration_status"] != "VERIFIED"
                    for row in rows for side in row["sides"].values()),
                "registration_success_rate": (
                    sum(side["registration_status"] == "VERIFIED"
                        for row in rows for side in row["sides"].values()) /
                    max(1, sum(len(row["sides"]) for row in rows))),
                "top_bottom_consistency": {
                    "status": "NOT_VERIFIED",
                    "reason": "No independently adjudicated shared TOP/BOTTOM landmarks or vias",
                },
            },
        }
        output = (args.output or artifact_dir / "summary.json").expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved registration attempt record to {output}")
        return 0
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        print(f"Registration preparation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
