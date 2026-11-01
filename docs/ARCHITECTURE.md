# Architecture and evidence policy

## Workflow
1. Input: KiCad XML netlist, failed reference, **specified failure mode** and optional measurement evidence.
2. Parse components, references, pins, and nets into a typed representation.
3. Find candidate electrically connected components using a **bipartite** component/net graph; paths show potential propagation only.
4. Generate supported baseline/fault SPICE scenarios; never treat unsupported components as valid simulations.
5. Calculate pin-level changes and compare them with **part-specific** ratings and scenario exposure time.
6. Rank inspection candidates using interpretable features and/or lightweight local inference.
7. Suggest next safe diagnostic measurement; update ranking only when real measurements are provided.
8. Export an evidence-bearing report. Photo/PCB overlays are future scope.

## Integrity requirements
- Electrical connectivity is not directional. Power flow and damaging fault propagation require device models, topology, current paths, and boundary conditions.
- 'Potentially affected' != 'damaged'. A pin exceeding an absolute maximum does not establish an empirical damage probability.
- Separate fault-present stress, stress-duration assumptions, device ratings, and verified physical damage.
- A simulator error is not evidence of a safe circuit.
- No ungrounded probabilities; use ordinal risk and explicit uncertainty until calibration data exist.
- Circuit-family split during evaluation (not random splits of scenarios from the same circuit). Compare graph-only and physics-only baselines.
- Local-first: no telemetry, cloud API, or remote dependency in the core pipeline.

## Data model (bootstrap)
- `Component(ref, value, library_id)`
- `Connection(ref, pin, net)`
- `Circuit(components, connections)`
- `CandidateImpact(target_ref, shared_nets, evidence_level="connectivity_only")`

Planned extensions: `FaultScenario`, `ElectricalStress`, `Measurement`, `RiskAssessment`, `RepairRecommendation`, with provenance.

## Repair safety
Default to power-off inspection. Avoid powering damaged boards until basic isolation and short-circuit checks are complete. Physical test procedures should be scoped to suitable low-voltage laboratory circuits and safe, current-limited supplies.
