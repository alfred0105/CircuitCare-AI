#!/usr/bin/env python3
"""Evaluate a one-class YOLO experiment on one explicit PCB-DSLR manifest split."""
from __future__ import annotations
import argparse
import json
import math
import platform
import resource
import statistics
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/component_training/manifests/pcb-dslr-part1-ic-manifest.json"
DEFAULT_YAML = ROOT / "data/component_training/processed/pcb-dslr-part1-ic-v3/data.yaml"


def iou_xyxy(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    return inter / (area_a + area_b - inter) if area_a + area_b > inter else 0.0


def match_at_iou(rows, threshold, confidence=0.001, small_only=False, imgsz=640):
    gt_total = 0
    candidates = []
    per_image = {}
    for row in rows:
        factor = imgsz / max(row["image_size_px"])
        gts = [a["bbox_xyxy"] for a in row["ground_truth"]
               if not small_only or (a["bbox_xyxy"][2]-a["bbox_xyxy"][0]) *
                                      (a["bbox_xyxy"][3]-a["bbox_xyxy"][1]) * factor * factor < 32*32]
        gt_total += len(gts)
        preds = [p for p in row["predictions"] if p["confidence"] >= confidence]
        candidates.extend((p["confidence"], row["image_id"], p["bbox_xyxy"]) for p in preds)
        per_image[row["image_id"]] = {"ground_truth": gts, "matched": set(), "fp": 0, "tp": 0}
    candidates.sort(key=lambda x: -x[0])
    tp_flags, fp_flags = [], []
    for conf, image_id, box in candidates:
        state = per_image[image_id]
        matches = [(iou_xyxy(box, gt), index) for index, gt in enumerate(state["ground_truth"])
                   if index not in state["matched"]]
        best = max(matches, default=(0.0, -1))
        if best[0] >= threshold:
            state["matched"].add(best[1]); state["tp"] += 1; tp_flags.append(1); fp_flags.append(0)
        else:
            state["fp"] += 1; fp_flags.append(1); tp_flags.append(0)
    tp = sum(tp_flags); fp = sum(fp_flags); fn = gt_total - tp
    return {"tp": tp, "fp": fp, "fn": fn, "gt": gt_total,
            "precision": tp/(tp+fp) if tp+fp else 0.0,
            "recall": tp/gt_total if gt_total else 0.0,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,
            "per_image": per_image, "tp_flags": tp_flags, "fp_flags": fp_flags,
            "confidences": [c[0] for c in candidates]}


def average_precision(rows, iou_threshold, imgsz):
    result = match_at_iou(rows, iou_threshold, confidence=0.001, imgsz=imgsz)
    if result["gt"] == 0: return 0.0
    tp = np.cumsum(result["tp_flags"]); fp = np.cumsum(result["fp_flags"])
    recall = tp / result["gt"]
    precision = tp / np.maximum(tp + fp, 1)
    return float(np.mean([np.max(precision[recall >= r], initial=0.0)
                          for r in np.linspace(0, 1, 101)]))


def render_examples(rows, fixed, out):
    out.mkdir(parents=True, exist_ok=True)
    fp_rows, fn_rows = [], []
    for row in rows:
        state = fixed["per_image"][row["image_id"]]
        matched = state["matched"]
        gt_boxes = [a["bbox_xyxy"] for a in row["ground_truth"]]
        pred_boxes = [p for p in row["predictions"] if p["confidence"] >= 0.25]
        image = Image.open(row["path"]).convert("RGB")
        draw = ImageDraw.Draw(image)
        for index, box in enumerate(gt_boxes):
            draw.rectangle(box, outline=(50, 160, 255), width=max(2, image.width//1500))
        for pred in pred_boxes:
            box = pred["bbox_xyxy"]
            draw.rectangle(box, outline=(40, 255, 80), width=max(2, image.width//1500))
        image.save(out / (row["image_id"].replace(":", "_") + "_comparison.jpg"), quality=86)
        fn = len(gt_boxes)-len(matched); fp = state["fp"]
        if fp: fp_rows.append((fp, row["image_id"]))
        if fn: fn_rows.append((fn, row["image_id"]))
    return {"false_positive_images": sorted(fp_rows, reverse=True)[:12],
            "false_negative_images": sorted(fn_rows, reverse=True)[:12]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "sealed_test"), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data", type=Path, default=DEFAULT_YAML)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    rows=[]
    for item in manifest["images"]:
        if item["split"] != args.split: continue
        image_path = ROOT / item["image_path"]
        if image_path.stat().st_size == 0: raise ValueError(f"empty image: {image_path}")
        image = Image.open(image_path).convert("RGB")
        if list(image.size) != item["image_size_px"]: raise ValueError(f"size mismatch: {item['image_id']}")
        rows.append({"image_id":item["image_id"],"path":image_path,"image":image,
          "image_size_px":item["image_size_px"],"board_id":item["board_id"],
          "ground_truth":item["annotations"],"predictions":[]})
    if not rows: raise ValueError(f"no images found for split {args.split}")
    import torch
    from ultralytics import YOLO
    if args.device == "mps" and not torch.backends.mps.is_available(): raise RuntimeError("MPS requested but unavailable")
    model=YOLO(str(args.weights)); latencies=[]
    for row in rows:
        started=time.perf_counter()
        result=model.predict(row["image"],imgsz=args.imgsz,conf=0.001,iou=args.nms_iou,
                             device=args.device,verbose=False)[0]
        latencies.append((time.perf_counter()-started)*1000)
        if result.boxes is not None:
            row["predictions"]=[{"bbox_xyxy":[float(v) for v in box.xyxy[0].cpu().tolist()],
                "confidence":float(box.conf[0].cpu()),"class_id":int(box.cls[0].cpu())} for box in result.boxes]
    fixed=match_at_iou(rows,0.5,args.confidence,imgsz=args.imgsz)
    small=match_at_iou(rows,0.5,args.confidence,small_only=True,imgsz=args.imgsz)
    aps={f"{threshold:.2f}":average_precision(rows,threshold,args.imgsz)
         for threshold in np.arange(.5,.96,.05)}
    boards=defaultdict(lambda:{"gt":0,"tp":0})
    for row in rows:
        state=fixed["per_image"][row["image_id"]];board=boards[row["board_id"]]
        board["gt"]+=len(state["ground_truth"]);board["tp"]+=state["tp"]
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    examples=render_examples(rows,fixed,output/"comparisons")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    curve=match_at_iou(rows,.5,.001,imgsz=args.imgsz)
    tp=np.cumsum(curve["tp_flags"]);fp=np.cumsum(curve["fp_flags"])
    rec=tp/max(curve["gt"],1);prec=tp/np.maximum(tp+fp,1)
    plt.figure();plt.plot(rec,prec);plt.xlabel("Recall");plt.ylabel("Precision");plt.title("PCB-DSLR IC precision-recall (IoU=0.5)");plt.grid(True);plt.savefig(output/"precision_recall.png",dpi=160);plt.close()
    cm=np.array([[fixed["tp"],fixed["fn"]],[fixed["fp"],0]])
    fig,ax=plt.subplots();ax.imshow(cm,cmap="Blues");ax.set_xticks([0,1],labels=["Detected","Missed"]);ax.set_yticks([0,1],labels=["GT IC","Background FP"])
    for (i,j),v in np.ndenumerate(cm):ax.text(j,i,str(v),ha="center",va="center")
    ax.set_title("IC confusion counts @ confidence 0.25, IoU 0.5");fig.tight_layout();fig.savefig(output/"confusion_matrix.png",dpi=160);plt.close(fig)
    report={"schema_version":"circuitcare.pcb-dslr-yolov8-experiment-evaluation.v1",
      "dataset_id":manifest["dataset_id"],"dataset_version":manifest["source_version"],"dataset_manifest_sha256":__import__("hashlib").sha256(args.manifest.read_bytes()).hexdigest(),
      "split":args.split,"image_count":len(rows),"board_count":len(boards),"board_ids":sorted(boards),"annotation_count":sum(len(r["ground_truth"]) for r in rows),
      "model":str(args.weights.resolve()),"model_class_contract":["integrated_circuit"],"image_size":args.imgsz,"device":args.device,"confidence_threshold":args.confidence,"nms_iou":args.nms_iou,"metric_iou":0.5,
      "metrics":{"precision":fixed["precision"],"recall":fixed["recall"],"f1":fixed["f1"],"mAP50":aps["0.50"],"mAP50_95":float(np.mean(list(aps.values()))),"ap_by_iou":aps,"tp":fixed["tp"],"fp":fixed["fp"],"fn":fixed["fn"],"small_object_recall":small["recall"],"small_object_gt_count":small["gt"]},
      "board_metrics":{board:{"gt":v["gt"],"tp":v["tp"],"recall":v["tp"]/v["gt"] if v["gt"] else None} for board,v in sorted(boards.items())},
      "inference_latency_ms":{"mean":statistics.mean(latencies),"median":statistics.median(latencies),"p95":float(np.percentile(latencies,95))},
      "peak_process_rss_bytes":int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if platform.system()=="Darwin" else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024),
      "visualizations":{"pr_curve":str((output/"precision_recall.png").resolve()),"confusion_matrix":str((output/"confusion_matrix.png").resolve()),"comparisons":str((output/"comparisons").resolve())},
      "failure_examples":examples,"ground_truth_status":"SOURCE_PROVIDED_UNADJUDICATED","interpretation":"Experimental source-label agreement only; not independently adjudicated generalization accuracy."}
    (output/"evaluation.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k not in {"board_metrics","failure_examples"}},indent=2,ensure_ascii=False))
    return 0

if __name__=="__main__":raise SystemExit(main())
