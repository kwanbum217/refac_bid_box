# 2026-10-14~10-24 개찰 복수예가 용역 공고 낙찰결과 미보유 696건 원인 분석 (2026-11-17)

> **작성일**: 2026-11-17
> **상태**: 분석 완료 (코드·설정·DB·스키마 변경 없음)
> **범위**: 개찰일 2026-10-14~2026-10-24, 업무구분 Servc, 예비가격 결정방법 복수예가 공고 2,308건 중 `bid_results` 미보유 696건의 정상/누락 판정과 원인 후보, 재수집 방법
> **정본 모듈**: `src/app/services/collector_service.py`(`resolve_collection_window`, `MAX_CATCHUP_DAYS`), `src/app/services/api_collector.py`(`getScsbidListSttus*`, `getOpengResultListInfo*`)
> **질의 방법**: `uv run python scripts/db_readonly_query.py --sql "<질의>"` (읽기 전용, SELECT 단일 문장)
> **계약 준수**: 조달청 API 직접 조회 없음. 운영 DB 쓰기 없음. `docker exec`·`mysql` 직접 호출 없음. `raw_data` 전 테이블 LIKE 스캔 없음. 코드 수정 없음. 산출물은 본 문서 1건.

---

## 1. 요약 (결론)

1. **모집단과 결과 없음 수를 재현했다.** 개찰일 2026-10-14~10-24, Servc, `raw_data.prearngPrceDcsnMthdNm = '복수예가'` 공고번호는 **2,308건**이고, 같은 공고번호의 `bid_results` 행이 없는 공고는 **696건(30.2%)** 이다(질의 Q1, Q2). 코디네이터가 제시한 두 수와 정확히 일치한다.

2. **696건 중 464건(66.7%)은 결과가 없는 것이 정상이다.** 유찰 247건, 재입찰 4건, 개찰결과 없음이면서 취소공고가 있는 205건, 개찰완료이면서 취소공고가 있는 8건이다. 취소공고가 있는 공고 217건 중 낙찰결과가 있는 것은 1건뿐이므로 취소와 미보유의 관계가 일관된다(질의 Q3, Q9).

3. **나머지 232건(33.3%)이 누락 후보다.** `개찰완료`인데 낙찰결과가 없는 161건과, 개찰결과 자체가 없고 취소공고도 없는 71건이다. 이 두 집합이 이번 조사의 핵심이다(질의 Q3).

4. **이 기간의 수집 누락 징후는 발견되지 않았다.** 같은 조건의 기준 기간 두 곳에서도 누락 후보 비율이 **9.6~10.0%**(비취소 공고 대비)였고 이 기간은 **11.1%** 로, 차이는 늦은 도착 잔여분(개찰 후 24일 이후 도착 36행)으로 대부분 설명된다. 일자별 미보유율도 22.6~37.0% 로 특정 일자만 튀지 않는다. 차수 불일치와 카테고리 불일치는 각각 0건이다(질의 Q10~Q14, Q16, Q18).

5. **결론: 정상으로 설명되는 비율 66.7%(464/696), 수집 누락 추정 0건.** 누락 후보 232건은 "낙찰자가 없거나 원천에 공표되지 않은 개찰완료" 및 "개찰결과 API 미공표(PQ·기술평가형)" 로 판단한다. 다만 단건 API 확인 전이므로 **누락 상한은 232건(33.3%)** 으로 둔다. 확인용 공고번호 10건은 9장에 있다.

6. **재수집이 필요하면 8장의 두 스크립트를 쓴다.** 개찰결과는 `scripts/backfill_openg_results.py`, 낙찰결과는 `scripts/backfill_from_g2b.py --fetch-type result` 다. 후자는 조회 축이 개찰일이 아니라 **등록일**이므로 `--since` 를 개찰 시작일, `--until` 을 오늘로 잡아야 늦게 등록된 결과까지 회수한다.

---

## 2. 조사 범위와 계약

### 2.1 모집단 정의

| 항목 | 정의 |
| --- | --- |
| 공고 행 | `bid_announcements.category = 'Servc'` |
| 개찰일 | `openg_dt` 가 2026-10-14 00:00:00 이상, 2026-10-24 23:59:59 이하 |
| 예비가격 방식 | `JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.prearngPrceDcsnMthdNm')) = '복수예가'` |
| 모집단 단위 | 공고번호(`bid_ntce_no`) 단위 DISTINCT |
| 결과 없음 | 위 공고번호와 같은 `bid_ntce_no` 를 가진 `bid_results` 행이 0건 |

`bid_results` 매칭은 공고번호만 본다. 차수·카테고리는 이 Task 의 정의에 포함하지 않는다. 차수·카테고리 효과는 5.2·5.3절에서 별도로 검증했다.

### 2.2 방법과 제약

| 항목 | 내용 |
| --- | --- |
| DB 조회 | `uv run python scripts/db_readonly_query.py --sql "<질의>"` 만 사용. 한 번에 한 문장, 날짜 범위로 좁힘, `IN` 목록 50건 이하 |
| API | 직접 호출하지 않음(워커 환경에 키 없음). 단건 확인용 공고번호만 9장에 남김 |
| 운영 자원 | Docker·Redis·운영 쓰기 없음. 서비스 모듈을 `python -c` 로 호출하지 않음 |
| 코드 | 수정하지 않음. 원인 판정에 필요한 코드 구간만 읽음 |
| 산출물 | 본 문서 1건 |

---

## 3. 모집단과 결과 없음 재현

### 3.1 모집단 (질의 Q1)

개찰일 범위의 Servc 공고는 4,672행이었고, 예비가격 결정방법별 분포는 다음과 같다.

| 예비가격 결정방법 | 공고 행 | 공고번호 | 모집단 |
| --- | ---: | ---: | :---: |
| 복수예가 | 2,645 | **2,308** | 대상 |
| 비예가 | 1,263 | 1,118 | 제외 |
| 단일예가 | 764 | 735 | 제외 |

모집단 2,308건은 코디네이터 제시값과 일치한다.

### 3.2 결과 없음 (질의 Q2)

| 구분 | 공고번호 |
| --- | ---: |
| 모집단 | 2,308 |
| `bid_results` 보유 | 1,612 |
| `bid_results` 미보유 | **696 (30.2%)** |

