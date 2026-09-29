# PSI 드리프트 누적·확장 통계 특징의 오탐 영향 실측 (2026-09-29)

> **작성일**: 2026-09-29
> **작성자**: Orca builder (Task ID task_c343bafc0520, Run run_b406a154bbad)
> **기준 커밋**: 8bdd2671 (kwanbum217/orca-d4)
> **기준 시각 now**: 2026-09-29T03:06:00 (모든 측정에 동일 적용)
> **평가 창**: [2026-09-22T03:06:00, 2026-09-29T03:06:00), 7일
> **대상**: Cnstwk(공사), Servc(용역), Thng(물품) 3개 카테고리 모델의 기준선과 7일 평가 창
> **범위**: 코드·설정·DB·기준선을 변경하지 않는다. 본 문서는 실측과 추정을 구분해 기록한다.
> **목적**: 누적·확장 통계 특징(권고 3)이 오탐에 미치는 효과를 운영 데이터로 실측하고, 드리프트 2차 범위 결정의 근거를 제공한다.

---

## 1. 요약과 판정

7일 평가 창에서 누적·확장 통계 특징(이하 누적 특징) 9종은 **기준선(약 123일 프레임)과 창(7일 프레임)의 누적 깊이 차이만으로 PSI 가 임계를 넘는다.** 창의 누적 특징 값은 거의 전부 기본값으로 붕괴한다. 원인은 감시 경로가 평가 창 7일 프레임 안에서만 `attach_institution_history` / `attach_repeat_history` 를 돌리기 때문이다.

실측 결과는 다음과 같다.

1. **누적 특징은 비제외 드리프트의 큰 몫을 차지한다.** 7일 창의 누적 드리프트 수는 집단별로 Cnstwk 5, Servc 3+3, Thng 6+2 개다. 1차 제외 목록(달력 4종 + `is_post_regime_shift`)만 적용한 비제외 드리프트 9/16/12건 중 누적 특징이 5/6/8건이다.
2. **그러나 누적 특징을 전부 제외해도 창 판정은 뒤집히지 않는다.** 누적 특징을 제외하면 비제외 드리프트는 Cnstwk 9→4, Servc 16→10, Thng 12→4 로 줄지만, 3개 카테고리 모두 `DRIFT_DETECTED` 로 남는다. 남는 것은 금액·규모와 범주 특징이다. 집단 단위로는 Thng missing_lwlt 만 `DRIFT_DETECTED`→`STABLE` 로 뒤집힌다.
3. **누적 깊이는 프레임 길이의 함수다.** `inst_sample_cnt` 평균은 7일 창 0.3~1.2, 28일 창 1.7~4.9, 기준선(약 123일) 10.2~24.4 로 증가한다. 기준선은 학습 프레임 전체에 대해 누적 깊이를 계산하고, 감시 창은 7일 프레임에 대해서만 계산하므로 두 분포는 구조적으로 어긋난다.
4. **기준선 재생성이 필요한 대안과 불필요한 대안이 갈린다.** "동일 관측 시점 정렬"과 "값 표준화"는 특징값 또는 기준선 히스토그램을 바꾸므로 기준선 재생성을 요구한다(특징 정의를 바꾸면 모델 재학습도 요구). "판정 제외"만 기준선·모델을 건드리지 않는다.
5. **판정 제외로 잃는 실제 탐지 능력은 이 창에서는 관측되지 않는다.** 창의 누적 특징이 기본값으로 붕괴해 PSI 가 프레임 깊이 artifact 를 재는 수준이기 때문이다(추정, 8절).

**2차 범위에 대한 근거**: 누적 특징 제외는 비제외 드리프트 수를 절반 이하로 줄이지만 오탐을 해소하지 못한다. 2차는 (a) 누적 특징 9종의 판정 제외, (b) 금액·규모·범주 특징의 잔존 드리프트 대책, (c) 창 정합·기준선 재생성은 별도 후속 과제로 분리하는 구성이 실측에 부합한다(9절).

---

## 2. 재현 정보와 측정 계약

### 2.1 고정한 측정 파라미터

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 기준 시각 now | 2026-09-29T03:06:00 | 본 Task 에서 한 번 정해 모든 측정에 동일 적용 |
| 평가 창 | [now-7일, now) 개찰일 반열림 | `src/tasks/scheduled_tasks.py:887-891` |
| 임계 | with_lwlt(0.0) 0.20, missing_lwlt(1.0) 0.25 | 기준선 `psi_config.subgroup_thresholds` (`src/ml/monitoring.py:53-59`) |
| 최소 표본 | `min_samples_per_feature=100` | 기준선 `psi_config` |
| 정족수 | 2 (`DRIFT_FEATURE_QUORUM`) | `src/ml/drift_verdict.py:28` |
| 1차 제외 목록 | month_sin, month_cos, weekday_sin, weekday_cos, is_post_regime_shift | `src/ml/drift_verdict.py:12-20` |

### 2.2 모델·기준선 매핑

