"""Image-space geometry helpers; positions remain canonical-image pixels."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def component_axis(component: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, float, float] | None:
    """Return center, stable major-axis unit vector, half-length, and half-width."""
    polygon = component.get("polygon_xy")
    points = None
    if isinstance(polygon, (list, tuple)) and len(polygon) >= 4:
        try:
            parsed = np.asarray(polygon, dtype=np.float64).reshape(-1, 2)
            if np.isfinite(parsed).all():
                points = parsed
        except (TypeError, ValueError):
            points = None
    if points is None:
        box = component.get("bbox_xyxy")
        try:
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                return None
            x1, y1, x2, y2 = map(float, box)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)) or x1 >= x2 or y1 >= y2:
            return None
        points = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float64)

    center = points.mean(axis=0)
    centered = points - center
    covariance = centered.T @ centered / max(len(points), 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major = eigenvectors[:, int(np.argmax(eigenvalues))]
    # Make orientation deterministic under equivalent PCA eigenvector signs.
    if major[0] < -1e-9 or (abs(major[0]) <= 1e-9 and major[1] < 0):
        major = -major
    minor = np.array([-major[1], major[0]])
    projections = centered @ major
    cross = centered @ minor
    half_length = float((projections.max() - projections.min()) / 2)
    half_width = float((cross.max() - cross.min()) / 2)
    if half_length <= 0 or half_width <= 0:
        return None
    return center, major, half_length, half_width


def terminal_pair(component: dict[str, Any], *, offset_ratio: float = 0.12) -> list[dict[str, Any]]:
    axis = component_axis(component)
    if axis is None:
        return []
    center, major, half_length, half_width = axis
    if half_length / max(half_width, 1e-9) < 1.15:
        return []
    offset = max(1.0, half_width * offset_ratio)
    positions = [center - major * (half_length + offset), center + major * (half_length + offset)]
    return [{"terminal_id": "terminal_a", "position_xy": [float(point[0]), float(point[1])],
             "evidence": ["BODY_LONG_AXIS", "BODY_BOUNDING_GEOMETRY"],
             "position_status": "GEOMETRY_ESTIMATED"} for point in positions[:1]] + [
            {"terminal_id": "terminal_b", "position_xy": [float(positions[1][0]), float(positions[1][1])],
             "evidence": ["BODY_LONG_AXIS", "BODY_BOUNDING_GEOMETRY"],
             "position_status": "GEOMETRY_ESTIMATED"}]


def multipin_positions(component: dict[str, Any], package_type: str,
                       side_counts: tuple[int, ...]) -> list[dict[str, Any]]:
    """Place orientation-independent candidates around the body perimeter."""
    axis = component_axis(component)
    if axis is None:
        return []
    center, major, half_length, half_width = axis
    minor = np.array([-major[1], major[0]])
    margin = max(1.0, min(half_length, half_width) * 0.12)
    terminals = []

    if package_type == "EXTERNAL_CONNECTOR_TERMINALS_CANDIDATE":
        count = side_counts[0] if side_counts else 0
        offsets = np.linspace(-half_length * 0.82, half_length * 0.82, count) if count else []
        return [{"terminal_id": f"edge_candidate_{index:02d}",
                 "position_xy": [float(point[0]), float(point[1])],
                 "evidence": ["DECLARED_TERMINAL_COUNT", "BODY_GEOMETRY_CANDIDATE"],
                 "position_status": "GEOMETRY_ESTIMATED"}
                for index, value in enumerate(offsets, 1)
                for point in [center + minor * (half_width + margin) + major * float(value)]]

    def add(side_name: str, direction: np.ndarray, run_axis: np.ndarray,
            outward_distance: float, half_span: float, count: int) -> None:
        if count <= 0:
            return
        # Avoid corners by using 82% of each side span.
        offsets = np.linspace(-half_span * 0.82, half_span * 0.82, count)
        for index, value in enumerate(offsets, 1):
            point = center + direction * outward_distance
            point = point + direction * margin + run_axis * float(value)
            terminals.append({"terminal_id": f"{side_name}_{index:02d}",
                "position_xy": [float(point[0]), float(point[1])],
                "evidence": ["PACKAGE_GEOMETRY_CANDIDATE", "BODY_LONG_AXIS"],
                "position_status": "GEOMETRY_ESTIMATED"})

    if package_type == "SOT_23_CANDIDATE":
        # Typical outline hypothesis: two leads on one long edge, one on the other.
        add("side_a_long", minor, major, half_width, half_length, side_counts[0])
        add("side_b_long", -minor, major, half_width, half_length, side_counts[1])
    else:
        # Leads are modeled on the two long sides, or all four for QFP.
        if len(side_counts) == 4:
            add("side_top", -minor, major, half_width, half_length, side_counts[0])
            add("side_right", major, minor, half_length, half_width, side_counts[1])
            add("side_bottom", minor, major, half_width, half_length, side_counts[2])
            add("side_left", -major, minor, half_length, half_width, side_counts[3])
        else:
            add("side_a_long", minor, major, half_width, half_length, side_counts[0])
            add("side_b_long", -minor, major, half_width, half_length, side_counts[1])
    return terminals
