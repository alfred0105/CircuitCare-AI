#!/usr/bin/env python3
"""Compare PCB pin connectivity models using only the requested 18 component labels."""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "data/benchmarks/pcb_pin_connectivity"
OUT = BENCH / "pcb_18label_connectivity_results.json"
PROGRESS = ROOT / "data/benchmarks/phase22_connectivity/recommendation_progress.json"
SPEC = importlib.util.spec_from_file_location("pcb_connectivity_base", ROOT / "scripts/benchmark_pcb_pin_connectivity.py")
BASE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
R2_SPEC = importlib.util.spec_from_file_location(
    "pcb_connectivity_review2", ROOT / "scripts/benchmark_pcb_pin_connectivity_review2.py")
R2 = importlib.util.module_from_spec(R2_SPEC)
assert R2_SPEC and R2_SPEC.loader
sys.modules[R2_SPEC.name] = R2
R2_SPEC.loader.exec_module(R2)

# User's 18 detector labels. oscillator is normalized to clock; unsupported historic
# labels are treated as the explicitly allowed internal unknown/abstention class.
LABELS = ("IC", "LED", "battery", "buzzer", "capacitor", "connector", "diode", "display",
          "fuse", "inductor", "clock", "potentiometer", "relay", "resistor", "switch",
          "transistor", "transformer", "heatsink")
ALIASES = {"oscillator": "clock"}
EXCLUDED_TYPES = {"jumper", "ferrite_bead", "emi_filter"}


def update_progress(phase, step, fraction, detail):
    doc = {"status": "완료" if phase == "완료" else "실행 중", "phase": phase,
           "phase_number": step, "phase_count": 5, "phase_percent": round(fraction * 100, 1),
           "overall_percent": 100 if phase == "완료" else 100 * (step - 1 + fraction) / 5,
           "detail": detail}
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"[{step}/5 {fraction:.0%}] {phase}: {detail}", flush=True)


def component_label(raw):
    raw = str(raw or "unknown")
    raw = ALIASES.get(raw.casefold(), raw)
    if raw in LABELS:
        return raw
    return "unknown"


def graph_features(g):
    nodes = g["nodes_raw"]
    coords = g["coords"]
    n = len(nodes)
    types = [component_label(node.get("component_type")) for node in nodes]
    type_index = {name: i for i, name in enumerate(LABELS)}
    onehot = np.zeros((n, len(LABELS) + 1), np.float32)
    onehot[:, -1] = 1
    for i, label in enumerate(types):
        onehot[i, -1] = float(label not in type_index)
        if label in type_index:
            onehot[i, type_index[label]] = 1
    lo = coords.min(axis=0) if n else np.zeros(2)
    span = np.maximum(coords.max(axis=0) - lo, .1) if n else np.ones(2)
    board_pos = (coords - lo) / span if n else coords
    refs = g["refs"]
    centers = np.zeros((n, 2), np.float32)
    counts = np.zeros(n, np.float32)
    indices_by_ref = defaultdict(list)
    for i, ref in enumerate(refs):
        indices_by_ref[ref].append(i)
    for ids in indices_by_ref.values():
        centers[ids] = coords[ids].mean(axis=0)
        counts[ids] = len(ids)
    rel = (coords - centers) / max(float(np.linalg.norm(span)), 1.)
    comp_pos = (centers - lo) / span if n else centers
    angles = np.radians(np.asarray([float(node.get("rotation_deg", 0) or 0) for node in nodes]))
    # Pad vector in the component's local frame, normalized by board diagonal.
    local_x = rel[:, 0] * np.cos(angles) + rel[:, 1] * np.sin(angles)
    local_y = -rel[:, 0] * np.sin(angles) + rel[:, 1] * np.cos(angles)
    tree = cKDTree(coords) if n else None
    density = np.zeros((n, 4), np.float32)
    for j, radius in enumerate((1., 2., 5., 10.)):
        if tree:
            density[:, j] = np.asarray([max(0, len(x) - 1) for x in tree.query_ball_point(coords, radius)], dtype=np.float32)
    base_node = np.column_stack([board_pos, comp_pos]).astype(np.float32)
    rich_node = np.column_stack([base_node, onehot, rel, local_x, local_y, np.sin(angles),
                                 np.cos(angles), np.log1p(counts), density]).astype(np.float32)
    g["label_names"] = types
    g["node_A"] = base_node
    g["node_B"] = np.column_stack([base_node, onehot]).astype(np.float32)
    g["node_C"] = rich_node
    g["onehot"] = onehot
    g["rel"] = rel
    g["local"] = np.column_stack([local_x, local_y]).astype(np.float32)
    g["counts"] = counts
    g["density"] = density


