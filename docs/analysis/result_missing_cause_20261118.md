# 낙찰 결과(bid_results) 개별 누락 12건 원인 실측 (2026-11-18)

> **작성일**: 2026-11-18
> **상태**: 분석 완료 (코드·DB·설정 변경 없음)
> **범위**: 2026-11-18 02:01:50~02:03:27(UTC)에 재적재된 Servc 낙찰 결과 12건. 해당 건의 결과 등록일은 2026-10-01~2026-11-13이다.
> **정본 모듈**: `src/app/services/collector_service.py`(수집 창 계산), `src/app/services/api_collector.py`(낙찰정보 조회 축)
> **기준 커밋**: `ae2a789e`(14일 재수집 도입) 및 그 이전 코드 `ae2a789e^`
> **질의 방법**: `uv run python scripts/db_readonly_query.py --sql "<질의>"` (읽기 전용, SELECT 단일 문장)
> **계약 준수**: 조달청 API 직접 호출 없음. 운영 DB·Redis 쓰기 없음. `docker exec`·`mysql` 직접 호출 없음. `raw_data` 전 테이블 LIKE 스캔 없음. 코드 수정 없음. 산출물은 본 문서 1건.

---

## 1. 결론

1. **재적재 12건을 특정했다.** `collected_at` 2026-11-18 02:01:50~02:03:27(UTC) 구간에 삽입된 행은 Servc 12건뿐이고, 그 안에 `R26BK01725476` 이 있다. 현재 Servc `bid_results` 는 1,103,516행으로 캡슐 제시값과 일치한다(질의 Q1, Q2).

2. **개찰 후 늦은 등록은 사실이지만 원인이 아니다.** 12건의 개찰일시와 결과 등록일시(`raw_data.rgstDt`)는 최대 61.3일 벌어진다. 그러나 낙찰정보 API 의 조회 축은 개찰일이 아니라 **등록일시**다(3.2절). 따라서 개찰→등록 지연 자체는 누락을 만들지 않는다.

3. **'수집 창이 노출 지연보다 짧았다'는 가설은 기각한다.** 12건 모두 결과 등록일을 덮는 수집 실행이 재적재 이전에 실제로 있었고, 같은 실행이 **같은 등록일의 다른 행을, 그것도 해당 건보다 늦은 등록 시각까지** 적재했다(2.2절). 창의 끝은 항상 '어제(KST)'이며, 12건의 등록일은 모두 그 창 안이었다(3.1절).

4. **판정은 12건 전부 '수집 결함(창 내 개별 누락)'이다.** 수집기가 정상 응답의 행을 버리는 경로는 코드상 없고(3.3절), 12건 중 10건은 1페이지(999행 이하) 응답이었다. 따라서 **당시 API 응답에 그 행들이 없었다**고 보는 것이 가장 일관된다. 그 이유가 레코드 단위 노출 지연인지, 2페이지 수집의 경계 누락인지는 당시 응답 이력이 없어 **미확정**이다.

5. **14일 창은 방향은 맞지만 충분성을 단정할 수 없다.** 변경은 등록일을 한 번만 조회하던 구조를 14회 재조회로 바꾼다(3.4절). 확인된 '미노출 지속시간'의 하한은 최대 2.82일(10-12 등록 건)이므로 14일은 그 하한을 덮는다. 다만 노출 시점의 상한은 관측할 수 없어(재적재가 11-18 수동 1회) **14일이 충분하다고 단정하지 않는다**.

> 한 줄 요약: 원인은 '창이 짧아서'가 아니라, **창이 등록일을 한 번만 보고 다시 보지 않는데 그 한 번의 응답에 해당 건이 없었던 것**이다.

---

## 2. 재적재 12건과 당시 수집 커버리지

### 2.1 12건 식별