| 카테고리 | 모델 | baseline_version | 기준선 생성 시각 | 기준선 표본(0.0 / 1.0) |
| --- | --- | --- | --- | --- |
| Cnstwk | cnstwk_institution_v1 | b_20260926_cnstwk_post_regime | 2026-09-26T06:41:19 | 30,212 / 3,415 |
| Servc | servc_institution_v1 | b_20260926b_servc_post_regime | 2026-09-26T14:14:30 | 14,020 / 8,275 |
| Thng | quantum_leap_v25_pro | b_20260915_thng_post_regime | 2026-09-15T06:19:44 | 9,758 / 8,311 |

- 카테고리→모델: `src/ml/training_config.py:68-72` `CATEGORY_MODEL_NAMES`.
- 기준선 파일: `ml_registry/<model>/baseline/feature_distributions_v1.json`, `metadata.json`.
- 하위집단 키: `0.0`=with_lwlt(낙찰하한율 있음), `1.0`=missing_lwlt(하한율 결측).
- 재현: 11절 재현 명령이 위 metadata 를 그대로 읽는다.

### 2.3 평가 경로의 프레임 구성 (코드 확인)

감시 경로는 `_compute_drift_assessment_thread` (`src/tasks/scheduled_tasks.py:689-729`)이며, 순서는 다음과 같다.

1. `build_training_dataset(db, category_code, start_at=now-7일, end_at=now, persist=False)` — 7일 구간만 조회 (`src/ml/dataset.py:152-171`, `233-236`).
2. `attach_institution_history(df_raw)` (`src/tasks/scheduled_tasks.py:717`) — **7일 프레임 안에서만** expanding 누적.
3. `attach_repeat_history(df_raw)` (`:718`) — **7일 프레임 안에서만** 재발주 누적.
4. `check_dataset_drift(baseline_dist, df_feat, evaluation_window_days=7)` (`:725-729`).

학습 경로(`ModelTrainer.train_and_register`)도 같은 두 함수를 쓰지만 대상이 학습 프레임 전체다(`src/ml/trainer.py:390-391`). 이 차이가 6절의 구조적 원인이다.

### 2.4 이 문서의 분류와 1차 문서의 차이

1차 문서(`docs/analysis/drift_all_categories_20260928.md` 4.1절)는 범주 특징을 "기타"에 묶었다. 본 문서는 판정 대책을 정하기 위해 **누적 통계 / 금액·규모 / 범주 / 달력·레짐** 네 류로 분리한다. 누적 통계는 3절에서 코드로 확정한 `inst_*`, `repeat_*` 9종이다.

---

## 3. 누적 통계 특징 목록 (코드 확인)

`build_default_feature_map` (`src/ml/features.py:246-336`)와 두 이력 모듈이 만들어 내는 `inst_*`, `repeat_*` 특징 전부는 다음과 같다. 이 중 기준선에 실제로 저장되어 판정에 쓰이는 것만 "평가됨"이다.

| 특징 | 생성 코드 | 기준선 저장 여부 | 판정 대상 |
| --- | --- | --- | --- |
| inst_hist_rate | `src/ml/institution_history.py` `attach_institution_history` / `lookup_institution_stats` | 저장됨 | 예 |
| inst_sample_cnt | 위와 같음(누적 표본 수) | 저장됨 | 예 |
| inst_ewm_rate | 위와 같음(지수감쇠), Servc 전용 | 저장됨 | 예 (Servc) |
| inst_rate_mean_30d | `src/ml/features.py:294` | 미저장(학습 특징 아님) | 아니오 |
| inst_rate_std_90d | `src/ml/features.py:295` | 미저장 | 아니오 |
| inst_part_avg | `src/ml/features.py:314` | 미저장 | 아니오 |
| inst_inter_sem_* (5종) | `src/ml/features.py:337-345` | 미저장 | 아니오 |
| is_repeat | `src/ml/repeat_history.py` `attach_repeat_history` | 저장됨 | 예 |
| repeat_cnt | 위와 같음 | 저장됨 | 예 |
| repeat_hist_rate | 위와 같음 | 저장됨 | 예 |
| repeat_prev_rate | 위와 같음 | 저장됨 | 예 |
| repeat_hist_std | 위와 같음 | 저장됨 | 예 |
| repeat_days_since | 위와 같음 | 저장됨 | 예 |

**판정 대상 누적 특징 9종**(본 문서 이후 "누적 특징"): `inst_hist_rate`, `inst_sample_cnt`, `inst_ewm_rate`(Servc), `is_repeat`, `repeat_cnt`, `repeat_hist_rate`, `repeat_prev_rate`, `repeat_hist_std`, `repeat_days_since`.

- 기준선 특징 수는 Cnstwk/Thng 34종, Servc 35종(위 9종 중 Servc 만 `inst_ewm_rate` 포함). `src/ml/training_config.py:168-197`.
- 재현: 11절 재현 명령 첫 출력이 카테고리별 기준선 특징 키를 그대로 나열한다.

---

## 4. 특징 분류와 카테고리·집단별 PSI (실측)

분류 기준은 다음과 같다.

