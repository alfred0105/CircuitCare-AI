from __future__ import annotations

import os
import sys

import pytest

from scripts.run_crash_diagnostics import _run


@pytest.mark.skipif(os.name != "posix", reason="Signal exit codes are POSIX-specific")
@pytest.mark.crash_injection
def test_diagnostic_runner_records_child_sigsegv_without_killing_parent(tmp_path):
    report = _run("sigsegv_fixture", [sys.executable, "-c", "import os,signal; os.kill(os.getpid(), signal.SIGSEGV)"],
                  tmp_path, timeout=10)
    assert report["status"] == "FAILED"
    assert report["signal"] == "SIGSEGV"
    assert report["exit_code"] < 0
    assert report["parent_pid"] == os.getpid()
    assert report["child_pid"] != report["parent_pid"]
    assert report["termination_class"] == "EXPECTED_CHILD_SIGNAL_TEST"


def test_diagnostic_runner_terminates_timed_out_child(tmp_path):
    report = _run("timeout_fixture", [sys.executable, "-c", "import time; time.sleep(5)"],
                  tmp_path, timeout=1)
    assert report["status"] == "TIMEOUT"
    assert report["exit_code"] != 0
