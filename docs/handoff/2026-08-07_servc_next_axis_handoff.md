# 용역 모델 다음 축 인수인계 (2026-08-07)

> **작성일**: 2026-08-07
> **범위**: `quantile(0.5)` 승격 이후 남은 개선 축
> **상태**: **착수 전.** 세 축 모두 미검증입니다
> **선행 인수인계**: [`2026-08-07_servc_loss_function_handoff.md`](2026-08-07_servc_loss_function_handoff.md) (완료)

---

## 0. 한 문장

**손실함수를 `quantile(0.5)` 로 승격했으니, huber 아래에서 고른
하이퍼파라미터를 새 목적함수 아래에서 다시 재는 것이 다음 순서입니다.**

---

## 1. 재개 기준점

```bash
git checkout main
git pull --ff-only
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/validate_agent_rules.py
.venv/bin/python scripts/promote_model.py status
```

| 항목 | 값 |
| --- | --- |
| Servc 서빙 | `servc_institution_v1` / `v_20260807_043210_535` |
| Servc 롤백 대상 | `v_20260806_025423_494` |
| 점 추정 목적함수 | **`quantile(alpha=0.5)`** (`CATEGORY_HYPERPARAMS`) |
| 운영 기준선 (2025년 8,995건) | MAE 1.4050, 0.5%p 적중 64.97%, 구간 폭 1.6706, 피복률 89.56% |
| 승격 후 서빙 실측 (3,000건) | MAE 1.2009 / MAPE 1.3216% / R2 0.7038 |
| 전체 테스트 | 748 passed, 2 skipped |
| 규칙 검증 | 6/6 |

**서빙 버전을 반드시 먼저 확인하십시오.** `data/model_files/*/metadata.json` 은
Git 추적 대상이고 `model.bin` 은 `.gitignore` 의 `*.bin` 에 걸립니다. 브랜치를
옮기면 가중치는 새것인데 메타데이터만 옛 버전으로 되돌아갑니다. 2026-08-07 에
실제로 발생했고 복구는 다음과 같습니다.

```bash
git checkout main -- data/model_files/servc_institution_v1/metadata.json
```

---

## 2. 1순위: quantile 아래 하이퍼파라미터 재탐색

### 2.1 왜 이 축인가

`num_leaves=255` 는 **huber 기준으로 고른 값입니다.**
[`servc_hyperparam_search_20260804.md`](../design/servc_hyperparam_search_20260804.md)
의 좌표 하강 17회가 전부 `objective="huber", alpha=1.0` 아래에서 돌았습니다.
목적함수가 바뀌면 최적 용량도 이동할 수 있습니다.

quantile 은 huber 보다 학습이 빠릅니다(홀드아웃 21.3초 대 35.5초). 같은 시간에
더 넓은 공간을 볼 수 있다는 뜻입니다.

### 2.2 준비된 것

`scripts/tune_servc_hyperparams.py` 의 `FIXED_PARAMS` 를 **운영 설정에서 읽도록
고쳐 두었습니다.** 종전에는 huber 가 하드코딩돼 있어 승격 직후 운영과 어긋난
상태였습니다. 지금은 `CATEGORY_HYPERPARAMS["Servc"]["lightgbm"]` 를 참조하므로
자동으로 quantile(0.5)로 탐색합니다.

```bash
.venv/bin/python -c "from scripts.tune_servc_hyperparams import FIXED_PARAMS; print(FIXED_PARAMS)"
# {'objective': 'quantile', 'alpha': 0.5}
```

### 2.3 남은 손질

**탐색 시작점이 아직 `LGB_BASE_PARAMS` 입니다** (`tune_servc_hyperparams.py:133`).
용역 운영값은 `num_leaves=255` 인데 기본값은 63 이라 시작점이 어긋납니다.
좌표 하강은 시작점에 민감하므로 착수 전에 이 줄을 손보십시오.

```python
best = {key: LGB_BASE_PARAMS[key] for key in SEARCH_SPACE if key in LGB_BASE_PARAMS}
```

### 2.4 이미 닫힌 값

| 값 | 결과 |
| --- | --- |
| `num_leaves=127` | 게이트 4개 통과·홀드아웃 우세였으나 운영 쌍대에서 t=2.13 악화 |
| `subsample_freq` 실효화 | MAE -0.0001, 학습 시간 +21% |

huber 아래 결과이므로 quantile 에서 자동으로 같다고 볼 수는 없습니다. 다만
재시도한다면 운영 쌍대까지 반드시 가십시오. 홀드아웃에서 뒤집힌 전례입니다.

---

## 3. 2순위: LightGBM + CatBoost 앙상블

