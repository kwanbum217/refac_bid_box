# 물품 2026-08-24 주 차수 불일치 미매칭 원인 판정과 전 분류 규모 (2026-09-28)

> **작성일**: 2026-09-28
> **상태**: 분석 완료 (코드·설정·DB 변경 없음)
> **범위**: 물품(Thng) 2026-08-24 주 대형 미매칭 8건(공고번호 7개)의 차수 불일치 원인 판정, 전 분류·최근 12주 규모와 매칭률 영향, 조인 규칙 흡수안 위험 평가
> **계보**: W1 보고서 `docs/analysis/thng_match_rate_20260824.md` 5.4절·10절 Q9 의 후속 조사
> **정본 모듈**: `src/app/services/result_coverage.py` (`normalize_ord`, `LARGE_PRICE_THRESHOLD`, `RATE_DROP_ALERT`, `BASELINE_OFFSET_DAYS`)
> **질의 방법**: `uv run python scripts/db_readonly_query.py --sql "<질의>"` (읽기 전용, SELECT 단일 문장)
> **계약 준수**: 조달청 API 직접 조회 없음. 운영 DB 쓰기 없음. `docker exec`·`mysql` 직접 호출 없음. 산출물은 본 문서 1건.

---

## 1. 요약 (결론)

1. **8건은 수집 누락이 아니다.** 차수 불일치 8건(공고번호 7개)의 공고 테이블에는 결과 차수(001/002)에 대응하는 공고 행이 이미 존재한다. 7개 번호 전부에서 확인했고, 최근 12주 전 분류 차수 불일치 3,525행 전체에서도 **3,525/3,525(100%)** 가 결과 차수와 같은 차수의 공고 행을 가진다. 미수집분은 없다.

2. **원인은 변경공고(정정공고)로 인한 차수 분기와 정본 조인의 차수 완전 일치 요구다.** 8건의 원 공고 차수 `000` 행은 모두 `등록공고`이고, 결과 차수 `001`/`002` 대응 공고 행은 모두 `변경공고`다. 변경공고가 발행되면 공고 테이블에는 옛 차수 행과 새 차수 행이 함께 남고, 낙찰결과는 최신 차수에만 등록된다. 정본 매칭은 (bid_ntce_no, category, 정규화 차수) 완전 일치이므로 옛 차수 행은 조인 상대가 없어 미매칭으로 계수된다.

3. **규모는 작지 않다.** 최근 12주(2026-06-08 ~ 2026-08-24) 전 분류에서 차수 불일치 미매칭은 **3,525행(고유 공고번호 2,913)** 이다. 매칭률 영향은 분류·규모별로 **+2.63%p ~ +5.69%p** 이며, 대형만 보면 공사 +5.69%p, 용역 +4.69%p, 물품 +2.63%p 다.

4. **흡수안은 경고 임계를 새로 넘나든다.** 조인 규칙으로 차수를 흡수하면 현재와 기저 양쪽 매칭률이 함께 올라 방향이 일정하지 않다. 2026-08-24 주에 흡수하면 물품 대형 낙폭은 11.52%p → 13.41%p 로 확대되고, 용역 대형은 9.32%p → 11.82%p 로 10%p 임계를 새로 넘는다(경고 신규 발화). "차수 흡수가 경고 오탐을 줄인다"는 가정은 성립하지 않는다.

5. **권고**: 정본 매칭 정의는 유지하고, 차수 흡수는 별도 보조 지표로만 둔다. 분모 왜곡(한 사업의 복수 공고 행)을 고치려면 흡수보다 **공고번호 단위 중복 제거**가 먼저다. 흡수안을 쓰더라도 `결과 차수 > 공고 차수` 조건으로 한정해야 한다.

---

## 2. 조사 방법과 계약 범위

| 항목 | 내용 |
| --- | --- |
| 허용 명령 | `scripts/db_readonly_query.py` (SELECT, SHOW, EXPLAIN, DESC, WITH 단일 문장), git 조회 |
| 미허용 | 조달청 API 직접 조회, 운영 DB 쓰기, 그 외 스크립트 실행 |
| 매칭 판정 정본 | `src/app/services/result_coverage.py` — 매칭은 (bid_ntce_no, category, `normalize_ord`(차수)) 존재 여부. `normalize_ord` 는 앞뒤 공백 제거, 선행 0 제거, 3자리 왼쪽 0 채움(`src/app/services/result_coverage.py:42`) |
| 대형 임계 | `presmpt_prce >= 230000000` (`src/app/services/result_coverage.py:27`) |
| 경고 규칙 | `baseline_rate - rate >= 0.10`, 표본 `>= 100` (`src/app/services/result_coverage.py:28`, `:29`) |
| 기저 오프셋 | 364일 (`src/app/services/result_coverage.py:36`) |
| 대조 기준 | W1 보고서 `docs/analysis/thng_match_rate_20260824.md` 4.1절 표·5.4절·10절 Q9 |
| 성숙 주 정의 | `as_of - 28일` 이 속한 주의 직전 주부터 12주. `as_of=2026-09-28` 이면 최신 성숙 주 = 2026-08-24, 12주 시작 = 2026-06-08 |

