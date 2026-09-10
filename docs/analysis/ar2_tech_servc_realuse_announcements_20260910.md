# 기술용역 적격심사 실사용 공고 표본

> **조사일**: 2026-09-10
> **대상**: `category='Servc'`, `srvceDivNm='기술용역'`, `sucsfbidMthdNm`에 `적격심사` 포함
> **기간**: `bid_ntce_dt >= '2026-05-26'`
> **목적**: 기술용역 적격심사 판정·하한율 표시를 실제 공고로 검증하기 위한 대표 표본 확보

## 1. 표본 구성

`docs/analysis/aq2_servc_scope_extension_survey_20260910.md` 4.3절에서 확정한 건수 상위 10개 문자열 각각에 최신 공고 1건을 붙였습니다. 별도로 수기심사, 식별 문자열에 `기술용역`이 없는 경우, 기술인평가 포함, 사후PQ를 확인할 수 있도록 표본을 추가했으며, 추가 표본은 상위10 표본과 동일 공고를 피했습니다.

전체 모집단은 3,763건, 식별 문자열은 44개입니다. 아래 상위10 건수와 최빈 하한율은 기존 조사 결과를 그대로 인용한 값이며, 이 문서에서는 모집단을 재집계하지 않았습니다.

## 2. 상위 10개 문자열 표본

| 구분 | 4.3절 건수 | 최빈 하한율 | 내부 id | bid_ntce_no | bid_ntce_ord | sucsfbidMthdNm | sucsfbidLwltRate | base_amount | bid_ntce_dt |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | --- |
| 상위 1 | 963 | 79.9950 | 10226325 | R26BK01719112 | 000 | 적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준 | 79.995 | 2622862000 | 2026-09-09 23:40:12 |
| 상위 2 | 602 | 87.7450 | 10226299 | R26BK01721924 | 000 | 적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준 | 87.745 | 209000000 | 2026-09-09 17:59:28 |
| 상위 3 | 349 | 87.7450 | 10226145 | R26BK01718286 | 001 | 적격심사제-관리규정외 수기심사(총점입력) | 89.745 | 33407000 | 2026-09-09 13:59:20 |
| 상위 4 | 290 | 86.7450 | 10226250 | R26BK01720929 | 000 | 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준 | 86.745 | 462289000 | 2026-09-09 15:58:57 |
| 상위 5 | 287 | 89.7450 | 10226310 | R26BK01720853 | 001 | 적격심사제-추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 기술용역 평가기준 | 89.745 | 136382181 | 2026-09-09 18:33:19 |
| 상위 6 | 246 | 85.4950 | 10226270 | R26BK01721175 | 000 | 적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준 | 85.495 | 990000000 | 2026-09-09 17:01:03 |
| 상위 7 | 211 | 86.7450 | 10226308 | R26BK01722023 | 000 | 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ) | 86.745 | 168330000 | 2026-09-09 18:18:31 |
| 상위 8 | 122 | 86.7450 | 10226300 | R26BK01696572 | 001 | 적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준 | 86.745 | 226080000 | 2026-09-09 17:59:49 |
| 상위 9 | 118 | 87.7450 | 10218306 | R26BK01718733 | 000 | 적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준 | 87.745 | 58021520 | 2026-09-08 14:22:26 |
| 상위 10 | 85 | 88.7450 | 10218432 | R26BK01716655 | 000 | 적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q대상 기술용역 평가기준 | 88.745 | 322304400 | 2026-09-08 16:44:01 |

## 3. 경계 케이스 표본

| 경계 유형 | 내부 id | bid_ntce_no | bid_ntce_ord | sucsfbidMthdNm | sucsfbidLwltRate | base_amount | bid_ntce_dt | 확인 포인트 |
| --- | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 수기심사 별도 공고 | 10226131 | R26BK01712117 | 000 | 적격심사제-관리규정외 수기심사(총점입력) | 89.745 | 202400000 | 2026-09-09 13:14:07 | 상위3 공고와 다른 실재 공고이며 수기심사 식별 문자열을 보존합니다. |
| 기술용역 문자열 부재 | 10037524 | R26BK01562015 | 001 | 적격심사제-추정가격이 10억원 미만 5억원 이상인 용역 | 85.495 | 758737880 | 2026-07-22 18:01:18 | `srvceDivNm`은 기술용역이지만 `sucsfbidMthdNm` 자체에는 기술용역 문자열이 없습니다. |
| 기술인평가포함 | 10226288 | R26BK01721872 | 000 | 적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(기술인평가포함) | 79.995 | 9677052000 | 2026-09-09 17:40:57 | 기술인평가 포함 계열입니다. |
| 사후PQ 별도 공고 | 10226286 | R26BK01721616 | 001 | 적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ)-지역업체포함 | 88.745 | 113267000 | 2026-09-09 17:38:15 | 상위7 공고와 다른 사후PQ 공고입니다. |