| 류 | 특징 |
| --- | --- |
| 달력·레짐 (1차 제외 목록) | month_sin, month_cos, weekday_sin, weekday_cos, is_post_regime_shift |
| 누적 통계 | 3절의 9종 |
| 금액·규모 | log_price, notice_amt_ratio, is_over_notice_amt, tot_prdprc_num, drwt_prdprc_num, notice_duration |
| 범주 | srvce_div_nm, lrg_clsfc_nm, cntrct_mthd_nm, prearng_mthd, sucsfbid_mthd_nm, mid_clsfc_nm, clsfc_nm, ntce_kind_nm, bid_methd_nm, intrbid_yn, ppsw_gnrl_srvce_yn |
| 기타 | lwlt_rate, lwlt_rate_missing, tech_ablt_evl_rt, bid_prce_evl_rt |

### 4.1 류별 드리프트 개수 (드리프트 특징만 계수)

| 카테고리 (집단, 표본 n) | 달력·레짐 | 누적 | 금액·규모 | 범주 | 계 | 비제외 계 |
| --- | --- | --- | --- | --- | --- | --- |
| Cnstwk (0.0, 432) | 5 | 5 | 2 | 2 | 14 | 9 |
| Cnstwk (1.0, 73) | - | - | - | - | 0 | 0 (INSUFFICIENT_DATA) |
| Servc (0.0, 222) | 5 | 3 | 2 | 4 | 14 | 9 |
| Servc (1.0, 160) | 5 | 3 | 1 | 3 | 12 | 7 |
| Thng (0.0, 361) | 5 | 6 | 2 | 2 | 15 | 10 |
| Thng (1.0, 311) | 5 | 2 | 0 | 0 | 7 | 2 |

- 표본 n 은 `lwlt_rate_missing` 로 분리한 집단별 창 표본 수다. Cnstwk 1.0 은 73 < 100 이라 판정 불가다.
- 재현: 11절 재현 명령 `PROG` 줄 및 `check_dataset_drift` 의 `by_subgroup[*].drift_results`.

### 4.2 카테고리·집단별 드리프트 특징과 PSI (임계 이상만)

Cnstwk (0.0, n=432, 임계 0.20): 달력·레짐 `month_cos` 8.7442, `month_sin` 6.2477, `weekday_cos` 3.6189, `weekday_sin` 3.3354, `is_post_regime_shift` 0.5069 / 누적 `inst_sample_cnt` 2.8322, `inst_hist_rate` 2.2753, `repeat_prev_rate` 0.3522, `repeat_hist_rate` 0.3339, `is_repeat` 0.2670 / 금액·규모 `notice_duration` 0.4965, `log_price` 0.2435 / 범주 `sucsfbid_mthd_nm` 0.5588, `cntrct_mthd_nm` 0.3934.

Servc (0.0, n=222, 임계 0.20): 달력·레짐 `month_cos` 8.4930, `month_sin` 5.4900, `weekday_cos` 3.5312, `weekday_sin` 3.2585, `is_post_regime_shift` 0.5159 / 누적 `inst_ewm_rate` 3.2990, `inst_sample_cnt` 2.0071, `inst_hist_rate` 1.2998 / 금액·규모 `log_price` 0.3799, `is_over_notice_amt` 0.2484 / 범주 `sucsfbid_mthd_nm` 0.9822, `clsfc_nm` 0.7600, `cntrct_mthd_nm` 0.3530, `mid_clsfc_nm` 0.2284.

Servc (1.0, n=160, 임계 0.25): 달력·레짐 `month_cos` 8.4999, `month_sin` 5.7726, `weekday_cos` 3.4733, `weekday_sin` 3.2008, `is_post_regime_shift` 0.3557 / 누적 `inst_ewm_rate` 2.6725, `inst_hist_rate` 2.6660, `inst_sample_cnt` 1.5501 / 금액·규모 `log_price` 0.3625 / 범주 `clsfc_nm` 1.0787, `mid_clsfc_nm` 0.4518, `sucsfbid_mthd_nm` 0.3887.

Thng (0.0, n=361, 임계 0.20): 달력·레짐 `month_cos` 11.1743, `month_sin` 6.4088, `weekday_cos` 3.6900, `weekday_sin` 3.4067, `is_post_regime_shift` 0.5661 / 누적 `inst_hist_rate` 2.1578, `inst_sample_cnt` 0.8066, `repeat_days_since` 0.4576, `repeat_hist_rate` 0.3864, `repeat_prev_rate` 0.3781, `is_repeat` 0.2827 / 금액·규모 `log_price` 0.5674, `is_over_notice_amt` 0.2746 / 범주 `sucsfbid_mthd_nm` 0.8775, `cntrct_mthd_nm` 0.3321.

Thng (1.0, n=311, 임계 0.25): 달력·레짐 `month_cos` 10.1805, `month_sin` 5.7959, `weekday_sin` 2.7023, `weekday_cos` 2.2699, `is_post_regime_shift` 0.2859 / 누적 `inst_hist_rate` 2.2928, `inst_sample_cnt` 0.8642.

- 누적 특징 중 임계 미달: Cnstwk `repeat_cnt` 0.0325, `repeat_hist_std` 0.0412, `repeat_days_since` 0.1430; Servc `is_repeat` 0.1828, `repeat_hist_std` 0.0078 등 전부 0.2 미만.
- 재현: 11절 재현 명령이 `by_subgroup[*].drift_results` 의 `psi`/`drift_detected` 를 출력한다.

---

## 5. 단계적 제외 실측 (실측)

