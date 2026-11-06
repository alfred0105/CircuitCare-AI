# Phase 21.4.1 — Pin & Terminal Hypothesis Engine

## Scope and result

This backend accepts an existing CircuitCare Component Map and emits reviewable terminal-location and package hypotheses in that map's canonical image coordinate frame. It does not reconstruct traces, assert electrical nets, or alter existing component identity or measurement-history references.

For two-terminal resistor, capacitor, inductor, diode and fuse candidates, the component polygon/body axis yields two geometry-only terminal positions. When the source image is present, a bounded local ROI searches for bright, low-saturation regions near those ends. A matched region is marked `OBSERVED_TERMINAL`; this is still a visual appearance candidate and requires review because solder glare, silkscreen, vias and copper can look similar. If no candidate is found, the endpoint remains `GEOMETRY_ESTIMATED`. Diode polarity remains `UNKNOWN_POLARITY`.

For multi-pin parts, a declared `pin_count` and optional `package_hint` produce package alternatives and perimeter terminal templates. Pin count alone never confirms a package. SOIC-8 and DIP-8 remain separate candidates when evidence does not distinguish them. Unverified Pin 1 remains unresolved. Optional local appearance candidates are listed separately from the generated package geometry. QFN/BGA hints produce no visible lead coordinates.

If the existing map marks a component identity `IDENTITY_AMBIGUOUS` or `IDENTITY_CONFLICT`, the engine returns an unresolved hypothesis instead of estimating from potentially merged geometry. TOP and BOTTOM are processed separately. The stored component ID and measurement references are copied through.

## Run

The component-map module can be called directly:

```python
from circuitcare.vision.pin_estimation import estimate_component_map

pin_map = estimate_component_map(component_map)
```

The standalone smoke/benchmark command supports synthetic fixtures or a previously saved Component Map JSON:

```bash
python scripts/benchmark_pin_estimation.py \
  --fixture synthetic \
  --output reports/pin_estimation.json

python scripts/benchmark_pin_estimation.py \
  --component-map data/pin_input/component_map.json \
  --output reports/pin_estimation.json
```

The second command reports localization and classification metrics as `NOT_EVALUATED` unless pin-specific reviewed ground truth is added in a future evaluation input contract. It still writes candidate hypotheses and measured runtime.

## Manual correction and overlay

`PinHypothesisService.apply_manual_edits()` returns a copied map, records reviewer ID and review method, and marks changed positions `MANUAL_CONFIRMED`. Multipin edits specify `package_type` when the same temporary terminal ID appears in multiple hypotheses. `terminal_overlay_contract()` exposes canonical positions, side, status, evidence and review requirement for future frontend use.

The output carries `electrical_connectivity: NOT_EVALUATED` at all levels. A later connection-candidate engine should consume only user-confirmed or separately design-linked pin evidence and must not treat pin proximity or visual pad appearance as electrical continuity.

## Current verification limit

Unit and synthetic fixtures cover horizontal, vertical and rotated two-terminal bodies, visible-pad appearance candidates, SOT-23/SOIC-8/DIP/QFP hypotheses, hidden-lead QFN, unknown diode polarity, connector orientation uncertainty, invalid geometry, TOP/BOTTOM separation, map serialization, identity conflict blocking, overlays, and manual edits. No reviewed real PCB terminal-location dataset was available in this Phase; see [benchmark results](PHASE21_4_1_BENCHMARK_RESULTS.md).
