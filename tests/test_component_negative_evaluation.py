import importlib.util
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evaluate_component_domain", ROOT / "scripts" / "evaluate_component_domain.py")
evaluate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate)


def test_detector_failure_is_not_counted_as_zero_false_positives(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    row_root = tmp_path / "data/component_training/raw"
    row_root.mkdir(parents=True)
    image_path = row_root / "bread.jpg"
    Image.new("RGB", (16, 16), "white").save(image_path)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"images": [{"image_id": "bread-1", "image_path": "raw/bread.jpg",
        "image_type": "BREADBOARD", "hard_negative_eligible": True, "board_group_id": "board-1"}]}))
    monkeypatch.setattr(evaluate, "detect_components", lambda *a, **k: {
        "status": "MODEL_UNAVAILABLE", "detections": []})

    result = evaluate.evaluate_negatives(Path("model.onnx"), review, confidence=0.25, nms_iou=0.45)
    metrics = result["BREADBOARD"]
    assert metrics["reviewed_image_count"] == 1
    assert metrics["evaluated_image_count"] == 0
    assert metrics["inference_failure_count"] == 1
    assert metrics["image_level_false_positive_rate"] is None
    assert metrics["mean_false_positives_per_image"] is None
    assert metrics["status"] == "NO_SUCCESSFUL_INFERENCES"
    assert metrics["per_image"][0]["status"] == "INFERENCE_FAILED"


def test_only_successful_images_enter_negative_metric_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    row_root = tmp_path / "data/component_training/raw"
    row_root.mkdir(parents=True)
    for name in ("good.jpg", "bad.jpg"):
        Image.new("RGB", (16, 16), "white").save(row_root / name)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"images": [
        {"image_id": "good", "image_path": "raw/good.jpg", "image_type": "BREADBOARD",
         "hard_negative_eligible": True},
        {"image_id": "bad", "image_path": "raw/bad.jpg", "image_type": "BREADBOARD",
         "hard_negative_eligible": True}]}))

    def detector(image, model, **kwargs):
        if image.getpixel((0, 0)) == (255, 255, 255):
            return {"status": "INFERENCE_COMPLETE", "model": {"status": "READY"}, "detections": []}
        return {"status": "MODEL_UNAVAILABLE", "detections": []}

    # Make one image distinguishable so only its inference can fail.
    Image.new("RGB", (16, 16), "black").save(row_root / "bad.jpg")
    monkeypatch.setattr(evaluate, "detect_components", detector)
    result = evaluate.evaluate_negatives(Path("model.onnx"), review, confidence=0.25, nms_iou=0.45)
    metrics = result["BREADBOARD"]
    assert metrics["reviewed_image_count"] == 2
    assert metrics["evaluated_image_count"] == 1
    assert metrics["inference_failure_count"] == 1
    assert metrics["image_level_false_positive_rate"] == 0
    assert metrics["mean_false_positives_per_image"] == 0
    assert metrics["status"] == "PARTIAL_INFERENCE_FAILURE"