차수 불일치 미매칭의 정의는 다음과 같다. 공고 행이 정본 조인(차수 완전 일치)에서 **미매칭**이면서, 같은 `bid_ntce_no`·`category` 의 낙찰결과가 **다른 차수로 존재**하는 경우다. 즉 "결과가 어딘가에는 있는데 차수가 안 맞아 조인되지 않은" 행이다. 이후 이 값을 `차수 불일치` 또는 `불일치` 라 부른다.

---

## 3. 8건 상세 대조 (필수 항목 1)

W1 보고서 10절 Q9 가 찾은 8건을 그대로 재현했다. 미매칭 8행의 주체는 공고번호 7개이며, `R26BK01684354` 만 미매칭 행이 2개(차수 `000`·`001`)다.

### 3.1 미매칭 8건: 공고 행과 결과 행 대조

| # | 공고번호 | 공고차수 | 공고종류 | bid_ntce_dt | openg_dt | presmpt_prce | bid_methd_nm | 결과차수 | 결과 rl_openg_dt | 낙찰자 | 낙찰금액 | 낙찰률 |
| --: | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: |
| 1 | R26BK01629556 | 000 | 등록공고 | 2026-07-13 | 2026-08-24 | 470,000,000 | 전자입찰 | 001 | 2026-08-24 | (주)삼성피앤씨 | 517,000,000 | - |
| 2 | R26BK01636318 | 000 | 등록공고 | 2026-07-16 | 2026-08-26 | 952,494,545 | 전자입찰 | 001 | 2026-08-31 | 주식회사 세몽나이스 | 1,026,789,120 | - |
| 3 | R26BK01673404 | 000 | 등록공고 | 2026-08-13 | 2026-08-24 | 913,370,885 | 전자입찰 | 001 | 2026-08-24 | 주식회사 나라컨트롤 | 810,139,000 | 80.4980 |
| 4 | R26BK01679493 | 000 | 등록공고 | 2026-08-13 | 2026-08-26 | 579,146,273 | 전자입찰 | 001 | 2026-09-03 | 케이원에코텍 주식회사 | 426,420,000 | 69.0200 |
| 5 | R26BK01684354 | 000 | 등록공고 | 2026-08-17 | 2026-08-27 | 491,000,000 | 직찰/우편/상시 | 002 | 2026-08-31 | (주)한경글로벌 | 496,890,000 | - |
| 6 | R26BK01684354 | 001 | 변경공고 | 2026-08-17 | 2026-08-27 | 491,000,000 | 직찰/우편/상시 | 002 | 2026-08-31 | (주)한경글로벌 | 496,890,000 | - |
| 7 | R26BK01688802 | 000 | 등록공고 | 2026-08-19 | 2026-08-25 | 403,820,945 | 전자입찰 | 001 | 2026-08-31 | 근영산업개발(주) | 368,595,600 | 82.4950 |
| 8 | R26BK01693090 | 000 | 등록공고 | 2026-08-21 | 2026-08-25 | 581,818,182 | 전자시담 | 001 | 2026-08-25 | 동아정밀공업사 | 620,000,000 | 100.0000 |

`낙찰률` 은 `bid_results.sucsf_bid_rate` 원값이며, NULL 이면 `-` 로 표기했다.

### 3.2 결과 차수를 가진 동반 공고 행

미매칭 8행의 결과 차수(`001`/`002`)와 **같은 차수의 공고 행**이 공고 테이블에 존재한다. 아래가 그 행이다.

