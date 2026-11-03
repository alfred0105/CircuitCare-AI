"""Evidence-only component-center and risk overlay renderer."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

RISK_COLORS = {
    "EXCEEDED": (220, 38, 38),
    "NEAR_LIMIT": (245, 130, 32),
    "WITHIN_LIMIT": (70, 120, 165),
    "UNKNOWN": (130, 140, 150),
    "KNOWN_FAILED": (150, 45, 175),
}


def risk_by_reference(risk_assessment: dict[str, Any] | None, *, expected_fault: str | None,
                      expected_fault_type: str | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not risk_assessment:
        return {}, "현재 회로/고장 조건에 사용할 위험 평가 결과가 없습니다."
    if risk_assessment.get("simulation_status") != "success":
        return {}, "위험 평가가 성공한 시뮬레이션 결과가 아닙니다."
    if expected_fault and risk_assessment.get("failed_component") != expected_fault:
        return {}, "위험 보고서의 고장 부품이 현재 선택과 일치하지 않습니다."
    if expected_fault_type and risk_assessment.get("fault_type") != expected_fault_type:
        return {}, "위험 보고서의 고장 유형이 현재 선택과 일치하지 않습니다."
    result = {}
    for row in risk_assessment.get("secondary_candidates", []):
        ref = row.get("component_ref")
        if ref:
            result[ref] = dict(row)
    failed = risk_assessment.get("failed_component")
    if failed:
        result[failed] = {"component_ref": failed, "risk_level": "KNOWN_FAILED", "priority_rank": 0,
                          "reason": "사용자가 현재 분석의 고장 부품으로 지정했습니다.", "damage_confirmed": False}
    return result, None


def render_risk_overlay(image: Image.Image, component_locations: dict[str, Any],
                        risk_assessment: dict[str, Any] | None = None, *,
                        expected_fault: str | None = None,
                        expected_fault_type: str | None = None,
                        show_risk: bool = True,
                        selected_reference: str | None = None) -> tuple[Image.Image, dict[str, Any]]:
    records = component_locations.get("components", [])
    risks, risk_issue = risk_by_reference(
        risk_assessment, expected_fault=expected_fault, expected_fault_type=expected_fault_type,
    ) if show_risk else ({}, None)
    output = image.convert("RGB").copy()
    draw = ImageDraw.Draw(output)
    font = ImageFont.load_default()
    matched, unmatched = [], []
    for location in records:
        ref = location["reference"]
        risk = risks.get(ref)
        u, v = map(float, location["image_position_px"])
        radius = 13 if ref == selected_reference else 9
        color = RISK_COLORS.get(risk.get("risk_level"), RISK_COLORS["UNKNOWN"]) if risk else RISK_COLORS["UNKNOWN"]
        draw.ellipse((u - radius, v - radius, u + radius, v + radius), fill=color, outline=(255, 255, 255), width=3)
        label = ref
        if risk and risk.get("priority_rank") is not None and risk.get("priority_rank") != 0:
            label += f" #{risk['priority_rank']}"
        box = draw.textbbox((u + radius + 3, v - radius), label, font=font, stroke_width=1)
        draw.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill=(20, 25, 32))
        draw.text((u + radius + 3, v - radius), label, fill=(255, 255, 255), font=font, stroke_width=1)
        if risk:
            matched.append({**location, "risk": risk})
        else:
            unmatched.append(location)
    return output, {"matched": matched, "without_risk_result": unmatched, "risk_issue": risk_issue,
                    "risk_overlay_enabled": show_risk and risk_issue is None}