제외 목록을 세 단계로 넓혔다. v1 = 1차 제외 목록(달력 4종 + `is_post_regime_shift`), v2 = v1 + 누적 9종, v3 = v2 + 금액·규모 6종. 정족수는 2 로 고정했다.

### 5.1 집단별 비제외 드리프트 개수

| 카테고리 (집단, n) | v1 | v2 (+누적) | v3 (+금액·규모) |
| --- | --- | --- | --- |
| Cnstwk (0.0, 432) | 9 | 4 | 2 |
| Cnstwk (1.0, 73) | 0 (INSUFFICIENT) | 0 | 0 |
| Servc (0.0, 222) | 9 | 6 | 4 |
| Servc (1.0, 160) | 7 | 4 | 3 |
| Thng (0.0, 361) | 10 | 4 | 2 |
| Thng (1.0, 311) | 2 | 0 | 0 |

### 5.2 카테고리·집단별 창 판정

| 카테고리 | 집단 | v1 | v2 (+누적) | v3 (+금액·규모) |
| --- | --- | --- | --- | --- |
| Cnstwk | 0.0 | DRIFT_DETECTED | DRIFT_DETECTED | DRIFT_DETECTED |
| Cnstwk | 1.0 | INSUFFICIENT_DATA | INSUFFICIENT_DATA | INSUFFICIENT_DATA |
| Servc | 0.0 | DRIFT_DETECTED | DRIFT_DETECTED | DRIFT_DETECTED |
| Servc | 1.0 | DRIFT_DETECTED | DRIFT_DETECTED | DRIFT_DETECTED |
| Thng | 0.0 | DRIFT_DETECTED | DRIFT_DETECTED | DRIFT_DETECTED |
| Thng | 1.0 | DRIFT_DETECTED | STABLE | STABLE |
| **카테고리 종합** | - | **3/3 DRIFT_DETECTED** | **3/3 DRIFT_DETECTED** | **3/3 DRIFT_DETECTED** |

### 5.3 해석

- 누적 특징 제외(v2)는 비제외 드리프트를 크게 줄인다(합계 Cnstwk 9→4, Servc 16→10, Thng 12→4). 그러나 **어느 카테고리도 창 판정이 DRIFT_DETECTED→STABLE 로 뒤집히지 않는다.** 남은 비제외 드리프트는 여전히 정족수 2 이상이다.
- 집단 단위로는 Thng missing_lwlt 만 v2 에서 STABLE 로 뒤집힌다(비제외 드리프트 2 → 0). 이 집단의 v1 드리프트 2건은 정확히 `inst_hist_rate`, `inst_sample_cnt` 였다. 즉 누적 특징이 유일한 트리거였던 유일한 집단이다.
- v3(금액·규모까지 제외)에서도 3개 카테고리 종합은 DRIFT_DETECTED 다. Cnstwk/Thng 는 범주 2건(`sucsfbid_mthd_nm`, `cntrct_mthd_nm`), Servc 는 범주 3~4건이 남는다.
- 재현: 11절 재현 명령 `PROG` 줄.

### 5.4 지속성 조건과의 관계 (실측 보조)

본 Task 의 창 판정은 `check_dataset_drift` 의 원시 창 판정이다. 실제 감시 경로는 `apply_drift_persistence` (`src/ml/drift_verdict.py:85-116`)로 직전 겹치지 않는 창의 `window_drift` 를 요구한다. retrain_logs 의 `drift_monitor` 기록을 읽어 보면 **모든 기록의 `metrics_summary.window_drift` 가 없음(None)** 이다. 따라서 1차 규칙을 적용하면 이번 창의 3개 카테고리는 `DRIFT_DETECTED` 가 아니라 `DRIFT_PENDING` 으로 보류된다. 본 문서의 v1/v2/v3 판정은 창 자체 판정이므로 이 지속성 단계 이전 값이다.

- 재현: 11절 재현 명령에는 넣지 않았다. 읽기 전용 질의 `select id, champion_version, status, created_at, metrics_summary from retrain_logs where trigger_source='drift_monitor' order by created_at desc` 로 확인했다.

---

## 6. 누적 깊이와 단조성 (실측 + 코드 확인)

### 6.1 대표 누적 특징의 기준선 대 창 분포 요약

`inst_sample_cnt` 를 대표로 제시한다. 값은 (평균 / 중앙값 / 최대)다.

| 카테고리 (집단) | 기준선 JSON (약 123일) | 재구성 기준선 (123일) | 7일 창 | 28일 창 |
| --- | --- | --- | --- | --- |
| Cnstwk (0.0) | 24.42 / 13 / 201 | 24.63 / 14 / 205 | 1.19 / 0 / 13 | 4.92 / 2 / 41 |
| Cnstwk (1.0) | 14.28 / 8 / 137 | 14.35 / 8 / 139 | 0.22 / 0 / 3 | 2.91 / 1 / 28 |
| Servc (0.0) | 14.71 / 8 / 172 | 14.88 / 8 / 173 | 0.86 / 0 / 12 | 2.57 / 1 / 20 |
| Servc (1.0) | 12.39 / 5 / 166 | 12.49 / 5 / 166 | 0.30 / 0 / 4 | 2.26 / 1 / 21 |
| Thng (0.0) | 10.19 / 3 / 198 | 10.74 / 3 / 216 | 0.34 / 0 / 4 | 1.73 / 0 / 33 |
| Thng (1.0) | 19.32 / 4 / 304 | 20.38 / 4 / 332 | 0.51 / 0 / 8 | 4.01 / 0 / 91 |

