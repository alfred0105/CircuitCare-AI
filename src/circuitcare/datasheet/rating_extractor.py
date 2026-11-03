"""Conservative rule-based rating candidate discovery."""
from __future__ import annotations
import re
import unicodedata
from typing import Any

_RULES = [
    ("max_power_w", "power_rating", r"(?:rated\s+power|power\s+rating|maximum\s+power\s+dissipation|max(?:imum)?\s+dissipated\s+power|continuous\s+power|^power$)"),
    ("max_current_a", "current_rating", r"(?:maximum\s+continuous\s+current|continuous\s+current|rated\s+current|output\s+current|forward\s+current|peak\s+current)"),
    ("max_abs_voltage_v", "voltage_rating", r"(?:absolute\s+maximum\s+(?:input\s+)?voltage|maximum\s+input\s+voltage|maximum\s+working\s+voltage|working\s+voltage|rated\s+voltage|reverse\s+voltage|breakdown\s+voltage)"),
]
_NUMBER_UNIT = re.compile(r"(?P<value>[+−-]?\s*\d+(?:\.\d+)?)\s*(?P<prefix>m|u|µ|μ|k)?\s*(?P<unit>V|A|W)\b", re.I)
_PREFIX = {"": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "k": 1e3}
_TARGET_UNIT = {"max_power_w": "W", "max_current_a": "A", "max_abs_voltage_v": "V"}

def find_rating_candidates(pages: list[dict[str, Any]], tables: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    results = []
    for table in tables or []:
        for row in table.get("rows", []):
            if len(row) < 2:
                continue
            label, value_text = (_clean(str(row[0])), _clean(str(row[1])))
            for key, rating_type, keyword in _RULES:
                if not re.search(keyword, label, re.I):
                    continue
                # If a cell contains several voltage limits, retain only the value whose adjacent descriptor
                # says continuous/working. Overvoltage and withstand values are separate candidate classes.
                value_match = _NUMBER_UNIT.search(value_text)
                if key == "max_abs_voltage_v" and value_match:
                    descriptor = value_text[max(0, value_match.start() - 32):value_match.end() + 50]
                    if not re.search(r"working|continuous|rated", descriptor, re.I):
                        continue
                if not value_match or value_match.group("unit").upper() != _TARGET_UNIT[key]:
                    continue
                page_index = table["page_index"]
                page_text = next((page.get("text", "") for page in pages if page.get("page_index") == page_index), "")
                candidate = _make_candidate(key, rating_type, value_match, label + " " + value_text,
                                            page_index, "table_rule_based", page_text)
                if candidate:
                    results.append(candidate)
    for page in pages:
        lines = [_clean(line) for line in page.get("text", "").splitlines()]
        for line_no, line in enumerate(lines):
            for key, rating_type, keyword in _RULES:
                if not re.search(keyword, line, re.I):
                    continue
                context = "\n".join(lines[max(0, line_no - 1):min(len(lines), line_no + 3)])
                for match in _NUMBER_UNIT.finditer(context):
                    unit = match.group("unit").upper()
                    if unit != _TARGET_UNIT[key]:
                        continue
                    snippet = context.strip()
                    candidate = _make_candidate(key, rating_type, match, snippet,
                                                int(page["page_index"]), "text_rule_based", page.get("text", ""))
                    if candidate:
                        results.append(candidate)
    unique = {}
    for row in results:
        unique[(row["rating_key"], row["normalized_value"], row["pdf_page_index"], row["source_text"])] = row
    return list(unique.values())

def _make_candidate(key: str, rating_type: str, match: re.Match, snippet: str, page_index: int,
                    method: str, page_text: str = "") -> dict[str, Any] | None:
    raw_number = match.group("value").replace(" ", "").replace("−", "-")
    try:
        value = float(raw_number) * _PREFIX[match.group("prefix") or ""]
    except (ValueError, KeyError):
        return None
    raw_signed_value = value
    if key == "max_abs_voltage_v":
        value = abs(value)
    if value <= 0:
        return None
    lower = snippet.casefold()
    kind = "peak" if re.search(r"peak|overload|pulse|surge", lower) else ("absolute_max" if "absolute maximum" in lower or "absolute max" in lower else "continuous")
    return {"rating_key": key, "rating_type": rating_type, "rating_kind": kind,
            "raw_value": match.group(0).strip(), "normalized_value": value,
            "normalized_unit": _TARGET_UNIT[key], "source_text": snippet.strip(),
            "pdf_page_index": page_index, "printed_page_number": _printed_page_number(page_text),
            "conditions": {**_conditions(snippet), "polarity": "negative" if raw_signed_value < 0 else _conditions(snippet).get("polarity")}, "extraction_method": method,
            "extraction_status": "candidate", "evidence_status": "PENDING_REVIEW", "human_approved": False}

def _clean(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) != "Cf").replace("−", "-").strip()

def _printed_page_number(text: str) -> str | None:
    for line in reversed(text.splitlines()[-20:]):
        match = re.fullmatch(r"\s*(?:page\s*)?(\d{1,4})(?:\s+of\s+\d{1,4})?\s*", _clean(line), re.I)
        if match:
            return match.group(1)
    return None

def _conditions(text: str) -> dict[str, Any]:
    temp = re.search(r"(?:at\s+)?(-?\d+(?:\.\d+)?)\s*°?\s*C", text, re.I)
    duration = "peak" if re.search(r"peak|pulse|surge|overload", text, re.I) else ("continuous" if re.search(r"continuous|rated|working", text, re.I) else None)
    derating = next((line.strip() for line in text.splitlines() if re.search(r"derat|temperature", line, re.I)), None)
    signed = _NUMBER_UNIT.search(text)
    polarity = "negative" if signed and signed.group("value").replace(" ", "").startswith(("-", "−")) else None
    return {"temperature_c": float(temp.group(1)) if temp else None, "duration": duration, "polarity": polarity, "derating_text": derating}
