import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("acquire_component_dataset", ROOT / "scripts" / "acquire_component_dataset.py")
acquire = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquire)


class FakeResponse(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_download_verifies_sha_and_resumes_partial_file(tmp_path, monkeypatch):
    payload = b"source-data-with-resume"
    target = tmp_path / "data.bin"
    target.with_name("data.bin.part").write_bytes(payload[:7])

    def fake_open(request, timeout):
        assert request.get_header("Range") == "bytes=7-"
        response = FakeResponse(payload[7:], status=206)
        response.headers["Content-Range"] = f"bytes 7-{len(payload)-1}/{len(payload)}"
        return response

    monkeypatch.setattr(acquire.urllib.request, "urlopen", fake_open)
    result = acquire.download_file("https://example.invalid/dataset", target,
        expected_size=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    assert result["status"] == "DOWNLOADED_AND_VERIFIED"


def test_download_keeps_partial_on_interrupted_size(tmp_path, monkeypatch):
    monkeypatch.setattr(acquire.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"short"))
    with pytest.raises(OSError, match="download incomplete"):
        acquire.download_file("https://example.invalid/dataset", tmp_path / "x.bin", expected_size=10)
    assert (tmp_path / "x.bin.part").read_bytes() == b"short"


def test_tar_preflight_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, "w") as archive:
        payload = b"bad"
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValueError, match="unsafe archive path"):
        acquire.inspect_tar(archive_path)


def test_tar_preflight_reports_expanded_size_and_safe_extract(tmp_path):
    archive_path = tmp_path / "safe.tar"
    with tarfile.open(archive_path, "w") as archive:
        payload = b"ok"
        info = tarfile.TarInfo("folder/file.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    assert acquire.inspect_tar(archive_path)["uncompressed_bytes"] == 2
    out = tmp_path / "out"
    acquire.safe_extract_tar(archive_path, out)
    assert (out / "folder/file.txt").read_bytes() == b"ok"
