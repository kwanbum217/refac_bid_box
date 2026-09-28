# 물품(Thng) 대형 낙찰결과 매칭률 경고 원인 판정 (2026-08-24 주)

> **작성일**: 2026-09-28
> **상태**: 분석 완료 (코드·설정·DB 변경 없음)
> **범위**: 2026-09-28 커버리지 감시 경고(물품, 개찰 주 2026-08-24, 대형 매칭률 53.5%, 전년 동기 65.0%, 공고 454건)의 원인 판정
> **계보**: 2026-09-26 용역(Servc) 상류 공백 분석(`result_collection_gap_20260926.md`)의 물품 편 후속 조사
> **정본 모듈**: `../../src/app/services/result_coverage.py` (매칭률·경고 계산), `../../src/app/services/api_collector.py`, `../../src/app/services/collector_service.py`
> **질의 방법**: `uv run python scripts/db_readonly_query.py` (읽기 전용, SELECT 단일 문장), `uv run python scripts/result_match_rate_report.py`
> **계약 준수**: 조달청 API 직접 조회 없음. 운영 DB 쓰기 없음. 산출물은 본 문서 1건.

---

## 1. 요약 (결론)

1. **경고는 재현되며 실재하는 하락이다.** `uv run python scripts/result_match_rate_report.py --as-of 2026-09-28 --weeks 12 --format json` 은 물품 2026-08-24 주 대형 243/454 = **53.5%**, 전년 동기(2025-08-25 주) 266/409 = **65.0%** 를 그대로 재현한다. 경고 대상은 물품 1건뿐이고, 같은 주 용역은 40.2%(전년 49.5%, -9.3%p)라 10%p 임계에 닿지 않아 경고되지 않았다.

2. **자연 등록 지연만으로는 설명되지 않는다.** 08-24 주 대형 공고는 기준일 2026-09-28 에 이미 개찰 후 **31~35일** 경과했고, 같은 주 매칭 243건 중 241건(99.2%)이 개찰 후 30일 이내에 도착했다. 미매칭 211건의 경과일 구간(31~35일)은 도착 분포의 꼬리 바깥이다. 잔여 도착 여지까지 감안해도 자연 지연으로 회수될 수 있는 양은 10~17건 수준으로, 기준선 대비 결손 약 52건을 닫지 못한다.

3. **경고 폭의 약 40%는 물품 고유의 입찰방식 구성 차이다.** 전년 동기 주에는 물품 대형의 33.0%(135건)가 전자시담이었고 매칭률이 95.6%였다. 08-24 주는 전자시담 비중이 22.0%(100건)로 줄고 상대적으로 매칭률이 낮은 전자입찰 비중이 62.1%에서 73.3%로 늘었다. 표준화 분해 결과 구성 효과 **-4.5%p**, 방식별 매칭률 하락 효과 **-7.3%p**(합 11.5%p, 반올림 잔차 -0.3%p)이다.

4. **나머지 약 60%는 방식별 매칭률이 동시에 내려간 상류 등록 지연·누락이다.** 08-24 주 전년 대비 방식별 하락은 전자입찰 52.8% → 47.1%, 전자시담 95.6% → 86.0%, 직찰 15.8% → 0.0% 로 방식을 가리지 않는다. 미매칭은 발주기관 상위 15곳에 2~4건씩 흩어져 있어 특정 기관·특정 방식 집중이 아니다. 이 양상은 2026-09-26 용역 분석이 확정한 상류 공백과 같은 계열이며, 시차만 분류별로 다르다(용역 08-17 급락, 물품 08-10~08-24 완만 하락, 공사는 08-24 까지 -2.2%p 로 미영향).

5. **수집 경로·분류·임계의 물품 고유 결함은 확인되지 않았다.** 물품은 자체 엔드포인트(`getScsbidListSttusThng`, `getBidPblancListInfoThng`)를 쓰지만 수집 로직은 공통이고, 교차 분류 누출(다른 category 로 저장)은 0건이며, 2.3억 임계도 정본 정의와 일치한다. 미매칭 211건 중 8건(3.8%)만이 차수 불일치(공고 `000` vs 결과 `001`/`002`) 조인 결함이다.

