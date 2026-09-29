# PSI 드리프트 평가 창 길이 효과 실측 (2026-09-29)

> **작성일**: 2026-09-29
> **작성자**: Orca builder (Task task_2cf1cda9e939)
> **기준 커밋**: `8bdd2671` (브랜치 `kwanbum217/orca-d3`)
> **기준 시각(now)**: 2026-09-28 03:06:02 (DB 저장 시각 기준, naive). 1차 판정이 기록된 `retrain_logs` id 18·19·20 의 실행 시각과 맞췄다.
> **범위**: 코드·설정·DB·기준선을 변경하지 않는다. 본 문서는 실측 결과만 기록한다.

---

## 1. 판정 요약

**창 길이를 7일에서 28일로 늘리는 것만으로는 오탐이 해소되지 않는다.** 비제외 드리프트
개수는 크게 줄지만(공사 9, 용역 17, 물품 12 -> 공사 4, 용역 6, 물품 5) 정족수 2 이상이
유지되어 세 카테고리 모두 여전히 `DRIFT_DETECTED` 이다. 겹치지 않는 직전 창까지 보는
지속성 규칙도 7·14·28일 창 모두에서 알림을 막지 못한다. 직전 창도 `DRIFT_DETECTED` 였기
때문이다.

구조 원인은 **누적·이력 특징(`inst_hist_rate`, `inst_sample_cnt`, `inst_ewm_rate`)이 전달된
프레임 안에서만 누적 계산된다는 점**이다. 기준선은 학습 프레임 전체(약 4개월)로 만들어져
`inst_sample_cnt` 평균이 24.4 이지만, 감시 창은 창 안의 행만 세므로 7일 1.15, 28일 5.00,
90일 15.30 이다. 창을 넓히면 이 값이 기준선 쪽으로 수렴해 PSI 가 줄어들 뿐, 창이 기준선
기간을 덮기 전에는 0 이 되지 않는다.

**실효 안은 28일 창 + 누적 특징 제외(또는 전역 as-of 정의로 수선)이다.** 28일 창에서
`inst_*` 3종을 판정에서 빼면 공사·용역·물품 모두 비제외 드리프트 0(물품 물품집단 1, 정족수
미달)로 `STABLE` 이 된다. 반면 7일 창에서 `inst_*` 를 빼도 범주·금액 특징이 소표본으로
드리프트해 여전히 알림이 난다. 즉 **창 확대와 누적 특징 처리는 함께 가야 한다.**

기준선 재생성은 창 길이 변경에 **불필요하다**. 창 길이는 행 선택 구간만 바꾸고 PSI 는
저장된 기준선 히스토그램을 그대로 참조한다. 다만 누적 특징 정의를 수선하면 그 시점에
기준선도 함께 재생성해야 한다(7절).

---

## 2. 측정 설계와 기준 정보

### 2.1 고정 기준 시각과 평가 창

`now = 2026-09-28 03:06:02` 하나를 모든 측정에 사용했다. 평가 창은
`[now - W일, now)` 반열림 구간이며, `build_training_dataset` 이 `BidResult.rl_openg_dt` 로
필터링한다(`src/ml/dataset.py:230-234`). 창은 `src/tasks/scheduled_tasks.py:889-891` 과 같은
규칙이다.

| W (일) | 평가 창 | 직전 비겹침 창(지속성용) |
| ---: | --- | --- |
| 7 | [2026-09-21 03:06:02, 2026-09-28 03:06:02) | [2026-09-14 03:06:02, 2026-09-21 03:06:02) |
| 14 | [2026-09-14 03:06:02, 2026-09-28 03:06:02) | [2026-08-31 03:06:02, 2026-09-14 03:06:02) |
| 28 | [2026-08-31 03:06:02, 2026-09-28 03:06:02) | [2026-08-03 03:06:02, 2026-08-31 03:06:02) |
| 56 | [2026-08-03 03:06:02, 2026-09-28 03:06:02) | [2026-06-08 03:06:02, 2026-08-03 03:06:02) |
| 90 | [2026-06-30 03:06:02, 2026-09-28 03:06:02) | [2026-04-01 03:06:02, 2026-06-30 03:06:02) |

### 2.2 판정 규칙과 기준선

- 판정 함수: `src/ml/monitoring.py` `check_dataset_drift` / `_evaluate_feature_drift_on_frame`.
- 제외 특징 5종(`src/ml/drift_verdict.py:16-24`): `month_sin`, `month_cos`, `weekday_sin`,
  `weekday_cos`, `is_post_regime_shift`.
