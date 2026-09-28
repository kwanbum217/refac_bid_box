# 나중 차수 취소공고와 원 차수 공고 행의 매칭률 분모 잔존 규모·영향 판정 (2026-09-28)

> **작성일**: 2026-09-28
> **상태**: 분석 완료 (코드·설정·DB·스키마 변경 없음)
> **범위**: 같은 공고번호·분류에서 더 큰 정규화 차수가 `취소공고`인데 원 차수 공고 행(등록공고 등)이 매칭률 분모에 남는 현상의 최근 12주 규모, 분모 제외 시 매칭률 영향, 표본 대조, 분모 제외 규칙 권고, 공고번호 단위 보조 지표(`notice_*`)와의 관계
> **계보**: `docs/analysis/servc_g2b_manual_checklist_20260928.md` 2.2절 대조표 3번(R26BK01659726, 000 등록공고 / 001 취소공고)에서 발견
> **정본 모듈**: `src/app/services/result_coverage.py` (`compute_result_match_rates`, `normalize_ord`, `_notice_band_counts`, `CANCELLED_NTCE_KIND`, `LARGE_PRICE_THRESHOLD`)
> **질의 방법**: `uv run python scripts/db_readonly_query.py --sql "<질의>"` (읽기 전용, SELECT 단일 문장)
> **계약 준수**: 조달청 API 직접 조회 없음. 운영 DB 쓰기 없음. `docker exec`·`mysql` 직접 호출 없음. `git add -A` 미사용. 산출물은 본 문서 1건.

---

## 1. 요약 (결론)

1. **규모는 작지 않다.** 최근 12주(개찰 2026-06-08 ~ 2026-08-30) 전 분류에서 "분모에 들어간 비취소 공고 행 중, 같은 공고번호·분류의 더 큰 정규화 차수에 취소공고 행이 있는" 행은 **6,457행(고유 공고번호 5,951개)** 이다. 이는 같은 창의 전체 분모 99,414행의 **6.5%** 다.

2. **이 행들은 거의 전부 미매칭이고, 그것이 정상이다.** 6,457행 중 미매칭이 **6,441행(99.75%)**, 매칭은 16행(0.25%)이다. 사업 자체가 취소됐다면 낙찰결과가 없는 것이 정상이므로, 이들은 수집 누락이 아니라 **분모 과대 계수**다.

3. **분모에서 빼면 매칭률이 분류·규모별로 +3.34%p ~ +8.39%p 오른다.** 대형만 보면 공사 +8.39%p, 물품 +4.61%p, 용역 +4.40%p 다. 왜곡이 경고 판정에 쓰이는 대형 행에서 더 크다.

4. **경고 방향은 "낙폭 확대"다. 대칭 적용이 필수다.** 2026-08-24 주 단일 주에서 용역 대형 낙폭은 9.32%p → **11.09%p**(10%p 임계 신규 초과), 물품 대형은 11.52%p → **12.92%p** 로 확대된다. 전년 동기 기저 주에도 같은 취소 잔존 행이 비슷하게 있어(용역 44, 물품 31) 기저가 더 크게 오르기 때문이다. 현재 주에만 적용하면 낙폭이 오히려 축소(용역 4.83%p, 물품 7.59%p)되어 실제 하락 경고를 가릴 수 있다.

5. **`notice_*` 보조 지표는 이 문제를 해소하지 못한다.** `compute_result_match_rates` 는 조회 단계에서 `ntce_kind_nm = '취소공고'` 행을 이미 제외하므로, 공고번호 단위 대표 행(최대 차수)은 취소공고가 아니라 남아 있는 원 차수 행(등록공고 등)이다. 그 결과 `notice_*` 아래에도 같은 미매칭 행이 그대로 남는다(12주 기준 대형: 공사 651, 용역 592, 물품 427). 차수 불일치(변경공고) 문제와는 원인이 다르고, 중첩도 없다(4.5절).

