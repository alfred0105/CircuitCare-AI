#!/usr/bin/env python3
"""Validation-only candidate-generator comparisons using cached pin coordinates."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_connectivity_features import pin_name_group  # noqa: E402

DEFAULT_GRAPHS = ROOT / "data/external/connectivity-dataset-v1/extracted/pin_candidate_graphs.jsonl"


def baseline_candidates(graph: dict[str, Any]) -> set[tuple[int, int]]:
    return {tuple(sorted((int(e["source"]), int(e["target"])))) for e in graph["edges"]}


def geometric_candidates(nodes, k: int, radius: float) -> set[tuple[int, int]]:
    coords = np.asarray([[float(n["x"]), float(n["y"])] for n in nodes], dtype=np.float64)
    if len(coords) < 2:
        return set()
    tree = cKDTree(coords)
    around = tree.query_ball_point(coords, r=radius)
    candidates: set[tuple[int, int]] = set()
    for i, neighbors in enumerate(around):
        ranked = sorted((float(np.linalg.norm(coords[j] - coords[i])), int(j))
                        for j in neighbors if j != i and nodes[j].get("ref") != nodes[i].get("ref"))
        for _, j in ranked[:k]:
            candidates.add((min(i, j), max(i, j)))
    return candidates


def role_candidates(nodes, base: set[tuple[int, int]], per_pin: int) -> set[tuple[int, int]]:
    groups = []
    for n in nodes:
        role = pin_name_group(n.get("pin_name"))
        electrical = str(n.get("electrical", "")).casefold()
        if role == "ground":
            groups.append("ground")
        elif role == "power" or electrical in {"power_in", "power_out"}:
            groups.append("power")
        else:
            groups.append("")
    coords = np.asarray([[float(n["x"]), float(n["y"])] for n in nodes], dtype=np.float64)
    proposals: set[tuple[int, int]] = set()
    # Roles only propose candidates; names never decide a positive label.
    for i, role in enumerate(groups):
        if not role:
            continue
        compatible = [j for j, other in enumerate(groups)
                      if j != i and other == role and nodes[j].get("ref") != nodes[i].get("ref")]
        compatible.sort(key=lambda j: (float(np.linalg.norm(coords[j] - coords[i])), j))
        for j in compatible[:per_pin]:
            proposals.add((min(i, j), max(i, j)))
    return base | proposals


def two_hop_candidates(nodes, base: set[tuple[int, int]], per_pin: int) -> set[tuple[int, int]]:
    adjacency = [[] for _ in nodes]
    existing = set(base)
    for a, b in base:
        adjacency[a].append(b); adjacency[b].append(a)
    coords = np.asarray([[float(n["x"]), float(n["y"])] for n in nodes], dtype=np.float64)
    expanded = set(base)
    for i, first in enumerate(adjacency):
        proposals = set()
        for mid in first:
            proposals.update(adjacency[mid])
        proposals.discard(i)
        ranked = []
        for j in proposals:
            pair = (min(i, j), max(i, j))
            if pair in existing or nodes[j].get("ref") == nodes[i].get("ref"):
                continue
            ranked.append((float(np.linalg.norm(coords[j] - coords[i])), j, pair))
        ranked.sort()
        expanded.update(pair for _, _, pair in ranked[:per_pin])
    return expanded


def metrics_for_graph(g, candidates):
    nodes = g["nodes"]
    truth = {tuple(sorted(map(int, e))) for e in g.get("truth_edges", [])}
    valid = {e for e in truth if nodes[e[0]].get("ref") != nodes[e[1]].get("ref")}
    hits = len(valid & candidates)
    return {"truth": len(valid), "hits": hits, "internal_truth": len(truth) - len(valid),
            "candidate_count": len(candidates), "pins": len(nodes)}


def summarize(rows):
    total_truth = sum(r["truth"] for r in rows)
    total_hits = sum(r["hits"] for r in rows)
    total_candidates = sum(r["candidate_count"] for r in rows)
    total_pins = sum(r["pins"] for r in rows)
    recalls = [r["hits"] / r["truth"] for r in rows if r["truth"]]
    return {"graphs": len(rows), "truth_pairs_excluding_same_ref": total_truth,
            "unreachable_same_ref_truth_pairs": sum(r["internal_truth"] for r in rows),
            "candidate_true_pairs": total_hits,
            "candidate_recall_micro": total_hits / max(total_truth, 1),
            "candidate_recall_macro": float(np.mean(recalls)) if recalls else None,
            "candidate_precision": total_hits / max(total_candidates, 1),
            "candidate_edges": total_candidates,
            "candidates_per_pin_mean": total_candidates * 2 / max(total_pins, 1),
            "candidate_edges_per_graph_mean": total_candidates / max(len(rows), 1)}


def edge_records(nodes, candidates, truth):
    coords = np.asarray([[float(n["x"]), float(n["y"])] for n in nodes], dtype=np.float64)
    result = []
    ranks = {}
    # Rank is recomputed within each source endpoint's nearest cross-component neighbors.
    incident = [[] for _ in nodes]
    for a, b in candidates:
        distance = float(np.linalg.norm(coords[b] - coords[a]))
        incident[a].append((distance, b)); incident[b].append((distance, a))
    for i, adjacent in enumerate(incident):
        for rank, (_, j) in enumerate(sorted(adjacent), 1):
            ranks[(min(i, j), max(i, j))] = min(ranks.get((min(i, j), max(i, j)), rank), rank)
    for a, b in sorted(candidates):
        dx, dy = coords[b] - coords[a]
        result.append({"source": a, "target": b, "distance": float(math.hypot(dx, dy)),
                       "dx": float(dx), "dy": float(dy), "rank_i": float(ranks[(a, b)]),
                       "label": int((a, b) in truth)})
    return result


def build_variants(g, role_cap, twohop_cap, requested=None):
    old = baseline_candidates(g)
    nodes = g["nodes"]
    requested = set(requested or ("C0_baseline", "C1_k64_r250", "C2_k128_r250", "C3_k96_r150",
                                  "C4_k96_r350", "C5_k128_r350", "P1_power_ground_added",
                                  "H1_twohop_added", "H2_hybrid"))
    c = {}
    if "C0_baseline" in requested:
        c["C0_baseline"] = old
    geometric = {"C1_k64_r250": (64, 250), "C2_k128_r250": (128, 250),
                 "C3_k96_r150": (96, 150), "C4_k96_r350": (96, 350),
                 "C5_k128_r350": (128, 350)}
    for name, (k, radius) in geometric.items():
        if name in requested:
            c[name] = geometric_candidates(nodes, k, radius)
    if "P1_power_ground_added" in requested:
        c["P1_power_ground_added"] = role_candidates(nodes, old, role_cap)
    if "H1_twohop_added" in requested:
        c["H1_twohop_added"] = two_hop_candidates(nodes, old, twohop_cap)
    if "H2_hybrid" in requested:
        hybrid = geometric_candidates(nodes, 128, 350)
        hybrid = role_candidates(nodes, hybrid, role_cap)
        c["H2_hybrid"] = two_hop_candidates(nodes, hybrid, twohop_cap)
    return c


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPHS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/benchmarks/phase22_connectivity/exp03_candidate_generation.json")
    parser.add_argument("--role-cap", type=int, default=8)
    parser.add_argument("--twohop-cap", type=int, default=8)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--variants", nargs="+", default=None)
    parser.add_argument("--splits", nargs="+", choices=("train", "validation"), default=["validation"])
    args = parser.parse_args()
    totals: dict[str, list] = {}
    out_streams = {}
    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)
    with args.graphs.open(encoding="utf-8") as stream:
        for i, line in enumerate(stream, 1):
            g = json.loads(line)
            if g["split"] not in args.splits:
                continue
            candidates = build_variants(g, args.role_cap, args.twohop_cap, args.variants)
            if args.variants:
                candidates = {name: pairs for name, pairs in candidates.items() if name in args.variants}
            truth = {tuple(sorted(map(int, e))) for e in g.get("truth_edges", [])}
            for name, pairs in candidates.items():
                if g["split"] == "validation":
                    totals.setdefault(name, []).append(metrics_for_graph(g, pairs))
                if args.export_dir:
                    path = args.export_dir / f"{name}.jsonl"
                    out = out_streams.get(name)
                    if out is None:
                        out = path.open("w", encoding="utf-8")
                        out_streams[name] = out
                    row = dict(g)
                    row["edges"] = edge_records(g["nodes"], pairs, truth)
                    row_metrics = metrics_for_graph(g, pairs)
                    row["candidate_recall"] = row_metrics["hits"] / row_metrics["truth"] if row_metrics["truth"] else None
                    row["candidate_recall_scope"] = "excluding_same_component_pairs"
                    out.write(json.dumps(row, separators=(",", ":")) + "\n")
            if i % 500 == 0:
                print(f"scanned {i} graphs; validation records={sum(len(v) for v in totals.values()) // max(len(totals), 1)}", flush=True)
    for out in out_streams.values():
        out.close()
    report = {"metadata": {"experiment": "E3 candidate generation; validation-only selection",
                           "validation_graphs": 515, "test_accessed": False,
                           "export_splits": args.splits,
                           "baseline_k": 96, "baseline_radius_mm": 250,
                           "role_candidate_cap_per_pin": args.role_cap,
                           "twohop_candidate_cap_per_pin": args.twohop_cap,
                           "same_component_truth_pairs_excluded_from_recall": True,
                           "role_names_are_candidate_hints_only": True},
              "runs": {name: summarize(rows) for name, rows in totals.items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["runs"], indent=2), flush=True)
    print(f"Saved E3 results to {args.output}", flush=True)


if __name__ == "__main__":
    main()