- 정족수 2(`DRIFT_FEATURE_QUORUM`), 지속성 창 2(`DRIFT_PERSISTENCE_WINDOWS`).
- 임계: with_lwlt 0.20, missing_lwlt 0.25. 특징별 최소 표본 100.
- **정족수는 집단별로 적용되고, 전체 상태는 두 집단 상태의 OR 이다**
  (`src/ml/monitoring.py:494-531`). 전체 `drift_feature_count` 는 두 집단 합이지만 상태를
  결정하지는 않는다. 56일 창 공사·용역의 "합 2, 상태 STABLE" 이 그 예다(부록 B).

| 카테고리 | 모델 | baseline_version | 기준선 표본 (with_lwlt / missing_lwlt) |
| --- | --- | --- | --- |
| Cnstwk(공사) | cnstwk_institution_v1 | b_20260926_cnstwk_post_regime | 33,627 (30,212 / 3,415) |
| Servc(용역) | servc_institution_v1 | b_20260926b_servc_post_regime | 22,295 (14,020 / 8,275) |
| Thng(물품) | quantum_leap_v25_pro | b_20260915_thng_post_regime | 18,069 (9,758 / 8,311) |

DB 는 `.env` 의 127.0.0.1:3306 을 읽기만 했고, 측정 시각은 2026-09-29 10:47 KST 이다.

---

## 3. 창 길이별 판정 (필수 항목 2)

### 3.1 카테고리 요약

`비제외`는 판정에 반영되는 드리프트 특징 수(두 집단 합), `제외`는 제외 5종 중 임계를 넘은
수(두 집단 합)다.

| W | 카테고리 | 창 표본 | 창 판정 | 비제외 | 제외 |
| ---: | --- | ---: | :---: | ---: | ---: |
| 7 | Cnstwk | 605 | DRIFT_DETECTED | 9 | 5 |
| 7 | Servc | 443 | DRIFT_DETECTED | 17 | 10 |
| 7 | Thng | 903 | DRIFT_DETECTED | 12 | 10 |
| 14 | Cnstwk | 1,959 | DRIFT_DETECTED | 4 | 5 |
| 14 | Servc | 1,438 | DRIFT_DETECTED | 9 | 6 |
| 14 | Thng | 2,179 | DRIFT_DETECTED | 8 | 6 |
| 28 | Cnstwk | 5,047 | DRIFT_DETECTED | 4 | 5 |
| 28 | Servc | 3,626 | DRIFT_DETECTED | 6 | 6 |
| 28 | Thng | 4,362 | DRIFT_DETECTED | 5 | 6 |
| 56 | Cnstwk | 11,037 | STABLE | 2 | 5 |
| 56 | Servc | 8,354 | STABLE | 2 | 6 |
| 56 | Thng | 9,235 | STABLE | 0 | 5 |
| 90 | Cnstwk | 20,340 | STABLE | 0 | 5 |
| 90 | Servc | 14,321 | STABLE | 0 | 5 |
| 90 | Thng | 14,296 | STABLE | 0 | 5 |

### 3.2 W=7 (운영 기본)

| 카테고리 | 집단 | 표본 | 판정 | 비제외 드리프트 특징 (PSI) | 제외 |
| --- | --- | ---: | :---: | --- | ---: |
| Cnstwk | with_lwlt | 519 | DRIFT_DETECTED | inst_sample_cnt 2.8322, inst_hist_rate 2.5808, sucsfbid_mthd_nm 0.4894, notice_duration 0.4566, cntrct_mthd_nm 0.3551, repeat_hist_rate 0.3146, log_price 0.2388, is_repeat 0.2242, repeat_prev_rate 0.2147 | 5 |
| Cnstwk | missing_lwlt | 86 | INSUFFICIENT_DATA | (표본 부족) | 0 |
| Servc | with_lwlt | 266 | DRIFT_DETECTED | inst_ewm_rate 3.2990, inst_sample_cnt 2.0071, inst_hist_rate 1.4863, sucsfbid_mthd_nm 0.8437, clsfc_nm 0.6144, cntrct_mthd_nm 0.2623, log_price 0.2440, notice_duration 0.2153 | 5 |
| Servc | missing_lwlt | 177 | DRIFT_DETECTED | inst_hist_rate 2.4631, inst_ewm_rate 2.4620, inst_sample_cnt 1.5501, clsfc_nm 0.9537, mid_clsfc_nm 0.4487, sucsfbid_mthd_nm 0.2981, log_price 0.2820, tech_ablt_evl_rt 0.2748, bid_prce_evl_rt 0.2739 | 5 |
| Thng | with_lwlt | 522 | DRIFT_DETECTED | inst_hist_rate 2.0459, sucsfbid_mthd_nm 0.9649, inst_sample_cnt 0.8066, log_price 0.6228, repeat_days_since 0.4576, cntrct_mthd_nm 0.4450, is_over_notice_amt 0.3442, repeat_prev_rate 0.2672, repeat_hist_rate 0.2611, notice_duration 0.2065 | 5 |
| Thng | missing_lwlt | 381 | DRIFT_DETECTED | inst_hist_rate 2.2476, inst_sample_cnt 0.8642 | 5 |

