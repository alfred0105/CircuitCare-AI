# YOLO26m 40-class experiment comparison

This is a reduced-data comparison: a class-covering 5% train sample, 5% validation/test samples, and 10 training epochs per condition. Treat metrics as directional because the train sample is intentionally capped.

| Condition | Status | imgsz | epochs | batch | Test P | Test R | Test mAP50 | Test mAP50-95 | seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 640 baseline | complete | 640.0000 | 10.0000 | 2.0000 | 0.4801 | 0.2518 | 0.2132 | 0.1289 | 596.1000 |
| 960 baseline | complete | 960.0000 | 10.0000 | 1.0000 | 0.4999 | 0.1796 | 0.1765 | 0.1141 | 1243.2000 |
| 1280 baseline | complete | 1280.0000 | 10.0000 | 1.0000 | 0.3903 | 0.1080 | 0.1542 | 0.0925 | 1486.7000 |
| cls_pw=0.5 | complete | 640.0000 | 10.0000 | 2.0000 | 0.6264 | 0.2639 | 0.3350 | 0.2178 | 540.1000 |
| PCB augmentation | complete | 640.0000 | 10.0000 | 2.0000 | 0.5168 | 0.1451 | 0.1667 | 0.0743 | 522.7000 |
| Extra: multi-scale ±25% | complete | 640.0000 | 10.0000 | 1.0000 | 0.5360 | 0.1220 | 0.1330 | 0.0805 | 1034.2000 |
| Extra: rare-class oversampling (+211 repeats) | complete | 640.0000 | 10.0000 | 2.0000 | 0.7135 | 0.3220 | 0.3999 | 0.2528 | 658.1000 |
| 640 + test-time augmentation | complete | 640.0000 |  |  | 0.6077 | 0.2159 | 0.2677 | 0.1547 | 5.9000 |
| 640 + tiled inference | complete | 640.0000 |  |  | 0.7068 | 0.1126 | 0.1409 | 0.0683 | 7.5000 |

## Sampling and limits

- Train: 921 of 18,418 images (5%); validation: 116 of 2,302 (5%); test: 116 of 2,303 (5%).
- Subsets are deterministic and selected to cover every class present in each split. No image crosses splits.
- Same pretrained YOLO26m (`yolo26m.pt`), seed 42, and 10 epochs per training condition; CUDA, AMP and automatic batch sizing were used.
- `solder_joint` has one train image and one test image in the full source, so its pilot metric is not reliable.
