# Bundled PCB model weights

The default PCB locator/classifier and licensed comparison checkpoints are included here. See [`../THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md) for attribution and license terms.

QWEN/LLM weights are intentionally excluded. The optional PAINE 2026 checkpoint is also excluded until its redistribution license is clarified.

The app uses this folder by default when both `any_best.pt` and `fine_best.pt` are present. Set `CIRCUITCARE_PCB_WEIGHTS` to use another local weight directory.

SHA-256:

| File | SHA-256 |
|---|---|
| `any_best.pt` | `1065cdb4a32d65799b6308dc267ec9c66a1a0d261293738417bff316697725ec` |
| `fine_best.pt` | `79a0f399c2fb33a89c8036f1ebc52a6fa2f1785c520cae53f6dccd8548661208` |
| `external/nuts_best.onnx` | `70b0e26bf343f033a76292c69adf126d0138092b5691e3a4eb0b936d458c27a9` |
| `external/nuts_best.pt` | `aaf61d6ab0dd7807018ff31d4d514b66a7099461ab9d15568ab736339f3dfc03` |
| `external/pcb-ai-doctor/best_v12n.pt` | `adcad7631d9919abe52a694d5cdf205a2db0fa457f15031b613f789a621a9544` |
| `external/pcb-ai-doctor/best_v8n.pt` | `641bc711669e8c9615893364a6108dce56077121f3fb996296971aa5e8e869fc` |
| `external/pcb-yolov8s-detection/best.pt` | `f42a748053456bba5e95ea2600ba76ddbbd94917f4ae826147c2fa32750e58f9` |
| `external/PCBInspect-AI/YoloV12-Medium-160-FineTuned.pt` | `ed31d287a1428ec644a9b7c0a558fcd44c61d85c76d7de1b96fec0a7f0a86ed5` |
