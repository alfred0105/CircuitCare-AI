# Datasheet extraction benchmark

## Status and corpus

The evaluation schema and scoring pipeline are implemented. Four official manufacturer PDFs were obtained locally and manually labeled: one resistor family, one capacitor MPN, one diode, and one regulator IC family. There are three manufacturers across those four documents, four verified target labels, and one target rating per family. PDFs are intentionally outside Git; the manifest records source URL, revision, SHA-256 and page metadata. Phase 14's YAGEO development PDF is excluded. An alternate TDK capacitor PDF retrieval returned HTTP 403 and is recorded as not acquired.

The corpus was first evaluated, then used to improve table extraction and row/column evidence handling. Therefore the **post-fix scores below are a development pilot, not an independent holdout result**. The original before-fix metrics are preserved in `evaluation/datasheet_extraction/results/pre_table_context_fix_development_pilot.json`. New unseen documents are required before claiming independent post-fix accuracy.

## Methods and post-fix results

Rules-only and rules-plus-local-LLM use the same documents, four labels, unit normalization, evidence validator, and candidate matching policy. A true positive must match the labeled value, unit, and rating kind. Page evidence and table context are scored separately; a correct value elsewhere on the same page is not enough for table-context accuracy.

| Metric | Rules only | Rules + local LLM |
|---|---:|---:|
| Candidates | 48 | 54 |
| Correct candidates | 4 | 4 |
| Candidate precision | 0.0833 | 0.0741 |
| Recall | 1.00 | 1.00 |
| F1 | 0.1538 | 0.1379 |
| Value accuracy among matched labels | 1.00 | 1.00 |
| Unit accuracy | 1.00 | 1.00 |
| Rating kind accuracy | 1.00 | 1.00 |
| Condition accuracy (2 evaluable labels) | 1.00 | 1.00 |
| Page evidence accuracy | 1.00 | 1.00 |
| Table context accuracy (3 table labels) | 1.00 | 1.00 |
| Unsupported claim rate | 0.9167 | 0.9259 |
| Source-verification rejection rate | 0.3333 | 0.3519 |

The rules run processed the four documents in approximately 0.003–0.026 seconds each in this local environment. The local Gemma 4 12B calls varied by document; measured calls in the final run took about 10.82 s, 8.74 s, 17.19 s, and 23.79 s. The LLM added candidates without adding a correct label in this small sample, reducing precision. These aggregate metrics are only diagnostics and do not establish performance across manufacturers or document types.

## Error patterns and review controls

- Table rows now retain a candidate's row label, model variant, column, selected cell, and table coordinates. The Streamlit review view exposes this context along with the cited text and page table.
- Multi-column resistor family tables can still produce surplus candidates, including an empty/repeated model cell when PDF extraction merges rows. These candidates are not treated as verified facts solely because the numeric quote is found.
- Diode continuous/peak distinctions and temperature conditions are kept separate. Adjacent-row or neighboring-model values need row/column evidence and are not silently combined.
- The LM7805 product feature “up to 1.5 A” lacks a complete operating condition in its text excerpt; the candidate remains `CONDITION_INCOMPLETE` and cannot be applied without human review and a written condition rationale.
- `page_evidence_accuracy` measures page plus quote agreement against the human label; `table_context_accuracy` measures row/model/column/cell association where the label is table-based. Fields not applicable to a label are `null`, not counted as correct.

## Reproduction and limits

Place local PDFs named by `document_id` in a folder and run:

```bash
python scripts/evaluate_datasheet_extraction.py --documents-dir /path/to/local/pdfs --run-llm --model gemma4:12b
```

The benchmark verifies each PDF's SHA-256 against the manifest and records model, digest, prompt version, commit, operating system, timing, and result status. Missing documents remain unevaluated. The PDFs are not committed. The current sample has one document per family and does not cover multiple models per vendor, multiple vendors per family, scans/OCR, or a genuine untouched holdout. No claim is made that extracted values match a physical PCB Reference without human confirmation.