### 3.3 W=14

| 카테고리 | 집단 | 표본 | 판정 | 비제외 드리프트 특징 (PSI) | 제외 |
| --- | --- | ---: | :---: | --- | ---: |
| Cnstwk | with_lwlt | 1,710 | DRIFT_DETECTED | inst_sample_cnt 2.0793, inst_hist_rate 1.3279 | 3 |
| Cnstwk | missing_lwlt | 249 | DRIFT_DETECTED | inst_sample_cnt 2.6142, inst_hist_rate 1.5691 | 2 |
| Servc | with_lwlt | 909 | DRIFT_DETECTED | inst_sample_cnt 2.0071, inst_ewm_rate 1.2247, inst_hist_rate 1.1544, sucsfbid_mthd_nm 0.2861, clsfc_nm 0.2644 | 3 |
| Servc | missing_lwlt | 529 | DRIFT_DETECTED | inst_sample_cnt 1.5501, inst_hist_rate 0.9607, inst_ewm_rate 0.9462, clsfc_nm 0.4234 | 3 |
| Thng | with_lwlt | 1,139 | DRIFT_DETECTED | inst_hist_rate 1.2372, inst_sample_cnt 0.8066, repeat_days_since 0.4576, sucsfbid_mthd_nm 0.3312, cntrct_mthd_nm 0.2205, repeat_hist_rate 0.2051 | 3 |
| Thng | missing_lwlt | 1,040 | DRIFT_DETECTED | inst_hist_rate 0.9594, inst_sample_cnt 0.5801 | 3 |

### 3.4 W=28

| 카테고리 | 집단 | 표본 | 판정 | 비제외 드리프트 특징 (PSI) | 제외 |
| --- | --- | ---: | :---: | --- | ---: |
| Cnstwk | with_lwlt | 4,426 | DRIFT_DETECTED | inst_sample_cnt 1.5057, inst_hist_rate 0.5249 | 3 |
| Cnstwk | missing_lwlt | 621 | DRIFT_DETECTED | inst_sample_cnt 1.1069, inst_hist_rate 0.5960 | 2 |
| Servc | with_lwlt | 2,317 | DRIFT_DETECTED | inst_sample_cnt 1.2878, inst_ewm_rate 0.4287, inst_hist_rate 0.4181 | 3 |
| Servc | missing_lwlt | 1,309 | DRIFT_DETECTED | inst_sample_cnt 0.9145, inst_hist_rate 0.4136, inst_ewm_rate 0.4039 | 3 |
| Thng | with_lwlt | 1,987 | DRIFT_DETECTED | inst_sample_cnt 0.4529, inst_hist_rate 0.3851, repeat_days_since 0.3694 | 3 |
| Thng | missing_lwlt | 2,375 | DRIFT_DETECTED | inst_hist_rate 0.4113, inst_sample_cnt 0.3651 | 3 |

### 3.5 W=56

| 카테고리 | 집단 | 표본 | 판정 | 비제외 드리프트 특징 (PSI) | 제외 |
| --- | --- | ---: | :---: | --- | ---: |
| Cnstwk | with_lwlt | 9,696 | STABLE | inst_sample_cnt 0.6016 | 3 |
| Cnstwk | missing_lwlt | 1,341 | STABLE | inst_sample_cnt 0.6243 | 2 |
| Servc | with_lwlt | 5,423 | STABLE | inst_sample_cnt 0.2563 | 3 |
| Servc | missing_lwlt | 2,931 | STABLE | inst_sample_cnt 0.3248 | 3 |
| Thng | with_lwlt | 4,553 | STABLE | (없음) | 3 |
| Thng | missing_lwlt | 4,682 | STABLE | (없음) | 2 |

### 3.6 W=90

| 카테고리 | 집단 | 표본 | 판정 | 비제외 드리프트 특징 (PSI) | 제외 |
| --- | --- | ---: | :---: | --- | ---: |
| Cnstwk | with_lwlt | 18,096 | STABLE | (없음) | 3 |
| Cnstwk | missing_lwlt | 2,244 | STABLE | (없음) | 2 |
| Servc | with_lwlt | 9,090 | STABLE | (없음) | 3 |
| Servc | missing_lwlt | 5,231 | STABLE | (없음) | 2 |
| Thng | with_lwlt | 7,149 | STABLE | (없음) | 3 |
| Thng | missing_lwlt | 7,147 | STABLE | (없음) | 2 |

**관찰**: 창이 길어질수록 살아남는 비제외 드리프트는 `inst_*` 누적 특징뿐이고, 나머지
범주·금액·재발주 특징은 28일 창에서 모두 임계 아래로 내려간다. 요일 특징 4종과
`is_post_regime_shift` 도 14일 창부터 일부가 임계 아래로 떨어진다(제외 수 5 -> 3).