6. **조치가 필요하다.** 단일 주 전년 동기 비교는 기저율 변동(물품 대형 전년 매칭률이 인접 주 57.6~69.7%로 요동)과 방식 구성 차이에 민감해 오탐·과소탐지를 만든다. 방식 구성 보정, 전년 동기 다주 평균 기저, 비전자 방식(직찰/우편) 분리, 2주 연속 조건을 제안한다(8절).

---

## 2. 조사 방법과 계약 범위

| 항목 | 내용 |
| --- | --- |
| 허용 명령 | `result_match_rate_report.py`, `db_readonly_query.py`, git 조회만 |
| 미허용 | 조달청 API 직접 조회, 운영 DB 쓰기, 그 외 스크립트 실행 |
| 경고 판정 정본 | `../../src/app/services/result_coverage.py` (`LARGE_PRICE_THRESHOLD=230_000_000`, `RATE_DROP_ALERT=0.10`, `MIN_WEEK_SAMPLES=100`, 성숙 `min_elapsed_days=28`, `BASELINE_OFFSET_DAYS=364`, 취소공고 제외, 차수 정규화 조인) |
| 경과일 기준 | `DATEDIFF('2026-09-28', DATE(a.openg_dt))` |
| 주요 한계 | 2025년 `bid_results.collected_at` 은 2026-03 대량 백필 시각이라 전년 도착 곡선으로 쓸 수 없다(7절 불확실성) |

`collected_at` 월별 수집 이력(Q7)에서 2026-03 에 공사 1,254,295건·용역 889,933건·물품 826,016건이, 2026-07 에 물품 29,182건이 적재됐고 2026-04~06 은 물품 결과 적재가 없다. 따라서 `collected_at` 기반 도착 곡선은 2026-07 이후 코호트에만 유효하며, 본 보고서는 2026-08 코호트를 중심으로 해석한다.

---

## 3. 경고 재현

```
uv run python scripts/result_match_rate_report.py --as-of 2026-09-28 --weeks 12 --format json
```

위 명령의 `alerts` 배열은 정확히 한 건이다.

| 분류 | 주시작 | 실측 | 전년 동기 | 공고 | 전년 공고 |
| --- | --- | ---: | ---: | ---: | ---: |
| Thng | 2026-08-24 | 53.5% (243/454) | 65.0% (266/409) | 454 | 409 |

성숙 규칙상 `as_of - 28일 = 2026-08-31` → 그 주의 월요일이 08-24 이므로, 2026-08-24 주가 "분류별 가장 최근 성숙 주"다. 참고로 **직전 성숙 주인 08-17 주도 -12.6%p**(52.9% vs 65.5%)로 임계를 넘었으나, 경고는 가장 최근 성숙 주만 보므로 이미 지나가 경고되지 않았다. 즉 물품은 08-10~08-24 세 주 연속 임계 초과 상태다.

---

## 4. 주별 매칭률 12주와 전년 동기

### 4.1 물품(Thng) 대형·소형

명령 Q1: `uv run python scripts/result_match_rate_report.py --as-of 2026-09-28 --weeks 12 --format json`

| 주시작 | 대형 공고 | 대형 매칭 | 대형 매칭률 | 전년 대형 공고 | 전년 대형 매칭률 | 소형 공고 | 소형 매칭 | 소형 매칭률 | 전년 소형 매칭률 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-06-08 | 554 | 353 | 63.7% | 580 | 65.7% | 2007 | 1064 | 53.0% | 52.4% |
| 2026-06-15 | 597 | 364 | 61.0% | 599 | 68.6% | 2389 | 1357 | 56.8% | 61.5% |
| 2026-06-22 | 654 | 401 | 61.3% | 558 | 69.7% | 2641 | 1550 | 58.7% | 63.7% |
| 2026-06-29 | 463 | 267 | 57.7% | 375 | 63.2% | 1764 | 848 | 48.1% | 51.3% |
| 2026-07-06 | 456 | 258 | 56.6% | 380 | 58.7% | 1636 | 841 | 51.4% | 52.2% |
| 2026-07-13 | 433 | 262 | 60.5% | 375 | 64.3% | 1531 | 736 | 48.1% | 51.9% |
| 2026-07-20 | 537 | 294 | 54.7% | 453 | 59.6% | 2033 | 1024 | 50.4% | 52.2% |
| 2026-07-27 | 467 | 250 | 53.5% | 415 | 62.4% | 1839 | 903 | 49.1% | 53.0% |
| 2026-08-03 | 445 | 250 | 56.2% | 434 | 57.6% | 1745 | 844 | 48.4% | 51.6% |
| 2026-08-10 | 496 | 246 | 49.6% | 312 | 60.9% | 2000 | 974 | 48.7% | 53.0% |
| 2026-08-17 | 486 | 257 | 52.9% | 467 | 65.5% | 2202 | 1147 | 52.1% | 57.5% |
| 2026-08-24 | 454 | 243 | 53.5% | 409 | 65.0% | 2550 | 1345 | 52.7% | 59.1% |

