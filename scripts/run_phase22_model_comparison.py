#!/usr/bin/env python3
"""Validation-only, matched-feature LightGBM/GNN comparison for Phase 22."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from lightgbm import LGBMClassifier
from sklearn.metrics import (average_precision_score, precision_recall_curve,
                             roc_auc_score)
from sklearn.utils.class_weight import compute_sample_weight
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_connectivity_features import (  # noqa: E402
    ACLPGNN, CLASS_PAIR_LABELS, FEATURE_RUNS, augment_graph, combine,
)

DEFAULT_GRAPHS = ROOT / "data/external/connectivity-dataset-v1/extracted/pin_candidate_graphs.jsonl"
ALL_FLAGS = tuple(dict.fromkeys(flag for flags in FEATURE_RUNS.values() for flag in flags))


def edge_matrix(x, pairs, edge_attr, pair_ids, flags):
    parts = [x[pairs[:, 0]], x[pairs[:, 1]], edge_attr]
    if "component_type_pair" in flags:
        parts.append(pair_ids[:, None].astype(np.float32))
    return np.concatenate(parts, axis=1)


def sampling_indices(y: np.ndarray, sample_id: str, seed: int, ratio: int,
                     min_neg: int, max_neg: int) -> np.ndarray:
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    count = min(len(neg), max(min_neg, len(pos) * ratio), max_neg)
    if count < len(neg):
        material = f"{seed}:{sample_id}".encode()
        graph_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "little")
        neg = np.random.default_rng(graph_seed).choice(neg, count, replace=False)
    return np.sort(np.concatenate((pos, neg))).astype(np.int64)


def load_training(path: Path, flags: tuple[str, ...], seed: int,
                  ratio: int, min_neg: int, max_neg: int, build_lgbm: bool = True):
    rows, lgbm_x, lgbm_y = [], [], []
    with path.open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            g = json.loads(line)
            if g["split"] != "train":
                continue
            row = augment_graph(g, flags)
            x, pairs, edge_attr, y, pair_ids = row
            keep = sampling_indices(y, g["sample_id"], seed, ratio, min_neg, max_neg)
            # Both learners optimize the same deterministic positive/negative edge set.
            # GNN still message-passes over the full candidate graph.
            rows.append((g, *row, keep))
            if build_lgbm and len(keep):
                features = edge_matrix(x, pairs[keep], edge_attr[keep], pair_ids[keep], flags)
                lgbm_x.append(features)
                lgbm_y.append(y[keep])
            if n % 500 == 0:
                print(f"  train scan {n}: selected {len(rows)}", flush=True)
    if len(rows) != 3920:
        raise RuntimeError(f"Expected 3920 train graphs, found {len(rows)}")
    if not build_lgbm:
        return rows, None, None
    return rows, np.concatenate(lgbm_x), np.concatenate(lgbm_y)


def project_row(row, flags: tuple[str, ...]):
    """Select an ablation's columns from a row precomputed with all features."""
    g, x, pairs, attrs, y, pair_ids, *tail = row
    base_node = list(range(30))
    extra_node = []
    if "relative_geometry" in flags:
        extra_node.extend(range(30, 32))
    if "pin_name_category" in flags:
        extra_node.extend(range(32, 44))
    if "power_ground" in flags:
        extra_node.extend(range(44, 46))
    if "drop_pin_name_derived" in flags:
        base_node.remove(29)
    node_cols = base_node + extra_node

    edge_cols = list(range(6))
    if "relative_geometry" in flags:
        edge_cols.extend(range(6, 8))
    if "neighbor_geometry" in flags:
        edge_cols.extend(range(8, 9))
    if "pin_facing" in flags:
        edge_cols.extend(range(9, 13))
    if "pitch_normalized_distance" in flags:
        edge_cols.extend(range(13, 16))
    selected_pair = pair_ids if "component_type_pair" in flags else np.zeros_like(pair_ids)
    return (g, x[:, node_cols], pairs, attrs[:, edge_cols], y, selected_pair, *tail)