6. **권고: 채택한다.** 단 (a) 정본 매칭에서 **미매칭인 행만** 제외해 매칭 16행을 건드리지 않고, (b) **현재 주와 전년 기저에 동시 적용**하며, (c) 정본 필드는 유지하고 **별도 분모 기준/플래그**로 병행 산출한다.

---

## 2. 조사 방법과 계약 범위

### 2.1 대상 행의 정의

이 보고서가 다루는 행을 `취소 잔존 행` 이라 부른다.

| 구분 | 정의 |
| --- | --- |
| 대상 공고 행 a | `category IN ('Servc','Cnstwk','Thng')`, `openg_dt` 가 개찰 창 [2026-06-08, 2026-08-30] 안, `bid_ntce_dt` 가 [2025-06-08, 2026-08-30] 안(정본 조회 블록의 공고일 하한 골격), `ntce_kind_nm` 이 `취소공고` 가 아님(NULL 포함) |
| 취소 잔존 조건 | 같은 `(bid_ntce_no, category)` 에 `normalize_ord(c.bid_ntce_ord) > normalize_ord(a.bid_ntce_ord)` 인 `ntce_kind_nm = '취소공고'` 행 c 가 존재 |
| 미매칭 | `(bid_ntce_no, category, normalize_ord(a.bid_ntce_ord))` 가 `bid_results` 에 없음 (정본 매칭 정의) |
| 규모 | `presmpt_prce >= 230000000` 이면 대형, 그 밖(NULL 포함)은 소형 |

차수 정규화 SQL 표현은 `normalize_ord` 와 동일한 아래 식이다(이하 `NORM(x)` 로 표기).

```
RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(x)), ''), '0')), 3)
```

### 2.2 계약 범위

| 항목 | 내용 |
| --- | --- |
| 허용 명령 | `uv run python scripts/db_readonly_query.py --sql "<질의>"` (SELECT 단일 문장), git 조회 |
| 미허용 | 조달청 API 직접 조회, 운영 DB 쓰기, 그 외 스크립트 실행 |
| 매칭 판정 정본 | `src/app/services/result_coverage.py` — (bid_ntce_no, category, 정규화 차수) 존재 여부 |
| 분모에서 제외되는 정본 조건 | `ntce_kind_nm` 이 `NULL` 이거나 `취소공고` 가 아닌 행 (같은 파일 `compute_result_match_rates`) |
| 대형 임계 | `presmpt_prce >= 230000000` |
| 경고 규칙 | `baseline_multi_rate - adjusted_rate >= 0.10`, 표본 `>= 100`, 2주 연속 (본 보고서는 재계산하지 않음) |
| 공고종류 분포 | 최근 12주 창에서 `등록공고` 82,541 / `재공고` 11,125 / `취소공고` 5,917 / `변경공고` 5,748 (NULL 값 없음). `취소공고` 문자열이 취소를 나타내는 유일한 값임을 확인 (질의 Q9) |

---

## 3. 규모: 최근 12주 (필수 항목 1)

### 3.1 분류 × 규모별 취소 잔존 행

기간: 개찰 2026-06-08 ~ 2026-08-30. 조건은 2.1절 정의와 동일하다. 질의 Q1.

| 분류 | 규모 | 분모(공고 행) | 매칭 | 현행 매칭률 | 취소 잔존 행 | 그중 미매칭 | 그중 매칭 | 분모 대비 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cnstwk | 대형 | 7,158 | 5,413 | 75.62% | 715 | 715 | 0 | 9.99% |
| Cnstwk | 소형 | 22,804 | 19,187 | 84.14% | 1,340 | 1,335 | 5 | 5.88% |
| Servc | 대형 | 7,484 | 3,553 | 47.47% | 637 | 636 | 1 | 8.51% |
| Servc | 소형 | 31,589 | 18,018 | 57.04% | 1,826 | 1,824 | 2 | 5.78% |
| Thng | 대형 | 6,042 | 3,445 | 57.02% | 454 | 453 | 1 | 7.51% |
| Thng | 소형 | 24,337 | 12,633 | 51.91% | 1,485 | 1,478 | 7 | 6.10% |
| 합계 | | 99,414 | 62,249 | 62.62% | 6,457 | 6,441 | 16 | 6.50% |

