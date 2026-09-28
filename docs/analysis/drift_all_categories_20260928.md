# PSI 드리프트 감시 전 카테고리 DRIFT_DETECTED 원인 판정 (2026-09-28)

> **작성일**: 2026-09-28
> **Task ID**: task_889ad6055f75
> **Run ID**: run_0f28089a96b2
> **브랜치**: kwanbum217/orca-w12
> **대상**: retrain_logs id 18, 19, 20 (trigger_source='drift_monitor', 2026-09-28 03:06)
> **판정**: 감시 방법의 **구조적 오탐**이 지배적이다. 실제 입력 분포 변화의 증거는 없다.
> **범위**: 코드·설정·DB·모델·기준선을 변경하지 않는다. 본 문서는 분석 결과만 기록한다.

---

## 1. 요약과 판정

2026-09-28 03:06 드리프트 감시가 용역·공사·물품 세 카테고리 모두 `DRIFT_DETECTED`
(`overall_action=TRIGGER_RETRAIN`)로 판정했다. 원인을 재현한 결과 판정은 다음 세 구조적
요인으로 전부 설명되며, 재학습을 정당화하는 지속적 입력 분포 변화는 확인되지 않았다.

1. **달력 특징 4종(`month_sin`, `month_cos`, `weekday_sin`, `weekday_cos`)의 결정적 오탐.**
   평가 창이 7일이라 개찰일이 전부 9월 한 달에 몰리고, 그 주가 추석 연휴와 겹쳐
   월·화·수에만 개찰이 집중됐다. 달력 특징 4종의 관측 PSI(월 5.5~11.2, 요일 3.2~3.8)는
   기준선 히스토그램과 "창의 모든 행이 9월"이라는 사실만으로 **소수점 넷째 자리까지
   해석적으로 재현**된다(4절).
2. **단계 특징 `is_post_regime_shift` 오탐.** 기준선에 레짐 전환(2026-05-26) 이전 행이
   4.6~8.3% 남아 있어, 전부 레짐 이후인 창은 정확히 같은 방식으로 오탐된다(관측치 5건
   전부 해석적으로 재현).
3. **누적·확장 통계 특징(`inst_*`, `repeat_*`)의 시간 편향.** 순수 표본 잡음만으로는
   임계(0.2/0.25)를 넘길 수 없음(6절)을 확인했다. 관측된 잔여 드리프트는 창 시점(9월 말)의
   누적 이력 값이 기준선 기간(약 4개월) 평균과 체계적으로 다른 데서 온다.

달력 특징만 제거해도 판정은 뒤집히지 않는다(7절). 즉 원인은 "달력 특징 하나"가 아니라
**감시 창 설계(7일) · 기준선 구성 · 누적 특징 정의**의 상호작용이며, 현시점 재학습은
불필요하다(8절).

---

## 2. 분석 대상과 재현 정보

### 2.1 카테고리·모델·기준선 매핑

`src/ml/training_config.py:68-72` 의 `CATEGORY_MODEL_NAMES` 를 따른다.

| 카테고리 | 모델 | baseline_version | 기준선 생성 | 기준선 표본(하위집단) |
| --- | --- | --- | --- | --- |
| Cnstwk(공사) | cnstwk_institution_v1 | b_20260926_cnstwk_post_regime | 2026-09-26T06:41:19 | 33,627 (30,212 / 3,415) |
| Servc(용역) | servc_institution_v1 | b_20260926b_servc_post_regime | 2026-09-26T14:14:30 | 22,295 (14,020 / 8,275) |
| Thng(물품) | quantum_leap_v25_pro | b_20260915_thng_post_regime | 2026-09-15T06:19:44 | 18,069 (9,758 / 8,311) |

- 기준선 파일: `ml_registry/<model>/baseline/metadata.json`,
  `ml_registry/<model>/baseline/feature_distributions_v1.json`
- 하위집단 키: `0.0`=with_lwlt(낙찰하한율 있음), `1.0`=missing_lwlt(낙찰하한율 결측)

### 2.2 감시 경로와 임계

- 태스크: `src/tasks/scheduled_tasks.py:750-946` `drift_monitor_task` /
  `_run_drift_monitor` (매일 04:00, 평가 창 기본 7일, `persist=False`).
