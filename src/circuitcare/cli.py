"""Initial offline CLI. No probabilistic or physical damage claims."""

import argparse
import json

from .graph import direct_candidates
from .netlist import load_netlist


def main() -> None:
    parser = argparse.ArgumentParser(description="CircuitCare AI bootstrap CLI")
    parser.add_argument("--netlist", required=True, help="KiCad XML netlist path")
    parser.add_argument("--fault", required=True, help="Known failed component ref (e.g. U1)")
    args = parser.parse_args()

    circuit = load_netlist(args.netlist)
    candidates = direct_candidates(circuit, args.fault)
    print(json.dumps({
        "failed_component": args.fault,
        "analysis_stage": "connectivity_only",
        "warning": "Connected components are not confirmed damaged. Fault type, electrical ratings and simulation are not yet evaluated.",
        "components_loaded": len(circuit.components),
        "candidates": [
            {
                "reference": candidate.target_ref,
                "shared_nets": list(candidate.shared_nets),
                "evidence_level": candidate.evidence_level,
            }
            for candidate in candidates
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
