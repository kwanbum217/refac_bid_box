# 용역 모델 다음 축 인수인계 (2026-08-07)

> **작성일**: 2026-08-07
> **범위**: `quantile(0.5)` 승격 이후 남은 개선 축
> **상태**: 1순위 **기각 완료**. 남은 것은 **앙상블(1순위)과 교차 이력(2순위)** 입니다
> **선행 인수인계**: [`2026-08-07_servc_loss_function_handoff.md`](2026-08-07_servc_loss_function_handoff.md) (완료)

---

## 0. 한 문장

**하이퍼파라미터 재탐색은 기각으로 닫혔으니, 다음 순서는 LightGBM + CatBoost
앙상블입니다.**

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

## 2. 1순위였던 축: quantile 아래 하이퍼파라미터 재탐색 (기각)

> **2026-08-07 종료.** 운영 쌍대 검정에서 기각했습니다. **재시도하지 마십시오.**
> 상세는 [`servc_hyperparam_quantile_20260807.md`](../design/servc_hyperparam_quantile_20260807.md).

| 단계 | 결과 |
| --- | --- |
| 좌표 하강 21회 | 완료 |
| 시드 재현성 검정 | 실체 있음 (시드 3개 -0.0035~-0.0038, 산포의 4.6배) |
| 재학습 `v_20260807_110637_435` | 완료. 레지스트리에만 등록 |
| 운영 쌍대 8,995건 | **기각.** MAE 1.4050 -> 1.4188, t=5.14 |
| 집단별 | 6개 집단 중 challenger 우세 **0개** |
| 되돌림 | `CATEGORY_HYPERPARAMS` 원복 완료 |

### 2.1 확정된 사실

**용량 최적점은 목적함수와 무관합니다.** 두 목적함수 모두 31 < 63 < 127 <
255 > 511 로 순서가 같고 255 에서 최소입니다. 목적함수를 바꿨다는 이유만으로
용량 축을 다시 훑지 마십시오.

### 2.2 왜 뒤집혔는가

`tune_servc_hyperparams.py` 는 조기 종료를 걸지 않고 `_train_lightgbm` 은
`early_stopping(10)` 을 겁니다. `learning_rate` 를 낮추면 더 많은 트리로
보상해야 하는데, 탐색에서는 `n_estimators=2000` 이 보상했고 운영에서는 조기
종료가 그 전에 잘랐습니다.

**원인은 제거했습니다.** `tune_servc_hyperparams.py` 의 `evaluate` 가 운영
3단계를 그대로 따릅니다. 학습 구간을 시간순 80/20 으로 가르고, 뒤 20%를
`eval_set` 으로 조기 종료해 트리 수를 정한 뒤, 그 트리 수로 학습 구간 전량을
재적합합니다. 검증 연도는 평가에만 씁니다.

**이 수정 이전 탐색 결과의 절대값은 새 경로와 비교할 수 없습니다.** 시행
시간은 학습이 2회로 늘어도 25% 증가에 그칩니다(실측 39.5초 -> 49.4초).

그래도 **이 축을 다시 여는 것은 권하지 않습니다.** 경로를 맞춘 것이지 여지가
있다는 증거가 생긴 것은 아닙니다. 앙상블과 교차 이력이 먼저입니다.

### 2.3 레지스트리 주의

`ml_registry/servc_institution_v1/v_20260807_110637_435` 를 재판단용으로
남겼습니다. **`promote_model.py status` 가 이 버전을 "승격 조건 통과" 로
표시하지만 학습기 지표만 본 판정입니다. 운영 쌍대에서 기각됐으므로 승격하지
마십시오.**

---

## 3. 1순위: LightGBM + CatBoost 앙상블

CatBoost 가 R2 0.6994 로 LightGBM 0.6967 을 이겼고 MAPE 로만 순서가 뒤집혔습니다
(1.431 대 1.5025). **강점이 다르다는 신호**이므로 앙상블 여지가 있습니다.

`train_and_register` 는 MAPE 최저 하나만 고르는 구조라 앙상블을 넣으려면 선택
로직 자체를 손봐야 합니다. 범위가 큽니다.

---

## 4. 2순위: 기관 x 소분류 교차 이력

현행 기관 이력은 기관 전체 평균이고 재발주 특징은 정규화 공고명 기준입니다.
**둘의 교차는 없습니다.** 같은 기관이라도 소분류가 다르면 낙찰률 수준이 다를
수 있습니다.

`features.py` 를 건드리므로 학습·추론 양쪽 영향을 함께 확인해야 합니다
(AGENTS.md 6항).

### 4.1 사전 신호부터 재십시오 (특징을 만들기 전에)

특징을 만들어 재학습하면 한 번에 40분이 넘습니다. **잔차 parquet 으로 먼저
값어치를 판단하십시오.** 잔차는 이미 기관 이력(`inst_hist_rate`,
`inst_ewm_rate`)을 반영한 모델의 것이므로, 그 잔차가 기관 x 소분류로 갈린다면
그것이 **증분 신호**입니다.

