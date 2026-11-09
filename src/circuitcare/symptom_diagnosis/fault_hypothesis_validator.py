"""Hard safety gates for component-level fault hypotheses."""

from __future__ import annotations

from typing import Any


_INTRINSIC_ROLE_TYPES = {"battery", "buzzer", "fuse", "led", "relay", "switch"}


def validate_component_hypothesis(
    *, mode: dict[str, Any], component: dict[str, Any], confirmed_component_ids: set[str],
    component_block: dict[str, Any] | None = None,
    component_observations: list[dict[str, Any]] | None = None,
    has_validated_measurement: bool = False,
) -> dict[str, Any]:
    """Return an explicit eligibility decision; detection alone never confirms presence."""
    component_id = str(component.get("component_id") or "")
    component_type = str(component.get("component_type", component.get("label", "unknown"))).casefold()
    allowed_types = {str(value).casefold() for value in mode.get("component_types", [])}
    reasons: list[str] = []
    if not component_id or component_id not in confirmed_component_ids:
        reasons.append("COMPONENT_PRESENCE_UNCONFIRMED")
    if allowed_types and component_type not in allowed_types:
        reasons.append("INCOMPATIBLE_COMPONENT_TYPE")

    required_roles = {str(value) for value in mode.get("functional_roles", [])}
    if required_roles:
        confirmed_roles = {str(value) for value in component.get("confirmed_functional_roles", [])}
        block = component_block or {}
        if block.get("verified"):
            confirmed_roles.update(str(value) for value in block.get("candidate_blocks", []))
        directly_supported = any(
            str(row.get("component_id") or "") == component_id and row.get("value") is True
            and row.get("code") in mode.get("supporting_evidence", {})
            for row in (component_observations or []) if isinstance(row, dict)
        )
        role_supported = bool(required_roles & confirmed_roles) or directly_supported or has_validated_measurement
        intrinsic_role_match = component_type in _INTRINSIC_ROLE_TYPES
        if not role_supported and not intrinsic_role_match:
            reasons.append("FUNCTIONAL_ROLE_UNCONFIRMED")

    return {"eligible": not reasons, "reasons": reasons,
            "component_id": component_id, "component_type": component_type}
