# 용역 손실함수 변경 재개 인수인계 (2026-08-07)

> **작성일**: 2026-08-07
> **범위**: Servc 손실함수 `quantile(0.5)` 승격 절차
> **상태**: 홀드아웃 우세 확인. **운영 경로 쌍대 검정 전. 승격하지 않음**
> **선행 인수인계**: [`2026-08-06_servc_diagnosis_handoff.md`](2026-08-06_servc_diagnosis_handoff.md)

---

## 0. 한 문장

**점 추정 objective 를 `huber(alpha=1.0)` 에서 `quantile(alpha=0.5)` 로 바꾸는
후보가 홀드아웃에서 우세하며, 남은 것은 운영 경로 쌍대 검정과 승격입니다.**

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
| Servc 서빙 | `servc_institution_v1` / `v_20260806_025423_494` |
| Servc 롤백 대상 | `v_20260805_103528_292` |
| 운영 기준선 | MAE 1.4471, 0.5%p 적중 64.02%, 구간 폭 1.7290%p, 피복률 89.40% |
| 전체 테스트 | 748 passed, 2 skipped |
| 규칙 검증 | 6/6 |

운영 기준선 재측정 명령입니다.

```bash
.venv/bin/python scripts/eval_servc_api_path.py \
  --category Servc --samples 4000 --year 2025 --seed 42
```

---

## 2. 확보한 근거

상세는 [`servc_loss_function_20260807.md`](../design/servc_loss_function_20260807.md).

2026년 out-of-sample 56,338건, 학습 2025년까지 861,291행, 손실함수 외 전부 동일.

| 후보 | MAE | RMSE | 0.5%p 적중 |
| --- | ---: | ---: | ---: |
| huber a=1 (현행) | 1.3554 | 2.7454 | 58.53% |
| **quantile a=0.5** | **1.3312** | 2.7834 | **59.65%** |

쌍대 검정 7개 모집단에서 **6개 우세 / 1개 판별 불가 / 0개 악화** 이며 관측
차이(-0.02417)가 최소 감지 차이(0.00323)의 7.5배입니다.

---

## 3. 남은 절차

### 3.1 구현

`src/ml/trainer.py:367` `_train_lightgbm` 의 `params` 입니다.

```python
params = {**LGB_BASE_PARAMS, "objective": "huber", "alpha": 1.0}
```

**이 함수는 물품(Thng)도 함께 씁니다.** 용역에서만 검증된 변경이므로 그대로
바꾸면 안 됩니다. `CATEGORY_HYPERPARAMS` 와 같은 방식으로 카테고리별 분기를
두십시오. 물품에 적용하려면 별도 검증이 필요합니다.

분위 모델(`_train_quantile_models`)은 건드리지 마십시오. 점 추정만 바꿉니다.

### 3.2 운영 경로 쌍대 검정 (건너뛰지 말 것)

홀드아웃만 보고 내린 승격 판단이 이 프로젝트에서 **네 번 뒤집혔습니다.**

1. 후보 설정으로 재학습해 레지스트리에 등록
   (`scripts/retrain_servc_from_parquet.py`)
2. 후보를 서빙 루트(`data/model_files/`)에 **임시 ID** 로 올림
3. `scripts/compare_servc_models_paired.py --base servc_institution_v1
   --challenger <임시 ID>` 로 겨룸
4. t 절댓값 2.0 초과이고 방향이 후보 우세여야 통과

### 3.3 승격

```bash
.venv/bin/python scripts/promote_model.py promote --model servc_institution_v1   # 예행
.venv/bin/python scripts/promote_model.py promote --model servc_institution_v1 --category Servc --apply
.venv/bin/python scripts/measure_serving_model.py --model servc_institution_v1 --category Servc --apply
```

### 3.4 승격 후 확인

| 항목 | 기대 | 이유 |
| --- | --- | --- |
| MAE | 개선 | 홀드아웃에서 1.8% |
| 0.5%p 적중 | 개선 | 홀드아웃에서 +1.12%p |
| **RMSE** | **악화 허용** | L1 최적화의 대가. 2.7454 -> 2.7834 |
| 구간 폭·피복률 | 변화 없음 | `_conformal_scale` 은 분위 모델 자체 중심을 씀. 코드 확인 완료, 실측 재확인 필요 |
| 모델 선택 | 확인 필요 | `train_and_register` 는 MAPE 로 LightGBM/CatBoost/Ridge 중 하나를 고름. 목적함수를 바꾸면 선택이 달라질 수 있음 |