측정 순서는 스킬의 원칙을 따릅니다. **재현성보다 오라클을 먼저** 재십시오.

1. 셀별 잔차 평균과 표본 수 분포
2. **오라클**: 그 해 셀 평균을 그 해에서 빼면 MAE 가 개선되는가 (상한)
3. 오라클이 손해면 중단. 이득이면 재현성(연도 간 상관, 부호 일치)
4. **실용**: 전년 셀 평균을 다음 해에 적용하면 개선되는가

소분류 단독 잔차 오프셋은 이미 기각됐습니다(재현성 0.803 인데도 오라클 오프셋
-0.1525). 교차가 단독보다 나을 근거는 아직 없습니다.

### 4.2 2026-08-07 에 막힌 지점

**저장된 잔차 parquet 에 기관 식별자가 없었습니다.** `dminstt_nm` 은 원본
`dataset_Servc.parquet` 에만 있고, 원본과 행 순서로 맞추려 해도 같은
`openg_dt` 안의 순서가 달라(2025년 96,141행에서 `clsfc_nm` 일치율 12%)
안전하게 이을 수 없었습니다. 재생성에 35분이 걸려 그 자리에서 되돌릴 수도
없었습니다.

`diagnose_servc_lwlt_residuals.py` 가 `bid_ntce_no` / `dminstt_nm` /
`ntce_instt_nm` 을 함께 남기도록 고쳤습니다. **다음 재생성부터 반영됩니다.**
기존 4개 연도 parquet 에는 아직 없으므로, 이 분석을 하려면 먼저 재생성해야
합니다.

```bash
.venv/bin/python scripts/diagnose_servc_lwlt_residuals.py \
  --years 2023 2024 2025 2026 --dump-dir data/analysis/servc_residuals
```

특징이 아니라 진단 축으로 붙였으므로 학습에는 들어가지 않습니다
(`fit_until` 이 `feature_columns` 만 골라 씁니다).

---

## 5. 닫힌 갈래 (재시도 금지)

정본은 [`.agents/skills/servc-model-tuning/SKILL.md`](../../.agents/skills/servc-model-tuning/SKILL.md)
기각 목록 18행입니다. **착수 전에 반드시 먼저 읽으십시오.**

2026-08-07 에 추가된 것입니다.

| 접근 | 기각 근거 |
| --- | --- |
| 하한율 결측 집단을 개선 축으로 | 설명력이 보유 집단과 동등(0.38~0.44 대 0.41~0.45). MAE 3배는 못해서가 아니라 어려워서. 잔차 최대 상관 0.076 |
| quantile 아래 하이퍼파라미터 재탐색 | 용량 최적점은 목적함수와 무관하게 255. 나머지 조합은 홀드아웃 -0.0037 이 운영 쌍대에서 +0.0139 t=5.14 로 뒤집힘. 탐색과 운영의 조기 종료 차이가 원인 |

---

## 6. 판정 도구

| 도구 | 용도 | 비고 |
| --- | --- | --- |
| `scripts/compare_servc_models_paired.py` | 전체 쌍대 검정 | 1,000건은 검정력 부족. **9,000건 이상 쓰십시오** |
| `scripts/compare_servc_models_by_group.py` | 집단별 회귀 검정 | 2026-08-07 신설. 비중 가중 판정, 본페로니 보정, parquet 저장 |
| `scripts/tune_servc_hyperparams.py` | 좌표 하강 | 목적함수·시작점·조기 종료를 운영 학습기에 맞춤 |
| `scripts/measure_servc_tuning_noise.py` | 탐색 결과가 시드 산포보다 큰지 | 2026-08-07 신설. 좌표 하강 뒤 반드시 거칠 것 |
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
`feat/kb-coverage-500k` 로 바뀌어 있었습니다. 같은 날 저녁 그 세션이 별도
worktree(`/private/tmp/.../wt-kb`)로 옮겨 갔습니다. **다른 worktree 가 쓰는
브랜치는 이 트리에서 체크아웃할 수 없습니다.** `git worktree list` 로 먼저
확인하십시오.

- `git add` 직전에 `git status --short --branch` 로 **HEAD 를 반드시 확인**
- `git add -A` 와 `git stash` 금지
- 병합 후 상대가 쓰던 브랜치로 HEAD 를 되돌려 놓을 것
- 브랜치를 옮겼으면 `promote_model.py status` 로 서빙 버전을 다시 확인할 것

---

## 9. 완료 정의

- 후보가 나오면 동일 학습 상한 재학습
- 운영 경로 쌍대 검정 9,000건 이상, t 절댓값 2.0 초과
- **집단별 회귀 검정 동반**. 비중 가중 합계로 판정
- 전체 테스트와 `validate_agent_rules.py` 통과
- 승격은 예행 후 명시적 `--apply`, 사후 서빙 경로 재측정
- 작업 브랜치 커밋 후 `git merge --no-ff` 로 `main` 병합

측정하지 않은 최적화는 최적화가 아닙니다.