대형은 08-10 주(-11.3%p)·08-17 주(-12.6%p)·08-24 주(-11.5%p)로 임계를 3주 연속 넘겼고, 소형도 같은 기간 -4.3~-6.4%p 로 함께 내려갔다. 대형만의 문제가 아니라 물품 전반의 완만한 하락이다.

### 4.2 용역(Servc) 같은 기간 대비

같은 Q1 출력의 용역 행이다. 매칭률 절대 수준은 물품보다 낮지만 하락 시점이 더 급격하다.

| 주시작 | Servc 대형 매칭률 | Servc 전년 대형 | 차이 | Servc 소형 매칭률 | Servc 전년 소형 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-27 | 48.3% | 53.4% | -5.1%p | 58.3% | 62.5% |
| 2026-08-03 | 44.8% | 52.9% | -8.1%p | 58.0% | 60.7% |
| 2026-08-10 | 46.5% | 53.4% | -6.9%p | 58.3% | 65.3% |
| 2026-08-17 | 38.2% | 52.4% | **-14.2%p** | 57.1% | 59.4% |
| 2026-08-24 | 40.2% | 49.5% | -9.3%p | 57.6% | 64.1% |

| 주시작 | Thng 대형 차이 | Servc 대형 차이 | Cnstwk 대형 차이 |
| --- | ---: | ---: | ---: |
| 2026-08-03 | -1.4%p (56.2/57.6) | -8.1%p | -2.1%p (69.5/71.6) |
| 2026-08-10 | **-11.3%p** (49.6/60.9) | -6.9%p | -1.1%p (73.6/74.7) |
| 2026-08-17 | **-12.6%p** (52.9/65.5) | **-14.2%p** | -0.2%p (71.7/72.0) |
| 2026-08-24 | **-11.5%p** (53.5/65.0) | -9.3%p | -2.2%p (72.0/74.2) |

공사는 08-24 주까지 기준선 수준을 유지한다. 세 분류가 동시에 무너지지 않고 시차를 두고 내려간다는 점은, 수집기 일괄 결함(전 분류 동시 하락)보다 상류 측 분류별 등록 사정과 같은 계열임을 시사한다.

---

## 5. 입찰방식 분해: 구성 효과와 순수 매칭률 하락

### 5.1 08-24 주 방식별 매칭 (정본 표본과 일치)

명령 Q4 (365일 공고 조회 하한 포함, 합계가 정본 454/243 과 일치):

| 방식 | 2026-08-24 공고 | 2026 매칭 | 2026 매칭률 | 2025-08-25 공고 | 2025 매칭 | 2025 매칭률 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 전자입찰 | 333 | 157 | 47.1% | 254 | 134 | 52.8% |
| 전자시담(+2인 이상) | 100 | 86 | 86.0% | 135 | 129 | 95.6% |
| 직찰 | 19 | 0 | 0.0% | 19 | 3 | 15.8% |
| 직찰/우편/상시 | 2 | 0 | 0.0% | 1 | 0 | 0.0% |
| 합계 | 454 | 243 | 53.5% | 409 | 266 | 65.0% |

### 5.2 표준화 분해

`result_coverage.py` 의 분류×규모 집계에 방식을 추가해 분해했다. 기준선 65.0%(=266/409) 대비 2026년 53.5%(=243/454)의 11.5%p 를 방식 구성과 방식별 매칭률로 나눈다.

| 시나리오 | 계산 | 매칭률 | 기준선과 차이 |
| --- | --- | ---: | ---: |
| 2025 구성 × 2025 매칭률 (기준선 실측) | 266/409 | 65.0% | - |
| 2026 구성 × 2025 매칭률 | (100×0.956 + 333×0.528 + 21×0.150)/454 = 274.5/454 | 60.5% | **-4.5%p (구성 효과)** |
| 2025 구성 × 2026 매칭률 | (135×0.860 + 254×0.471 + 20×0.000)/409 = 235.9/409 | 57.7% | **-7.3%p (매칭률 하락 효과)** |
| 2026 구성 × 2026 매칭률 (실측) | 243/454 | 53.5% | -11.5%p |