### 3.2 분류별 공고번호 수

같은 공고번호에서 원 차수 행과 중간 차수 행이 함께 취소 잔존 행이 될 수 있어(3.3절) 공고번호 수는 행 수보다 작다. 질의 Q2.

| 분류 | 취소 잔존 행 | 고유 공고번호 | 행/번호 비 |
| --- | ---: | ---: | ---: |
| Cnstwk | 2,055 | 1,842 | 1.12 |
| Servc | 2,463 | 2,298 | 1.07 |
| Thng | 1,939 | 1,811 | 1.07 |
| 합계 | 6,457 | 5,951 | 1.09 |

### 3.3 차수 조합 분포

취소는 차수 `001` 뿐 아니라 `002`~`007` 에도 있고, 한 공고번호 안에서 여러 원 차수 행이 같은 취소 행을 공유한다(예: `000`·`001` 비취소 + `002` 취소 → 두 행 모두 취소 잔존). 질의 Q3.

| 분류 | 원 차수 | 최대 취소 차수 | 행 수 |
| --- | --- | --- | ---: |
| Cnstwk | 000 | 001 / 002 / 003 / 004 / 005 / 007 | 1,687 / 110 / 31 / 4 / 6 / 1 |
| Cnstwk | 001~006 | (그보다 큰) 002~007 | 216 |
| Servc | 000 | 001 / 002 / 003 / 004 / 005 | 2,147 / 124 / 16 / 3 / 1 |
| Servc | 001~004 | (그보다 큰) 002~005 | 172 |
| Thng | 000 | 001 / 002 / 003 / 004 / 005 | 1,698 / 93 / 13 / 3 / 2 |
| Thng | 001~003 | (그보다 큰) 002~005 | 130 |

대다수는 `000`(등록공고) + `001`(취소공고) 형태이고, 취소가 최대 차수인 경우가 우세하다. 3장 표의 합계 6,457행은 위 조합 행 수의 총합과 같다.

---

## 4. 분모 제외 시 매칭률 영향 (필수 항목 2)

### 4.1 최근 12주

취소 잔존 행을 분모에서 빼면, 그 행이 매칭이었으면 분자에서도 함께 뺀다. 즉 `(매칭 − 그중 매칭) / (분모 − 취소 잔존 행)`. 질의 Q1 의 값에서 산출한다.

| 분류 | 규모 | 현행 매칭률 | 제외 후 매칭률 | 변화 |
| --- | --- | ---: | ---: | ---: |
| Cnstwk | 대형 | 75.62% | 84.01% | **+8.39%p** |
| Cnstwk | 소형 | 84.14% | 89.37% | +5.23%p |
| Servc | 대형 | 47.47% | 51.88% | +4.40%p |
| Servc | 소형 | 57.04% | 60.53% | +3.49%p |
| Thng | 대형 | 57.02% | 61.63% | +4.61%p |
| Thng | 소형 | 51.91% | 55.25% | +3.34%p |
| 합계 | | 62.62% | 66.95% | +4.33%p |

대형에서 변화가 소형보다 크고(공사 +8.39%p, 물품 +4.61%p, 용역 +4.40%p), 경고 판정이 대형 행에서만 나온다는 점에서 이 왜곡은 경고 규칙과 직접 맞닿아 있다.

### 4.2 2026-08-24 주 단일 주와 전년 동기 단일 주

경고 규칙(5주 기저·방식 보정·2주 연속)은 재계산하지 않는다. 대신 단일 주 실측률과 364일 전 같은 단일 주(2025-08-25 ~ 2025-08-31)를 취소 잔존 행 제외 전후로 비교해 방향만 본다. 질의 Q5(현재 주), Q6(전년 주).

