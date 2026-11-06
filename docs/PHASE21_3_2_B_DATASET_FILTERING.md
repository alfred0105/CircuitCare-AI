# Phase 21.3.2-B — 도메인 필터링

허용 도메인은 `POPULATED_PCB`, `PARTIALLY_POPULATED_PCB`, `PCB_COMPONENT_CLOSEUP`입니다. `BARE_PCB`, `BREADBOARD`, `ISOLATED_COMPONENT`, `LOOSE_COMPONENT_COLLECTION`, `UNKNOWN` 및 검토가 끝나지 않은 이미지는 기본 학습에서 빠집니다. 실장 소자 수는 포함 여부의 기준이 아닙니다. 빈 라벨은 음성 샘플로 해석하지 않습니다.

이번에 생성한 두 이미지별 manifest에는 유형, 자동 분류 상태, 검토 상태, 원본 split, 라벨 수, 라벨 비어 있음 여부, 파일 해시, 포함 여부와 제외 사유가 있습니다. 개별 행은 자동/출처 기반이며 `HUMAN_REVIEWED`로 주장하지 않습니다. 현재 두 후보 모두 `training_include=false`입니다.

## 필수 검증 결과

- 분류 및 포함 상태: Kaggle 변환본 1,410행, WACV 47행 기록.
- 필터링 전후: 후보 원본 총 1,457 이미지 → 현재 canonical 학습 신규 포함 0장. Phase A 데이터 130장은 유지.
- 고유 실물 보드: 미검증. Kaggle의 433 filename stem은 물리 보드 ID가 아닙니다.
- Kaggle split 누수: filename stem 기준 433 그룹 중 37개가 원본 train/validation/test 경계를 넘습니다. 보드 누수 검사 결과 **FAIL / 실제 보드 그룹 unresolved**.
- 제외된 실장 PCB의 오제외 검사: 제외된 후보를 주 도메인에서 임의로 빼지 않도록 `PCB_COMPONENT_CLOSEUP`으로 자동 분류했으나, 사람의 전체 이미지별 판독은 수행하지 않았습니다. 현재 분류별 검토가 필요합니다.
- 개별 소자 제품 사진의 오포함: 두 신규 후보에서 제품 단독 이미지를 주 학습에 포함한 사례는 0건(모두 제외). 전체 이미지 육안 검토는 미완료입니다.
- 빈 이미지: Kaggle 변환본 114장의 빈 annotation은 `EMPTY_UNREVIEWED`이며 negative sample로 사용하지 않습니다.

`PARTIAL_ANNOTATION`, `BOARD_ID_UNRESOLVED`, `LICENSE_REVIEW_REQUIRED`, `UNKNOWN`은 학습 불가 사유입니다. 이미지 manifest 상태를 승인된 검토 결과로 바꾼 뒤 별도 이미지 목록만 생성해야 합니다. 원본 파일은 그대로 둡니다.