---

## 4. 이번 세션에서 기각한 것

| 접근 | 기각 근거 |
| --- | --- |
| huber `alpha` 0.2 / 2.0 / 5.0 | 7개 모집단 전부 기준선 우세 |
| huber `alpha` 0.5 | 전체는 우세하나 기관 이력 얕은 12,339건에서 t=2.69 악화 |
| 소분류별 잔차 오프셋 | 재현성 0.803 인데도 오라클 오프셋 -0.1525 |
| 일반용역 얕은이력 셀의 특징 엔지니어링 | 잔차와 수치 특징의 최대 상관 0.105 |
| 금액대·재발주를 개선 축으로 | 집중 배수가 4년 내내 1 근처 |
| 기술용역/결측 셀 겨냥 | 이력 깊이 효과의 부호가 세 해 반대 |

정본은 `.agents/skills/servc-model-tuning/SKILL.md` 기각 목록입니다.

---

## 5. 아직 손대지 않은 축

손실함수 다음 순위였던 것입니다. 전부 미검증입니다.

| 축 | 근거 |
| --- | --- |
| LightGBM + CatBoost 앙상블 | CatBoost 가 R2 0.6994 로 LightGBM 0.6967 을 이겼고 MAPE 로만 뒤집혔음. 강점이 다르다는 신호 |
| 기관 x 소분류 교차 이력 특징 | 현행 기관 이력은 전체 평균, 재발주는 정규화 공고명 기준. 교차는 없음 |
| `quantile` 채택 후 하이퍼파라미터 재탐색 | 좌표 하강은 huber 기준으로 돌았음. 목적함수가 바뀌면 최적점도 이동 가능 |

세 번째가 특히 자연스러운 후속입니다. `num_leaves=255` 는 huber 아래에서
고른 값입니다.

---

## 6. 분석 자산

| 자산 | 경로 | 비고 |
| --- | --- | --- |
| 잔차 parquet 4개 연도 | `data/analysis/servc_residuals/` | 재생성 35분. gitignore 적용. **세션 스크래치패드가 아니라 여기 있습니다** |
| 잔차 구조 진단 | `scripts/diagnose_servc_lwlt_residuals.py` | 약 35분 |
| 오차 집중 분해 | `scripts/analyze_servc_error_concentration.py` | 잔차 재사용, 초 단위 |
| 손실함수 탐색 | `scripts/eval_servc_huber_alpha.py` | 약 45분 |

전부 읽기 전용이며 레지스트리에 쓰지 않습니다.

---

## 7. 주의 사항

**이 저장소는 병렬 세션이 동작합니다.** 2026-08-06~07 사이 다른 세션이 공유
작업 트리에서 브랜치를 다섯 번 갈아탔고 한 번은 병합 충돌 상태였습니다.

- `git add` 직전에 `git status --short --branch` 로 **HEAD 를 반드시 확인**
- `git add -A` 와 `git stash` 금지
- 병합 후 상대가 쓰던 브랜치로 HEAD 를 되돌려 놓을 것
- 브랜치 전환 시 `.claude`/`.opencode` 스킬 미러가 어긋난 사례가 있음.
  커밋 전 `validate_agent_rules.py` 로 확인

---

## 8. 완료 정의

- 카테고리별 분기로 구현 (물품에 영향 없음 확인)
- 동일 학습 상한 재학습
- 운영 경로 쌍대 검정 통과 (t 절댓값 2.0 초과)
- 하한율 보유·결측, 용역구분, 기관 이력 깊이별 회귀 확인
- 전체 테스트와 `validate_agent_rules.py` 통과
- 승격은 예행 후 명시적 `--apply`, 사후 서빙 경로 재측정
- 작업 브랜치 커밋 후 `git merge --no-ff` 로 `main` 병합
- RMSE 악화는 예상된 대가이므로 기록하되 기각 사유로 쓰지 말 것

측정하지 않은 최적화는 최적화가 아닙니다.
