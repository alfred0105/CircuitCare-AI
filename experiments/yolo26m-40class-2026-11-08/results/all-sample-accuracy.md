# All-sample correctness by condition

Test sample: 116 images. “Exact-image accuracy” requires every labeled box to match the class at IoU ≥ 0.50, confidence ≥ 0.25, with no extra detections. This is intentionally strict; detection has no ordinary classification accuracy.

| Condition | Exact images | Exact-image accuracy | Micro P | Micro R | Micro F1 | Mean image F1 | TP / FP / FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| 640 baseline | 10/116 | 8.6% | 0.497 | 0.121 | 0.194 | 0.348 | 722 / 732 / 5261 |
| 960 baseline | 9/116 | 7.8% | 0.482 | 0.068 | 0.119 | 0.275 | 405 / 436 / 5578 |
| 1280 baseline | 9/116 | 7.8% | 0.418 | 0.076 | 0.129 | 0.235 | 456 / 634 / 5527 |
| cls_pw=0.5 | 11/116 | 9.5% | 0.486 | 0.077 | 0.133 | 0.272 | 460 / 486 / 5523 |
| PCB augmentation | 9/116 | 7.8% | 0.523 | 0.076 | 0.133 | 0.285 | 454 / 414 / 5529 |
| Multi-scale ±25% | 10/116 | 8.6% | 0.528 | 0.046 | 0.085 | 0.262 | 278 / 249 / 5705 |
| Rare-class oversampling | 16/116 | 13.8% | 0.487 | 0.130 | 0.205 | 0.441 | 777 / 819 / 5206 |
| 640 + TTA | 10/116 | 8.6% | 0.444 | 0.138 | 0.210 | 0.381 | 824 / 1033 / 5159 |
| 640 + tiled inference | 9/116 | 7.8% | 0.420 | 0.155 | 0.227 | 0.340 | 928 / 1281 / 5055 |

Matching rule: greedy one-to-one class match with IoU ≥ 0.50; predictions below confidence 0.25 are ignored; max detections per image = 300.
The exact-image rate is not directly comparable to mAP because it uses one confidence threshold and requires every object in an image to be correct. See the per-image CSV for all sample-level TP/FP/FN.
