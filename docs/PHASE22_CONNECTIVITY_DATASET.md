# Phase 22 — Schematic Connectivity Dataset

## Objective

Build paired examples for estimating electrical connectivity from a schematic
that still shows components and their pins but has no drawn electrical
connections. Keep the original design and its netlist as the answer. Never
rewrite source data in place.

The fixed component taxonomy is `IC`, `LED`, `battery`, `buzzer`,
`capacitor`, `connector`, `diode`, `display`, `emi_filter`, `ferrite_bead`,
`fuse`, `inductor`, `jumper`, `oscillator`, `potentiometer`, `relay`,
`resistor`, `switch`, and `transistor`.

## Source fit

| Source | Role | Constraints |
|---|---|---|
| [bshada/open-schematics](https://huggingface.co/datasets/bshada/open-schematics) | Primary input. Contains KiCad schematic source, rendered schematic image, PCB artifacts, component/library metadata and a `name` field. | 87.9k rows; Hugging Face reports 317 GB total and CC BY 4.0. A bounded acquisition produced 5,046 unique KiCad schematics (about 693 MiB). Preserve `name` as a project group so sibling schematics stay in the same split. |
| [AbijahKaj/kicad-netlist-sft-dataset](https://huggingface.co/datasets/AbijahKaj/kicad-netlist-sft-dataset) | Structured target-netlist supplement and cross-check. `netlist_json` includes components and pin-to-net membership. | 100,179 rows, Apache-2.0 declared. One exact project match was used for the netlist-format pilot. Many records derive from open-schematics, so deduplicate by source/design before combining. |
| [digailab/PCB-Bench](https://github.com/digailab/PCB-Bench) | Optional external evaluation/context source for PCB routing reasoning and real PCB project artifacts. | 174 projects are PCB design comprehension cases; its primary tasks do not provide a clean schematic-image/wire-free input and component-to-net answer pair. Do not count QA/CQ records as connectivity training pairs. Inspect each artifact and its license/provenance before conversion. |

## Pair contract

Each accepted source schematic produces:

- `inputs/<id>.kicad_sch`: a byte-preserving copy with root-level `wire`,
  `bus`, `bus_entry`, `junction`, `no_connect`, `label`, `global_label`, and
  `hierarchical_label` records removed. Component symbols and their pin
  definitions remain.
- `targets/<id>.json`: when a netlist is supplied/exported, a graph of the
  19-class components and original nets with component reference and pin.
- `targets/<id>.kicad_sch`: in `original-schematic` mode, an untouched copy of
  the complete wired source schematic as the ground-truth target.
- `originals/<id>.netlist.json`: full exported original connectivity for audit
  when using netlist mode.
- `records.jsonl`: source hashes, labels, source/license attribution, group,
  split and output paths.

Labels and global/hierarchical labels are removed because they can disclose
connectivity even when wires are absent. Junction dots are removed for the same
reason. `no_connect` markers are removed so the input does not directly expose
negative pin labels. In `netlist-json` mode, the netlist is exported from the
untouched source schematic via `kicad-cli`; the wire-removed input is never used
to create its own target. In `original-schematic` mode, the target is a copy of
the original wired schematic.

Components not classifiable into the 19 labels remain visible in the input. In
`netlist-json` mode they are omitted as target nodes, and a target net is
retained only when it connects at least two labelled components. The
`original-schematic` target keeps every original component and connection.
Unknown library mappings are left unlabelled rather than guessed into a class.
The first-pass mapping uses symbol library ID/value/description and reference
prefix; review the class distribution and ambiguous mappings before training.

## Preparation

For direct netlist export from each source schematic, install KiCad 8 or newer
and make `kicad-cli` available on PATH. A matched target supplied through
`--netlist-map` does not require KiCad CLI. Fetch a bounded subset of schematic
source text with:

```bash
python scripts/fetch_open_schematics.py --limit 100 --page-size 25
```

The fetcher saves no images or PCB files and records each source project and
hash in `source_manifest.jsonl`. Use `--limit 0` only when intentionally
acquiring the entire source (Hugging Face reports 317 GB for the dataset).
Then prepare the clean-input/original-target pairs:

```bash
python scripts/prepare_connectivity_pairs.py data/external/open-schematics-sample \
  --source-name bshada/open-schematics \
  --source-url https://huggingface.co/datasets/bshada/open-schematics \
  --license CC-BY-4.0 \
  --output data/external/connectivity_pairs
```

Use `--limit 100` for an initial pass. The output folder is ignored by Git.
The script skips designs that do not have at least two taxonomy-labelled
components. In `netlist-json` mode it also skips designs without a net joining
at least two labelled components.
Flat input folders fall back to filename-based split groups; this is marked in
the manifest and is not adequate evidence of leakage-free board/project splits.
For a paired source-to-source dataset without KiCad CLI/netlist matches, use
`--target-format original-schematic`; this preserves the wired original as the
target while creating the wire-free input. The pair is lossless design
supervision, while JSON netlist targets remain the preferred training format
for a graph-prediction model.

When an independently sourced target netlist is available, provide a JSON map
whose keys exactly match paths relative to the source directory and whose
values are either `netlist_json` strings or parsed netlist objects. This allows
the source and target datasets to be recorded separately:

```bash
python scripts/prepare_connectivity_pairs.py data/external/open-schematics \
  --netlist-map data/external/kicad-netlist-sft/netlist-map.json \
  --source-name bshada/open-schematics --license CC-BY-4.0 \
  --target-source-name AbijahKaj/kicad-netlist-sft-dataset \
  --target-license Apache-2.0 \
  --output data/external/connectivity_pairs
```

### Pilot and batch completed

One matching sample was retrieved from each Hugging Face source using the
datasets-server rows API. `TiebeDeclercq/Uart-programmer` matched exactly by
GitHub project URL. The resulting local-only pair has 39 taxonomy-labelled
components, 28 target nets and 72 component-pin nodes. Nine of the 19 classes
appear in this single sample. A scan of the generated input confirmed that
root-level wires, net labels and junctions were absent. The source file,
target map and generated pair are in ignored `data/external/` paths and are not
committed. This is a conversion smoke check, not a dataset-quality or model
evaluation result.

The bounded batch contains **5,046 unique source schematics** (726,551,030
bytes; 692.9 MiB) and produced **4,957 wire-free/original pairs**. The 89
unpaired designs each had fewer than two components mapped to the 19-class
taxonomy. Across accepted samples, class counts are in the generated
`summary.json`; the largest are resistor (36,439), capacitor (31,679),
connector (22,144), switch (16,342), and diode (13,352). These are component
instance counts, not sample counts. The paired artifacts occupy about 1.26
GiB. Source and pair artifacts remain in ignored local data directories.

Batch audit found all 19 classes represented, verified 4,957 inputs and 4,957
original targets, and found zero remaining root-level wire, bus, junction,
no-connect or net-label records in the inputs. The 4,955 project groups do not
cross the generated train/validation/test split. The split is project-grouped,
but its labels are automatically mapped and have not had manual review.

The current input artifact is a wire-free KiCad schematic source file. It keeps
component symbols and their pin definitions. The batch target is an untouched
copy of the original wired schematic. KiCad CLI 10.0.7 is now installed in the
user environment; the link-prediction pipeline exports each original target to
KiCad XML at extraction time, leaving the stored source pairs unchanged.
Rendering and validating a wire-free image view, manually reviewing the
automatic component classes, and scaling beyond this bounded batch remain open
work.

## Pin-level link prediction and baseline comparison

`scripts/benchmark_connectivity_link_prediction.py` exports the original
schematic netlist with `kicad-cli`, parses symbol-library pin coordinates, and
applies the schematic instance rotation and mirror transform. Each pin is a
NetworkX node. A cKDTree finds nearby pins from different components; the
symmetrized k-nearest-neighbor links within the configured radius become
candidate edges. Edge labels are positive when both `(reference, pin)` endpoints
belong to the same original net. Multi-pin nets therefore create pairwise
positive links; this is a link-prediction proxy for shared-net membership, not
a claim that every positive pin pair has a direct drawn wire between them.

Candidate recall is measured before model evaluation. A positive pin pair that
was not proposed by cKDTree cannot be predicted by either model, so report
candidate recall alongside test metrics. A sweep over all 4,948 extracted
graphs gave mean per-schematic candidate recall of about 0.50 at `k=32`,
`100 mm`; 0.71 at `k=64`, `200 mm`; and 0.80 at `k=96`, `250 mm`. The larger
setting produced about 6,200 candidate edges per schematic on average, so the
default uses `k=96`, radius `250 mm` as a recall/density tradeoff. Distances use
KiCad schematic millimeters. This sweep is descriptive; final settings should
be chosen on validation projects, not test projects.

Both models use the existing project-grouped `train`/`validation`/`test`
manifest splits and the exact same candidate edges. LightGBM gets endpoint
class/pin features and relative geometry. The compact PyTorch model aggregates
messages over the candidate graph and scores candidate links; it is an
independent GNN-ACLP-inspired baseline, not a reproduction of the paper's SEAL
model or reported results. Evaluation emphasizes PR-AUC because positive links
are sparse; threshold metrics are also reported. LightGBM training caps sampled
negative edges to control memory, while test metrics include all test candidates.

The GNN-ACLP paper describes port-level prediction with a SEAL framework and
its official implementation is GPL-3.0. This repository uses a separate
implementation and does not copy that code. See the [paper](https://doi.org/10.1016/j.engappai.2025.113035)
and [official repository](https://github.com/guanyuanpeterpan/GNN-ACLP) for
the reference method and license.

Run the full graph extraction and comparison:

```bash
pip install -e ".[connectivity]"
python scripts/benchmark_connectivity_link_prediction.py extract --workers 6
python scripts/benchmark_connectivity_link_prediction.py train
```

KiCad CLI can be passed explicitly with `--kicad-cli PATH`; the script also
searches common Windows install paths and `KICAD_CLI`. Intermediate graph JSONL
and extraction failures are local-only under ignored
`data/benchmarks/phase22_connectivity/`. The compact comparison report and
extraction summary are kept as reviewable benchmark outputs. Training also
writes the GNN state dictionary and LightGBM text model under ignored
`models/phase22_connectivity/`.

The repository does not download the full 317 GB source dataset. The completed
bounded acquisition contains 5,046 unique schematic files in ignored
`data/external/open-schematics-5000/`, with a SHA-256 inventory. The generated
wire-free/original pairs are in ignored
`data/external/connectivity_pairs-5000-complete/`. Retain source URLs and hashes
in every derived sample. Avoid publishing source artifacts or generated copies
unless the applicable source license allows redistribution.

## Evaluation safeguards

- Split by source project/repository before sample generation, not randomly by
  schematic file. Sibling boards and derived variants must stay together.
- Keep the SFT dataset's overlapping open-schematics-derived records out of
  validation/test unless deduplication has been performed at project/design
  level.
- Record the source revision, exact license, SHA-256 and conversion tool
  version. A license on the dataset wrapper does not automatically settle the
  licensing of every upstream design artifact.
- Audit class counts, unmatched classes, empty-net counts, disconnected pins,
  and duplicate design hashes before training. The initial label mapper is a
  proposal and requires manual review on a stratified sample.
- This dataset evaluates schematic design connectivity. It does not establish
  connectivity reconstruction accuracy from physical PCB photographs.