**누적 깊이는 프레임 길이에 단조로 증가한다**: 7일 < 28일 < 123일. 창의 중앙값은 모든 집단에서 0~2 로, 기준선(3~14)과 다른 위치에 있다. 이것이 `inst_sample_cnt` PSI(0.81~2.83)의 지배적 원인이다.

`inst_hist_rate` 는 창에서 기본값으로 붕괴한다. `attach_institution_history` 는 기관 이력 표본이 `min_samples=5` 미만이면 카테고리 기본값을 채운다(`src/ml/institution_history.py`, `HISTORY_MIN_SAMPLES = 5`). 7일 창에서는 대부분 기관이 5건을 못 채우므로 창의 `inst_hist_rate` 는 p25=p50=p75 가 카테고리 기본값(Cnstwk 0.8859, Servc 0.9011, Thng 0.9132)이다. 기준선의 `inst_hist_rate` 는 0.90 부근 좁은 스파이크(std≈0.009~0.034)이므로, 상수로 붕괴한 창과 비교하면 PSI 가 크게 벌어진다.

`repeat_*` 도 같은 구조다. 7일 창에서 `repeat_cnt` p95 = 0, `repeat_days_since` p95 = -1, `is_repeat` 평균 0.002~0.029 로 사실상 전부 기본값이다. 재발주 매칭은 같은 키가 창 안에서 두 번 이상 나타나야 이력이 생기므로 7일 창에서는 거의 발생하지 않는다.

### 6.2 단조성

- **프레임 내 단조**: `attach_institution_history` 는 개찰일 정렬 후 `shift(1).expanding().count()` / `.mean()` 을 쓰므로, 같은 기관의 `inst_sample_cnt` 는 시간에 대해 비감소다(`src/ml/institution_history.py`). `repeat_cnt` 도 같은 구조다(`src/ml/repeat_history.py`).
- **창 내 순위 상관(실측)**: 7일 창에서 `inst_sample_cnt` 와 개찰시각의 Spearman 상관은 Cnstwk 0.1823, Servc 0.1940, Thng 0.0792 로 양(+)이다. 기관 구성이 섞여 값이 약하지만 방향은 단조 증가와 일치한다.
- **프레임 간 단조(실측)**: 6.1절 표에서 프레임이 길수록 평균이 커진다.

### 6.3 기준선 시점의 누적 깊이는 어떻게 정해지는가 (코드 근거)

1. 학습 경로는 `df_raw = attach_institution_history(df_raw)` / `attach_repeat_history(df_raw)` 를 **학습 프레임 전체**에 적용한다(`src/ml/trainer.py:390-391`). 그 `df_feat` 로 기준선을 저장한다(`save_baseline_distributions(df_feat, ...)`, `src/ml/trainer.py:555-560`).
2. `save_baseline_distributions` (`src/ml/monitoring.py:177-260`)는 넘겨받은 프레임의 특징별 히스토그램·분위수를 파일로 굳힌다. 프레임 길이 파라미터는 없고, **프레임 자체가 누적 깊이를 결정**한다.
3. 재학습 파이프라인이 넘기는 학습 프레임은 `build_training_dataset` 의 기본값(start/end = None)으로 만들어지며(`src/tasks/retrain_task.py:144-159`, `src/ml/dataset.py:171`), 기본은 전체 이력이다. 그러나 실제 운영 기준선 3종은 `is_post_regime_shift` 평균이 0.9168~0.9840 이고 `month_sin` 값 범위가 5~9월에 몰려 있어, **레짐 전환일(2026-05-26, `src/ml/features.py:32`)부터 기준선 생성일까지의 프레임**으로 만들어졌음을 보인다.
4. 이를 확인하기 위해 `[2026-05-26, 기준선 생성 시각)` 프레임을 같은 코드로 재구성하면 행 수와 `inst_sample_cnt` 통계가 기준선 JSON 과 근접한다.

| 카테고리 | 기준선 training_samples | 재구성 행 수 | 기준선 inst_sample_cnt 평균/중앙값/최대 | 재구성 평균/중앙값/최대 |
| --- | --- | --- | --- | --- |
| Cnstwk | 33,627 | 33,936 | 24.42 / 13 / 201 | 24.63 / 14 / 205 |
| Servc | 22,295 | 22,510 | 14.71 / 8 / 172 | 14.88 / 8 / 173 |
| Thng | 18,069 | 19,487 | 10.19 / 3 / 198 | 10.74 / 3 / 216 |

- 즉 기준선의 누적 깊이는 **약 123일 프레임에서의 기관별 선행 행 수**이고, 감시 창의 누적 깊이는 **7일 프레임에서의 선행 행 수**다. 두 값은 같은 정의의 서로 다른 스케일이며, PSI 는 이 스케일 차이를 그대로 잰다.
- Thng 만 재구성 행 수가 7.8% 많다. 실제 기준선 프레임 종료일이 2026-09-15 이전이거나 추가 필터가 있었을 수 있다. 그래도 `inst_sample_cnt` 통계는 근접해 결론을 바꾸지 않는다(10절).
- 재현: 11절 재현 명령 `DEPTH` 줄.