def evaluate_pin_ranking(graph_rows, score_rows) -> dict[str, float | int | None]:
    labels_all, scores_all = [], []
    candidate_tp = candidate_total = truth_total = same_ref_truth = 0
    macro_candidate_recalls = []
    e2e_hits = {1: 0, 3: 0, 5: 0}
    pin_hits = {1: 0, 3: 0, 5: 0}
    pin_slots = {1: 0, 3: 0, 5: 0}
    pin_precisions = {k: [] for k in (1, 3, 5)}

    for (g, x, pairs, edge_attr, y, pair_ids), scores in zip(graph_rows, score_rows):
        labels_all.append(y)
        scores_all.append(scores)
        nodes = g["nodes"]
        edge_by_pin: list[list[tuple[float, int, int]]] = [[] for _ in nodes]
        candidate = set()
        for (a, b), score, label in zip(pairs, scores, y):
            a, b = int(a), int(b)
            key = (min(a, b), max(a, b))
            candidate.add(key)
            edge_by_pin[a].append((float(score), b, int(label)))
            edge_by_pin[b].append((float(score), a, int(label)))
        truth = {tuple(sorted(map(int, e))) for e in g.get("truth_edges", [])}
        valid_truth = {e for e in truth if nodes[e[0]].get("ref") != nodes[e[1]].get("ref")}
        same_ref_truth += len(truth) - len(valid_truth)
        hits = len(valid_truth & candidate)
        candidate_tp += hits
        candidate_total += len(y)
        truth_total += len(valid_truth)
        if valid_truth:
            macro_candidate_recalls.append(hits / len(valid_truth))

        for k in (1, 3, 5):
            selected_pairs = set()
            for incident in edge_by_pin:
                if not incident:
                    continue
                ranked = sorted(incident, key=lambda t: (-t[0], t[1]))[:k]
                slots = len(ranked)
                hits_pin = sum(item[2] for item in ranked)
                pin_hits[k] += hits_pin
                pin_slots[k] += slots
                pin_precisions[k].append(hits_pin / slots)
            # Count each recovered undirected ground-truth edge once if either endpoint ranked it.
            selected_pairs = set()
            for pin, incident in enumerate(edge_by_pin):
                ranked = sorted(incident, key=lambda t: (-t[0], t[1]))[:k]
                for _, neighbor, label in ranked:
                    if label:
                        selected_pairs.add(tuple(sorted((pin, neighbor))))
            e2e_hits[k] += len(selected_pairs & valid_truth)

    labels = np.concatenate(labels_all)
    scores = np.concatenate(scores_all)
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    if len(thresholds):
        f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
        ix = int(np.argmax(f1))
        threshold = float(thresholds[ix])
        selected = scores >= threshold
        tp = int(np.sum(labels[selected] == 1))
        p_at_threshold = tp / max(int(selected.sum()), 1)
        r_at_threshold = tp / max(int(labels.sum()), 1)
    else:
        threshold, p_at_threshold, r_at_threshold = 1.0, 0.0, 0.0
    out: dict[str, Any] = {
        "candidate_edges": int(len(labels)),
        "candidate_positive_rate": float(labels.mean()),
        "candidate_pr_auc": float(average_precision_score(labels, scores)),
        "candidate_roc_auc": float(roc_auc_score(labels, scores)) if len(np.unique(labels)) > 1 else None,
        "validation_f1_threshold": threshold,
        "validation_precision_at_selected_threshold": p_at_threshold,
        "validation_recall_at_selected_threshold": r_at_threshold,
        "candidate_recall_micro_excluding_same_ref": candidate_tp / max(truth_total, 1),
        "candidate_recall_macro_excluding_same_ref": float(np.mean(macro_candidate_recalls)) if macro_candidate_recalls else None,
        "same_ref_truth_pairs_excluded": same_ref_truth,
        "truth_pairs_excluding_same_ref": truth_total,
        "candidates_per_pin_mean": 2 * candidate_total / max(sum(len(g["nodes"]) for g, *_ in graph_rows), 1),
        "probabilities_calibrated": False,
    }
    for k in (1, 3, 5):
        out[f"pin_precision_at_{k}_micro"] = pin_hits[k] / max(pin_slots[k], 1)
        out[f"pin_precision_at_{k}_macro"] = float(np.mean(pin_precisions[k])) if pin_precisions[k] else None
        out[f"end_to_end_recall_at_{k}_micro"] = e2e_hits[k] / max(truth_total, 1)
    return out


def load_eval(path: Path, split: str, flags: tuple[str, ...]):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            g = json.loads(line)
            if g["split"] == split:
                rows.append((g, *augment_graph(g, flags)))
            if n % 500 == 0:
                print(f"  {split} scan {n}: selected {len(rows)}", flush=True)
    return rows


