# CircuitCare AI — 10-phase plan

**Competition:** poster due 2026-11-23; presentation 2026-11-27. Dates are planning targets, not progress claims.

## Phase 01 — Repository bootstrap (Nov 2) — Complete
Python 3.11+ package metadata, offline CLI, KiCad XML fixture, baseline connectivity models, README, roadmap, and Python 3.11 CI are in place. The fixture contains J1, U1, U2, C3, and R4; selecting U1 lists direct candidates and their shared nets without claiming damage.
**Complete when:** editable package installation succeeds, the sample CLI runs, and the existing test suite passes. Verified against the Phase 01 fixture and existing offline tests. No additional runtime dependencies are needed.

## Phase 02 — KiCad XML netlist ingestion (Nov 2–3) — Complete
Extract component references, values, library IDs, optional footprint and datasheet, pin-to-net connections, and net codes. Assign unique names to unnamed nets, deduplicate repeated identical pin links, reject conflicting pin assignments, and sort parsed data deterministically. Verified against the repository fixture and a KiCad 10.0.6 XML export from its bundled Raspberry Pi HAT schematic (6 components, 35 nets).
**Complete when:** deterministic extraction from fixture and real KiCad XML is verified. Do not infer electrical function from net names alone.

## Phase 03 — Connectivity and candidate influence (Nov 4) — Complete
Build a typed component–net bipartite graph with pin-preserving edges. Find direct and indirect simple paths up to the requested component-hop limit, keep candidate evidence at `connectivity_only`, and export fault/path-highlighted Graphviz DOT. Optional net types come only from user-supplied metadata; GND paths remain present unless explicitly filtered for traversal, and filtering is not a safety conclusion.
**Complete when:** CLI path output distinguishes direct and indirect candidates, identifies path nets and hop counts, and DOT contains component/net nodes and pin-labeled edges.

## Phase 04 — Failure-mode library (Nov 5–6) — Complete
Add controlled resistor open/short/drift, ideal regulator output rise/drop/loss, and explicitly mapped voltage-controlled switch stuck-open/stuck-on models. Require an explicit KiCad-reference-to-SPICE-element mapping, retain the original baseline, and save scenario assumptions and change records.
**Complete when:** three reproducible resistor scenarios and supported regulator/switch scenarios generate faulted SPICE netlists and metadata. Simulation is not run in this phase; the regulator output and switch are documented abstractions, not component-accurate failure mechanisms.

## Phase 05 — Physics-backed propagation (Nov 7–9) — Complete
Run transient ngspice baseline and fault decks from temporary instrumented copies. Save logs and CSV samples; align differing time axes over their shared interval; report probe-node voltage deltas and supported component voltage/current/power changes. Resistor current and dissipation use measured terminal voltage and each deck's actual resistance; ideal voltage-source current uses ngspice's branch-current sign convention. Unsupported current/power stay null with a reason.
**Complete when:** the supported 5 V divider runs in ngspice, R1 drift changes LOAD from 2.5 V to about 0.455 V, component changes are saved, and simulator failures cannot be marked successful. This is electrical simulation evidence, not proof of damage or a rating assessment.

## Phase 06 — Secondary-damage risk assessment (Nov 10–12) — Complete
Load explicit per-component voltage/current/power ratings with source and duration metadata. Compare supported fault-case peak stress, retain baseline deltas, calculate utilization, and classify `EXCEEDED`, `NEAR_LIMIT`, `WITHIN_LIMIT`, or `UNKNOWN`. Rank secondary inspection candidates with a deterministic 0–100 priority index and retain a separate connectivity-only order. Capacitors support terminal-voltage-only evaluation; unsupported current and power remain unknown. Demo ratings are labeled assumptions, not datasheet facts; damage probability is not estimated.
**Complete when:** the ngspice 5 V→8 V output-rise scenario identifies C1 at 8 V / 6.3 V = 1.27 utilization as `EXCEEDED`, RLOAD at 16 mW / 125 mW as `WITHIN_LIMIT`, writes `risk_assessment.json`, and leaves unknown/unmapped candidates out of false safety conclusions. Q1's inconsistent KiCad/SPICE terminal mapping is explicitly excluded from physical ranking.

## Phase 07 — Local AI and next-test selection (Nov 13–15) — Complete
Load hypothesis-specific predictions and risk reports from saved Phase 05/06 JSON. Apply sequential log-space Gaussian Bayesian updates using explicit positive voltage σ, report model mismatch when all hypotheses are more than 4σ from observed values, and select unused configured low-voltage demo nodes by deterministic numerical expected information gain. Recompute posterior-weighted inspection indices while preserving each scenario's rating-exceedance evidence. The CLI is `circuitcare-diagnose`; no model training or network access is required.
**Complete when:** equal-prior 3 V / 6 V / 8 V saved scenarios produce prior-only output and an active VOUT recommendation; a 7.9 V ±0.2 V simulated-demo observation updates the 8 V hypothesis to about 1.0 conditional posterior; measured VOUT is excluded from further recommendations; inspection score changes with the posterior; RLOAD power reduction does not earn stress-increase points. Conditional posterior values are not field failure probabilities, and recommendations are not live-work safety approval.

## Phase 08 — Repair advisory (Nov 16–17)
Recommend next inspection, safe isolation steps, replacement checks, and post-repair validation.
**Done when:** report separates facts, assumptions, and suggestions with a traceable explanation.

## Phase 09 — Integration, offline demo, benchmark (Nov 18–21)
Build a minimal UI and evaluate 2–3 held-out circuit families; record latency/memory, top-k coverage and avoidable inspections.
**Done when:** reproducible offline flow and non-leaky comparisons are available.

## Phase 10 — Release and presentation (Nov 22–27)
Freeze core demo, publish limitations, document test evidence, prepare poster by Nov 23 and five-minute explanation.
**Done when:** project starts offline and no demonstrated result depends on invented data.

## Explicit future scope
PCB image alignment, camera overlay of risk/test points, instrument control, broad IC model ingestion, and probabilistically calibrated field-failure forecasts.

## Development practice
Implement → focused test → commit → next phase. Prioritize end-to-end execution over excessive pre-implementation checks. Do not mark a phase complete solely because scaffolding exists.