| # | 공고번호 | 차수 | 공고종류 | bid_ntce_dt | openg_dt | bid_methd_nm | 수집일 |
| --: | --- | --- | --- | --- | --- | --- | --- |
| 1 | R26BK01629556 | 001 | 변경공고 | 2026-07-13 | 2026-08-24 | 전자입찰 | 2026-07-31 |
| 2 | R26BK01636318 | 001 | 변경공고 | 2026-08-11 | 2026-08-31 | 전자입찰 | 2026-08-13 |
| 3 | R26BK01673404 | 001 | 변경공고 | 2026-08-13 | 2026-08-24 | 전자입찰 | 2026-08-13 |
| 4 | R26BK01679493 | 001 | 변경공고 | 2026-08-18 | 2026-09-03 | 전자입찰 | 2026-08-27 |
| 5 | R26BK01684354 | 002 | 변경공고 | 2026-08-27 | 2026-08-31 | 전자입찰 | 2026-08-27 |
| 6 | R26BK01684354 | 002 | 변경공고 | 2026-08-27 | 2026-08-31 | 전자입찰 | 2026-08-27 |
| 7 | R26BK01688802 | 001 | 변경공고 | 2026-08-24 | 2026-08-31 | 전자입찰 | 2026-08-27 |
| 8 | R26BK01693090 | 001 | 변경공고 | 2026-08-25 | 2026-08-25 | 전자시담 | 2026-08-27 |

`R26BK01684354` 는 공고 행이 3개다. 차수 `000`(등록공고)·`001`(변경공고)·`002`(변경공고)이며, 미매칭은 `000`·`001` 두 행이고 결과 차수 `002` 행은 다음 주(2026-08-31)에 매칭된다. 또한 이 사업은 변경공고에서 입찰방식이 `직찰/우편/상시`(차수 000·001)에서 `전자입찰`(차수 002)로 바뀌었다.

### 3.3 차수의 주간 귀속과 정본 매칭 결과

| # | 공고번호 | 미매칭 행 openg 주 | 결과 rl_openg 주 | 동반 변경공고 행 주 | 정본 매칭 결과 |
| --: | --- | --- | --- | --- | --- |
| 1 | R26BK01629556 | 2026-08-24 | 2026-08-24 | 2026-08-24 | 000 미매칭, 001 같은 주 매칭 (같은 사업 중복 계수) |
| 2 | R26BK01636318 | 2026-08-24 | 2026-08-31 | 2026-08-31 | 000 미매칭, 001 다음 주 매칭 |
| 3 | R26BK01673404 | 2026-08-24 | 2026-08-24 | 2026-08-24 | 000 미매칭, 001 같은 주 매칭 (중복 계수) |
| 4 | R26BK01679493 | 2026-08-24 | 2026-09-03 | 2026-09-03 | 000 미매칭, 001 다음 주 매칭 |
| 5 | R26BK01684354 | 2026-08-24 | 2026-08-31 | 2026-08-31 | 000·001 미매칭, 002 다음 주 매칭 |
| 6 | R26BK01684354 | 2026-08-24 | 2026-08-31 | 2026-08-31 | 000·001 미매칭, 002 다음 주 매칭 |
| 7 | R26BK01688802 | 2026-08-24 | 2026-08-31 | 2026-08-31 | 000 미매칭, 001 다음 주 매칭 |
| 8 | R26BK01693090 | 2026-08-24 | 2026-08-24 | 2026-08-24 | 000 미매칭, 001 같은 주 매칭 (중복 계수) |

