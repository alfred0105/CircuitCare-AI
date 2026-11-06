from circuitcare.vision.detection_evaluation import (
    evaluate_detections, validate_annotation_manifest, validate_board_splits,
)
import pytest


def test_evaluation_reports_map5095_small_recall_confidence_curve_and_duplicate_fp():
    truth = {"a.jpg": [{"class_id": 0, "bbox_xyxy": [0, 0, 20, 20]},
                       {"class_id": 0, "bbox_xyxy": [30, 30, 80, 80]}]}
    predictions = {"a.jpg": [
        {"class_name": "resistor", "confidence": 0.9, "bbox_xyxy": [0, 0, 20, 20]},
        {"class_name": "resistor", "confidence": 0.8, "bbox_xyxy": [0, 0, 20, 20]},
        {"class_name": "resistor", "confidence": 0.7, "bbox_xyxy": [30, 30, 80, 80]},
    ]}
    metrics = evaluate_detections(truth, predictions, class_names=["resistor"],
                                  confidence_threshold=0.25, confidence_thresholds=[0.5])
    assert metrics["true_positive_count"] == 2
    assert metrics["false_positive_count"] == 1
    assert metrics["false_negative_count"] == 0
    assert metrics["map50"] == pytest.approx(5 / 6)
    assert metrics["map50_95"] == pytest.approx(5 / 6)
    assert metrics["classes"]["resistor"]["small_object_ground_truth_count"] == 1
    assert metrics["classes"]["resistor"]["small_object_recall_at_confidence_threshold"] == 1.0
    assert metrics["confidence_threshold_curve"][0]["precision"] == 2 / 3


def test_board_split_leakage_detects_related_images_and_duplicate_bytes():
    result = validate_board_splits([
        {"image_id": "board-a-top", "board_id": "board-a", "split": "training", "image_sha256": "same"},
        {"image_id": "board-a-close", "board_id": "board-a", "split": "sealed_test", "image_sha256": "other"},
        {"image_id": "board-b", "board_id": "board-b", "split": "validation", "image_sha256": "same"},
    ])
    assert result["status"] == "LEAKAGE_OR_MANIFEST_ERROR"
    codes = {row["code"] for row in result["errors"]}
    assert "BOARD_SPLIT_LEAKAGE" in codes
    assert "IMAGE_HASH_SPLIT_LEAKAGE" in codes


def test_annotation_manifest_requires_reviewed_truth_to_be_scoreable():
    row = {"component_id": "U1", "class": "integrated_circuit", "bbox_xyxy": [1, 1, 9, 9],
           "occlusion_state": "VISIBLE", "small_component": False,
           "annotation_status": "DRAFT_ANNOTATION", "reviewer": "annotator-a", "source": "manual"}
    image = {"image_id": "image-1", "board_id": "board-a", "board_revision": "rev-1",
             "board_side": "TOP", "split": "validation", "image_sha256": "a" * 64,
             "image_size_px": [10, 10], "source": "camera", "annotations": [row]}
    manifest = {"schema_version": "circuitcare.component-annotation.v1", "dataset_source": "source",
                "dataset_license": "CC BY 4.0", "images": [image]}
    result = validate_annotation_manifest(manifest, class_names=["integrated_circuit"])
    assert result["status"] == "VALID"
    assert result["scoreable_status"] == "BLOCKED_NO_REVIEWED_GROUND_TRUTH"
    row["annotation_status"] = "REVIEWED_GROUND_TRUTH"
    row["reviewer"] = "reviewer-1"
    reviewed = validate_annotation_manifest(manifest, class_names=["integrated_circuit"])
    assert reviewed["scoreable_status"] == "READY_REVIEWED_LABELS"
    draft = {**row, "component_id": "U2", "annotation_status": "DRAFT_ANNOTATION"}
    image["annotations"].append(draft)
    mixed = validate_annotation_manifest(manifest, class_names=["integrated_circuit"])
    assert mixed["scoreable_status"] == "BLOCKED_UNREVIEWED_ANNOTATIONS"


def test_manifest_rejects_out_of_bounds_boxes_unsupported_classes_and_board_leakage():
    base = {"component_id": "R1", "class": "inductor", "bbox_xyxy": [1, 1, 20, 20],
            "occlusion_state": "UNKNOWN", "small_component": True,
            "annotation_status": "REVIEWED_GROUND_TRUTH", "reviewer": "r1", "source": "manual"}
    images = []
    for image_id, split in (("v1", "training"), ("v2", "sealed_test")):
        images.append({"image_id": image_id, "board_id": "same-board", "board_revision": "revA",
            "board_side": "TOP", "split": split, "image_sha256": (image_id * 64)[:64],
            "image_size_px": [10, 10], "source": "camera", "annotations": [base]})
    manifest = {"schema_version": "circuitcare.component-annotation.v1", "dataset_source": "source",
                "dataset_license": "declared", "images": images}
    result = validate_annotation_manifest(manifest, class_names=["resistor"])
    errors = {row["code"] for row in result["errors"]}
    assert "INVALID_BOUNDING_BOX" in errors
    assert "UNSUPPORTED_CLASS" in errors
    assert "BOARD_SPLIT_LEAKAGE" in errors
