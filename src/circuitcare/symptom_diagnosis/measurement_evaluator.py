"""Scope measurement judgments to one component, one fault, and one test condition."""

from __future__ import annotations

from math import isfinite
from typing import Any


def evaluate_component_measurements(measurements: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Evaluate only real, location-confirmed measurements with cited normal limits."""
    evaluations: dict[tuple[str, str], dict[str, Any]] = {}
    for row in measurements or []:
        if not isinstance(row, dict):
            continue
        component_id = str(row.get("component_id") or "")
        fault_id = str(row.get("fault_hypothesis") or "")
        measurement_id = str(row.get("measurement_id") or "")
        target = str(row.get("measurement_target") or "").strip()
        condition = str(row.get("operating_conditions") or "").strip().casefold()
        reference_condition = str(row.get("reference_conditions") or "").strip().casefold()
        low, high = row.get("reference_min"), row.get("reference_max")
        reference_source = str(row.get("reference_source") or "").strip()
        reason = None
        if not component_id or not fault_id or not measurement_id:
            reason = "측정 대상 부품 또는 고장 가설이 지정되지 않음"
        elif row.get("source") != "user_measurement" or row.get("verification_status") != "USER_REPORTED":
            reason = "실제 사용자 측정으로 확인되지 않음"
        elif row.get("location_verified") is not True:
            reason = "측정 위치와 부품 연결을 확인하지 않음"
        elif not target:
            reason = "측정 대상/단자가 지정되지 않음"
        elif low is None or high is None or not reference_source:
            reason = "출처가 있는 정상 기준 범위가 없음"
        elif not condition or condition != reference_condition:
            reason = "실제 측정 조건과 정상 기준 조건이 일치하지 않음"
        elif row.get("uncertainty") is None:
            reason = "측정기 오차 또는 측정 불확실도를 입력하지 않음"
        elif not str(row.get("uncertainty_source") or "").strip():
            reason = "측정기 오차 근거(계측기 사양)가 없음"
        else:
            try:
                value = float(row["value"])
                low_value, high_value = float(low), float(high)
                sigma = float(row["uncertainty"] or 0.0)
                if not all(isfinite(x) for x in (value, low_value, high_value, sigma)) or low_value > high_value or sigma <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError, OverflowError):
                reason = "측정값 또는 정상 범위가 유효하지 않음"
            else:
                measured_low, measured_high = value - sigma, value + sigma
                if measured_low >= low_value and measured_high <= high_value:
                    status = "TEST_NORMAL"
                    reason = "해당 측정 항목과 조건이 정상 범위 안에 있음"
                elif measured_high < low_value or measured_low > high_value:
                    status = "TEST_ABNORMAL"
                    reason = "해당 측정 항목과 조건이 정상 범위를 벗어남"
                else:
                    status = "INCONCLUSIVE"
                    reason = "측정 불확실도 범위가 정상 기준 경계와 겹침"
                key = (component_id, fault_id)
                previous = evaluations.get(key)
                # Conflicting or incomparable assessments are never collapsed into green/red.
                if previous and previous["status"] == "INCONCLUSIVE":
                    evaluations[key] = {
                        "component_id": component_id, "fault_id": fault_id,
                        "status": status, "reason": reason,
                        "measurement_target": target, "operating_conditions": condition,
                        "reference_source": reference_source, "reference_min": low_value,
                        "reference_max": high_value, "value": value, "unit": row.get("unit"),
                        "evidence_ids": [*previous.get("evidence_ids", []), measurement_id],
                    }
                elif previous and previous["status"] != status:
                    evaluations[key] = {
                        "component_id": component_id, "fault_id": fault_id,
                        "status": "CONFLICTED",
                        "reason": "같은 가설에 대해 측정 결과가 서로 다름",
                        "evidence_ids": [*previous.get("evidence_ids", []), measurement_id],
                    }
                elif not previous:
                    evaluations[key] = {
                        "component_id": component_id, "fault_id": fault_id,
                        "status": status, "reason": reason,
                        "measurement_target": target, "operating_conditions": condition,
                        "reference_source": reference_source, "reference_min": low_value,
                        "reference_max": high_value, "value": value, "unit": row.get("unit"),
                        "evidence_ids": [measurement_id],
                    }
                else:
                    previous["evidence_ids"].append(measurement_id)
                continue

        if component_id and fault_id:
            key = (component_id, fault_id)
            # Keep an earlier valid result; an incomplete later record cannot erase it.
            previous = evaluations.get(key)
            if not previous or previous.get("status") == "INCONCLUSIVE":
                evidence_ids = list(previous.get("evidence_ids", [])) if previous else []
                if measurement_id:
                    evidence_ids.append(measurement_id)
                evaluations[key] = {"component_id": component_id, "fault_id": fault_id,
                                    "status": "INCONCLUSIVE", "reason": reason,
                                    "evidence_ids": evidence_ids}
    return evaluations