696건도 제시값과 일치한다.

---

## 4. 분류

### 4.1 최신 개찰행 판정 규칙

`bid_openg_results` 는 공고번호당 최대 3행이었다(696건 중 393건이 1행, 질의 Q24). 여러 행이 있으면 아래 순서로 1행을 골라 상태를 판정했다.

```
ROW_NUMBER() OVER (
  PARTITION BY bid_ntce_no
  ORDER BY last_seen_at DESC, rbid_no DESC
)
```

`rbid_no` 우선(`CAST(rbid_no AS UNSIGNED) DESC, last_seen_at DESC`)으로 바꿔도 분류 결과는 **276/247/169/4 로 동일**했다(질의 Q3 의 정렬 키만 교체). 즉 판정 키 민감도는 없다.

`취소공고` 판정은 대표 행의 `ntce_kind_nm` 만 보지 않고, 같은 공고번호의 **임의 차수에 취소공고 행이 있는지**(`any_cancel`)로 넓게 잡았다. 대표 행의 공고종류만 보는 좁은 기준으로도 취소 분해가 205/8/3 으로 같다(질의 Q25).

### 4.2 상태별 결과 보유 (질의 Q5)

| 최신 개찰 상태 | 모집단 | 결과 있음 | 결과 없음 | 결과 보유율 |
| --- | ---: | ---: | ---: | ---: |
| 개찰완료 | 1,779 | 1,610 | 169 | 90.5% |
| 개찰결과 없음 | 278 | 2 | 276 | 0.7% |
| 유찰 | 247 | 0 | 247 | 0.0% |
| 재입찰 | 4 | 0 | 4 | 0.0% |
| **합계** | **2,308** | **1,612** | **696** | **69.8%** |

`개찰결과 없음` 278건 중 2건은 낙찰결과가 있다. 개찰결과 적재가 반대로 빠진 사례이며, 공고번호는 `R26BK01759839`, `R26BK01764747` 이다. 규모는 작지만 개찰결과 백필에 구멍이 있음을 보여준다.

### 4.3 분류 표 (질의 Q3)

| 분류 | 건수 | 비율 | 판정 |
| --- | ---: | ---: | --- |
| 개찰결과 없음 · 취소공고 있음 | 205 | 29.5% | 정상 (사업 취소) |
| 개찰결과 없음 · 취소공고 없음 | 71 | 10.2% | 누락 후보 |
| 유찰 | 247 | 35.5% | 정상 (낙찰자 없음) |
| 재입찰 | 4 | 0.6% | 정상 (재입찰 진행) |
| 개찰완료 · 취소공고 있음 | 8 | 1.1% | 정상 (개찰 후 취소) |
| 개찰완료 · 취소공고 없음 | 161 | 23.1% | 누락 후보 |
| **합계** | **696** | **100.0%** | |

- 정상 확정: **464건 (66.7%)**
- 누락 후보: **232건 (33.3%)**

재입찰 4건 중 3건은 취소공고 행이 함께 있어 "재입찰" 행에 포함했다. 표의 행은 상호 배타적이므로 합계가 696과 일치한다.

### 4.4 취소공고와 결과 보유의 관계 (질의 Q4, Q9)

| 취소공고 행 보유 | 공고번호 | 결과 있음 | 결과 없음 |
| --- | ---: | ---: | ---: |
| 있음 | 217 | 1 | 216 |
| 없음 | 2,091 | 1,611 | 480 |

취소공고가 있는 공고는 99.5%가 결과가 없다. 이는 "취소 = 결과 없음"이 정상임을 직접 보여준다. 반대로 비취소 2,091건의 결과 없음 480건 중 유찰·재입찰 248건을 빼면 **232건**이 남아 4.3절의 누락 후보와 일치한다.

---

## 5. 누락 후보 232건의 원인 후보

### 5.1 수집 일자 공백 (기각)

| 확인 | 결과 | 판정 |
| --- | --- | --- |
| 개찰일 기준 일별 결과 행수(10-12~10-27) | 평일 237~433행, 주말 1~7행 | 정상. 특정 평일 공백 없음 (질의 Q7) |
| 적재일(`collected_at`) 기준 건수 | 10-15 1,087, 10-24 661, 10-28 676 등 큰 회수 실행 존재. 0행인 날은 "새 행 없음"이며 실행 부재 증거가 아님 (질의 Q8) | 공백 징후 없음 |
| 적재일 간격 | 최장은 10-11 이후 10-15(4일). 그 밖의 간격은 1~2일 | 모두 `MAX_CATCHUP_DAYS=7` 이내 (질의 Q8) |
| 대상 기간 결과의 실제 도착 | 11-04 317행, 11-10 40행, 11-13 33행, 11-17 4행까지 계속 도착 (질의 Q15) | 수집기가 계속 재조회 중 |

10월 실행 이력은 `schedule_run_log` 로 확인할 수 없다. 이 테이블의 최초 기록이 2026-11-11 이기 때문이다(질의 Q22). 따라서 "실행 자체가 없었다"는 반증은 `collected_at` 연속성과 일별 개찰일 분포로 대신했다. 최장 적재일 간격이 4일이고 다음 실행이 누적분을 회수했으므로 클램프 구멍은 없다.

### 5.2 차수 불일치 (기각)

- 결과 보유 1,612건 중 결과 차수가 공고 차수와 하나도 맞지 않는 공고는 **0건**이다(질의 Q18).
- 모집단 2,308건 중 공고 차수가 2개 이상인 공고는 295건, 개찰일이 2개 이상인 공고는 21건이다. 대표 행은 범위 내 최대 차수로 골랐고, 일별 표 합계는 2,308로 유지된다(질의 Q6).
- 공고번호 단위로 매칭하므로 차수 불일치는 누락을 만들 수 없다. 기각.

### 5.3 카테고리 분류 (기각)

- 결과 보유 1,612건 중 `Servc` 가 아닌 카테고리에만 결과가 있는 공고는 **0건**이다(질의 Q18).
- 공고번호 단위 매칭이므로 카테고리 표기가 달라도 결과가 있으면 보유로 계산된다. 카테고리 분류는 696건의 원인이 될 수 없다. 기각.

### 5.4 원천 미공표·지연 (주원인)

