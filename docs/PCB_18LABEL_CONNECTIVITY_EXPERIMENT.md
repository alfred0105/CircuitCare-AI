# PCB 18-label connectivity experiment

Run date: 2026-11-09. This experiment uses the pin-only PCB CAD archive and the requested 18 component labels as model inputs. It excludes prior schematic/Phase 22 training graphs. The repository-grouped split contains 153 training, 19 validation, and 18 test boards.

## Label handling

The 18-label vocabulary is `IC`, `LED`, `battery`, `buzzer`, `capacitor`, `connector`, `diode`, `display`, `fuse`, `inductor`, `clock`, `potentiometer`, `relay`, `resistor`, `switch`, `transistor`, `transformer`, and `heatsink`. Existing `oscillator` labels are normalized to `clock`. An internal `unknown`/abstention bucket handles unsupported source labels; this is not an extra detector class. The current archive has no `transformer` or `heatsink` examples, and has legacy `jumper` and `ferrite_bead` examples mapped to `unknown`.

## Held-out test comparison

All runs use the same 100 mm / 32-nearest candidate graph, LightGBM training setup, and validation-selected mutual Top-K transitive clustering.

| Experiment | Inputs | PR-AUC | ROC-AUC | End-to-end Recall@5 | Net-pair precision | Net-pair recall | Net-pair F1 | Predicted pairs |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | Pad/component coordinates and pair geometry | 0.0845 | 0.5633 | 9.39% | 6.49% | 98.57% | 12.18% | 83,731 |
| B | A + 18-label one-hot and component-pair cues | 0.0763 | 0.5368 | 9.39% | 6.57% | 95.39% | 12.30% | 80,017 |
| C | B + component-relative pad position, local density, pin count, rotation/facing proxy | **0.0894** | **0.5979** | **10.33%** | **6.78%** | 96.63% | **12.67%** | 78,615 |

The best validation-selected Top-K was 12 for all three runs. Candidate recall was 100% on test (5,514/5,514 truth pairs), while the average candidate degree was about 208 pins per pin. So the current bottleneck is ranking and grouping, not candidate coverage.

The component labels alone did not improve ranking: B trailed A on PR-AUC and ROC-AUC, with almost no Recall@5 change. The added geometric structure in C improved held-out ranking: PR-AUC rose from 0.0845 to 0.0894 and Recall@5 from 9.39% to 10.33%. The gain is modest, and only 18 test boards are available.

## Example ranked candidates from C

For board `016a73554bd8106d`, the top-ranked pair `R2:2` (`resistor`) ↔ `D1:1` (`LED`) scored 0.961 and was same-net in the CAD target. The adjacent candidate `R2:1` ↔ `D1:2` scored 0.962 but was not same-net. High scores therefore remain candidate probabilities, not confirmed connections.

## Limits

- The target is same-net membership between different components, not direct physical copper adjacency.
- Transitive clustering has low precision and over-merges nets (19 false-merge clusters on test). Do not export its output as a verified netlist.
- Rotation is only a rough facing-direction proxy because exact pad normals are unavailable in the source schema.
- `transformer` and `heatsink` cannot be assessed until labeled PCB examples exist. The source distribution is heavily imbalanced; e.g. `potentiometer` has only three pin records.
- This evaluates PCB CAD placement and CAD net labels, not photos, trace segmentation, or photo-to-pad registration.

Artifacts: runner `scripts/benchmark_pcb_18label_connectivity.py`; full metrics and top-10 candidates per held-out board `data/benchmarks/pcb_pin_connectivity/pcb_18label_connectivity_results.json`; trained models `data/benchmarks/pcb_pin_connectivity/models/lightgbm_18label_a.txt`, `lightgbm_18label_b.txt`, and `lightgbm_18label_c.txt`.