- 판정 함수: `src/ml/monitoring.py` `check_dataset_drift` /
  `_evaluate_feature_drift_on_frame`.
- 임계: with_lwlt 0.2, missing_lwlt 0.25 (`src/ml/monitoring.py:53-54`,
  기준선 `psi_config.subgroup_thresholds`). `min_samples_per_feature=100`.
- 평가 창: `[now - evaluation_window_days, now)` 반열림 구간(개찰일 기준),
  `now = 2026-09-28 03:06`. 즉 약 `[2026-09-21, 2026-09-28)`.
- 특징 생성 정본: `src/ml/features.py` `build_feature_frame` → `build_default_feature_map`.
  달력 특징은 기준 시각 `reference_ts` 에서 파생된다.
- **`reference_ts` 우선순위는 `openg_dt`(개찰일시) → `bid_clse_dt` → `bid_ntce_dt`**
  (`src/ml/features.py:176-181`). 따라서 7일 창에서는 달력 특징이 창 길이에 종속된다.

### 2.3 사용한 질의 (전문)

```sql
-- Q1. 세 카테고리 드리프트 판정 원본
SELECT id, trigger_source, champion_version, challenger_version, status, created_at, metrics_summary
FROM retrain_logs WHERE id IN (18,19,20) ORDER BY id;

-- Q2. 개찰일 컬럼 보유 테이블 확인
SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
WHERE COLUMN_NAME IN ('openg_dt','bid_clse_dt','bid_ntce_dt') ORDER BY TABLE_NAME;

-- Q3. 평가 창의 개찰일·요일 분포 (공고 원본 기준)
SELECT DATE(openg_dt) d, WEEKDAY(openg_dt) wd, COUNT(*) c
FROM bid_announcements
WHERE openg_dt >= '2026-09-21 03:06:02' AND openg_dt < '2026-09-28 03:06:02'
GROUP BY d, wd ORDER BY d;

-- Q4. 2026-09 월 전체 개찰일·요일 분포 (연휴 공백 대조)
SELECT DATE(openg_dt) d, WEEKDAY(openg_dt) wd, COUNT(*) c
FROM bid_announcements
WHERE openg_dt >= '2026-09-01' AND openg_dt < '2026-09-29'
GROUP BY d, wd ORDER BY d;
```

`retrain_logs.metrics_summary` 는 JSON 이므로 Q1 은 `--format json` 으로 받아 파싱했다.

---

## 3. 세 카테고리 드리프트 특징 전체 목록 (필수 항목 1)

### 3.1 판정 요약

| id | 카테고리 | 모델 | status | overall_action | 최근 표본 | 드리프트 수 | 하위집단 유형 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 18 | Cnstwk | cnstwk_institution_v1 | DRIFT_DETECTED | TRIGGER_RETRAIN | 479 | 15 | with_lwlt_only |
| 19 | Servc | servc_institution_v1 | DRIFT_DETECTED | TRIGGER_RETRAIN | 336 | 31 | both |
| 20 | Thng | quantum_leap_v25_pro | DRIFT_DETECTED | TRIGGER_RETRAIN | 805 | 22 | both |

하위집단별 판정 (Q1):

| id | 하위집단 | 표본 | 임계 | 드리프트 수 | 상태 |
| --- | --- | --- | --- | --- | --- |
| 18 | with_lwlt (0.0) | 401 | 0.20 | 15 | DRIFT_DETECTED |
| 18 | missing_lwlt (1.0) | 78 | 0.25 | 0 | INSUFFICIENT_DATA (표본 < 100) |
| 19 | with_lwlt (0.0) | 181 | 0.20 | 16 | DRIFT_DETECTED |
| 19 | missing_lwlt (1.0) | 155 | 0.25 | 15 | DRIFT_DETECTED |
| 20 | with_lwlt (0.0) | 456 | 0.20 | 15 | DRIFT_DETECTED |
| 20 | missing_lwlt (1.0) | 349 | 0.25 | 7 | DRIFT_DETECTED |

### 3.2 Cnstwk (id 18) — with_lwlt, 표본 401, 임계 0.20

