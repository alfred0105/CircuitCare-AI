# PCB trace inference prototype

This folder packages the two local candidate pipelines used by the PCB component test UI. It is an experimental branch addition; it does not replace the existing `circuitcare.vision.reconstruction` photo-observation workflow.

## Staged graph pipeline

`pcb_trace_graph.py` implements:

1. Multi-source mask voting: optional PRISM mask, local multi-angle line evidence, and color evidence. The 0.50 threshold requires at least two votes; no single filter is sufficient.
2. Morphological bright-pad candidates.
3. Pad suppression followed by Zhang-Suen thinning.
4. Low-confidence terminal priors estimated only when a supported package template and pin count are available; unsupported IC/connector templates are listed in diagnostics.
5. One-to-one pad matching using global Hungarian assignment, distance, outward direction, and pad shape confidence.
6. Skeleton pixels are traversed through 8-neighbor adjacency into ordered polylines. Each connected centerline component is retained as a graph node, so branches and parallel segments are not reduced to a single farthest pad pair. Pad contacts are recorded before pad suppression and reused when attaching centerline segments.
7. A NetworkX `MultiGraph` when NetworkX is installed, with ranked candidate edges and explicit uncertainty. An adjacency-data fallback keeps image analysis available when it is not installed.

Minimal call shape (image is an OpenCV BGR array):

```python
import cv2
from pcb_trace_graph import run_trace_graph_pipeline

image = cv2.imread("board.jpg")
detections = [
    {"class_name": "IC", "bbox_xyxy": [120, 80, 250, 190], "confidence": 0.8},
    {"class_name": "capacitor", "bbox_xyxy": [300, 170, 340, 210], "confidence": 0.7},
]
result = run_trace_graph_pipeline(image, detections, prism_mask=None)
print(result["diagnostics"])
print(result["edges"])
```

`pcb_connection_inference.py` retains the earlier location-guided alternatives: conductivity/line-likelihood A* routing between nearby component boxes and connected-region flood fill. A* pairs that fail route-evidence, supported-length, or both-endpoint thresholds are returned as `UNKNOWN` diagnostics instead of being drawn as routes. Flood-fill samples are explicitly stored as `(x, y)` and are not misrepresented as ordered polylines.

## Additional trace experiments

- `trace_filter_experiments.py` runs scikit-image Frangi and Meijering at multiple scales and both ridge polarities. The UI overlays show filter response strength only; they are not accepted routes. These filters are ridge enhancers and may also highlight silkscreen and component edges.
- `cldice_loss.py` contains a PyTorch soft-clDice loss combined with BCE and Dice for a future binary trace-segmentation model. It is not attached to the current YOLO detection model. The local PCB-Layout sample set contains photo/design-image pairs, not verified trace masks, so it is not enough to train or score this loss as-is.
- `sam2_label_assist.py` is an optional point/box-prompted SAM 2 mask proposal helper. A person must inspect and correct each mask before using it as training truth. The official SAM 2 installation guide recommends WSL/Ubuntu for Windows; this helper does not install SAM 2 or download checkpoints.

Example from a configured SAM 2 checkout/environment:

```bash
python sam2_label_assist.py --image board.png --output proposed-trace-mask.png --checkpoint checkpoints/sam2.1_hiera_small.pt --config configs/sam2.1/sam2.1_hiera_s.yaml --positive-points '[[420,180],[510,205]]' --negative-points '[[455,260]]'
```

Current UI response-map experiment dependency: `scikit-image==0.26.0`.

## Limits

- Box-edge terminal priors are not pin detections; package pitch, orientation, and pin count are not yet read from a footprint library.
- Bright silkscreen and specular glare can still be pad candidates.
- The edge rank is relative evidence, not a calibrated probability.
- A single-side photo cannot establish hidden-layer connectivity, a net, or physical continuity.
- Treat every edge as a review hypothesis. Do not use it as a verified repair route.

## References

- [PRISM](https://github.com/KamMalinski/PRISM): its mask can be supplied as an optional vote; this prototype does not import PRISM code.
- [PCB Mapper](https://github.com/AMFT/pcb-mapper): reference for conductivity scoring and A* route ranking; no upstream source is included.
- [PCB Tracer](https://github.com/cm68/traces): reference for pad/pin anchor and flood-fill connectivity concepts; no upstream source is included.
- [scikit-image ridge filters](https://scikit-image.org/docs/stable/api/skimage.filters.html): API reference for Frangi and Meijering.
- [clDice reference implementation](https://github.com/jocpae/clDice): topology-aware segmentation metric/loss reference; `cldice_loss.py` is a standalone adaptation for binary PCB masks.
- [SAM 2](https://github.com/facebookresearch/sam2): promptable image/video segmentation; use the official install guide before setting up the optional helper.
- Zhang and Suen, “A fast parallel algorithm for thinning digital patterns,” *Communications of the ACM*, 27(3), 236–239, 1984, [DOI](https://doi.org/10.1145/357994.358023). The thinning procedure is implemented independently.

The two cited GitHub projects have distinct upstream licenses (MIT for PCB Mapper; GPL-3.0 for PCB Tracer). No source files from either project are included here. Review upstream terms before incorporating their code.
