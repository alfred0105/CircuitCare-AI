# Phase 22 연결 추정 실험 결과

## 실행 범위와 재현 조건

- 데이터 분할: 학습 3,920 그래프, 검증 515 그래프. 테스트 513 그래프는 열거나 평가하지 않았다.
- GPU: Apple Silicon MPS를 GNN 학습에 사용했다. CUDA 장치는 이 환경에서 사용할 수 없었다. LightGBM 실험은 CPU에서 실행했다.
- E1, E2, E4, E5의 학습 후보 간선은 그래프별 결정적 샘플링을 사용했다. 핀 순위와 End-to-End 지표는 검증 그래프에서 계산했다.
- 후보 생성 Recall은 후보 생성기가 만들 수 없는 동일 부품 내부의 정답 핀 쌍 36,570개를 제외한 298,543개 정답 쌍을 기준으로 한다.
- 불균형 가중치와 negative sampling이 적용돼 모델 점수는 보정된 연결 확률로 해석할 수 없다. 검증 F1 임계값은 검증 집합에서 선택했다.
- 실험 스크립트는 `scripts/run_phase22_*.py`, 요약 결과는 `data/benchmarks/phase22_connectivity/exp*.json`에 있다. 원본/파생 데이터는 별도 릴리스에서 받아야 하며 이 저장소에는 커밋하지 않았다.

## 결과 요약

| 실험 | 검증 결과 | 해석 |
|---|---|---|
| E1 공정 모델 비교 | 기본 feature 평균 candidate PR-AUC: LightGBM 0.3179, GNN 0.2013. 전체 feature: LightGBM 0.4184 (3 seed SD 0.0016), GNN 0.2947 (SD 0.0092). | 동일 feature와 학습 간선 조건에서 LightGBM이 우세했다. 전체 feature는 기본 feature보다 두 모델 모두 성능을 높였다. |
| E2 Feature ablation | Pin-facing 제거 시 GNN PR-AUC가 세 seed에서 약 0.232–0.236으로 하락했다. Pin-name 범주 제거 시 약 0.223–0.237, pin-name 파생 feature 전체 제거 시 약 0.216–0.232였다. | 핀 방향 추정과 핀 이름 의미 feature가 도움이 되는 신호다. Neighbor-rank 제거 효과는 seed에 따라 달랐고, pitch-normalized distance 단독 제거는 한 seed에서 소폭 개선돼 추가 반복이 필요하다. Pin-facing은 실제 KiCad 핀 방향이 아니라 중심점으로부터 계산한 근사치다. |
| E3 후보 생성 | 기존 C0 micro/macro Recall 0.6343/0.8745, 후보 3,256,763개. H2 hybrid는 0.7794/0.9428, 후보 4,196,752개(+28.9%), 핀당 평균 후보 99.19→127.82. | 계획의 검증 micro Recall 75% 목표와 후보 증가 40% 미만 조건을 충족했다. 후보 precision은 0.0581에서 0.0554로 소폭 하락했다. 이는 후보 포함률이지 모델이 실제 전선을 복원한 비율이 아니다. |
| E3 H2 + LightGBM | H2 후보에서 LightGBM candidate PR-AUC 평균 0.4149, P@5 0.2440, End-to-End R@5 0.1942 (3 seed). | 후보 Recall은 크게 올랐지만 기존 후보의 LightGBM PR-AUC 0.4184보다 조금 낮고 E2E R@5 개선도 제한적(+0.006)이었다. 후보 수와 추론 품질 간 trade-off가 있다. |
| E4 Edge-aware GNN | 평균 candidate PR-AUC: mean GNN 0.3197, edge-gated 0.3289, edge-MLP 0.3869 (각 3 seed). Edge-MLP E2E R@5 평균 0.1643, P@1 0.2053. | Edge-MLP가 세 GNN 중 가장 높았지만 seed 변동(SD 0.0208)이 크며, 검증 LightGBM보다 낮다. |
| E5 검증 기반 탐색 | LightGBM 20 trial 중 최고 검증 PR-AUC 0.4850 (trial 16). 설정: 800 trees, 127 leaves, depth 제한 없음, learning rate 0.1, min child 20, L2 1.0, feature fraction 1.0. 별도 seed 재확인: 0.4852 (seed 123), 0.4831 (seed 2026). | LightGBM 최고 설정은 검증에서 재현됐다. GNN Optuna 탐색은 사용자 요청으로 중단됐다. 완료된 첫 trial만 보고되며, 검증 PR-AUC 0.4237 (seed 42, hidden 48, layer 1, lr 0.001, dropout 0.3, weight decay 1e-5)이다. 전체 3-trial 탐색이나 다중 seed 재확인은 완료되지 않았다. |

## 결과 파일

- E1: `exp01_model_comparison.json`, `exp01_model_comparison_baseline.json`
- E2: `exp02_feature_ablation.json`, `exp02_feature_ablation_repeat.json`
- E3: `exp03_candidate_generation.json`, `exp03_candidate_generation_export.json`, `exp03_hybrid_lgbm_validation.json`
- E4: `exp04_edge_aware_gnn.json`
- E5: `exp05_lgbm_search.json`, `exp05_lgbm_recheck.json`, `exp05_gnn_search.json` (마지막 파일은 중단 시점까지의 부분 결과)

## 제한과 다음 작업

수치는 모두 학습/검증 분할에서 얻은 개발 결과이며, 테스트 일반화 성능을 주장하지 않는다. 클래스 가중치와 음성 샘플링 때문에 점수 보정도 수행하지 않았다. 동일 부품 내부 연결은 별도 정답 집계에서 제외했으므로, 해당 특수 사례를 다루려면 후보 생성·평가 정책을 확장해야 한다. GitHub Actions의 성공 여부는 이 실험들의 자동 재현이나 검증을 보장하지 않는다.

실험은 E5 GNN 탐색 도중 중단됐다. 재개할 경우에는 저장된 완료 trial을 보존하면서 탐색을 재개하고, 최적 GNN 설정을 다른 seed로 재검증한 다음 테스트 분할을 마지막에 한 번만 평가한다.