def train_gnn(rows, seed: int, device: torch.device, epochs: int, batch_size: int,
              flags: tuple[str, ...] = ALL_FLAGS):
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(1)
    node_dim, edge_dim = rows[0][1].shape[1], rows[0][3].shape[1]
    use_pair = "component_type_pair" in flags
    model = ACLPGNN(node_dim, edge_dim, use_pair).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
    pos_count = sum(int(np.sum(r[4][r[6]])) for r in rows if len(r[6]))
    loss_count = sum(len(r[6]) for r in rows)
    pos_weight = torch.tensor([(loss_count - pos_count) / max(pos_count, 1)], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    steps = 0
    for epoch in range(epochs):
        order = np.random.default_rng(seed + epoch).permutation(len(rows))
        for start in range(0, len(order), batch_size):
            batch = [rows[int(i)] for i in order[start:start + batch_size]]
            joined = combine([r[1:6] for r in batch])
            x, pairs, attrs, y, pids = joined
            offsets = np.cumsum([0] + [len(r[1]) for r in batch[:-1]])
            keep = np.concatenate([r[6] + offsets[i] for i, r in enumerate(batch)])
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(pairs, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            ty = torch.as_tensor(y[keep], dtype=torch.float32, device=device)
            tp = torch.as_tensor(pids, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(tx, te, ta, tp)[torch.as_tensor(keep, dtype=torch.long, device=device)]
            loss = loss_fn(logits, ty)
            loss.backward(); optimizer.step(); steps += 1
        if epoch == 0 or (epoch + 1) % 5 == 0:
            print(f"  GNN seed={seed} epoch={epoch + 1}/{epochs} steps={steps} loss={float(loss.detach().cpu()):.4f}", flush=True)
    model.eval()
    return model, {"optimizer_steps": steps, "loss_edges": loss_count}


def score_gnn(model, rows, device):
    outputs = []
    model.eval()
    with torch.no_grad():
        for g, x, pairs, attrs, y, pair_ids in rows:
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(pairs, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
            outputs.append(torch.sigmoid(model(tx, te, ta, tp)).cpu().numpy())
    return outputs


def train_lgbm(x, y, seed: int, trees: int, flags: tuple[str, ...]):
    weights = compute_sample_weight("balanced", y)
    pair_col = x.shape[1] - 1
    model = LGBMClassifier(n_estimators=trees, learning_rate=0.04, num_leaves=31,
                           max_depth=-1, subsample=0.85, colsample_bytree=0.85,
                           reg_lambda=1.0, random_state=seed, n_jobs=1, verbosity=-1)
    fit_kwargs = {"sample_weight": weights}
    if "component_type_pair" in flags:
        fit_kwargs["categorical_feature"] = [pair_col]
    model.fit(x, y, **fit_kwargs)
    return model


def score_lgbm(model, rows, flags):
    scores = []
    for g, x, pairs, attrs, y, pids in rows:
        if not len(y):
            scores.append(np.empty(0, dtype=np.float64))
            continue
        features = edge_matrix(x, pairs, attrs, pids, flags)
        scores.append(model.predict_proba(features)[:, 1])
    return scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPHS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp01_model_comparison.json")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--trees", type=int, default=250)
    parser.add_argument("--negative-ratio", type=int, default=20)
    parser.add_argument("--max-negatives-per-graph", type=int, default=1000)
    parser.add_argument("--models", nargs="+", choices=("lightgbm", "gnn"), default=["lightgbm", "gnn"])
    parser.add_argument("--experiment-label", default="E1 matched-feature model comparison")
    parser.add_argument("--feature-set", choices=("baseline", "all_features"), default="all_features")
    parser.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    args = parser.parse_args()
    device = torch.device(args.device)
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS is unavailable")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")
    flags = ALL_FLAGS if args.feature_set == "all_features" else ()
    result = {"metadata": {"experiment": args.experiment_label,
                           "feature_set": args.feature_set,
                           "features": list(flags), "training_graphs": 3920,
                           "validation_graphs": 515, "test_accessed": False,
                           "device": str(device), "gnn_epochs": args.epochs,
                           "gnn_batch_size": args.batch_size, "lightgbm_trees": args.trees,
                           "loss_edge_policy": "same sampled candidate edges for both models; GNN message-passes over all candidates",
                           "negative_ratio": args.negative_ratio,
                           "max_negatives_per_graph": args.max_negatives_per_graph,
                           "threshold_policy": "validation-only F1 maximization; scores are not calibrated probabilities"},
              "runs": []}
    for seed in args.seeds:
        print(f"\n=== E1 seed {seed}: preparing shared features ===", flush=True)
        train_rows, xtr, ytr = load_training(args.graphs, flags, seed, args.negative_ratio, 16,
                                             args.max_negatives_per_graph,
                                             build_lgbm="lightgbm" in args.models)
        val_rows = load_eval(args.graphs, "validation", flags)
        if len(val_rows) != 515:
            raise RuntimeError(f"Expected 515 validation graphs, got {len(val_rows)}")
        print(f"  shared loss set: {len(ytr):,} edges ({int(ytr.sum()):,} positive)", flush=True)
        run = {"seed": seed}
        if "lightgbm" in args.models:
            lgbm = train_lgbm(xtr, ytr, seed, args.trees, flags)
            run["lightgbm"] = evaluate_pin_ranking(val_rows, score_lgbm(lgbm, val_rows, flags))
            del lgbm, xtr, ytr
        if "gnn" in args.models:
            model, fit_info = train_gnn(train_rows, seed, device, args.epochs, args.batch_size, flags)
            run["gnn"] = {**evaluate_pin_ranking(val_rows, score_gnn(model, val_rows, device)), **fit_info}
            del model
            if device.type == "mps":
                torch.mps.empty_cache()
        result["runs"].append(run)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("  validation AP: " + "; ".join(
            f"{model_name}={run[model_name]['candidate_pr_auc']:.4f}"
            for model_name in args.models), flush=True)
        del train_rows, val_rows
        if device.type == "mps":
            torch.mps.empty_cache()
    print(f"Saved validation-only E1 results to {args.output}", flush=True)


if __name__ == "__main__":
    main()