| 특징 | PSI | 특징 | PSI |
| --- | --- | --- | --- |
| month_cos | 8.7442 | inst_sample_cnt | 2.8322 |
| month_sin | 6.2477 | cntrct_mthd_nm | 0.5553 |
| weekday_cos | 3.6020 | is_post_regime_shift | 0.5069 |
| weekday_sin | 3.3083 | notice_duration | 0.4272 |
| inst_hist_rate | 2.5961 | log_price | 0.3415 |
| sucsfbid_mthd_nm | 0.8677 | repeat_hist_rate | 0.3311 |
| repeat_prev_rate | 0.2834 | is_repeat | 0.2608 |
| is_over_notice_amt | 0.2383 | | |

### 3.3 Servc (id 19) — with_lwlt, 표본 181, 임계 0.20

| 특징 | PSI | 특징 | PSI |
| --- | --- | --- | --- |
| month_cos | 8.4930 | clsfc_nm | 0.9426 |
| month_sin | 5.4900 | log_price | 0.6266 |
| weekday_cos | 3.4703 | is_post_regime_shift | 0.5159 |
| weekday_sin | 3.1976 | cntrct_mthd_nm | 0.4643 |
| inst_ewm_rate | 3.2990 | is_over_notice_amt | 0.3712 |
| inst_sample_cnt | 2.0071 | notice_duration | 0.3141 |
| inst_hist_rate | 1.3432 | mid_clsfc_nm | 0.3040 |
| sucsfbid_mthd_nm | 1.1989 | lwlt_rate | 0.2200 |

### 3.4 Servc (id 19) — missing_lwlt, 표본 155, 임계 0.25

| 특징 | PSI | 특징 | PSI |
| --- | --- | --- | --- |
| month_cos | 8.4999 | inst_sample_cnt | 1.5501 |
| month_sin | 5.7726 | clsfc_nm | 1.0891 |
| weekday_cos | 3.4926 | mid_clsfc_nm | 0.5301 |
| weekday_sin | 3.2201 | is_post_regime_shift | 0.3557 |
| inst_hist_rate | 2.4554 | sucsfbid_mthd_nm | 0.3255 |
| inst_ewm_rate | 2.4541 | tech_ablt_evl_rt | 0.2981 |
| notice_duration | 0.3110 | bid_prce_evl_rt | 0.2972 |
| log_price | 0.3084 | | |

### 3.5 Thng (id 20) — with_lwlt, 표본 456, 임계 0.20

| 특징 | PSI | 특징 | PSI |
| --- | --- | --- | --- |
| month_cos | 11.1743 | cntrct_mthd_nm | 0.6657 |
| month_sin | 6.4088 | is_post_regime_shift | 0.5661 |
| weekday_cos | 3.7984 | repeat_days_since | 0.4576 |
| weekday_sin | 3.5151 | repeat_prev_rate | 0.2560 |
| inst_hist_rate | 2.0403 | repeat_hist_rate | 0.2505 |
| sucsfbid_mthd_nm | 1.4329 | notice_duration | 0.2180 |
| log_price | 0.8474 | is_over_notice_amt | 0.7103 |
| inst_sample_cnt | 0.8066 | | |

### 3.6 Thng (id 20) — missing_lwlt, 표본 349, 임계 0.25

| 특징 | PSI |
| --- | --- |
| month_cos | 10.1805 |
| month_sin | 5.7959 |
| weekday_cos | 3.8131 |
| weekday_sin | 3.5234 |
| inst_hist_rate | 2.2457 |
| inst_sample_cnt | 0.8642 |
| is_post_regime_shift | 0.2859 |

---

## 4. 특징 분류와 류별 드리프트 개수 (필수 항목 2)

### 4.1 분류 기준

| 류 | 특징 |
| --- | --- |
| 달력류 (날짜 파생) | month_sin, month_cos, weekday_sin, weekday_cos |
| 금액·규모류 | log_price, notice_amt_ratio, is_over_notice_amt, tot_prdprc_num, drwt_prdprc_num, notice_duration |
| 기관·이력류 | inst_hist_rate, inst_sample_cnt, inst_ewm_rate, is_repeat, repeat_cnt, repeat_hist_rate, repeat_prev_rate, repeat_hist_std, repeat_days_since |
| 기타 (제도·범주·레짐) | is_post_regime_shift, lwlt_rate, lwlt_rate_missing, tech_ablt_evl_rt, bid_prce_evl_rt, srvce_div_nm, lrg_clsfc_nm, cntrct_mthd_nm, prearng_mthd, sucsfbid_mthd_nm, mid_clsfc_nm, clsfc_nm, ntce_kind_nm, bid_methd_nm, intrbid_yn, ppsw_gnrl_srvce_yn |

