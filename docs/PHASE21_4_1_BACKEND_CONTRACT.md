# Phase 21.4.1 Backend Contract

## Schema

Top-level schema: `circuitcare.pcb-pin-hypothesis.v1`. Input is the existing serialized Component Map. The result preserves its board ID, source schema version, component IDs, TOP/BOTTOM split, source photo IDs, and measurement-history references.

Each component result includes:

- `component_id`, `component_type`, `board_side`, `source_image_ids`
- `coordinate_frame`: `MOSAIC_PIXEL` when derived from the current multi-image map, or `CANONICAL_IMAGE_PIXEL` for a direct component estimate
- `component_bbox_xyxy`
- `package_hypotheses[]`: candidate type/count, evidence, side counts, Pin 1 candidate status, geometry terminal templates, and optional separate `observed_pad_candidates[]`
- `terminals[]`: used for two-terminal parts; multi-pin terminal templates stay nested under each package alternative
- `status`, `warnings`, `measurement_history_refs`
- `electrical_connectivity: NOT_EVALUATED`

Terminal `pin_number` is `null` and `pin_function` is `UNKNOWN_FUNCTION` unless a user explicitly supplies a manual correction. Position status is `OBSERVED_TERMINAL`, `GEOMETRY_ESTIMATED`, `MANUAL_CONFIRMED`, or `UNRESOLVED`. Appearance scores carry `score_kind: RULE_BASED_NOT_CALIBRATED`; they are not calibrated probabilities.

Example:

```json
{
  "component_id": "component-r1",
  "component_type": "resistor",
  "board_side": "TOP",
  "coordinate_frame": "MOSAIC_PIXEL",
  "terminals": [
    {
      "terminal_id": "terminal_a",
      "pin_number": null,
      "pin_function": "UNKNOWN_FUNCTION",
      "position_xy": [120.0, 85.0],
      "coordinate_frame": "MOSAIC_PIXEL",
      "position_status": "GEOMETRY_ESTIMATED",
      "evidence": ["BODY_LONG_AXIS", "BODY_BOUNDING_GEOMETRY"],
      "review_required": true
    }
  ],
  "electrical_connectivity": "NOT_EVALUATED"
}
```

## Manual edits

```python
updated = PinHypothesisService().apply_manual_edits(
    pin_map,
    [{"component_id": "component-r1", "terminal_id": "terminal_a",
      "position_xy": [118.5, 84.0], "pin_number": "1"}],
    reviewer_id="technician-01",
)
```

Coordinates must remain finite and in the target image frame. The edit updates a copy, adds reviewer provenance, and leaves component IDs and measurement references unchanged. Electrical connectivity remains not evaluated.

## Overlay

`terminal_overlay_contract(pin_map)` emits `circuitcare.pcb-terminal-overlay.v1` rows with board side, component and terminal IDs, canonical position, position status, evidence, and `connectivity_status: NOT_EVALUATED`. It is an overlay data interface only; no frontend files are changed.

## Failure behavior and safety

- Invalid/missing bounding box or unsupported coordinate frame returns an unresolved component record.
- Missing canonical image skips visual pad extraction but still permits geometry-only candidates.
- Ambiguous/conflicting Component Map identity blocks terminal geometry from merged observations.
- Hidden QFN/BGA leads are not synthesized as observed terminals.
- Package suggestions do not number pins or assign VCC/GND/IN/OUT functions.
- No output represents a trace, net, continuity result, fault probability or measurement conclusion.