| 분류·규모 | 구분 | 분모 | 매칭 | 현행률 | 취소 잔존(미매칭) | 제외 후률 | 변화 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Servc 대형 | 2026-08-24 주 | 468 | 188 | 40.17% | 47 (47) | 44.66% | +4.48%p |
| Servc 대형 | 2025-08-25 주(전년) | 392 | 194 | 49.49% | 44 (44) | 55.75% | +6.26%p |
| Thng 대형 | 2026-08-24 주 | 454 | 243 | 53.52% | 31 (31) | 57.45% | +3.93%p |
| Thng 대형 | 2025-08-25 주(전년) | 409 | 266 | 65.04% | 31 (31) | 70.37% | +5.33%p |
| Cnstwk 대형 | 2026-08-24 주 | 407 | 293 | 71.99% | 42 (42) | 80.27% | +8.28%p |
| Cnstwk 대형 | 2025-08-25 주(전년) | 503 | 373 | 74.16% | 57 (57) | 83.63% | +9.47%p |

### 4.3 방향 판정

| 분류·규모 | 현행 낙폭(기저−실측) | 양쪽 적용 낙폭 | 비대칭(현재만) 낙폭 | 방향 |
| --- | ---: | ---: | ---: | --- |
| Servc 대형 | 9.32%p | **11.09%p** | 4.83%p | 양쪽 적용 시 확대(10%p 임계 신규 초과), 현재만 적용 시 축소 |
| Thng 대형 | 11.52%p | **12.92%p** | 7.59%p | 양쪽 적용 시 확대, 현재만 적용 시 축소 |
| Cnstwk 대형 | 2.17%p | 3.36%p | −6.11%p | 양쪽 적용 시 확대, 현재만 적용 시 부호 반전 |

**해석**: 취소 잔존 행은 현재 주와 전년 기저에 비슷한 비율로 존재한다. 그래서 양쪽에 같은 규칙을 적용하면 기저가 더 크게 올라 낙폭이 **확대**된다(용역은 10%p 임계를 새로 넘고, 물품은 더 벌어진다). 반대로 현재 주에만 적용하면 기저는 그대로 두고 실측만 올라 낙폭이 **축소**된다. 따라서 이 규칙은 "경고를 줄이는" 보정이 아니며, **대칭 적용을 강제하지 않으면 오히려 오탐/미탐 방향이 뒤집힌다.**

---

## 5. 표본 5건 대조 (필수 항목 3)

추정가격 상위와 대조표 발견 건을 섞어 5건을 골랐다. 모두 `bid_results` 에 결과 행이 0건(미매칭)인 취소 잔존 행이다. 질의 Q7.

| # | 공고번호 | 분류 | 차수 | 공고종류 | 개찰일 | 결과 존재 | 비고 |
| --: | --- | --- | --- | --- | --- | --- | --- |
| 1 | R26BK01278853 | Cnstwk | 000 | 등록공고 | 2026-06-26 | 없음 | 001 취소공고(개찰일 동일). 추정가격 3,257억 |
| 2 | R26BK01317903 | Cnstwk | 000 | 등록공고 | 2026-07-08 | 없음 | 001 취소공고(개찰일 동일). 추정가격 1,732억 |
| 3 | R25BK01219840 | Cnstwk | 000 | 등록공고 | 2026-06-16 | 없음 | 001 취소공고(개찰일 동일). 추정가격 1,481억 |
| 4 | R26BK01664551 | Servc | 000 | 재공고 | 2026-08-20 | 없음 | 001 취소공고(개찰일 동일). 추정가격 924억 |
| 5 | R26BK01659726 | Servc | 000 | 등록공고 | 2026-08-06 | 없음 | 001 취소공고(개찰일 동일). 대조표 3번 발견 건. 추정가격 189억 |