`notice_duration` 은 개찰(또는 마감)과 공고일의 차이로 날짜에서 파생되지만 주기 부호화가
아니라 기간 길이라 금액·규모류로 분류했다. 본 특징 집합에는 `day_*` 계열이 없다.
`inst_ewm_rate` 는 Servc 전용 추가 특징이다(`src/ml/training_config.py:190`).

### 4.2 류별 드리프트 개수 (드리프트 특징만 계수)

| 카테고리 (하위집단, 표본) | 달력 | 금액·규모 | 기관·이력 | 기타 | 합계 |
| --- | --- | --- | --- | --- | --- |
| Cnstwk with_lwlt (401) | 4 | 3 | 5 | 3 | 15 |
| Servc with_lwlt (181) | 4 | 3 | 3 | 6 | 16 |
| Servc missing_lwlt (155) | 4 | 2 | 3 | 6 | 15 |
| Thng with_lwlt (456) | 4 | 3 | 5 | 3 | 15 |
| Thng missing_lwlt (349) | 4 | 0 | 2 | 1 | 7 |
| **합계** | **20** | **11** | **18** | **19** | **68** |

달력류는 **표본 수와 무관하게 5개 하위집단 모두에서 4종 전부 드리프트로 잡혔다.**
이는 창 길이에 대한 결정적(deterministic) 반응이다.

---

## 5. 기준선 대 평가 창 대조와 달력 특징 구조적 PSI 논증 (필수 항목 3)

### 5.1 기간·표본 대조

| 항목 | 기준선 | 평가 창 | 비율 |
| --- | --- | --- | --- |
| 기간 | 2026-05-26(레짐 전환) ~ 2026-09-15/26 | 2026-09-21 ~ 2026-09-28 | 약 120일 : 7일 (약 17:1) |
| 포함 월 | 5, 6, 7, 8, 9월 | 9월 단일 | - |
| 하위집단 표본 | 3,415 ~ 30,212 | 78 ~ 456 | 약 66:1 ~ 100:1 |

- 기준선 기간은 명시 저장값이 없다. `month_sin`/`month_cos` 히스토그램의 비어 있지 않은
  버킷이 5~9월에만 존재하고 `is_post_regime_shift` 평균이 0.930~0.934 인 것으로 보아
  **레짐 전환(2026-05-26) 이후 ~ 기준선 생성일(2026-09-15/26) 사이**로 추정한다.
  (근거: `src/ml/features.py:32` `REGIME_SHIFT_DATE = 2026-05-26`.)
- 평가 창은 `reference_ts=openg_dt` 필터 구간과 정확히 일치한다.

### 5.2 창의 달력 값이 단일값으로 붕괴한다

7일 창 `[2026-09-21, 2026-09-28)` 안의 개찰일은 Q3 결과 전부 9월이다.

| 개찰일 | 요일 | 건수 |
| --- | --- | --- |
| 2026-09-21 | 월 | 1,777 |
| 2026-09-22 | 화 | 2,413 |
| 2026-09-23 | 수 | 1,732 |
| 2026-09-24 | 목 | 9 |
| 2026-09-25 | 금 | 10 |
| 2026-09-27 | 일 | 1 |
| 2026-09-28 | 월 | 1 |

- 모든 행이 `month=9` 이므로
  `month_sin = sin(2π·9/12) = -1.0` (기준선 첫 버킷),
  `month_cos = cos(2π·9/12) ≈ -1.8e-16` (기준선 마지막 버킷) 로 **상수**가 된다.
- 요일도 월·화·수에 5,922/5,943 = **99.6%** 가 몰린다. Q4 로 보면 9월 평일 개찰은
  정상(1,200~2,400건)이나 **9/24(목)~9/27(일)은 추석 연휴·주말로 개찰이 사실상 없다.**
  기준선(5~9월 약 4개월)은 월~금에 고르게 분포하므로, 단일 연휴 주간의 요일 구성은
  구조적으로 기준선과 다르다.

