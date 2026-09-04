# `agency_announce_top10` 컬럼 전환 실측

> **측정일**: 2026-09-04
> **측정자**: 코디네이터 (직접 실행)
> **대상 DB**: compose `db`, 볼륨 `refac_bid_box_mysql_data`, `bid_announcements` 5,497,840행
> **측정 방식**: 같은 세션에서 두 표현식을 번갈아 2회. `SET SESSION TRANSACTION READ ONLY`
> **관련 문서**: [`base_amount_column_mismatch_343_20260904.md`](base_amount_column_mismatch_343_20260904.md)

---

## 1. 결과

| 회차 | JSON 파싱 경로 | `base_amount` 컬럼 경로 | 배율 | top10 동일 |
| --- | --- | --- | --- | --- |
| 1 | 68.26초 | **2.38초** | 28.7배 | **동일** |
| 2 | 58.82초 | **2.22초** | 26.5배 | **동일** |

**산출값이 완전히 같으면서 26~29배 빨라집니다.** top10 의 기관명, 총액, 건수가
두 경로에서 모두 일치했습니다.

상위 3개 값입니다.

```
가덕도신공항건설공단   32,167,219,537,290   29건
한국토지주택공사       13,135,261,537,271  156건
각 수요기관            10,540,380,914,611 2008건
```

---

## 2. 두 표현식

집계 대상과 필터는 같고 금액을 얻는 방식만 다릅니다.

**JSON 파싱 경로 (전환 전)**

```
CASE WHEN raw_data IS NULL THEN CAST(base_amount AS DECIMAL(30,0))
     ELSE CAST(REPLACE(COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.asignBdgtAmt')),''),
                                NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.bdgtAmt')),'')),
                       ',', '') AS DECIMAL(30,0)) END
```

**컬럼 경로 (전환 후)**

```
CAST(base_amount AS DECIMAL(30,0))
```

두 경로 모두 `MAX_REASONABLE_ANNOUNCEMENT_AMOUNT`(100조) 상한을 적용합니다.

---

## 3. 왜 이렇게 차이가 나는가

550만 행마다 `JSON_EXTRACT` 로 longtext 를 파싱하고 `REPLACE` 로 콤마를 떼고
`DECIMAL` 로 캐스팅합니다. **금액이 컬럼이 아니라 JSON 문서 안의 문자열이라
인덱스로 줄일 수 없는 전수 파싱입니다.**

수집 코드(`api_collector.py` 의 `_map_announcement_item`)가 이미 같은 파싱을
수행해 `base_amount` 컬럼에 넣고 있었으므로, 집계는 같은 일을 549만 번 반복하고
있었습니다.

---

## 4. 인수인계 수치와의 차이

이전 세션 기록은 웜 상태 31.97초였고 이번 JSON 경로는 58.82~68.26초입니다.
**같은 조건이 아닙니다.** 이 측정은 컨테이너를 올린 뒤 다른 작업과 함께 돌아가는
상태였고 버퍼풀 온도를 통제하지 않았습니다.

**절대값을 게이트로 쓰지 마십시오.** 이 저장소는 콜드 SQL 절대값을 게이트에서
제외하기로 이미 판정한 이력이 있습니다. 여기서 의미 있는 것은 **같은 세션에서
번갈아 측정한 배율(26~29배)과 산출값 동일성**입니다.

컬럼 경로의 2.2~2.4초도 여전히 550만 행 스캔입니다. 더 줄이려면 사전집계나
인덱스가 필요하며 이 문서의 범위가 아닙니다.

---

## 5. 남은 것

`base_amount` 는 `BIGINT` 이고 포화 2건이 그대로 있습니다. 상한이 그 두 건을
집계에서 배제하므로 화면 영향은 없지만, 컬럼 값 자체를 `NULL` 로 바로잡는 것은
DB 값 변경이라 승인이 필요한 별도 작업입니다.