- 재적재 구간(2026-11-18 02:00~02:04 UTC)에 삽입된 `bid_results` 는 **Servc 12행**이 전부다(질의 Q12). 같은 날 01:14:10(UTC)의 야간 수집 328행과는 시각이 분리된다.
- 12행은 9개 시각 군집(1/1/1/1/2/3/1/1/1)으로 들어왔고, `rgstDt` 일자별 행 수 분포(1/1/1/1/2/3/1/1/1)와 정확히 일치한다. 등록일시 일자 단위 재조회로 들어온 행임을 보여준다.
- 결과 등록 일시 필드는 `raw_data.rgstDt` 다. `fnlSucsfDate` 는 최종 낙찰일이다(질의 Q2). `raw_data` 에 `bidNtceDt` 키는 없다.
- 실행 기록은 `schedule_run_log` 에서 `worker_id IS NOT NULL` 로 운영 워커 행만 골랐다. 이번 조회 시점에 260행 전부 `worker_id` 가 있었고, 2026-11-13 에 확인된 pytest 오염(965행 중 962행)은 재현되지 않았다(질의 Q11). 다만 이 로그는 2026-11-11 이후만 있고 수집 창 파라미터를 남기지 않아, **10월 실행 창은 `collected_at` 삽입 흔적으로 복원했다**(질의 Q9, Q10). 11-17 02:32:03 과 11-18 01:13:25 의 `schedule_catchup` 성공 기록은 해당 삽입 배치와 일치한다(질의 Q11).

### 2.2 12건 표

`collected_at` 은 모두 2026-11-18(UTC)이다. '커버 실행'은 해당 등록일을 실제로 조회한 실행의 삽입 시각(UTC)이고, '창 끝(KST)'은 그 실행이 조회한 마지막 등록일이다. '같은 등록일 적재'는 **그 실행이 같은 응답에서 적재한 같은 등록일 행 수와 최대 등록일시**다.

| # | 공고번호 | 차수 | 개찰 일시 | 결과 등록 일시(rgstDt) | 개찰→등록 | 재적재 collected_at(UTC) | 커버 실행(UTC) | 창 끝(KST) | 같은 등록일 적재 | 확인된 미노출 하한 | 판정 |
| --: | --- | --- | --- | --- | ---: | --- | --- | --- | --- | ---: | --- |
| 1 | R26BK01691924 | 000 | 2026-10-01 17:21:30 | 2026-10-01 17:24:42 | 0.0일 | 02:01:50.708703 | 2026-10-02 16:04:40 | 2026-10-02 | 333행, 최대 10-01 21:02:12 | 1.32일 | 창 내 누락 |
| 2 | R26BK01650900 | 000 | 2026-10-12 17:33:04 | 2026-10-12 17:33:48 | 0.0일 | 02:02:05.201397 | 2026-10-15 04:09:45 | 2026-10-14 | 362행, 최대 10-12 23:36:44 | 2.82일 | 창 내 누락 (2페이지) |
| 3 | R26BK01673651 | 000 | 2026-09-04 11:28:06 | 2026-10-13 09:21:04 | 38.9일 | 02:02:15.861447 | 2026-10-15 04:09:45 | 2026-10-14 | 390행, 최대 10-13 21:39:43 | 2.16일 | 창 내 누락 (2페이지) |
| 4 | R26BK01760961 | 000 | 2026-10-14 11:04:52 | 2026-10-18 12:35:20 | 4.1일 | 02:02:24.307335 | 2026-10-19 03:15:21 | 2026-10-18 | 8행, 최대 10-18 18:30:28 | 0.99일 | 창 내 누락 |
| 5 | R26BK01699911 | 000 | 2026-09-30 14:10:00 | 2026-10-27 10:33:13 | 26.8일 | 02:02:29.959125 | 2026-10-28 02:29:46 | 2026-10-27 | 356행, 최대 10-27 23:52:19 | 1.04일 | 창 내 누락 |
| 6 | R26BK01711348 | 000 | 2026-09-30 13:26:02 | 2026-10-27 16:09:45 | 27.1일 | 02:02:29.959218 | 2026-10-28 02:29:46 | 2026-10-27 | 356행, 최대 10-27 23:52:19 | 0.81일 | 창 내 누락 |
| 7 | R26BK01716825 | 000 | 2026-10-08 11:22:52 | 2026-10-28 21:06:18 | 20.4일 | 02:03:27.709670 | 2026-10-29 06:31:19 | 2026-10-28 | 319행, 최대 10-28 21:35:07 | 0.77일 | 창 내 누락 |
| 8 | R26BK01717867 | 000 | 2026-10-29 16:55:44 | 2026-11-05 09:09:17 | 6.7일 | 02:02:37.973409 | 2026-11-06 00:07:14 | 2026-11-05 | 351행, 최대 11-05 22:46:24 | 1.00일 | 창 내 누락 |
| 9 | R26BK01725476 | 000 | 2026-10-14 11:07:33 | 2026-11-05 19:14:23 | 22.3일 | 02:02:37.973562 | 2026-11-06 00:07:14 | 2026-11-05 | 351행, 최대 11-05 22:46:24 | 0.58일 | 창 내 누락 |
| 10 | R26BK01760844 | 000 | 2026-10-20 11:07:05 | 2026-11-05 19:29:43 | 16.3일 | 02:02:37.973564 | 2026-11-06 00:07:14 | 2026-11-05 | 351행, 최대 11-05 22:46:24 | 0.57일 | 창 내 누락 |
| 11 | R26BK01709462 | 000 | 2026-09-10 11:10:12 | 2026-11-10 19:24:50 | 61.3일 | 02:02:44.112509 | 2026-11-11 02:22:01 | 2026-11-10 | 357행, 최대 11-10 22:20:33 | 0.67일 | 창 내 누락 |
| 12 | R26BK01719965 | 000 | 2026-10-08 13:11:23 | 2026-11-13 08:56:46 | 35.8일 | 02:02:50.579520 | 2026-11-14 00:53:16 | 2026-11-13 | 291행, 최대 11-13 21:25:50 | 1.04일 | 창 내 누락 |