---

## 7. 시간 정렬 대안과 기준선 재생성 요구 (코드 근거 + 추정)

| 대안 | 무엇을 바꾸는가 | 기준선 재생성 필요 | 모델 재학습 필요 | 코드 근거 |
| --- | --- | --- | --- | --- |
| 동일 관측 시점 정렬 (창 길이 정합 기준선) | 기준선 히스토그램을 7일(또는 창과 같은 길이) 프레임에서 재생성 | **필요** | 불필요 (모델 입력값 불변) | `save_baseline_distributions(df_feat, feature_columns, target_dir, ...)` 는 임의 프레임을 받는다(`src/ml/monitoring.py:177`). 호출부는 `src/ml/trainer.py:555` 하나뿐이다. |
| 동일 관측 시점 정렬 (특징 정의를 고정 lookback 으로) | `src/ml/features.py` / `institution_history.py` / `repeat_history.py` 의 누적 정의 | **필요** | **필요** | 특징 단일 공급원 `src/ml/features.py` (`AGENTS.md` 6항). 학습·서빙이 같은 함수를 쓰므로 값을 바꾸면 양쪽이 함께 바뀐다. |
| 값 표준화 (프레임 크기·기본값 기준 정규화) | 누적 특징값 자체 | **필요** | **필요** | `build_default_feature_map` 이 유일 정의(`src/ml/features.py:246`). `check_dataset_drift` 는 기준선에 저장된 원시 히스토그램과 원시 창 값을 비교하며 변환 훅이 없다(`src/ml/monitoring.py:330-455`). |
| 판정 제외 | `DRIFT_VERDICT_EXCLUDED_FEATURES` 또는 호출부 `excluded_features` | 불필요 | 불필요 | `src/ml/drift_verdict.py:12-20`, `check_dataset_drift(..., excluded_features=...)` (`src/ml/monitoring.py:295-299`) |

핵심 판단:

- **기준선 재생성이 필요한 경우**: 동일 관측 시점 정렬과 값 표준화다. 기준선 히스토그램은 정적 아티팩트이므로, 창과 비교 가능하게 만들려면 새 프레임에서 다시 굳혀야 한다.
- **재생성 경로**: 현재 `src` 안에서 기준선을 다시 쓰는 경로는 학습 파이프라인 `ModelTrainer.train_and_register` → `save_baseline_distributions` 하나다(`src/ml/trainer.py:555`). 감시 경로(`check_dataset_drift`)는 기준선을 읽기만 하고 다시 쓰지 않는다. 따라서 "창 길이 정합 기준선"을 만들려면 **새 호출 경로를 추가해야 하며 이는 본 Task 범위 밖**이다.
- **영향 범위**: 모델 입력값을 바꾸는 대안(특징 정의 변경, 값 표준화)은 3개 카테고리 모델 재학습과 3개 기준선 재생성을 동시에 요구한다. 창 길이 정합 기준선만 바꾸는 대안은 기준선 JSON 3개 파일만 바꾸지만, 기준선이 "학습 분포"라는 의미도 함께 바뀌므로 해석상 영향이 있다.
- **가장 저렴한 대안은 판정 제외**다. 코드 한 곳(`DRIFT_VERDICT_EXCLUDED_FEATURES` 확장) 또는 호출부 인자로 끝나고 기준선·모델·DB 를 건드리지 않는다.

---

## 8. 누적 특징을 판정에서 빼면 잃는 탐지 능력 (추정)

### 8.1 모델 성능 관점

누적 특징, 특히 `inst_hist_rate` 는 낙찰률 예측의 핵심 신호다(단독 R2 0.33, `src/ml/institution_history.py` 모듈 docstring; 학습 특징 선정 근거 `src/ml/training_config.py:142-151`). 그러나 본 검토는 **드리프트 감시 판정**에서 빼는 것이며, 서빙 시 모델 입력에서 빼는 것이 아니다. 예측 성능은 영향받지 않는다.

### 8.2 감시 관점에서 잃는 것 (추정)

판정에서 누적 특징을 빼면 다음 실제 변화를 감시가 놓칠 수 있다.

- 기관별 과거 낙찰률 **수준**의 이동(예: 제도 개정으로 기관 평균 낙찰률이 통째로 이동).
- 기관 이력 **깊이·집중도** 변화(신규 기관 급증 등).
- **재발주 비중** 변화.

### 8.3 정량 근거와 추정의 분리

