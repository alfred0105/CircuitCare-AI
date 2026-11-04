"""Validation for report provenance and exported bundle manifests."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_report(report: dict[str, Any], *, expected_circuit_hash: str | None = None) -> list[str]:
    errors = []
    circuit = report.get("circuit", {})
    if expected_circuit_hash and circuit.get("hash") != expected_circuit_hash:
        errors.append("STALE_CIRCUIT_CONTEXT")
    evidence_ids = {row.get("evidence_id") for row in report.get("evidence", [])}
    current_hash = circuit.get("hash")
    for evidence in report.get("evidence", []):
        evidence_hash = evidence.get("circuit_hash")
        if evidence_hash and current_hash and evidence_hash != current_hash:
            errors.append(f"CROSS_CIRCUIT_EVIDENCE:{evidence.get('evidence_id')}")
    scenario_ids = {row.get("scenario_id") for row in report.get("evidence", []) if row.get("scenario_id")}
    report_scenario = report.get("spice_verification", {}).get("scenario_id")
    if report_scenario and scenario_ids and report_scenario not in scenario_ids:
        errors.append("CROSS_SCENARIO_EVIDENCE")
    for finding in report.get("findings", []):
        if any(source not in evidence_ids for source in finding.get("source_evidence_ids", [])):
            errors.append(f"MISSING_FINDING_EVIDENCE:{finding.get('finding_id')}")
    if report.get("secondary_damage_risk", {}).get("damage_confirmed") is True:
        errors.append("UNSUPPORTED_DAMAGE_CONFIRMATION")
    return errors


def verify_bundle(bundle: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(__import__("io").BytesIO(bundle)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate bundle paths are not allowed.")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe path in evidence bundle.")
        manifest = json.loads(archive.read("manifest.json"))
        for name, expected in manifest.get("artifacts", {}).items():
            if name not in names:
                raise ValueError(f"Manifest artifact missing: {name}")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if not SHA256_RE.fullmatch(expected) or actual != expected:
                raise ValueError(f"Artifact hash mismatch: {name}")
        return manifest