구성 효과의 원인은 전자시담 비중 변화다. 전자시담은 매칭률이 86~96%로 전자입찰(47~53%)의 두 배에 가깝기 때문에, 그 비중이 33.0% → 22.0% 로 줄면 전체 매칭률이 기계적으로 내려간다. 물품은 전자시담 비중이 큰 분류다(08-24 주 기준 물품 22.0%, 용역 9.4%, 공사 0.9%). 즉 **경고의 약 40%는 물품 고유의 방식 구성 차이이지 데이터 손실이 아니다.**

### 5.3 방식별 장기 추이 (물품 대형)

명령 Q6: 월별·방식별 매칭률(공고 20건 이상).

| 시점 | 전자입찰 | 전자시담 | 직찰 |
| --- | ---: | ---: | ---: |
| 2025-08 | 618/1165 = 53.0% | 415/438 = 94.7% | 14/78 = 17.9% |
| 2026-03 | 699/1272 = 55.0% | 374/405 = 92.3% | 4/128 = 3.1% |
| 2026-04 | 844/1562 = 54.0% | 499/538 = 92.8% | 18/215 = 8.4% |
| 2026-05 | 750/1471 = 51.0% | 421/443 = 95.0% | 7/225 = 3.1% |
| 2026-06 | 885/1718 = 51.5% | 577/620 = 93.1% | 16/221 = 7.2% |
| 2026-07 | 787/1539 = 51.1% | 413/457 = 90.4% | 12/249 = 4.8% |
| 2026-08 | 668/1473 = 45.4% | 340/365 = 93.2% | 11/280 = 3.9% |

전자입찰은 2026-05~07 약 51%에서 2026-08 45.4% 로 한 단계 더 내려갔고, 2025-08(53.0%) 대비 -7.6%p 다. 직찰은 2026-03 이후 3~8%로 2025년(13~28%)에서 구조적으로 내려앉았다. 전자시담은 월 단위로는 안정(90~95%)이며, 08-24 주의 86.0%만 이례적 저점이다.

### 5.4 물품 고유 요인 후보 검토

| 후보 | 판정 | 근거 |
| --- | --- | --- |
| 수집 경로가 물품만 다름 | 기각 | `api_collector.py` 는 분류별 URL 만 다르고 페이징·재시도·적재 로직은 `collector_service.py` 공통 경로다. 물품 전용 분기 결함 없음 |
| 분류 오분류(교차 누출) | 기각 | 미매칭 211건 중 같은 공고번호의 결과가 다른 category 로 존재하는 경우 0건(Q9) |
| 차수 정규화 조인 결함 | 부분 인정 | 미매칭 211건 중 8건(3.8%)이 공고 `000` vs 결과 `001`/`002` 불일치(Q9). 이 8건은 방식상 전자입찰 6·전자시담 1·직찰/우편/상시 1 |
| 2.3억 임계가 물품에 부적합 | 기각 | 물품 대형 454건은 정본 정의(`presmpt_prce >= 230000000`)와 일치하며 표본도 충분(≥100) |
| 방식 구성 차이(전자시담·직찰) | 채택 | 5.2절. 구성 효과 -4.5%p |

---

## 6. 미매칭 대형 공고 경과일 분포와 도착 지연 곡선

### 6.1 미매칭 211건의 개찰 후 경과일 분포

명령 Q2 (기준일 2026-09-28, 물품 대형, 취소공고 제외, 365일 공고 하한 포함):

| 개찰일 | 경과일 | 미매칭 건수 |
| --- | ---: | ---: |
| 2026-08-24 | 35 | 35 |
| 2026-08-25 | 34 | 42 |
| 2026-08-26 | 33 | 42 |
| 2026-08-27 | 32 | 60 |
| 2026-08-28 | 31 | 32 |
| 합계 | - | 211 |

미매칭은 모두 개찰 후 **31~35일** 구간에 몰려 있다. 08-27 개찰분이 60건으로 가장 많은데, 이 날짜의 공고 수가 원래 많았기 때문이다.

