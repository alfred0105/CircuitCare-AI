# Frontend / Backend Contract

Status: frontend contract on `frontend/workbench-v2`, updated after backend Phase 21.1.2 (`8f68af7`; current `origin/main` also includes `29d710e`). This document does not change backend schemas or promise API availability.

## Boundary

The frontend owns view models in `circuitcare.frontend.models`. Adapters translate between those models and current backend outputs. UI code must not depend directly on diagnosis-engine internals. A backend result is displayable as a confirmed fault only when its provenance explicitly verifies that conclusion; absent or unverified data remains neutral/unknown.

The current product direction is photo-first: recognize visible components, combine multiple views of the same board where registration is supported, infer only evidence-bounded functional relationships, and use symptoms and measurements to rank diagnostic candidates. Complete board-design reconstruction is not an intake prerequisite. Visual contact, detected proximity, and PCB trace appearance are not verified electrical connectivity. A schematic or KiCad export is optional supporting evidence.

Existing reusable surfaces include `dashboard/views/schematic_workspace.py` with `schematic/viewer.py` and SVG interaction assets, plus the photo workflow in `vision_ui.py`. Existing `workspace.models.WorkspaceContext` and measurement provenance are existing workspace contracts and are not replaced by these UI models.

## Frontend view models

| Model | Fields | Notes |
| --- | --- | --- |
| `ProjectContext` | `project_id`, `board_id`, `image_records`, `symptom_category`, `symptom_description`, `circuit_source`, `input_fingerprint` | Session-local intake state in F1.1; IDs are distinct from content hashes. |
| `ImageRecord` | `image_id`, `content_sha256`, `media_type`, `side`, `capture_type`, `image_dimensions`, `image_format`, `filename` | `side`: `front` / `back` / `unknown`. `capture_type`: `full_view` / `close_up` / `oblique` / `marking_detail` / `unknown`. |
| `ComponentViewModel` | `component_ref`, `display_name`, `location`, `mapping_status`, `diagnostic_status`, `evidence_ids` | Mapping and diagnostic confidence are separate. `CONFIRMED` requires verified evidence. |
| `MeasurementViewModel` | `probe_id`, `component_ref`, `node_id`, `value`, `unit`, `source`, `timestamp`, `analysis_context_id` | `value=0` is valid; `None` means absent. |
| `DiagnosisSummaryViewModel` | `overall_status`, `candidate_components`, `suggested_measurements`, `secondary_risks`, `verification_status`, `provenance` | Empty collections mean no supplied items, not a negative result. |
| `SelectionState` | `project_id`, `board_id`, `selected_component`, `selected_probe`, `active_tab` | Only PCB/schematic tabs. Cross-view synchronization requires verified component mapping. |

These are presentation contracts, not a replacement for backend domain types.

## Adapter expectations

The current application is a local Streamlit UI rather than a versioned HTTP API. Existing integration points include `load_netlist`, `build_workspace_context`, `dashboard.analysis_loader.load_analysis_snapshot`, measurement diagnosis service functions, `workspace.measurement_provenance`, the schematic viewer callback and the existing vision UI. Adapters will consume these behind a frontend-owned interface and preserve existing provenance/context checks.

`MockDiagnosisAdapter` returns no candidate or measurement claims and marks every response `source=MOCK`, `verification_status=DEMO_ONLY`. Inject it explicitly and show it as demo data; it must not be the production default. A mock measurement update acknowledges request shape only and never claims analysis was recalculated.

`frontend.photo_adapter.adapt_photo_record()` is the only F1.1 boundary to backend `PhotoRecord`. It carries project/board ownership alongside the backend record because `PhotoRecord` itself does not contain those IDs. It maps `image_id` to `photo_id` and preserves the original content hash. Unspecified capture type remains unspecified and returns `UNSUPPORTED`; the current photo collector must never silently turn it into `full_view`. The adapter validates metadata only; it does not run detection or registration.

Backend Phase 21.1.2 exposes a bounded registration service that requires design-reference geometry. It can return a design-assisted estimate, but its result is not independently verified without reviewed held-out validation and a predeclared threshold. A photo-only intake must not fabricate design geometry or treat a registration estimate as verified.

## Integration gaps

1. Stable project and board identifiers for projects created from uploads; current workspace context is circuit-oriented and requires an existing netlist.
2. Intake persistence/API boundary for multiple PCB images, symptoms and optional schematic/KiCad attachments, including a content fingerprint.
3. Probe/node measurement payload and response provenance for physical measurements. Current diagnosis flows accept node/value/unit/source-shaped records, but UI probe and project/board identity are not one shared API.
4. Verified PCB-reference-to-schematic-reference mapping with explicit mapping status. Until available, do not synchronize selection automatically.
5. Stable result fields and verification semantics for candidates, next measurements, secondary risks and evidence.
6. UI-safe service boundaries and optional runtime requirements for diagnosis refresh.

## F1.1 photo intake contract

The intake payload includes `project_id`, `board_id`, `image_id`, `content_sha256`, `side`, `capture_type`, `image_dimensions` and `input_fingerprint`. Existing F1 limits remain: up to eight photos, 80 MB aggregate, 20 MB per photo, and the existing 25-million-pixel decoder cap. `image_id` is a record UUID, distinct from SHA-256, `project_id` and `board_id`. Changing metadata does not alter the source image hash.

F1.1 supports legacy intake metadata where old `side=detail` and no `capture_type` means `side=unknown`, `capture_type=close_up`. The current UI does not emit this legacy shape. Unknown `capture_type` is valid for creating a project draft but cannot enter `collect_photos()` until the backend accepts it or the user classifies the image. No silent default is applied.

The generated `ProjectContext` is session-local; it is not durable storage and does not invoke diagnosis. **입력 수정** removes the current draft/analysis state while retaining editable inputs. **새 프로젝트** clears current project inputs and namespaced widget state but leaves any unrelated or persisted data untouched. The legacy demo remains reachable and the existing UI remains the default when the feature flag is unset.