---

## 4. 28일 창의 PSI 감소 (7일 대비, 필수 항목 3)

7일 창에서 드리프트였던 특징의 28일 창 PSI 다. 28일 목록에 없으면 임계(0.20/0.25) 미만으로
내려간 것이다.

### 4.1 Cnstwk with_lwlt (7일 표본 519 -> 28일 4,426)

| 특징 | 7일 PSI | 28일 PSI | 변화 |
| --- | ---: | ---: | ---: |
| inst_sample_cnt | 2.8322 | 1.5057 | -1.3265 |
| inst_hist_rate | 2.5808 | 0.5249 | -2.0559 |
| sucsfbid_mthd_nm | 0.4894 | < 0.20 | 임계 미만 |
| notice_duration | 0.4566 | < 0.20 | 임계 미만 |
| cntrct_mthd_nm | 0.3551 | < 0.20 | 임계 미만 |
| repeat_hist_rate | 0.3146 | < 0.20 | 임계 미만 |
| log_price | 0.2388 | < 0.20 | 임계 미만 |
| is_repeat | 0.2242 | < 0.20 | 임계 미만 |
| repeat_prev_rate | 0.2147 | < 0.20 | 임계 미만 |

Cnstwk missing_lwlt 은 7일 표본 86 < 100 이라 7일 판정이 불가해 비교하지 못한다.
28일에서는 inst_sample_cnt 1.1069, inst_hist_rate 0.5960 두 개다.

### 4.2 Servc with_lwlt (7일 266 -> 28일 2,317)

| 특징 | 7일 PSI | 28일 PSI | 변화 |
| --- | ---: | ---: | ---: |
| inst_ewm_rate | 3.2990 | 0.4287 | -2.8703 |
| inst_sample_cnt | 2.0071 | 1.2878 | -0.7193 |
| inst_hist_rate | 1.4863 | 0.4181 | -1.0682 |
| sucsfbid_mthd_nm | 0.8437 | < 0.20 | 임계 미만 |
| clsfc_nm | 0.6144 | < 0.20 | 임계 미만 |
| cntrct_mthd_nm | 0.2623 | < 0.20 | 임계 미만 |
| log_price | 0.2440 | < 0.20 | 임계 미만 |
| notice_duration | 0.2153 | < 0.20 | 임계 미만 |

### 4.3 Servc missing_lwlt (7일 177 -> 28일 1,309)

| 특징 | 7일 PSI | 28일 PSI | 변화 |
| --- | ---: | ---: | ---: |
| inst_hist_rate | 2.4631 | 0.4136 | -2.0495 |
| inst_ewm_rate | 2.4620 | 0.4039 | -2.0581 |
| inst_sample_cnt | 1.5501 | 0.9145 | -0.6356 |
| clsfc_nm | 0.9537 | < 0.25 | 임계 미만 |
| mid_clsfc_nm | 0.4487 | < 0.25 | 임계 미만 |
| sucsfbid_mthd_nm | 0.2981 | < 0.25 | 임계 미만 |
| log_price | 0.2820 | < 0.25 | 임계 미만 |
| tech_ablt_evl_rt | 0.2748 | < 0.25 | 임계 미만 |
| bid_prce_evl_rt | 0.2739 | < 0.25 | 임계 미만 |

### 4.4 Thng with_lwlt (7일 522 -> 28일 1,987)

| 특징 | 7일 PSI | 28일 PSI | 변화 |
| --- | ---: | ---: | ---: |
| inst_hist_rate | 2.0459 | 0.3851 | -1.6608 |
| sucsfbid_mthd_nm | 0.9649 | < 0.20 | 임계 미만 |
| inst_sample_cnt | 0.8066 | 0.4529 | -0.3537 |
| log_price | 0.6228 | < 0.20 | 임계 미만 |
| repeat_days_since | 0.4576 | 0.3694 | -0.0882 |
| cntrct_mthd_nm | 0.4450 | < 0.20 | 임계 미만 |
| is_over_notice_amt | 0.3442 | < 0.20 | 임계 미만 |
| repeat_prev_rate | 0.2672 | < 0.20 | 임계 미만 |
| repeat_hist_rate | 0.2611 | < 0.20 | 임계 미만 |
| notice_duration | 0.2065 | < 0.20 | 임계 미만 |

### 4.5 Thng missing_lwlt (7일 381 -> 28일 2,375)

| 특징 | 7일 PSI | 28일 PSI | 변화 |
| --- | ---: | ---: | ---: |
| inst_hist_rate | 2.2476 | 0.4113 | -1.8363 |
| inst_sample_cnt | 0.8642 | 0.3651 | -0.4991 |