### 6.2 08-24 주 대형 도착 지연 곡선

명령 Q3 (물품 대형, 개찰 주 08-03~09-21, `DATEDIFF(br.collected_at, a.openg_dt)` 버킷):

| 개찰 주 | 0~1일 | 2~5일 | 6~13일 | 14~30일 | 30일 초과 | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-03 | 0 | 1 | 176 | 59 | 14 | 250 |
| 2026-08-10 | 33 | 45 | 58 | 102 | 8 | 246 |
| 2026-08-17 | 0 | 0 | 179 | 76 | 2 | 257 |
| 2026-08-24 | 36 | 44 | 116 | 45 | 2 | 243 |

08-24 주는 매칭 243건 중 **241건(99.2%)이 개찰 후 30일 이내** 도착했고 30일 초과는 2건(0.8%)뿐이다. 미매칭 211건의 경과일(31~35일)은 도착 분포가 이미 닫힌 뒤 구간이다.

### 6.3 방식별 도착 곡선 (2026-08)

명령 Q11 (물품 대형, 방식별).

| 방식 | 0~5일 | 6~13일 | 14~30일 | 30일 초과 | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 전자시담(08-24 주) | 50 | 33 | 3 | 0 | 86 |
| 전자입찰(08-24 주) | 30 | 83 | 42 | 2 | 157 |

전자시담은 08-24 주 매칭 86건 중 83건(96.5%)이 13일 이내 도착했고 30일 초과는 0건이다. 전자시담 기대치(전년 95.6% → 100건 기준 약 96건)와 실측 86건의 차이 약 10건은 자연 지연으로 설명되지 않는다.

### 6.4 성숙도별 누적 매칭 (08-24 주)

명령 Q10 (`collected_at <= openg_dt + N일` 로 코호트를 동일 성숙도에서 비교).

| 개찰 주 | 7일 | 14일 | 21일 | 28일 | 35일 | 현재 최종 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-07-20 | 14 | 217 | 236 | 272 | 279 | 294 |
| 2026-07-27 | 101 | 163 | 219 | 231 | 246 | 250 |
| 2026-08-03 | 73 | 177 | 193 | 232 | 242 | 250 |
| 2026-08-10 | 78 | 159 | 213 | 234 | 245 | 246 |
| 2026-08-17 | 102 | 187 | 237 | 252 | 256 | 257 |
| 2026-08-24 | 113 | 203 | 228 | **240** | **243** | 243 |

08-24 주는 28일 240건 → 35일 243건으로 증가폭이 3건뿐이다. 앞선 코호트의 28일 이후 추가 도착은 08-03 주 18건, 07-20 주 22건이었던 것에 비하면 이미 포화 상태다. 28일 이후 추가 도착 여지를 앞선 코호트 비율(2~7%)로 넓게 잡아도 08-24 주의 잔여 기대 도착은 5~17건이다.

### 6.5 자연 지연으로 설명되지 않는 결손

| 항목 | 값 | 계산 |
| --- | ---: | --- |
| 전년 동기 기준 기대 매칭 | 295.3 | 0.6503668 × 454 |
| 2026-08-24 실측 매칭 | 243 | Q1 |
| 결손 | 52.3 | 295.3 - 243 |
| 자연 지연 잔여 회수 상한 | 5~17 | 6.4절 꼬리 비율 |
| 자연 지연 제외 결손 | **35~47** | 52.3 - (5~17) |

---

## 7. 판정

### 7.1 판정문

**자연 등록 지연 단독이 아니다. 경고 폭 11.5%p 중 약 4.5%p 는 물품 고유의 입찰방식 구성 차이(전자시담 비중 전년 동기 33.0% → 22.0%)이고, 나머지 약 7.3%p 는 물품 대형의 방식별 매칭률이 동시에 내려간 상류 등록 지연·누락이다. 수집 경로·분류·임계의 물품 고유 결함은 확인되지 않았다.**

부수적으로, 미매칭의 3.8%(8건)는 공고 차수(`000`)와 결과 차수(`001`/`002`) 불일치 조인 결함이며, 직찰·직찰/우편/상시는 2026-03 이후 연중 매칭률 3~8%로 구조적 미수집 구간이다.

### 7.2 근거 정합성

