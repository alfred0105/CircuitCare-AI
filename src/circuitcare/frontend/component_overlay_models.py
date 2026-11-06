"""Frontend-only view models for conservative PCB component overlays."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentOverlayViewModel:
    project_id: str
    board_id: str
    board_side: str
    component_id: str
    component_type: str
    display_label: str | None
    canonical_frame_id: str
    coordinate_frame: str
    bbox_xyxy: tuple[float, float, float, float]
    polygon_xy: tuple[tuple[float, float], ...]
    source_backend_photo_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    detection_confidence: float | None
    identification_status: str | None
    identity_match_status: str | None
    ocr_marking: str | None
    possible_part_number: str | None
    evidence: tuple[str, ...]
    overlay_status: str


@dataclass(frozen=True)
class ComponentOverlayResult:
    status: str
    board_id: str
    board_side: str
    canonical_frame_id: str | None
    coordinate_frame: str | None
    image_size_px: tuple[int, int] | None
    components: tuple[ComponentOverlayViewModel, ...]
    detection_status: str
    rejected_count: int = 0
    reason: str | None = None
