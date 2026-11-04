#!/usr/bin/env python3
"""Run pytest-based diagnostic suites in isolated, timed child processes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "fast": ["-m", "pytest", "-q", "-m", "not integration and not stress"],
    "integration": ["-m", "pytest", "-q", "-m", "integration"],
    "stress": ["-m", "pytest", "-q", "-m", "stress"],
}


def _environment() -> dict:
    packages = {}
    for module, label in (("streamlit", "streamlit"), ("ngspice", "ngspice"), ("numpy", "numpy"),
                          ("cv2", "opencv"), ("onnxruntime", "onnxruntime"), ("rapidocr", "rapidocr")):
        if module == "ngspice":
            import shutil
            path = shutil.which("ngspice")
            version = None
            if path:
                try:
                    version = subprocess.run([path, "--version"], capture_output=True, text=True,
                                             timeout=5).stdout.splitlines()[1].strip("* ")
                except (OSError, subprocess.SubprocessError, IndexError):
                    version = "unknown"
            packages[label] = {"available": bool(path), "version": version}
            continue
        try:
            loaded = __import__(module)
            packages[label] = {"available": True, "version": getattr(loaded, "__version__", "unknown")}
        except Exception:
            packages[label] = {"available": False}
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        ram = None
    return {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "python": sys.version.split()[0],
            "os": platform.system(), "os_release": platform.release(), "architecture": platform.machine(),
            "pid": os.getpid(), "git_sha": _git_sha(), "available_ram_bytes": ram,
            "selected_model": None, "active_workflow_step": "diagnostic_suite_start", "dependencies": packages}


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        process.kill()
    process.wait(timeout=5)


def _process_tree_rss_bytes(root_pid: int) -> int | None:
    """Sample RSS for a child and descendants using ps, available on macOS/Linux."""
    try:
        result = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], capture_output=True,
                                text=True, timeout=3, check=True)
        rows = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3:
                rows[int(parts[0])] = (int(parts[1]), int(parts[2]) * 1024)
        selected = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, (parent, _rss) in rows.items():
                if parent in selected and pid not in selected:
                    selected.add(pid)
                    changed = True
        return sum(rows[pid][1] for pid in selected if pid in rows)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _run(name: str, command: list[str], output_dir: Path, timeout: int) -> dict:
    stdout_path = output_dir / f"{name}.stdout.log"
    stderr_path = output_dir / f"{name}.stderr.log"
    started = time.monotonic()
    peak_rss = None
    baseline_rss = None
    final_rss = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        child_environment = os.environ.copy()
        child_environment["CIRCUITCARE_DIAGNOSTICS_DIR"] = str(output_dir.resolve())
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, env=child_environment,
                                   start_new_session=(os.name == "posix"))
        try:
            baseline_rss = _process_tree_rss_bytes(process.pid)
            while process.poll() is None:
                current_rss = _process_tree_rss_bytes(process.pid)
                if current_rss is not None:
                    peak_rss = max(peak_rss or 0, current_rss)
                    final_rss = current_rss
                if time.monotonic() - started > timeout:
                    _terminate_tree(process)
                    break
                time.sleep(0.1)
            exit_code = process.wait()
        finally:
            _terminate_tree(process)
    elapsed = time.monotonic() - started
    final_rss = _process_tree_rss_bytes(process.pid) or final_rss
    sig = -exit_code if exit_code < 0 else None
    status = "TIMEOUT" if elapsed > timeout else ("PASSED" if exit_code == 0 else "FAILED")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")[-20000:]
    signal_name = signal.Signals(sig).name if sig and sig in signal.Signals._value2member_map_ else sig
    termination = ("TIMEOUT" if status == "TIMEOUT" else "NORMAL_EXIT" if exit_code == 0
                   else "CHILD_PROCESS_SIGSEGV" if signal_name == "SIGSEGV"
                   else "PROCESS_KILLED" if signal_name == "SIGKILL"
                   else "PYTHON_EXCEPTION" if "Traceback (most recent call last)" in stderr_text
                   else "CHILD_PROCESS_FAILURE" if exit_code != 0 else "UNKNOWN_TERMINATION")
    return {"suite": name, "stage": name, "status": status,
            "termination_class": termination, "process_id": process.pid, "command": command,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "wall_time_seconds": round(elapsed, 3), "baseline_rss_mb": round(baseline_rss / 1048576, 2) if baseline_rss else None,
            "peak_rss_mb": round(peak_rss / 1048576, 2) if peak_rss else None,
            "final_rss_mb": round(final_rss / 1048576, 2) if final_rss else None,
            "rss_growth_mb": round((final_rss - baseline_rss) / 1048576, 2) if final_rss and baseline_rss else None,
            "rss_measurement_source": "ps_process_tree_sampled_peak" if peak_rss else "NOT_AVAILABLE",
            "exit_code": exit_code, "signal": signal_name,
            "exception_type": None, "fatal_traceback_available": "Fatal Python error" in stderr_text,
            "child_process_status": termination,
            "stdout_log": stdout_path.name, "stderr_log": stderr_path.name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["fast", "integration", "stress", "all"], default="stress")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/private/diagnostics")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "runtime_environment.json").write_text(json.dumps(_environment(), indent=2) + "\n", encoding="utf-8")
    selected = ["fast", "integration", "stress"] if args.suite == "all" else [args.suite]
    reports = []
    for name in selected:
        command = [sys.executable, *SUITES[name]]
        report = _run(name, command, args.output_dir, args.timeout)
        (args.output_dir / f"{name}_stress.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        reports.append(report)
    summary = {"status": "PASSED" if all(row["status"] == "PASSED" for row in reports) else "FAILED",
               "suites": reports, "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
    (args.output_dir / "crash_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