`공고종류` 는 `bid_announcements.ntce_kind_nm`, `결과 존재` 는 같은 공고번호·분류의 `bid_results` 행 수다. 5건 모두 결과가 0건이라 원 차수 행이 정본 매칭에서 미매칭으로 계수된다.

---

## 6. `notice_*` 공고번호 단위 보조 지표와의 관계 (필수 항목 5)

`notice_*` 는 같은 `(bid_ntce_no, category)` 의 여러 차수 공고 행 중 정규화 차수가 가장 큰 행 하나만 세는 보조 지표다(`_notice_band_counts`). 그러나 조회 단계에서 `취소공고` 행을 이미 제외하므로, 대표 행은 취소공고가 아니라 남아 있는 원 차수 행이 된다. 따라서 **취소 잔존 행은 `notice_*` 에서도 그대로 계수된다.** 질의 Q8.

| 분류 | 규모 | 정본 분모 | 정본 매칭 | 정본률 | notice 분모 | notice 매칭 | notice률 | notice 아래 취소 잔존 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cnstwk | 대형 | 7,158 | 5,413 | 75.62% | 6,620 | 5,413 | 81.77% | 651 |
| Cnstwk | 소형 | 22,804 | 19,187 | 84.14% | 21,577 | 19,187 | 88.92% | 1,191 |
| Servc | 대형 | 7,484 | 3,553 | 47.47% | 6,849 | 3,553 | 51.88% | 592 |
| Servc | 소형 | 31,589 | 18,018 | 57.04% | 29,968 | 18,018 | 60.12% | 1,706 |
| Thng | 대형 | 6,042 | 3,445 | 57.02% | 5,736 | 3,445 | 60.06% | 427 |
| Thng | 소형 | 24,337 | 12,633 | 51.91% | 23,100 | 12,633 | 54.69% | 1,384 |

**관계 정리**

1. `notice_*` 는 분모를 줄이지만(공고번호 단위 중복 제거), 취소 잔존 행은 줄이지 못한다. 대표 행이 취소공고가 아니기 때문이다. 예를 들어 물품 대형은 정본 6,042 → notice 5,736 으로 306행 줄지만, 그중 427행이 여전히 "더 큰 차수에 취소공고가 있는" 행이다.
2. 두 문제는 **원인이 다르고 중첩이 없다.** 차수 불일치(`ord_mismatch`, 변경공고로 옛 차수 행 잔존)는 취소 잔존 행에서 관측되지 않았다. 취소 잔존 행 중 "임의 차수의 결과가 있는" 행(4.5절, `ct_matched_any`)은 16행으로, 전부 같은 차수에서 매칭된 행이다. 즉 두 집합은 서로소다.
3. 따라서 "사업 단위 분모"를 만들려면 **변경공고 차수 흡수/중복 제거(`notice_*`)** 와 **취소 잔존 제외**가 모두 필요하다. 한쪽만으로는 다른 쪽 왜곡이 남는다.

### 6.1 (참고) 차수 불일치와의 중첩 규모

질의 Q4. 취소 잔존 행 중 결과가 임의 차수에라도 있는 행(`ct_matched_any`)은 12주 전 분류에서 16행(공사 5, 용역 3, 물품 8)이며, 이는 3.1절의 "그중 매칭" 16행과 정확히 일치한다. 결과가 다른 차수에 있는 중첩(차수 불일치)은 0행이다.

---

## 7. 권고와 오탐 위험 (필수 항목 4)

### 7.1 판정

**분모 제외 규칙은 필요하다. 채택을 권고한다.**