같은 주에 원 공고와 변경공고가 함께 있는 3건(#1·#3·#8)은 동일 사업이 미매칭 1행과 매칭 1행으로 **두 번 계수**된다. 나머지 5행(#2·#4·#5·#6·#7)은 변경공고가 개찰일을 다음 주로 옮겨 옛 차수 행만 08-24 주에 남은 경우다.

---

## 4. 원인 판정 (필수 항목 2)

### 4.1 판정문

**결과 차수 `001`/`002` 는 같은 입찰의 정정공고(변경공고)이며, 공고 테이블에 해당 차수 행이 이미 존재한다. 매칭에서 빠진 이유는 기간 조건이 아니라 차수 완전 일치 조인 규칙이다. 미수집분은 없다.**

| 코디네이터 3지선다 | 판정 | 근거 |
| --- | --- | --- |
| 결과 차수가 같은 입찰의 재공고·정정 공고인가 | **정정공고(변경공고)다.** 재공고가 아니다 | 8건의 결과 차수 대응 공고 행 `ntce_kind_nm` 이 전부 `변경공고`(3.2절). 공고 차수 `000` 행은 전부 `등록공고` |
| 공고 테이블에 차수 행이 존재하는데 기간 조건으로 빠졌는가 | **행은 존재한다. 기간 조건 때문이 아니다** | 7개 번호 전부 결과 차수 공고 행 존재(3.2절). 12주 불일치 3,525행 중 3,525행(100%)이 결과 차수 공고 행을 가진다(4.2절) |
| 공고 차수 행 자체가 미수집인가 | **아니다** | 위와 같음. 불일치 행이 결과 차수보다 작은 차수에만 존재 |

### 4.2 전 분류 확인: 결과 차수 공고 행 보유율 100%

같은 현상이 8건에만 있는지 전 분류·12주로 확장해 확인했다. 불일치 행이 결과 차수와 같은 차수의 공고 행을 가지는 비율은 **100%** 다.

| 분류 | 불일치 행 | 결과 차수 공고 행 보유 | 보유율 | 고유 공고번호 | 결과 차수 > 공고 차수 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Servc | 1,294 | 1,294 | 100.0% | 1,056 | 1,294 (100.0%) |
| Cnstwk | 1,374 | 1,374 | 100.0% | 1,123 | 1,374 (100.0%) |
| Thng | 857 | 857 | 100.0% | 734 | 857 (100.0%) |
| 합계 | 3,525 | 3,525 | 100.0% | 2,913 | 3,525 (100.0%) |

"결과 차수 > 공고 차수" 는 흡수안의 안전 조건을 확인한 것이다. 불일치 행은 전부 **옛 차수** 공고 행이며, 결과는 항상 **더 큰 차수**에 등록돼 있다. 차수가 역행하는(결과 차수 < 공고 차수) 불일치 행은 관측되지 않았다.

### 4.3 불일치 행의 공고종류 구성

불일치 행 3,525건의 공고종류는 다음과 같다. 약 80%가 원 공고(등록공고) 차수 행이고, 약 18%가 중간 변경공고 차수 행, 2.6%가 재공고 차수 행이다.

| 공고종류 | 불일치 행 | 비중 | Servc | Cnstwk | Thng |
| --- | ---: | ---: | ---: | ---: | ---: |
| 등록공고 | 2,806 | 79.6% | 993 | 1,110 | 703 |
| 변경공고 | 628 | 17.8% | 244 | 257 | 127 |
| 재공고 | 91 | 2.6% | 57 | 7 | 27 |
| 합계 | 3,525 | 100.0% | 1,294 | 1,374 | 857 |

대표적 구성은 "등록공고 `000` → 결과 `001`"(Cnstwk 914, Servc 810, Thng 612), "변경공고 `001` → 결과 `002`"(Cnstwk 164, Servc 159, Thng 71), "등록공고 `000` → 결과 `002`"(Cnstwk 157, Servc 149, Thng 67) 순이다.

### 4.4 근본 원인

정본 매칭은 (bid_ntce_no, category, 정규화 차수) **완전 일치**를 요구한다(`src/app/services/result_coverage.py:42` 이하, `compute_result_match_rates`). 그런데 상류 데이터는 차수별로 공고 행을 **모두** 남기고 낙찰결과는 **최신 차수에만** 등록한다. 그래서 변경공고가 한 번이라도 발행되면 옛 차수 공고 행은 구조적으로 조인 상대가 없다.

이것은 수집기 결함이나 조달청 API 미등록이 아니라, **차수 분기 데이터 구조와 완전 일치 조인 규칙 사이의 정의 불일치**다. W1 보고서 5.4절이 "차수 정규화 조인 결함(부분 인정)"으로 적은 항목의 실체가 이것이다.

부수 효과로, 같은 사업의 복수 공고 행이 모두 개찰 주별 분모에 계수된다. 최근 12주 기준 복수 공고 행을 가진 공고번호는 Servc 1,859 / Cnstwk 1,414 / Thng 1,309 건이며, 공고 행 총계는 공고번호 수보다 Servc 2,256 / Cnstwk 1,765 / Thng 1,543 행 많다(4.5절). 같은 주에 원·변경 공고가 겹치면(#1·#3·#8) 한 사업이 매칭 1·미매칭 1로 두 번 계수된다.

### 4.5 공고 행 중복 규모

| 분류 | 공고번호 | 공고 행 | 복수 행 공고번호 | 3행 이상 공고번호 | 행 초과분 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Servc | 36,817 | 39,073 | 1,859 | 315 | 2,256 |
| Cnstwk | 28,197 | 29,962 | 1,414 | 268 | 1,765 |
| Thng | 28,836 | 30,379 | 1,309 | 177 | 1,543 |

행 초과분 = 공고 행 − 공고번호. 분모(공고 행)가 사업 수보다 많은 구조다.

---

## 5. 조인 규칙 흡수 시뮬레이션

흡수안은 "같은 공고번호·분류의 결과가 다른 차수에 있으면 매칭으로 인정"(예: 최대 차수 결과 인정)이다. 공고 행 단위 존재 판정이므로 "임의 차수 결과 인정"과 "최대 차수 결과 인정"은 같은 결과를 낸다. 흡수 시 매칭률은 `matched_any / ann`, 영향은 `(matched_any − matched_ord) / ann` 로 계산했다.

| 구분 | 계산 | 설명 |
| --- | --- | --- |
| 현행 매칭 | `EXISTS(결과 where 차수 일치)` | 정본 정의 |
| 흡수 매칭 | `EXISTS(결과 where 공고번호·분류 일치)` | 차수 무시 |
| 영향(%p) | `(흡수 − 현행) / 공고` | 매칭률 상승폭 |

2026-08-24 주 물품 대형을 예로 들면 현행 243/454 = 53.52% 가 흡수 시 251/454 = 55.29% 로 **+1.76%p** 오른다. 다만 이는 분모(454)를 그대로 둔 값이며, 분모의 중복 계수는 흡수로 해소되지 않는다.

---

## 6. 전 분류·최근 12주 규모와 매칭률 영향 (필수 항목 3)

### 6.1 분류 × 규모 12주 집계

기간: 최신 성숙 주 2026-08-24 부터 12주(2026-06-08 ~ 2026-08-30 개찰). 공고 조건은 정본과 동일(`category IN (Servc, Cnstwk, Thng)`, 취소공고 제외, 공고일 하한 블록 시작 − 365일).

| 분류 | 규모 | 공고 | 현행 매칭 | 현행 매칭률 | 차수 불일치 | 흡수 매칭 | 흡수 매칭률 | 영향 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cnstwk | 대형 | 7,158 | 5,413 | 75.62% | 407 | 5,820 | 81.31% | **+5.69%p** |
| Cnstwk | 소형 | 22,804 | 19,187 | 84.14% | 967 | 20,154 | 88.38% | +4.24%p |
| Servc | 대형 | 7,484 | 3,553 | 47.47% | 351 | 3,904 | 52.16% | **+4.69%p** |
| Servc | 소형 | 31,589 | 18,018 | 57.04% | 943 | 18,961 | 60.02% | +2.99%p |
| Thng | 대형 | 6,042 | 3,445 | 57.02% | 159 | 3,604 | 59.65% | +2.63%p |
| Thng | 소형 | 24,337 | 12,633 | 51.88% | 698 | 13,331 | 54.78% | +2.87%p |

대형 기준 영향은 공사 +5.69%p > 용역 +4.69%p > 물품 +2.63%p 다. W1 보고서가 경고 대상으로 삼은 물품 대형이 오히려 세 분류 중 영향이 가장 작다.

### 6.2 주별 차수 불일치 건수

| 주시작 | Cnstwk 대형 | Cnstwk 소형 | Servc 대형 | Servc 소형 | Thng 대형 | Thng 소형 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-06-08 | 43 | 76 | 49 | 104 | 10 | 54 |
| 2026-06-15 | 42 | 84 | 34 | 91 | 18 | 68 |
| 2026-06-22 | 42 | 115 | 26 | 85 | 24 | 82 |
| 2026-06-29 | 37 | 101 | 30 | 66 | 20 | 42 |
| 2026-07-06 | 27 | 90 | 25 | 78 | 13 | 35 |
| 2026-07-13 | 37 | 93 | 24 | 96 | 11 | 48 |
| 2026-07-20 | 38 | 73 | 48 | 84 | 9 | 44 |
| 2026-07-27 | 24 | 72 | 26 | 81 | 9 | 51 |
| 2026-08-03 | 36 | 72 | 28 | 55 | 6 | 41 |
| 2026-08-10 | 26 | 83 | 26 | 83 | 18 | 62 |
| 2026-08-17 | 32 | 56 | 24 | 68 | 13 | 72 |
| 2026-08-24 | 23 | 52 | 11 | 52 | 8 | 99 |
| 합계 | 407 | 967 | 351 | 943 | 159 | 698 |

물품 대형은 12주 내내 6~24건으로 절대 규모가 작다. 같은 물품 소형은 마지막 주 99건으로 늘었다.

### 6.3 2026-08-24 주 분류 × 규모

경고가 난 주의 값이다. 참고로 같은 주 정본 값(물품 대형 243/454)은 W1 보고서 4.1절과 일치한다.

| 분류 | 규모 | 공고 | 현행 매칭 | 현행 매칭률 | 차수 불일치 | 흡수 매칭률 | 영향 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cnstwk | 대형 | 407 | 293 | 71.99% | 23 | 77.64% | +5.65%p |
| Cnstwk | 소형 | 1,482 | 1,213 | 81.85% | 52 | 85.36% | +3.51%p |
| Servc | 대형 | 468 | 188 | 40.17% | 11 | 42.52% | +2.35%p |
| Servc | 소형 | 2,238 | 1,290 | 57.64% | 52 | 59.96% | +2.32%p |
| Thng | 대형 | 454 | 243 | 53.52% | 8 | 55.29% | +1.76%p |
| Thng | 소형 | 2,550 | 1,345 | 52.75% | 99 | 56.63% | +3.88%p |

### 6.4 경고 임계에 미치는 영향

흡수는 현재·기저 양쪽을 올린다. 최신 성숙 주(실측 2026-08-24, 기저 2025-08-25)에 대해 흡수 전후 낙폭을 계산했다. 기저는 364일 오프셋 주를 같은 정의로 집계한 값이다.

| 분류 | 현행 기저 | 현행 실측 | 현행 낙폭 | 흡수 기저 | 흡수 실측 | 흡수 낙폭 | 경고 판정 변화 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Thng 대형 | 266/409 = 65.04% | 243/454 = 53.52% | -11.52%p | 281/409 = 68.70% | 251/454 = 55.29% | **-13.41%p** | 경고 유지, 낙폭 확대 |
| Servc 대형 | 194/392 = 49.49% | 188/468 = 40.17% | -9.32%p | 213/392 = 54.34% | 199/468 = 42.52% | **-11.82%p** | **미경고 → 경고 신규** |
| Cnstwk 대형 | 373/503 = 74.16% | 293/407 = 71.99% | -2.17%p | 399/503 = 79.32% | 316/407 = 77.64% | -1.68%p | 미경고 유지 |

물품 대형은 기저가 더 많이 오르는 바람에 낙폭이 오히려 커지고(11.52 → 13.41%p), 용역 대형은 10%p 임계를 새로 넘는다. **차수 흡수는 경고를 줄이는 방향이 아니라 바꾸는 방향으로 작동한다.**

---

## 7. 흡수안 오탐 위험과 권고 (필수 항목 4)

### 7.1 흡수안 정의와 오탐 위험

| 위험 | 내용 | 근거 | 심각도 |
| --- | --- | --- | --- |
| 시도별 낙찰률 과대평가 | 원 차수 공고가 유찰됐고 나중 차수에서 낙찰된 경우에도 원 차수 행을 매칭으로 세어, "공고 시도별 낙찰률"이 실제보다 높아진다. 결과 테이블만으로 유찰 여부를 구분할 수 없다 | 불일치 행 79.6%가 등록공고 차수 행(4.3절) | 중 |
| 주차 귀속 이동 | 변경공고가 개찰일을 뒤로 미루면 옛 주에 결과를 인정해 주간 매칭률이 이동한다. 08-24 주 물품 대형 8행 중 5행이 이 유형 | 3.3절 #2·#4·#5·#6·#7 | 중 |
| 분모 중복 미해소 | 흡수는 분자만 늘리고 같은 사업의 복수 공고 행을 그대로 센다. 매칭률이 "사업 단위 성공률"과 계속 어긋난다 | 4.5절 (12주 행 초과분 Thng 1,543) | 중 |
| 경고 임계 요동 | 현재·기저를 함께 올려 낙폭 방향이 일정하지 않다. 08-24 주에서 물품 낙폭 확대, 용역 신규 경고 | 6.4절 | 높음 |
| 차수 역행 오탐 | 결과 차수가 공고 차수보다 작은 경우 옛 시도를 미래 결과와 잘못 연결할 수 있다 | 관측상 0건(4.2절). 결과 차수 > 공고 차수 100% | 낮음 |

### 7.2 권고

| 번호 | 권고 | 근거 | 우선순위 |
| --- | --- | --- | --- |
| B1 | 정본 매칭 정의(차수 완전 일치)는 유지한다. 이 8건은 데이터 회수 문제가 아니므로 수집 파이프라인 조치는 불필요하다 | 4.1·4.2절 | 높음 |
| B2 | 차수 회수율이 필요하면 흡수 대신 **별도 보조 지표**("공고번호 단위 결과 회수율")로 산출한다. 정본 지표와 분리해 경고 판정에 쓰지 않는다 | 6.4절 경고 요동 | 높음 |
| B3 | 분모 왜곡을 고치려면 흡수보다 **공고번호 단위 중복 제거**(같은 공고번호·분류의 복수 공고 행을 최종 차수 1건으로 축약)가 먼저다. 그래야 한 사업의 다중 계수가 사라진다 | 4.5절 | 중 |
| B4 | 흡수안을 도입하더라도 `결과 차수 > 공고 차수` 이고 공고종류가 등록공고·변경공고·재공고인 경우로 한정한다. 관측상 100%가 이 조건을 만족한다 | 4.2절 | 중 |
| B5 | 경고 로직 변경은 흡수 여부와 별개로 다룬다. 정의를 바꾸면 임계 통과 여부가 달라지므로(6.4절), 변경 시 별도 승인과 전후 검증이 필요하다 | 6.4절 | 높음 |

---

## 8. 불확실성과 한계

1. **유찰 여부 미구분.** 결과 테이블만으로 원 차수 시도의 유찰/취소를 판정할 수 없다. 조달청 API 직접 조회가 금지된 계약이라 상류 이력으로 확인하지 못했다.
2. **성숙도.** 최근 주(2026-08-17·24)는 결과 도착이 아직 진행 중일 수 있다. 다만 차수 불일치는 수집 지연과 다른 구조 문제이며, W1 보고서 6.2·6.4절이 08-24 주 도착 곡선이 이미 포화임을 보였다.
3. **기저 흡수값의 범위.** 6.4절 흡수 기저는 364일 오프셋 주를 같은 규칙으로 집계한 값이다. 정본 경고 로직이 기저 블록을 12주 전체로 함께 조회하는 방식과 창 정의는 동일하나, 흡수안 자체는 정본에 없는 정의이므로 임계 판정 변화는 참고치다.
4. **표본.** 2026-08-24 주 물품 대형 불일치는 8건으로 작다. 주간 등락이 확대 해석을 부른다(6.2절).

---

## 9. 재현 명령

모든 수치는 `uv run python scripts/db_readonly_query.py --sql "<질의>"` 로 재현한다. 아래 `RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(<차수>)), ''), '0')), 3)` 는 `normalize_ord` 와 동일한 차수 정규화 표현이다.

O1. 8건 공고 행·결과 행 대조(3.1절):
```
SELECT a.id AS ann_id, a.bid_ntce_no, a.bid_ntce_ord AS ann_ord, a.bid_ntce_nm, a.bid_methd_nm, a.dminstt_nm, DATE(a.bid_ntce_dt) AS bid_ntce_day, DATE(a.openg_dt) AS openg_day, a.presmpt_prce, a.ntce_kind_nm, br.id AS res_id, br.bid_ntce_ord AS res_ord, br.category AS res_cat, DATE(br.rl_openg_dt) AS res_openg_day, br.bidwinnr_nm, br.sucsf_bid_amt, br.sucsf_bid_rate FROM bid_announcements a JOIN bid_results br ON br.bid_ntce_no = a.bid_ntce_no WHERE a.category = 'Thng' AND a.openg_dt >= '2026-08-24 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.bid_ntce_dt >= '2024-06-09 00:00:00' AND NOT EXISTS (SELECT 1 FROM bid_results br2 WHERE br2.bid_ntce_no = a.bid_ntce_no AND br2.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br2.bid_ntce_ord)), ''), '0')), 3)) ORDER BY a.bid_ntce_no, a.bid_ntce_ord
```

O2. 7개 공고번호의 전체 공고 행(3.2절):
```
SELECT a.id, a.bid_ntce_no, a.bid_ntce_ord, a.category, a.bid_ntce_nm, a.bid_methd_nm, DATE(a.bid_ntce_dt) AS bid_ntce_day, DATE(a.openg_dt) AS openg_day, a.presmpt_prce, a.ntce_kind_nm, DATE(a.collected_at) AS coll_day FROM bid_announcements a WHERE a.bid_ntce_no IN ('R26BK01629556','R26BK01636318','R26BK01673404','R26BK01679493','R26BK01684354','R26BK01688802','R26BK01693090') ORDER BY a.bid_ntce_no, a.category, a.bid_ntce_ord
```

O3. 7개 공고번호의 전체 결과 행(3.1절):
```
SELECT br.id, br.bid_ntce_no, br.bid_ntce_ord, br.category, br.bid_ntce_nm, DATE(br.rl_openg_dt) AS rl_openg_day, br.bidwinnr_nm, br.sucsf_bid_amt, br.sucsf_bid_rate, DATE(br.collected_at) AS coll_day FROM bid_results br WHERE br.bid_ntce_no IN ('R26BK01629556','R26BK01636318','R26BK01673404','R26BK01679493','R26BK01684354','R26BK01688802','R26BK01693090') ORDER BY br.bid_ntce_no, br.bid_ntce_ord
```

O4. 분류 × 규모 12주 집계(6.1절). 기저 창은 아래 O9 와 동일 골격에서 기간만 바꾼다.
```
SELECT a.category, CASE WHEN a.presmpt_prce >= 230000000 THEN 'large' ELSE 'small' END AS band, COUNT(*) AS ann, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS matched_ord, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) THEN 1 ELSE 0 END) AS matched_any, SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) AND EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) THEN 1 ELSE 0 END) AS ord_mismatch FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') GROUP BY a.category, band ORDER BY a.category, band
```

O5. 주별 분류 × 규모 집계(6.2·6.3절). O4 와 같은 골격에 `SELECT`·`GROUP BY` 에 `DATE_SUB(DATE(a.openg_dt), INTERVAL WEEKDAY(a.openg_dt) DAY) AS wk` 를 추가한다.

O6. 불일치 행의 공고종류 구성(4.3절):
```
SELECT COALESCE(a.ntce_kind_nm, '(null)') AS ann_kind, COUNT(*) AS n, SUM(CASE WHEN a.category = 'Servc' THEN 1 ELSE 0 END) AS servc, SUM(CASE WHEN a.category = 'Cnstwk' THEN 1 ELSE 0 END) AS cnstwk, SUM(CASE WHEN a.category = 'Thng' THEN 1 ELSE 0 END) AS thng FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND NOT EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) AND EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) GROUP BY ann_kind ORDER BY n DESC
```

O7. 결과 차수 공고 행 보유율·고유 공고번호·차수 역행 검사(4.2절):
```
SELECT a.category, COUNT(*) AS mismatch_rows, COUNT(DISTINCT a.bid_ntce_no) AS notices, SUM(CASE WHEN CAST((SELECT MAX(br.bid_ntce_ord) FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) AS UNSIGNED) > CAST(a.bid_ntce_ord AS UNSIGNED) THEN 1 ELSE 0 END) AS res_ord_greater FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND NOT EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) AND EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) GROUP BY a.category
```

O8. 결과 차수 공고 행 보유율(4.2절의 보유 건수). O7 과 같은 조건에서 `COUNT(*)` 옆에 `SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_announcements a2 WHERE a2.bid_ntce_no = a.bid_ntce_no AND a2.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a2.bid_ntce_ord)), ''), '0')), 3) IN (SELECT RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category)) THEN 1 ELSE 0 END) AS ann_row_at_res_ord` 를 추가한다.

O9. 기저 364일 오프셋 집계(6.4절 기저 열). O4 와 같은 골격에서 기간을 `a.openg_dt >= '2025-06-09' AND a.openg_dt <= '2025-08-31 23:59:59.999999' AND a.bid_ntce_dt >= '2024-06-09' AND a.bid_ntce_dt <= '2025-08-31 23:59:59.999999'` 로 바꾼다.

O10. 기저 주 2025-08-25 대형(6.4절). O9 에 `a.presmpt_prce >= 230000000` 을 더하고 `ann, matched_ord, matched_any` 만 `GROUP BY a.category` 로 낸다.

O11. 공고번호 단위 공고 행 중복(4.5절):
```
SELECT t.category, COUNT(*) AS notices, SUM(t.cnt) AS ann_rows, SUM(CASE WHEN t.cnt >= 2 THEN 1 ELSE 0 END) AS multi_row_notices, SUM(CASE WHEN t.cnt >= 3 THEN 1 ELSE 0 END) AS triple_row_notices FROM (SELECT a.bid_ntce_no, a.category, COUNT(*) AS cnt FROM bid_announcements a WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.openg_dt >= '2026-06-08 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.bid_ntce_dt >= '2025-06-08 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') GROUP BY a.bid_ntce_no, a.category) t GROUP BY t.category
```

O12. 불일치 행 구성 상세(4.3절의 대표 구성). O6 과 같은 조건에서 `SELECT` 에 `a.bid_ntce_ord AS ann_ord, (SELECT MIN(br.bid_ntce_ord) FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) AS min_res_ord, (SELECT MAX(br.bid_ntce_ord) FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category) AS max_res_ord` 를 추가하고 `GROUP BY a.category, ann_kind, a.bid_ntce_ord, min_res_ord, max_res_ord` 로 묶는다.

---

## 10. 참고 문서

- `docs/analysis/thng_match_rate_20260824.md`: W1 물품 매칭률 경고 원인 판정. 본 보고서는 5.4절·10절 Q9 의 후속 조사다.
- `docs/analysis/result_collection_gap_20260926.md`: 용역 상류 공백 분석. 수집 창 클램프 리스크를 다룬다.
- `docs/context/CURRENT_STATE.md`: 수집 파이프라인 운영 정본.
- `src/app/services/result_coverage.py`: 매칭률·경고 계산 정본. `normalize_ord`(`:42`), 대형 임계(`:27`), 경고 임계(`:29`).
- `src/app/models/bids.py`: `normalize_bid_ntce_ord` 와 `preload_matching_announcements` 의 차수 정규화 매칭 규칙.
- `scripts/db_readonly_query.py`: 읽기 전용 재현 도구.