def edge_features(g, variant, indexes=None):
    if indexes is None:
        indexes = np.arange(len(g["pairs"]))
    pairs = g["pairs"][indexes]
    a, b = pairs[:, 0], pairs[:, 1]
    geom = g["edge_geom"][indexes]
    x = g[f"node_{variant}"]
    pieces = [geom, x[a] + x[b], np.abs(x[a] - x[b])]
    if variant == "C":
        delta = g["coords"][b] - g["coords"][a]
        dist = np.maximum(np.linalg.norm(delta, axis=1), 1e-6)
        unit = delta / dist[:, None]
        comp_delta = g["coords"][b] - g["coords"][a]
        aa = np.radians(np.asarray([float(g["nodes_raw"][i].get("rotation_deg", 0) or 0) for i in a]))
        ab = np.radians(np.asarray([float(g["nodes_raw"][i].get("rotation_deg", 0) or 0) for i in b]))
        # Pad-facing score is a weak feature: component orientation is only a proxy
        # because pad normals are unavailable in the pin-only source.
        face_a = np.column_stack([np.cos(aa), np.sin(aa)])
        face_b = np.column_stack([np.cos(ab), np.sin(ab)])
        facing = np.column_stack([np.sum(face_a * unit, axis=1), np.sum(face_b * -unit, axis=1),
                                  np.sum(face_a * face_b, axis=1)])
        pair_label = np.column_stack([g["onehot"][a] + g["onehot"][b],
                                      np.abs(g["onehot"][a] - g["onehot"][b])])
        pieces.extend([g["rel"][a] + g["rel"][b], np.abs(g["rel"][a] - g["rel"][b]),
                       g["local"][a] + g["local"][b], np.abs(g["local"][a] - g["local"][b]),
                       facing, np.log1p(g["counts"][a])[:, None], np.log1p(g["counts"][b])[:, None],
                       g["density"][a] + g["density"][b], pair_label])
    return np.concatenate(pieces, axis=1).astype(np.float32)