### 5.3 해석적 재현 — 관측 PSI가 정확히 재현된다

기준선 하위집단 히스토그램의 `counts`/`bin_edges` 와 "창의 모든 행이 단일 버킷"이라는
사실만으로 PSI 를 계산하면(monitoring.py 의 수치 PSI 식, `1e-4` 스무딩) 관측치와
**정확히 일치**한다.

| 카테고리 (하위집단) | month_sin 관측 / 해석 | month_cos 관측 / 해석 | is_post_regime_shift 관측 / 해석 |
| --- | --- | --- | --- |
| Cnstwk with_lwlt | 6.2477 / 6.2477 | 8.7442 / 8.7442 | 0.5069 / 0.5069 |
| Servc with_lwlt | 5.4900 / 5.4900 | 8.4930 / 8.4930 | 0.5159 / 0.5159 |
| Servc missing_lwlt | 5.7726 / 5.7726 | 8.4999 / 8.4999 | 0.3557 / 0.3557 |
| Thng with_lwlt | 6.4088 / 6.4088 | 11.1743 / 11.1743 | 0.5661 / 0.5661 |
| Thng missing_lwlt | 5.7959 / 5.7959 | 10.1805 / 10.1805 | 0.2859 / 0.2859 |

`is_post_regime_shift` 도 같은 방식으로 재현된다. 이 특징은 창에서 전부 1.0 인데,
기준선에는 레짐 전환 이전(값 0.0) 행이 with_lwlt 4.6~8.3% 남아 있다. 예로 Cnstwk
with_lwlt 기준선은 0.0 이 2,286/30,212 = 7.6% 이고, "창의 값이 전부 1.0" 으로 계산한
PSI 0.5069 가 관측치와 일치한다.

**의미**: 달력 특징과 `is_post_regime_shift` 의 드리프트는 모집단이 변했다는 신호가
아니라, **창 구성(단일 월 · 연휴 주간)과 기준선 구성(다개월 · 레짐 이전 혼입)의 차이를
PSI 가 그대로 반영**한 것이다. 이 두 묶음만 합쳐도 5개 하위집단에서 각각 5개 특징이
드리프트로 잡혔다.

### 5.4 요일 특징도 같은 구조

Q3 의 창 요일 구성을 기준선 버킷에 투영하면(전 카테고리 공고 기준 대리값):

| 카테고리 (하위집단) | weekday_sin 관측 / DB구성 재현 | weekday_cos 관측 / DB구성 재현 |
| --- | --- | --- |
| Cnstwk with_lwlt | 3.3083 / 2.1687 | 3.6020 / 2.1683 |
| Servc with_lwlt | 3.1976 / 2.0885 | 3.4703 / 2.0880 |
| Servc missing_lwlt | 3.2201 / 2.0779 | 3.4926 / 2.0756 |
| Thng with_lwlt | 3.5151 / 2.2052 | 3.7984 / 2.2047 |
| Thng missing_lwlt | 3.5234 / 2.2618 | 3.8131 / 2.2612 |

카테고리별 요일 구성 차이 때문에 값이 관측치보다 작지만, **자릿수와 방향이 일치**한다.
즉 요일 드리프트도 연휴 주간이라는 일시적 창 구성에서 온다.

---

## 6. 표본 181~456건에서 PSI 추정의 불안정성 (필수 항목 4)

방법: 각 기준선 하위집단 히스토그램을 참 확률분포로 보고, 평가 창과 같은 표본 수를
다항분포로 3,000회 재표집하여 PSI 분포(귀무분포)를 만들었다. 평가 데이터가 기준선과
**통계적으로 동일**하다면 PSI 가 임계를 넘을 확률을 본다.