| 근거 | 내용 |
| --- | --- |
| 왜곡이 구조적이고 크다 | 12주 6,457행(전체 분모의 6.5%)이 구조적으로 결과가 없는 사업이다. 미매칭률 99.75% |
| 경고 판정과 직접 맞닿음 | 경고는 대형 행에서만 나오는데, 대형의 왜곡이 더 크다(공사 +8.39%p, 물품 +4.61%p, 용역 +4.40%p) |
| 정상 미매칭의 정의 문제 | `servc_g2b_manual_checklist_20260928.md` 4절이 "유찰·취소는 정상 미등록이므로 분모 정의를 재검토"로 지목한 항목의 실체다 |
| 다른 지표로 해소 불가 | `notice_*` 는 이 행을 제거하지 못한다(6절) |

### 7.2 채택 시 필수 조건

| 번호 | 조건 | 근거 |
| --- | --- | --- |
| C1 | 정본 매칭에서 **미매칭인 행만** 분모에서 제외한다. 매칭된 취소 잔존 행(12주 16행)은 건드리지 않는다 | 3.1절 "그중 매칭" 16행. 이 게이트를 두면 분자를 줄이지 않아 매칭 건을 잃지 않는다 |
| C2 | 현재 성숙 주와 전년 기저 창에 **동시에** 같은 규칙을 적용한다 | 4.3절. 현재 주에만 적용하면 낙폭이 축소(용역 9.32→4.83%p)되어 경고를 가린다 |
| C3 | 정본 필드(`announcements`, `matched`, `rate`)의 정의는 유지하고, **별도 분모 기준/플래그**(예: `excl_cancelled`)로 병행 산출한다. 경고 판정(`baseline_multi_rate`, `adjusted_rate`, 2주 연속)은 별도 승인 전까지 바꾸지 않는다 | 경고 임계 통과 여부가 달라지므로(4.3절 용역 신규 초과) 변경은 별도 검증이 필요하다 |
| C4 | 취소 조건은 `normalize_ord(취소 차수) > normalize_ord(원 차수)` 로 한정한다. 차수 역행·동일 차수는 제외 대상이 아니다 | 3.3절. 취소는 항상 더 큰 차수에 있다 |

### 7.3 오탐 위험

| 위험 | 내용 | 규모·근거 | 완화 |
| --- | --- | --- | --- |
| 매칭 행 오제외 | 원 차수에서 낙찰되고 나중 차수가 취소된 경우, 원 차수 행을 분모·분자에서 빼면 매칭이 사라진다 | 12주 16행(0.25%). 전부 `000 등록공고 + 001 취소공고` 이면서 같은 차수 결과 보유 | C1(미매칭 행만 제외)로 차단 |
| 문자열 값 변형 | 다른 표기의 취소 값(`취소`, `취소공고(재공고)` 등)을 놓치면 제외가 덜 된다 | 12주 창 공고종류는 등록공고·재공고·취소공고·변경공고 4종뿐이고 NULL 없음(2.2절 질의 Q9) | 현재는 문자열 단일 값이라 위험 낮음. 신규 값 유입 시 상류 확인 필요 |
| 유찰·재공고와의 혼동 | 유찰 후 재공고가 새 공고번호로 나가면 취소 잔존이 아니다. 원 번호에 취소 행이 있는 경우만 제외하므로 이 경우는 애초에 대상이 아니다 | 2.1절 정의 | 정의상 대상 아님 |
| 중복 계수 미해소 | 원 차수 행과 중간 변경공고 행이 둘 다 취소 잔존이면 두 행이 함께 빠진다. 이는 왜곡 축소가 아니라 사업 단위 정합에 가깝다 | 3.2절 행/번호 비 1.09 | `notice_*` 와 병행 시 사업 단위 1건으로 수렴 |
| 경고 임계 방향 반전 | 대칭 적용 시 낙폭이 확대되어 경고가 늘어난다(용역 08-24 주 신규 초과). 억제·억제 해제 목록과 상호작용을 재확인해야 한다 | 4.3절 | C3. 별도 승인·전후 검증 |

---

## 8. 불확실성과 한계

