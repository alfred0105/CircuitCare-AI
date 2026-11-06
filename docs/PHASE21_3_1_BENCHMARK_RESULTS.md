# Phase 21.3.1 Benchmark Results

## Evaluation status

The available 13-image / 196-box public validation split is a **source-label comparison**, not reviewed validation or a sealed board-level test. Its board IDs are unresolved and its annotations have not been independently adjudicated. This Phase does not promote those labels or model outputs to ground truth.

| Track | Status | Images | Boxes | Board independence |
|---|---|---:|---:|---|
| Source-provided labels | `SOURCE_LABEL_COMPARISON` | 13 | 196 | `BLOCKED_BOARD_ID_UNRESOLVED` |
| Reviewed validation | `BLOCKED_REVIEWED_GROUND_TRUTH_UNAVAILABLE` | — | — | unavailable |
| Sealed board-level test | `BLOCKED_SEALED_TEST_UNAVAILABLE` | — | — | unavailable |

## Current comparison

The manifest-backed evaluation smoke run during implementation reproduced the Phase 21.3 single-image result:

| Metric | Result |
|---|---:|
| Precision at confidence 0.25 | 0.4979 |
| Recall at confidence 0.25 | 0.6122 |
| mAP@0.5 | 0.5848 |
| mAP@0.5:0.95 | 0.3336 |

This run used the Phase 21.3.1 working tree before its final commit, so it is diagnostic evidence only. The clean-commit rerun and its exact runtime/resource metadata will be recorded here before this Phase is finalized.

The evaluation uses model `pcb-yolov8s-2026-07-11`, SHA-256 `45a1dc54bb2eaff067edc631be30fee650deb1236e97a038610faa11aef28424`, at 960 input resolution, confidence threshold 0.25, NMS IoU 0.45, metric IoU 0.50, and AP prediction floor 0.001. The evaluator records model/data hashes, runtime versions, configuration, runtime, peak RSS, source manifest, source commit, code revision, and dirty-tree state.

## Interpretation and next data gate

These values compare predictions to upstream labels that may be incomplete or incorrect. They do not establish real-PCB detection accuracy, board-independent generalization, or a damage probability. Per-class support below 10 is flagged as insufficient for reporting. Small-object misses and source-label false positives remain candidates for human review.

To unblock independent validation, reviewers must identify physical board/revision and side for each image, adjudicate boxes and omissions, record reviewer/provenance, and reserve board groups for validation and sealed test before tuning against those splits. Until then, retain `BLOCKED_REVIEWED_GROUND_TRUTH_UNAVAILABLE`, `BLOCKED_BOARD_ID_UNRESOLVED`, and `BLOCKED_SEALED_TEST_UNAVAILABLE`.

See [dataset audit](PHASE21_3_1_DATASET_AUDIT.md), [evaluation validation](PHASE21_3_1_EVALUATION_VALIDATION.md), and [recognition reliability report](PHASE21_3_1_RECOGNITION_RELIABILITY.md) for source inventory and protocol details.
