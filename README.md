# CircuitCare AI

**Local, lightweight AI-assisted circuit fault propagation analysis and repair prioritization.**

CircuitCare AI aims to answer a practical repair question: **if one component has failed, which *other* components might have been affected, why, and what should be checked next?**

> **Status: Phases 01–02 complete; Phase 03 has an initial implementation.** The CLI parses KiCad XML netlists and reports direct connectivity candidates. It does **not** calculate electrical stress, actual damage, or failure probabilities. Do not use its output to approve a live repair. KiCad 10.0.6 export verification used the bundled Raspberry Pi HAT schematic.

## Core differentiator
- Start from a **known failed component and failure mode**, not just a symptom.
- Track possible **secondary effects** through the circuit topology.
- Verify candidate impacts using **normal-vs-fault SPICE simulations** and component limits (planned).
- Use **lightweight local inference** for risk ranking and information-efficient next measurements (planned).
- Return **ranked inspection/repair guidance with evidence**, not fabricated failure probabilities (planned).

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 01 | Python environment, conventions, sample data | Complete |
| 02 | KiCad netlist parser | Complete; verified with KiCad 10.0.6 export |
| 03 | Component-net graph and affected-neighbor candidates | Initial implementation |
| 04 | Failure modes and fault injection models | Planned |
| 05 | ngspice baseline/fault electrical comparisons | Planned |
| 06 | Secondary-damage stress assessment and evidence | Planned |
| 07 | Local lightweight AI and active measurement ranking | Planned |
| 08 | Repair recommendations and audit trail | Planned |
| 09 | UI, benchmark, offline evaluation | Planned |
| 10 | Stabilization, poster, reproducible demo | Planned |

Full acceptance criteria: [docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start

Requires Python 3.11+ (Python 3.11 is the CI baseline; Python 3.12 also works).

```bash
python -m pip install -e ".[dev]"
circuitcare --netlist tests/fixtures/simple_kicad_netlist.xml --fault U1
python -m pytest -q
```

To inspect parsed component metadata and pin-to-net connections, add `--show-pins`:

```bash
circuitcare --netlist tests/fixtures/simple_kicad_netlist.xml --fault U1 --show-pins
```

The included sample intentionally connects U1 to J1, U2 and C3; R4 is present as a non-directly-connected comparison. A shared net is **a candidate influence path, not evidence of damage**. The CLI reports the selected failed component, total component count, direct candidates, shared nets, and connectivity-only evidence level.

## Current implementation and next phase

Phase 02 was verified with the repository fixture and an XML export from KiCad 10.0.6's bundled Raspberry Pi HAT schematic (6 components, 35 nets). The real export preserved component metadata and pin-to-net connections through the parser and `--show-pins` CLI. Phase 03 will build on this connection data. Circuit connectivity alone remains an unverified candidate, not damage or risk.

## Scope and caution

- The first supported input is a **KiCad XML netlist** (e.g. exported using KiCad's schematic netlist export).
- Photos, automatic PCB localization, external cloud APIs, and automated energization of damaged boards are **out of scope** for the competition MVP.
- Distinguish **known failed**, **potentially affected**, **measured abnormal**, and **confirmed damaged** components.
- Do not report calibrated failure percentages without real failure-rate/validation data.
- Tests and simulations are not substitutes for safety checks, isolation, and current-limited professional measurement.

## Structure

```text
src/circuitcare/       parser, graph, CLI
tests/                 offline parser/graph tests and KiCad XML fixture
docs/ROADMAP.md        10-phase delivery plan
docs/ARCHITECTURE.md   model assumptions, data contracts, evaluation
```

Future version: align a PCB photo with known EDA coordinates and overlay prioritized test/repair points.

## Attribution
This repository was repurposed from an unrelated Drosophila experiment on 2026-11-01. Old project files are preserved in the `archive/drosomath-before-circuitcare-2026-11-01` branch.
