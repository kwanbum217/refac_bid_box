# 재학습 파이프라인 E2E 검증 결과

> **작성일**: 2026-08-02
> **버전**: v1.0.0
> **상태**: 배선 복구 완료. 모델 설계는 실측 기반 고도화 대상
> **검증**: [`tests/test_retrain_pipeline_e2e.py`](../../tests/test_retrain_pipeline_e2e.py) 15건

---

## 1. 요약

E2E 실기동 결과, **재학습 파이프라인은 지금까지 한 번도 실제 DB 에서 동작한 적이 없었습니다.** 첫 단계인 데이터셋 빌더가 존재하지 않는 컬럼을 참조해 즉시 예외로 죽었습니다.

배선을 고쳐 전 주기가 돌아가게 만들었고, 그 과정에서 결함 6건이 드러났습니다. 모델 성능 고도화는 별도 과제로 이어집니다.

---

## 2. 발견한 결함

| # | 위치 | 증상 | 처리 |
| ---: | --- | --- | --- |
| 1 | `ml/dataset.py` | `bid_notice_no`, `presumed_price` 등 **존재하지 않는 컬럼** 참조. `AttributeError` 즉사 | 실제 스키마 컬럼으로 교체 |
| 2 | `ml/dataset.py` | `BidResult.announcement_id` 로 조인. 그런 컬럼도 FK 도 없음 | 공고번호+차수+업무구분 조인으로 교체 |
| 3 | `ml/dataset.py` | 데이터가 없으면 **더미 1행**을 만들어 학습이 성공한 것처럼 보임 | 빈 프레임 반환, 태스크가 `skipped` 처리 |
| 4 | `tasks/retrain_task.py` | `evaluate_model_performance(y, y)` — **정답을 정답과 비교**. 항상 rmse 0 / r2 1 | 홀드아웃 예측값과 비교 |
| 5 | `tasks/retrain_task.py` | 승격 게이트(`compare_champion_vs_challenger`)를 **아무도 호출하지 않음** | 재학습 주기에 연결 |
| 6 | `ml/trainer.py` | 버전명이 초 단위(`v_%Y%m%d_%H%M%S`). 같은 초에 두 번 학습하면 **디렉터리를 덮어씀** | 밀리초 + 충돌 시 접미사 |

부수적으로 `retrain_logs` 테이블이 정의만 되어 있고 **아무도 쓰지 않던 것**을 연결했고, `tests/test_mlops_pipeline.py` 가 테스트마다 **운영 `ml_registry/` 에 버전을 쌓던 것**을 임시 디렉터리로 돌렸습니다(누적 21건 확인).

---

## 3. 데이터 조인 실측

두 테이블 사이에 FK 가 없어 공고번호 + 차수 + 업무구분으로 붙입니다. **차수 자리수가 서로 다른 것**이 핵심입니다.

| 테이블 | `bid_ntce_ord` 형식 | 최빈값 |
| --- | --- | --- |
| `bid_results` | 2자리 | `00` (2,809,073) |
| `bid_announcements` | 3자리 | `000` (1,624,262) |

정규화 없이 조인하면 **0건**입니다. `000` 을 앞에 붙이고 뒤 3자를 잘라 맞춥니다 (`LPAD` 는 SQLite 에 없어 테스트가 깨집니다).

정규화 후 조인 성공률입니다.

| 카테고리 | 조인 성공 | 낙찰 전체 | 비율 |
| --- | ---: | ---: | ---: |
| Thng (물품) | 857,212 | 858,026 | **99.9%** |
| Servc (용역) | 46,587 | 889,933 | **5.2%** |
| Cnstwk (건설) | 65,541 | 1,254,295 | **5.2%** |

용역·건설은 공고 데이터가 거의 수집되지 않았습니다(`bid_announcements` 기준 용역 100,000 / 건설 223,580 vs 물품 1,515,508).

이 때문에 `build_training_dataset(require_announcement=False)` 경로를 두었습니다. 공고를 붙이지 않고 낙찰 결과만 쓰면 용역 표본이 41,423 -> 773,045 로 늘어납니다. 다만 **예정가격·기초금액을 쓸 수 없습니다.**

---

## 4. 실기동 결과 (용역)

