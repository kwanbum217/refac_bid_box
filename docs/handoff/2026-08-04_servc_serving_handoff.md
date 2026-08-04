# 용역 모델 서빙 배선 인수인계

> **작성일**: 2026-08-04
> **상태**: 1~3번 완료 및 main 병합. 4번(예측 구간)은 측정까지만 완료
> **병합 커밋**: `e1f7255`, `cbb9e5b`
> **미병합 브랜치**: `feat/servc-prediction-interval`, `docs/servc-model-handoff-0803`

---

## 1. 무엇이 문제였나

성능은 올려 놨는데 **그 모델을 서비스에 태울 경로가 없었습니다.** 네 지점에서 값이 끊겼습니다.

| 지점 | 증상 | 상태 |
| --- | --- | --- |
| `model_registry` 특징 맵 복제본 | 문자열 범주가 float 변환 실패로 0.0 | 해결 |
| 서빙 불가 특징 0 채움 | 모르는 컬럼을 조용히 0.0 으로 | 해결 |
| `ml_registry` -> `data/model_files` | 잇는 코드 자체가 없음 | 해결 |
| `predict_optimal_price` 프레임 축소 | 제도 특징 26종·재발주 6종 유실 | 해결 |
| `predict_price_api` 제도 필드 누락 | 34개 중 30개가 기본값 | 해결 |

전부 **예외가 나지 않고 성능만 조용히 무너지는** 형태였습니다.

---

## 2. 최종 실측

API 경로, 2025년 무작위 300건(하한율 보유).

| 모델 | MAE | RMSE | 편향 | 1%p 이내 | 3%p 이내 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `servc_institution_v1` | **0.973** | **2.340** | -0.422 | **83.0%** | **92.0%** |
| `ssh_hist_premium` (종전) | 6.128 | 6.494 | +5.713 | 0.7% | 12.0% |

학습기 홀드아웃(183,526건) 기준 R2 0.6881 / RMSE 2.6757 / MAE 1.3176 / 0.5%p 적중 59.77%.

---

## 3. 함께 고친 것

### 3.1 모델 선택 기준

`avg_r2` 로 고르고 있었습니다. 실측에서 CatBoost 가 R2 는 이기고(0.6994 대 0.6967) **0.5%p 적중은 46.80% 대 60.49% 로 크게 졌습니다.** 낙찰률 잔차가 0 에 몰린 비대칭이라 R2 는 중심을 위로 밀어 올린 모델을 뽑습니다. `avg_mape` 로 교체했고 LightGBM 이 선택됩니다.

### 3.2 하이퍼파라미터

운영 학습기가 200트리/31리프로 실험본(600트리/63리프)보다 작았습니다. 맞춘 뒤 홀드아웃 R2 0.6688 -> 0.6881, 0.5%p 적중 54.77% -> 59.77%.

### 3.3 승격 게이트

설계서 7장 필수 4(어느 폴드도 R2 > 0.99 아닐 것)를 판정할 데이터가 없었습니다. 폴드 지표가 평균으로 뭉개져 저장됐기 때문입니다. `cv_metrics["folds"]` 에 원지표를 남기도록 고쳤습니다. 승격본 폴드별 R2 는 0.554 ~ 0.6819 로 누수 없음이 확인됩니다.

### 3.4 카테고리 기본 모델 매핑 3중 복제

`model_registry` / `bid_queries` / `bid_prediction_tool` 세 곳에 같은 dict 가 있었습니다. `model_registry.CATEGORY_DEFAULT_MODELS` 를 정본으로 삼고 나머지는 참조만 합니다.

---

## 4. 새로 생긴 것

| 파일 | 역할 |
| --- | --- |
| `src/ml/promotion.py` | `ml_registry` -> `data/model_files` 승격. 조건 검사 + 백업 + 롤백 |
| `src/ml/repeat_history.py` | (기존) 재발주 이력 |
| `src/ml/dataset.py::announcement_feature_payload` | 공고 1건을 학습 프레임 키 규격으로 펼침 |
| `src/ml/features.py::unservable_features` | 배포 전 서빙 가능 판정 |
| `ModelRegistry.verify_servable_features` | 배포 게이트 |
| `tests/test_serving_feature_parity.py` | 회귀 방지 48건 |
| `scripts/eval_servc_prediction_interval.py` | 예측 구간 보정 측정 |

