#!/usr/bin/env python3
"""Small Optuna/early-stopping search for edge-MLP GNN; validation only."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

import numpy as np
import optuna
import torch
from sklearn.metrics import average_precision_score
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_connectivity_features import combine  # noqa: E402
from run_phase22_edge_aware_gnn import EdgeAwareGNN, score_architecture  # noqa: E402
from run_phase22_model_comparison import (  # noqa: E402
    ALL_FLAGS, evaluate_pin_ranking, load_eval, load_training,
)

DEFAULT_GRAPHS = ROOT / "data/external/connectivity-dataset-v1/derived/phase22_hybrid/H2_hybrid.jsonl"


def train_with_early_stopping(train_rows, val_rows, seed, device, params, max_epochs,
                              batch_size, eval_every=5, patience=2):
    torch.manual_seed(seed); np.random.seed(seed); torch.set_num_threads(1)
    model = EdgeAwareGNN(train_rows[0][1].shape[1], train_rows[0][3].shape[1], "edge_mlp",
                         hidden=params["hidden"], layers=params["layers"],
                         dropout=params["dropout"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=params["learning_rate"],
                                  weight_decay=params["weight_decay"])
    positives = sum(int(r[4][r[6]].sum()) for r in train_rows)
    selected = sum(len(r[6]) for r in train_rows)
    pos_weight = torch.tensor([(selected - positives) / max(positives, 1)], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    best_ap, best_epoch, best_state, stale, steps = -1.0, 0, None, 0, 0
    history = []
    for epoch in range(max_epochs):
        order = np.random.default_rng(seed + epoch).permutation(len(train_rows))
        total_loss, seen = 0.0, 0
        for start in range(0, len(order), batch_size):
            batch = [train_rows[int(i)] for i in order[start:start + batch_size]]
            x, edges, attrs, labels, pair_ids = combine([r[1:6] for r in batch])
            offsets = np.cumsum([0] + [len(r[1]) for r in batch[:-1]])
            keep = np.concatenate([r[6] + offsets[i] for i, r in enumerate(batch)])
            tx = torch.as_tensor(x, dtype=torch.float32, device=device)
            te = torch.as_tensor(edges, dtype=torch.long, device=device)
            ta = torch.as_tensor(attrs, dtype=torch.float32, device=device)
            tp = torch.as_tensor(pair_ids, dtype=torch.long, device=device)
            tk = torch.as_tensor(keep, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(tx, te, ta, tp)[tk]
            loss = loss_fn(logits, torch.as_tensor(labels[keep], dtype=torch.float32, device=device))
            loss.backward(); optimizer.step(); steps += 1
            total_loss += float(loss.detach().cpu()) * len(keep); seen += len(keep)
        epoch_loss = total_loss / max(seen, 1)
        if (epoch + 1) % eval_every == 0:
            per_graph = score_architecture(model, val_rows, device)
            labels = np.concatenate([r[4] for r in val_rows])
            ap = float(average_precision_score(labels, np.concatenate(per_graph)))
            history.append({"epoch": epoch + 1, "validation_candidate_pr_auc": ap,
                            "training_loss": epoch_loss})
            print(f"  epoch {epoch + 1}/{max_epochs}: validation AP={ap:.4f} loss={epoch_loss:.4f}", flush=True)
            if ap > best_ap + 1e-5:
                best_ap, best_epoch = ap, epoch + 1
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                stale = 0
            else:
                stale += 1
            if stale >= patience:
                print(f"  early stop at epoch {epoch + 1}; restore epoch {best_epoch}", flush=True)
                break
    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        best_epoch = max_epochs
    model.load_state_dict(best_state)
    return model, {"best_epoch": best_epoch, "best_validation_pr_auc_during_training": best_ap,
                   "history": history, "optimizer_steps": steps, "loss_edges": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPHS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp05_gnn_search.json")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    args = parser.parse_args()
    device = torch.device(args.device)
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS is unavailable")
    print("Loading H2 hybrid train/validation graphs", flush=True)
    train_rows, _, _ = load_training(args.graphs, ALL_FLAGS, args.seed, 20, 16, 1000, build_lgbm=False)
    val_rows = load_eval(args.graphs, "validation", ALL_FLAGS)
    report = {"metadata": {"experiment": "E5-B edge-MLP GNN Optuna search; validation only",
                            "candidate_graph": "H2_hybrid", "features": list(ALL_FLAGS),
                            "training_graphs": 3920, "validation_graphs": 515,
                            "test_accessed": False, "seed": args.seed, "device": str(device),
                            "max_epochs": args.max_epochs, "batch_size": args.batch_size,
                            "early_stopping": {"metric": "validation candidate PR-AUC",
                                               "eval_every_epochs": 5, "patience_evaluations": 2,
                                               "restore_best_checkpoint": True}}, "trials": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def objective(trial):
        params = {
            "hidden": trial.suggest_categorical("hidden", [32, 48, 64]),
            "layers": trial.suggest_categorical("layers", [1, 2, 3]),
            "learning_rate": trial.suggest_categorical("learning_rate", [0.0003, 0.001, 0.003]),
            "dropout": trial.suggest_categorical("dropout", [0.1, 0.2, 0.3]),
            "weight_decay": trial.suggest_categorical("weight_decay", [1e-5, 1e-4, 1e-3]),
        }
        model, fit_info = train_with_early_stopping(train_rows, val_rows, args.seed, device,
                                                    params, args.max_epochs, args.batch_size)
        metrics = evaluate_pin_ranking(val_rows, score_architecture(model, val_rows, device))
        record = {"number": trial.number, "params": params,
                  "validation": metrics, "fit": fit_info}
        report["trials"].append(record)
        report["best_trial_number"] = trial.number if trial.number == 0 or metrics["candidate_pr_auc"] > max(
            r["validation"]["candidate_pr_auc"] for r in report["trials"][:-1]) else report.get("best_trial_number")
        report["best_validation_pr_auc"] = max(r["validation"]["candidate_pr_auc"] for r in report["trials"])
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        del model
        if device.type == "mps":
            torch.mps.empty_cache()
        return metrics["candidate_pr_auc"]

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=args.seed))
    study.optimize(objective, n_trials=args.trials, n_jobs=1)
    report["best_params"] = study.best_params
    report["best_validation_pr_auc"] = study.best_value
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Best GNN validation AP={study.best_value:.4f}; saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
