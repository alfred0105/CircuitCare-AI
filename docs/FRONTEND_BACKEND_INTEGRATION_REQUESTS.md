# Frontend / Backend Integration Requests

Status: requests identified during F0; no backend changes made.

1. Specify project and board identity for projects created from uploaded photos and optional circuit files.
2. Specify intake persistence and supported attachment types/limits, including multiple photos and front/back/detail roles.
3. Specify measurement update and diagnosis refresh inputs/outputs, including `probe_id`, `node_id`, unit, source, timestamp, analysis context, project and board identity. Preserve zero as a valid value.
4. Specify verified component identity mapping between PCB and schematic, with an explicit status and evidence reference.
5. Specify provenance and confidence semantics for diagnosis candidates, recommended measurements and secondary impacts. Define when `CONFIRMED` is valid.
6. Confirm callable service boundaries and optional runtime dependencies for UI-triggered diagnosis refresh.

Current UI work can proceed using frontend-owned models and an explicit demo-only adapter. No request requires edits to diagnosis, SPICE, Bayesian, reconstruction, training or ground-truth engines.
