## Third-party code

`hr/infer/predict.py` includes the Parsa PCB component detection inference helper. Its original MIT license is preserved in `PARSA-LICENSE.txt`.

## Bundled model checkpoints

The following upstream checkpoints are included with attribution. Keep each model's license and source terms with the files when redistributing this repository:

| Checkpoint | Upstream | License / terms |
|---|---|---|
| `weights/any_best.pt`, `weights/fine_best.pt` | [ParsaVictor/pcb-component-detection-yolo26](https://github.com/ParsaVictor/pcb-component-detection-yolo26) | MIT; cite Mohammad Parsa Karkooti and the upstream repository. |
| `weights/external/pcb-ai-doctor/best_v8n.pt`, `best_v12n.pt` | [chunchun9999/pcb-ai-doctor](https://huggingface.co/chunchun9999/pcb-ai-doctor) | CC BY-NC 4.0; attribution required, non-commercial use only. |
| `weights/external/pcb-yolov8s-detection/best.pt` | [Arshia82sbn/pcb-yolov8s-detection](https://huggingface.co/Arshia82sbn/pcb-yolov8s-detection) | MIT. |
| `weights/external/PCBInspect-AI/YoloV12-Medium-160-FineTuned.pt` | [JcProg/PCBInspect-AI](https://huggingface.co/JcProg/PCBInspect-AI) | MIT. |
| `weights/external/nuts_best.pt`, `nuts_best.onnx` | [MJOpeanuts/nuts_vision_desktop](https://github.com/MJOpeanuts/nuts_vision_desktop) | CC BY 4.0; attribution required. |

The PAINE 2026 `unet_trained.pth` checkpoint is not bundled: its [Zenodo record](https://zenodo.org/records/21887282) currently has no displayed redistribution license. Obtain permission or a license clarification from the authors before redistributing it.

QWEN and other LLM weights are intentionally excluded.
