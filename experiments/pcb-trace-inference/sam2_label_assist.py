"""Optional SAM 2 image-mask proposal helper for human-reviewed trace labels.

SAM 2 and its checkpoint are intentionally optional. Run this in a supported
environment (the upstream project recommends WSL/Ubuntu on Windows), then
review the output mask before using it as a training label.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def propose_mask(image_path: str, output_path: str, checkpoint: str, model_config: str,
                 positive_points: list[list[float]], negative_points: list[list[float]] | None = None,
                 box_xyxy: list[float] | None = None, device: str = "cuda") -> dict:
    if not positive_points and not negative_points and box_xyxy is None:
        raise ValueError("Provide at least one point or a box prompt")
    try:
        import torch
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except ImportError as exc:
        raise RuntimeError("Install the official SAM 2 package in a supported environment first") from exc

    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read image: {image_path}")
    if device.startswith("cuda") and not torch.cuda.is_available():
        device = "cpu"
    model = build_sam2(model_config, checkpoint, device=device)
    predictor = SAM2ImagePredictor(model)
    predictor.set_image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    coords, labels = [], []
    for point in positive_points:
        coords.append(point)
        labels.append(1)
    for point in negative_points or []:
        coords.append(point)
        labels.append(0)
    masks, scores, _ = predictor.predict(
        point_coords=np.asarray(coords, dtype=np.float32) if coords else None,
        point_labels=np.asarray(labels, dtype=np.int32) if labels else None,
        box=np.asarray(box_xyxy, dtype=np.float32) if box_xyxy else None,
        multimask_output=True,
    )
    best = int(np.argmax(scores))
    mask = masks[best].astype(np.uint8) * 255
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), mask):
        raise RuntimeError(f"Cannot write mask: {destination}")
    return {"mask_path": str(destination), "score": float(scores[best]),
            "mask_pixels": int(np.count_nonzero(mask)),
            "warning": "SAM 2 proposal only; manually inspect and correct before training."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", required=True, help="SAM 2 model YAML config")
    parser.add_argument("--positive-points", default="[]", help='JSON [[x,y],...]')
    parser.add_argument("--negative-points", default="[]", help='JSON [[x,y],...]')
    parser.add_argument("--box", default="", help="JSON [x0,y0,x1,y1]")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    box = json.loads(args.box) if args.box else None
    result = propose_mask(args.image, args.output, args.checkpoint, args.config,
                          json.loads(args.positive_points), json.loads(args.negative_points),
                          box, args.device)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
