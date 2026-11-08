#!/usr/bin/env python3
"""Recheck the best Optuna LightGBM parameters with additional seeds."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from lightgbm import LGBMClassifier
from sklearn.utils.class_weight import compute_sample_weight

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_phase22_lgbm_search import load_training_matrix  # noqa: E402
from run_phase22_model_comparison import (  # noqa: E402
    ALL_FLAGS, DEFAULT_GRAPHS, evaluate_pin_ranking, load_eval, score_lgbm,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=ROOT / "data/external/connectivity-dataset-v1/derived/phase22_hybrid/H2_hybrid.jsonl")
    parser.add_argument("--search-results", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp05_lgbm_search.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp05_lgbm_recheck.json")
    parser.add_argument("--seeds", nargs="+", type=int, default=[123, 2026])
    args = parser.parse_args()
    search = json.loads(args.search_results.read_text())
    params = dict(search["best_params"])
    val_rows = load_eval(args.graphs, "validation", ALL_FLAGS)
    report = {"metadata": {"experiment": "E5-A fixed best LightGBM configuration; validation recheck",
                            "test_accessed": False, "candidate_graph": "H2_hybrid",
                            "features": list(ALL_FLAGS), "params": params,
                            "other_seeds": args.seeds}, "runs": []}
    for seed in args.seeds:
        print(f"\nrecheck LightGBM seed={seed}", flush=True)
        x, y = load_training_matrix(args.graphs, seed, 20, 1000)
        weights = compute_sample_weight("balanced", y)
        model = LGBMClassifier(**params, subsample=0.85, random_state=seed,
                               n_jobs=1, verbosity=-1)
        model.fit(x, y, sample_weight=weights,
                  categorical_feature=[x.shape[1] - 1])
        metrics = evaluate_pin_ranking(val_rows, score_lgbm(model, val_rows, ALL_FLAGS))
        report["runs"].append({"seed": seed, "validation": metrics})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"seed={seed} validation AP={metrics['candidate_pr_auc']:.4f}", flush=True)
        del model, x, y, weights
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
