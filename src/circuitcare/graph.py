"""Circuit connectivity candidate discovery (not a damage assessment)."""

from collections import defaultdict

from .models import CandidateImpact, Circuit


def direct_candidates(circuit: Circuit, failed_ref: str) -> list[CandidateImpact]:
    """Find components sharing one or more nets with a failed component."""
    if failed_ref not in circuit.components:
        raise ValueError(f"Unknown component reference: {failed_ref}")

    component_nets: dict[str, set[str]] = defaultdict(set)
    net_components: dict[str, set[str]] = defaultdict(set)
    for conn in circuit.connections:
        component_nets[conn.ref].add(conn.net)
        net_components[conn.net].add(conn.ref)

    shared: dict[str, set[str]] = defaultdict(set)
    for net in component_nets[failed_ref]:
        for neighbor in net_components[net]:
            if neighbor != failed_ref:
                shared[neighbor].add(net)

    return [
        CandidateImpact(target_ref=ref, shared_nets=tuple(sorted(nets)))
        for ref, nets in sorted(shared.items())
    ]