낙찰정보 API(`getScsbidListSttus*`)는 **낙찰자가 있는 건만** 반환한다. 코드 주석이 이를 명시한다.

```text
src/app/services/api_collector.py:702-704
낙찰현황(getScsbidListSttus*)은 낙찰자가 있는 건만 내려주므로 유찰을 담지 못합니다.
```

따라서 `개찰완료` 는 "개찰이 끝났다"는 뜻이지 "낙찰자가 정해졌다"는 뜻이 아니다. 개찰 후 무효·부적격·예정가격 초과로 낙찰자가 없으면 `bid_results` 에 행이 생기지 않는 것이 정상이다. 다음 사실이 이 해석을 뒷받침한다.

| 근거 | 값 | 질의 |
| --- | --- | --- |
| 개찰완료 미보유 169건의 참가업체 수 | 169건 모두 0명 초과, 평균 54.63명, 최대 880명 | Q20 |
| 결과 보유 개찰완료의 참가업체 수 | 1,610건 평균 42.44명, 최대 1,182명 | Q20 |
| 계약방법별 개찰완료 미보유율(비취소) | 수의계약 4.5%, 제한경쟁 10.5%, 일반경쟁 22.6%, 지명경쟁 40.3% | Q13 |
| 기준 기간 같은 표(2026-10-01~10-11) | 수의계약 6.7%, 제한경쟁 7.6%, 일반경쟁 23.1%, 지명경쟁 35.3% | Q14 |

계약방법별 미보유율의 모양이 이 기간과 기준 기간에서 거의 같다. 경쟁이 강한 일반·지명에서 미보유가 높은 것은 "낙찰자 없음" 성격이 구조적임을 뜻한다.

### 5.5 개찰결과 자체가 없는 71건 (보조 원인)

| 확인 | 값 | 질의 |
| --- | --- | --- |
| 71건의 공고명 키워드 | 사업수행능력·건설사업관리·평가·PQ 중 하나 포함 **44건** | Q19 |
| 계약방법 | 일반경쟁 50, 제한경쟁 20, 지명경쟁 1, 수의계약 0 | Q23 |
| 일자 분포 | 10-14 4, 10-15 11, 10-16 9, 10-19 7, 10-20 9, 10-21 10, 10-22 8, 10-23 12, 10-24 1 | Q19 |
| 개찰결과 테이블 적재 시작 | `collected_at` 최소 2026-11-04, 최대 2026-11-17 | Q21 |
| 반대 방향 구멍 | 결과는 있는데 개찰결과가 없는 공고 2건 | Q5 |

71건은 특정 일자에 몰리지 않고 평일마다 고르게 퍼져 있다. 44건이 PQ·기술평가·건설사업관리형 공고명이라, 가격개찰이 아닌 평가 단계이거나 개찰결과 API에 공표되지 않는 유형으로 보인다. 다만 `bid_openg_results` 자체가 2026-11-04 백필로 채워졌으므로, 백필 창 누락 가능성은 남는다. `scripts/backfill_openg_results.py` 의 `--ledger`(기본 `.cache/openg_backfill_ledger.json`)에 10-14~10-24 창이 `skipped` 로 남았는지 확인하는 것이 다음 단계다.

### 5.6 기간 비교 (핵심 근거)

같은 모집단 정의로 기간만 바꿔 비취소 공고 대비 누락 후보 비율을 계산했다(질의 Q10~Q12).

| 기간 | 비취소 공고 | 결과 있음 | 결과 없음 | 누락 후보 | 후보 비율 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-09-14~09-24 | 2,074 | 1,550 | 524 | 207 | **9.98%** |
| 2026-10-01~10-11 | 1,271 | 980 | 291 | 122 | **9.60%** |
| **2026-10-14~10-24** | **2,091** | **1,611** | **480** | **232** | **11.10%** |

이 기간이 1.1~1.5%p 높은 것은 대상 기간의 마지막 개찰일이 상대적으로 젊기 때문이다. 대상 기간 결과의 도착 지연은 다음과 같다.

| 개찰 후 경과 | 결과 행 | 비율 |
| --- | ---: | ---: |
| 0~1일 | 783 | 28.1% |
| 2~5일 | 858 | 30.7% |
| 6~13일 | 702 | 25.2% |
| 14~30일 | 443 | 15.9% |
| 31일 이상 | 5 | 0.2% |
| **합계** | **2,791** | **100.1% (개별 반올림 누적)** |

개찰 후 24일 이후 도착한 행은 36행(1.3%)이다(질의 Q17). 10-23·10-24 개찰분은 아직 24~25일 경과라 이 잔여분이 더 채워질 수 있다. 따라서 11.10%는 성숙 후 9.6~10.0% 대로 내려갈 여지가 있다. 기간 고유의 수집 결함을 뜻하지 않는다.

---

## 6. 일자별 낙찰 결과 적재 건수 (10-12~10-27)

### 6.1 적재일(`collected_at`) 기준 (질의 Q8)

`collected_at` 은 행이 실제로 삽입된 시각이다. `_bulk_insert` 는 `INSERT IGNORE` 를 쓰므로 중복 행은 갱신되지 않고, 새 행이 없는 실행은 이 표에 흔적을 남기지 않는다.

| 적재일 | Servc 결과 행 | 비고 |
| --- | ---: | --- |
| 2026-10-12 | 0 | 신규 행 없음 |
| 2026-10-13 | 0 | 신규 행 없음 |
| 2026-10-14 | 0 | 신규 행 없음 |
| 2026-10-15 | 1,087 | 10-12~10-15 누적 회수 성격 |
| 2026-10-16 | 0 | 신규 행 없음 |
| 2026-10-17 | 633 | 주말 |
| 2026-10-18 | 12 | 주말 |
| 2026-10-19 | 8 | 주말 직후 소량 |
| 2026-10-20 | 362 | |
| 2026-10-21 | 392 | |
| 2026-10-22 | 338 | |
| 2026-10-23 | 0 | 신규 행 없음 |
| 2026-10-24 | 661 | 주말 |
| 2026-10-25 | 0 | 주말, 신규 행 없음 |
| 2026-10-26 | 18 | 주말 직후 소량 |
| 2026-10-27 | 0 | 신규 행 없음 |

