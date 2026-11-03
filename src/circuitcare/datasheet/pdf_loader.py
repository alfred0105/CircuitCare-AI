"""Bounded local PDF text and optional table extraction."""
from __future__ import annotations
import hashlib
import io
from typing import Any

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 200

class DatasheetError(ValueError):
    """Invalid, unsupported, or over-limit local PDF."""

def load_pdf(data: bytes, filename: str, *, max_bytes: int = MAX_PDF_BYTES, max_pages: int = MAX_PDF_PAGES) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise DatasheetError("The uploaded PDF is empty.")
    if len(data) > max_bytes:
        raise DatasheetError(f"PDF exceeds the {max_bytes // (1024 * 1024)} MiB size limit.")
    if not data.startswith(b"%PDF-"):
        raise DatasheetError("The uploaded file does not have a PDF signature.")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DatasheetError('Install PDF support with: python -m pip install -e ".[datasheet]"') from exc
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DatasheetError("Encrypted PDFs are not supported. Provide an unlocked local copy.")
        if not reader.pages:
            raise DatasheetError("PDF contains no pages.")
        if len(reader.pages) > max_pages:
            raise DatasheetError(f"PDF exceeds the {max_pages}-page processing limit.")
        pages = [{"page_index": index, "text": page.extract_text(extraction_mode="layout") or ""}
                 for index, page in enumerate(reader.pages)]
        metadata = {str(key).lstrip("/"): str(value) for key, value in (reader.metadata or {}).items() if value is not None}
    except DatasheetError:
        raise
    except Exception as exc:
        raise DatasheetError(f"Could not read PDF: {exc}") from exc
    extracted = sum(bool(page["text"].strip()) for page in pages)
    return {"filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
            "page_count": len(pages), "metadata": metadata, "pages": pages,
            "text_status": "TEXT_EXTRACTED" if extracted else "OCR_REQUIRED", "pages_with_text": extracted}

def extract_pdf_tables(data: bytes) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError:
        return []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [{"page_index": index, "table_index": table_index,
                     "rows": [[cell or "" for cell in row] for row in (table or [])]}
                    for index, page in enumerate(pdf.pages)
                    for table_index, table in enumerate(page.extract_tables() or []) if table]
    except Exception as exc:
        raise DatasheetError(f"PDF table extraction failed: {exc}") from exc