def main():
    from lightgbm import LGBMClassifier, log_evaluation
    from sklearn.metrics import average_precision_score, roc_auc_score
    update_progress("PCB 핀 데이터 로드", 1, .1, "PCB pin-only 데이터; 18개 라벨 정규화")
    raw = BASE.load_raw()
    audit = BASE.candidate_audit(raw, [(100., 32)])
    graphs = []
    for row in raw:
        g = BASE.prepare_graph(row, 100., 32)
        graph_features(g)
        graphs.append(g)
    train = [g for g in graphs if g["split"] == "train"]
    val = [g for g in graphs if g["split"] == "validation"]
    test = [g for g in graphs if g["split"] == "test"]
    update_progress("18개 라벨·핀 특징 구성", 2, 1, f"보드 {len(graphs)}; train/val/test={len(train)}/{len(val)}/{len(test)}")
    summary = {"taxonomy": list(LABELS), "internal_unknown_class": True,
      "label_normalization": {"oscillator": "clock", "unsupported_labels": "internal unknown/abstention"},
      "source_label_counts": {}, "source_only_classes_mapped_to_unknown": sorted(EXCLUDED_TYPES),
      "dataset": {"boards": len(graphs), "train": len(train), "validation": len(val), "test": len(test),
                  "candidate_radius_mm": 100, "candidate_k": 32, "candidate_audit": audit},
      "feature_sets": {
        "A": "normalized pad/component coordinates + pair distance/direction only",
        "B": "A + 18-class one-hot component labels and unordered component-pair interaction",
        "C": "B + component-relative/local-frame pad coordinates, pin-count, local density, rotation/facing proxies"},
      "model": "LightGBM; same training sampler and same validation-selected mutual Top-K transitive clustering for A/B/C",
      "caveat": "Face direction uses component rotation as a proxy; true pad normals and photo-derived traces are unavailable."}
    from collections import Counter
    summary["source_label_counts"] = dict(Counter(n.get("component_type", "unknown") for g in graphs for n in g["nodes_raw"]))
    all_scores = {}
    for model_idx, variant in enumerate(("A", "B", "C"), start=1):
        update_progress(f"실험 {variant} 학습", 3, (model_idx - 1) / 3, f"같은 후보 그래프·LightGBM; feature set {variant}")
        xs, ys, ws = [], [], []
        for g in train:
            idx, w = BASE.sample_training(g, 42)
            if len(idx):
                xs.append(edge_features(g, variant, idx)); ys.append(g["y"][idx]); ws.append(w)
        X, y, w = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
        model = LGBMClassifier(n_estimators=350, learning_rate=.04, num_leaves=31, subsample=.85,
            colsample_bytree=.85, reg_lambda=1., random_state=42, n_jobs=6, verbosity=-1)
        model.fit(X, y, sample_weight=w, callbacks=[log_evaluation(period=0)])
        def predict(group):
            return {g["graph_id"]: model.predict_proba(edge_features(g, variant))[:, 1] if len(g["pairs"])
                    else np.zeros(0, dtype=np.float32) for g in group}
        vs, ts = predict(val), predict(test)
        calibrated = R2.calibrate_cluster(val, vs, "mutual_topk")
        test_cluster = R2.cluster_metrics(test, ts, calibrated["threshold"], "mutual_topk", calibrated["topk"])
        def metrics(group, scores):
            yy = np.concatenate([g["y"] for g in group]); ss = np.concatenate([scores[g["graph_id"]] for g in group])
            return {"candidate_pr_auc": float(average_precision_score(yy, ss)),
                    "candidate_roc_auc": float(roc_auc_score(yy, ss)),
                    **BASE.truth_degree_metrics(group, scores, 5)}
        all_scores[variant] = {"val": vs, "test": ts}
        summary.setdefault("experiments", {})[variant] = {"training_pairs": int(len(y)),
            "validation_candidate_metrics": metrics(val, vs), "test_candidate_metrics": metrics(test, ts),
            "validation_selected_clustering": calibrated["best_validation"],
            "test_clustering": test_cluster}
        model.booster_.save_model(str(BENCH / "models" / f"lightgbm_18label_{variant.lower()}.txt"))
        update_progress(f"실험 {variant} 학습", 3, model_idx / 3, f"test PR-AUC={summary['experiments'][variant]['test_candidate_metrics']['candidate_pr_auc']:.4f}")
    # List the highest-confidence proposed links on held-out boards for inspection.
    proposed = []
    for g in sorted(test, key=lambda z: z["graph_id"]):
        scores = all_scores["C"]["test"][g["graph_id"]]
        order = np.argsort(-scores)[:10]
        for ei in order:
            a, b = map(int, g["pairs"][ei])
            proposed.append({"board_id": g["graph_id"], "pin_a": g["nodes_raw"][a]["id"],
              "component_a": g["refs"][a], "label_a": g["label_names"][a],
              "pin_b": g["nodes_raw"][b]["id"], "component_b": g["refs"][b],
              "label_b": g["label_names"][b], "confidence": float(scores[ei]),
              "same_net_truth": bool(g["y"][ei])})
    summary["top_10_candidates_per_test_board_from_C"] = proposed
    summary["interpretation"] = "These are same-net candidate probabilities. They do not mean direct physical copper adjacency; review high-confidence links before treating them as a netlist."
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "models").mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    update_progress("완료", 5, 1, str(OUT))
    print(json.dumps({"experiments": summary["experiments"], "output": str(OUT)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
