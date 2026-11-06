# Phase 21.2 — Multi-Image PCB Reconstruction and Component Mapping

## Scope and evidence

This phase builds the local backend path from same-board photos to a partial per-side image and component map. It does not infer KiCad alignment, net connectivity, or confirmed damage. Phase 21.1.2 design-coordinate transforms remain a separate contract. Every inferred image registration/detection is a candidate; user review and independent references are still required for confirmed geometry or component identity.

The phase changes the earlier Phase 21.2 order, which began with annotations and grouped dataset splits. The first deliverable is now multi-photo intake, same-side image registration, conservative mosaics, observation fusion, and an overlay adapter. Independent board-group annotations and sealed evaluation remain necessary before detection accuracy or electrical reconstruction can be claimed.

## Implemented flow

`MultiImageComponentMapService.ingest(board_id, inputs)` accepts bounded `PhotoInput` values. JPG/JPEG, PNG and WebP are decoded by the existing `load_board_image` path, which applies EXIF orientation and preserves original input bytes in the in-memory session. Each upload has an ID, SHA-256 digest, declared TOP/BOTTOM side and capture role. Exact duplicate bytes are recorded and not reprocessed. A duplicate remains a distinct photo record.

`build_map(session, detector=..., model_path=...)` treats each side independently, chooses an explicit REFERENCE first and otherwise an OVERVIEW/large image, then reuses the project's ORB/RANSAC same-side registration. It checks finite/invertible transforms, conditioning, projected extent, match/inlier support, residuals, overlap and output canvas bounds. Only `REGISTERED_CANDIDATE` images enter the mosaic or map detections into canonical coordinates. Failed, low-overlap, opposite-side and budget-limited views remain separate. Full-size coordinate mappings include the source scaling, canvas shift and optional manual rectification transform.

Mosaics are PNG artifacts embedded as base64 in the current JSON response; a second lossless grayscale PNG maps each mosaic pixel to the source photo index. At overlap pixels, the photo with the higher global Laplacian sharpness score supplies the pixel. A bounded per-channel median brightness correction is estimated from the overlap. These are simple deterministic heuristics; they do not model local focus or optimize seam blending. Expanded/angled component parallax can remain, and the output is labeled candidate geometry.

The existing optional ONNX detector is called through `detect_components`; callers can inject a detector for tests or another local adapter. Without a model, the map still contains photo registration, mosaic, board-boundary candidates, and an empty component list with `DETECTOR_NOT_CONFIGURED`. OCR text is carried only if an upstream detector supplies it; no OCR/model identity is invented. Fusion requires the same predicted class, high bounding-box overlap, and close centers. Fused IDs hash board, side, type and canonical position, making IDs independent of observation iteration order. This conservative geometry rule can miss same-component fusions under perspective and must not be treated as reviewed identity.

`fault_overlay(component_map, side, candidates)` joins diagnostic component IDs to canonical boxes. Unknown IDs stay unmapped. `CONFIRMED_FAULT` is downgraded to `UNDETERMINED` unless the input explicitly contains measurement/inspection confirmation. Candidate status and diagnostic provenance are preserved.

## Rectification

The project already has `detect_board_candidates` and `rectify_board`. Boundary detection emits unconfirmed corner candidates; the service only rectifies if `PhotoInput.rectification_corners_px` supplies corners. Those coordinates are in the EXIF-corrected, intake-decoded image frame. Rectification failures retain the original image and include the reason. Successful output is marked `RECTIFIED_CANDIDATE_NOT_PHYSICALLY_VALIDATED`; physical dimensions and a verified metric board frame are not implied. Tall-component parallax cannot be fixed by a planar homography.

## Default resource limits

The service caps input at 20 images, 20 MiB per file / 80 MiB per session, 12 MP per photo / 40 MP total, a decoded edge of 1600 px, a 4000 px / 8 MP mosaic, and 60 seconds per pipeline. The existing ORB implementation caps keypoints at 2500 per image. Oversize canvases fall back to the reference view and mark other views unregistered. These are bounded workload limits, not operating-system RSS enforcement; actual peak RSS varies with OpenCV/Pillow allocator behavior. No persistent temp files are created by the service. Raw bytes and decoded images are retained only by the caller-owned in-memory session.

## Local use

```python
from circuitcare.vision.reconstruction.multi_image_component_map import (
    MultiImageComponentMapService, PhotoInput,
)

service = MultiImageComponentMapService()
session = service.ingest("board-123", [
    PhotoInput("top-overview.jpg", "TOP", "REFERENCE", "overview"),
    PhotoInput("top-closeup.webp", "TOP", "CLOSEUP", "closeup"),
    PhotoInput("bottom.png", "BOTTOM", "OVERVIEW", "bottom"),
])
component_map = service.build_map(session, model_path="models/pcb_detector.onnx")
```

For deterministic local pipeline timing and known geometric error, run:

```bash
python scripts/benchmark_multi_image_component_map.py
```

The script uses synthetic textured crops with known offsets. It is a smoke/reproducibility fixture and not a real PCB or detector accuracy benchmark.