- **실측**: 이번 7일 창에서 누적 특징을 전부 제외해도 카테고리 종합 창 판정은 3개 모두 DRIFT_DETECTED 로 유지됐다(5.2절). 즉 이 창에서는 누적 특징 제외로 인해 트리거가 사라지는 경우가 없다. 유일한 집단 단위 변화는 Thng missing_lwlt 의 STABLE 전환이다.
- **실측**: 창의 누적 특징은 대부분 기본값으로 붕괴한다(6.1절). 붕괴한 값의 PSI 는 실제 모집단 변화보다 프레임 깊이 차이를 반영하므로, 현재 7일 창에서 누적 특징 PSI 가 담고 있는 **실제 변화 정보량은 작다**.
- **추정**: 따라서 판정 제외로 잃는 실제 탐지 능력은 이 창 구성(7일)에서는 작다. 누적 특징의 실제 감시 가치는 창을 28일 이상으로 넓히거나 고정 lookback 으로 정의를 바꿔야 회복된다. 그 전까지 7일 창 PSI 로 누적 특징을 감시하는 것은 신호 대비 잡음이 낮다.
- **잔여 위험(추정)**: 기관 낙찰률 수준만 이동하고 금액·규모·범주는 안정적인 변화가 발생하면, 누적 특징을 제외한 판정은 이를 놓친다. 이 경우를 감시하려면 누적 특징을 버리는 것이 아니라 정렬된 통계로 다시 설계해야 한다(7절의 재생성 대안).

---

## 9. 권고

우선순위 순으로 정리한다. 어느 항목도 본 Task 에서 실행하지 않았다.

1. **누적 특징 9종을 판정 제외 후보로 확정한다.** 근거: 창 값이 기본값으로 붕괴하고(6.1절), PSI 가 프레임 깊이 차이에 지배된다(6.3절). 비용은 `DRIFT_VERDICT_EXCLUDED_FEATURES` 확장 또는 호출부 인자이며 기준선·모델을 건드리지 않는다(7절). 실측 효과: 비제외 드리프트 합계 Cnstwk 9→4, Servc 16→10, Thng 12→4.
2. **제외만으로는 오탐이 해소되지 않음을 2차 범위에 반영한다.** v3(금액·규모까지 제외)에서도 3개 카테고리 종합은 DRIFT_DETECTED 이며, 남는 것은 범주 특징(`cntrct_mthd_nm`, `sucsfbid_mthd_nm`, `clsfc_nm`, `mid_clsfc_nm`)과 일부 금액·규모다(5.2~5.3절). 2차는 범주·금액·규모 대책을 함께 다뤄야 한다.
3. **누적 특징의 실제 감시는 창 정합·기준선 재생성 과제로 분리한다.** 동일 관측 시점 정렬 또는 값 표준화는 기준선 재생성을 요구하고, 특징 정의를 바꾸면 모델 재학습까지 요구한다(7절). 2차에서 실행하려면 별도 Task 로 분리하고 영향 범위(3개 모델 재학습 + 3개 기준선 재생성)를 명시한다.
4. **지속성·정족수 규칙을 2차에서 재점검한다.** 1차 지속성 규칙은 직전 창 기록이 없어 현재 모든 카테고리를 DRIFT_PENDING 으로 보류한다(5.4절). 누적 특징을 제외한 뒤 정족수를 다시 볼 근거가 마련됐다.
5. **창 확대 또는 다중 창 검토를 2차 후보로 둔다.** 7일 창은 연휴·수집 지연에 취약하고 누적 특징을 기본값으로 붕괴시킨다(1차 문서 8절 4항, 6.1절). 누적 특징을 감시 대상으로 유지하려면 창 길이가 선행 조건이다.

---

## 10. 한계

- 본 Task 의 허용 범위에 `scripts/` 가 없어 기준선 생성 스크립트를 열람하지 못했다. 6.3절의 기준선 프레임 재구성은 `src` 의 코드 경로와 기준선 JSON 통계로 역산한 것이며, 실제 생성 스크립트가 있다면 파라미터가 다를 수 있다.
- Thng 기준선 재구성 행 수가 18,069 대비 19,487(약 7.8% 많음)이다. 실제 프레임 종료일이 2026-09-15 이전이거나 추가 필터가 있었을 가능성이 있다. `inst_sample_cnt` 통계는 근접해 결론에는 영향이 없다.
- 창의 특징값은 어디에도 영속되지 않아, 창 프레임을 코드로 재구성해 측정했다(2.3절). 재구성은 감시 경로와 동일한 함수 호출 순서를 쓴다.
- 5.4절 지속성 관계는 retrain_logs 읽기로 확인한 사실이며, 본 문서의 v1/v2/v3 표는 지속성 적용 이전의 창 판정이다.
- 8절의 탐지 능력 손실은 추정이며, 본 Task 에서 실제 변화 시나리오를 주입한 실험은 하지 않았다.
- 달력·레짐 특징의 오탐 메커니즘은 1차 문서(`docs/analysis/drift_all_categories_20260928.md`)의 4~6절을 그대로 인용하지 않고 재측정했으며, 값은 1차 문서와 동일하다.

---

## 11. 재현 명령

아래 히어독은 읽기 전용이다. `persist=False` 로 Parquet 을 쓰지 않고, retrain_logs 기록·알림 함수·기준선 파일을 호출하거나 수정하지 않는다. now 는 2026-09-29T03:06:00 로 고정한다. DB 는 `.env` 의 127.0.0.1:3306 을 읽기만 한다.

