# Phase 21.4.1 Benchmark Results

## Synthetic fixture smoke run

Command:

```bash
python scripts/benchmark_pin_estimation.py --fixture synthetic --output reports/pin_estimation.json
```

Observed run on the local Python 3.12 environment:

| Metric | Result |
|---|---:|
| Evaluation status | `SYNTHETIC_FIXTURE_ONLY` |
| Components | 3 (horizontal, vertical, rotated) |
| Terminal localization tolerance | 8 px |
| TP / FP / FN | 6 / 0 / 0 |
| Precision / Recall | 1.000 / 1.000 |
| Mean / P95 localization error | 0.70 / 1.00 px |
| Runtime | approximately 0.4 ms per component in this smoke run |
| Package classification accuracy | `NOT_EVALUATED` |
| Pin numbering/function accuracy | `NOT_EVALUATED` |
| Real PCB accuracy | `NOT_EVALUATED` |

The fixtures use simple generated geometry and pale rectangular pad appearances. These results only check the synthetic code path; they are not evidence of real-board precision, recall, package accuracy, or pin-number accuracy. Runtime is a local smoke measurement, not a performance benchmark.

## Real-image evaluation

No Phase 21.4.1 pin-terminal Ground Truth was available. Therefore the following remain `NOT_EVALUATED`: terminal detection precision/recall, terminal-count accuracy, localization error on real images, package classification accuracy, pin-number assignment accuracy, and pin-function accuracy. A saved Component Map can be processed by the CLI, but without reviewed pin labels the output is a hypothesis export, not a scored benchmark.

Before real-image claims, create board-grouped reviewed annotations with component Reference/identity, side, visible terminal locations, package candidates, pin-1 evidence, and explicit visibility/occlusion status. Keep source photos, derived synthetic fixtures, and reviewed ground truth in separate evaluation tracks.