```
category            = Servc
require_announcement = False
samples             = 773,045
version             = v_20260802_064411_973
champion_version    = v_20260802_064146
metrics             = {'rmse': 4.5108, 'mape': 3.5131, 'r2': -0.0012}
recommendation      = PROMOTE_CHALLENGER
```

전 주기(데이터셋 -> 학습 -> 홀드아웃 평가 -> 승격 판정 -> 이력 기록)가 약 30초에 완주합니다. `retrain_logs` 에도 기록됩니다.

**R² -0.0012 는 평균값 예측보다 못하다는 뜻입니다.** 현재 모델(Ridge, 특징 4개)에는 예측력이 없습니다. 이전에는 이 사실이 rmse 0 / r2 1 로 가려져 있었습니다.

---

## 5. 성능 고도화 과제

아래는 실측 근거를 갖춘 뒤 결정해야 하는 항목입니다. 각 항목마다 후보안을 비교하고 수치로 판단합니다.

### 5.1 승격 임계값 — 지금은 동일 성능도 승격됩니다

`compare_champion_vs_challenger` 는 다음과 같습니다.

```python
improved_r2 = challenger_metrics["r2"] >= champion_metrics["r2"]  # 같아도 True
should_promote = improved_rmse or improved_r2
```

같은 데이터로 두 번 학습해 지표가 **완전히 동일**한데도 `PROMOTE_CHALLENGER` 가 나옵니다. AGENTS.md 의 "champion 을 성능으로 **압도**할 때만 승격" 과 어긋납니다.

개선 방향(예시): `>=` 를 `>` 로 바꾸고 최소 개선 폭을 둡니다.

```python
MIN_R2_GAIN = 0.01
MIN_RMSE_GAIN_RATIO = 0.02
```

얼마를 둘지는 도메인 판단입니다.

### 5.2 모델과 특징

`features.py` 는 60개가 넘는 특징을 산출하는데 학습에는 4개만 씁니다.

```python
TRAINING_FEATURES = ["presumed_price", "base_price", "price_ratio", "inst_hist_rate"]
```

`inst_hist_rate` 는 실제 기관 이력이 아니라 상수 기본값(`DEFAULT_INST_RATE = 0.925`)으로 채워집니다. 기관별 낙찰률 이력을 실제로 계산해 넣는 것이 R² 개선의 출발점으로 보입니다.

모델도 Ridge 이며 docstring 이 말하는 K-Fold 나 LightGBM/CatBoost 는 적용되어 있지 않습니다.

### 5.3 홀드아웃 분할 전략

현재는 프레임 순서 기준 뒤 20% 를 검증에 씁니다(`DEFAULT_VALIDATION_SPLIT`). 낙찰 데이터는 시계열이므로 개찰일 기준 분할이 더 적절할 수 있습니다. 무작위 분할은 미래 정보가 학습에 새어 들어갈 수 있습니다.

### 5.4 용역 학습 데이터 선택

| 선택 | 표본 | 가격 특징 |
| --- | ---: | --- |
| 공고 조인 (`require_announcement=True`) | 41,423 | 사용 가능 |
| 낙찰만 (`require_announcement=False`) | 773,045 | **사용 불가** |

표본 19배와 가격 특징 사이의 맞교환입니다. 낙찰가 예측에서 예정가격은 핵심 입력이므로, 공고 데이터를 추가 수집하는 쪽이 근본 해결입니다.

---

## 6. 재현 방법

```bash
python - <<'PY'
import asyncio
from src.tasks.retrain_task import run_retrain_pipeline_task
print(asyncio.run(run_retrain_pipeline_task(
    {}, trigger_source="manual", category_code="Servc", require_announcement=False)))
PY
```

주간 재학습은 매주 월요일 03:00 에 자동 실행됩니다(`src/tasks/worker.py` `cron_jobs`). `ML_WEEKLY_RETRAIN_ENABLED=false` 로 끌 수 있습니다.

---

## 7. 참조

- 정기 실행 스케줄: [`../handoff/2026-08-01_session_todo.md`](../handoff/2026-08-01_session_todo.md)
- 인코딩 손상 (건설 문자열): [`../migration/encoding_corruption_analysis.md`](../migration/encoding_corruption_analysis.md)
- 설계서 재학습 파이프라인: [`../design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 7장
