# Phase 21.3.2-C.1 — Annotation 복구

원본 11,119개 rectangle은 기존 형식·좌표 경계 검사를 통과했지만, 실제 소자와의 위치 일치, 클래스 정답성, 누락 여부, 중복 여부 및 박스 크기의 적절성에 대한 사람 검증은 0건입니다. 출처 라벨을 변경하거나 pseudo-label을 ground truth로 승격하지 않았습니다.

클래스 gallery는 다양성 표본의 bbox crop과 원본 클래스명을 보여 줍니다. 화면 테두리 접촉, 극소 box, IoU 0.85 이상 box 중첩을 기하학적 휴리스틱으로 표시한 별도 queue도 생성합니다. 이는 오류 확정이 아닌 우선 검토 후보입니다. **모델의 단순 예측은 누락 라벨 후보일 뿐입니다.** 이 환경에는 배포된 `models/pcb_component_detector.onnx`가 없었습니다. 기존 실험 체크포인트는 다른 클래스·필터 상태를 쓰거나 학습 선택 부적격으로 표시되어 있어 라벨 검토에 사용하지 않았습니다. YOLO 예측 기반 pseudo-label 후보는 0개입니다. 모델 예측이 없다고 라벨을 지우지 않았습니다.

기하 검사에서 1,430개 box 행이 후보로 나왔습니다(이미지 테두리에 닿는 box 1,427개, 상대 면적 0.0005 미만 3개). 데이터 원본은 회전·크롭된 사진을 포함하므로 테두리 접촉은 잘린 소자/정상 경계 box일 수 있습니다. 이 후보를 오류 수로 해석하지 않았습니다.

빈 annotation 114장을 `EMPTY_UNREVIEWED`로 유지하고 별도 우선 검토 queue와 이미지 연락판을 생성했습니다. 사람이 대상 부품 부재를 확인하기 전까지 negative 학습이나 empty-reviewed 상태로 바꾸지 않습니다. 모든 빈 라벨 이미지도 빈 기판이라고 추정하지 않습니다.

복구 queue: [`pcb-component-detection-c1-empty-review-queue.csv`](../data/component_training/manifests/pcb-component-detection-c1-empty-review-queue.csv). box geometry 후보는 `pcb-component-detection-c1-annotation-review-candidates.csv`에 기록합니다. 시트는 `data/component_training/processed/kaggle-c1-review/empty-annotation-review/`에 있습니다. 원본 box 수정, 보완 annotation, 승인된 negative는 현재 모두 0입니다.