0행인 날은 실행 부재를 뜻하지 않는다. 10-15와 10-24의 큰 적재는 직전 공백을 회수한 실행으로 보인다. 직전 적재일은 10-11(11행)이고 10-12~10-14가 0행이므로 최장 간격은 4일이며 `MAX_CATCHUP_DAYS=7` 이내다. 10-10은 0행이다(질의 Q8, 범위를 10-10부터로 넓혀 확인).

### 6.2 개찰일(`rl_openg_dt`) 기준 (질의 Q7)

| 개찰일 | Servc 결과 행 | 결과 공고 | 비고 |
| --- | ---: | ---: | --- |
| 2026-10-12 | 303 | 303 | |
| 2026-10-13 | 415 | 415 | |
| 2026-10-14 | 393 | 393 | |
| 2026-10-15 | 322 | 322 | |
| 2026-10-16 | 331 | 331 | |
| 2026-10-17 | 7 | 7 | 주말 |
| 2026-10-18 | 5 | 5 | 주말 |
| 2026-10-19 | 329 | 329 | |
| 2026-10-20 | 433 | 433 | |
| 2026-10-21 | 334 | 334 | |
| 2026-10-22 | 327 | 327 | |
| 2026-10-23 | 305 | 305 | |
| 2026-10-24 | 5 | 5 | 주말 |
| 2026-10-25 | 1 | 1 | 주말 |
| 2026-10-26 | 237 | 237 | |
| 2026-10-27 | 341 | 341 | |

평일 237~433행으로 안정적이고, 주말만 1~7행이다. 적재 누락이 특정 일자에 집중된 모습은 없다.

### 6.3 대상 기간 공고의 일별 미보유율 (질의 Q6)

공고번호 단위 대표 행(범위 내 최대 차수) 기준이다. 합계가 2,308·696과 일치한다.

| 개찰일 | 모집단 | 결과 없음 | 미보유율 |
| --- | ---: | ---: | ---: |
| 2026-10-14 | 315 | 95 | 30.2% |
| 2026-10-15 | 247 | 86 | 34.8% |
| 2026-10-16 | 292 | 66 | 22.6% |
| 2026-10-19 | 245 | 84 | 34.3% |
| 2026-10-20 | 349 | 86 | 24.6% |
| 2026-10-21 | 303 | 112 | 37.0% |
| 2026-10-22 | 287 | 87 | 30.3% |
| 2026-10-23 | 269 | 79 | 29.4% |
| 2026-10-24 | 1 | 1 | 100.0% |
| **합계** | **2,308** | **696** | **30.2%** |

10-24는 1건뿐이라 100%는 표본 착시다. 나머지 날짜는 22.6~37.0% 범위에 있고 추세나 급변은 없다.

---

## 7. 결론

| 항목 | 값 |
| --- | ---: |
| 결과 없음 | 696 |
| 정상으로 설명됨 | **464 (66.7%)** |
| 누락 후보 | **232 (33.3%)** |
| 수집 누락 추정 | **0건** |
| 누락 상한(단건 확인 전) | 232건 (33.3%) |

판정 근거는 다음과 같다.

1. 취소공고가 있는 217건 중 216건이 결과 없음이므로 취소는 결과 없음의 정상 사유다. 유찰 247건은 낙찰자가 없고, 재입찰 4건은 재입찰 진행 상태다. 표의 상호 배타 행 기준으로 정상은 464건이다.
2. 남은 232건 중 161건(개찰완료)과 71건(개찰결과 없음)의 비율은 같은 조건의 기준 기간(9.6~10.0%)과 크게 다르지 않다. 이 기간만의 수집 중단이나 클램프 구멍은 없다.
3. 일별 미보유율이 평평하고, 차수·카테고리 불일치가 0건이며, 결과가 지금도 계속 도착한다.
4. 따라서 232건은 "원천에 낙찰 결과가 없거나 늦게 공표되는 건"으로 보는 것이 타당하다. 다만 API 단건 확인 전이므로 0건이라고 단정하지 않고 상한 232건을 함께 둔다.

---

## 8. 재수집 방법

코드는 고치지 않고, 저장소에 실재하는 스크립트와 확인한 옵션만 적는다.

### 8.1 개찰결과(`bid_openg_results`) 보강 — 71건 대상

개찰결과 API는 개찰일시 축(`inqryDiv=3`)을 쓴다. 먼저 dry-run 으로 창과 호출 수를 확인한다.

```bash
uv run python scripts/backfill_openg_results.py \
  --start 20261014 --end 20261024 --categories Servc \
  --max-calls 40 --dry-run
```

문제가 없으면 `--dry-run` 을 `--execute` 로 바꾼다. `--max-calls` 는 필수 옵션이고, `--ledger` 기본값은 `.cache/openg_backfill_ledger.json` 이다. 실행 전에 기존 원장에서 10-14~10-24 창이 `skipped` 로 남았는지 확인한다.

### 8.2 낙찰결과(`bid_results`) 보강 — 161건 대상

낙찰정보 API는 조회 축이 개찰일이 아니라 **등록일**이다(`inqryDiv=1`). 따라서 `--since` 를 개찰 시작일, `--until` 을 오늘로 잡아야 개찰 후 늦게 등록된 결과까지 회수된다. 먼저 dry-run 으로 구간을 확인한다.

```bash
uv run python scripts/backfill_from_g2b.py \
  --category Servc --since 20261014 --until 20261117 \
  --fetch-type result --dry-run
```

실행 시 `--dry-run` 을 빼고, 새 행이 실제로 들어간 경우에만 `--sync-downstream` 을 붙여 파생 집계·KB 색인·검색 색인 동기화를 수행한다. 적재는 `INSERT IGNORE` 라 재실행이 멱등이다.

### 8.3 재수집 후 검증

```bash
uv run python scripts/result_match_rate_report.py \
  --as-of 2026-11-17 --weeks 8 --late-window-days 7
```

읽기 전용 매칭률 보고서다. 재수집 전후 비취소 공고 누락 후보 비율이 9.6~10.0% 대로 돌아오는지 확인한다. 이 보고서의 수치는 본 문서 5.6절과 같은 정의(공고번호 단위 매칭)가 아니므로 방향과 자릿수만 대조한다.

---

## 9. 코디네이터 확인용 공고번호 10건

단건 API 확인이 필요한 공고다. 10건 모두 `bid_results` 0행을 재확인했다(질의 Q26).

