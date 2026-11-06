# Phase 21.3.2-B — 학습 준비도 결정

## 결정: 신규 데이터 학습에 미포함

주요 목적은 실제 PCB에 실장된 전자 부품 객체 검출입니다. 현 시점에 새 후보에서 canonical 10-class 학습 목록으로 승인된 이미지는 **0장**입니다. 원본 Phase A 목록은 보존됩니다. 이는 최종 데이터셋 전체가 부적합하다는 결론이 아니라, 발견된 파일을 현재 label contract, 권리, 보드 분할 요건에 맞게 승인할 근거가 부족하다는 뜻입니다.

| 항목 | 결과 |
|---|---:|
| 신규 취득 후보 | 1,457장 (Kaggle 변환본 1,410 + WACV 47) |
| 신규 canonical 학습 포함 | 0장 |
| 신규 검증된 고유 PCB board | 0 (실제 수는 미검증) |
| 원본 Phase A 유지 | 130장 / 3,300 box |
| 검토 승인된 negative / breadboard 평가 이미지 | 0장 |
| Kaggle stem split leakage | 37 / 433 stem groups; FAIL |

## 다음 승인 조건

1. WACV 및 FPIC 사용 조건을 권리자가 명시한 문서로 확인.
2. 이미지별 PCB 도메인 분류와 제외 오류를 사람이 확인하고 검토 기록을 manifest에 추가.
3. 촬영 세션/실물 보드 기준 ID를 확인하고 동일 보드의 close-up을 같은 그룹에 둔 뒤 group split 재생성.
4. 각 클래스의 mapping 및 annotation completeness를 승인. 빈 라벨은 실제 검토된 경우에만 negative로 표시.
5. 같은 board group이 split 경계를 넘지 않는지 다시 검사.
6. 위 조건을 통과한 이미지 ID만 학습 inclusion list에 추가하고 필터링 전후 카운트를 재산출.

이번 작업에서는 모델 재학습을 실행하지 않았으며, 검토/추적 가능한 manifest와 조사 보고서만 저장했습니다.
