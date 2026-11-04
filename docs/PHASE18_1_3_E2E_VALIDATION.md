# Phase 18.1.3 End-to-End Validation

Environment: macOS 27.0.1, Apple Silicon arm64, Python 3.12.14, local Streamlit on port 8502, Chromium via Playwright. Browser artifacts and raw private logs are under the ignored `data/private/diagnostics/phase18_1_3/` directory.

## Browser results

| Flow | Result | Evidence |
|---|---|---|
| Streamlit startup | PASS | Browser title `CircuitCare AI`; health endpoint returned 200. |
| Known fault, browser-triggered ngspice | PASS after fix | Fresh Streamlit process launched the divider fault; comparison, risk, and simulation-context artifacts were created. The UI did not reuse a saved result. |
| Report JSON download | PASS | Browser downloaded non-empty JSON (24,131 bytes after the successful live run). |
| Direct Vision view switch | PASS | Browser selected `PCB 사진 인식`; no page errors. |
| Two browser sessions | PASS, limited | Two isolated Chromium contexts retained different circuit selections simultaneously. This did not run SPICE/PDF/ONNX tasks concurrently. |
| 100-view AppTest soak | PASS | 100 switches over 4 case choices and 11 views; warm-up RSS 164.56 MiB, samples: switch 10 201.17 MiB, switch 50 230.53 MiB, switch 100 218.98 MiB. |

The first browser runs exposed a real `-11` child crash. A macOS DiagnosticReport showed the child-side multithreaded `fork` path. The UI CLI, ngspice, and PDF worker launch options were changed so CPython uses `posix_spawn`; Git SHA lookup no longer spawns `git` during report rendering. On a freshly restarted server, a real browser-triggered fault simulation completed, created comparison and risk artifacts, downloaded its JSON report, and switched directly to Vision without page errors. `BROWSER_E2E_VERIFIED` is **PASS for this known-fault flow**.

## Other actual app/runtime checks

- Local Ollama `gemma4:12b`, digest `c7597fc90b86aff6965317f37dd5465402284e26382d9b4bf2dfe3ef1491f4b6`: plain chat 200; JSON format requests 501 with `structured output is unavailable`; app `OllamaClient.chat_json()` succeeded using the bounded fallback with `json_mode=false`, `fallback_used=true`, `fallback_reason=structured_output_unavailable`.
- Actual fault-hypothesis proposal returned one explicitly `proposed` candidate; it was not treated as validated or executable. Synthetic datasheet text produced a 0.125 W proposal with `human_approved=false`.
- ngspice direct repeat: 20/20 runs succeeded. Native integration tests: 5 passed. Browser-triggered CLI remained the failing boundary in the initial runs.
- ONNX isolated native integration and OCR isolated native integration passed. ONNX board detection repeat: 30 distinct synthetic images completed; all results were `candidate_unverified`. This is runtime exercise, not accuracy validation. No full browser OCR/reference-confirmation/overlay flow was completed.
- PDF worker repeat: 20 same-content loads used one worker PID, 19 cache hits / 1 miss; changing the content hash triggered a new parse. Two concurrent same/different PDF requests preserved result and filename contexts.
- Mixed workload: local Ollama JSON request, ngspice divider run (508 samples), isolated PDF worker (31.73 MiB sampled peak), and Streamlit health request ran concurrently and all passed in 4.1 seconds. The parent Python process sampled 47.12 MiB peak RSS; this does not include the Ollama service or Streamlit server process.

## Not completed

- Browser end-to-end for unknown-fault AI, complete Vision/OCR, and datasheet approval/risk reassessment.
- Simultaneous user sessions running Circuit A SPICE, Circuit B PDF, and Vision/ONNX at once. Only separate circuit selection state across two concurrent browser contexts was checked.
- Mixed Ollama + ngspice + PDF worker + Streamlit health workload passed in parallel (4.1 seconds); ONNX was not included in that mixed run.
- Ollama soak beyond the bounded direct requests already recorded.

Raw output and diagnostic records are local-only and excluded from Git.

GitHub Actions run #41794469574 completed successfully on commit `5853c4e01e78b2df21081c0edd8e950ded9f8b2c`; all six configured jobs passed, including Python 3.11/3.12, ngspice, OCR, stress, and isolated crash injection.
