# Phase 21.3.2-B — 후보 클래스 매핑

기존 10-class 구성은 변경하지 않았습니다. 후보 클래스명은 출처의 표기를 보존하며, 보류 중인 매핑을 실제 학습 라벨로 자동 변환하지 않습니다.

| 출처 표기 | 후보 해석 | 처리 |
|---|---|---|
| Cap1, Cap2, Cap3, Cap4 | capacitor 세부 유형 | `capacitor`로 병합 가능성 검토. 검토 승인 전 미매핑 |
| Resistor | resistor | 표기 대응은 직접적이나 canonical label 검토 보류 |
| Resestor | 오타 가능성이 있는 저항 표기 | 자동 수정 금지, 원본 클래스 확인 필요 |
| MOSFET | MOSFET | generic transistor/IC로 합치지 않고 별도 experimental class 후보 |
| Mov | metal oxide varistor 추정 | diode에 합치지 않고 명칭/샘플 검토 후 별도 후보 |
| Transformer | transformer | 기존 10-class 외 별도 experimental class 후보 |
| WACV resistor/capacitor/diode/LED/IC/connector | 동일 이름의 부품군 후보 | 클래스별 정의 검토 필요 |
| WACV text/pads/pins/unknown/test 등 | 비부품 또는 정의 불명확 | 검출 목표와 매핑되지 않으면 `UNMAPPED`; 배경으로 취급 시 라벨 누락 가능성 기록 |
| FPIC SMD `Designator` | 부품 reference designator | 클래스가 아니므로 component class로 매핑하지 않음 |
| FPIC OCR Board/Device/Board Text | OCR/텍스트 객체 | 소자 검출 클래스가 아님 |
| FPIC VTP Connection | 연결/검증 대상 | 소자 검출 클래스가 아님 |

이미지 내 미매핑 소자가 남으면 이를 단순 배경으로 간주해 detector에 학습시키지 않습니다. 우선 클래스 계약과 annotation coverage를 검토해야 합니다.