## 4. 실사용 검증 시 관찰점

1. `sucsfbidMthdNm`은 44개 문자열로 분절되어 있어 문자열 전체 일치만으로는 기술용역 계열을 충분히 설명하기 어렵습니다.
2. 수기심사는 같은 문자열 안에서도 하한율이 넓게 흩어질 수 있으므로, 하한율을 문자열 하나의 고정 규칙으로 일반화하지 않아야 합니다.
3. `srvceDivNm='기술용역'`과 `sucsfbidMthdNm`의 기술용역 포함 여부는 서로 다른 판정축입니다. 두 필드를 함께 보존해야 경계 공고를 놓치지 않습니다.
4. 모든 표본은 2026-05-26 이후 공고이며, 공고 테이블의 `base_amount`를 그대로 사용했습니다.

## 5. 필드 보존 확인

각 표본은 다음 필드를 포함합니다.

| 필드 | 원천 |
| --- | --- |
| `id` | `bid_announcements.id` |
| `bid_ntce_no` | `bid_announcements.bid_ntce_no` |
| `bid_ntce_ord` | `bid_announcements.bid_ntce_ord` |
| `sucsfbidMthdNm` | `raw_data`의 `$.sucsfbidMthdNm` |
| `sucsfbidLwltRate` | `raw_data`의 `$.sucsfbidLwltRate` |
| `base_amount` | `bid_announcements.base_amount` |

## 6. 표본 선택 규칙

상위10은 4.3절 문자열별 목록의 순서를 사용하고, 각 문자열에서 `bid_ntce_dt DESC, id DESC`로 최신 1건을 선택했습니다. 경계 표본도 같은 정렬을 사용하되, 상위10에서 이미 선택한 내부 id는 제외하여 동일 공고를 두 표본 칸에 중복하지 않았습니다.

## 7. 재현성 및 제한

DB 조회는 `uv run python scripts/db_readonly_query.py`를 통해 단일 읽기 전용 질의로 수행했습니다. 이 문서는 공고 표본 검증용이며 3,763건 모집단이나 44개 문자열을 재집계하지 않습니다. 조회 시점 이후 DB에 추가된 공고는 포함하지 않습니다.

## 8. 재현용 질의와 결과 원문

아래 질의는 위 표의 14건을 재현합니다. 셸에서 JSON 경로의 `$`가 확장되지 않도록 `\$`로 표기했습니다.

```sh
uv run python scripts/db_readonly_query.py --sql "WITH base AS (SELECT id, bid_ntce_no, bid_ntce_ord, base_amount, bid_ntce_dt, JSON_UNQUOTE(JSON_EXTRACT(raw_data, '\$.sucsfbidMthdNm')) AS method_name, JSON_UNQUOTE(JSON_EXTRACT(raw_data, '\$.sucsfbidLwltRate')) AS lwlt_rate FROM bid_announcements WHERE category = 'Servc' AND bid_ntce_dt >= '2026-05-26' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '\$.srvceDivNm')) = '기술용역' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '\$.sucsfbidMthdNm')) LIKE '%적격심사%'), top_ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY method_name ORDER BY bid_ntce_dt DESC, id DESC) AS rn FROM base WHERE method_name IN ('적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준','적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준','적격심사제-관리규정외 수기심사(총점입력)','적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준','적격심사제-추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 기술용역 평가기준','적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준','적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ)','적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준','적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준','적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q대상 기술용역 평가기준')), top_samples AS (SELECT '상위10' AS sample_group, id, bid_ntce_no, bid_ntce_ord, method_name, lwlt_rate, base_amount, bid_ntce_dt FROM top_ranked WHERE rn = 1), special_ranked AS (SELECT CASE WHEN method_name = '적격심사제-관리규정외 수기심사(총점입력)' THEN '경계-수기심사' WHEN method_name = '적격심사제-추정가격이 10억원 미만 5억원 이상인 용역' THEN '경계-기술용역문자열부재' WHEN method_name LIKE '%기술인평가포함%' THEN '경계-기술인평가포함' WHEN method_name LIKE '%사후PQ%' THEN '경계-사후PQ' END AS sample_group, id, bid_ntce_no, bid_ntce_ord, method_name, lwlt_rate, base_amount, bid_ntce_dt, ROW_NUMBER() OVER (PARTITION BY CASE WHEN method_name = '적격심사제-관리규정외 수기심사(총점입력)' THEN '수기' WHEN method_name = '적격심사제-추정가격이 10억원 미만 5억원 이상인 용역' THEN '무기술문자열' WHEN method_name LIKE '%기술인평가포함%' THEN '기술인평가' WHEN method_name LIKE '%사후PQ%' THEN '사후PQ' END ORDER BY bid_ntce_dt DESC, id DESC) AS rn FROM base WHERE (method_name = '적격심사제-관리규정외 수기심사(총점입력)' OR method_name = '적격심사제-추정가격이 10억원 미만 5억원 이상인 용역' OR method_name LIKE '%기술인평가포함%' OR method_name LIKE '%사후PQ%') AND NOT EXISTS (SELECT 1 FROM top_samples t WHERE t.id = base.id)), special_samples AS (SELECT s.* FROM special_ranked s WHERE s.rn = 1) SELECT sample_group, id, bid_ntce_no, bid_ntce_ord, method_name AS sucsfbidMthdNm, lwlt_rate AS sucsfbidLwltRate, base_amount, bid_ntce_dt FROM top_samples UNION ALL SELECT sample_group, id, bid_ntce_no, bid_ntce_ord, method_name, lwlt_rate, base_amount, bid_ntce_dt FROM special_samples ORDER BY sample_group, id" --format json --limit 30
```