| 판정 요소 | 근거 절 | 수치 |
| --- | --- | --- |
| 자연 지연 아님 | 6.2, 6.4, 6.5 | 31~35일 경과, 30일 이내 도착 99.2%, 결손 35~47건 잔존 |
| 구성 효과(물품 고유) | 5.1, 5.2 | -4.5%p |
| 방식별 동반 하락(상류) | 5.1, 5.3 | 전자입찰 -5.7%p, 전자시담 -9.6%p, 직찰 -15.8%p, 기관 분산 |
| 수집 경로 결함 아님 | 5.4, Q7 | 공통 수집 경로, 08-24 주 등록 구간 수집 공백 없음 |

### 7.3 수집 창 공백과의 관계

2026-09-26 용역 분석은 8/15~9/5, 9/11~9/13, 9/21, 9/23~9/25 의 수집 실행 공백과 `MAX_CATCHUP_DAYS=7` 클램프 리스크를 지적했다. 이번 08-24 주에는 그 공백이 결손을 만들지 않았다. 08-24 주 결과의 등록 가능 구간(8/24 이후)은 8/27·9/04·9/07~9/19·9/22·9/26 실행이 덮었고, Q7 의 월별 적재에서도 2026-08 물품 5,132건이 확인된다(8/13 1,938, 8/14 201, 8/27 2,990, 8/09 3). 다만 마지막 수집이 9/26 이므로 9/27~9/28 등록분은 아직 미반영이며, 이것이 6.5절 잔여 자연 지연의 일부다.

---

## 8. 조치 제안

| 번호 | 제안 | 근거 | 우선순위 |
| --- | --- | --- | --- |
| A1 | 경고 비교를 단일 주 전년 동기가 아니라 **전년 동기 인접 4~5주 평균 기저**로 바꾼다 | 물품 대형 전년 매칭률이 인접 주 57.6~69.7%로 요동한다(4.1절). 08-24 주 기저 65.0% 는 국지적으로 높아 오탐을 키웠다 | 높음 |
| A2 | 방식 구성 보정 매칭률(표준화율)을 병행 산출하고, 경고는 보정율 기준으로 판정한다 | 구성 효과만 -4.5%p(5.2절). 보정 없이는 방식 구성만 바뀌어도 경고가 난다 | 높음 |
| A3 | 직찰·우편·상시 등 비전자 방식을 대형 매칭률 표본에서 분리하거나 별도 지표로 둔다 | 직찰은 2026-03 이후 3~8%로 구조적 미수집(5.3절). 08-24 주 0/21 이 전체를 끌어내린다 | 중간 |
| A4 | `NOTICE_LOOKBACK_DAYS=365` 로 제외되는 장기 재공고를 검토한다. 08-24 주에 12건(모두 미매칭 직찰)이 제외되어 분모가 466 → 454 로 줄었다 | 미제외 시 매칭률 52.1%, 제외 시 53.5%(Q4 vs Q12) | 낮음 |
| A5 | 성숙 기간은 28일 유지가 타당하다. 다만 30일 초과 꼬리가 코호트에 따라 1~6% 있으므로 보조 판정으로 35일 성숙을 함께 본다 | 6.2~6.4절. 28일 시점 후 추가 도착이 08-03 주 18건까지 관측됐다 | 중간 |
| A6 | 2주 연속 임계 초과 시에만 경고하는 조건을 검토한다 | 물품은 08-10~08-24 3주 연속 초과(4.1절)로 이미 지속성이 확인된다. 단일 주 노이즈를 줄인다 | 중간 |
| A7 | 차수(`bid_ntce_ord`) 정규화 보강: 공고 `000` ↔ 결과 `001`/`002` 불일치 8건을 조인 규칙으로 흡수할지 검토한다 | 5.4절, Q9. 다만 정본 매칭 정의를 바꾸는 일이므로 별도 승인 필요 | 낮음 |
| A8 | 상류 확인은 별도 트랙으로 둔다. 조달청 API 직접 조회가 금지된 계약이므로, 나라장터 화면과 표본 공고를 대조해 미반영/미등록을 가르는 후속 조사가 필요하다 | 9절 한계 | 중간 |

---

## 9. 불확실성과 한계

