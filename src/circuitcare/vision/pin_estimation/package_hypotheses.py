"""Conservative footprint-family hypotheses from known type/count/outline cues."""

from __future__ import annotations

from typing import Any


HIDDEN_LEAD_PACKAGES = {"QFN", "BGA"}


def package_candidates(component: dict[str, Any]) -> list[tuple[str, int | None, tuple[int, ...], str, bool]]:
    """Return candidate (name, count, side counts, evidence, leads-hidden) rows."""
    kind = str(component.get("component_type", "")).strip().lower()
    package_hint = str(component.get("package_hint", "")).strip().upper().replace("-", "_")
    try:
        pin_count = int(component.get("pin_count", component.get("terminal_count")))
        if pin_count <= 0:
            pin_count = None
    except (TypeError, ValueError):
        pin_count = None

    candidates: list[tuple[str, int | None, tuple[int, ...], str, bool]] = []
    if kind in {"resistor", "capacitor", "inductor", "diode", "fuse", "two_terminal_fuse"}:
        candidates.append(("TWO_TERMINAL_SMD_CANDIDATE", 2, (), "COMPONENT_TYPE_AND_BODY_GEOMETRY", False))
    elif kind in {"crystal", "crystal_resonator"}:
        if pin_count == 2:
            candidates.append(("TWO_TERMINAL_CRYSTAL_CANDIDATE", 2, (), "DECLARED_TERMINAL_COUNT_AND_BODY_GEOMETRY", False))
        else:
            candidates.append(("CRYSTAL_PIN_COUNT_UNRESOLVED", pin_count, (), "COMPONENT_TYPE_ONLY", False))
    elif kind in {"integrated_circuit", "ic", "microcontroller", "transistor", "connector", "header", "switch_button"}:
        if package_hint in {"QFN", "BGA"}:
            candidates.append((f"{package_hint}_CANDIDATE", pin_count, (), "EXPLICIT_PACKAGE_HINT; LEADS_NOT_VISIBLE", True))
        elif package_hint:
            normalized = package_hint.replace("_CANDIDATE", "")
            candidates.extend(_from_explicit_package(normalized, pin_count))
        elif pin_count is None:
            candidates.append(("UNKNOWN_MULTIPIN_PACKAGE_CANDIDATE", None, (), "COMPONENT_TYPE_ONLY", False))
        elif kind in {"connector", "header"}:
            candidates.append(("EXTERNAL_CONNECTOR_TERMINALS_CANDIDATE", pin_count, (pin_count,),
                               "DECLARED_TERMINAL_COUNT_AND_BODY_GEOMETRY", False))
        elif pin_count == 3:
            candidates.append(("SOT_23_CANDIDATE", 3, (2, 1), "DECLARED_PIN_COUNT_AND_BODY_GEOMETRY", False))
            candidates.append(("UNKNOWN_3_PIN_PACKAGE_CANDIDATE", 3, (), "DECLARED_PIN_COUNT_ONLY", False))
        elif pin_count == 8:
            candidates.extend([
                ("SOIC_8_CANDIDATE", 8, (4, 4), "DECLARED_PIN_COUNT_AND_BODY_GEOMETRY", False),
                ("DIP_8_CANDIDATE", 8, (4, 4), "DECLARED_PIN_COUNT_AND_BODY_GEOMETRY", False),
                ("UNKNOWN_8_PIN_PACKAGE_CANDIDATE", 8, (), "DECLARED_PIN_COUNT_ONLY", False),
            ])
        elif pin_count >= 12 and pin_count % 4 == 0:
            candidates.append((f"QFP_{pin_count}_CANDIDATE", pin_count, (pin_count // 4,) * 4,
                               "DECLARED_PIN_COUNT_AND_BODY_GEOMETRY", False))
            candidates.append((f"UNKNOWN_{pin_count}_PIN_PACKAGE_CANDIDATE", pin_count, (),
                               "DECLARED_PIN_COUNT_ONLY", False))
        elif pin_count % 2 == 0:
            candidates.append((f"SOIC_SOP_{pin_count}_CANDIDATE", pin_count,
                               (pin_count // 2, pin_count // 2), "DECLARED_PIN_COUNT_AND_BODY_GEOMETRY", False))
            candidates.append((f"UNKNOWN_{pin_count}_PIN_PACKAGE_CANDIDATE", pin_count, (),
                               "DECLARED_PIN_COUNT_ONLY", False))
        else:
            candidates.append((f"UNKNOWN_{pin_count}_PIN_PACKAGE_CANDIDATE", pin_count, (),
                               "DECLARED_PIN_COUNT_ONLY", False))
    else:
        return []

    return candidates


def _from_explicit_package(package: str, pin_count: int | None
                           ) -> list[tuple[str, int | None, tuple[int, ...], str, bool]]:
    if package in HIDDEN_LEAD_PACKAGES:
        return [(f"{package}_CANDIDATE", pin_count, (), "EXPLICIT_PACKAGE_HINT; LEADS_NOT_VISIBLE", True)]
    try:
        count = pin_count or int("".join(character for character in package if character.isdigit()))
    except ValueError:
        count = pin_count
    if count is None:
        return [(f"{package}_CANDIDATE", None, (), "EXPLICIT_PACKAGE_HINT", False)]
    if package.startswith("SOT_23"):
        sides = (2, 1) if count == 3 else ()
    elif package.startswith(("QFP", "TQFP", "LQFP")):
        sides = (count // 4,) * 4 if count % 4 == 0 else ()
    elif package.startswith(("SOIC", "SOP", "DIP", "TSSOP")):
        sides = (count // 2, count // 2) if count % 2 == 0 else ()
    else:
        sides = ()
    return [(f"{package}_CANDIDATE", count, sides, "EXPLICIT_PACKAGE_HINT", False)]
