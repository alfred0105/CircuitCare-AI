# PCB trace inference prototype

This folder packages the two local candidate pipelines used by the PCB component test UI. It is an experimental branch addition; it does not replace the existing `circuitcare.vision.reconstruction` photo-observation workflow.

## Staged graph pipeline

`pcb_trace_graph.py` implements:

1. Multi-source mask voting: optional PRISM mask, local multi-angle line evidence, and color evidence.
2. Morphological bright-pad candidates.
3. Pad suppression followed by Zhang-Suen thinning.
4. Low-confidence terminal priors estimated from component box edges and class group.
5. One-to-one pad matching using distance, outward direction, and pad shape confidence.
6. A NetworkX graph when NetworkX is installed, with ranked candidate edges and explicit uncertainty. An adjacency-data fallback keeps image analysis available when it is not installed.

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

`pcb_connection_inference.py` retains the earlier location-guided alternatives: conductivity/line-likelihood A* routing between nearby component boxes and connected-region flood fill.

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
- Zhang and Suen, “A fast parallel algorithm for thinning digital patterns,” *Communications of the ACM*, 27(3), 236–239, 1984, [DOI](https://doi.org/10.1145/357994.358023). The thinning procedure is implemented independently.

The two cited GitHub projects have distinct upstream licenses (MIT for PCB Mapper; GPL-3.0 for PCB Tracer). No source files from either project are included here. Review upstream terms before incorporating their code.