**요약**: 28일 창에서 임계 위로 남는 것은 사실상 `inst_*` 3종뿐이다. 창 확대는 이들의
PSI 를 2~8배 줄이지만 정족수 2 미만으로 떨어뜨리지는 못한다. 나머지 특징은 소표본
잡음이 걷히며 모두 임계 아래로 내려간다.

---

## 5. 누적 특징의 프레임 의존성 (구조 원인)

`attach_institution_history` 는 전달받은 프레임 안에서 개찰일 순 `shift(1).expanding()` 으로
누적 평균·건수를 만든다(`src/ml/institution_history.py`). 학습·기준선 경로는 프레임 전체를
넘기지만, 감시 경로는 **창 안의 행만** 넘긴다(`src/tasks/scheduled_tasks.py:703-723`).
따라서 같은 특징이 프레임 범위에 따라 다른 값을 갖는다.

Cnstwk with_lwlt 실측:

| 프레임 | 행 수 | inst_sample_cnt 평균 | 최대 |
| --- | ---: | ---: | ---: |
| 기준선 | 30,212 | 24.425 | - |
| W=7 창 | 519 | 1.148 | 13 |
| W=28 창 | 4,426 | 4.998 | 41 |
| W=90 창 | 18,096 | 15.300 | 152 |

창이 길어질수록 값이 기준선 쪽으로 수렴한다(1.15 -> 5.00 -> 15.30). 이 수렴이 4절의
PSI 단조 감소를 그대로 설명한다. 즉 창 확대는 **정의가 다른 두 분포를 더 비슷하게
만들 뿐**이고, 창이 기준선 기간을 덮으면(90일) 자기비교가 되어 PSI 가 사라진다.

`inst_ewm_rate` 도 같은 expanding 프레임에서 나오며, `repeat_*` 도 프레임 안 이력으로
계산된다(`src/ml/repeat_history.py`).

---

## 6. 28일 창 지속성 판정 (필수 항목 4)

각 W 에 대해 최근 창과 **겹치지 않는 직전 창**을 각각 계산해, 직전 창도 창 드리프트였는지
확인하고 `apply_drift_persistence`(required_windows=2)를 적용했다.

| W | 카테고리 | 최근 창 (표본, 비제외) | 직전 창 (표본, 비제외) | 지속성 적용 결과 |
| ---: | --- | :---: | :---: | :---: |
| 7 | Cnstwk | DRIFT_DETECTED (605, 9) | DRIFT_DETECTED (1,354, 5) | DRIFT_DETECTED (알림) |
| 7 | Servc | DRIFT_DETECTED (443, 17) | DRIFT_DETECTED (995, 9) | DRIFT_DETECTED (알림) |
| 7 | Thng | DRIFT_DETECTED (903, 12) | DRIFT_DETECTED (1,276, 9) | DRIFT_DETECTED (알림) |
| 14 | Cnstwk | DRIFT_DETECTED (1,959, 4) | DRIFT_DETECTED (3,088, 4) | DRIFT_DETECTED (알림) |
| 14 | Servc | DRIFT_DETECTED (1,438, 9) | DRIFT_DETECTED (2,188, 7) | DRIFT_DETECTED (알림) |
| 14 | Thng | DRIFT_DETECTED (2,179, 8) | DRIFT_DETECTED (2,183, 5) | DRIFT_DETECTED (알림) |
| 28 | Cnstwk | DRIFT_DETECTED (5,047, 4) | DRIFT_DETECTED (5,990, 4) | DRIFT_DETECTED (알림) |
| 28 | Servc | DRIFT_DETECTED (3,626, 6) | DRIFT_DETECTED (4,728, 6) | DRIFT_DETECTED (알림) |
| 28 | Thng | DRIFT_DETECTED (4,362, 5) | DRIFT_DETECTED (4,873, 5) | DRIFT_DETECTED (알림) |
| 56 | Cnstwk | STABLE (11,037, 2) | STABLE (18,361, 0) | STABLE |
| 56 | Servc | STABLE (8,354, 2) | STABLE (11,362, 0) | STABLE |
| 56 | Thng | STABLE (9,235, 0) | STABLE (9,990, 0) | STABLE |

**판정**: 28일 창에 지속성 규칙을 적용해도 **알림이 나간다.** 최근 28일 창과 직전 28일 창이
모두 창 드리프트이고, 두 창의 비제외 드리프트 개수가 각각 4/4, 6/6, 5/5 로 동일하다. 이는
누적 특징이 두 창 모두에서 같은 방향으로 어긋나기 때문이다(5절). 창 길이를 7·14·28일 중
무엇으로 두어도 지속성은 알림을 억제하지 못한다. 56일 창에서만 두 창 모두 STABLE 이다.

> 주의: 위는 물리적 창을 직접 계산한 결과다. 운영 경로의 `_previous_window_drift` 는
> `retrain_logs` 를 조회한다(`src/tasks/scheduled_tasks.py:732-774`). 규칙 도입 직후에는
> 직전 창 기록이 없어 첫 창은 `DRIFT_PENDING`(보류)으로 남을 수 있다.