```sh
uv run python - <<'EOF'
import json
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from src.ml.dataset import build_training_dataset
from src.ml.institution_history import attach_institution_history
from src.ml.repeat_history import attach_repeat_history
from src.ml.features import (
    build_feature_frame, collect_category_levels, apply_categorical_dtypes,
)
from src.ml.monitoring import load_baseline_distributions, check_dataset_drift
from src.ml.drift_verdict import DRIFT_VERDICT_EXCLUDED_FEATURES
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks.scheduled_tasks import SessionLocal

NOW = datetime(2026, 9, 29, 3, 6, 0)
WIN = 7
CUMULATIVE = {"inst_hist_rate","inst_sample_cnt","inst_ewm_rate","is_repeat","repeat_cnt",
              "repeat_hist_rate","repeat_prev_rate","repeat_hist_std","repeat_days_since"}
AMOUNT = {"log_price","notice_amt_ratio","is_over_notice_amt","tot_prdprc_num",
          "drwt_prdprc_num","notice_duration"}
BASE_START = datetime(2026, 5, 26)
BASE_CREATED = {"Cnstwk": datetime(2026,9,26,6,41,19),
                "Servc": datetime(2026,9,26,14,14,30),
                "Thng": datetime(2026,9,15,6,19,44)}
VARIANTS = {
    "v1_calendar_regime": set(DRIFT_VERDICT_EXCLUDED_FEATURES),
    "v2_plus_cumulative": set(DRIFT_VERDICT_EXCLUDED_FEATURES) | CUMULATIVE,
    "v3_plus_amount": set(DRIFT_VERDICT_EXCLUDED_FEATURES) | CUMULATIVE | AMOUNT,
}
CATS = ["Cnstwk", "Servc", "Thng"]

def stat(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return (round(float(s.mean()), 2), int(s.median()), int(s.max()))

def build_frame(cat, start, end):
    db = SessionLocal()
    try:
        df = build_training_dataset(db, category_code=cat, start_at=start, end_at=end, persist=False)
    finally:
        db.close()
    if df.empty:
        return None
    df = attach_institution_history(df)
    df = attach_repeat_history(df)
    f = pd.DataFrame(build_feature_frame(df.to_dict(orient="records")))
    return apply_categorical_dtypes(f, collect_category_levels(f))

for cat in CATS:
    model = CATEGORY_MODEL_NAMES[cat]
    base = load_baseline_distributions(Path("ml_registry") / model / "baseline")
    print("BASE", cat, base["model_version"], base["training_samples"], len(base["features"]))
    df7 = build_frame(cat, NOW - timedelta(days=WIN), NOW)
    df28 = build_frame(cat, NOW - timedelta(days=28), NOW)
    dfb = build_frame(cat, BASE_START, BASE_CREATED[cat])
    print("FRAME", cat, "rebuilt_base", len(dfb), "w7", len(df7), "w28", len(df28))
    r1 = check_dataset_drift(base, df7, evaluation_window_days=WIN)
    for sk, s in r1["by_subgroup"].items():
        drifts = sorted([(f, v["psi"], v.get("excluded_from_verdict", False))
                         for f, v in s["drift_results"].items() if v["drift_detected"]], key=lambda x: -x[1])
        print("DRIFT", cat, sk, "n", s["recent_samples"], "status", s["status"],
              "count", s["drift_feature_count"], drifts)
    for name, excl in VARIANTS.items():
        r = check_dataset_drift(base, df7, evaluation_window_days=WIN, excluded_features=excl)
        per = {sk: (s["status"], s["drift_feature_count"]) for sk, s in r["by_subgroup"].items()}
        print("PROG", cat, name, "overall", r["status"], "combined", r["drift_feature_count"], per)
    for sk in ("0.0", "1.0"):
        bf = base["by_lwlt_missing"][sk]["features"]["inst_sample_cnt"]
        m7 = df7["lwlt_rate_missing"].astype(float) == float(sk)
        m28 = df28["lwlt_rate_missing"].astype(float) == float(sk)
        mb = dfb["lwlt_rate_missing"].astype(float) == float(sk)
        print("DEPTH", cat, sk,
              "base_json", (round(bf["mean"], 2), int(bf["quantiles"]["0.5"]), int(bf["max"])),
              "rebuilt_base", stat(dfb.loc[mb, "inst_sample_cnt"]),
              "w7", stat(df7.loc[m7, "inst_sample_cnt"]),
              "w28", stat(df28.loc[m28, "inst_sample_cnt"]))
EOF
```

대조 기준:

- `BASE` 줄의 특징 수(34/35)와 3절의 판정 대상 누적 특징 포함 여부.
- `FRAME` 줄은 2.2·6.3절의 표본 수다. `rebuilt_base` 는 6.3절 재구성 행 수, `w7`/`w28` 은 창 표본 수다.
- `DRIFT` 줄은 4.1·4.2절이다. `n` 은 집단 표본 수, `count` 는 비제외 드리프트 수, 뒤 목록은 드리프트 특징의 (이름, PSI, 1차 제외 여부)다. `True` 는 1차 제외 목록, `False` 는 판정 대상이다.
- `PROG` 줄은 5.1·5.2절이다. 집단별 (상태, 비제외 드리프트 수)와 카테고리 종합(overall, combined)이 일치해야 한다.
- `DEPTH` 줄은 6.1·6.3절이다. (평균, 중앙값, 최대)가 집단 `0.0`/`1.0` 별로 일치해야 한다.
