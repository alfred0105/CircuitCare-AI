"""Conservative lookup policy for OCR candidates read from IC package markings.

This module deliberately does not perform network requests. Supply results from
an approved manufacturer/distributor search provider to ``resolve_ic_marking``.
Only an exact marking match on a semiconductor manufacturer or distributor page
is returned as a part-number candidate. Every outcome retains the detector class
as ``IC``; unresolved text is never guessed into a different component class.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


TRUSTED_PART_SOURCES = frozenset({
    "analog.com", "digikey.com", "infineon.com", "lcsc.com", "microchip.com",
    "mouser.com", "nxp.com", "onsemi.com", "renesas.com", "st.com",
    "ti.com", "winbond.com",
})


def _canonical(value: str) -> str:
    return "".join(char for char in str(value).upper() if char.isalnum())


def _valid_candidate(value: str) -> bool:
    compact = _canonical(value)
    return 3 <= len(compact) <= 40 and any(c.isalpha() for c in compact) and any(c.isdigit() for c in compact)


def _trusted_domain(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in TRUSTED_PART_SOURCES)


def _exact_marking_match(marking: str, text: str) -> bool:
    """Match the full alphanumeric marking while allowing spaces/dashes between chars."""
    chars = [re.escape(c) for c in _canonical(marking)]
    if not chars:
        return False
    pattern = r"(?<![A-Z0-9])" + r"[\W_]*".join(chars) + r"(?![A-Z0-9])"
    return re.search(pattern, str(text), flags=re.IGNORECASE) is not None


def resolve_ic_marking(
    ocr_text: str,
    search_results: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve an OCR string only when a trusted source confirms the exact mark.

    Search result mappings should contain ``title``, ``url``, and optionally
    ``snippet``. The input OCR string is preserved without autocorrection.
    """
    raw = str(ocr_text or "").strip()
    base = {
        "class_name": "IC",
        "ocr_text": raw,
        "part_number": None,
        "lookup_status": "UNRESOLVED_IC",
        "source_url": None,
        "source_title": None,
    }
    if not _valid_candidate(raw):
        base["reason"] = "OCR text is not a plausible alphanumeric part marking."
        return base

    for result in search_results:
        if not isinstance(result, Mapping):
            continue
        url = str(result.get("url", ""))
        title = str(result.get("title", ""))
        snippet = str(result.get("snippet", ""))
        if not _trusted_domain(url):
            continue
        if not (_exact_marking_match(raw, title) or _exact_marking_match(raw, snippet)):
            continue
        base.update({
            "part_number": raw,
            "lookup_status": "PART_CANDIDATE_FOUND",
            "source_url": url,
            "source_title": title,
            "reason": "Exact marking found on a trusted manufacturer/distributor page; human confirmation is still recommended.",
        })
        return base

    base["reason"] = "No exact match found on a trusted manufacturer/distributor page; keep the component labeled IC."
    return base
