# Frontend / Backend Integration Requests

Status: frontend requests after F1.1 review of backend `origin/main` at `8f68af7`/`29d710e`; no backend changes made.

F1 now creates a session-only UI project draft behind `CIRCUITCARE_UI_V2=1`. It does not persist projects or run diagnosis. The existing legacy UI remains the default without the flag.

1. Specify project and board identity for projects created from uploaded photos and optional circuit files.
2. Specify intake persistence and supported attachment types/limits, including multiple photos and front/back/detail roles.
3. Specify measurement update and diagnosis refresh inputs/outputs, including `probe_id`, `node_id`, unit, source, timestamp, analysis context, project and board identity. Preserve zero as a valid value.
4. Specify verified component identity mapping between PCB and schematic, with an explicit status and evidence reference.
5. Specify provenance and confidence semantics for diagnosis candidates, recommended measurements and secondary impacts. Define when `CONFIRMED` is valid.
6. Confirm callable service boundaries and optional runtime dependencies for UI-triggered diagnosis refresh.

Current UI work can proceed using frontend-owned models and an explicit demo-only adapter. No request requires edits to diagnosis, SPICE, Bayesian, reconstruction, training or ground-truth engines.

## Photo-first direction / Phase 21.1.2

1. Add or document a multi-photo analysis entry point that accepts project/board IDs and each source `photo_id`, hash, side, capture type and original dimensions, without requiring full KiCad board reconstruction.
2. Define how an unspecified `capture_type` is handled by backend processing. Current `collect_photos()` accepts four known capture types and otherwise defaults omitted values to `full_view`; the frontend adapter deliberately withholds unknown types rather than making that assumption.
3. Define an image-only analysis/registration path or explicitly state which analyses require design-reference geometry. Current Phase 21.1.2 registration service requires `design_reference_geometry`; photo-only input must not fabricate it.
4. Specify per-photo registration results keyed by original photo ID, including frames, board side, verification status, provenance, and resource failures. An automatic estimate without independent held-out validation must remain unverified and cannot drive a verified overlay.
5. Specify component detection and reference-mapping output contracts so detected visual components remain separate from design-confirmed references.
6. Confirm project and board persistence/identity semantics. F1.1 IDs and image bytes are session-local and do not provide durable storage.

These are integration requests for later phases. F1.1 only creates/validates intake records and exercises the metadata adapter; it does not call registration, component detection, topology reconstruction or diagnosis.
