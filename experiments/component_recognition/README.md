# Component recognition training lab

This workflow is intentionally independent of the CircuitCare UI and runtime. It uses a separate Python 3.12 ARM64 environment; application dependencies and the checked-in detector remain unchanged.

## Setup

```bash
python3.12 -m venv .venv-component-train
source .venv-component-train/bin/activate
python -m pip install --upgrade pip
python -m pip install -r experiments/component_recognition/requirements-macos-arm64.txt
python scripts/component_training.py doctor
```

The doctor command checks the actual host, PyTorch MPS tensor operations, backward/optimizer, system memory, and package versions. FP32 is the default. CUDA is never selected. `device=auto` selects MPS only after its probe passes, otherwise CPU.

Ultralytics is installed only in this isolated training environment; upstream publishes the framework under AGPL-3.0. Review its current terms and any obligations for distributing training code or derived artifacts. It is not added to the CircuitCare application runtime.

## Data

Store raw datasets under ignored `data/component_training/raw/`; generated data, splits, runs, and checkpoints remain local under `data/component_training/`. The reviewed manifest is `data/component_training/manifests/pinned-source-domain-review.json`, with the eight image types `POPULATED_PCB`, `PARTIALLY_POPULATED_PCB`, `PCB_COMPONENT_CLOSEUP`, `BARE_PCB`, `BREADBOARD`, `ISOLATED_COMPONENT`, `LOOSE_COMPONENT_COLLECTION`, and `UNKNOWN`. Only the first three enter main training. Bare PCBs and breadboards require explicit human confirmation that target PCB components are absent before separate hard-negative/evaluation use; an empty label file is not sufficient. One-component PCB images remain included, and closeups stay grouped with their parent board.

Current source notes and access status are in `docs/PHASE21_3_2_DATASET_EXPANSION.md`. The filtered dataset has 101 images (77 train / 24 development validation) and 33 manually reviewed visual groups. The source lacks verified physical board IDs, so this group-level split is not an independent sealed test.

Dataset YAML follows Ultralytics detection format and includes train/val paths and names. Use complete board annotations. Images with partial labels must remain excluded from ordinary detector training unless their unlabeled regions have been adjudicated.

## Training

```bash
python scripts/component_training.py smoke --data data/component_training/processed/smoke/data.yaml
python scripts/prepare_component_dataset.py \
  --manifest data/component_training/manifests/pinned-source-domain-review.json \
  --output-dir data/component_training/processed/domain-reviewed-v5
python scripts/component_training.py train \
  --data data/component_training/processed/domain-reviewed-v5/data.yaml \
  --profile baseline --epochs 40
```

Runs get unique IDs and are never overwritten. Batch fallback happens only after an out-of-memory error and is recorded. The training wrapper writes host/process memory snapshots and a reproducibility metadata JSON alongside the Ultralytics run. Review thermals and swap in Activity Monitor during long runs; psutil cannot read Apple Silicon package temperature.

## Evaluate / export / inference

Use the existing evaluation CLI for CircuitCare-compatible metrics and provenance, and compare each checkpoint on one locked board-level test split. Export separately with `python scripts/component_training.py export --weights PATH --imgsz 640`. Run single-image inference with:

```bash
python scripts/run_component_inference.py --model PATH --image PCB.jpg --output-dir data/component_training/runs/inference
```

The original ONNX model is never an output target by default. Validate PyTorch versus ONNX outputs on the same test images before proposing integration.
