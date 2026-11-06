# Phase 21.3.2-B — 데이터 수집 감사

## 결과

새 공개 후보를 조사했고 세 출처에서 파일을 확보했습니다. 확보한 원본은 `data/component_training/raw/external/`에 보존했고 기존 데이터는 삭제하거나 덮어쓰지 않았습니다. 단, 현재 canonical 10-class 모델의 신규 학습에 바로 추가할 수 있는 이미지는 **0장**, 보드 ID를 검증한 고유 PCB 수도 **0개(미검증)** 입니다. 이는 확보 실패가 아니라 라이선스·라벨 범위·보드 분할 검증을 통과하지 못한 파일을 학습 목록에서 제외한 결과입니다.

| 출처 | 실제 확보 | 라이선스 / 접근 상태 | 학습 준비 상태 |
|---|---:|---|---|
| Kaggle PCB Component Detection, DatasetNinja 변환본 | 1,410장, 11,119 box, CC0 | Kaggle 메타데이터 CC0-1.0 확인 | 보류: 실제 보드 ID 미확인, 원본 split 누수, 10-class 매핑 미완료 |
| PCB-WACV 2019 | 47장, 18,201 VOC 객체 | 공식 페이지에 라이선스 명시를 찾지 못함 | 보류: 권리 검토, 텍스트·패드 등 미매핑 범주 포함 |
| FPIC PhysicalDB | SMD/OCR/VTP/metadata annotation만 받음 | 공개 페이지에 사용 조건 명시를 찾지 못함 | 보류: 이미지 ZIP(7,196,349,363 bytes)은 받지 않음. SMD엔 class 필드가 없음 |
| FICS-PCB | 파일 미확보 | 공식 Trust-Hub 페이지에서 익명 다운로드 접근 확인 불가 | 접근 확인 전 보류 |
| PCB-DSLR | 파일 미확보 | Zenodo 메타데이터 CC BY 4.0과 설명의 비상업 연구 조건이 상충 | 권리 확인 전 보류; IC 전용이며 다운로드 약 6.2GB |

세부 URL, 체크섬, 압축 크기, 사유는 [source registry](../data/component_training/manifests/phase21-3-2-b-source-registry.json)에 기록했습니다. 이미지별 파일 해시와 포함 상태는 [Kaggle 후보 manifest](../data/component_training/manifests/pcb-component-detection-acquisition-manifest.json), [WACV manifest](../data/component_training/manifests/pcb-wacv-2019-acquisition-manifest.json)에 있습니다.

## 크기·보존

다운로드된 세 데이터셋의 archive 및 추출 파일은 약 995 MiB입니다. 조사 당시 작업 볼륨의 여유 공간은 약 138 GiB였습니다. 기존 Phase A의 130장/3,300 box 데이터는 그대로 유지되며 신규 획득 통계와 합산하지 않았습니다. 압축 파일은 SHA-256을 기록했고, TAR 경로 순회·링크·비정상 확장 크기를 검사한 뒤 안전하게 추출했습니다.

## 출처

- [Georgia Tech PCB-WACV 2019 공식 페이지](https://ripl.cc.gatech.edu/pcb-dataset/)
- [Kaggle PCB Component Detection 원본 페이지](https://www.kaggle.com/datasets/animeshkumar/printed-board-circuit-pcb-component-detection)
- [DatasetNinja 데이터셋 카드](https://datasetninja.com/printed-board-circuit-pcb-component-detection)
- [UF PhysicalDB 공식 페이지](https://physicaldb.ece.ufl.edu/pcb-dataset/)
- [Trust-Hub 데이터 페이지](https://trust-hub.org/data)
- [PCB-DSLR Zenodo 레코드](https://zenodo.org/records/13298212)
