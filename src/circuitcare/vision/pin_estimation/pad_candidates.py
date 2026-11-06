"""Conservative local image cues for possible visible terminal metal."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .geometry import component_axis


def extract_pad_candidates(image_rgb: np.ndarray, component: dict[str, Any], *,
                           max_candidates: int = 64) -> list[dict[str, Any]]:
    """Find bright, low-saturation connected regions close to component edges.

    These are appearance candidates only: vias, glare and silkscreen can look similar.
    """
    if not isinstance(image_rgb, np.ndarray) or image_rgb.ndim != 3 or image_rgb.shape[2] < 3:
        return []
    axis = component_axis(component)
    if axis is None:
        return []
    center, major, half_length, half_width = axis
    image_height, image_width = image_rgb.shape[:2]
    margin = max(2.0, half_width * 0.7)
    half_x = int(np.ceil(abs(major[0]) * (half_length + margin) + abs(-major[1]) * (half_width + margin)))
    half_y = int(np.ceil(abs(major[1]) * (half_length + margin) + abs(major[0]) * (half_width + margin)))
    x1, x2 = max(0, int(center[0]) - half_x), min(image_width, int(center[0]) + half_x + 1)
    y1, y2 = max(0, int(center[1]) - half_y), min(image_height, int(center[1]) + half_y + 1)
    if x2 <= x1 or y2 <= y1:
        return []
    rgb = image_rgb[y1:y2, x1:x2, :3].astype(np.uint8, copy=False)
    hsv = cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    # Exclude the body itself; a bright chip top or text is not a terminal observation.
    yy, xx = np.indices(rgb.shape[:2], dtype=np.float32)
    points = np.stack((xx + x1 - center[0], yy + y1 - center[1]), axis=-1)
    major_projection = points @ major.astype(np.float32)
    minor_projection = points @ np.array([-major[1], major[0]], dtype=np.float32)
    outside_body = (np.abs(major_projection) >= half_length * 0.92) | (np.abs(minor_projection) >= half_width * 1.05)
    metal_appearance = (hsv[:, :, 2] >= 150) & (hsv[:, :, 1] <= 125) & outside_body
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(metal_appearance.astype(np.uint8), 8)
    candidates = []
    max_area = max(4.0, half_width * half_width * 2.5)
    for label in range(1, count):
        x, y, width, height, area = map(int, stats[label])
        if area < 3 or area > max_area:
            continue
        local_center = centroids[label]
        px, py = float(local_center[0] + x1), float(local_center[1] + y1)
        relative = np.array([px, py], dtype=np.float64) - center
        axial, lateral = float(relative @ major), float(relative @ np.array([-major[1], major[0]]))
        if abs(axial) < half_length * 0.75 or abs(lateral) > half_width * 0.9:
            continue
        candidates.append({"position_xy": [px, py], "bbox_xyxy": [x + x1, y + y1, x + x1 + width, y + y1 + height],
            "evidence": ["LOCAL_BRIGHT_LOW_SATURATION_REGION", "OUTSIDE_COMPONENT_BODY"],
            "appearance_score": float(min(1.0, area / max(max_area, 1.0))),
            "score_kind": "RULE_BASED_NOT_CALIBRATED"})
    candidates.sort(key=lambda row: (row["position_xy"][0], row["position_xy"][1]))
    return candidates[:max_candidates]


def extract_perimeter_pad_candidates(image_rgb: np.ndarray, component: dict[str, Any], *,
                                    max_candidates: int = 128) -> list[dict[str, Any]]:
    """Collect generic lead/pad appearance candidates around all body edges."""
    if not isinstance(image_rgb, np.ndarray) or image_rgb.ndim != 3 or image_rgb.shape[2] < 3:
        return []
    axis = component_axis(component)
    if axis is None:
        return []
    center, major, half_length, half_width = axis
    minor = np.array([-major[1], major[0]])
    reach = max(3.0, min(half_length, half_width) * 0.9)
    image_height, image_width = image_rgb.shape[:2]
    extent_x = abs(major[0]) * (half_length + reach) + abs(minor[0]) * (half_width + reach)
    extent_y = abs(major[1]) * (half_length + reach) + abs(minor[1]) * (half_width + reach)
    x1, x2 = max(0, int(center[0] - extent_x)), min(image_width, int(center[0] + extent_x + 1))
    y1, y2 = max(0, int(center[1] - extent_y)), min(image_height, int(center[1] + extent_y + 1))
    if x2 <= x1 or y2 <= y1:
        return []
    rgb = image_rgb[y1:y2, x1:x2, :3].astype(np.uint8, copy=False)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    yy, xx = np.indices(rgb.shape[:2], dtype=np.float32)
    rel_x, rel_y = xx + x1 - center[0], yy + y1 - center[1]
    axial = rel_x * major[0] + rel_y * major[1]
    lateral = rel_x * minor[0] + rel_y * minor[1]
    outside = ((np.abs(axial) >= half_length * 1.03) | (np.abs(lateral) >= half_width * 1.08))
    within_neighborhood = (np.abs(axial) <= half_length + reach) & (np.abs(lateral) <= half_width + reach)
    mask = (hsv[:, :, 2] >= 150) & (hsv[:, :, 1] <= 125) & outside & within_neighborhood
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    max_area = max(6.0, min(half_length, half_width) ** 2 * 3.0)
    candidates = []
    for label in range(1, count):
        x, y, width, height, area = map(int, stats[label])
        if area < 3 or area > max_area:
            continue
        local_center = centroids[label]
        px, py = float(local_center[0] + x1), float(local_center[1] + y1)
        rel = np.array([px, py]) - center
        position_axis = float(rel @ major)
        position_cross = float(rel @ minor)
        candidates.append({"position_xy": [px, py],
            "bbox_xyxy": [x + x1, y + y1, x + x1 + width, y + y1 + height],
            "position_status": "OBSERVED_TERMINAL", "review_required": True,
            "evidence": ["LOCAL_BRIGHT_LOW_SATURATION_REGION", "OUTSIDE_COMPONENT_BODY"],
            "body_axis_position": position_axis, "body_cross_axis_position": position_cross,
            "heuristic_score": float(min(1.0, area / max(max_area, 1.0))),
            "score_kind": "RULE_BASED_NOT_CALIBRATED"})
    candidates.sort(key=lambda row: (round(row["body_axis_position"], 3), round(row["body_cross_axis_position"], 3)))
    return candidates[:max_candidates]
