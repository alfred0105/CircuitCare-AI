"""Safe, bounded, local image loading for PCB photographs."""

from __future__ import annotations

import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from circuitcare.vision.models import BoardImage

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_EDGE = 2400


class ImageLoadError(ValueError):
    """Raised when an uploaded image is invalid or exceeds safe limits."""


def load_board_image(data: bytes, *, max_file_bytes: int = MAX_FILE_BYTES,
                     max_pixels: int = MAX_PIXELS, max_edge: int = MAX_EDGE) -> BoardImage:
    if not data:
        raise ImageLoadError("이미지 파일이 비어 있습니다.")
    if len(data) > max_file_bytes:
        raise ImageLoadError(f"이미지 파일은 {max_file_bytes // (1024 * 1024)} MB 이하만 지원합니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(data))
            if source.format not in {"JPEG", "PNG"}:
                raise ImageLoadError("JPG/JPEG 또는 PNG 이미지만 지원합니다.")
            if source.width <= 0 or source.height <= 0 or source.width * source.height > max_pixels:
                raise ImageLoadError(f"이미지는 최대 {max_pixels:,} 픽셀까지 지원합니다.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            original_size = image.size
            image_format = source.format
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ImageLoadError("이미지를 읽을 수 없습니다. 손상되었거나 허용 크기를 초과했는지 확인하세요.") from exc

    if max_edge < 1:
        raise ValueError("max_edge는 양수여야 합니다.")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    processed_size = image.size
    return BoardImage(
        image=image,
        sha256=hashlib.sha256(data).hexdigest(),
        original_size=original_size,
        processed_size=processed_size,
        scale_xy=(processed_size[0] / original_size[0], processed_size[1] / original_size[1]),
        format=image_format,
    )