---

## 7. 기준선 재생성 필요 여부 (필수 항목 5)

### 7.1 기준선이 만들어지는 방식 (코드 근거)

- `save_baseline_distributions`(`src/ml/monitoring.py:143-218`)는 **전달받은 `df_feat` 의
  히스토그램과 범주 빈도**를 저장한다. 기간을 스스로 정하지 않는다. 저장되는 메타데이터는
  `training_samples`, `created_at`, `model_version` 뿐이고 **데이터 기간은 저장하지 않는다**.
- 호출부는 두 곳이다.
  - `src/ml/trainer.py:552-561` `train_and_register`: `attach_institution_history` ->
    `attach_repeat_history` -> `build_feature_frame` 을 거친 **학습 프레임 전체**로 생성.
  - `scripts/generate_drift_baseline.py:231`: `--start-at`/`--end-at` 로 지정한
    `[start_at, end_at)` 구간(`BidResult.rl_openg_dt` 기준)으로 생성. `--write` + `--start-at`
    필수이며, 구간을 생략하면 전체 이력이 되어 거부된다.
- `evaluation_window_days` 는 PSI 계산에 쓰이지 않는다. `_evaluate_feature_drift_on_frame`
  은 기준선 `bin_edges`/`counts` 와 창 값만으로 PSI 를 낸다(`src/ml/monitoring.py:316-329`).
  즉 W 는 `build_training_dataset` 의 행 선택 구간만 바꾼다.

### 7.2 판단

- **창 길이만 바꾸는 변경에는 기준선 재생성이 불필요하다.** 기존 히스토그램을 그대로
  참조한다. W=7/28/56/90 측정이 모두 같은 기준선 파일로 계산됐고 이 보고서의 수치가 그
  사실을 보여준다.
- **누적 특징 정의를 수선하면 그 시점에는 기준선도 함께 재생성해야 한다.** 기준선도 같은
  expanding 정의로 만들어졌으므로, 정의를 전역 as-of 로 바꾸면 기존 기준선 히스토그램은
  새 정의와 맞지 않게 된다(5절).
- **창 확대에 맞춰 기준선을 최근 구간으로 재생성하는 것은 해법이 아니다.** 창을 기준선
  기간에 겹치게 만들어 드리프트를 가리는 목표 이동이 된다. 90일 창의 PSI 붕괴가 그 예다.
- 현재 기준선 기간은 아티팩트에 명시 저장돼 있지 않다. 버전 라벨(`b_*_post_regime`)과
  `month_sin` 비어 있지 않은 버킷 4개, `is_post_regime_shift` 값 0.0 비율 1.6~8.3% 로 보아
  **2026-05 초 ~ 09-15/26 (약 4.3~4.9개월)** 로 추정한다(추정).

---

## 8. 창 길이 권고안 비교 (필수 항목 6)

제안 A~F 의 "예상 알림"은 `now = 2026-09-28 03:06:02` 실측 기준이다. 지속성 규칙 때문에
알림 확정에는 최소 2W 가 걸린다(겹치지 않는 창 2개가 모두 드리프트여야 함).

| 안 | 내용 | 예상 알림 | 최소 탐지 지연 | 비고 |
| --- | --- | :---: | ---: | --- |
| A | 현행 7일 창 유지 | 알림 (세 카테고리) | 14일 | 오탐 지속 |
| B | 단일 28일 창 | 알림 (세 카테고리) | 56일 | 창 확대만으로는 해소 안 됨 (6절) |
| C | 28일 창 + `inst_*` 제외 | **알림 없음** (세 카테고리 STABLE) | 56일 | 현재 창이 STABLE 이므로 지속성 무관 |
| D | 28일 창 + `inst_*` 전역 as-of 수선 | 알림 없음 (추정) | 56일 | 정본 특징 변경이라 별도 승인 필요 |
| E | 단일 56일 창 | 알림 없음 | 112일 | 창이 기준선 기간과 겹침, 지연 과다 |
| F | 단일 90일 창 | 알림 없음 | 180일 | 기준선과 대량 겹침(자기비교), 부적절 |

### 8.1 안 C 근거 (28일 창 + 누적 특징 제외)

28일 창에서 제외 집합을 `기존 5종 + {inst_hist_rate, inst_sample_cnt, inst_ewm_rate}` 로
넓혀 계산한 결과다.

| 카테고리 | 비제외 개수 | 판정 | 집단별 (with / missing) |
| --- | ---: | :---: | --- |
| Cnstwk | 0 | STABLE | STABLE 0 / STABLE 0 |
| Servc | 0 | STABLE | STABLE 0 / STABLE 0 |
| Thng | 1 | STABLE | below_quorum 1 (repeat_days_since 0.3694) / STABLE 0 |