1. **상류 직접 확인 불가.** 조달청 API 직접 조회가 계약상 금지되어, "API 에 없다"와 "우리 창이 놓쳤다"를 DB 만으로 완전히 분리하지 못했다. 다만 08-24 주의 등록 구간은 수집 실행이 덮었고(7.3절), 방식을 가리지 않는 동반 하락과 기관 분산(6.1절)이 수집기 결함 쪽 가능성을 낮춘다.
2. **2025년 도착 곡선 비교 불가.** `bid_results.collected_at` 이 2026-03 백필 시각이라 2025년 코호트의 도착 지연을 복원할 수 없다. 전년 대비 도착 지연 악화 여부는 판정하지 못했고, 본 보고서의 도착 곡선은 2026-08 코호트에 한정한다.
3. **잔여 자연 지연.** 9/26 이후 등록분이 미반영이라 결손 35~47건은 상한이다. 시간이 더 지나면 일부 회수될 수 있다.
4. **표본 크기.** 08-24 주 전자시담 100건, 직찰 21건으로 작다. 방식별 소표본 변동이 경고 폭에 영향을 준다.
5. **구성 효과는 "손실 아님"이 아니라 "손실로 단정할 수 없음"이다.** 방식 구성 변화가 실제 조달 관행 변화인지 수집 범위 차이인지는 확인하지 못했다.

---

## 10. 재현 명령

모든 수치는 아래 명령으로 재현한다. Q1 만 스크립트이고 나머지는 읽기 전용 SQL 이다. 아래 SQL 은 `uv run python scripts/db_readonly_query.py --sql "<질의>"` 로 실행한다.

Q1. 주별 매칭률·경고:
```
uv run python scripts/result_match_rate_report.py --as-of 2026-09-28 --weeks 12 --format json
```

Q2. 08-24 주 미매칭 대형 경과일 분포:
```
SELECT DATE(a.openg_dt) AS openg_day, DATEDIFF('2026-09-28', DATE(a.openg_dt)) AS elapsed_days, COUNT(*) AS unmatched_large FROM bid_announcements a WHERE a.category = 'Thng' AND a.openg_dt >= '2026-08-24 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.bid_ntce_dt >= '2024-06-09 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' AND NOT EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) GROUP BY DATE(a.openg_dt), DATEDIFF('2026-09-28', DATE(a.openg_dt)) ORDER BY openg_day
```

Q3. 물품 대형 도착 지연 곡선(주별):
```
SELECT DATE_SUB(DATE(a.openg_dt), INTERVAL WEEKDAY(a.openg_dt) DAY) AS wk, CASE WHEN DATEDIFF(br.collected_at, a.openg_dt) <= 1 THEN 'A_0-1' WHEN DATEDIFF(br.collected_at, a.openg_dt) <= 5 THEN 'B_2-5' WHEN DATEDIFF(br.collected_at, a.openg_dt) <= 13 THEN 'C_6-13' WHEN DATEDIFF(br.collected_at, a.openg_dt) <= 30 THEN 'D_14-30' ELSE 'E_30+' END AS bucket, COUNT(DISTINCT br.id) AS n FROM bid_announcements a JOIN bid_results br ON br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) WHERE a.category = 'Thng' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.openg_dt >= '2026-08-03 00:00:00' AND a.openg_dt <= '2026-09-21 23:59:59.999999' GROUP BY wk, bucket ORDER BY wk, bucket
```

Q4. 08-24 주 방식별 매칭:
```
SELECT COALESCE(a.bid_methd_nm, '(null)') AS method, COUNT(*) AS ann, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS matched FROM bid_announcements a WHERE a.category = 'Thng' AND a.openg_dt >= '2026-08-24 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.bid_ntce_dt >= '2024-06-09 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999' GROUP BY method ORDER BY ann DESC
```

Q5. 2개년 8월 주별·방식별 매칭: Q4 와 같은 골격에서 `wk`(주 시작)를 추가하고 기간 조건을 `((a.openg_dt >= '2025-08-04' AND a.openg_dt <= '2025-08-31 23:59:59.999999') OR (a.openg_dt >= '2026-08-03' AND a.openg_dt <= '2026-08-30 23:59:59.999999'))` 로 바꾼다.

Q6. 월별·방식별 매칭 추이:
```
SELECT DATE_FORMAT(a.openg_dt, '%Y-%m') AS ym, a.bid_methd_nm AS method, COUNT(*) AS ann, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS matched FROM bid_announcements a WHERE a.category = 'Thng' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.openg_dt >= '2025-01-01 00:00:00' AND a.openg_dt <= '2026-08-31 23:59:59.999999' GROUP BY ym, method HAVING ann >= 20 ORDER BY ym, method
```

