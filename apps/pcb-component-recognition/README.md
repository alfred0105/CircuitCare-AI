# CircuitCare AI PCB Component Recognition

This local web module provides PCB component location detection, component type classification, and review-only pin/pad candidates. It is packaged under CircuitCare AI as the selected browser UI (`apps/pcb-component-recognition/index.html`). It does not infer wire paths or electrical connections.

## Run locally

Python 3.11+ is recommended. Install PyTorch for the user's CUDA version first, then install the remaining packages:

```powershell
python -m pip install -r requirements.txt
$env:CIRCUITCARE_PCB_WEIGHTS = 'C:\path\to\pcb-model-weights'
python app_server.py --port 8768
```

Open `http://127.0.0.1:8768`. The weight root can also be the module's `weights` directory. Model files and sample PCB photos are intentionally excluded from Git; image upload remains available. Place optional sample photos under `data/samples/`.

## Bundled model checkpoints

The repository includes the checkpoints needed by the default locator/classifier pipeline and the bundled optional comparison models. They are stored under `weights/` so a fresh checkout can start without copying files from a separate local directory:

- `any_best.pt` and `fine_best.pt` — Parsa YOLO26s locator and fine classifier.
- `external/pcb-ai-doctor/best_v8n.pt` and `best_v12n.pt` — AI Doctor comparison/location models.
- `external/pcb-yolov8s-detection/best.pt` — Arshia YOLOv8s component classifier.
- `external/PCBInspect-AI/YoloV12-Medium-160-FineTuned.pt` — PCBInspect comparison model.
- `external/nuts_best.pt` and `nuts_best.onnx` — Nuts Vision comparison checkpoint and export.

The optional PAINE pin-segmentation comparison checkpoint is not bundled because its Zenodo record does not show a redistribution license. Download it from the upstream record and place it at `weights/external/paine2026/unet_trained.pth` only if its author/license permits redistribution.

Third-party model attribution and license links are listed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). QWEN/LLM weights are not part of this repository. Setting `CIRCUITCARE_PCB_WEIGHTS` overrides the bundled weights directory.

## What the output means

- Component boxes combine the YOLO26s locator and AI Doctor v12n proposals; Arshia classifies matching boxes. Pin/pad detections from the classifier are excluded from component types.
- After detection, use **박스 검수** to draw an added box, select and move a box on the image, disable or delete incorrect boxes, edit its class or pixel coordinates, and ask the type model to classify the selected crop. Apply the model suggestion only when it looks right; export the reviewed boxes to CSV when finished. Review edits stay in the browser session until exported.
- Pin and pad markers are candidates for visual review. Yellow is a low-confidence geometric prior; green is an image-derived pad candidate; magenta indicates a supported or observed prior. They are not verified electrical terminals.
- The page includes single-image and YOLO ZIP evaluation tools. Only annotated regions are scored; unlabeled image areas are not treated as negatives.

The model's benchmark results are tied to the displayed datasets and annotation sources. They are not a guarantee of performance on a new board.
