"""Minimal typed domain objects for KiCad netlist ingestion."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    ref: str
    value: str
    library_id: str = ""


@dataclass(frozen=True)
class Connection:
    ref: str
    pin: str
    net: str


@dataclass
class Circuit:
    components: dict[str, Component]
    connections: list[Connection]


@dataclass(frozen=True)
class CandidateImpact:
    target_ref: str
    shared_nets: tuple[str, ...]
    evidence_level: str = "connectivity_only"
