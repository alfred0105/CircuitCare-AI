# CircuitCare AI — 10-phase plan

**Competition:** poster due 2026-11-23; presentation 2026-11-27. Dates are planning targets, not progress claims.

## Phase 01 — Repository bootstrap (Nov 1)
Set up Python package, unit-test entry point, baseline fixture, versioned docs, and CI.
**Done when:** sample command starts and tests are runnable. Avoid external dependencies in the minimal parser.

## Phase 02 — KiCad XML netlist ingestion (Nov 2–3)
Parse components, values, refs, pin-to-net links; report missing and malformed data.
**Done when:** deterministically extract components and nets from a sample KiCad-exported XML netlist. Do not infer electrical function from net names alone.

## Phase 03 — Connectivity and candidate influence (Nov 4)
Build a component–net bipartite graph and report direct connected candidates, ordered paths, and evidence.
**Done when:** user selects failed component; connected candidate components and shared nets appear. Explicitly label graph-only findings as **unverified**.

## Phase 04 — Failure-mode library (Nov 5–6)
Add controlled fault templates: open/short, resistor drift, regulator output fault, and MOSFET switch fault. Require explicit scenario metadata and valid component model.
**Done when:** at least three supported scenarios produce reproducible faulted SPICE netlists.

## Phase 05 — Physics-backed propagation (Nov 7–9)
Compare ngspice baseline vs fault case by pin: voltage, current, power, transients, time exposure.
**Done when:** simulate one supported low-voltage circuit, show impact changes and simulator failures transparently.

## Phase 06 — Secondary-damage risk assessment (Nov 10–12)
Read part-specific ratings and aggregate stress indicators; distinguish out-of-spec stress vs observed damage.
**Done when:** produce explainable ranked inspection candidates with rating evidence, plus a graph-only baseline comparison.

## Phase 07 — Local AI and next-test selection (Nov 13–15)
Use small classical ML/Bayesian inference; condition rankings on measurement evidence; prefer expected diagnostic value.
**Done when:** new offline measurement changes candidate ranking and next suggested safe test. Compare against deterministic baseline; retain it if ML is not better.

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
