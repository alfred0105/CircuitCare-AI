"""Initial offline CLI. No probabilistic or physical damage claims."""

import argparse
import json

from .graph import direct_candidates
from .netlist import load_netlist


def main() -> None:
    parser = argparse.ArgumentParser(description="CircuitCare AI bootstrap CLI")
    parser.add_argument("--netlist", required=True, help="KiCad XML netlist path")
    parser.add_argument("--fault", required=True, help="Known failed component ref (e.g. U1)")
    parser.add_argument("--show-pins", action="store_true", help="Include component metadata and pin-to-net connections")
    args = parser.parse_args()

    circuit = load_netlist(args.netlist)
    candidates = direct_candidates(circuit, args.fault)
    output = {
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
    }
    if args.show_pins:
        output["component_details"] = [
            {
                "reference": component.ref,
                "value": component.value,
                "library_id": component.library_id,
                "footprint": component.footprint,
                "datasheet": component.datasheet,
                "nets": list(circuit.component_nets[component.ref]),
            }
            for component in circuit.components.values()
        ]
        output["pin_connections"] = [
            {"reference": item.ref, "pin": item.pin, "net": item.net, "net_code": item.net_code}
            for item in circuit.connections
        ]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