| # | 공고번호 | 개찰일 | 차수 | 공고종류 | 최신 개찰상태 | 참가업체 | 결과 행 |
| --: | --- | --- | --- | --- | --- | ---: | ---: |
| 1 | R26BK01725476 | 2026-10-14 | 000 | 등록공고 | 개찰완료 | 69 | 0 |
| 2 | R26BK01727678 | 2026-10-14 | 000 | 등록공고 | 개찰완료 | 50 | 0 |
| 3 | R26BK01755636 | 2026-10-14 | 000 | 등록공고 | 개찰완료 | 29 | 0 |
| 4 | R26BK01756086 | 2026-10-14 | 000 | 등록공고 | 개찰완료 | 2 | 0 |
| 5 | R26BK01757194 | 2026-10-14 | 000 | 등록공고 | 개찰완료 | 11 | 0 |
| 6 | R26BK01758623 | 2026-10-14 | 000 | 재공고 | 개찰결과 없음 | - | 0 |
| 7 | R26BK01729957 | 2026-10-15 | 000 | 등록공고 | 개찰결과 없음 | - | 0 |
| 8 | R26BK01753535 | 2026-10-15 | 000 | 재공고 | 개찰결과 없음 | - | 0 |
| 9 | R26BK01753546 | 2026-10-15 | 000 | 재공고 | 개찰결과 없음 | - | 0 |
| 10 | R26BK01741729 | 2026-10-14 | 000 | 등록공고 | 개찰결과 없음 | - | 0 |

1~5는 "개찰완료인데 낙찰결과 없음" 표본이고, 6~10은 "개찰결과 자체 없음" 표본이다. 10번은 공고명에 `P.Q` 가 포함된 평가형 공고다. 단건 조회에서 낙찰자가 확인되면 해당 건수만큼 수집 누락으로 확정한다.

---

## 10. 한계와 후속 확인

1. **10월 실행 이력 부재.** `schedule_run_log` 는 2026-11-11 이후만 있다. 10월 수집 실행 여부는 `collected_at` 연속성으로만 추정했다.
2. **개찰결과 백필 원장 미확인.** `bid_openg_results` 는 2026-11-04~11-17 사이에 적재됐다. `scripts/backfill_openg_results.py --ledger` 의 10-14~10-24 `skipped` 여부를 확인해야 71건의 원인이 확정된다.
3. **API 단건 미확인.** 계약상 API 를 직접 호출하지 않았다. 9장 10건의 단건 확인 전까지 누락 상한 232건을 유지한다.
4. **성숙도.** 10-23·10-24 개찰분은 24~25일 경과다. 개찰 후 24일 이후 도착분이 36행 있어 후보 232건은 소폭 줄 수 있다.
5. **수의계약 공표 정책.** 수의계약 51건은 낙찰현황 API 공표 대상 여부를 코드·문서만으로 확정하지 못했다. 계약방법별 기준선(5.4절)이 같으므로 구조적 성격으로 판단했다.

---

## 11. 재현 질의

모든 질의는 아래 형태로 실행한다.

```bash
uv run python scripts/db_readonly_query.py --format table --sql "<질의>"
```

**Q1. 모집단과 예비가격 방식 분포 (3.1절)**
```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.prearngPrceDcsnMthdNm')) AS mthd,
       COUNT(*) AS row_cnt, COUNT(DISTINCT bid_ntce_no) AS notice_cnt
FROM bid_announcements
WHERE category='Servc'
  AND openg_dt >= '2026-10-14 00:00:00' AND openg_dt <= '2026-10-24 23:59:59'
GROUP BY mthd ORDER BY row_cnt DESC
```

**Q2. 결과 없음 696건 (3.2절)**
```sql
SELECT COUNT(*) AS missing_cnt
FROM (SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
      WHERE a.category='Servc'
        AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
        AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가') p
LEFT JOIN bid_results r ON r.bid_ntce_no = p.bid_ntce_no
WHERE r.id IS NULL
```

**Q3. 최신 개찰행 분류 (4.1·4.3절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), missing AS (
  SELECT p.bid_ntce_no FROM pop p
  LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no WHERE r.id IS NULL
), canc AS (
  SELECT a.bid_ntce_no,
         MAX(CASE WHEN a.ntce_kind_nm='취소공고' THEN 1 ELSE 0 END) AS any_cancel
  FROM bid_announcements a JOIN missing m ON m.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc' GROUP BY a.bid_ntce_no
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN missing m ON m.bid_ntce_no=o.bid_ntce_no
)
SELECT CASE WHEN l.progrs_div_cd_nm IS NULL THEN '1_none'
            WHEN l.progrs_div_cd_nm='유찰' THEN '2_fail'
            WHEN l.progrs_div_cd_nm='재입찰' THEN '3_rebid'
            ELSE '4_done' END AS grp,
       canc.any_cancel AS has_cancel,
       COUNT(*) AS cnt, ROUND(100*COUNT(*)/696,1) AS pct
FROM missing m JOIN canc ON canc.bid_ntce_no=m.bid_ntce_no
LEFT JOIN last l ON l.bid_ntce_no=m.bid_ntce_no AND l.rn=1
GROUP BY grp, has_cancel ORDER BY grp, has_cancel
```

**Q4. 취소공고 보유별 결과 보유 (4.4절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), canc AS (
  SELECT a.bid_ntce_no,
         MAX(CASE WHEN a.ntce_kind_nm='취소공고' THEN 1 ELSE 0 END) AS any_cancel
  FROM bid_announcements a JOIN pop p ON p.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc' GROUP BY a.bid_ntce_no
)
SELECT canc.any_cancel, COUNT(*) AS total,
       SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
       SUM(CASE WHEN r.id IS NULL THEN 1 ELSE 0 END) AS missing
FROM canc LEFT JOIN bid_results r ON r.bid_ntce_no=canc.bid_ntce_no
GROUP BY canc.any_cancel
```

