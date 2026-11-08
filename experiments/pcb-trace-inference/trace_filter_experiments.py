"""Experimental multiscale ridge responses for PCB trace visualization."""
from __future__ import annotations

import cv2
import numpy as np


def _response_overlay(image: np.ndarray, response: np.ndarray) -> tuple[np.ndarray, dict]:
    clean = np.nan_to_num(response.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    positive = clean[clean > 1e-7]
    if not positive.size:
        return image.copy(), {"response_pixels": 0, "p95_threshold": 0.0, "p95_pixels": 0}
    scale = max(1e-7, float(np.percentile(positive, 99.5)))
    normalized = np.clip(clean / scale, 0.0, 1.0)
    heat = cv2.applyColorMap(np.round(normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    alpha = (normalized[..., None] * 0.68).astype(np.float32)
    overlay = np.clip(image.astype(np.float32) * (1.0 - alpha) + heat.astype(np.float32) * alpha,
                      0, 255).astype(np.uint8)
    threshold = float(np.percentile(positive, 95.0))
    return overlay, {"response_pixels": int(np.count_nonzero(clean > 1e-7)),
                     "p95_threshold": round(threshold, 6),
                     "p95_pixels": int(np.count_nonzero(clean >= threshold)),
                     "normalization_p99_5": round(scale, 6)}


def run_ridge_filter_experiments(image: np.ndarray) -> dict:
    """Compute Frangi and Meijering response maps at several trace-width scales.

    Both ridge polarities are combined because visible PCB traces can be darker
    or brighter than the solder mask. The returned overlays are response maps,
    not accepted trace masks or connectivity claims.
    """
    try:
        from skimage.filters import frangi, meijering
    except ImportError as exc:
        raise RuntimeError("scikit-image is required for Frangi/Meijering experiments") from exc

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    scales = (0.7, 1.0, 1.5, 2.2, 3.2)
    outputs = {}
    for name, filter_fn in (("frangi", frangi), ("meijering", meijering)):
        dark = filter_fn(gray, sigmas=scales, black_ridges=True)
        bright = filter_fn(gray, sigmas=scales, black_ridges=False)
        response = np.maximum(dark, bright)
        overlay, diagnostics = _response_overlay(image, response)
        diagnostics.update({"method": name, "sigmas": list(scales),
                            "polarity": "max(black_ridges, white_ridges)",
                            "interpretation": "response visualization only; requires review"})
        outputs[name] = {"overlay": overlay, "response": response,
                         "diagnostics": diagnostics}
    return outputs
