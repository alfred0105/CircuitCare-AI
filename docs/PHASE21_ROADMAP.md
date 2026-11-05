# Phase 21 Roadmap

Phase 21 targets three measured contributions: electrical connectivity reconstruction, physics-informed fault reasoning, and active measurement efficiency. No stage may upgrade evidence status without the specified data and validation.

| Phase | Focus and dependency | Start condition | Completion evidence |
|---|---|---|---|
| 21.0 | Audit, scope, evaluation rules and verified UI fixes | Existing repository | inventory, limits, shared schema, regression + browser evidence, reviewed roadmap |
| 21.1 | PCB data and registration foundation; depends on 21.0 | Board identity/revision, front/back photos, matching KiCad PCB/Position CSV/netlist, independent calibration and validation points | reproducible photo↔design transform with residuals; image-only and design-assisted inputs explicitly separated |
| 21.2 | Component, pad, via and copper annotation set; depends on 21.1 | Registered board samples and independent labels | frozen board-group split, annotation guide, inter-review agreement, candidate metrics and error taxonomy |
| 21.3 | Image-only reconstruction baseline; depends on 21.2 | Training/development labels and sealed board holdout | per-board detection/segmentation scores, uncertainty and false merge/split; holdout scored once by isolated evaluator |
| 21.4 | Design-assisted reconstruction and ablation; depends on 21.1–21.3 | matching design data and frozen image-only baseline | separately scored design-assisted results and ablation; no silent design metadata in image-only track |
| 21.5 | Electrical connectivity reconstruction; depends on 21.4 and electrical truth | independently reviewed pin/pad/net correspondence including shorts/opens and via layer links | net/edge and false-short/open metrics by board; candidates stay separate from confirmed circuit nets |
| 21.6 | Physics-informed diagnosis improvement; depends on supported reconstruction or explicit KiCad inputs and frozen 21.0 protocol | independent circuit families, supported SPICE models, known injected faults and observation conditions | matched rules/Bayesian/SPICE/combined baselines, top-k/calibration/abstention by topology; physical claims only if real outcomes exist |
| 21.7 | Active measurement policy evaluation; depends on frozen diagnosis task and measurement model | paired case set, probe costs/accessibility, fixed stopping/seed protocol | Random, Rule, existing EIG and optional improved EIG comparison on identical cases; efficiency and accuracy at fixed budgets |
| 21.8 | Integrated competition demonstrator and release | 21.3–21.7 artifacts have reproducible records; no unresolved provenance bypass | end-to-end demo, clear image-only/design-assisted labels, reproducibility bundle, limitations and presentation-ready results |

## Immediate Phase 21.1 gate

The repository does not currently contain a matching physical CircuitCare photo + KiCad PCB/Position CSV + electrical netlist/reference set, calibrated scale, or independent validation points. PRISM has useful image inputs but not valid registered geometry/electrical ground truth. Phase 21.1 may start by acquiring and documenting the data package and calibration procedure; quantitative reconstruction implementation is blocked until those inputs exist. Do not use PRISM pixel candidate fractions as accuracy targets.

The first substantive technical blocker is therefore data provenance and image-to-design registration, followed by independently adjudicated connectivity ground truth. In parallel, diagnosis work can continue on explicitly synthetic/design tracks, and measurement policy evaluation can be prepared on frozen simulated cases without making physical efficiency claims.
