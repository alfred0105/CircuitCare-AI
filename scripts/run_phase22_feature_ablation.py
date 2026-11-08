#!/usr/bin/env python3
"""Validation-only feature ablations using the matched-loss GNN runner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_phase22_model_comparison import (  # noqa: E402
    ALL_FLAGS, DEFAULT_GRAPHS, evaluate_pin_ranking, load_eval, load_training,
    project_row, score_gnn, train_gnn,
)

VARIANTS = {
    "F0": ALL_FLAGS,
    "F1_no_neighbor_rank": tuple(x for x in ALL_FLAGS if x != "neighbor_geometry"),
    "F2_no_relative_geometry": tuple(x for x in ALL_FLAGS if x != "relative_geometry"),
    "F3_no_component_pair": tuple(x for x in ALL_FLAGS if x != "component_type_pair"),
    "F4_no_pin_facing": tuple(x for x in ALL_FLAGS if x != "pin_facing"),
    "F5_no_pin_name_category": tuple(x for x in ALL_FLAGS if x != "pin_name_category"),
    "F6_no_power_ground": tuple(x for x in ALL_FLAGS if x != "power_ground"),
    "F7_no_pitch_distance": tuple(x for x in ALL_FLAGS if x != "pitch_normalized_distance"),
    "F8_no_pin_name_derived": tuple(x for x in ALL_FLAGS
                                     if x not in {"pin_name_category", "power_ground"}) + ("drop_pin_name_derived",),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPHS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp02_feature_ablation.json")
    parser.add_argument("--variants", nargs="+", choices=tuple(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[42])
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    args = parser.parse_args()
    device = torch.device(args.device)
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("MPS is unavailable")

    results = {"metadata": {"experiment": "E2 validation-only feature ablation",
                            "training_graphs": 3920, "validation_graphs": 515,
                            "test_accessed": False, "device": str(device),
                            "epochs": args.epochs, "batch_size": args.batch_size,
                            "loss_edges": "same deterministic per-graph sampled edge set across variants",
                            "primary_metric": "candidate_pr_auc",
                            "pin_name_derived_group": ["pin_name_category", "power_ground", "raw pin-name length"]},
               "runs": []}
    for seed in args.seeds:
        print(f"\n=== E2 seed {seed}: loading shared full-feature rows ===", flush=True)
        base_train, _, _ = load_training(args.graphs, ALL_FLAGS, seed, 20, 16, 1000, build_lgbm=False)
        base_val = load_eval(args.graphs, "validation", ALL_FLAGS)
        if len(base_train) != 3920 or len(base_val) != 515:
            raise RuntimeError(f"Unexpected split size: train={len(base_train)}, val={len(base_val)}")
        for variant in args.variants:
            flags = VARIANTS[variant]
            print(f"  run {variant}: features={flags}", flush=True)
            train_rows = [project_row(row, flags) for row in base_train]
            val_rows = [project_row(row, flags) for row in base_val]
            model, fit_info = train_gnn(train_rows, seed, device, args.epochs, args.batch_size, flags)
            scores = score_gnn(model, val_rows, device)
            metrics = evaluate_pin_ranking(val_rows, scores)
            results["runs"].append({"variant": variant, "features": list(flags), "seed": seed,
                                   "validation": {**metrics, **fit_info}})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"  {variant} validation AP={metrics['candidate_pr_auc']:.4f}", flush=True)
            del model, train_rows, val_rows, scores
            if device.type == "mps":
                torch.mps.empty_cache()
        del base_train, base_val
    print(f"Saved E2 results to {args.output}", flush=True)


if __name__ == "__main__":
    main()
