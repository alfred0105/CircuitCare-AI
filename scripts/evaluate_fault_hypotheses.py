#!/usr/bin/env python3
"""Run the small labeled fault-hypothesis dataset and write reproducible metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from circuitcare.fault_ai.evaluation import score_fault_cases
from circuitcare.fault_ai.fault_catalog import generate_rule_candidates
from circuitcare.fault_ai.hypothesis_validator import validate_hypotheses
from circuitcare.fault_ai.llm_hypothesis import PROMPT_VERSION, propose_hypotheses
from circuitcare.fault_ai.hypothesis_ranking import rank_hypotheses
from circuitcare.fault_ai.simulation_bridge import preflight_candidates, simulate_hypothesis
from circuitcare.local_llm import OllamaClient
from circuitcare.netlist import load_netlist

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="evaluation/fault_hypothesis/manifest.json")
    parser.add_argument("--output", default="evaluation/fault_hypothesis/results")
    parser.add_argument("--run-llm", action="store_true", help="Run the installed local Ollama model.")
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--simulate", action="store_true", help="Explicitly run ngspice for up to 40 catalog candidates per case.")
    args = parser.parse_args()
    manifest_path = ROOT / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    rule_predictions, llm_predictions, combined_predictions = {}, {}, {}
    case_results = []
    model_metadata = None
    for case in cases:
        paths = {key: ROOT / value for key, value in case["circuit"].items()}
        circuit = load_netlist(paths["netlist"])
        mapping = json.loads(paths["mapping"].read_text(encoding="utf-8"))
        probes = json.loads(paths["probes"].read_text(encoding="utf-8"))
        spice_text = paths["spice"].read_text(encoding="utf-8")
        rule_raw = generate_rule_candidates(circuit, mapping, spice_text, case.get("observations", []))
        rule_rows = preflight_candidates(rule_raw, component_refs=set(circuit.components), component_mapping=mapping, spice_text=spice_text)
        llm_rows, llm_info = [], None
        if args.run_llm:
            components = [{"ref": item.ref, "value": item.value, "library_id": item.library_id,
                           "nets": list(circuit.component_nets.get(item.ref, ())),
                           "mapping_available": item.ref in mapping,
                           "model_type": mapping.get(item.ref, {}).get("model_type")}
                          for item in circuit.components.values()]
            raw = propose_hypotheses(OllamaClient(), args.model, circuit_id=case["case_id"],
                components=components, observations=case.get("observations", []),
                symptoms=f"Synthetic known injected fault evaluation case {case['case_id']}", executable_catalog=rule_rows)
            llm_rows = validate_hypotheses(raw["hypotheses"], component_refs=set(circuit.components),
                component_mapping=mapping, spice_text=spice_text, allowed_catalog=rule_rows)
            llm_info = {key: raw.get(key) for key in ("model", "model_info", "prompt_version", "latency_seconds", "json_mode")}
            model_metadata = raw.get("model_info")
        # The combined method intentionally retains every safe deterministic rule candidate.
        combined_rows = _dedupe([*rule_rows, *llm_rows])
        if args.simulate:
            sims = 0
            for row in combined_rows:
                if row.get("validation_status") == "VALIDATED_EXECUTABLE" and sims < 40:
                    result = simulate_hypothesis(row, base_netlist=paths["spice"], component_mapping=mapping,
                        probes=probes, observations=case.get("observations", []), timeout_seconds=60)
                    row.update(result)
                    sims += 1
        ranked_combined = rank_hypotheses(combined_rows)
        rule_keys = {_identity(row) for row in rule_rows}
        llm_keys = {_identity(row) for row in llm_rows}
        rule_ranked = [row for row in ranked_combined if _identity(row) in rule_keys]
        llm_ranked = [row for row in ranked_combined if _identity(row) in llm_keys]
        case_id = case["case_id"]
        rule_predictions[case_id], llm_predictions[case_id], combined_predictions[case_id] = rule_ranked, llm_ranked, ranked_combined
        case_results.append({"case_id": case_id, "truth_source": case["truth_source"], "split": case["split"],
            "rule_candidate_count": len(rule_rows), "llm_candidate_count": len(llm_rows),
            "llm_generation": llm_info, "rule_candidates": rule_ranked,
            "llm_candidates": llm_ranked, "combined_ranked": ranked_combined})
    result = {
        "status": "MEASURED_SYNTHETIC" if args.simulate else "PROPOSAL_ONLY",
        "dataset_id": manifest.get("dataset_id"), "dataset_version": manifest.get("version"),
        "split": manifest.get("split"), "independent_holdout": manifest.get("independent_holdout", False),
        "run_metadata": {"git_commit_sha": _git_sha(), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "os": platform.platform(), "llm": model_metadata,
            "model_requested": args.model if args.run_llm else None,
            "prompt_version": PROMPT_VERSION if args.run_llm else None,
            "simulator": _ngspice_version() if args.simulate else None,
            "simulate": args.simulate, "llm_enabled": args.run_llm},
        "methods": {
            "A_rule_based": score_fault_cases(cases, rule_predictions),
            "B_local_llm_only": score_fault_cases(cases, llm_predictions),
            "C_rules_llm_validator": score_fault_cases(cases, combined_predictions),
        },
        "case_results": case_results,
        "interpretation": "This dataset contains known simulated injections, not real repair records or an independent holdout; metrics are development diagnostics only. Simulated consistency is not physical fault confirmation.",
    }
    llm_times = [item.get("llm_generation", {}).get("latency_seconds") for item in case_results
                 if isinstance(item.get("llm_generation", {}).get("latency_seconds"), (int, float))]
    result["methods"]["B_local_llm_only"]["inference_latency_seconds"] = llm_times
    result["methods"]["B_local_llm_only"]["mean_inference_latency_seconds"] = sum(llm_times) / len(llm_times) if llm_times else None
    result["methods"]["C_rules_llm_validator"]["inference_latency_seconds"] = llm_times
    result["methods"]["C_rules_llm_validator"]["mean_inference_latency_seconds"] = sum(llm_times) / len(llm_times) if llm_times else None
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    target = output / "metrics.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name, method in (("rule_baseline.json", "A_rule_based"), ("llm_candidates.json", "B_local_llm_only"),
                         ("validated_candidates.json", "C_rules_llm_validator")):
        (output / name).write_text(json.dumps({"run_metadata": result["run_metadata"], "method": method,
            "metrics": result["methods"][method], "cases": {item["case_id"]: item.get("rule_candidates" if method == "A_rule_based" else "llm_candidates" if method == "B_local_llm_only" else "combined_ranked", []) for item in case_results}}, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "simulation_verification.json").write_text(json.dumps({"run_metadata": result["run_metadata"],
        "cases": {item["case_id"]: [{"hypothesis_id": row.get("hypothesis_id"), "simulation_status": row.get("simulation_status"),
            "simulation_seconds": row.get("simulation_seconds"), "predicted_measurements": row.get("predicted_measurements"),
            "observation_match": row.get("observation_match"), "simulation_error": row.get("simulation_error")}
            for row in item.get("combined_ranked", [])] for item in case_results}}, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target.relative_to(ROOT)), "status": result["status"], "methods": result["methods"]}, ensure_ascii=False, indent=2))
    return 0


def _dedupe(rows):
    result, seen = [], set()
    for row in rows:
        key = _identity(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(row))
    return result


def _identity(row):
    normalized = {}
    for key, value in row.get("parameters", {}).items():
        try:
            normalized[key] = f"{float(value):.12g}"
        except (TypeError, ValueError):
            normalized[key] = str(value).strip().casefold()
    return (row.get("component_ref"), row.get("fault_type"), json.dumps(normalized, sort_keys=True))


def _git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _ngspice_version():
    try:
        return subprocess.run(["ngspice", "--version"], check=False, capture_output=True, text=True, timeout=5).stdout[-500:]
    except (OSError, subprocess.SubprocessError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