CatBoost 가 R2 0.6994 로 LightGBM 0.6967 을 이겼고 MAPE 로만 순서가 뒤집혔습니다
(1.431 대 1.5025). **강점이 다르다는 신호**이므로 앙상블 여지가 있습니다.

`train_and_register` 는 MAPE 최저 하나만 고르는 구조라 앙상블을 넣으려면 선택
로직 자체를 손봐야 합니다. 범위가 큽니다.

---

## 4. 3순위: 기관 x 소분류 교차 이력

현행 기관 이력은 기관 전체 평균이고 재발주 특징은 정규화 공고명 기준입니다.
**둘의 교차는 없습니다.** 같은 기관이라도 소분류가 다르면 낙찰률 수준이 다를
수 있습니다.

`features.py` 를 건드리므로 학습·추론 양쪽 영향을 함께 확인해야 합니다
(AGENTS.md 6항).

---

## 5. 닫힌 갈래 (재시도 금지)

정본은 [`.agents/skills/servc-model-tuning/SKILL.md`](../../.agents/skills/servc-model-tuning/SKILL.md)
기각 목록 18행입니다. **착수 전에 반드시 먼저 읽으십시오.**

2026-08-07 에 추가된 것입니다.

| 접근 | 기각 근거 |
| --- | --- |
| 하한율 결측 집단을 개선 축으로 | 설명력이 보유 집단과 동등(0.38~0.44 대 0.41~0.45). MAE 3배는 못해서가 아니라 어려워서. 잔차 최대 상관 0.076 |

---

## 6. 판정 도구

| 도구 | 용도 | 비고 |
| --- | --- | --- |
| `scripts/compare_servc_models_paired.py` | 전체 쌍대 검정 | 1,000건은 검정력 부족. **9,000건 이상 쓰십시오** |
| `scripts/compare_servc_models_by_group.py` | 집단별 회귀 검정 | 2026-08-07 신설. 비중 가중 판정, 본페로니 보정, parquet 저장 |
| `scripts/tune_servc_hyperparams.py` | 좌표 하강 | 목적함수는 운영 설정을 따라감 |
| `scripts/measure_serving_model.py` | 승격 후 서빙 실측 | — |

**전체 쌍대만으로 판정하지 마십시오.** 2026-08-07 에 전체는 t=-2.89 우세였지만
하한율 결측 집단은 t=+4.20 으로 악화했습니다. 집단별 검정을 함께 돌리십시오.

표본 크기 감각입니다. 1,000건에서 최소 감지 차이가 0.021 인데 관측 차이는
0.011 이라 판별 불가였습니다. 9,000건에서 최소 감지 차이가 0.0076 으로 내려가
비로소 판정이 났습니다.

---

## 7. 분석 자산

| 자산 | 경로 | 비고 |
| --- | --- | --- |
| 잔차 parquet 4개 연도 | `data/analysis/servc_residuals/servc_residuals_20XX.parquet` | 특징 전량 + 예측 + 잔차. 재생성 35분 |
| 쌍대 검정 결과 2개 연도 | 같은 경로 `paired_quantile_vs_huber_20XX.parquet` | 예측 재실행 없이 재집계 가능 |

`compare_servc_models_by_group.py --from-parquet <경로>` 로 집계만 다시 할 수
있습니다. 축을 바꿔 보고 싶을 때 예측을 다시 돌리지 마십시오.

---

## 8. 주의 사항

**이 저장소는 병렬 세션이 동작합니다.** 2026-08-07 에도 작업 중 HEAD 가
`feat/kb-coverage-500k` 로 바뀌어 있었습니다.

- `git add` 직전에 `git status --short --branch` 로 **HEAD 를 반드시 확인**
- `git add -A` 와 `git stash` 금지
- 병합 후 상대가 쓰던 브랜치로 HEAD 를 되돌려 놓을 것
- 브랜치를 옮겼으면 `promote_model.py status` 로 서빙 버전을 다시 확인할 것

---

## 9. 완료 정의

- 탐색 시작점을 용역 운영값으로 맞춘 뒤 좌표 하강
- 후보가 나오면 동일 학습 상한 재학습
- 운영 경로 쌍대 검정 9,000건 이상, t 절댓값 2.0 초과
- **집단별 회귀 검정 동반**. 비중 가중 합계로 판정
- 전체 테스트와 `validate_agent_rules.py` 통과
- 승격은 예행 후 명시적 `--apply`, 사후 서빙 경로 재측정
- 작업 브랜치 커밋 후 `git merge --no-ff` 로 `main` 병합

측정하지 않은 최적화는 최적화가 아닙니다.