### 2.3 표를 읽는 법

- **판정 규칙**은 캡슐이 지정한 그대로다. 결과 등록일이 당시 수집 창 밖으로 늦었으면 '노출 지연', 창 안이었는데 빠졌으면 '수집 결함'이다.
- 12건 모두 등록일이 창 안이다. 근거는 두 가지다.
  1. 커버 실행의 창 끝(어제 KST)이 해당 등록일과 같거나 늦다.
  2. 그 실행이 **같은 등록일의 다른 행을 더 늦은 등록 시각까지** 적재했다. 예를 들어 #9 의 등록 시각은 11-05 19:14 인데, 같은 실행이 11-05 22:46 등록 건까지 적재했다. 응답이 11-05 하루를 22:46 까지 덮었다는 뜻이므로 19:14 건이 창 밖이었을 수 없다.
- '확인된 미노출 하한'은 **커버 실행 시각(KST) − 등록 시각**이다. 이 값은 "그 시점까지 API 응답에 없었다"는 하한이며, 실제 노출 시점은 이보다 늦을 수 있다. 최대값은 2.82일(#2)이다.
- #2 와 #3 의 커버 실행은 4일 창(10-11~10-14)을 한 번에 받았고 1,087행이라 **2페이지**였다. 이 두 건만은 페이지 경계 누락 가능성을 배제할 수 없다(4장). 나머지 10건은 999행 이하의 **1페이지** 응답이었다.
- 개찰→등록 지연(0.0~61.3일)은 참고값이다. 조회 축이 등록일이므로 이 값이 커도 누락과 직접 인과가 없다.

---

## 3. 코드 근거

### 3.1 수집 창은 개찰일 체크포인트로 계산되고, 끝은 항상 '어제(KST)'다

`git show ae2a789e^:src/app/services/collector_service.py`(14일 재수집 도입 이전) 기준이다.

```text
146    yesterday: date = kst_today(utcnow()) - timedelta(days=1)
147    yesterday_str = yesterday.strftime("%Y%m%d")
151    today_start = datetime.combine(yesterday + timedelta(days=1), datetime.min.time())
```

```text
204    if fetch_type in ("both", "result"):
205        res_q = select(func.max(BidResult.rl_openg_dt).label("max_dt"))
206        res_q = res_q.where(
207            BidResult.category.in_(ckpt_categories),
208            BidResult.rl_openg_dt < today_start,
209        )
210        per_cat = res_q.group_by(BidResult.category).subquery()
211        row = db.scalar(select(func.min(per_cat.c.max_dt)))
```

```text
221    gap_start = latest + timedelta(days=1)
222
223    if gap_start > yesterday:
224        return yesterday_str, yesterday_str, False
```

- 체크포인트 `latest` 는 **개찰일(`rl_openg_dt`)의 카테고리별 최신값 중 최솟값**이다(205~211행).
- 창의 끝은 `yesterday`(어제 KST)로 고정된다(146~147, 223~224행). 시작은 `latest + 1` 이고, 시작이 어제를 넘으면 `(어제, 어제)` 로 잘린다.
- 따라서 결과 경로가 조회하는 구간의 **끝은 언제나 어제(KST)** 이며, 하루 전에 등록된 결과는 항상 창 안에 들어온다. 창의 시작이 등록일보다 늦어지는 경우는 `최신 개찰일 = 어제` 인 경우뿐인데, 그때도 창은 `(어제, 어제)` 로 등록일을 포함한다.

14일 재수집 이전의 결과 경로는 이 창을 그대로 썼다.

```text
544        if fetch_type in ("both", "result"):
545            metrics["attempted"] += 1
546            try:
547                saved = await stream_bid_data(
548                    resolved_start,
549                    resolved_end,
550                    lambda rows: _bulk_insert(db, BidResult, rows),
551                    category=cat_code,
552                )
```

### 3.2 낙찰 결과 조회 축은 등록일시(`inqryDiv=1`)다

`src/app/services/api_collector.py` 기준이다.

```text
329        inqry_div: str = "1",
338        async def _page(page_no: int) -> tuple[list[dict[str, Any]], int]:
339            params: dict[str, str] = {
340                "serviceKey": get_service_key(),
341                "pageNo": str(page_no),
342                "numOfRows": str(num_of_rows),
343                "inqryDiv": inqry_div,
344                "inqryBgnDt": f"{step_start}0000",
345                "inqryEndDt": f"{step_end}2359",
346                "type": "xml",
347            }
```

```text
496    async def _run_ranges(
...
504        inqry_div: str = "1",
```

```text
591    async def stream_bid_data(
592        start_date: str,
593        end_date: str,
594        sink: Callable[[list[dict[str, Any]]], Any],
595        num_of_rows: int = 999,
596        category: str = "Thng",
597    ) -> int:
598        """낙찰정보를 15일 구간 단위로 받아 즉시 `sink` 로 넘깁니다."""
599        return await _run_ranges(
600            _resolve_bid_url(category),
601            start_date,
602            end_date,
603            num_of_rows,
604            _map_result_item(category),
605            "낙찰정보",
606            sink,
607        )
```

- `stream_bid_data` 는 `inqry_div` 를 넘기지 않으므로 504행 기본값 `"1"` 이 적용된다. 낙찰정보 API 의 `inqryDiv=1` 은 **등록일시** 축이다. `scripts/audit_result_missing.py` 도 같은 축을 명시한다(5~7행, 97~107행). 따라서 3.1절의 창(개찰일 체크포인트로 계산)이 실제로는 **등록일 축**에 적용된다.
- 구간 분할은 15일 단위다(`RANGE_DAYS = 15`, 82행; `split_date_range`, 165~179행). 한 구간은 페이지 단위로 다시 쪼개진다(1페이지에서 `totalCount` 확인 후 나머지 페이지 병렬 수집, 368~376행).
- 결과 등록일시 필드는 `raw_data.rgstDt` 다. `_map_result_item` 은 응답 원문을 그대로 `raw_data` 에 넣는다(379행부터). 별도 등록일 컬럼은 없다.

### 3.3 수집기가 정상 응답의 행을 버리는 경로

`collector_service.py` 의 `_bulk_insert` 는 두 가지 경우에 행을 떨어뜨리고, `_run_ranges` 는 구간 실패 시 그 구간 전체를 적재하지 않는다.

```text
272        stmt = insert(model.__table__).prefix_with(_ignore_prefix(db))
...
276            chunk = [row for row in rows[start : start + BATCH_ROWS] if row.get("bid_ntce_no")]
...
284            inserted += rowcount if rowcount is not None and rowcount >= 0 else len(chunk)
```

- `bid_ntce_no` 가 빈 행은 버린다(276행). 12건은 모두 공고번호가 있다.
- 유니크 키 `(bid_ntce_no, bid_ntce_ord, category)` 충돌 행은 `INSERT IGNORE` 로 무시된다(272행). 12건은 재적재 전 DB 에 없었으므로 충돌이 아니다.
- `_run_ranges` 는 한 구간이라도 실패하면 `RangeCollectionError` 를 올리고, 그 구간의 행은 `sink` 로 넘기지 않는다(496~560행). 그런데 관측된 배치는 같은 실행에서 수백 행을 적재했으므로 해당 구간 수집은 실패하지 않았다.
- 결론: **응답에 행이 있었다면 버려질 경로가 없다.** 따라서 12건은 당시 응답에 없었다고 보는 것이 가장 일관된다. 단, 2페이지 이상인 구간에서는 페이지 수집 중 응답 순서가 흔들려 행이 페이지 경계에서 빠질 가능성을 코드만으로 배제할 수 없다. 12건 중 #2, #3 만 2페이지 구간이다.

### 3.4 2026-11-18 변경: 결과 경로만 14일 재수집

현재 코드(`ae2a789e` 이후) 기준이다.

```text
67    # 낙찰 결과는 등록일시보다 늦게 API 에 노출되는 경우가 있어(2026-11-18 실측:
68    # 용역 낙찰현황 10,977건 중 12건 누락) 결과 경로만 매일 최근 14일을 다시 받습니다.
69    RESULT_RESCAN_DAYS = 14
```

```text
507        result_start = resolved_start
508        if fetch_type in ("both", "result"):
509            if start_date is None:
510                rescan_floor = datetime.strptime(resolved_end, "%Y%m%d").date() - timedelta(
511                    days=RESULT_RESCAN_DAYS - 1
512                )
513                result_start = min(resolved_start, rescan_floor.strftime("%Y%m%d"))
514                logger.info("낙찰 결과 재수집 구간: %s ~ %s", result_start, resolved_end)
515            metrics["result_start_date"] = result_start
```

```text
566                saved = await stream_bid_data(
567                    result_start,
568                    resolved_end,
569                    lambda rows: _bulk_insert(db, BidResult, rows),
570                    category=cat_code,
571                )
```

- 자동 창(`start_date is None`)에서만 결과 시작일을 14일 전으로 당긴다. 명시적 백필은 요청 구간을 지킨다(509행).
- 이 변경의 실질 효과는 **같은 등록일을 14회 재조회**하는 것이다. 기존 구조는 등록일을 사실상 한 번만 조회했으므로, 그 한 번의 응답에 없던 행은 영구 누락이었다.

### 3.5 12건이 모두 창 안이었음에도 빠진 이유

- 12건 모두 등록일을 덮는 실행이 있었고, 그 실행의 같은 등록일 최대 등록 시각이 해당 건보다 늦었다(2.2절). 즉 조회 범위는 충분했다.
- 10건은 1페이지 응답이었으므로 페이지 경계 문제도 없다. 수집기는 정상 응답의 행을 버리지 않는다(3.3절).
- 남는 설명은 **해당 시점의 API 응답에 그 레코드가 없었다**는 것이다. 등록일시 메타데이터(`rgstDt`)는 그 날짜를 가리키지만, 목록 API 가 그 시점에 그 행을 반환하지 않았다는 뜻이다. 이는 '레코드 단위 노출 지연' 또는 '일시적 응답 불완전'으로 부를 수 있다.
- 다만 **그것이 노출 지연인지 확정할 수는 없다.** 당시 API 응답 원문 이력이 없고, 이후 성공 조회는 2026-11-18 수동 재적재 1회뿐이다. 따라서 하위 기제는 미확정으로 둔다.

---

## 4. 남은 불확실성과 필요한 API 확인 순서

### 4.1 남은 불확실성

1. **당시 응답 이력 부재.** 12건이 그 실행의 응답에 없었다는 사실은 DB 삽입 결과로 확정되지만, 그것이 레코드 노출 지연인지 응답 불완전인지는 구분할 수 없다.
2. **노출 지연 상한 미관측.** 재적재가 2026-11-18 수동 1회여서, 각 건이 언제부터 API 에 있었는지 알 수 없다. 재적재일까지의 경과는 최대 47.7일(#1)이지만 이는 **수동 재적재 시점의 상한**이지 API 노출 지연의 상한이 아니다. 그러므로 14일 창의 충분성을 단정할 수 없다.
3. **2페이지 구간.** #2, #3 의 커버 실행(10-15, 1,087행)만 2페이지였다. 페이지 경계 누락 가능성을 배제하지 못한다.
4. **실행 기록의 한계.** `schedule_run_log` 는 2026-11-11 이후만 있고 수집 창 파라미터를 남기지 않는다. 10월 실행은 `collected_at` 삽입 흔적으로 복원했으므로, "실행이 있었다"는 확정이지만 "그 실행이 정확히 어느 창을 요청했는지"는 코드와 삽입 분포로 추정한 값이다. 다만 2.2절의 '같은 등록일 최대 등록 시각'은 창 추정과 무관하게 성립하는 관측값이다.
5. **14일 창 충분성.** 확인된 미노출 하한(최대 2.82일)은 14일이 덮는다. 그러나 상한을 모르므로 "충분"이 아니라 "관측된 하한을 덮는 조건부 충분"으로 둔다. 재발 감시가 필요하다.

### 4.2 코디네이터가 수행할 API 확인 순서

워커 환경에는 조달청 키가 없어 API 를 호출하지 않았다. 아래 순서로 확인하면 남은 불확실성이 닫힌다.

1. **재현 확인(단건).** `getScsbidListSttusServc` 에 `inqryDiv=1`, `inqryBgnDt=202611050000`, `inqryEndDt=202611052359`, `pageNo=1`, `numOfRows=999` 로 조회해 `R26BK01725476` 이 반환되는지 확인한다. 반환되면 등록일 축과 현재 노출을 동시에 확인하는 셈이다.
2. **노출 지연 상한 측정.** 같은 오퍼레이션으로 등록일 2026-10-01~2026-11-17 을 하루씩 재조회해, 12건이 현재 반환되는지 확인한다. 최소 두 시점(예: 2026-11-18, 2026-11-25)에서 같은 조회를 반복해 **반환되기 시작한 시점의 상한**을 좁힌다. 그 값이 14일 이내인지가 14일 창 충분성의 판정 근거가 된다.
3. **페이지 경계 검증.** 10-15 실행과 같은 창(`inqryDiv=1`, `inqryBgnDt=202610110000`, `inqryEndDt=202610142359`)을 `numOfRows=999` 로 다시 받아 `totalCount`, 페이지별 항목 수, `R26BK01650900`·`R26BK01673651` 의 포함 여부를 기록한다. 두 건이 포함되면 2페이지 경계 누락 가능성이 닫힌다.
4. **14일 창 판정.** 2번에서 얻은 노출 지연 상한과 14일을 비교한다. 상한이 14일을 넘으면 `RESULT_RESCAN_DAYS` 를 늘리거나, 누락 감시(`result_coverage_monitor`)와 `scripts/audit_result_missing.py` 정기 실행을 함께 둔다.

---

## 5. 부록: 재현 질의

모든 질의는 아래 형태로 실행한다.

```bash
uv run python scripts/db_readonly_query.py --format table --sql "<질의>"
```

**Q1. 현재 Servc 결과 행 수 (1장, 2.1절)**
```sql
SELECT COUNT(*) AS servc_rows FROM bid_results WHERE category='Servc'
```

**Q2. 재적재 12건과 결과 등록일시 (2.1, 2.2절)**
```sql
SELECT id, bid_ntce_no AS no, bid_ntce_ord AS ord, rl_openg_dt AS openg_dt,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt')) AS rgst_dt,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.fnlSucsfDate')) AS fnl_date,
       collected_at
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-11-18 02:00:00' AND collected_at < '2026-11-18 02:04:00'
ORDER BY rgst_dt
```

**Q3. 실행별 등록일 커버리지 (2.2절, 10-02~10-05 실행)**
```sql
SELECT DATE(collected_at) AS ins_day,
       DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-10-02 00:00:00' AND collected_at < '2026-10-06 00:00:00'
GROUP BY ins_day, rgst_day ORDER BY ins_day, rgst_day
```

**Q4. 10-15 실행의 등록일 커버리지 (#2, #3)**
```sql
SELECT DATE(collected_at) AS ins_day,
       DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-10-15 00:00:00' AND collected_at < '2026-10-17 00:00:00'
GROUP BY ins_day, rgst_day ORDER BY ins_day, rgst_day
```

**Q5. 10-19 실행의 등록일 커버리지 (#4)**
```sql
SELECT DATE(collected_at) AS ins_day,
       DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-10-19 00:00:00' AND collected_at < '2026-10-20 00:00:00'
GROUP BY ins_day, rgst_day ORDER BY ins_day, rgst_day
```

**Q6. 10-28·10-29 실행의 등록일 커버리지 (#5, #6, #7)**
```sql
SELECT DATE(collected_at) AS ins_day,
       DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-10-28 00:00:00' AND collected_at < '2026-10-30 00:00:00'
GROUP BY ins_day, rgst_day ORDER BY ins_day, rgst_day
```

**Q7. 11-06 실행의 등록일 커버리지 (#8, #9, #10)**
```sql
SELECT DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-11-06 00:00:00' AND collected_at < '2026-11-07 00:00:00'
GROUP BY rgst_day ORDER BY rgst_day
```

**Q8. 11-11·11-14 실행의 등록일 커버리지 (#11, #12)**
```sql
SELECT DATE(collected_at) AS ins_day,
       DATE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS rgst_day,
       COUNT(*) AS cnt,
       MIN(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS min_rgst,
       MAX(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.rgstDt'))) AS max_rgst
FROM bid_results
WHERE category='Servc'
  AND (
        (collected_at >= '2026-11-11 00:00:00' AND collected_at < '2026-11-12 00:00:00')
     OR (collected_at >= '2026-11-14 00:00:00' AND collected_at < '2026-11-15 00:00:00')
      )
GROUP BY ins_day, rgst_day ORDER BY ins_day, rgst_day
```

**Q9. 9~10월 삽입 배치(실행 시각) (2.1, 3.5절)**
```sql
SELECT DATE(collected_at) AS d, COUNT(*) AS cnt,
       MIN(TIME(collected_at)) AS first_t, MAX(TIME(collected_at)) AS last_t
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-09-28 00:00:00' AND collected_at < '2026-11-01 00:00:00'
GROUP BY d ORDER BY d
```

**Q10. 11월 삽입 배치(실행 시각) (2.1절)**
```sql
SELECT DATE(collected_at) AS d, COUNT(*) AS cnt,
       MIN(TIME(collected_at)) AS first_t, MAX(TIME(collected_at)) AS last_t
FROM bid_results
WHERE category='Servc'
  AND collected_at >= '2026-11-01 00:00:00' AND collected_at < '2026-11-19 00:00:00'
GROUP BY d ORDER BY d
```

**Q11. 운영 워커 실행 기록과 오염 여부 (2.1절)**

Q11-1. 전체 행 수와 `worker_id` 결측 수
```sql
SELECT COUNT(*) AS total_rows,
       SUM(CASE WHEN worker_id IS NULL THEN 1 ELSE 0 END) AS null_worker
FROM schedule_run_log
```

Q11-2. 2026-11-16 이후 운영 워커 수집 실행
```sql
SELECT schedule_name, started_at, finished_at, status, LEFT(worker_id,26) AS worker
FROM schedule_run_log
WHERE worker_id IS NOT NULL
  AND schedule_name IN ('schedule_catchup','intraday_collect')
  AND started_at >= '2026-11-16 00:00:00'
ORDER BY started_at
```

**Q12. 재적재 구간의 카테고리별 삽입 수 (2.1절)**
```sql
SELECT category, COUNT(*) AS cnt,
       MIN(collected_at) AS min_c, MAX(collected_at) AS max_c
FROM bid_results
WHERE collected_at >= '2026-11-18 02:00:00' AND collected_at < '2026-11-18 02:04:00'
GROUP BY category
```

---

## 6. 참고 문서

- `docs/analysis/result_coverage_20261117.md`: 2026-10-14~10-24 용역 복수예가 696건 분석. 9.1절의 `R26BK01725476` 단건 확인이 본 조사의 출발점이다.
- `src/app/services/api_collector.py`: 낙찰정보·개찰결과 API 매핑, 조회 축, 구간·페이지 수집.
- `src/app/services/collector_service.py`: 체크포인트·수집 창·`MAX_CATCHUP_DAYS`·`RESULT_RESCAN_DAYS`.
- `scripts/audit_result_missing.py`: 등록일시 축 일별 재조회·대조 도구. `_registration_text` 는 `raw_data.bidNtceDt` 를 우선하지만 낙찰현황 응답에는 이 키가 없어 조회일로 대체한다(180~186행).
- `scripts/backfill_from_g2b.py`: 명시 창 수동 백필 도구.
