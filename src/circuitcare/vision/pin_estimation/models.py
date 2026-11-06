"""Serializable contracts for pin and terminal hypotheses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TerminalHypothesis:
    terminal_id: str
    pin_number: str | None
    pin_function: str
    position_xy: tuple[float, float]
    coordinate_frame: str
    position_status: str
    evidence: tuple[str, ...]
    review_required: bool = True
    heuristic_score: float | None = None
    score_kind: str = "RULE_BASED_NOT_CALIBRATED"

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["position_xy"] = list(self.position_xy)
        row["evidence"] = list(self.evidence)
        return row


@dataclass(frozen=True)
class PackageHypothesis:
    package_type: str
    terminal_count: int | None
    evidence: tuple[str, ...]
    status: str = "CANDIDATE"
    side_terminal_counts: tuple[int, ...] = ()
    pin1_candidate: dict[str, Any] | None = None
    terminals: tuple[TerminalHypothesis, ...] = field(default_factory=tuple)
    observed_pad_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"package_type": self.package_type,
                "terminal_count": self.terminal_count,
                "evidence": list(self.evidence), "status": self.status,
                "side_terminal_counts": list(self.side_terminal_counts),
                "pin1_candidate": self.pin1_candidate,
                "terminals": [terminal.to_dict() for terminal in self.terminals],
                "observed_pad_candidates": list(self.observed_pad_candidates),
                "observed_pad_candidate_count": len(self.observed_pad_candidates)}


@dataclass(frozen=True)
class PinHypothesis:
    component_id: str
    component_type: str
    board_side: str
    source_image_ids: tuple[str, ...]
    coordinate_frame: str
    component_bbox_xyxy: tuple[float, float, float, float] | None
    package_hypotheses: tuple[PackageHypothesis, ...]
    terminals: tuple[TerminalHypothesis, ...]
    status: str
    electrical_connectivity: str = "NOT_EVALUATED"
    measurement_history_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["source_image_ids"] = list(self.source_image_ids)
        row["component_bbox_xyxy"] = list(self.component_bbox_xyxy) if self.component_bbox_xyxy else None
        row["package_hypotheses"] = [item.to_dict() for item in self.package_hypotheses]
        row["terminals"] = [item.to_dict() for item in self.terminals]
        row["measurement_history_refs"] = list(self.measurement_history_refs)
        row["warnings"] = list(self.warnings)
        return row
