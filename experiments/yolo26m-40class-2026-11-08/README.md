# YOLO26m 40-class quick experiment (2026-11-08)

This directory contains the experiment results and the scripts used to create the pilot subset, run the YOLO26m comparisons, evaluate each test image, and generate classwise reports. Dataset images/labels and model weights are intentionally not included.

## Run setup

- Model: Ultralytics YOLO26m, initialized from `yolo26m.pt`
- Epochs: 10 for every training condition
- Seed: 42
- Train / validation / test pilot: 921 / 116 / 116 images (about 5% per split; class-aware deterministic selection)
- Device in the recorded run: NVIDIA GeForce RTX 4060 Ti, CUDA, AMP
- Conditions: 640, 960, 1280, class loss weighting, PCB augmentation, multi-scale, rare-class oversampling; plus 640 test-time augmentation and tiled inference
- The 116-image test sample is small. Per-class metrics with few test images are highly uncertain and should guide review, not be treated as final production accuracy.

## Reproduction layout

The scripts expect the workspace data layout below. Set `CIRCUITCARE_EXPERIMENT_ROOT` to the workspace root (the default is the repository root):

```text
<workspace>/
  yolo26m.pt
  work/yolo26-benchmark/dataset-40class-quality/{train,valid,test}/{images,labels}/
  work/yolo26-benchmark/dataset-40class-quality/data.yaml
```

Then run `code/make_pilot_subset.py`, followed by `code/run_yolo26m_experiments.py`. The evaluation/report scripts consume the resulting pilot data and files under `outputs/yolo26m-40class-experiments/`. Dependencies include Python, PyTorch with CUDA, Ultralytics, PyYAML, NumPy, and Pillow. Paths and runtime settings are centralized near the top of each script.

## Headline result

Rare-class oversampling had the highest observed test mAP50–95 among these short pilot runs (0.2528), versus 0.1289 for the 640 baseline. This is a single 10-epoch comparison on a small, fixed test subset; it is a promising hypothesis, not a validated generalization claim.

The classwise improvement plan is in `results/label-improvement-plan.md`; complete numerical outputs are in the CSV files. Image-level exact match uses confidence >= 0.25, IoU >= 0.50, max detections 300, and requires every GT box to match with no extra detection. This deliberately strict metric is not the standard object-detection accuracy metric.
