# 물품 모델 재학습·승격

> **작성일**: 2026-08-06
> **버전**: v1.0.0
> **상태**: 재학습·운영 쌍대 검증·승격 완료
> **서빙 버전**: `quantum_leap_v25_pro/v_20260806_043408_749`

---

## 1. 배경

기존 물품 champion 25.1은 제목·기관·추정가격·시나리오 모드 네 개를 쓰는
규칙 모델이며 재학습된 적이 없었습니다. 2026년 3,000건 서빙 실측은 MAE
5.4942, R2 -0.2133으로 평균값 예측보다 나빴습니다.

## 2. 학습

`data/feature_store/dataset_Thng.parquet` 784,266행 × 12컬럼을 정식
`ModelTrainer.for_category("Thng")` 경로로 학습했습니다. 원본 컬럼은 12개지만
기관·재발주 이력과 파생 특징은 `src/ml/features.py` 단일 경로에서 생성합니다.

| 항목 | 값 |
| --- | ---: |
| 버전 | `v_20260806_043408_749` |
| 소요시간 | 386초 |
| 특징 | 34개 |
| 모델 | LightGBM |
| 홀드아웃 RMSE | 4.7659 |
| 홀드아웃 R2 | 0.3583 |
| 폴드별 R2 | 0.2603, 0.2987, 0.3210, 0.2944 |
| 전량 재적합 | `true` |

## 3. 운영 쌍대 비교

2026년 물품 3,000건을 같은 순서로 기존 champion과 challenger에 호출했고,
금액 미공개 8건을 제외한 2,992건을 채점했습니다.

| 모델 | MAE | RMSE | 0.5%p 적중 | 90% 구간 피복률 |
| --- | ---: | ---: | ---: | ---: |
| 기존 champion | 5.9600 | 8.1347 | 2.31% | 구간 없음 |
| challenger | **3.2587** | **6.4055** | **29.31%** | 90.21% |

| 지표 | 평균 차이 | 표준오차 | t | 판정 |
| --- | ---: | ---: | ---: | --- |
| 절대오차 | -2.70127 | 0.07967 | -33.91 | challenger 우세 |
| 제곱오차 | -25.14290 | 1.59984 | -15.72 | challenger 우세 |

challenger가 더 정확한 공고 비율은 75.64%입니다. 최소 감지 MAE 차이
0.15934보다 관측 차이 2.70127이 훨씬 큽니다.

## 4. 승격 후 검증

승격 후 parquet 3,000건을 전체 원본 특징과 기관 이력까지 포함한 서빙 경로로
다시 측정했습니다. 실패는 0건입니다.

| 지표 | 기존 25.1 | 승격본 |
| --- | ---: | ---: |
| MAE | 5.4942 | **2.8958** |
| RMSE | 6.3769 | **4.4243** |
| R2 | -0.2133 | **0.4160** |
| MAPE | 5.9648% | **3.1789%** |
| 편향 | -0.0774 | -0.0221 |

직전 규칙 모델은 `data/model_backups/quantum_leap_v25_pro`에 보관했습니다.
원본 체크섬 검증도 승격 후 백업 경로를 인식하도록 보강했으며
`scripts/verify_migration.py` 전 항목 통과를 승격 완료 조건으로 둡니다.

## 5. 함께 수정한 측정 결함

| 결함 | 수정 |
| --- | --- |
| 평가 표본이 Servc로 고정 | 두 API 평가 스크립트에 `--category` 추가 |
| 비교 가능한 구간 폭이 0건이어도 base 우세 표시 | `측정 불가`로 표시 |
| 서빙 측정이 parquet 12개 중 3개만 전달 | 전체 원본 행을 특징 단일 경로에 전달 |
| `SingletonPredictor`가 명시한 `model_id` 무시 | 명시 모델을 실제 추론에 사용 |

## 6. 재현

```bash
.venv/bin/python scripts/retrain_servc_from_parquet.py --category Thng

.venv/bin/python scripts/compare_servc_models_paired.py \
  --base thng_base --challenger quantum_leap_v25_pro \
  --category Thng --samples 3000 --year 2026 --seed 42

.venv/bin/python scripts/measure_serving_model.py \
  --model quantum_leap_v25_pro --category Thng \
  --since 2026-01-01 --sample 3000
```
