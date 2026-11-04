# Reporting guide

The overview's report controls export a snapshot of the current workspace. Export is read-only and never reruns circuit analysis.

## Report files

- **JSON** is the structured snapshot for later inspection or processing.
- **Markdown** summarizes circuit identity, fault context, SPICE state, risk review, evidence, limitations, and Git revision.
- **HTML** is a self-contained UTF-8 page that can be opened locally without a server.
- **Evidence Bundle ZIP** contains those three outputs and a manifest with SHA-256 hashes. Raw PCB photographs, original datasheet PDFs, private repair database files, and external paths are excluded unless an explicitly supported, in-root artifact is selected by code.

## Evidence labels

The report differentiates SPICE simulation, user-reported observations, synthetic/demo inputs, model proposals, and unevaluated sections. A `CACHED` run is an existing artifact; `SUCCESS` is a live run for the active scenario. Neither state proves physical component damage. Conditional Bayesian weights and inspection scores are not failure probabilities.

Every report records the circuit hash and hashes for the configured SPICE deck, mapping, probes, and rating input when available. Findings refer to evidence IDs. The validator rejects missing evidence references and mismatched current circuit hashes. The bundle verifier recomputes each included artifact hash and rejects unsafe archive paths.

## Review before sharing

Inspect the circuit name and hash, active fault, observation source, scenario ID, rating notes, model status, and limitations. Private data is stored locally. Review an export before sharing it; do not include original photos, source PDFs, or repair history by default.
