from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest

from circuitcare.datasheet.pdf_loader import DatasheetError, clear_pdf_cache, load_pdf
from circuitcare.datasheet.pdf_supervisor import run_pdf_worker


def _pdf(page_count: int = 1) -> bytes:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.integration
@pytest.mark.parametrize("pages", [1, 50])
def test_pdf_worker_parses_small_and_medium_documents(pages: int) -> None:
    document = load_pdf(_pdf(pages), f"{pages}-page.pdf")
    assert document["page_count"] == pages
    assert document["worker"]["result_status"] == "PASSED"
    assert document["worker"]["worker_pid"] != document["worker"]["parent_pid"]
    assert len(document["sha256"]) == 64


@pytest.mark.integration
def test_pdf_worker_rejects_malformed_input_without_terminating_parent() -> None:
    with pytest.raises(DatasheetError):
        load_pdf(b"%PDF-1.7 damaged structure", "damaged.pdf")


@pytest.mark.integration
def test_pdf_worker_timeout_and_memory_limit_are_supervised() -> None:
    data = _pdf()
    with pytest.raises(DatasheetError, match="TIMEOUT"):
        run_pdf_worker(data, "document", timeout_seconds=0.001)
    with pytest.raises(DatasheetError, match="MEMORY_LIMIT"):
        run_pdf_worker(data, "document", max_rss_bytes=1)


@pytest.mark.integration
def test_pdf_worker_records_signal_termination_without_crashing_parent(monkeypatch) -> None:
    import circuitcare.datasheet.pdf_supervisor as supervisor

    records = []

    class SignaledWorker:
        pid = 12345
        stdout = BytesIO(b"")
        stderr = BytesIO(b"isolated worker signal")

        @staticmethod
        def poll():
            return -11

        @staticmethod
        def wait():
            return -11

    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: SignaledWorker())
    monkeypatch.setattr(supervisor, "_save_diagnostic", records.append)
    with pytest.raises(DatasheetError, match="exit -11"):
        run_pdf_worker(_pdf(), "document")
    assert records[0]["signal"] == "SIGSEGV"
    assert records[0]["result_status"] == "FAILED"


@pytest.mark.integration
def test_pdf_cache_reuses_same_hash_and_invalidates_changed_file() -> None:
    clear_pdf_cache()
    first_data, second_data = _pdf(1), _pdf(2)
    first = load_pdf(first_data, "same.pdf")
    again = load_pdf(first_data, "renamed.pdf")
    changed = load_pdf(second_data, "same.pdf")
    assert again["filename"] == "renamed.pdf"
    assert first["sha256"] == again["sha256"] != changed["sha256"]
    assert again["worker"]["worker_pid"] == first["worker"]["worker_pid"]
    assert changed["worker"]["worker_pid"] != first["worker"]["worker_pid"]


@pytest.mark.integration
def test_concurrent_pdf_worker_requests_keep_document_context_separate() -> None:
    first_data, second_data = _pdf(1), _pdf(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(load_pdf, first_data, "circuit-a.pdf")
        second_future = pool.submit(load_pdf, second_data, "circuit-b.pdf")
        first, second = first_future.result(), second_future.result()
    assert first["filename"] == "circuit-a.pdf" and first["page_count"] == 1
    assert second["filename"] == "circuit-b.pdf" and second["page_count"] == 2
    assert first["sha256"] != second["sha256"]


@pytest.mark.integration
def test_concurrent_sessions_for_same_pdf_keep_filename_context_separate() -> None:
    data = _pdf(1)
    clear_pdf_cache()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(load_pdf, data, "session-a.pdf")
        second_future = pool.submit(load_pdf, data, "session-b.pdf")
        first, second = first_future.result(), second_future.result()
    assert first["sha256"] == second["sha256"]
    assert first["filename"] == "session-a.pdf"
    assert second["filename"] == "session-b.pdf"
