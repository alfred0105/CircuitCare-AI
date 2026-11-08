#!/usr/bin/env python3
"""Compare mean, edge-gated, and edge-MLP GNNs on validation-only data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_connectivity_features import ACLPGNN, CLASS_PAIR_LABELS, augment_graph, combine  # noqa: E402
from run_phase22_model_comparison import (  # noqa: E402
    ALL_FLAGS, evaluate_pin_ranking, load_eval, load_training, score_gnn,
)

DEFAULT_GRAPHS = ROOT / "data/external/connectivity-dataset-v1/derived/phase22_hybrid/H2_hybrid.jsonl"


def reverse_edge_attr(edge_attr: torch.Tensor) -> torch.Tensor:
    rev = edge_attr.clone()
    if rev.shape[1] >= 3:
        rev[:, 1:3] = -rev[:, 1:3]
    if rev.shape[1] >= 8:
        rev[:, 6:8] = -rev[:, 6:8]
    if rev.shape[1] >= 13:
        first, second = rev[:, 9].clone(), rev[:, 10].clone()
        rev[:, 9], rev[:, 10] = second, first
    return rev


class EdgeAwareGNN(nn.Module):
    def __init__(self, node_dim: int, edge_dim: int, architecture: str, hidden: int = 48,
                 layers: int = 2, dropout: float = 0.15):
        super().__init__()
        self.architecture = architecture
        self.layers = layers
        self.encoder = nn.Linear(node_dim, hidden)
        if architecture == "edge_gated":
            self.node_messages = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
            self.edge_gates = nn.ModuleList([
                nn.Sequential(nn.Linear(edge_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden))
                for _ in range(layers)])
        elif architecture == "edge_mlp":
            self.messages = nn.ModuleList([
                nn.Sequential(nn.Linear(hidden + edge_dim, hidden * 2), nn.ReLU(),
                              nn.Linear(hidden * 2, hidden)) for _ in range(layers)])
        self.updates = nn.ModuleList([nn.Linear(hidden * 2, hidden) for _ in range(layers)])
        self.norms = nn.ModuleList([nn.LayerNorm(hidden) for _ in range(layers)])
        self.pair_embedding = nn.Embedding(len(CLASS_PAIR_LABELS), 8)
        self.edge_head = nn.Sequential(nn.Linear(hidden * 2 + edge_dim + 8, hidden), nn.ReLU(),
                                       nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x, edges, edge_attr, pair_ids):
        h = torch.relu(self.encoder(x))
        src, dst = edges[:, 0], edges[:, 1]
        rev_attr = reverse_edge_attr(edge_attr)
        for layer in range(self.layers):
            if self.architecture == "edge_gated":
                fw = torch.sigmoid(self.edge_gates[layer](edge_attr)) * self.node_messages[layer](h[src])
                bw = torch.sigmoid(self.edge_gates[layer](rev_attr)) * self.node_messages[layer](h[dst])
            else:
                fw = self.messages[layer](torch.cat((h[src], edge_attr), dim=1))
                bw = self.messages[layer](torch.cat((h[dst], rev_attr), dim=1))
            agg = torch.zeros_like(h)
            agg.index_add_(0, dst, fw); agg.index_add_(0, src, bw)
            deg = torch.zeros((len(h), 1), dtype=h.dtype, device=h.device)
            ones = torch.ones((len(src), 1), dtype=h.dtype, device=h.device)
            deg.index_add_(0, dst, ones); deg.index_add_(0, src, ones)
            update = torch.relu(self.updates[layer](torch.cat((h, agg / deg.clamp_min(1)), dim=1)))
            h = self.norms[layer](h + update)
        return self.edge_head(torch.cat((h[src], h[dst], edge_attr,
                                         self.pair_embedding(pair_ids)), dim=1)).squeeze(-1)


def train_architecture(rows, seed, device, architecture, epochs, batch_size):
    torch.manual_seed(seed); np.random.seed(seed); torch.set_num_threads(1)
    node_dim, edge_dim = rows[0][1].shape[1], rows[0][3].shape[1]
    if architecture == "mean":
        model = ACLPGNN(node_dim, edge_dim, True).to(device)
    else:
        model = EdgeAwareGNN(node_dim, edge_dim, architecture).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
    pos_count = sum(int(r[4][r[6]].sum()) for r in rows)
    selected_count = sum(len(r[6]) for r in rows)
    pos_weight = torch.tensor([(selected_count - pos_count) / max(pos_count, 1)], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    steps = 0
    for epoch in range(epochs):
        order = np.random.default_rng(seed + epoch).permutation(len(rows))
        total, seen = 0.0, 0
        for start in range(0, len(order), batch_size):
            batch = [rows[int(i)] for i in order[start:start + batch_size]]
            x, pairs, attrs, y, pair_ids = combine([r[1:6] for r in batch])
            offsets = np.cumsum([0] + [len(r[1]) for r in batch[:-1]])
            keep = np.concatenate([r[6] + offsets[i] for i, r in enumerate(batch)])
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(pairs, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
            tk = torch.as_tensor(keep, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(tx, te, ta, tp)[tk]
            loss = loss_fn(logits, torch.as_tensor(y[keep], dtype=torch.float32, device=device))
            loss.backward(); optimizer.step(); steps += 1
            total += float(loss.detach().cpu()) * len(keep); seen += len(keep)
        if epoch == 0 or (epoch + 1) % 5 == 0:
            print(f"  {architecture} seed={seed} epoch={epoch + 1}/{epochs} "
                  f"steps={steps} loss={total / max(seen, 1):.4f}", flush=True)
    return model, {"optimizer_steps": steps, "loss_edges": selected_count}


def score_architecture(model, rows, device):
    model.eval(); scores = []
    with torch.no_grad():
        for g, x, pairs, attrs, y, pair_ids in rows:
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(pairs, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
            scores.append(torch.sigmoid(model(tx, te, ta, tp)).cpu().numpy())
    return scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPHS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp04_edge_aware_gnn.json")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--architectures", nargs="+", choices=("mean", "edge_gated", "edge_mlp"),
                        default=["mean", "edge_gated", "edge_mlp"])
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    args = parser.parse_args()
    device = torch.device(args.device)
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS is unavailable")
    result = {"metadata": {"experiment": "E4 edge-aware GNN; validation-only",
                           "candidate_graph": "H2_hybrid",
                           "training_graphs": 3920, "validation_graphs": 515,
                           "test_accessed": False, "features": list(ALL_FLAGS),
                           "device": str(device), "epochs": args.epochs,
                           "batch_size": args.batch_size,
                           "loss_edge_policy": "same sampled candidate loss edges across architectures; full candidate graph for message passing"},
              "runs": []}
    for seed in args.seeds:
        print(f"\n=== E4 seed {seed}: loading H2 hybrid rows ===", flush=True)
        train_rows, _, _ = load_training(args.graphs, ALL_FLAGS, seed, 20, 16, 1000, build_lgbm=False)
        val_rows = load_eval(args.graphs, "validation", ALL_FLAGS)
        if len(train_rows) != 3920 or len(val_rows) != 515:
            raise RuntimeError(f"Unexpected split sizes: train={len(train_rows)}, val={len(val_rows)}")
        for architecture in args.architectures:
            model, fit_info = train_architecture(train_rows, seed, device, architecture,
                                                 args.epochs, args.batch_size)
            metric = evaluate_pin_ranking(val_rows, score_architecture(model, val_rows, device))
            result["runs"].append({"architecture": architecture, "seed": seed,
                                   "validation": {**metric, **fit_info}})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"  {architecture} validation AP={metric['candidate_pr_auc']:.4f}", flush=True)
            del model
            if device.type == "mps":
                torch.mps.empty_cache()
        del train_rows, val_rows
    print(f"Saved E4 results to {args.output}", flush=True)


if __name__ == "__main__":
    main()
