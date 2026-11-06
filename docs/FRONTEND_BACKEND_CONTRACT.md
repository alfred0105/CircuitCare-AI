# Frontend / Backend Contract

Status: frontend proposal, established from `origin/main` at `396f8f826500a97b8bff2d306ef55f78b61f5304` (2026-11-06). This document does not change backend schemas or promise API availability.

## Boundary

The frontend owns view models in `circuitcare.frontend.models`. Adapters translate between those models and current backend outputs. UI code must not depend directly on diagnosis-engine internals. A backend result is displayable as a confirmed fault only when its provenance explicitly verifies that conclusion; absent or unverified data remains neutral/unknown.

Existing reusable surfaces include `dashboard/views/schematic_workspace.py` with `schematic/viewer.py` and SVG interaction assets, plus the photo workflow in `vision_ui.py`. Existing `workspace.models.WorkspaceContext` and measurement provenance are existing workspace contracts and are not replaced by these UI models.

## Frontend view models

| Model | Fields | Notes |
| --- | --- | --- |
| `ProjectContext` | `project_id`, `board_id`, `image_records`, `symptom_category`, `symptom_description`, `circuit_source`, `input_fingerprint` | Intake state. `ImageRecord` carries image ID, side, filename, digest and media type. |
| `ComponentViewModel` | `component_ref`, `display_name`, `location`, `mapping_status`, `diagnostic_status`, `evidence_ids` | Mapping and diagnostic confidence are separate. `CONFIRMED` requires verified evidence. |
| `MeasurementViewModel` | `probe_id`, `component_ref`, `node_id`, `value`, `unit`, `source`, `timestamp`, `analysis_context_id` | `value=0` is valid; `None` means absent. |
| `DiagnosisSummaryViewModel` | `overall_status`, `candidate_components`, `suggested_measurements`, `secondary_risks`, `verification_status`, `provenance` | Empty collections mean no supplied items, not a negative result. |
| `SelectionState` | `project_id`, `board_id`, `selected_component`, `selected_probe`, `active_tab` | Only PCB/schematic tabs. Cross-view synchronization requires verified component mapping. |

These are presentation contracts, not a replacement for backend domain types.

## Adapter expectations

The current application is a local Streamlit UI rather than a versioned HTTP API. Existing integration points include `load_netlist`, `build_workspace_context`, `dashboard.analysis_loader.load_analysis_snapshot`, measurement diagnosis service functions, `workspace.measurement_provenance`, the schematic viewer callback and the existing vision UI. Adapters will consume these behind a frontend-owned interface and preserve existing provenance/context checks.

`MockDiagnosisAdapter` returns no candidate or measurement claims and marks every response `source=MOCK`, `verification_status=DEMO_ONLY`. Inject it explicitly and show it as demo data; it must not be the production default. A mock measurement update acknowledges request shape only and never claims analysis was recalculated.

## Integration gaps

1. Stable project and board identifiers for projects created from uploads; current workspace context is circuit-oriented and requires an existing netlist.
2. Intake persistence/API boundary for multiple PCB images, symptoms and optional schematic/KiCad attachments, including a content fingerprint.
3. Probe/node measurement payload and response provenance for physical measurements. Current diagnosis flows accept node/value/unit/source-shaped records, but UI probe and project/board identity are not one shared API.
4. Verified PCB-reference-to-schematic-reference mapping with explicit mapping status. Until available, do not synchronize selection automatically.
5. Stable result fields and verification semantics for candidates, next measurements, secondary risks and evidence.
6. UI-safe service boundaries and optional runtime requirements for diagnosis refresh.

## F1 boundary

F1 provides a real intake screen behind `CIRCUITCARE_UI_V2=1`. It uses the existing bounded image decoder (20 MB per image, 25 million pixels), a UI cap of eight photos/80 MB aggregate, and accepts currently parsed KiCad XML Netlist and `.kicad_sch` files. The generated `ProjectContext` is session-local; it is not durable project storage and does not invoke diagnosis. The legacy demo remains reachable from the intake screen and the legacy UI remains the default when the flag is unset.
