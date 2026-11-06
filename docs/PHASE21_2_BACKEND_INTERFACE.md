# Phase 21.2 Backend Interface

## Python entry points

- `MultiImageComponentMapService.ingest(board_id, Iterable[PhotoInput]) -> PCBPhotoSession`
- `MultiImageComponentMapService.build_map(session, detector=None, model_path=None) -> dict`
- `MultiImageComponentMapService.fault_overlay(component_map, side, candidates) -> dict`
- `to_json(component_map) -> str`

`PhotoInput.data` is bytes or a local path; `side` must be `TOP` or `BOTTOM`; `role` is `REFERENCE`, `OVERVIEW`, `CLOSEUP`, or `ANGLED`. Optional `rectification_corners_px` contains four corners in the intake decoded-image frame. Data is local; no server, hosted API, database, or LLM is required.

## Map response

`circuitcare.pcb-component-map.v1` includes:

- `board_id`, `processing_status`, timestamps and per-session `resource_limits`
- photo IDs, content SHA-256, side, role, input format/dimensions, duplicate relation, original-byte-preservation flag and optional rectification status/matrix
- separate `sides.TOP` and `sides.BOTTOM` records
- canonical image reference, frame, dimensions, reference-frame canvas origin, PNG artifact and source-photo-index PNG
- per-photo homography, registration status, candidate matches, inliers/ratio, RMSE/P95, overlap and failure reason
- component detections, canonical positions/boxes/polygons, source IDs and original-image boxes, confidence, OCR if provided, identification and fusion status, provenance
- unconfirmed board-boundary candidates, functional-block `NOT_EVALUATED`, warnings and explicit `NOT_INFERRED_FROM_PHOTOS` connectivity state

Photo registration states are `REFERENCE`, `REGISTERED_CANDIDATE`, `UNREGISTERED`, and `DUPLICATE_SKIPPED`. `REGISTERED_CANDIDATE` means sufficient geometric checks passed; it is not independently ground-truth verified. Rectification state likewise distinguishes a geometric candidate from physical validation.

## Fault overlay response

`circuitcare.pcb-fault-overlay.v1` returns board/side/image reference and for every candidate a mapped component ID/position or `UNMAPPED_COMPONENT_ID`, candidate status, ranking, evidence, suggested measurement, measurement result, uncertainty, and registration status. Supported states are `CONFIRMED_FAULT`, `SUSPECTED_FAULT`, `RELATED_COMPONENT`, and `UNDETERMINED`. A confirmed fault requires explicit `confirmed_by_measurement_or_inspection: true`; otherwise the service returns `UNDETERMINED`.

## Fail-closed behavior

| Condition | Response |
|---|---|
| unsupported/corrupt image | typed `MultiImageError` with `INVALID_IMAGE` |
| invalid side/role or empty ID | typed `INVALID_SIDE_OR_ROLE` / `INVALID_BOARD_ID` |
| per-file/session/total-pixel/image-count limit | typed limit error before map is returned |
| invalid/weak/unstable homography or insufficient overlap | `UNREGISTERED`; no detections are placed from that photo |
| canvas budget exceeded | reference-only canonical image; other photos remain unregistered |
| unknown/other-side overlay component | explicit unmapped record; no guessed coordinate |
| model absent | map generation continues, `DETECTOR_NOT_CONFIGURED`, no fabricated detections |

The response keeps image-to-image registrations separate from the Phase 21.1.2 `KICAD_DESIGN` to `IMAGE_RAW` service. This component-map API does not authorize those estimated transforms for electrical or SPICE use.