같은 제외 집합을 7일 창에 적용하면 여전히 알림이 난다(공사 with 7, 용역 with 5·missing 6,
물품 with 8). 7일 창은 범주·금액 특징이 소표본으로 흔들리기 때문이다. 따라서 **창 확대와
누적 특징 처리를 함께 해야** 알림이 멈춘다. 정족수는 집단별로 적용되므로 위 개수는 집단
판정 기준이다.

### 8.2 안 B·E 의 함정

- B: 창을 28일로 넓히면 개수는 4/6/5 로 줄지만 정족수 2 이상이 유지되고, 직전 28일 창도
  드리프트라 지속성도 통과한다. 알림이 계속 난다.
- E·F: 창이 기준선 기간(추정 2026-05 초 ~ 09-15/26)과 겹치면 기준선과 같은 구간을 비교하는
  자기비교가 되어 PSI 가 인위적으로 낮아진다. 90일 창에서 PSI 가 0 에 수렴하는 것이 그
  증거다. 안전 판정 근거로 쓸 수 없다. 또한 지연이 112~180일로 실효성이 없다.

### 8.3 권고

1. **단기(오탐 즉시 차단)**: 28일 창 + `inst_*` 3종 판정 제외(안 C). 실측으로 세 카테고리
   모두 STABLE 이며, 별도 학습·기준선 변경 없이 판정 코드만으로 가능하다.
2. **근본**: `inst_*` 를 프레임 독립(전역 as-of) 정의로 수선하고(안 D) 기준선을 함께
   재생성한다. 창은 28일 단일 창을 유지한다.
3. **다중 창(7/28/90)은 현재 형태로는 권하지 않는다.** 7일 창이 `inst_*` 를 빼고도
   드리프트하므로 "어느 창이든 지속 시 알림"은 오탐을 줄이지 못한다. 다중 창을 쓰려면
   최단 창을 28일 이상으로 두거나, 최단 창을 보조 신호로만 쓰고 승격 판정에서는 제외한다.
4. **지속성 조건은 유지**한다. 다만 현재 누적 특징 때문에 28일 창에서는 지속성만으로
   걸러지지 않으므로, 정족수·지속성은 누적 특징 수선과 함께 재검토한다.

---

## 9. 코디네이터 예비 수치와의 차이 (확인 필요)

Capsule 이 인용한 코디네이터 예비 측정과 본 보고서 수치가 일부 다르다.

| 항목 | 코디네이터 예비 | 본 보고서 | 차이 |
| --- | ---: | ---: | --- |
| 7일 창 Servc 비제외(두 집단 합) | 16 | 17 | +1 |
| 28일 창 Servc 표본 | 3,456 | 3,626 | +170 |
| 7일 창 Cnstwk / Thng 비제외 | 9 / 12 | 9 / 12 | 일치 |

차이 원인은 두 가지로 본다.

1. **DB 수집 지연·백필**: 평가 창 행 집합은 측정 시각의 DB 내용에 좌우된다. 본 측정은
   2026-09-29 10:47 KST 기준이다.
2. **경계선 특징**: Servc 7일 창에서 `log_price`(0.2440), `notice_duration`(0.2153)이
   임계 0.20 바로 위에 있어 1건 차이로 개수가 뒤집힐 수 있다.

본 보고서의 재현 명령(부록 A)이 `now` 를 고정하므로, 동일 시점 DB에서는 본 수치가
재현된다. 코디네이터 예비 수치는 확정치가 아니다.

---

## 10. 한계

- 기준선 기간이 아티팩트에 저장돼 있지 않아 7.2절 기간은 추정이다.
- DB 는 수집 지연으로 이후 변할 수 있어 최근 창(7·14일) 수치는 재현 시점에 따라 소폭
  달라질 수 있다. 56·90일 창은 안정적이다.
- 90일 창은 기준선 기간과 겹치는 자기비교 편향이 있다(8.2절). STABLE 을 정상 판정으로
  해석하면 안 된다.
- 지속성은 물리적 창을 직접 계산했다. 운영 경로는 `retrain_logs` 를 조회하므로 첫 실행은
  `DRIFT_PENDING` 일 수 있다(6절 주의).
- 정족수는 집단별로 적용되고 전체 `drift_feature_count` 는 두 집단 합이라, 합계만 보면
  상태를 오해할 수 있다(부록 B).
- 안 C·D 의 제외/수선은 본 Task 에서 실행하지 않았다. 후속 승인 대상이다.

---

## 부록 A. 재현 히어독

워크트리 루트에서 아래를 한 번 실행하면 3~6절 수치가 재계산된다.

