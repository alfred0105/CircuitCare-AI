#!/usr/bin/env python3
"""Optuna search for LightGBM on H2 candidates; uses validation only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import optuna
from lightgbm import LGBMClassifier
from sklearn.utils.class_weight import compute_sample_weight

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_connectivity_features import augment_graph  # noqa: E402
from run_phase22_model_comparison import (  # noqa: E402
    ALL_FLAGS, DEFAULT_GRAPHS, edge_matrix, evaluate_pin_ranking, load_eval, sampling_indices,
    score_lgbm,
)


def load_training_matrix(path: Path, seed: int, negative_ratio: int, max_neg: int):
    xs, ys, graph_count = [], [], 0
    with path.open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            g = json.loads(line)
            if g["split"] != "train":
                continue
            graph_count += 1
            x, pairs, attrs, y, pids = augment_graph(g, ALL_FLAGS)
            keep = sampling_indices(y, g["sample_id"], seed, negative_ratio, 16, max_neg)
            if len(keep):
                xs.append(edge_matrix(x, pairs[keep], attrs[keep], pids[keep], ALL_FLAGS))
                ys.append(y[keep])
            if n % 500 == 0:
                print(f"  training scan {n}: {graph_count} train graphs", flush=True)
    if graph_count != 3920:
        raise RuntimeError(f"Expected 3920 training graphs, found {graph_count}")
    return np.concatenate(xs), np.concatenate(ys)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=ROOT / "data/external/connectivity-dataset-v1/derived/phase22_hybrid/H2_hybrid.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp05_lgbm_search.json")
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--negative-ratio", type=int, default=20)
    parser.add_argument("--max-negatives-per-graph", type=int, default=1000)
    args = parser.parse_args()
    print("Loading matched H2 training loss edges", flush=True)
    x_train, y_train = load_training_matrix(args.graphs, args.seed, args.negative_ratio,
                                            args.max_negatives_per_graph)
    sample_weight = compute_sample_weight("balanced", y_train)
    print(f"Training matrix={x_train.shape}, positives={int(y_train.sum()):,}", flush=True)
    val_rows = load_eval(args.graphs, "validation", ALL_FLAGS)
    results = {"metadata": {"experiment": "E5-A Optuna LightGBM search; validation only",
                            "training_graphs": 3920, "validation_graphs": 515,
                            "test_accessed": False, "candidate_graph": "H2_hybrid",
                            "features": list(ALL_FLAGS), "seed": args.seed,
                            "training_loss_edges": len(y_train),
                            "negative_ratio_cap": args.negative_ratio,
                            "max_sampled_negatives_per_graph": args.max_negatives_per_graph,
                            "objective": "validation candidate PR-AUC",
                            "class_weighting": "balanced after per-graph negative sampling",
                            "probabilities_calibrated": False}, "trials": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 200, 1000, step=100),
            "num_leaves": trial.suggest_categorical("num_leaves", [15, 31, 63, 127]),
            "max_depth": trial.suggest_categorical("max_depth", [4, 6, 8, -1]),
            "learning_rate": trial.suggest_categorical("learning_rate", [0.02, 0.05, 0.1]),
            "min_child_samples": trial.suggest_categorical("min_child_samples", [20, 50, 100, 200]),
            "reg_lambda": trial.suggest_categorical("reg_lambda", [0.0, 1.0, 10.0]),
            "colsample_bytree": trial.suggest_categorical("colsample_bytree", [0.7, 0.85, 1.0]),
        }
        model = LGBMClassifier(**params, subsample=0.85, random_state=args.seed,
                               n_jobs=1, verbosity=-1)
        model.fit(x_train, y_train, sample_weight=sample_weight,
                  categorical_feature=[x_train.shape[1] - 1])
        scores = score_lgbm(model, val_rows, ALL_FLAGS)
        metrics = evaluate_pin_ranking(val_rows, scores)
        record = {"number": trial.number, "params": params, "validation": metrics}
        results["trials"].append(record)
        results["best_trial_number"] = trial.number if trial.number == 0 or metrics["candidate_pr_auc"] > max(
            r["validation"]["candidate_pr_auc"] for r in results["trials"][:-1]) else results.get("best_trial_number")
        results["best_validation_pr_auc"] = max(r["validation"]["candidate_pr_auc"] for r in results["trials"])
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"trial {trial.number + 1}/{args.trials}: AP={metrics['candidate_pr_auc']:.4f} "
              f"P@1={metrics['pin_precision_at_1_micro']:.4f} params={params}", flush=True)
        return metrics["candidate_pr_auc"]

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=args.seed))
    study.optimize(objective, n_trials=args.trials, n_jobs=1)
    results["best_params"] = study.best_params
    results["best_validation_pr_auc"] = study.best_value
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Best validation AP={study.best_value:.4f}; saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
