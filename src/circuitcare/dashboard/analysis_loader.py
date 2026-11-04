"""Load and classify one simulation result snapshot for dashboard views."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from circuitcare.dashboard.context import _simulation_status
from circuitcare.workspace.simulation_context import verify_simulation_manifest


def json_object_if_exists(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@dataclass(frozen=True)
class AnalysisSnapshot:
    result_dir: Path
    comparison: dict
    risk: dict
    stress: dict
    manifest: dict
    integrity: str
    status: str


def load_analysis_snapshot(*, result_dir: Path, current_fingerprint: dict,
                           live_used: bool, live_error: str | None,
                           cached_selection: bool) -> AnalysisSnapshot:
    """Read files and fail closed for invalid cached provenance while preserving live status."""
    comparison = json_object_if_exists(result_dir / "comparison.json")
    risk = json_object_if_exists(result_dir / "risk_assessment.json")
    stress = json_object_if_exists(result_dir / "component_stress.json")
    manifest = json_object_if_exists(result_dir / "simulation_context.json")
    integrity, _ = verify_simulation_manifest(result_dir, manifest, current_fingerprint)
    if not live_used and cached_selection and integrity != "VERIFIED":
        comparison, risk, stress = {}, {}, {}

    status = _simulation_status(live_used, live_error, cached_selection)
    if status == "CACHED":
        status = "CACHED_SIMULATION" if integrity == "VERIFIED" else integrity
    if status in {"STALE", "PROVENANCE_UNVERIFIED"} or (
        status == "FAILED" and cached_selection and integrity != "VERIFIED"
    ):
        comparison, risk, stress = {}, {}, {}
    return AnalysisSnapshot(result_dir, comparison, risk, stress, manifest, integrity, status)
