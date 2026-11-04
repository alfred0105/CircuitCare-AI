"""JSON, Markdown, standalone HTML, and allowlisted evidence ZIP export."""

from __future__ import annotations

import hashlib
import html
import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from circuitcare.reporting.report_validator import validate_report, verify_bundle


def export_json(report: dict[str, Any]) -> str:
    errors = validate_report(report)
    if errors:
        raise ValueError("Report validation failed: " + ", ".join(errors))
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def export_markdown(report: dict[str, Any]) -> str:
    circuit = report.get("circuit", {})
    fault = report.get("fault_or_symptom", {})
    spice = report.get("spice_verification", {})
    risk = report.get("secondary_damage_risk", {})
    lines = ["# CircuitCare AI 진단 보고서", "",
             f"- 회로: {circuit.get('name', 'Unknown')}",
             f"- Circuit Hash: `{circuit.get('hash', 'NOT_EVALUATED')}`",
             f"- 생성 시각: {report.get('generated_at', 'NOT_EVALUATED')}",
             f"- 부품 / Net: {circuit.get('component_count', 0)} / {circuit.get('net_count', 0)}", "",
             "## 고장 및 관측", "",
             f"- 모드: {fault.get('mode', 'NOT_EVALUATED')}",
             f"- 대상: {fault.get('component_ref', 'NOT_EVALUATED')} / {fault.get('fault_type', 'NOT_EVALUATED')}",
             f"- 관측 분류: {fault.get('observation_classification', 'NOT_EVALUATED')}", "",
             "## 파라미터 후보 Grid", "",
             f"- 상태: {report.get('parameter_identification', {}).get('status', 'NOT_EVALUATED')}",
             f"- 해석: {report.get('parameter_identification', {}).get('interpretation', '후보 Grid 비교를 수행하지 않았습니다.')}", "",
             "## SPICE 검증", "",
             f"- 상태: {spice.get('status', 'NOT_EVALUATED')}",
             f"- 출처: {spice.get('source', 'NOT_EVALUATED')}",
             f"- Scenario ID: {spice.get('scenario_id') or 'NOT_EVALUATED'}", "",
             "## 정격 스트레스 검토", "",
             f"- 상태: {risk.get('status', 'RECORDED')}",
             "- 손상 확정 여부: 아니요", "",
             "## 근거", ""]
    for evidence in report.get("evidence", []):
        lines.append(f"- {evidence.get('evidence_id')}: {evidence.get('evidence_type')} · {evidence.get('verification_status')} · {evidence.get('source_artifact') or '원본 파일 없음'}")
    lines.extend(["", "## 한계", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.extend(["", "## 재현 정보", "", f"- Git SHA: `{report.get('reproducibility', {}).get('git_sha') or 'NOT_EVALUATED'}`", ""])
    return "\n".join(lines)


def export_html(report: dict[str, Any]) -> str:
    markdown = export_markdown(report)
    escaped = html.escape(markdown)
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>CircuitCare AI 진단 보고서</title><style>body{font:16px/1.6 system-ui,sans-serif;"
            "max-width:960px;margin:3rem auto;padding:0 1.25rem;color:#17212b;background:#f8fafc}"
            "pre{white-space:pre-wrap;background:white;padding:1.5rem;border:1px solid #d8e0e8;"
            "border-radius:10px}</style></head><body><h1>CircuitCare AI 진단 보고서</h1><pre>"
            f"{escaped}</pre></body></html>")


def export_bundle(report: dict[str, Any], *, root: Path,
                  selected_artifacts: dict[str, Path] | None = None) -> bytes:
    """Bundle report outputs and only explicitly selected, in-root artifacts."""
    files: dict[str, bytes] = {
        "diagnosis.json": export_json(report).encode("utf-8"),
        "report.md": export_markdown(report).encode("utf-8"),
        "report.html": export_html(report).encode("utf-8"),
    }
    allowed = {"measurements.json", "fault_hypotheses.json", "spice_results.json",
               "risk_assessment.json", "rating_evidence.json"}
    root = root.resolve()
    for archive_name, path in (selected_artifacts or {}).items():
        if archive_name not in allowed:
            raise ValueError(f"Artifact is not an approved bundle item: {archive_name}")
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Evidence artifact must be inside the workspace root.") from exc
        if not resolved.is_file():
            raise ValueError(f"Evidence artifact does not exist: {archive_name}")
        files[f"evidence/{archive_name}"] = resolved.read_bytes()
    manifest = {"bundle_version": "circuitcare-evidence-bundle-v1",
                "workspace_id": report.get("workspace", {}).get("workspace_id"),
                "circuit_hash": report.get("circuit", {}).get("hash"),
                "analysis_timestamp": report.get("generated_at"),
                "evidence_sources": report.get("evidence", []),
                "missing_artifacts": ["measurement raw file not selected", "PCB original image excluded by default"],
                "model_versions": report.get("reproducibility", {}),
                "artifacts": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())}}
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            archive.writestr(name, value)
    result = buffer.getvalue()
    verify_bundle(result)
    return result
