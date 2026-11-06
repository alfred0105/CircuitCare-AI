# Phase 21.3.2-B — 데이터 품질 및 평가 안전성

## 후보 품질

Kaggle/DatasetNinja 변환본은 1,410장, 11,119개의 기하학적으로 유효한 source boxes가 있습니다. 소스 split은 train 1,099 / validation 200 / test 111이며 빈 라벨 이미지는 각각 0 / 3 / 111입니다. 파일명 suffix를 제거한 stem 그룹은 433개이고 37개 그룹이 split을 넘습니다. 고유 파일 해시 1,410개라는 사실은 고유 보드 1,410개를 뜻하지 않습니다. 시각 표본에서도 같은 보드 캡처 시퀀스의 유사 프레임 정황이 있어, `board_group`은 비워 두고 실물 보드 수를 미검증으로 보고합니다.

WACV는 47개 이미지와 18,201개 XML 객체를 포함하며 XML 안에 부품 외 text/pads/pins/unknown 등의 항목이 섞여 있습니다. 공식 설명은 약 62K component instances를 말하지만 이번 archive의 파싱 객체 수는 18,201입니다. 서로 다른 카운트 정의일 수 있어 혼합하지 않습니다. 라이선스가 확인되지 않아 격리합니다.

FPIC의 SMD 52,582행은 부품 클래스 없이 designator/geometry/validation을 담습니다. OCR 23,218행은 문자 관련, VTP 3,954행은 connection/solder 상태입니다. component detector의 클래스 라벨로 바로 대체할 수 없습니다.

## 평가 오류 수정

`evaluate_component_domain.py`는 이제 `INFERENCE_COMPLETE` 상태, 준비된 모델, `detections` 배열을 확인한 결과만 평가 분모에 넣습니다. 실패 dict나 예외를 빈 검출로 세지 않고 실패 수 및 partial/no-success 상태를 보고합니다. 검토되지 않은 빈 이미지도 평가 음성으로 자동 승격하지 않습니다. 분리할 지표는 populated PCB detection Precision/Recall/mAP, 검토된 빈 PCB image-level FPR와 image당 평균 FP, 브레드보드 FPR입니다. 현재 검토된 negative/board-level 평가셋이 없어 수치는 계산하지 않습니다.

## 파이프라인 보호

`acquire_component_dataset.py`는 예상 크기 사전조건, 여유 공간 검사, HTTP Range 재개, `.part` 보존, SHA-256 검증 후 원자적 이동을 지원합니다. TAR 추출 전에 경로 traversal·링크·파일 타입·파일 수·확장 크기를 거부합니다. 원본 archive 및 추출물을 지우거나 수정하지 않습니다.
