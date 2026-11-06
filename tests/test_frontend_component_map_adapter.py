import base64
import io

import pytest
from PIL import Image

from circuitcare.frontend.component_map_adapter import (
    component_map_cache_key, decode_canonical_image, map_backend_photo_ids,
    validate_component_map,
)
from circuitcare.frontend.photo_adapter import ComponentMapPhotoInput


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "#456").save(buffer, format="PNG")
    return buffer.getvalue()


def _map():
    """Synthetic TEST FIXTURE contract; it is never used by the product UI."""
    raw = _png()
    return {"schema_version": "circuitcare.pcb-component-map.v1", "board_id": "b1", "photos": [
        {"photo_id": "backend-1", "sha256": "a" * 64, "side": "TOP", "role": "OVERVIEW"}],
        "sides": {"TOP": {"canonical_image": {
            "image_id": "frame-1", "coordinate_frame": "MOSAIC_PIXEL", "image_size_px": [8, 6],
            "reference_photo_id": "backend-1", "image_png_base64": base64.b64encode(raw).decode()},
            "registrations": [{"photo_id": "backend-1", "status": "REFERENCE"}]}},
    }


def test_schema_validation_and_canonical_decode():
    value = validate_component_map(_map(), board_id="b1")
    canonical = decode_canonical_image(value["sides"]["TOP"]["canonical_image"])
    assert (canonical.frame_id, canonical.width, canonical.height) == ("frame-1", 8, 6)
    assert canonical.registration_status == "CANDIDATE_GEOMETRY_ONLY"


def test_schema_and_base64_fail_closed():
    with pytest.raises(ValueError):
        validate_component_map({**_map(), "schema_version": "v9"}, board_id="b1")
    canonical = _map()["sides"]["TOP"]["canonical_image"]
    with pytest.raises(ValueError):
        decode_canonical_image({**canonical, "image_png_base64": "!!!"})


def test_photo_id_mapping_requires_unique_side_role_hash():
    item = ComponentMapPhotoInput("b1", "front-1", "a" * 64, "TOP", "OVERVIEW", b"x", "name")
    result = _map()
    mapped = map_backend_photo_ids(project_id="p1", board_id="b1", inputs=[item], result=result)
    assert mapped[0].backend_photo_id == "backend-1"
    assert mapped[0].registration_status == "REFERENCE"
    duplicate = map_backend_photo_ids(project_id="p1", board_id="b1", inputs=[item, item], result=result)
    assert all(row.mapping_status == "UNCONFIRMED" for row in duplicate)


def test_cache_key_is_project_board_and_input_scoped():
    item = ComponentMapPhotoInput("b1", "front-1", "a" * 64, "TOP", "OVERVIEW", b"x", "name")
    key = component_map_cache_key(project_id="p1", board_id="b1", inputs=[item])
    assert key != component_map_cache_key(project_id="p2", board_id="b1", inputs=[item])
    assert key != component_map_cache_key(project_id="p1", board_id="b2", inputs=[item])