```sh
uv run python - <<'EOF'
from datetime import datetime, timedelta
from pathlib import Path
from src.app.core.db import SessionLocal
from src.ml.dataset import build_training_dataset
from src.ml.institution_history import attach_institution_history
from src.ml.repeat_history import attach_repeat_history
from src.ml.features import build_feature_frame, collect_category_levels, apply_categorical_dtypes
from src.ml.monitoring import load_baseline_distributions, check_dataset_drift
from src.ml.drift_verdict import DRIFT_VERDICT_EXCLUDED_FEATURES, apply_drift_persistence
from src.tasks import scheduled_tasks as st
from src.ml.training_config import CATEGORY_MODEL_NAMES
import pandas as pd

NOW = datetime(2026, 9, 28, 3, 6, 2)

def frame(cat, start, end):
    db = SessionLocal()
    try:
        df = build_training_dataset(db, cat, start_at=start, end_at=end, persist=False)
    finally:
        db.close()
    if df.empty:
        return df
    df = attach_institution_history(df)
    df = attach_repeat_history(df)
    d = pd.DataFrame(build_feature_frame(df.to_dict(orient="records")))
    return apply_categorical_dtypes(d, collect_category_levels(d))

for W in (7, 14, 28, 56, 90):
    for cat in sorted(CATEGORY_MODEL_NAMES):
        base = load_baseline_distributions(Path("ml_registry") / CATEGORY_MODEL_NAMES[cat] / "baseline")
        v = st._compute_drift_assessment_thread(cat, NOW - timedelta(days=W), NOW, base, W)
        print(f"W={W} {cat} samples={v['recent_samples']} status={v['status']} non_excl={v['drift_feature_count']} excl={len(v['excluded_drift_features'])}")
        for k, s in v["by_subgroup"].items():
            ne = ",".join(f"{f['feature']}:{f['psi']}" for f in s.get("drift_features", []))
            print(f"  {k} n={s.get('recent_samples')} {s.get('status')} NE={s.get('drift_feature_count')} [{ne}] EX={len(s.get('excluded_drift_features', []))}")

# 지속성: 최근 창 + 겹치지 않는 직전 창
for W in (7, 14, 28, 56):
    for cat in sorted(CATEGORY_MODEL_NAMES):
        base = load_baseline_distributions(Path("ml_registry") / CATEGORY_MODEL_NAMES[cat] / "baseline")
        cur = st._compute_drift_assessment_thread(cat, NOW - timedelta(days=W), NOW, base, W)
        prv = st._compute_drift_assessment_thread(cat, NOW - timedelta(days=2 * W), NOW - timedelta(days=W), base, W)
        final = apply_drift_persistence(cur, prv["status"] == "DRIFT_DETECTED")
        print(f"W={W} {cat} cur={cur['status']}({cur['drift_feature_count']}) prev={prv['status']}({prv['drift_feature_count']}) -> {final['status']}")

# 누적 특징 프레임 의존성 (Cnstwk with_lwlt)
base = load_baseline_distributions(Path("ml_registry") / CATEGORY_MODEL_NAMES["Cnstwk"] / "baseline")
print("baseline inst_sample_cnt mean =", base["by_lwlt_missing"]["0.0"]["features"]["inst_sample_cnt"]["mean"])
for W in (7, 28, 90):
    d = frame("Cnstwk", NOW - timedelta(days=W), NOW)
    s0 = d[d["lwlt_rate_missing"] == 0.0]
    print(f"W={W} rows={len(d)} with_lwlt n={len(s0)} inst_sample_cnt mean={s0['inst_sample_cnt'].mean():.3f} max={s0['inst_sample_cnt'].max()}")

# 안 C: 28일 창 + 누적 특징 제외
EXT = set(DRIFT_VERDICT_EXCLUDED_FEATURES) | {"inst_hist_rate", "inst_sample_cnt", "inst_ewm_rate"}
for W in (7, 28):
    for cat in sorted(CATEGORY_MODEL_NAMES):
        base = load_baseline_distributions(Path("ml_registry") / CATEGORY_MODEL_NAMES[cat] / "baseline")
        d = frame(cat, NOW - timedelta(days=W), NOW)
        v = check_dataset_drift(base, d, evaluation_window_days=W, excluded_features=EXT)
        print(f"EXT W={W} {cat} {v['status']} non_excl={v['drift_feature_count']}")
EOF
```

---

## 부록 B. 정족수는 집단별 적용

`check_dataset_drift` 는 집단별 `_evaluate_feature_drift_on_frame` 결과의 상태를 OR 하고
(`src/ml/monitoring.py:494-531`), 전체 `drift_feature_count` 는 두 집단 합으로 낸다. 그래서
56일 창 공사(`inst_sample_cnt` with 0.6016, missing 0.6243)는 합 2 이지만 각 집단이 1 로
정족수 미달이라 `STABLE` 이다. "합계 2 이상"으로 상태를 추정하면 오판한다.
