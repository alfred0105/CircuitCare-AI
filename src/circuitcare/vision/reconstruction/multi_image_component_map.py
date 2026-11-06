"""Bounded same-board photo intake, registration, mosaic, and component map.

Image-to-image registration in this module is separate from KiCad design
registration. Inferred detections and registrations remain candidates until
reviewed; no electrical connectivity is created here.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import base64
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable

import cv2
import numpy as np
from PIL import Image

from circuitcare.vision.board_detector import detect_board_candidates
from circuitcare.vision.component_detector import detect_components
from circuitcare.vision.image_loader import ImageLoadError, load_board_image
from circuitcare.vision.perspective import rectify_board
from circuitcare.vision.reconstruction.multiview_registration import register_same_side


class BoardSide(StrEnum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"


class CaptureRole(StrEnum):
    REFERENCE = "REFERENCE"
    OVERVIEW = "OVERVIEW"
    CLOSEUP = "CLOSEUP"
    ANGLED = "ANGLED"


@dataclass(frozen=True)
class ImageBudget:
    max_images: int = 20
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_file_bytes: int = 80 * 1024 * 1024
    max_image_pixels: int = 12_000_000
    max_total_pixels: int = 40_000_000
    max_decoded_edge: int = 1600
    max_canvas_edge: int = 4000
    max_canvas_pixels: int = 8_000_000
    max_runtime_seconds: float = 60.0

    def __post_init__(self) -> None:
        ints = (self.max_images, self.max_file_bytes, self.max_total_file_bytes, self.max_image_pixels,
                self.max_total_pixels, self.max_decoded_edge, self.max_canvas_edge,
                self.max_canvas_pixels)
        if any(value < 1 for value in ints) or not math.isfinite(self.max_runtime_seconds) or self.max_runtime_seconds <= 0:
            raise ValueError("image budgets must be positive")


@dataclass(frozen=True)
class PhotoInput:
    data: bytes | bytearray | str | Path
    side: BoardSide | str
    role: CaptureRole | str = CaptureRole.OVERVIEW
    name: str = "photo"
    rectification_corners_px: tuple[tuple[float, float], ...] | None = None


@dataclass
class PhotoAsset:
    photo_id: str
    sha256: str
    side: str
    role: str
    name: str
    original_size_px: tuple[int, int]
    processed_size_px: tuple[int, int]
    decoded_size_px: tuple[int, int]
    image_format: str
    image: Image.Image = field(repr=False)
    original_bytes: bytes = field(repr=False)
    duplicate_of: str | None = None
    rectification: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"photo_id": self.photo_id, "sha256": self.sha256, "side": self.side,
                "role": self.role, "name": self.name, "original_size_px": list(self.original_size_px),
                "processed_size_px": list(self.processed_size_px), "decoded_size_px": list(self.decoded_size_px),
                "image_format": self.image_format,
                "duplicate_of": self.duplicate_of, "original_preserved": True,
                "rectification": self.rectification}


@dataclass
class PCBPhotoSession:
    board_id: str
    photos: list[PhotoAsset]
    created_at_epoch: float
    budget: ImageBudget


@dataclass(frozen=True)
class RegistrationRecord:
    photo_id: str
    side: str
    reference_photo_id: str
    status: str
    method: str
    transform_moving_to_canonical: tuple[tuple[float, ...], ...] | None
    candidate_matches: int = 0
    inlier_count: int = 0
    inlier_ratio: float | None = None
    rmse_px: float | None = None
    overlap_ratio: float = 0.0
    failure_reason: str | None = None
    p95_reprojection_error_px: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "transform_moving_to_canonical":
                [list(row) for row in self.transform_moving_to_canonical]
                if self.transform_moving_to_canonical else None}


class MultiImageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MultiImageComponentMapService:
    """Create a partial but provenance-preserving map for one board session."""

    SCHEMA_VERSION = "circuitcare.pcb-component-map.v1"

    def __init__(self, *, budget: ImageBudget = ImageBudget()):
        self.budget = budget

    def ingest(self, board_id: str, inputs: Iterable[PhotoInput]) -> PCBPhotoSession:
        if not isinstance(board_id, str) or not board_id.strip():
            raise MultiImageError("INVALID_BOARD_ID", "board_id is required")
        values = []
        for item in inputs:
            if len(values) >= self.budget.max_images:
                raise MultiImageError("IMAGE_COUNT_LIMIT", f"Provide 1 to {self.budget.max_images} photos")
            values.append(item)
        if not values or len(values) > self.budget.max_images:
            raise MultiImageError("IMAGE_COUNT_LIMIT", f"Provide 1 to {self.budget.max_images} photos")
        seen: dict[str, str] = {}
        assets: list[PhotoAsset] = []
        total_pixels = 0
        total_bytes = 0
        intake_started = time.perf_counter()
        for index, item in enumerate(values):
            if time.perf_counter() - intake_started > self.budget.max_runtime_seconds:
                raise MultiImageError("TIMEOUT", "Photo intake exceeded its time budget")
            try:
                side = BoardSide(item.side).value
                role = CaptureRole(item.role).value
            except ValueError as exc:
                raise MultiImageError("INVALID_SIDE_OR_ROLE", str(exc)) from exc
            raw = _read_bytes(item.data, self.budget.max_file_bytes)
            total_bytes += len(raw)
            if total_bytes > self.budget.max_total_file_bytes:
                raise MultiImageError("TOTAL_FILE_SIZE_LIMIT", "Session exceeds total input byte budget")
            try:
                loaded = load_board_image(raw, max_file_bytes=self.budget.max_file_bytes,
                                          max_pixels=self.budget.max_image_pixels,
                                          max_edge=self.budget.max_decoded_edge)
            except ImageLoadError as exc:
                raise MultiImageError("INVALID_IMAGE", str(exc)) from exc
            total_pixels += loaded.original_size[0] * loaded.original_size[1]
            if total_pixels > self.budget.max_total_pixels:
                raise MultiImageError("TOTAL_PIXEL_LIMIT", "Session exceeds total original image pixel budget")
            photo_id = "photo_" + hashlib.sha256(
                f"{board_id}|{side}|{role}|{item.name}|{index}|{loaded.sha256}".encode()).hexdigest()[:16]
            asset = PhotoAsset(photo_id, loaded.sha256, side, role, str(item.name),
                               loaded.original_size, loaded.processed_size, loaded.processed_size, loaded.format,
                               loaded.image.copy(), raw, seen.get(loaded.sha256))
            if item.rectification_corners_px is not None:
                asset = self._rectify_asset(asset, item.rectification_corners_px)
            seen.setdefault(loaded.sha256, photo_id)
            assets.append(asset)
        return PCBPhotoSession(board_id.strip(), assets, time.time(), self.budget)

    def build_map(self, session: PCBPhotoSession, *, detector: Callable[[Any], dict[str, Any]] | None = None,
                  model_path: str | Path | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        if not session.photos:
            raise MultiImageError("EMPTY_SESSION", "No photos are available")
        sides: dict[str, list[PhotoAsset]] = {side.value: [p for p in session.photos if p.side == side.value]
                                              for side in BoardSide}
        side_maps = {}
        for side, photos in sides.items():
            if photos:
                if time.perf_counter() - started > session.budget.max_runtime_seconds:
                    raise MultiImageError("TIMEOUT", "Multi-image processing exceeded its time budget")
                side_maps[side] = self._build_side(session.board_id, side, photos, detector, model_path,
                                                   started, session.budget)
        return {"schema_version": self.SCHEMA_VERSION, "board_id": session.board_id,
                "created_at_epoch": session.created_at_epoch, "processing_status": "PARTIAL_MAP_READY",
                "design_registration": {"status": "NOT_RUN_SEPARATE_FROM_PHOTO_REGISTRATION"},
                "sides": side_maps,
                "photos": [p.to_dict() for p in session.photos],
                "resource_limits": session.budget.__dict__.copy(),
                "runtime_seconds": time.perf_counter() - started,
                "electrical_connectivity": "NOT_INFERRED_FROM_PHOTOS"}

    def _rectify_asset(self, photo: PhotoAsset, corners: Any) -> PhotoAsset:
        try:
            result = rectify_board(photo.image, corners, max_output_edge=self.budget.max_decoded_edge)
            photo.rectification = {"status": "RECTIFIED_CANDIDATE_NOT_PHYSICALLY_VALIDATED",
                                   "source_to_rectified": result["transform_matrix"],
                                   "output_size_px": result["output_size_px"],
                                   "confidence_diagnostics": {"method": "USER_SUPPLIED_BOARD_CORNERS",
                                                               "physical_dimensions_known": False}}
            photo.image = result["image"]
            photo.processed_size_px = tuple(result["output_size_px"])
        except (ValueError, cv2.error) as exc:
            photo.rectification = {"status": "RECTIFICATION_FAILED_KEEP_ORIGINAL", "reason": str(exc),
                                   "source_to_rectified": None}
        return photo

    def _build_side(self, board_id: str, side: str, photos: list[PhotoAsset],
                    detector: Callable[[Any], dict[str, Any]] | None, model_path: str | Path | None,
                    started: float, budget: ImageBudget) -> dict[str, Any]:
        unique = []
        duplicate_records = {}
        known_sha: dict[str, str] = {}
        for photo in photos:
            if photo.sha256 in known_sha:
                duplicate_records[photo.photo_id] = known_sha[photo.sha256]
            else:
                unique.append(photo)
                known_sha[photo.sha256] = photo.photo_id
        reference = min(unique, key=lambda p: (0 if p.role == CaptureRole.REFERENCE.value else
                                               1 if p.role == CaptureRole.OVERVIEW.value else 2,
                                               -p.image.width * p.image.height, p.sha256))
        registrations: dict[str, RegistrationRecord] = {
            reference.photo_id: RegistrationRecord(reference.photo_id, side, reference.photo_id,
                "REFERENCE", "IDENTITY", tuple(tuple(float(x) for x in row) for row in np.eye(3)))
        }
        for photo in unique:
            if photo.photo_id == reference.photo_id:
                continue
            if time.perf_counter() - started > budget.max_runtime_seconds:
                registrations[photo.photo_id] = RegistrationRecord(photo.photo_id, side, reference.photo_id,
                    "UNREGISTERED", "ORB_RANSAC_HOMOGRAPHY", None, failure_reason="TIMEOUT")
                continue
            try:
                result = register_same_side(reference.image, photo.image, source_photo_id=photo.photo_id,
                                            reference_photo_id=reference.photo_id,
                                            board_side="front" if side == "TOP" else "back")
            except (ValueError, cv2.error) as exc:
                registrations[photo.photo_id] = RegistrationRecord(photo.photo_id, side, reference.photo_id,
                    "UNREGISTERED", "ORB_RANSAC_HOMOGRAPHY", None, failure_reason=str(exc))
                continue
            record = _validate_registration(photo, reference, result)
            registrations[photo.photo_id] = record
        for duplicate_id, original_id in duplicate_records.items():
            registrations[duplicate_id] = RegistrationRecord(duplicate_id, side, reference.photo_id,
                "DUPLICATE_SKIPPED", "SHA256_DUPLICATE", registrations[original_id].transform_moving_to_canonical)

        mosaic, source_map, canvas_origin, included_ids = _make_mosaic(reference, unique, registrations, budget)
        for photo_id, record in list(registrations.items()):
            if photo_id not in included_ids and record.status not in {"DUPLICATE_SKIPPED"}:
                registrations[photo_id] = RegistrationRecord(photo_id, side, reference.photo_id,
                    "UNREGISTERED", record.method, None, record.candidate_matches, record.inlier_count,
                    record.inlier_ratio, record.rmse_px, record.overlap_ratio,
                    "CANVAS_RESOURCE_LIMIT")
        shift = np.array([[1, 0, -canvas_origin[0]], [0, 1, -canvas_origin[1]], [0, 0, 1]], dtype=np.float64)
        for photo_id, record in list(registrations.items()):
            if record.transform_moving_to_canonical is not None:
                canonical_transform = shift @ np.asarray(record.transform_moving_to_canonical)
                registrations[photo_id] = RegistrationRecord(
                    record.photo_id, record.side, record.reference_photo_id, record.status, record.method,
                    tuple(tuple(float(x) for x in row) for row in canonical_transform),
                    record.candidate_matches, record.inlier_count, record.inlier_ratio, record.rmse_px,
                    record.overlap_ratio, record.failure_reason, record.p95_reprojection_error_px)
        observations = []
        detector_status = "DETECTOR_NOT_CONFIGURED"
        for photo in unique:
            if time.perf_counter() - started > budget.max_runtime_seconds:
                detector_status = "PARTIAL_TIMEOUT"
                break
            if detector is None and model_path is None:
                continue
            try:
                detection_result = detector(photo.image) if detector else detect_components(photo.image, model_path)
                detector_status = detection_result.get("status", "INFERENCE_COMPLETE")
                transform = registrations[photo.photo_id].transform_moving_to_canonical
                if transform is None or registrations[photo.photo_id].status not in {"REFERENCE", "REGISTERED_CANDIDATE"}:
                    continue
                for detection in detection_result.get("detections", []):
                    observations.append(_map_detection(detection, photo, np.asarray(transform), (0, 0)))
            except (ValueError, OSError, RuntimeError, cv2.error) as exc:
                detector_status = "DETECTOR_ERROR"
                observations.append({"photo_id": photo.photo_id, "error": str(exc), "status": "DETECTION_FAILED"})
        components = _fuse_observations(board_id, side, observations)
        canonical_id = f"mosaic:{board_id}:{side}"
        return {"board_id": board_id, "board_side": side,
                "canonical_image": {"image_id": canonical_id, "coordinate_frame": "MOSAIC_PIXEL",
                    "image_size_px": [int(mosaic.shape[1]), int(mosaic.shape[0])],
                    "canvas_origin_in_reference_px": list(canvas_origin),
                    "image_png_base64": _png_base64(mosaic),
                    "pixel_source_map_png_base64": _png_base64(source_map),
                    "pixel_source_map_values": {str(index + 1): photo.photo_id for index, photo in enumerate(unique)},
                    "rectification_validation": "CANDIDATE_GEOMETRY_ONLY"},
                "registrations": [record.to_dict() for record in registrations.values()],
                "components": components, "component_observations": observations,
                "detection_status": detector_status,
                "board_boundary_candidates": _board_boundary_records(unique, started, budget),
                "functional_blocks": {"status": "NOT_EVALUATED", "candidates": []},
                "warnings": ["Photo registration does not establish KiCad coordinate alignment or electrical connectivity."]}

    @staticmethod
    def fault_overlay(component_map: dict[str, Any], side: str,
                      candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
        try:
            side_value = BoardSide(side).value
        except ValueError as exc:
            raise MultiImageError("INVALID_SIDE_OR_ROLE", "side must be TOP or BOTTOM") from exc
        side_record = component_map.get("sides", {}).get(side_value)
        if side_record is None:
            raise MultiImageError("BOARD_SIDE_NOT_FOUND", "No component map exists for the requested side")
        components = {item["component_id"]: item for item in side_record["components"]}
        result = []
        for candidate in candidates:
            component_id = str(candidate.get("component_id", ""))
            state = str(candidate.get("status", "UNDETERMINED"))
            if state not in {"CONFIRMED_FAULT", "SUSPECTED_FAULT", "RELATED_COMPONENT", "UNDETERMINED"}:
                raise MultiImageError("INVALID_FAULT_STATUS", f"Unsupported fault candidate state: {state}")
            if state == "CONFIRMED_FAULT" and not candidate.get("confirmed_by_measurement_or_inspection"):
                state = "UNDETERMINED"
            component = components.get(component_id)
            result.append({"board_id": component_map["board_id"], "board_side": side,
                "canonical_image_reference": side_record["canonical_image"]["image_id"],
                "component_id": component_id if component else None,
                "component_position": component.get("bbox_xyxy") if component else None,
                "mapping_status": "MAPPED" if component else "UNMAPPED_COMPONENT_ID",
                "fault_candidate_status": state, "candidate_ranking": candidate.get("ranking"),
                "diagnostic_evidence": candidate.get("diagnostic_evidence", []),
                "suggested_measurement": candidate.get("suggested_measurement"),
                "measurement_result": candidate.get("measurement_result"),
                "confidence": candidate.get("confidence"),
                "uncertainty": candidate.get("uncertainty", "NOT_PROVIDED"),
                "registration_validation_status": "IMAGE_TO_IMAGE_CANDIDATE_ONLY"})
        return {"schema_version": "circuitcare.pcb-fault-overlay.v1", "board_id": component_map["board_id"],
                "board_side": side, "candidates": result}


def _read_bytes(value: Any, limit: int) -> bytes:
    if isinstance(value, (str, Path)):
        path = Path(value)
        try:
            if path.stat().st_size > limit:
                raise MultiImageError("FILE_SIZE_LIMIT", f"Image file exceeds {limit} bytes")
            data = path.read_bytes()
        except OSError as exc:
            raise MultiImageError("INVALID_IMAGE", str(exc)) from exc
    else:
        data = bytes(value)
    if not data or len(data) > limit:
        raise MultiImageError("FILE_SIZE_LIMIT", f"Image bytes must be between 1 and {limit}")
    return data


def _validate_registration(photo: PhotoAsset, reference: PhotoAsset, result: Any) -> RegistrationRecord:
    matrix = np.asarray(result.transformation, dtype=np.float64) if result.transformation else None
    if matrix is None or matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        return RegistrationRecord(photo.photo_id, photo.side, reference.photo_id, "UNREGISTERED",
                                  result.method, None, None,
                                  result.inlier_count, result.inlier_ratio or 0.0, result.reprojection_error_px,
                                  failure_reason=result.registration_status)
    determinant = float(np.linalg.det(matrix))
    condition = float(np.linalg.cond(matrix))
    corners = np.array([[0, 0], [photo.image.width - 1, 0],
                        [photo.image.width - 1, photo.image.height - 1], [0, photo.image.height - 1]], dtype=np.float32)
    try:
        projected = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        area = abs(float(cv2.contourArea(projected.astype(np.float32))))
    except cv2.error:
        projected, area = np.zeros((4, 2)), 0.0
    ref_area = float(reference.image.width * reference.image.height)
    intersection_area = 0.0
    if area > 0 and ref_area > 0:
        ref_polygon = np.array([[0, 0], [reference.image.width - 1, 0],
                                [reference.image.width - 1, reference.image.height - 1],
                                [0, reference.image.height - 1]], dtype=np.float32)
        try:
            intersection_area, _ = cv2.intersectConvexConvex(
                cv2.convexHull(projected.astype(np.float32)), ref_polygon)
        except cv2.error:
            intersection_area = 0.0
    overlap = min(1.0, float(intersection_area) / min(area, ref_area)) if area and ref_area else 0.0
    valid_geometry = (abs(determinant) > 1e-12 and condition < 1e10 and area > 0
                      and area <= ref_area * 8
                      and np.isfinite(projected).all()
                      and np.max(np.abs(projected)) < max(reference.image.size) * 8)
    status = result.registration_status
    if status != "REGISTERED_CANDIDATE" or not valid_geometry:
        status = "UNREGISTERED"
    if overlap < 0.02:
        status = "UNREGISTERED"
    return RegistrationRecord(photo.photo_id, photo.side, reference.photo_id, status,
        result.method, tuple(tuple(float(x) for x in row) for row in matrix) if status != "UNREGISTERED" else None,
        result.candidate_match_count, result.inlier_count, result.inlier_ratio or 0.0,
        result.reprojection_error_px, overlap,
        None if status != "UNREGISTERED" else "INVALID_TRANSFORM_OR_INSUFFICIENT_OVERLAP",
        result.p95_reprojection_error_px)


def _make_mosaic(reference: PhotoAsset, photos: list[PhotoAsset],
                 records: dict[str, RegistrationRecord], budget: ImageBudget):
    placements = []
    all_points = []
    for photo in photos:
        record = records[photo.photo_id]
        if record.status not in {"REFERENCE", "REGISTERED_CANDIDATE"} or record.transform_moving_to_canonical is None:
            continue
        matrix = np.asarray(record.transform_moving_to_canonical, dtype=np.float64)
        corners = np.array([[0, 0], [photo.image.width - 1, 0],
                            [photo.image.width - 1, photo.image.height - 1], [0, photo.image.height - 1]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        placements.append((photo, matrix, transformed))
        all_points.extend(transformed.tolist())
    points = np.asarray(all_points)
    min_x, min_y = np.floor(points.min(axis=0)).astype(int)
    max_x, max_y = np.ceil(points.max(axis=0)).astype(int)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    if width <= 0 or height <= 0 or width > budget.max_canvas_edge or height > budget.max_canvas_edge or width * height > budget.max_canvas_pixels:
        placements = [(reference, np.eye(3), np.array([[0, 0], [reference.image.width-1, 0],
                        [reference.image.width-1, reference.image.height-1], [0, reference.image.height-1]], dtype=np.float32))]
        min_x = min_y = 0
        width, height = reference.image.size
        # The reference itself is already capped by the intake pixel and edge budgets.
    shift = np.array([[1, 0, -min_x], [0, 1, -min_y], [0, 0, 1]], dtype=np.float64)
    mosaic = np.zeros((height, width, 3), dtype=np.uint8)
    sources = np.zeros((height, width), dtype=np.uint8)
    quality = np.full((height, width), -1.0, dtype=np.float32)
    for photo, matrix, _ in sorted(placements, key=lambda item: item[0].photo_id):
        transform = shift @ matrix
        array = np.asarray(photo.image.convert("RGB"))
        warped = cv2.warpPerspective(array, transform, (width, height))
        mask = cv2.warpPerspective(np.ones(array.shape[:2], dtype=np.uint8), transform,
                                   (width, height), flags=cv2.INTER_NEAREST).astype(bool)
        overlap_mask = mask & (sources > 0)
        if np.any(overlap_mask):
            current_pixels = mosaic[overlap_mask].astype(np.int16)
            new_pixels = warped[overlap_mask].astype(np.int16)
            channel_delta = np.median(current_pixels - new_pixels, axis=0)
            warped = np.clip(warped.astype(np.int16) + np.clip(channel_delta, -32, 32), 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
        score = max(0.0, float(cv2.Laplacian(gray, cv2.CV_32F).var()))
        replace_mask = mask & (score > quality)
        mosaic[replace_mask] = warped[replace_mask]
        photo_index = next(index for index, candidate in enumerate(photos) if candidate.photo_id == photo.photo_id)
        sources[replace_mask] = photo_index + 1
        quality[replace_mask] = score
    return mosaic, sources, (int(min_x), int(min_y)), {photo.photo_id for photo, _, _ in placements}


def _map_detection(detection: dict[str, Any], photo: PhotoAsset,
                   matrix: np.ndarray, canvas_origin: tuple[int, int]) -> dict[str, Any]:
    bbox = detection.get("bbox_xyxy") or detection.get("bbox")
    if bbox is None or len(bbox) != 4:
        return {"photo_id": photo.photo_id, "detection_id": detection.get("detection_id"),
                "status": "INVALID_DETECTION_BOX"}
    x1, y1, x2, y2 = map(float, bbox)
    if (not all(math.isfinite(value) for value in (x1, y1, x2, y2))
            or not (0 <= x1 < x2 <= photo.image.width and 0 <= y1 < y2 <= photo.image.height)):
        return {"photo_id": photo.photo_id, "detection_id": detection.get("detection_id"),
                "status": "INVALID_DETECTION_BOX"}
    corners = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    mapped[:, 0] -= canvas_origin[0]
    mapped[:, 1] -= canvas_origin[1]
    min_xy, max_xy = mapped.min(axis=0), mapped.max(axis=0)
    original_corners = corners.copy()
    if photo.rectification and photo.rectification.get("source_to_rectified"):
        inverse_rectification = np.linalg.inv(np.asarray(photo.rectification["source_to_rectified"], dtype=np.float64))
        original_corners = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), inverse_rectification).reshape(-1, 2)
    original_corners[:, 0] *= photo.original_size_px[0] / photo.decoded_size_px[0]
    original_corners[:, 1] *= photo.original_size_px[1] / photo.decoded_size_px[1]
    original_min, original_max = original_corners.min(axis=0), original_corners.max(axis=0)
    confidence = detection.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            confidence = None
    return {"photo_id": photo.photo_id, "detection_id": str(detection.get("detection_id") or "detection"),
            "class_name": str(detection.get("class_name", detection.get("predicted_class", "unknown_component"))),
            "bbox_xyxy": [float(min_xy[0]), float(min_xy[1]), float(max_xy[0]), float(max_xy[1])],
            "polygon_xy": [[float(x), float(y)] for x, y in mapped],
            "processed_bbox_xyxy": [x1, y1, x2, y2],
            "original_bbox_xyxy": [float(original_min[0]), float(original_min[1]),
                                   float(original_max[0]), float(original_max[1])],
            "source_image_size_px": list(photo.processed_size_px),
            "confidence": confidence, "ocr_marking": detection.get("ocr_text"),
            "possible_part_number": None, "identification_status": "SUGGESTED_CLASS_ONLY",
            "evidence": "MODEL_DETECTION_CANDIDATE", "coordinate_transform": "PHOTO_TO_CANONICAL_CANDIDATE"}


def _fuse_observations(board_id: str, side: str, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [item for item in observations if item.get("bbox_xyxy")]
    groups: list[list[dict[str, Any]]] = []
    for item in sorted(valid, key=lambda row: (row["class_name"], row["bbox_xyxy"], row["photo_id"])):
        target = next((group for group in groups if _same_component(item, group[0])), None)
        if target is not None:
            target.append(item)
        else:
            groups.append([item])
    components = []
    for group in groups:
        boxes = np.asarray([item["bbox_xyxy"] for item in group], dtype=np.float64)
        box = np.median(boxes, axis=0).tolist()
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        key = f"{board_id}|{side}|{group[0]['class_name']}|{round(center[0], 1)}|{round(center[1], 1)}"
        component_id = "component_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        components.append({"component_id": component_id, "component_type": group[0]["class_name"],
            "canonical_position_xy": [float(center[0]), float(center[1])], "bbox_xyxy": [float(x) for x in box],
            "polygon_xy": [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
            "source_image_ids": sorted({item["photo_id"] for item in group}),
            "original_image_positions": [{"photo_id": item["photo_id"], "bbox_xyxy": item["original_bbox_xyxy"]} for item in group],
            "detection_confidence": max((float(item["confidence"]) for item in group if item.get("confidence") is not None), default=None),
            "ocr_marking": next((item["ocr_marking"] for item in group if item.get("ocr_marking")), None),
            "possible_part_number": None, "identification_status": "SUGGESTED_UNCONFIRMED",
            "identity_fusion_status": "MULTI_OBSERVATION_FUSED" if len(group) > 1 else "SINGLE_OBSERVATION",
            "evidence": [{"photo_id": item["photo_id"], "detection_id": item["detection_id"],
                          "confidence": item["confidence"], "source": item["evidence"]} for item in group]})
    return components


def _same_component(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first["photo_id"] == second["photo_id"]:
        return False
    if first["class_name"].lower() != second["class_name"].lower():
        return False
    a, b = first["bbox_xyxy"], second["bbox_xyxy"]
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = max(1e-9, (a[2]-a[0]) * (a[3]-a[1]))
    area_b = max(1e-9, (b[2]-b[0]) * (b[3]-b[1]))
    iou = intersection / (area_a + area_b - intersection)
    center_a = np.array([(a[0]+a[2])/2, (a[1]+a[3])/2])
    center_b = np.array([(b[0]+b[2])/2, (b[1]+b[3])/2])
    diagonal = max(1.0, math.hypot(a[2]-a[0], a[3]-a[1]))
    return iou >= 0.65 and float(np.linalg.norm(center_a-center_b)) <= diagonal * 0.25


def _board_boundary_records(photos: list[PhotoAsset], started: float,
                            budget: ImageBudget) -> list[dict[str, Any]]:
    results = []
    for photo in photos:
        if time.perf_counter() - started > budget.max_runtime_seconds:
            results.append({"photo_id": photo.photo_id, "status": "NOT_EVALUATED_TIMEOUT"})
            continue
        try:
            detected = detect_board_candidates(photo.image, max_candidates=3)
            results.append({"photo_id": photo.photo_id, "status": detected["status"],
                            "candidates": detected["candidates"], "verification": "UNCONFIRMED_CANDIDATE"})
        except (ValueError, cv2.error) as exc:
            results.append({"photo_id": photo.photo_id, "status": "NOT_DETECTED", "reason": str(exc)})
    return results


def to_json(component_map: dict[str, Any]) -> str:
    """Stable JSON serialization for API/UI adapters; NumPy values are excluded."""
    return json.dumps(component_map, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _png_base64(array: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", array)
    if not ok:
        raise MultiImageError("ARTIFACT_ENCODING_FAILED", "Could not encode canonical image artifact")
    return base64.b64encode(encoded.tobytes()).decode("ascii")
