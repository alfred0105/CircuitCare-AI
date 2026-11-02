# CircuitCare AI

**Local, lightweight AI-assisted circuit fault propagation analysis and repair prioritization.**

CircuitCare AI aims to answer a practical repair question: **if one component has failed, which *other* components might have been affected, why, and what should be checked next?**

> **Status: Phases 01–05 complete.** The CLI parses KiCad XML netlists, reports connectivity candidates, generates explicitly mapped SPICE fault scenarios, and compares supported baseline/fault transient simulations. It does **not** determine actual damage or failure probability. Do not use its output to approve a live repair.

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
| 03 | Component-net graph and affected-neighbor candidates | Complete |
| 04 | Failure modes and fault injection models | Complete; simulation not run |
| 05 | ngspice baseline/fault electrical comparisons | Complete; supported demo circuit verified |
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

To list direct and indirect connectivity paths (two component hops by default), use `--show-paths`. Export the bipartite graph as DOT with `--export-dot`:

```bash
circuitcare --netlist tests/fixtures/simple_kicad_netlist.xml --fault U1 --show-paths --max-hops 2
circuitcare --netlist tests/fixtures/simple_kicad_netlist.xml --fault U1 --export-dot circuit_graph.dot
```

Net types are unknown unless explicitly supplied in a JSON mapping such as `{"GND":"ground","VIN":"power","VOUT":"power","SIGNAL":"signal"}` using `--net-types net-types.json`. `--exclude-net-types ground` filters ground paths from path traversal while retaining them in the graph and direct connectivity results. This filter does not imply that a real effect cannot travel through GND.

Generate a faulted SPICE circuit using the explicit KiCad-to-SPICE mapping and starter circuit:

```bash
circuitcare --netlist tests/fixtures/fault_demo_netlist.xml --fault R1 \
  --fault-type resistance_drift --fault-value 10k \
  --spice-base data/circuits/fault_demo.cir \
  --spice-mapping data/circuits/fault_demo_mapping.json \
  --output data/fault_scenarios
```

This writes `baseline.cir`, a faulted `.cir`, and `scenarios.json`. Supported scenarios include resistor open/short/drift, ideal regulator output rise/drop/loss, and mapped voltage-controlled switch stuck-open/stuck-on. These are stated approximations; scenario generation does not run a simulator. The committed `data/fault_scenarios/` files show resistor open, short, and 10 kΩ drift examples.

To run both baseline and faulted decks with ngspice and compare probe data, add `--simulate` and `--probes`:

```bash
circuitcare --netlist tests/fixtures/fault_demo_netlist.xml --fault R1 \
  --fault-type resistance_drift --fault-value 10k \
  --spice-base data/circuits/fault_demo.cir \
  --spice-mapping data/circuits/fault_demo_mapping.json \
  --output data/fault_scenarios/example_001 \
  --simulate --probes data/circuits/fault_demo_probes.json
```

ngspice must be installed (`brew install ngspice` on macOS). The runner saves logs and CSV samples; comparison and component stress summaries are JSON. The example uses a 5 V source and two 1 kΩ resistors: LOAD measures 2.5 V at baseline and about 0.455 V with R1 at 10 kΩ. Resistor current/power use the mapped terminals and actual netlist resistance; ideal voltage-source current comes from ngspice. Unsupported switch current/power are left null. These are simulated electrical changes, not damage or rating assessments.

The included sample intentionally connects U1 to J1, U2 and C3; R4 is present as a non-directly-connected comparison. A shared net is **a candidate influence path, not evidence of damage**. The CLI reports the selected failed component, total component count, direct candidates, shared nets, and connectivity-only evidence level.

## Current implementation and next phase

Phases 01–05 are implemented: KiCad component/net data becomes a bipartite graph; the CLI enumerates paths, exports DOT, generates explicitly mapped fault decks, runs baseline and fault decks in ngspice, and saves node and supported component comparisons. Net roles remain user-supplied. Simulation changes are not damage assessments, and ratings are not evaluated in this phase.

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