### 결과 원문

```json
[
  {"sample_group":"경계-기술용역문자열부재","id":"10037524","bid_ntce_no":"R26BK01562015","bid_ntce_ord":"001","sucsfbidMthdNm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 용역","sucsfbidLwltRate":"85.495","base_amount":"758737880","bid_ntce_dt":"2026-07-22 18:01:18"},
  {"sample_group":"경계-기술인평가포함","id":"10226288","bid_ntce_no":"R26BK01721872","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(기술인평가포함)","sucsfbidLwltRate":"79.995","base_amount":"9677052000","bid_ntce_dt":"2026-09-09 17:40:57"},
  {"sample_group":"경계-사후PQ","id":"10226286","bid_ntce_no":"R26BK01721616","bid_ntce_ord":"001","sucsfbidMthdNm":"적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ)-지역업체포함","sucsfbidLwltRate":"88.745","base_amount":"113267000","bid_ntce_dt":"2026-09-09 17:38:15"},
  {"sample_group":"경계-수기심사","id":"10226131","bid_ntce_no":"R26BK01712117","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-관리규정외 수기심사(총점입력)","sucsfbidLwltRate":"89.745","base_amount":"202400000","bid_ntce_dt":"2026-09-09 13:14:07"},
  {"sample_group":"상위10","id":"10218306","bid_ntce_no":"R26BK01718733","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준","sucsfbidLwltRate":"87.745","base_amount":"58021520","bid_ntce_dt":"2026-09-08 14:22:26"},
  {"sample_group":"상위10","id":"10218432","bid_ntce_no":"R26BK01716655","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q대상 기술용역 평가기준","sucsfbidLwltRate":"88.745","base_amount":"322304400","bid_ntce_dt":"2026-09-08 16:44:01"},
  {"sample_group":"상위10","id":"10226145","bid_ntce_no":"R26BK01718286","bid_ntce_ord":"001","sucsfbidMthdNm":"적격심사제-관리규정외 수기심사(총점입력)","sucsfbidLwltRate":"89.745","base_amount":"33407000","bid_ntce_dt":"2026-09-09 13:59:20"},
  {"sample_group":"상위10","id":"10226250","bid_ntce_no":"R26BK01720929","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준","sucsfbidLwltRate":"86.745","base_amount":"462289000","bid_ntce_dt":"2026-09-09 15:58:57"},
  {"sample_group":"상위10","id":"10226270","bid_ntce_no":"R26BK01721175","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준","sucsfbidLwltRate":"85.495","base_amount":"990000000","bid_ntce_dt":"2026-09-09 17:01:03"},
  {"sample_group":"상위10","id":"10226299","bid_ntce_no":"R26BK01721924","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준","sucsfbidLwltRate":"87.745","base_amount":"209000000","bid_ntce_dt":"2026-09-09 17:59:28"},
  {"sample_group":"상위10","id":"10226300","bid_ntce_no":"R26BK01696572","bid_ntce_ord":"001","sucsfbidMthdNm":"적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준","sucsfbidLwltRate":"86.745","base_amount":"226080000","bid_ntce_dt":"2026-09-09 17:59:49"},
  {"sample_group":"상위10","id":"10226308","bid_ntce_no":"R26BK01722023","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ)","sucsfbidLwltRate":"86.745","base_amount":"168330000","bid_ntce_dt":"2026-09-09 18:18:31"},
  {"sample_group":"상위10","id":"10226310","bid_ntce_no":"R26BK01720853","bid_ntce_ord":"001","sucsfbidMthdNm":"적격심사제-추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 기술용역 평가기준","sucsfbidLwltRate":"89.745","base_amount":"136382181","bid_ntce_dt":"2026-09-09 18:33:19"},
  {"sample_group":"상위10","id":"10226325","bid_ntce_no":"R26BK01719112","bid_ntce_ord":"000","sucsfbidMthdNm":"적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준","sucsfbidLwltRate":"79.995","base_amount":"2622862000","bid_ntce_dt":"2026-09-09 23:40:12"}
]
```
