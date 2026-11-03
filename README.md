# CircuitCare AI

**Local, lightweight AI-assisted circuit fault propagation analysis and repair prioritization.**

CircuitCare AI aims to answer a practical repair question: **if one component has failed, which *other* components might have been affected, why, and what should be checked next?**

> **Status: Phases 01–09 complete.** The Streamlit dashboard runs live ngspice analyses in an isolated Python subprocess, validates fresh results before displaying them, and keeps measurements and outputs scoped to the selected circuit and fault conditions. Risk levels and posterior weights do **not** determine actual damage or real-world failure probability.

## Core differentiator
- Start from a **known failed component and failure mode**, not just a symptom.
- Track possible **secondary effects** through the circuit topology.
- Verify supported candidate impacts using **normal-vs-fault SPICE simulations** and explicitly configured component limits.
- Use **lightweight local Bayesian inference** and expected information gain to update diagnoses and rank measurements.
- Return **ranked inspection guidance with evidence**, without presenting conditionally weighted hypotheses as real-world failure probabilities.

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 01 | Python environment, conventions, sample data | Complete |
| 02 | KiCad netlist parser | Complete; verified with KiCad 10.0.6 export |
| 03 | Component-net graph and affected-neighbor candidates | Complete |
| 04 | Failure modes and fault injection models | Complete; simulation not run |
| 05 | ngspice baseline/fault electrical comparisons | Complete; supported demo circuit verified |
| 06 | Secondary-damage stress assessment and evidence | Complete; overvoltage demo flags C1 above its declared demo rating |
| 07 | Local lightweight AI and active measurement ranking | Complete; simulated measurement updates hypothesis posterior |
| 08 | Evidence-grounded repair recommendations and audit trail | Complete; local Ollama explanation plus deterministic fallback |
| 09 | UI, benchmark, offline evaluation | Complete; divider and RC live runs verified in the dashboard, with fault-scoped session state and accumulated Bayesian measurements |
| 10 | Stabilization, poster, reproducible demo | Planned |

Full acceptance criteria: [docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start

Requires Python 3.11+ (Python 3.11 is the CI baseline; Python 3.12 also works).

```bash
python -m pip install -e ".[dev]"
circuitcare --netlist tests/fixtures/simple_kicad_netlist.xml --fault U1
python -m pytest -q
```

For the integrated dashboard, install the optional UI dependency and start Streamlit:

```bash
python -m pip install -e ".[ui]"
streamlit run src/circuitcare/ui.py
```

The dashboard has circuit/fault, SPICE, rating risk, Bayesian diagnosis, and local LLM tabs. It opens the saved 5 V→8 V regulator demo by default; the divider and RC charging examples can also be run with ngspice. The app labels cached results separately from live runs. User measurements and simulated demo measurements are distinguished, and Ollama is called only after an explicit question. Without Ollama, deterministic advice remains available.

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

To compare fault-case stress against explicit component ratings and create `risk_assessment.json`, add `--ratings` and `--assess-risk`:

```bash
circuitcare --netlist tests/fixtures/fault_demo_netlist.xml --fault U1 \
  --fault-type regulator_output_rise --fault-value 8 \
  --spice-base data/circuits/fault_demo.cir \
  --spice-mapping data/circuits/fault_demo_mapping.json \
  --output data/fault_scenarios/overvoltage_demo \
  --simulate --probes data/circuits/fault_demo_probes.json \
  --ratings data/component_specs/fault_demo_ratings.json --assess-risk
```

The demo raises the ideal 5 V output to 8 V. C1 is measured at 8 V against an explicitly labeled, unverified 6.3 V demo assumption (utilization 1.27, `EXCEEDED`). RLOAD dissipates 16 mW against a 125 mW demo assumption (`WITHIN_LIMIT`). Those rating values are illustrative and are not verified against component datasheets. The priority score is an explainable inspection ordering index, never a damage probability. Missing ratings or probes remain `UNKNOWN`; Q1 is excluded from physical ranking because its fixture pins do not map consistently to the SPICE switch terminals. Capacitor current, ESR loss, and heating are not calculated.

Run prior-only diagnosis from stored SPICE and risk JSON, then rerun with a measurement:

```bash
circuitcare-diagnose --hypotheses data/diagnosis/demo_hypotheses.json \
  --output data/diagnosis/prior_results
circuitcare-diagnose --hypotheses data/diagnosis/demo_hypotheses.json \
  --measurements data/diagnosis/demo_measurements.json \
  --output data/diagnosis/posterior_results
```

The three hypotheses reference saved 3 V, 6 V, and 8 V ngspice results; predicted node voltages are loaded from each `comparison.json`, not embedded in the diagnosis code. Priors are equal weights, and voltage measurement σ=0.2 V is a labeled demo assumption. The example 7.9 V observation is marked `simulated_demo`; it moves the 8 V hypothesis from 1/3 prior weight to approximately 1.0 conditional posterior. Before measurement, VOUT has the highest calculated information gain; after measuring VOUT it is excluded, and the remaining LOAD prediction is not informative enough to recommend another measurement. Outputs contain posterior history, measurement recommendations, and prior/posterior weighted inspection indices. These conditional values are not real-world failure probabilities, and measurement suggestions do not authorize live probing.

For evidence-backed repair guidance, install Ollama separately and pull a local model (for example, `ollama pull qwen3:4b-instruct`). The advisor never sends data to a cloud API. It checks the local Ollama model list, uses only evidence JSON from the diagnosis, inspection ranking, measurement recommendation, and optional risk/stress reports, then writes `repair_advice.json`, `evidence.json`, and `llm_explanation.json`:

```bash
circuitcare-advise \
  --diagnosis data/diagnosis/posterior_results/diagnosis.json \
  --inspection-ranking data/diagnosis/posterior_results/inspection_ranking.json \
  --measurement-recommendations data/diagnosis/posterior_results/measurement_recommendations.json \
  --model qwen3:4b-instruct \
  --question 'C1을 왜 먼저 점검해야 해?' \
  --output data/repair_advice/example
```

Use `--no-llm` to produce deterministic isolation, inspection, replacement, and post-repair checks without model inference. An installed local model can be selected with `--model`; Phase 08 was exercised with `gemma4:12b` on Ollama 0.40.3. Ollama 0.40.3 does not support structured output for this model, so the client retries once in plain-text mode and validates the returned JSON and evidence references locally. Model explanations are rejected on invalid or unsupported claims, leaving the deterministic advice available. Output labels simulation/demo assumptions and unknowns separately; the model is not allowed to assert damage or convert conditional posterior weights into real failure probabilities.

## Current implementation and next phase

Phases 01–09 are implemented. Phase 09 adds the dashboard and two distinct small circuit topologies (resistor divider and RC charging) with reproducible live ngspice evaluations. The dashboard runs each analysis in a separate Python subprocess using a unique output directory, and activates a result only after checking the process status, scenario identity, simulation status, and newly written reports. Divider R1 drift and RC RCHARGE drift were both run successfully from the dashboard; the divider showed LOAD changing from 2.5 V to about 0.455 V, and the RC view showed its normal/fault waveform. Session data is keyed to the circuit files and fault settings; measurements accumulate by node, replace earlier values for the same node, and can be cleared to recompute prior-only results. See [the Phase 09 summary](data/evaluations/phase09_summary.json) and run `python scripts/evaluate.py` to regenerate it. Timings and memory are local observations, not general performance guarantees. Only explicitly supplied ratings and supported measurements are evaluated. Posterior weights are conditional on the configured hypothesis set and do not estimate real-world failure probability or confirm damage.

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
