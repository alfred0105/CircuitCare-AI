#!/usr/bin/env python3
"""Run fixed-size GNN feature ablations on the released connectivity graphs."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from scipy.spatial import cKDTree
from sklearn.metrics import (average_precision_score, f1_score, precision_score,
                             recall_score, roc_auc_score)
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_connectivity_link_prediction import LABELS, edge_features

DEFAULT_GRAPHS = ROOT / "data/external/connectivity-dataset-v1/extracted/pin_candidate_graphs.jsonl"
DEFAULT_OUTPUT = ROOT / "data/benchmarks/phase22_connectivity/feature_experiments_mps_b256.json"
DEFAULT_MODEL_ROOT = ROOT / "models/phase22_connectivity/feature_experiments_mps_b256"

FEATURES = (
    "neighbor_geometry",
    "component_type_pair",
    "pin_facing",
    "pin_name_category",
    "power_ground",
    "pitch_normalized_distance",
)
FEATURE_RUNS = {name: (name,) for name in FEATURES}
FEATURE_RUNS["neighbor_geometry"] = ("neighbor_geometry", "relative_geometry")
FEATURE_RUNS["all_features"] = tuple(dict.fromkeys(flag for name in FEATURES for flag in FEATURE_RUNS[name]))

PIN_NAME_GROUPS = (
    "power", "ground", "input", "output", "clock", "reset", "enable",
    "data_bus", "analog", "interrupt", "chip_select", "other",
)
PIN_NAME_INDEX = {name: i for i, name in enumerate(PIN_NAME_GROUPS)}
CLASS_PAIR_LABELS = [(a, b) for i, a in enumerate(LABELS) for b in LABELS[i:]]
CLASS_PAIR_INDEX = {pair: i for i, pair in enumerate(CLASS_PAIR_LABELS)}


def pin_name_group(raw: Any) -> str:
    name = str(raw or "").strip().upper().replace("#", "")
    compact = "".join(ch for ch in name if ch.isalnum() or ch in "_+-")
    tokens = {token for token in compact.replace("+", "_").replace("-", "_").split("_") if token}
    if any(x in compact for x in ("GND", "GROUND", "AGND", "DGND", "PGND")) or compact == "0V":
        return "ground"
    if any(x in compact for x in ("VCC", "VDD", "VBAT", "VSYS", "VUSB", "3V3", "5V")) or compact in {"VIN", "VREF", "POWER"}:
        return "power"
    if compact in {"IN", "INPUT", "AIN", "DIN", "RX", "RXD"} or any(x in tokens for x in ("INPUT", "RX")):
        return "input"
    if compact in {"OUT", "OUTPUT", "AOUT", "DOUT", "TX", "TXD"} or any(x in tokens for x in ("OUTPUT", "TX")):
        return "output"
    if any(x in compact for x in ("CLOCK", "CLK", "XTAL", "SCK", "SCLK")):
        return "clock"
    if any(x in compact for x in ("RESET", "RST")):
        return "reset"
    if any(x in compact for x in ("ENABLE", "EN_", "_EN", "CE")) or compact in {"EN", "OE"}:
        return "enable"
    if any(x in compact for x in ("SDA", "SCL", "MOSI", "MISO", "UART", "DATA", "D0", "D1")):
        return "data_bus"
    if any(x in compact for x in ("ANALOG", "ADC", "DAC", "AIN", "AOUT")):
        return "analog"
    if any(x in compact for x in ("IRQ", "INTERRUPT")) or compact in {"INT", "IRQ"}:
        return "interrupt"
    if any(x in compact for x in ("CHIPSELECT", "CHIP_SEL", "CS_")) or compact in {"CS", "NCS"}:
        return "chip_select"
    return "other"


def component_geometry(graph: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, float], np.ndarray, np.ndarray, float]:
    nodes = graph["nodes"]
    by_ref: dict[str, list[int]] = defaultdict(list)
    xy = np.asarray([[float(n.get("x", 0.0)), float(n.get("y", 0.0))] for n in nodes], dtype=np.float32)
    for i, node in enumerate(nodes):
        by_ref[str(node.get("ref", i))].append(i)
    centers: dict[str, np.ndarray] = {}
    pitches: dict[str, float] = {}
    pitch_values = []
    for ref, indices in by_ref.items():
        points = xy[indices]
        centers[ref] = points.mean(axis=0)
        if len(points) < 2:
            continue
        distances, _ = cKDTree(points).query(points, k=2)
        nearest = distances[:, 1]
        nearest = nearest[np.isfinite(nearest) & (nearest > 1e-4)]
        if len(nearest):
            pitch = float(np.median(nearest))
            pitches[ref] = pitch
            pitch_values.append(pitch)
    graph_pitch = float(np.median(pitch_values)) if pitch_values else 1.0
    min_pitch = max(graph_pitch * 0.1, 0.1)
    return centers, pitches, xy, np.asarray([PIN_NAME_INDEX[pin_name_group(n.get("pin_name"))] for n in nodes]), min_pitch


def augment_graph(graph: dict[str, Any], flags: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x, pairs, edge_attr, y = edge_features(graph)
    if pairs.ndim == 1:
        pairs = pairs.reshape((-1, 2))
    if edge_attr.ndim == 1:
        edge_attr = edge_attr.reshape((len(graph["edges"]), 6))
    nodes = graph["nodes"]
    edges = graph["edges"]
    centers, pitches, xy, name_categories, min_pitch = component_geometry(graph)
    refs = [str(n.get("ref", i)) for i, n in enumerate(nodes)]
    classes = [str(n.get("class", "")) for n in nodes]
    pair_ids = np.zeros(len(edges), dtype=np.int64)
    extra_nodes: list[np.ndarray] = []
    extra_edges: list[np.ndarray] = []

    if "relative_geometry" in flags:
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        board_scale = max(float(np.linalg.norm(hi - lo)), 1.0)
        center = (lo + hi) / 2.0
        extra_nodes.append((xy - center) / board_scale)
        dxy = np.asarray([[float(e.get("dx", 0.0)), float(e.get("dy", 0.0))] for e in edges], dtype=np.float32)
        dxy = dxy.reshape((-1, 2))
        dist = np.asarray([float(e.get("distance", 0.0)) for e in edges], dtype=np.float32)
        unit = dxy / np.maximum(dist[:, None], 1e-6)
        extra_edges.append(unit)

    if "neighbor_geometry" in flags:
        rank = np.asarray([float(e.get("rank_i", 97.0)) for e in edges], dtype=np.float32)
        rank_norm = np.log1p(np.minimum(rank, 96.0)) / math.log1p(96.0)
        extra_edges.append(rank_norm[:, None])

    if "component_type_pair" in flags:
        for j, edge in enumerate(edges):
            a, b = classes[int(edge["source"])], classes[int(edge["target"])]
            pair = tuple(sorted((a, b), key=lambda value: LABELS.index(value) if value in LABELS else len(LABELS)))
            pair_ids[j] = CLASS_PAIR_INDEX.get(pair, 0)

    if "pin_facing" in flags:
        directions = np.zeros_like(xy)
        for i, ref in enumerate(refs):
            radial = xy[i] - centers[ref]
            norm = float(np.linalg.norm(radial))
            if norm > 1e-6:
                directions[i] = radial / norm
        values = np.zeros((len(edges), 4), dtype=np.float32)
        for j, edge in enumerate(edges):
            a, b = int(edge["source"]), int(edge["target"])
            v = xy[b] - xy[a]
            norm = float(np.linalg.norm(v))
            if norm <= 1e-6:
                continue
            unit = v / norm
            face_a = float(np.dot(directions[a], unit))
            face_b = float(np.dot(directions[b], -unit))
            values[j] = (face_a, face_b, min(face_a, face_b), face_a * face_b)
        extra_edges.append(values)

    if "pin_name_category" in flags:
        name_onehot = np.eye(len(PIN_NAME_GROUPS), dtype=np.float32)[name_categories]
        extra_nodes.append(name_onehot)

    if "power_ground" in flags:
        power = np.asarray([name_categories[i] == PIN_NAME_INDEX["power"] or
                            str(nodes[i].get("electrical", "")).casefold() in {"power_in", "power_out"}
                            for i in range(len(nodes))], dtype=np.float32)
        ground = np.asarray([name_categories[i] == PIN_NAME_INDEX["ground"] for i in range(len(nodes))], dtype=np.float32)
        extra_nodes.append(np.stack((power, ground), axis=1))

    if "pitch_normalized_distance" in flags:
        values = np.zeros((len(edges), 3), dtype=np.float32)
        for j, edge in enumerate(edges):
            a, b = int(edge["source"]), int(edge["target"])
            ref_a, ref_b = refs[a], refs[b]
            pitch_a = max(pitches.get(ref_a, min_pitch), min_pitch)
            pitch_b = max(pitches.get(ref_b, min_pitch), min_pitch)
            scale = max(math.sqrt(pitch_a * pitch_b), min_pitch)
            center_distance = float(np.linalg.norm(centers[ref_a] - centers[ref_b]))
            pin_distance = float(edge.get("distance", 0.0))
            values[j] = (math.log1p(center_distance), math.log1p(center_distance / scale),
                         math.log1p(pin_distance / scale))
        extra_edges.append(values)

    if extra_nodes:
        x = np.concatenate((x, *extra_nodes), axis=1).astype(np.float32, copy=False)
    if extra_edges:
        edge_attr = np.concatenate((edge_attr, *extra_edges), axis=1).astype(np.float32, copy=False)
    return x, pairs, edge_attr, y, pair_ids


class ACLPGNN(nn.Module):
    def __init__(self, node_dim: int, edge_dim: int, use_pair_embedding: bool, hidden: int = 48):
        super().__init__()
        self.use_pair_embedding = use_pair_embedding
        pair_dim = 8 if use_pair_embedding else 0
        self.encoder = nn.Linear(node_dim, hidden)
        self.msg1 = nn.Linear(hidden * 2, hidden)
        self.msg2 = nn.Linear(hidden * 2, hidden)
        self.edge_head = nn.Sequential(nn.Linear(hidden * 2 + edge_dim + pair_dim, hidden), nn.ReLU(),
                                       nn.Dropout(0.15), nn.Linear(hidden, 1))
        self.pair_embedding = nn.Embedding(len(CLASS_PAIR_LABELS), pair_dim) if use_pair_embedding else None

    def forward(self, x: torch.Tensor, edges: torch.Tensor, edge_attr: torch.Tensor,
                pair_ids: torch.Tensor) -> torch.Tensor:
        h = torch.relu(self.encoder(x))
        for layer in (self.msg1, self.msg2):
            src, dst = edges[:, 0], edges[:, 1]
            agg = torch.zeros_like(h)
            agg.index_add_(0, dst, h[src])
            agg.index_add_(0, src, h[dst])
            deg = torch.zeros((h.shape[0], 1), dtype=h.dtype, device=h.device)
            ones = torch.ones((len(src), 1), dtype=h.dtype, device=h.device)
            deg.index_add_(0, dst, ones)
            deg.index_add_(0, src, ones)
            h = torch.relu(layer(torch.cat([h, agg / deg.clamp_min(1)], dim=1)))
        pieces = [h[edges[:, 0]], h[edges[:, 1]], edge_attr]
        if self.pair_embedding is not None:
            pieces.append(self.pair_embedding(pair_ids))
        return self.edge_head(torch.cat(pieces, dim=1)).squeeze(-1)


def combine(rows: list[tuple[np.ndarray, ...]]) -> tuple[np.ndarray, ...]:
    node_rows, edge_rows, attr_rows, label_rows, pair_rows = [], [], [], [], []
    offset = 0
    for x, edges, attrs, labels, pair_ids in rows:
        node_rows.append(x)
        edge_rows.append(edges + offset)
        attr_rows.append(attrs)
        label_rows.append(labels)
        pair_rows.append(pair_ids)
        offset += len(x)
    return (np.concatenate(node_rows), np.concatenate(edge_rows), np.concatenate(attr_rows),
            np.concatenate(label_rows), np.concatenate(pair_rows))


def get_metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    predicted = (scores >= 0.5).astype(np.int8)
    return {
        "candidate_edges": int(len(labels)),
        "positive_edges": int(labels.sum()),
        "positive_rate": float(labels.mean()),
        "pr_auc": float(average_precision_score(labels, scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "f1_at_0_5": float(f1_score(labels, predicted, zero_division=0)),
        "precision_at_0_5": float(precision_score(labels, predicted, zero_division=0)),
        "recall_at_0_5": float(recall_score(labels, predicted, zero_division=0)),
    }


def load_split_rows(path: Path, flags: tuple[str, ...], split: str) -> list[tuple[np.ndarray, ...]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for i, line in enumerate(stream, 1):
            graph = json.loads(line)
            if graph["split"] == split:
                rows.append(augment_graph(graph, flags))
            if i % 500 == 0:
                print(f"  {split}: scanned {i} graph records; selected={len(rows)}", flush=True)
    return rows


def run_one(name: str, flags: tuple[str, ...], args: argparse.Namespace, device: torch.device) -> dict[str, Any]:
    print(f"\n=== feature run: {name} ({', '.join(flags) if flags else 'baseline'}) ===", flush=True)
    train_rows = load_split_rows(Path(args.graphs), flags, "train")
    if not train_rows:
        raise SystemExit("Expected a non-empty train split")
    if len(train_rows) != args.train_graphs:
        raise SystemExit(f"Expected {args.train_graphs} train graphs, found {len(train_rows)}")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(args.torch_threads)
    use_pair = "component_type_pair" in flags
    node_dim, edge_dim = train_rows[0][0].shape[1], train_rows[0][2].shape[1]
    model = ACLPGNN(node_dim, edge_dim, use_pair).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    positives = sum(int(row[3].sum()) for row in train_rows)
    edges_total = sum(len(row[3]) for row in train_rows)
    pos_weight = torch.tensor([(edges_total - positives) / max(positives, 1)], dtype=torch.float32, device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    for epoch in range(args.epochs):
        order = np.random.default_rng(args.seed + epoch).permutation(len(train_rows))
        total_loss, seen = 0.0, 0
        for start in range(0, len(order), args.graph_batch_size):
            batch = [train_rows[int(i)] for i in order[start:start + args.graph_batch_size]]
            x, pairs, attrs, y, pair_ids = combine(batch)
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(pairs, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            ty = torch.as_tensor(y, dtype=torch.float32, device=device)
            tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(tx, te, ta, tp), ty)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu()) * len(y)
            seen += len(y)
        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"  epoch {epoch + 1}/{args.epochs} loss={total_loss / max(seen, 1):.4f} device={device}", flush=True)

    def score_split(split: str) -> dict[str, Any]:
        labels, scores = [], []
        model.eval()
        batch = []
        seen = 0
        with Path(args.graphs).open(encoding="utf-8") as stream, torch.no_grad():
            for line in stream:
                graph = json.loads(line)
                if graph["split"] != split:
                    continue
                batch.append(augment_graph(graph, flags))
                if len(batch) < args.graph_batch_size:
                    continue
                x, pairs, attrs, y, pair_ids = combine(batch)
                tx = torch.as_tensor(x, dtype=torch.float32, device=device)
                te = torch.as_tensor(pairs, dtype=torch.long, device=device)
                ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
                tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
                values = torch.sigmoid(model(tx, te, ta, tp)).cpu().numpy()
                labels.append(y)
                scores.append(values)
                seen += len(batch)
                print(f"  {split}: scored {seen} graphs", flush=True)
                del x, pairs, attrs, y, pair_ids, tx, te, ta, tp, values
                batch.clear()
            if batch:
                x, pairs, attrs, y, pair_ids = combine(batch)
                tx = torch.as_tensor(x, dtype=torch.float32, device=device)
                te = torch.as_tensor(pairs, dtype=torch.long, device=device)
                ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
                tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
                values = torch.sigmoid(model(tx, te, ta, tp)).cpu().numpy()
                labels.append(y)
                scores.append(values)
                seen += len(batch)
                print(f"  {split}: scored {seen} graphs", flush=True)
        return get_metrics(np.concatenate(labels), np.concatenate(scores))

    del train_rows
    del x, pairs, attrs, y, pair_ids, tx, te, ta, ty, tp, loss, batch
    import gc
    gc.collect()
    if device.type == "mps":
        torch.mps.empty_cache()
    validation = score_split("validation")
    test = score_split("test")
    model_dir = Path(args.model_root) / name
    model_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "node_dim": node_dim, "edge_dim": edge_dim, "features": list(flags),
                "seed": args.seed, "epochs": args.epochs, "graph_batch_size": args.graph_batch_size,
                "device": str(device)}, model_dir / "gnn.pt")
    del model, optimizer
    torch.mps.empty_cache() if device.type == "mps" else None
    return {"features": list(flags), "device": str(device), "training_graphs": args.train_graphs,
            "graph_batch_size": args.graph_batch_size, "epochs": args.epochs,
            "validation": validation, "test": test}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", default=str(DEFAULT_GRAPHS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--model-root", default=str(DEFAULT_MODEL_ROOT))
    parser.add_argument("--runs", nargs="+", choices=tuple(FEATURE_RUNS), default=list(FEATURE_RUNS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--graph-batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--torch-threads", type=int, default=1)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--train-graphs", type=int, default=3920)
    args = parser.parse_args()
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else
                              "mps" if torch.backends.mps.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS was requested but is unavailable")
    print(f"feature experiments use {device}; graph_batch_size={args.graph_batch_size}; seed={args.seed}", flush=True)
    result_path = Path(args.output)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"experiment": {"seed": args.seed, "device": str(device), "graph_batch_size": args.graph_batch_size,
                              "epochs": args.epochs, "training_graphs": args.train_graphs,
                              "project_grouped_split": True,
                              "candidate_recall_test_legacy_macro_including_same_component": 0.8065484913870787,
                              "candidate_recall_test_macro_excluding_same_component": 0.8714459120547977,
                              "candidate_recall_test_micro_excluding_same_component": 0.6837643021452281,
                              "unreachable_same_component_truth_pairs_test": 14659,
                              "notes": ["Each feature variant changes only the listed feature group.",
                                        "Candidate-only PR-AUC excludes candidate-generation misses. Same-component truth pairs are excluded from corrected candidate-recall metrics because candidate generation forbids them.",
                                        "Pin facing is estimated from pin position relative to the component pin centroid; exact KiCad pin orientation is not present in the released graph file."]},
              "runs": []}
    for run_name in args.runs:
        flags = FEATURE_RUNS[run_name]
        result = run_one(run_name, flags, args, device)
        report["runs"].append(result)
        result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"completed {run_name}: validation PR-AUC={result['validation']['pr_auc']:.4f}; "
              f"test PR-AUC={result['test']['pr_auc']:.4f}", flush=True)
    print(f"Feature experiment report saved to {result_path}", flush=True)


if __name__ == "__main__":
    main()
