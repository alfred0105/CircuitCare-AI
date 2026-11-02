"""Initial offline CLI. No probabilistic or physical damage claims."""

import argparse
import json
from pathlib import Path

from .graph import build_graph, direct_candidates, find_paths, to_dot
from .netlist import load_netlist


def main() -> None:
    parser = argparse.ArgumentParser(description="CircuitCare AI bootstrap CLI")
    parser.add_argument("--netlist", required=True, help="KiCad XML netlist path")
    parser.add_argument("--fault", required=True, help="Known failed component ref (e.g. U1)")
    parser.add_argument("--show-pins", action="store_true", help="Include component metadata and pin-to-net connections")
    parser.add_argument("--show-paths", action="store_true", help="Include direct and indirect connectivity paths")
    parser.add_argument("--max-hops", type=int, default=2, help="Maximum component-to-component path length (default: 2)")
    parser.add_argument("--net-types", type=Path, help="Optional JSON map of net names to ground, power, signal or unknown")
    parser.add_argument("--exclude-net-types", help="Comma-separated net types to exclude from path traversal")
    parser.add_argument("--export-dot", type=Path, help="Write the circuit connectivity graph as a Graphviz DOT file")
    args = parser.parse_args()

    circuit = load_netlist(args.netlist)
    candidates = direct_candidates(circuit, args.fault)
    net_types = json.loads(args.net_types.read_text(encoding="utf-8")) if args.net_types else None
    if net_types is not None and not isinstance(net_types, dict):
        parser.error("--net-types must contain a JSON object mapping net names to types")
    graph = build_graph(circuit, net_types)
    excluded_types = {
        item.strip().lower()
        for item in (args.exclude_net_types or "").split(",")
        if item.strip()
    }
    if excluded_types and not (args.show_paths or args.export_dot):
        parser.error("--exclude-net-types requires --show-paths or --export-dot")
    paths = None
    if args.show_paths or args.export_dot:
        paths = find_paths(
            circuit,
            args.fault,
            max_hops=args.max_hops,
            net_types=net_types,
            exclude_net_types=excluded_types,
        )

    output = {
        "failed_component": args.fault,
        "analysis_stage": "connectivity_only",
        "warning": "Connected components are not confirmed damaged. Fault type, electrical ratings and simulation are not yet evaluated.",
        "components_loaded": len(circuit.components),
        "candidates": [
            {
                "reference": candidate.target_ref,
                "shared_nets": list(candidate.shared_nets),
                "shared_net_types": {
                    net: str((net_types or {}).get(net, "unknown")).strip().lower()
                    for net in candidate.shared_nets
                },
                "evidence_level": candidate.evidence_level,
            }
            for candidate in candidates
        ],
    }
    if args.show_paths:
        output["max_hops"] = args.max_hops
        output["path_candidates"] = [
            {
                "reference": candidate.target_ref,
                "connection_type": candidate.connection_type,
                "hops": candidate.hops,
                "path": list(candidate.path),
                "nets": list(candidate.nets),
                "net_types": dict(candidate.net_types),
                "ground_only_path": candidate.ground_only_path,
                "evidence_level": candidate.evidence_level,
            }
            for candidate in (paths or [])
        ]
    if excluded_types:
        output["excluded_net_types"] = sorted(excluded_types)
        output["path_filter_note"] = (
            "Excluded net types only limit displayed traversal; this does not establish "
            "that excluded connections cannot carry fault effects."
        )
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
    if args.export_dot:
        args.export_dot.write_text(to_dot(graph, args.fault, paths), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