| 특징 (하위집단, 표본) | 귀무 p50 | 귀무 p95 | 귀무 p99 | P(PSI ≥ 임계) |
| --- | --- | --- | --- | --- |
| inst_hist_rate (Cnstwk with_lwlt, 401) | 0.017 | 0.039 | 0.059 | 0.000 |
| inst_hist_rate (Servc with_lwlt, 181) | 0.061 | 0.105 | 0.127 | 0.002 |
| inst_ewm_rate (Servc with_lwlt, 181) | 0.063 | 0.118 | 0.147 | 0.004 |
| log_price (Thng with_lwlt, 456) | 0.017 | 0.037 | 0.055 | 0.000 |
| month_sin / month_cos (전 하위집단) | ≤ 0.016 | ≤ 0.052 | ≤ 0.075 | 0.000 |

**결론**: 이 표본 규모에서 순수 표본 잡음만으로 임계(0.2/0.25)를 넘을 확률은
0.0~0.4% 로 매우 낮다. 따라서 관측된 비달력 특징 PSI(0.2~2.8)는 표본 잡음이 아니라
**창과 기준선 사이의 실제 차이**를 반영한다. "표본이 작아 PSI 가 과대 추정됐다"는
가설은 이 특징 집합·표본 규모에서는 **지지되지 않는다.**

단, 빈 버킷·양자화 민감도는 별개로 존재한다. 예로 Cnstwk with_lwlt 의
`inst_hist_rate` 는 기준선의 65%(19,594/30,212)가 버킷 폭 0.0108 한 칸에 몰린
스파이크 분포다. 버킷 폭이 특징 표준편차(0.009~0.011)와 비슷해, 10버킷 PSI 는
한 칸 규모의 이동만으로도 2~3 까지 치솟는다. 이는 잡음이 아니라 **측정 해상도의
증폭 효과**이며, 뒤의 권고(8절)에 반영한다.

---

## 7. 달력류를 제외했을 때 남는 드리프트 (필수 항목 5)

### 7.1 단계별 잔존 개수

| 카테고리 (하위집단) | 전체 | 달력 제외 | + is_post_regime_shift 제외 | + inst_* 제외 |
| --- | --- | --- | --- | --- |
| Cnstwk with_lwlt | 15 | 11 | 10 | 8 |
| Servc with_lwlt | 16 | 12 | 11 | 8 |
| Servc missing_lwlt | 15 | 11 | 10 | 7 |
| Thng with_lwlt | 15 | 11 | 10 | 8 |
| Thng missing_lwlt | 7 | 3 | 2 | 0 |

- **달력류만 빼도 모든 하위집단이 여전히 TRIGGER_RETRAIN 이다.** 달력 제외로는 오탐이
  해소되지 않는다.
- Thng missing_lwlt 는 달력 4 + `is_post_regime_shift` + `inst_hist_rate` +
  `inst_sample_cnt` 로 **전부 설명**된다. 이 하위집단의 드리프트는 구조적 요인만으로 남김없이
  재구성된다.

### 7.2 남는 특징의 성격 판단

| 잔존 그룹 | 예시 | 판단 |
| --- | --- | --- |
| 누적·확장 통계 | inst_hist_rate(1.3~2.6), inst_sample_cnt(0.8~2.8), inst_ewm_rate(2.5~3.3), repeat_hist_rate, repeat_prev_rate, repeat_days_since | **구조적 시간 편향(추정).** 이 특징들은 "기준 시점 이전" 누적 이력으로 산출되므로, 9월 말 창의 값은 기준선 기간 평균과 체계적으로 다르다. 특히 `inst_sample_cnt` 는 시간에 따라 단조 증가한다. 실제 모집단 변화가 아니라 특징 정의와 단주간 창의 상호작용이다. |
| 금액·규모 | log_price(0.3~0.85), notice_duration(0.2~0.4), is_over_notice_amt(0.2~0.7) | **단주간 구성 차이.** 연휴 주간의 소수 개찰에 금액대·기간이 치우쳤을 가능성. PSI 0.2~0.85 는 경계선이며 지속성 근거가 없다. |
| 범주(제도) | cntrct_mthd_nm(0.46~0.67), sucsfbid_mthd_nm(0.33~1.43), clsfc_nm(0.94~1.09), mid_clsfc_nm(0.30~0.53) | **소표본 희소 범주 효과.** 표본 155~456 에서 범주 조합이 조금만 달라져도 범주 PSI 가 커진다. |
| 레짐 | is_post_regime_shift(0.29~0.57) | **기준선 구성 결함.** 5.3절에서 정확 재현. 판정에서 제외하거나 기준선에서 레짐 이전 행을 제거해야 한다. |

