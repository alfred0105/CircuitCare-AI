"""OCR helpers for reading printed markings inside detected IC boxes.

This module is intentionally independent from the PCB detection UI and inference
pipeline. Install the optional engine with ``python -m pip install rapidocr``.

Example::

    result = read_ic_marking(image_bgr, (x1, y1, x2, y2))
    print(result["text"])

The returned text is an OCR candidate and must be checked by a person; it is
not treated as a confirmed part number.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence


class ICMarkingOCRUnavailable(RuntimeError):
    """Raised when the optional OCR engine is missing or cannot run."""


@lru_cache(maxsize=1)
def _get_engine() -> Any:
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise ICMarkingOCRUnavailable(
            "IC marking OCR requires RapidOCR. Install it with `python -m pip install rapidocr`."
        ) from exc
    return RapidOCR()


def _prepare_ic_crop(image_bgr: Any, bbox_xyxy: Sequence[float]) -> tuple[Any, int]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ICMarkingOCRUnavailable(
            "IC marking OCR requires OpenCV and NumPy from the component recognition environment."
        ) from exc

    image = np.asarray(image_bgr)
    if image.ndim not in (2, 3) or image.size == 0:
        raise ValueError("image_bgr must be a non-empty OpenCV image.")
    if len(bbox_xyxy) != 4:
        raise ValueError("bbox_xyxy must contain x1, y1, x2, y2.")

    height, width = image.shape[:2]
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    left = max(0, min(width, int(round(min(x1, x2)))))
    top = max(0, min(height, int(round(min(y1, y2)))))
    right = max(0, min(width, int(round(max(x1, x2)))))
    bottom = max(0, min(height, int(round(max(y1, y2)))))
    if right <= left or bottom <= top:
        raise ValueError("IC bounding box is outside the image or has no area.")

    crop = image[top:bottom, left:right]
    if crop.ndim == 3:
        if crop.shape[2] == 4:
            crop = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
        else:
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Contrast enhancement and enlargement help with small laser-marked text.
    crop = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(crop)
    scale = max(2, min(4, 960 // max(crop.shape[:2])))
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return crop, scale


def read_ic_marking(image_bgr: Any, bbox_xyxy: Sequence[float]) -> dict[str, Any]:
    """Read text inside one detected IC box, returning unverified OCR candidates.

    Args:
        image_bgr: Full image as a NumPy/OpenCV BGR (or grayscale) array.
        bbox_xyxy: IC box in full-image pixel coordinates: ``(x1, y1, x2, y2)``.

    Returns:
        A JSON-serializable result with combined text and per-line OCR candidates.
        OCR boxes are expressed in coordinates relative to the original IC crop.
    """
    try:
        import numpy as np
        crop, scale = _prepare_ic_crop(image_bgr, bbox_xyxy)
        result = _get_engine()(crop)
    except ICMarkingOCRUnavailable:
        raise
    except Exception as exc:
        raise ICMarkingOCRUnavailable(f"IC marking OCR failed: {exc}") from exc

    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    texts = () if texts is None else texts
    scores = () if scores is None else scores
    boxes = () if boxes is None else boxes
    lines = []
    for index, value in enumerate(texts):
        text = str(value).strip()
        if not text:
            continue
        polygon = []
        if index < len(boxes) and boxes[index] is not None:
            polygon = np.asarray(boxes[index], dtype=float).reshape(-1, 2).tolist()
            # RapidOCR coordinates refer to the preprocessed crop. Return them
            # in original crop pixels for UI overlay integration later.
            polygon = [[round(float(x) / scale, 2), round(float(y) / scale, 2)] for x, y in polygon]
        score = float(scores[index]) if index < len(scores) else None
        lines.append({
            "text": text,
            "polygon_xy": polygon,
            "ocr_score": score,
            "verification_status": "unverified",
        })

    return {
        "status": "OCR_COMPLETE",
        "engine": "RapidOCR / PP-OCR",
        "text": "\n".join(line["text"] for line in lines),
        "lines": lines,
        "verification_status": "unverified",
        "source": "ic_marking",
    }