Q7. 낙찰결과 월별 수집 이력:
```
SELECT DATE_FORMAT(collected_at, '%Y-%m') AS ym, category, COUNT(*) AS n FROM bid_results WHERE collected_at >= '2025-06-01 00:00:00' AND collected_at <= '2026-09-28 23:59:59.999999' GROUP BY ym, category ORDER BY ym, category
```

Q8. 미매칭 대형 발주기관 분포: Q2 와 같은 조건에서 `GROUP BY` 를 `COALESCE(a.dminstt_nm,'(null)')` 로 바꾸고 `ORDER BY unmatched DESC LIMIT 15`.

Q9. 동일 공고번호 결과 존재 미매칭 상세:
```
SELECT a.bid_ntce_no, a.bid_ntce_ord AS ann_ord, a.bid_methd_nm, br.category AS res_cat, br.bid_ntce_ord AS res_ord FROM bid_announcements a JOIN bid_results br ON br.bid_ntce_no = a.bid_ntce_no WHERE a.category = 'Thng' AND a.openg_dt >= '2026-08-24 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.bid_ntce_dt >= '2024-06-09 00:00:00' AND NOT EXISTS (SELECT 1 FROM bid_results br2 WHERE br2.bid_ntce_no = a.bid_ntce_no AND br2.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br2.bid_ntce_ord)), ''), '0')), 3)) LIMIT 50
```

Q10. 성숙도별 누적 매칭:
```
SELECT DATE_SUB(DATE(a.openg_dt), INTERVAL WEEKDAY(a.openg_dt) DAY) AS wk, COUNT(*) AS ann, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) AND br.collected_at <= DATE_ADD(a.openg_dt, INTERVAL 7 DAY)) THEN 1 ELSE 0 END) AS m7, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) AND br.collected_at <= DATE_ADD(a.openg_dt, INTERVAL 14 DAY)) THEN 1 ELSE 0 END) AS m14, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) AND br.collected_at <= DATE_ADD(a.openg_dt, INTERVAL 21 DAY)) THEN 1 ELSE 0 END) AS m21, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) AND br.collected_at <= DATE_ADD(a.openg_dt, INTERVAL 28 DAY)) THEN 1 ELSE 0 END) AS m28, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3) AND br.collected_at <= DATE_ADD(a.openg_dt, INTERVAL 35 DAY)) THEN 1 ELSE 0 END) AS m35 FROM bid_announcements a WHERE a.category = 'Thng' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.openg_dt >= '2026-06-01 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' GROUP BY wk ORDER BY wk
```

Q11. 2026-08 방식·주별 도착 곡선: Q3 와 같은 골격에서 `a.bid_methd_nm IN ('전자입찰','전자시담')` 조건을 추가하고 `wk` 를 `SELECT`·`GROUP BY` 에 넣는다.

Q12. 08-24 주 대형 총계·매칭 교차검증:
```
SELECT COUNT(*) AS total_large, SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_results br WHERE br.bid_ntce_no = a.bid_ntce_no AND br.category = a.category AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3) = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(br.bid_ntce_ord)), ''), '0')), 3)) THEN 1 ELSE 0 END) AS matched FROM bid_announcements a WHERE a.category = 'Thng' AND a.openg_dt >= '2026-08-24 00:00:00' AND a.openg_dt <= '2026-08-30 23:59:59.999999' AND a.presmpt_prce >= 230000000 AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고') AND a.bid_ntce_dt >= '2024-06-09 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59.999999'
```

Q13. 수집 실행 이력(참고): `pipeline_executions` 조회 및 `bid_results.collected_at` 일별 분포는 2026-09-26 분석 4.5절과 동일한 골격을 쓴다.

---

## 11. 참고 문서

- `result_collection_gap_20260926.md`: 용역 상류 공백 원인 분석. 본 보고서의 선행 조사이며 수집 창 클램프 리스크를 다룬다.
- `../context/CURRENT_STATE.md`: 수집 파이프라인 운영 정본.
- `../../src/app/services/result_coverage.py`: 매칭률·경고 계산 정본.
- `../../scripts/result_match_rate_report.py`, `../../scripts/db_readonly_query.py`: 재현 도구.