승격 절차입니다.

```python
from src.ml.promotion import promote
promote("servc_institution_v1", category_code="Servc")
```

백업은 `data/model_backups/` 에 남습니다. **서빙 루트 안에 두면 `ModelRegistry` 가 백업을 모델로 오인해 로드합니다.**

---

## 5. 4번(예측 구간) 진행 상황

측정만 완료했습니다. 상세는 [`docs/design/servc_prediction_interval_20260804.md`](../design/servc_prediction_interval_20260804.md).

**핵심: 소박한 분위 회귀 구간은 보정에 실패합니다.** 명목 80% 대비 실제 75.52%, 10억 이상 구간은 66.85%. 등각예측 보정(배율 1.1095)을 적용하면 목표 90% 에서 실제 88.56% 로 들어옵니다.

배선 순서는 설계 문서 6장에 적어 두었습니다. **80% 구간은 보정 후에도 76.77% 라 쓰지 않고 90% 만 씁니다.**

---

## 6. 남은 작업

| 순서 | 작업 | 근거 |
| --- | --- | --- |
| 1 | 예측 구간 서빙 배선 | 설계서 6.3. 10%p 초과 오차가 1.43% 남아 있음 |
| 2 | 참가자 수 수집 | 제한경쟁 잔차의 지배 요인. 개찰결과 API 에 존재 |
| 3 | 세그먼트별 보정 배율 검토 | 전역 배율로는 10억 이상 66.85% 를 못 잡음 |
| 4 | `work_log.md` 갱신 | 08-02 이후 기록 누락 |

---

## 7. 주의

### 7.1 병렬 세션과의 간섭

같은 저장소에서 **다른 Claude Code 세션이 프론트엔드와 DB 재현 리팩토링을 동시에** 진행했습니다. 두 세션이 모두 `git add -A` 를 쓴 탓에 서로의 변경을 커밋하는 일이 양방향으로 일어났습니다.

| 방향 | 사례 |
| --- | --- |
| ML -> 프론트 | 로그인 next 리다이렉트, 예측 AJAX 전송 방식 변경을 함께 커밋 (되돌림) |
| 프론트 -> ML | `d0d9b98` 예측 구간 스크립트, `56a26a6` 문서 인덱스, `0b781d0` 미완성 ML 작업 트리 |

특히 `0b781d0` 은 **ML 작업의 중간 상태**가 커밋된 것입니다. `e1f7255` 로 병합됐으므로 후속 수정 `cbb9e5b` 가 반드시 함께 있어야 정상 동작합니다.

테스트도 간섭받습니다. `test_bid_list_parity` 2건이 일시 실패했는데, 상대 세션이 `src/app` 을 수정하는 중간 상태를 읽었기 때문입니다. 단독 재실행에서는 통과했습니다.

**대응 원칙입니다.**

- `git add -A` 를 쓰지 않고 **변경한 경로를 명시적으로 스테이징**합니다.
- 테스트가 `src/app` 계층에서 실패하면 **단독 재실행으로 먼저 격리**합니다. 상대 세션의 중간 상태일 수 있습니다.
- 병합 전 `git log --oneline main..HEAD` 로 **남의 커밋이 섞이지 않았는지** 확인합니다. 섞였으면 체리픽으로 분리합니다.
- 근본 해결은 세션별 `git worktree` 분리입니다. 작업 디렉터리가 갈리면 간섭이 사라집니다.

### 7.2 데이터셋

`data/feature_store/dataset_Servc.parquet` 은 **917,629행 x 28컬럼**이어야 합니다. 실험 전 행 수를 확인하십시오. 과거에 테스트 픽스처가 80행으로 덮어쓴 적이 있습니다.

### 7.3 모델 가중치

`.gitignore` 의 `*.bin` 때문에 `model.bin` 은 git 에 없습니다. `metadata.json` 만 추적됩니다. 다른 기기에서는 재학습 후 `promote` 가 필요합니다.

---

## 8. 재개 절차

```bash
git checkout main && git pull
.venv/bin/python -m pytest tests/ -q                      # 526 passed 기대
.venv/bin/python scripts/eval_servc_year_holdout.py       # R2 0.6968 기대
.venv/bin/python scripts/validate_agent_rules.py          # 6/6 기대
```