**Q5. 최신 개찰상태별 결과 보유 (4.2절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN pop p ON p.bid_ntce_no=o.bid_ntce_no
), matched AS (
  SELECT p.bid_ntce_no, MAX(CASE WHEN r.id IS NULL THEN 0 ELSE 1 END) AS has_result
  FROM pop p LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no
  GROUP BY p.bid_ntce_no
)
SELECT COALESCE(l.progrs_div_cd_nm,'(none)') AS status,
       COUNT(*) AS total, SUM(mt.has_result) AS matched,
       SUM(1-mt.has_result) AS missing,
       ROUND(100*SUM(mt.has_result)/COUNT(*),1) AS matched_pct
FROM pop p JOIN matched mt ON mt.bid_ntce_no=p.bid_ntce_no
LEFT JOIN last l ON l.bid_ntce_no=p.bid_ntce_no AND l.rn=1
GROUP BY status ORDER BY total DESC
```

**Q6. 공고번호 대표 행 기준 일별 미보유율 (6.3절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), ann AS (
  SELECT a.bid_ntce_no, a.openg_dt,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN pop p ON p.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
), rep AS (SELECT an.bid_ntce_no, DATE(an.openg_dt) AS od FROM ann an WHERE an.rn=1)
SELECT rep.od AS openg_d, COUNT(*) AS total,
       SUM(CASE WHEN r.id IS NULL THEN 1 ELSE 0 END) AS missing,
       ROUND(100*SUM(CASE WHEN r.id IS NULL THEN 1 ELSE 0 END)/COUNT(*),1) AS missing_pct
FROM rep LEFT JOIN bid_results r ON r.bid_ntce_no=rep.bid_ntce_no
GROUP BY rep.od ORDER BY rep.od
```

**Q7. 개찰일 기준 일별 결과 행수 (6.2절)**
```sql
SELECT DATE(rl_openg_dt) AS d, COUNT(*) AS rows_cnt,
       COUNT(DISTINCT bid_ntce_no) AS notice_cnt
FROM bid_results
WHERE category='Servc'
  AND rl_openg_dt >= '2026-10-12 00:00:00' AND rl_openg_dt < '2026-10-28 00:00:00'
GROUP BY d ORDER BY d
```

**Q8. 적재일 기준 일별 결과 행수 (6.1절)**
```sql
SELECT DATE(collected_at) AS d, COUNT(*) AS rows_cnt
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-10-10 00:00:00' AND collected_at < '2026-10-28 00:00:00'
GROUP BY d ORDER BY d
```

**Q9. 취소공고 보유 공고 수 (4.4절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
)
SELECT COUNT(*) AS total,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM bid_announcements c
                             WHERE c.bid_ntce_no=p.bid_ntce_no AND c.category='Servc'
                               AND c.ntce_kind_nm='취소공고') THEN 1 ELSE 0 END) AS any_cancel
FROM pop p
```

**Q10. 기준 기간 2026-09-14~09-24 비취소 누락 후보 (5.6절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-09-14 00:00:00' AND a.openg_dt <= '2026-09-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), canc AS (
  SELECT a.bid_ntce_no,
         MAX(CASE WHEN a.ntce_kind_nm='취소공고' THEN 1 ELSE 0 END) AS any_cancel
  FROM bid_announcements a JOIN pop p ON p.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc' GROUP BY a.bid_ntce_no
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN pop p ON p.bid_ntce_no=o.bid_ntce_no
), matched AS (
  SELECT p.bid_ntce_no, MAX(CASE WHEN r.id IS NULL THEN 0 ELSE 1 END) AS has_result
  FROM pop p LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no
  GROUP BY p.bid_ntce_no
)
SELECT COUNT(*) AS noncancel_total, SUM(mt.has_result) AS matched,
       SUM(1-mt.has_result) AS missing,
       SUM(CASE WHEN mt.has_result=0
                 AND (l.progrs_div_cd_nm IS NULL OR l.progrs_div_cd_nm='개찰완료')
                THEN 1 ELSE 0 END) AS candidates
FROM canc c JOIN matched mt ON mt.bid_ntce_no=c.bid_ntce_no
LEFT JOIN last l ON l.bid_ntce_no=c.bid_ntce_no AND l.rn=1
WHERE c.any_cancel=0
```

**Q11. 기준 기간 2026-10-01~10-11 비취소 누락 후보 (5.6절)**: Q10 의 개찰일 범위를 `2026-10-01 00:00:00` ~ `2026-10-11 23:59:59` 로 바꾼다.

**Q12. 대상 기간 비취소 누락 후보 (5.6절)**: Q10 의 개찰일 범위를 `2026-10-14 00:00:00` ~ `2026-10-24 23:59:59` 로 바꾼다.

**Q13. 비취소 개찰완료의 계약방법별 미보유 (5.4·5.5절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), canc AS (
  SELECT a.bid_ntce_no,
         MAX(CASE WHEN a.ntce_kind_nm='취소공고' THEN 1 ELSE 0 END) AS any_cancel
  FROM bid_announcements a JOIN pop p ON p.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc' GROUP BY a.bid_ntce_no
), ann AS (
  SELECT a.bid_ntce_no, a.cntrct_mthd_nm,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN pop p ON p.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN pop p ON p.bid_ntce_no=o.bid_ntce_no
), matched AS (
  SELECT p.bid_ntce_no, MAX(CASE WHEN r.id IS NULL THEN 0 ELSE 1 END) AS has_result
  FROM pop p LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no
  GROUP BY p.bid_ntce_no
)
SELECT COALESCE(an.cntrct_mthd_nm,'(null)') AS contract,
       COUNT(*) AS total, SUM(mt.has_result) AS matched,
       SUM(1-mt.has_result) AS missing,
       ROUND(100*SUM(1-mt.has_result)/COUNT(*),1) AS missing_pct
FROM pop p
JOIN canc c ON c.bid_ntce_no=p.bid_ntce_no AND c.any_cancel=0
JOIN matched mt ON mt.bid_ntce_no=p.bid_ntce_no
JOIN last l ON l.bid_ntce_no=p.bid_ntce_no AND l.rn=1
LEFT JOIN ann an ON an.bid_ntce_no=p.bid_ntce_no AND an.rn=1
WHERE l.progrs_div_cd_nm='개찰완료'
GROUP BY contract ORDER BY total DESC
```

**Q14. 기준 기간 2026-10-01~10-11 계약방법별 미보유 (5.4절)**: Q13 의 개찰일 범위를 `2026-10-01 00:00:00` ~ `2026-10-11 23:59:59` 로 바꾼다.

**Q15. 대상 기간 결과의 적재일 분포 (5.1절)**
```sql
SELECT DATE(collected_at) AS d, COUNT(*) AS rows_cnt
FROM bid_results
WHERE category='Servc'
  AND rl_openg_dt >= '2026-10-14 00:00:00' AND rl_openg_dt <= '2026-10-24 23:59:59'
