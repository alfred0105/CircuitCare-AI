# Phase 21 Roadmap

Phase 21 builds toward a repair workflow that can start from multiview PCB photos and natural-language symptoms. The three independently evaluated research contributions remain electrical connectivity reconstruction, physics-informed fault reasoning, and active-measurement efficiency. No stage may upgrade evidence status without the specified data and validation.

| Phase | Focus and dependency | Start condition | Completion evidence |
|---|---|---|---|
| 21.0 | Technical audit, scope, evaluation rules and initial workbench fixes | Existing repository | 20-area inventory, evidence limits, experiment schema, targeted regression and documented gaps |
| 21.0.1 | Roadmap alignment, UI verification and final documentation | Phase 21.0 baseline | target product and 21.1–21.10 plan aligned; browser evidence and limitations recorded; docs and CI updated |
| 21.1 | PCB data and registration foundation | Board identity/revision; front/back photos; matching KiCad PCB, Position CSV and netlist; independent calibration and validation points | reproducible photo↔design transform with residuals; image-only and design-assisted inputs separated |
| 21.2 | Component, pad, via and copper annotations / dataset | Registered board samples and independent labels | frozen board-group split, annotation guide, inter-review agreement, candidate metrics and error taxonomy |
| 21.3 | Image-only PCB Vision AI baseline | Development labels and sealed board holdout from 21.2 | per-board detection/segmentation scores, uncertainty and false merge/split; holdout scored once by isolated evaluator |
| 21.4 | Design-assisted reconstruction and ablation | Matching design data, registered boards and frozen 21.3 baseline | separately scored design-assisted results and ablation; no design metadata in image-only track |
| 21.5 | Electrical connectivity graph reconstruction | 21.4 plus independently reviewed pin/pad/net correspondence, including shorts/opens and layer links | net/edge and false-short/open metrics by board; visual candidates remain separate from confirmed electrical nets |
| 21.6 | Physics-informed fault diagnosis | Independent circuit families, supported SPICE models, known faults and observation conditions; explicit KiCad input allowed when visual connectivity is unverified | matched Rules/Bayesian/SPICE/combined baselines, top-k, calibration and abstention by topology; physical claims only with physical outcomes |
| 21.7 | Active measurement policy evaluation | Paired case set, probe cost/accessibility, fixed stopping and seed protocol | Random, Rule, existing EIG and optional improved EIG on identical cases; efficiency and accuracy at fixed budgets |
| 21.8 | Natural-language symptoms and secondary-damage diagnosis integration | Validated fault catalog and diagnosis outputs from 21.6; supported electrical graph or explicit design input; measured policy results from 21.7 | structured symptom interpretation and module candidates; distinct root-cause / secondary-impact outputs; bounded compound-fault hypotheses; suggested measurements; no LLM-confirmed failures |
| 21.9 | Integrated repair workbench and user-centered UI/UX | Stable 21.8 workflow plus usable PCB viewer and provenance states | new diagnosis → summary/detail → PCB viewer → report flow; advanced tools on demand; uncertainty and user measurement update visible |
| 21.10 | Competition evaluation, demo and release | Reproducible records from 21.3–21.9; independent holdouts; no provenance bypass | independently report three research contributions; integrated demo; runtime/limitations/reproducibility package and final presentation |

PCB reconstruction (21.1–21.5) and diagnosis / measurement work (21.6–21.7) may proceed in parallel on separate data tracks. Phase 21.8 should use verified design connectivity first. If image-derived connectivity is uncertain, the application must request design input or user confirmation, or limit itself to clearly labeled candidates; it must not imply a confirmed net.

For 21.8, evaluate natural-language symptom structuring, fault-candidate accuracy, and secondary-impact candidates separately. For 21.9, evaluate task completion and usability separately from AI accuracy. Keep physical damage observation distinct from simulated rating stress.

## Immediate Phase 21.1 gate

Phase 21.1 has added a provenance bundle schema, explicit coordinate frames, a correspondence-only RANSAC fitter, independent error/status records, and guarded design-reference projection. Pinned PRISM inventory is available at 12/12 boards; the initial run records 24 image sides as `REGISTRATION_UNVERIFIED`, because image candidates are not independently adjudicated correspondences. No matching physical CircuitCare photo + KiCad PCB/Position CSV + electrical reference set or held-out calibration points are present. Quantitative reconstruction claims remain blocked until these inputs exist. Do not use PRISM pixel candidate fractions as accuracy targets.

The first substantive technical blocker is therefore data provenance and image-to-design registration, followed by independently adjudicated connectivity ground truth. In parallel, diagnosis work can continue on explicitly synthetic/design tracks, and measurement policy evaluation can be prepared on frozen simulated cases without making physical efficiency claims.
