# Phase 18.2 — Architecture Refactor

## Goal

Improve maintainability without changing CircuitCare behavior, serialization, state names, or the existing Python/Streamlit/ngspice/Ollama/ONNX stack.

## Before and after

Before refactoring, `ui.py` was 1,075 lines and contained Streamlit rendering, analysis context fingerprints, simulation subprocess execution and result validation, measurement identity, cached CSV snapshots, report downloads, and diagnosis helpers. `render_vision_tab()` was 461 lines including its final confirmed risk-overlay workflow. `datasheet_ui.py` was 304 lines and mixed UI with document/risk-row data preparation.

The refactor moved the dashboard context/reuse helpers to `dashboard/context.py`, bounded download snapshots to `dashboard/downloads.py`, and spawn-safe simulation execution/result validation to `services/simulation_service.py`. Datasheet data preparation now lives in `datasheet/ui_helpers.py`. The confirmed PCB registration, overlay, evidence display, and save/download stage now has a separate `vision/overlay_view.py` rendering boundary.

`ui.py` is now 942 lines. It remains the current application coordinator and retains compatibility exports used by existing tests and callers. The largest functions are still `main()` (451 lines) and `_render_analysis_overview()` (264 lines); further view/state orchestration extraction remains follow-up work. `render_vision_tab()` is 330 lines, with the confirmed overlay stage factored into a separate 157-line module. `render_datasheet_tab()` remains 295 lines; its policy-sensitive flow stays cohesive while pure helper logic is separated.

## Preserved behavior and contracts

- Existing Streamlit entry command and analysis views remain unchanged.
- Session State keys, workspace/context invalidation, report formats, evidence hashes, and download limits are unchanged.
- Existing `circuitcare.ui` helper imports remain available, including simulation validation and CSV download helpers.
- Existing Vision same-board and per-reference confirmation gates remain in place; risk data stays unlinked until user confirmation.
- Datasheet ratings still require evidence and explicit approval. Reassessment reuses current SPICE stress and does not rerun ngspice.
- `execute_simulation()` retains absolute command paths and `close_fds=False` at the subprocess call site to preserve the macOS posix_spawn behavior.
- No algorithms, dependencies, persisted data, or report schemas were added or changed.

## Verification summary

- Baseline at `b93f45b0ecee26733ed6332232df719585299728`: 179 base tests, 14 integration, 11 stress, 204 non-crash total, and 3 crash-injection tests passed.
- Refactored code: the same test groups pass at the same counts. Existing pandas deprecation and duplicate ZIP test warnings remain.
- Browser: the application loaded and rendered its existing dashboard. A live divider fault run with an edited parameter reached `SUCCESS · Live Simulation`; the divider ngspice run, JSON report download, RC circuit switch, and prior-state reset all completed successfully; no browser page errors were observed.
- Static quality: focused import-order cleanup was applied; no broad cleanup was applied. Full-repository Ruff and mypy counts are included in the regression record.

## Follow-up debt

`main()` and `_render_analysis_overview()` remain large and should be split by workflow responsibility in a later, separately verified pass. Vision and datasheet selection/approval forms also remain cohesive long functions. This refactor prioritizes stable extraction boundaries and compatibility over moving a large function unchanged.

The future schematic viewer belongs under `dashboard/views/` (a new isolated view module) and should consume a presentation-ready analysis context; it should not own analysis, subprocess, or persisted evidence logic.