GROUP BY d ORDER BY d
```

**Q16. 결과 도착 지연 구간 (5.6절)**
```sql
SELECT CASE
         WHEN DATEDIFF(collected_at, rl_openg_dt) <= 1 THEN '0-1'
         WHEN DATEDIFF(collected_at, rl_openg_dt) <= 5 THEN '2-5'
         WHEN DATEDIFF(collected_at, rl_openg_dt) <= 13 THEN '6-13'
         WHEN DATEDIFF(collected_at, rl_openg_dt) <= 30 THEN '14-30'
         ELSE '31+'
       END AS bucket, COUNT(*) AS rows_cnt
FROM bid_results
WHERE category='Servc'
  AND rl_openg_dt >= '2026-10-14 00:00:00' AND rl_openg_dt <= '2026-10-24 23:59:59'
GROUP BY bucket
ORDER BY MIN(DATEDIFF(collected_at, rl_openg_dt))
```

**Q17. 24일 이후 도착 잔여 (5.6절)**
```sql
SELECT DATEDIFF(collected_at, rl_openg_dt) AS lag_days, COUNT(*) AS rows_cnt
FROM bid_results
WHERE category='Servc'
  AND rl_openg_dt >= '2026-10-14 00:00:00' AND rl_openg_dt <= '2026-10-24 23:59:59'
  AND DATEDIFF(collected_at, rl_openg_dt) >= 24
GROUP BY lag_days ORDER BY lag_days
```

**Q18. 차수·카테고리 불일치 (5.2·5.3절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), matched AS (
  SELECT DISTINCT p.bid_ntce_no FROM pop p
  JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no
)
SELECT COUNT(*) AS matched_notices,
       SUM(CASE WHEN NOT EXISTS (
             SELECT 1 FROM bid_results r
             JOIN bid_announcements a
               ON a.bid_ntce_no=r.bid_ntce_no AND a.category='Servc'
              AND RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(a.bid_ntce_ord)), ''), '0')), 3)
                = RIGHT(CONCAT('000', COALESCE(NULLIF(TRIM(LEADING '0' FROM TRIM(r.bid_ntce_ord)), ''), '0')), 3)
             WHERE r.bid_ntce_no=m.bid_ntce_no) THEN 1 ELSE 0 END) AS ord_mismatch_notices,
       SUM(CASE WHEN NOT EXISTS (
             SELECT 1 FROM bid_results r
             WHERE r.bid_ntce_no=m.bid_ntce_no AND r.category='Servc') THEN 1 ELSE 0 END) AS only_other_category
FROM matched m
```

**Q19. 71건 키워드·일자 분포 (5.5절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), missing AS (
  SELECT p.bid_ntce_no FROM pop p
  LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no WHERE r.id IS NULL
), ann AS (
  SELECT a.bid_ntce_no, a.bid_ntce_nm, a.ntce_kind_nm, a.openg_dt,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN missing m ON m.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
)
SELECT DATE(an.openg_dt) AS openg_d, COUNT(*) AS total,
       SUM(CASE WHEN an.bid_ntce_nm LIKE '%사업수행능%'
                  OR an.bid_ntce_nm LIKE '%건설사업관리%'
                  OR an.bid_ntce_nm LIKE '%평가%'
                  OR an.bid_ntce_nm LIKE '%P.Q%'
                  OR an.bid_ntce_nm LIKE '%PQ%' THEN 1 ELSE 0 END) AS pq_like
FROM missing m
JOIN ann an ON an.bid_ntce_no=m.bid_ntce_no AND an.rn=1
LEFT JOIN bid_openg_results o ON o.bid_ntce_no=m.bid_ntce_no
WHERE o.id IS NULL AND COALESCE(an.ntce_kind_nm,'') <> '취소공고'
GROUP BY DATE(an.openg_dt) ORDER BY DATE(an.openg_dt)
```

**Q20. 참가업체 수 (5.4절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm, o.prtcpt_cnum,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN pop p ON p.bid_ntce_no=o.bid_ntce_no
), matched AS (
  SELECT p.bid_ntce_no, MAX(CASE WHEN r.id IS NULL THEN 0 ELSE 1 END) AS has_result
  FROM pop p LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no
  GROUP BY p.bid_ntce_no
)
SELECT mt.has_result, COUNT(*) AS notices,
       SUM(CASE WHEN l.prtcpt_cnum=0 THEN 1 ELSE 0 END) AS zero_participants,
       ROUND(AVG(l.prtcpt_cnum),2) AS avg_participants,
       MAX(l.prtcpt_cnum) AS max_participants
FROM pop p JOIN matched mt ON mt.bid_ntce_no=p.bid_ntce_no
JOIN last l ON l.bid_ntce_no=p.bid_ntce_no AND l.rn=1
WHERE l.progrs_div_cd_nm='개찰완료'
GROUP BY mt.has_result
```

9장 10건은 아래 Q26 으로 재확인한다.

**Q21. 개찰결과 테이블 적재 범위 (5.5절)**
```sql
SELECT MIN(collected_at) AS min_c, MAX(collected_at) AS max_c, COUNT(*) AS rows_cnt
FROM bid_openg_results WHERE category='Servc'
```

**Q22. 스케줄 실행 이력 범위 (5.1절)**
```sql
SELECT schedule_name, COUNT(*) AS runs,
       MIN(DATE(started_at)) AS first_d, MAX(DATE(started_at)) AS last_d
FROM schedule_run_log GROUP BY schedule_name ORDER BY runs DESC
```

**Q23. 누락 후보 232건의 집단별 계약방법 (5.5절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), missing AS (
  SELECT p.bid_ntce_no FROM pop p
  LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no WHERE r.id IS NULL
), ann AS (
  SELECT a.bid_ntce_no, a.cntrct_mthd_nm, a.ntce_kind_nm,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN missing m ON m.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN missing m ON m.bid_ntce_no=o.bid_ntce_no
)
SELECT CASE WHEN l.progrs_div_cd_nm IS NULL THEN 'none' ELSE 'done' END AS grp,
       COALESCE(an.cntrct_mthd_nm,'(null)') AS contract, COUNT(*) AS cnt
