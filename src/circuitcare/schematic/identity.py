"""Conservative identity extraction from KiCad S-expression schematics."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SymbolIdentity:
    component_ref: str
    symbol_uuid: str
    sheet_path: str
    unit: int
    library_id: str
    value: str
    status: str = "UNVERIFIED_MAPPING"


def _blocks(text: str, marker: str) -> list[str]:
    """Return balanced S-expression blocks starting with marker, respecting strings."""
    found: list[str] = []
    pos = 0
    while True:
        start = text.find(marker, pos)
        if start < 0:
            return found
        depth, quoted, escaped = 0, False, False
        for end in range(start, len(text)):
            char = text[end]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    found.append(text[start:end + 1])
                    pos = end + 1
                    break
        else:
            raise ValueError("Malformed KiCad schematic S-expression")


def _quoted(block: str, key: str) -> str | None:
    match = re.search(rf'\({re.escape(key)}\s+"((?:\\.|[^"\\])*)"', block)
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def _property(block: str, name: str) -> str | None:
    match = re.search(rf'\(property\s+"{re.escape(name)}"\s+"((?:\\.|[^"\\])*)"', block)
    return bytes(match.group(1), "utf-8").decode("unicode_escape") if match else None


def read_symbol_identities(path: str | Path, *, project_root: str | Path) -> tuple[list[SymbolIdentity], list[str]]:
    """Read placed symbols and report referenced hierarchical sheets that are missing."""
    source = Path(path).resolve(strict=True)
    root = Path(project_root).resolve(strict=True)
    if not source.is_relative_to(root) or source.suffix != ".kicad_sch":
        raise ValueError("Schematic must be a .kicad_sch file inside the project root")
    text = source.read_text(encoding="utf-8")
    if len(text) > 20_000_000 or not text.lstrip().startswith("(kicad_sch"):
        raise ValueError("Invalid or oversized KiCad schematic")
    identities = []
    for block in _blocks(text, "(symbol"):
        ref = _property(block, "Reference")
        if not ref or ref.startswith("#"):
            continue
        uuid = _quoted(block, "uuid") or ""
        lib = _quoted(block, "lib_id") or ""
        value = _property(block, "Value") or ""
        unit_match = re.search(r"\(unit\s+(\d+)", block)
        # Instances contain the hierarchical path and canonical ref/unit.
        paths = _blocks(block, "(path ")
        if paths:
            for p in paths:
                instance_ref = _quoted(p, "reference") or ref
                instance_unit = re.search(r"\(unit\s+(\d+)", p)
                identities.append(SymbolIdentity(instance_ref, uuid, _quoted(p, "path") or "/",
                                                  int(instance_unit.group(1)) if instance_unit else int(unit_match.group(1)) if unit_match else 1,
                                                  lib, value))
        else:
            identities.append(SymbolIdentity(ref, uuid, "/", int(unit_match.group(1)) if unit_match else 1, lib, value))
    uuids = [item.symbol_uuid for item in identities if item.symbol_uuid]
    if len(uuids) != len(set(uuids)):
        raise ValueError("Duplicate symbol UUID in schematic")
    missing: list[str] = []
    for sheet in _blocks(text, "(sheet "):
        filename = _quoted(sheet, "name")
        # Sheet names are not file paths; KiCad stores the file in (property "Sheet file" ...).
        filename = _quoted(sheet, "Sheet file") or filename
        if filename and filename.lower().endswith(".kicad_sch"):
            candidate = (source.parent / filename).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                missing.append(filename)
    return identities, sorted(set(missing))


def map_component_refs(component_refs: list[str] | tuple[str, ...], identities: list[SymbolIdentity]) -> dict[str, dict]:
    """Only claim verified mappings when exactly one identity exists for a ref."""
    result = {}
    for ref in component_refs:
        matches = [item for item in identities if item.component_ref == ref]
        unique = {(item.symbol_uuid, item.sheet_path, item.unit) for item in matches}
        if matches and len(unique) == len(matches):
            result[ref] = {
                "component_ref": ref,
                "status": "VERIFIED_REFERENCE",
                "symbol_instances": [asdict(item) for item in matches],
            }
        else:
            result[ref] = {"component_ref": ref, "status": "UNVERIFIED_MAPPING",
                           "match_count": len(matches)}
    return result