1. **단일 주 창의 근사.** 4.2절은 개찰 창을 `[2026-06-08, 2026-08-30]` 로 균일하게 잡은 재현용 근사다. 정본은 성숙 주 블록과 전년 5주 기저 블록을 따로 조회하므로, 블록 경계에서 행이 ±1주 다를 수 있다. 다만 3장·4.1절의 방향과 자릿수는 창을 조금 바꿔도 유지된다.
2. **차수 정규화의 파이썬 측 동작.** 정본은 차수 비교를 파이썬에서 한다. 본 보고서는 같은 규칙을 SQL 식으로 옮겼고, 두 표현이 `normalize_ord` 와 동일함은 선행 문서(`ord_mismatch_20260928.md` 9절)에서 확인됐다.
3. **취소 사유 미구분.** `취소공고` 한 값만 보므로, 부분 취소·정정 취소·재입찰 준비 취소를 구분하지 못한다. 결과가 없는 취소는 모두 제외 대상으로 본다.
4. **성숙도.** 최근 주(2026-08-17·24)는 결과 도착이 진행 중일 수 있다. 취소 잔존은 수집 지연이 아니라 구조 문제이므로 방향에는 영향이 작다.
5. **표본.** 5장 표본은 추정가격 상위와 대조표 발견 건을 섞은 5건이며 무작위 표본이 아니다. 규모 수치는 전수 집계(3장)를 근거로 한다.

---

## 9. 재현 명령

모든 수치는 아래 형태로 재현한다. `NORM(x)` 는 2.1절의 차수 정규화 식이다.

```
uv run python scripts/db_readonly_query.py --sql "<질의>" --format json
```

**Q1. 분류 × 규모별 취소 잔존 행 (3.1·4.1절)**
```
SELECT a.category, CASE WHEN a.presmpt_prce >= 230000000 THEN 'large' ELSE 'small' END AS band, COUNT(*) AS ann, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no=a.bid_ntce_no AND br.category=a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)=RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS matched, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS ct_rows, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) AND NOT EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no=a.bid_ntce_no AND br.category=a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)=RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS ct_unmatched, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) AND EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no=a.bid_ntce_no AND br.category=a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)=RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS ct_matched FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') GROUP BY a.category, band ORDER BY a.category, band
```

**Q2. 취소 잔존 행·고유 공고번호 (3.2절)**
```
SELECT a.category, COUNT(*) AS ct_rows, COUNT(DISTINCT a.bid_ntce_no) AS ct_notices FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) GROUP BY a.category
```

**Q3. 원 차수 × 최대 취소 차수 분포 (3.3절)**
```
SELECT a.category, a.bid_ntce_ord AS a_ord, (SELECT MAX(RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3)) FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고') AS max_cancel_ord, COUNT(*) AS rows_cnt, COUNT(DISTINCT a.bid_ntce_no) AS notices FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) GROUP BY a.category, a_ord, max_cancel_ord ORDER BY a.category, a_ord, max_cancel_ord
```

**Q4. 임의 차수 결과 보유(차수 불일치 중첩) (6.1절)**
```
SELECT a.category, CASE WHEN a.presmpt_prce >= 230000000 THEN 'large' ELSE 'small' END AS band, COUNT(*) AS ct_rows, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no=a.bid_ntce_no AND br.category=a.category) THEN 1 ELSE 0 END) AS ct_matched_any FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) GROUP BY a.category, band ORDER BY a.category, band
```

**Q5. 2026-08-24 주 집계 (4.2절 현재 주)**: Q1 골격에서 `openg_dt >= '2026-08-24 00:00:00' AND openg_dt <= '2026-08-30 23:59:59.999999'` 로 좁히고 `bid_ntce_dt >= '2025-08-25 00:00:00'` 로 바꾼다.

**Q6. 2025-08-25 전년 동기 단일 주 집계 (4.2절 기저 주)**: Q1 골격에서 `openg_dt >= '2025-08-25 00:00:00' AND openg_dt <= '2025-08-31 23:59:59.999999'`, `bid_ntce_dt >= '2024-08-26 00:00:00' AND bid_ntce_dt <= '2025-08-31 23:59:59.999999'` 로 바꾼다.