FROM missing m
JOIN ann an ON an.bid_ntce_no=m.bid_ntce_no AND an.rn=1
LEFT JOIN last l ON l.bid_ntce_no=m.bid_ntce_no AND l.rn=1
WHERE (l.progrs_div_cd_nm IS NULL OR l.progrs_div_cd_nm='개찰완료')
  AND COALESCE(an.ntce_kind_nm,'') <> '취소공고'
GROUP BY grp, contract ORDER BY grp, cnt DESC
```

**Q24. 696건의 개찰결과 행수 분포 (4.1절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), missing AS (
  SELECT p.bid_ntce_no FROM pop p
  LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no WHERE r.id IS NULL
)
SELECT COUNT(*) AS notices,
       SUM(CASE WHEN rcnt=1 THEN 1 ELSE 0 END) AS single_row,
       MAX(rcnt) AS max_rows
FROM (SELECT m.bid_ntce_no, COUNT(o.id) AS rcnt
      FROM missing m LEFT JOIN bid_openg_results o ON o.bid_ntce_no=m.bid_ntce_no
      GROUP BY m.bid_ntce_no) x
```

**Q25. 대표 행 공고종류 기준 취소 분해 (4.1절)**
```sql
WITH pop AS (
  SELECT DISTINCT a.bid_ntce_no FROM bid_announcements a
  WHERE a.category='Servc'
    AND a.openg_dt >= '2026-10-14 00:00:00' AND a.openg_dt <= '2026-10-24 23:59:59'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm'))='복수예가'
), missing AS (
  SELECT p.bid_ntce_no FROM pop p
  LEFT JOIN bid_results r ON r.bid_ntce_no=p.bid_ntce_no WHERE r.id IS NULL
), ann AS (
  SELECT a.bid_ntce_no, a.ntce_kind_nm,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN missing m ON m.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN missing m ON m.bid_ntce_no=o.bid_ntce_no
)
SELECT CASE WHEN l.progrs_div_cd_nm IS NULL THEN '1_none'
            WHEN l.progrs_div_cd_nm='유찰' THEN '2_fail'
            WHEN l.progrs_div_cd_nm='재입찰' THEN '3_rebid'
            ELSE '4_done' END AS grp,
       COALESCE(an.ntce_kind_nm,'(null)') AS kind, COUNT(*) AS cnt
FROM missing m
JOIN ann an ON an.bid_ntce_no=m.bid_ntce_no AND an.rn=1
LEFT JOIN last l ON l.bid_ntce_no=m.bid_ntce_no AND l.rn=1
GROUP BY grp, kind ORDER BY grp, cnt DESC
```

**Q26. 9장 10건 단건 확인 (9장)**
```sql
WITH n AS (
  SELECT 'R26BK01725476' AS bid_ntce_no UNION ALL SELECT 'R26BK01727678'
  UNION ALL SELECT 'R26BK01755636' UNION ALL SELECT 'R26BK01756086'
  UNION ALL SELECT 'R26BK01757194' UNION ALL SELECT 'R26BK01758623'
  UNION ALL SELECT 'R26BK01729957' UNION ALL SELECT 'R26BK01753535'
  UNION ALL SELECT 'R26BK01753546' UNION ALL SELECT 'R26BK01741729'
), ann AS (
  SELECT a.bid_ntce_no, a.bid_ntce_ord, a.bid_ntce_nm, a.dminstt_nm,
         a.openg_dt, a.ntce_kind_nm,
         ROW_NUMBER() OVER (PARTITION BY a.bid_ntce_no
                            ORDER BY a.bid_ntce_ord DESC, a.id DESC) rn
  FROM bid_announcements a JOIN n ON n.bid_ntce_no=a.bid_ntce_no
  WHERE a.category='Servc'
), last AS (
  SELECT o.bid_ntce_no, o.progrs_div_cd_nm, o.prtcpt_cnum,
         ROW_NUMBER() OVER (PARTITION BY o.bid_ntce_no
                            ORDER BY o.last_seen_at DESC, o.rbid_no DESC) rn
  FROM bid_openg_results o JOIN n ON n.bid_ntce_no=o.bid_ntce_no
)
SELECT n.bid_ntce_no, an.bid_ntce_ord AS ord, DATE(an.openg_dt) AS openg_d,
       LEFT(an.bid_ntce_nm,30) AS nm, LEFT(an.dminstt_nm,14) AS inst,
       an.ntce_kind_nm AS kind,
       COALESCE(l.progrs_div_cd_nm,'(none)') AS openg_status,
       l.prtcpt_cnum AS bidders,
       (SELECT COUNT(*) FROM bid_results r
        WHERE r.bid_ntce_no=n.bid_ntce_no) AS result_rows
FROM n
LEFT JOIN ann an ON an.bid_ntce_no=n.bid_ntce_no AND an.rn=1
LEFT JOIN last l ON l.bid_ntce_no=n.bid_ntce_no AND l.rn=1
ORDER BY n.bid_ntce_no
```

---

## 12. 참고 문서

- `docs/analysis/result_collection_gap_20260926.md`: 낙찰정보 API 조회 축(등록일)과 대형 공고 상류 공백, 도착 곡선. 본 문서 5.4·5.6절의 해석 근거.
- `docs/analysis/cancel_ord_denominator_20260928.md`: 취소공고가 있는 공고의 결과 미보유가 정상인 이유와 분모 왜곡.
- `docs/analysis/openg_rbidno_uniqueness_20261102.md`: 개찰결과 `rbid_no` 중복 가능성과 최신 행 판정.
- `src/app/services/api_collector.py`: 낙찰현황·개찰결과 API 매핑과 조회 축.
- `src/app/services/collector_service.py`: 체크포인트·수집 창·`MAX_CATCHUP_DAYS`.
- `src/app/models/bids.py`, `src/app/models/openg_results.py`: `bid_results`, `bid_openg_results` 스키마.
- `scripts/backfill_from_g2b.py`, `scripts/backfill_openg_results.py`, `scripts/result_match_rate_report.py`: 재수집·검증 도구.
