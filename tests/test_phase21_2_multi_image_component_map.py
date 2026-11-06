import base64
import io

import cv2
import numpy as np
from PIL import Image
from PIL import ImageFilter

from circuitcare.vision.reconstruction.multi_image_component_map import (
    CaptureRole, ImageBudget, MultiImageComponentMapService, MultiImageError,
    PhotoInput, to_json,
)


def _textured_scene():
    rng = np.random.default_rng(9142)
    image = rng.integers(0, 256, (400, 520, 3), dtype=np.uint8)
    image = np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(1.2))).copy()
    for x in range(20, 520, 32):
        for y in range(20, 400, 32):
            color = (255, 255, 255) if (x + y) % 2 else (0, 0, 0)
            cv2.circle(image, (x, y), 5, color, 2)
    return image


def _png(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    return stream.getvalue()


def test_intake_hashes_orients_limits_and_keeps_sides_separate():
    service = MultiImageComponentMapService()
    image = np.full((80, 120, 3), 120, dtype=np.uint8)
    session = service.ingest("board-1", [
        PhotoInput(_png(image), "TOP", CaptureRole.OVERVIEW, "top.png"),
        PhotoInput(_png(image), "BOTTOM", CaptureRole.CLOSEUP, "bottom.png"),
        PhotoInput(_png(image), "TOP", CaptureRole.ANGLED, "top-copy.png"),
    ])
    assert session.photos[0].sha256 == session.photos[2].sha256
    assert session.photos[0].photo_id != session.photos[1].photo_id
    assert session.photos[2].duplicate_of == session.photos[0].photo_id
    result = service.build_map(session)
    assert set(result["sides"]) == {"TOP", "BOTTOM"}
    assert result["design_registration"]["status"] == "NOT_RUN_SEPARATE_FROM_PHOTO_REGISTRATION"
    assert "rgb_pixels" not in result["sides"]["TOP"]["canonical_image"]
    assert to_json(result).startswith('{"board_id":"board-1"')

    limited = MultiImageComponentMapService(budget=ImageBudget(max_images=1))
    try:
        limited.ingest("board", [PhotoInput(_png(image), "TOP"), PhotoInput(_png(image), "TOP")])
    except MultiImageError as exc:
        assert exc.code == "IMAGE_COUNT_LIMIT"
    else:
        raise AssertionError("image count limit was not enforced")


def test_exif_orientation_is_applied_and_corrupt_images_fail_closed():
    image = Image.new("RGB", (120, 80), "navy")
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    service = MultiImageComponentMapService()
    session = service.ingest("exif-board", [PhotoInput(stream.getvalue(), "TOP")])
    assert session.photos[0].original_size_px == (80, 120)
    assert session.photos[0].processed_size_px == (80, 120)
    try:
        service.ingest("bad-image", [PhotoInput(b"not an image", "TOP")])
    except MultiImageError as exc:
        assert exc.code == "INVALID_IMAGE"
    else:
        raise AssertionError("corrupt image was accepted")


def test_overlapping_photos_stitch_and_fuse_same_detection_with_provenance():
    scene = _textured_scene()
    first, second = scene[:, :400], scene[:, 120:520]
    service = MultiImageComponentMapService()
    session = service.ingest("fixture-board", [
        PhotoInput(_png(first), "TOP", CaptureRole.REFERENCE, "overview.png"),
        PhotoInput(_png(second), "TOP", CaptureRole.CLOSEUP, "closeup.png"),
    ])
    def detector(image):
        # Same physical component is at x=220 in canonical space.
        x = 220 if image.width == 400 and image.getpixel((10, 10)) == tuple(first[10, 10]) else 100
        return {"status": "INFERENCE_COMPLETE", "detections": [
            {"detection_id": "U1", "class_name": "integrated_circuit", "confidence": 0.91,
             "bbox_xyxy": [x - 15, 120, x + 15, 150]},
        ]}
    result = service.build_map(session, detector=detector)
    top = result["sides"]["TOP"]
    regs = {item["photo_id"]: item for item in top["registrations"]}
    moving = next(photo for photo in session.photos if photo.name == "closeup.png")
    assert regs[moving.photo_id]["status"] == "REGISTERED_CANDIDATE"
    assert regs[moving.photo_id]["inlier_ratio"] > 0.2
    repeat = service.build_map(session, detector=detector)
    repeat_regs = {item["photo_id"]: item for item in repeat["sides"]["TOP"]["registrations"]}
    assert regs[moving.photo_id]["transform_moving_to_canonical"] == repeat_regs[moving.photo_id]["transform_moving_to_canonical"]
    assert top["canonical_image"]["image_size_px"][0] >= 400
    assert len(top["components"]) == 1
    assert top["components"][0]["identity_fusion_status"] == "MULTI_OBSERVATION_FUSED"
    assert len(top["components"][0]["source_image_ids"]) == 2
    assert len({component["component_id"] for component in top["components"]}) == 1
    mosaic_png = base64.b64decode(top["canonical_image"]["image_png_base64"])
    assert Image.open(io.BytesIO(mosaic_png)).size == tuple(top["canonical_image"]["image_size_px"])

    overlay = service.fault_overlay(result, "TOP", [
        {"component_id": top["components"][0]["component_id"], "status": "CONFIRMED_FAULT",
         "confirmed_by_measurement_or_inspection": True},
        {"component_id": "missing", "status": "SUSPECTED_FAULT"},
    ])
    assert overlay["candidates"][0]["fault_candidate_status"] == "CONFIRMED_FAULT"
    assert overlay["candidates"][1]["mapping_status"] == "UNMAPPED_COMPONENT_ID"


def test_nonoverlapping_photos_are_not_forced_into_mosaic():
    rng = np.random.default_rng(33)
    one = rng.integers(0, 255, (220, 240, 3), dtype=np.uint8)
    two = rng.integers(0, 255, (220, 240, 3), dtype=np.uint8)
    session = MultiImageComponentMapService().ingest("unrelated", [
        PhotoInput(_png(one), "TOP", CaptureRole.REFERENCE),
        PhotoInput(_png(two), "TOP", CaptureRole.CLOSEUP),
    ])
    result = MultiImageComponentMapService().build_map(session)
    moving = next(photo for photo in session.photos if photo.photo_id != result["sides"]["TOP"]["registrations"][0]["photo_id"])
    records = {item["photo_id"]: item for item in result["sides"]["TOP"]["registrations"]}
    assert records[moving.photo_id]["status"] == "UNREGISTERED"
    assert records[moving.photo_id]["transform_moving_to_canonical"] is None