**Q7. 표본·상세 대조 (5장)**
```
SELECT a.bid_ntce_no, a.category, a.bid_ntce_ord AS a_ord, a.ntce_kind_nm AS a_kind, DATE(a.openg_dt) AS openg, a.presmpt_prce, a.bid_ntce_nm, (SELECT GROUP_CONCAT(CONCAT(c.bid_ntce_ord,':',COALESCE(c.ntce_kind_nm,'(null)'),'@',DATE(c.openg_dt)) ORDER BY c.bid_ntce_ord SEPARATOR ' | ') FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category) AS all_ords, (SELECT COUNT(*) FROM bid_results br WHERE br.bid_ntce_no=a.bid_ntce_no AND br.category=a.category) AS res_rows FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=a.bid_ntce_no AND c.category=a.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)) ORDER BY a.presmpt_prce DESC
```

**Q8. `notice_*` 와 취소 잔존 관계 (6절)**
```
SELECT t.category, t.band, COUNT(*) AS notice_ann, SUM(t.matched) AS notice_matched, SUM(t.ct) AS notice_ct FROM (SELECT x.bid_ntce_no, x.category, CASE WHEN x.presmpt_prce >= 230000000 THEN 'large' ELSE 'small' END AS band, CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no=x.bid_ntce_no AND br.category=x.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)=x.nord) THEN 1 ELSE 0 END AS matched, CASE WHEN EXISTS (SELECT 1 FROM bid_announcements c WHERE c.bid_ntce_no=x.bid_ntce_no AND c.category=x.category AND c.ntce_kind_nm='취소공고' AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(c.bid_ntce_ord)), ''), '0')), 3) > x.nord) THEN 1 ELSE 0 END AS ct FROM (SELECT a.bid_ntce_no, a.category, a.presmpt_prce, RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) AS nord, ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no, a.category ORDER BY RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) DESC) AS rn FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고')) x WHERE x.rn=1) t GROUP BY t.category, t.band ORDER BY t.category, t.band
```

**Q9. 공고종류 값 분포 (2.2절)**
```
SELECT COALESCE(a.ntce_kind_nm,'(null)') AS kind, COUNT(*) AS n FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' GROUP BY kind ORDER BY n DESC
```

---

## 10. 참고 문서

- `docs/analysis/servc_g2b_manual_checklist_20260928.md`: 본 조사의 발단. 2.2절 대조표 3번(R26BK01659726, 000 등록공고 / 001 취소공고), 4절 "유찰·취소는 분모 정의 재검토" 항목.
- `docs/analysis/ord_mismatch_20260928.md`: 차수 불일치(변경공고) 미매칭 규모와 흡수 위험. `notice_*` 보조 지표 도입 근거(9절 차수 정규화 SQL 표현).
- `docs/analysis/thng_match_rate_20260824.md`: 물품 2026-08-24 주 경고 원인(W1). 5주 기저·방식 보정·2주 연속 규칙의 배경.
- `docs/analysis/servc_upstream_recheck_20260928.md`: 용역 대형 상류 공백 25건 표본과 API 부재 판정.
- `docs/analysis/result_collection_gap_20260926.md`: 낙찰결과 수집 공백 C1 분석. 대형 결과 지연 R3.
- `docs/context/CURRENT_STATE.md`: 수집 파이프라인 운영 정본.
- `src/app/services/result_coverage.py`: 매칭률·경고 계산 정본. `normalize_ord`, `CANCELLED_NTCE_KIND`, `LARGE_PRICE_THRESHOLD`, `_notice_band_counts`.
- `src/app/models/bids.py`: `BidAnnouncement`(ntce_kind_nm, bid_ntce_ord), `BidResult` 스키마.
- `scripts/db_readonly_query.py`: 읽기 전용 재현 도구.