요약하면, 달력·레짐·누적 특징을 걷어낸 뒤 남는 것은 **경계선 수준의 단주간 구성 차이**뿐이며,
이를 지속적 입력 분포 변화로 볼 근거는 없다.

---

## 8. 권고 (필수 항목 6)

우선순위 순으로 정리한다. 어느 항목도 본 Task 에서 실행하지 않았으며, 후속 Task 에서
합의 후 진행할 것을 제안한다.

1. **달력 특징 제외 또는 창-정합 처리.** `month_sin/cos`, `weekday_sin/cos` 는 기준선과
   창의 시간 범위가 다르면 항상 오탐한다(5.3절 정확 재현). 판정 대상에서 제외하거나,
   기준선을 창과 동일한 월/요일 조건으로 재투영한 뒤 비교한다.
2. **`is_post_regime_shift` 처리.** 기준선에서 레짐 전환 이전 행을 제거해 재구성하거나
   판정에서 제외한다. 현 기준선은 "post_regime" 라벨과 달리 0.0 값이 4.6~8.3% 남아 있다.
   재학습이 아니라 **기준선 구성**의 문제다.
3. **누적·확장 통계 특징의 시간 정렬.** `inst_*`, `repeat_*` 는 창 시점과 기준선 기간의
   누적 깊이가 달라 구조적으로 어긋난다. 동일 관측 시점 정렬, 값 표준화, 또는 판정 제외를
   검토한다.
4. **평가 창 확대·다중 창.** 7일 단일 창은 연휴(추석)·수집 지연에 취약하다. 28일 이상으로
   넓히거나 7/28/90일 다중 창 중 하나라도 지속될 때만 트리거한다. 단주간 창은 폐기하거나
   보조 신호로 강등한다.
5. **지속성·quorum 조건.** 연속 N일 드리프트, 또는 비달력 특징이 특정 개수 이상일 때만
   `TRIGGER_RETRAIN` 으로 승격한다. 단일 창의 1개 특징 초과로는 트리거하지 않는다.
6. **최소 표본 조건·해상도 조정.** 현재 `min_samples_per_feature=100`. 순수 잡음은
   임계를 넘지 않으므로(6절) 표본 상향의 우선순위는 낮지만, 스파이크형 특징에는 10버킷
   PSI 대신 표본 수에 맞춘 버킷 수(예: 도수 기반 분위 버킷)나 KS 등 보정 지표를 검토한다.
7. **수집 지연 점검.** 창 말단(9/26~9/28)은 결과 미수집으로 표본이 잘릴 수 있다. 창 경계
   우측 절단을 감시 로직에서 보정하거나 최소 지연 버퍼를 둔다.
8. **재학습 필요 여부: 불필요.** 현 증거로는 세 카테고리 모두 재학습을 정당화하는 지속적
   입력 분포 변화가 없다. 드리프트 로그의 `TRIGGER_RETRAIN` 은 수동 재학습 지시로
   해석하지 말고, 위 구조적 요인을 먼저 제거한 뒤 재판정한다.

---

## 9. 한계

- `src/ml/psi.py` 는 본 Task 허용 범위 밖이라 열람하지 않았다. 범주형 PSI 공식은
  재현하지 못했고, 범주형 드리프트는 관측치와 정성 판단만 제시했다.
- 평가 창의 특징값은 어디에도 영속되지 않아, 창의 특징 분포를 직접 재구성하지는 못했다.
  달력·레짐 특징은 기준선 버킷과 창 날짜 구성만으로 해석적 재현이 가능해 정확히 검증했다.
- 요일 재현(5.4절)은 공고 원본(`bid_announcements`) 전 카테고리 요일 구성을 대리값으로
  사용했다. 카테고리별 요일 구성은 다를 수 있어 값은 관측치보다 작게 나온다.
- 추석 연휴와 결과 수집 지연의 기여를 분리하지 못했다. 두 요인 모두 창 구성을 왜곡하며,
  8절 7항의 점검이 필요하다.
- DB 수치는 Q1~Q4 로 재확인 가능하다. 기준선 수치는 위 2.1절 파일 경로에서 재확인 가능하다.
