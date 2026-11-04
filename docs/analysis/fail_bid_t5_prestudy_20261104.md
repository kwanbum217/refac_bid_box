# 유찰 T5 착수 전 코드 대조 조사

> **작성일**: 2026-11-04
> **작업 ID**: `task_6639f4e7018b`
> **브랜치**: `kwanbum217/orca-f-t5-prestudy`
> **성격**: 조사 보고서. 소스·시험·마이그레이션·DB 변경 0건, DB 조회 0회, 외부 API 호출 0회.
> **설계 정본**: [fail_bid_collection_design_20261031.md](fail_bid_collection_design_20261031.md) 6장, 8장 T5
> **결론**: 설계 6.2·6.3절의 위치 표기는 작성 이후 코드가 늘어나 전부 어긋났다. 함수 자체는 모두 남아 있으므로 의미는 유효하다. 다만 6.4절 계획 계층은 아직 `filters["outcome"]` 을 세우지 않아, 가드만 해제하면 유찰 목록은 정형 경로로 가지 않는다. T5 는 `data_gap_guard` 삭제만으로 끝나지 않는다.

---

## 1. 설계 위치 대조표

| 설계 위치 (2026-10-31 문서) | 현재 위치 | 일치 | 비고 |
| --- | --- | :---: | --- |
| `src/rag/data_gap_guard.py:117` `_ITEM_PATTERNS` | `src/rag/data_gap_guard.py:97` (유찰 항목은 `:102`) | 아니오 | 20줄 밀림. 항목 튜플 자체는 그대로 `("유찰 상태", (_VOID_STATUS,), True)` |
| `src/rag/data_gap_guard.py:70` `_VOID_STATUS` | `src/rag/data_gap_guard.py:57` | 아니오 | 13줄 밀림. `re.compile(r"유찰")` 동일 |
| `src/rag/data_gap_guard.py:45-49` `DATA_GAP_MESSAGES["유찰 상태"]` | `src/rag/data_gap_guard.py:36-40` | 아니오 | 9줄 밀림. 문구 내용 동일, 삭제 없음 |
| `src/rag/data_gap_guard.py:148-149` `_EXPLANATION` 우회 | 우회 조건은 `src/rag/data_gap_guard.py:133-134`, `_EXPLANATION` 정의는 `:61-65` | 아니오 | 15줄 밀림. `_EXPLANATION` 이고 `_ACTUAL_VALUE` 가 없으면 `None` 반환하는 구조 동일 |
| `src/rag/structured_data.py:604-660` `_announcement_conditions` | `src/rag/structured_data.py:630-689` | 아니오 | 26줄 밀림. 인자와 필터 키 구성 동일 |
| `src/rag/structured_data.py:2317-2383` `_fetch_sample_announcements` | `src/rag/structured_data.py:2427-2493` | 아니오 | 110줄 밀림. 호출부는 `:3559-3565` |
| `src/rag/structured_data.py:3089-3295` 목록 분기 | `src/rag/structured_data.py:3338-3565` (`announcement_limit` 판독 `:3340`, 표본 호출 `:3559`) | 아니오 | 249줄 밀림. 집계 total 은 같은 `announcement_conditions` 를 쓰므로 조건이 자동 공유됨 |
| `src/rag/structured_data.py:876-898` `_result_availability_conditions` | `src/rag/structured_data.py:909-931` | 아니오 | 33줄 밀림. outcome 미포함, 설계대로 변경 불필요 |
| `src/rag/query_planning.py:1749` `ANNOUNCEMENT_RESULT_STATUS_MARKERS` | `src/rag/query_planning.py:1888` | 아니오 | 139줄 밀림. 사용처는 `:1640`, `:2004`, `:2056` |
| 6.4절 "목록 예외 별도 변경" (위치 미기재) | `src/rag/query_planning.py:3086-3088`(라우팅), `:3412-3413`(`announcement_limit` 설정), `:2056`(목록 판정 차단) | 아니오 | 설계에 위치가 없던 항목. 이 세 곳이 실제 변경 지점 |

추가로 설계에 없던 사실 두 가지를 기록한다.

| 항목 | 사실 | 영향 |
| --- | --- | --- |
| `BidOpengResult` import | `src/rag/structured_data.py:29-38` 의 모델 import 블록에 없다 | 6.3절 EXISTS 서브쿼리를 넣으려면 import 추가가 선행되어야 함 |
| `_announcement_conditions` 호출처 | `src/rag/structured_data.py:1887`, `:2049-2066`(별도 빌더), `:2926`, `:3323`, `:3392` | `filters["outcome"]` 를 읽도록 고치면 5개 경로에 동시에 적용됨. 필터가 실릴 때만 동작하므로 무해하지만, 계획이 outcome 을 싣는 범위를 좁혀야 함 |

`src/rag/data_gap_guard.py:36-40` 의 고정 문구를 남기고 `:102` 항목만 제거하면, `DATA_GAP_MESSAGES` 를 순회하는 시험이 깨진다. 3절에 적는다.

---

## 2. 6.1절 가드 해제 세 조건 판정 질의

이 절의 SELECT 는 실행하지 않았다. 코디네이터가 1년 소급을 마친 뒤 실행한다. 모든 질의는 MySQL 8 기준이며, 3분류(`Thng`, `Cnstwk`, `Servc`)만 대상으로 한다. 외자(`Frgcpt`)는 수집 대상이 아니므로 분모에서 빼야 커버리지가 왜곡되지 않는다(설계 7절 결정 1).

조인 키는 `(bid_ntce_no, bid_ntce_ord, category)` 이다. `rbid_no` 는 `bid_announcements` 에 없고, `bid_openg_results` 의 유니크 키에 포함되어 같은 공고·차수에 여러 행을 만들 수 있으므로 조인에 쓰지 않는다.

### 2.1 조건 1: 최근 30일 개찰 공고의 개찰결과 보유 비율

```sql
SELECT
    COUNT(*)                                      AS eligible_total,
    SUM(t.matched)                                AS matched_total,
    ROUND(SUM(t.matched) / NULLIF(COUNT(*), 0), 4) AS coverage_ratio
FROM (
    SELECT
        a.id,
        EXISTS (
            SELECT 1
            FROM bid_openg_results r
            WHERE r.bid_ntce_no  = a.bid_ntce_no
              AND r.bid_ntce_ord = a.bid_ntce_ord
              AND r.category     = a.category
        ) AS matched
    FROM bid_announcements a
    WHERE a.category IN ('Thng', 'Cnstwk', 'Servc')
      AND a.openg_dt IS NOT NULL
      AND a.openg_dt >= NOW() - INTERVAL 30 DAY
      AND a.openg_dt <  NOW()
) t;
```

| 판정 항목 | 값 | 의미 |
| --- | --- | --- |
| `eligible_total` | 분모 | 최근 30일 안에 개찰일시가 지난 3분류 공고 수 |
| `matched_total` | 분자 | 그중 `bid_openg_results` 에 키가 맞는 행이 하나라도 있는 공고 수 |
| `coverage_ratio` | 비율 | 조건 1 의 측정값. 기준선은 이 값을 먼저 측정한 뒤 정한다 |

`EXISTS` 를 쓴 이유는 `rbid_no` 가 다른 복수 행이 분모를 부풀리지 않게 하기 위해서다. `LEFT JOIN` 으로 쓰면 같은 공고가 2행 이상으로 세어져 커버리지가 실제보다 낮게 나온다.

분모 정의를 확정하기 전에 아래 분해 질의로 구성비를 확인한다. 취소공고를 분모에 넣을지는 아직 정해지지 않았다.

```sql
SELECT
    a.ntce_kind_nm,
    COUNT(*)       AS eligible_total,
    SUM(t.matched) AS matched_total,
    ROUND(SUM(t.matched) / NULLIF(COUNT(*), 0), 4) AS coverage_ratio
FROM (
    SELECT
        a.id, a.ntce_kind_nm,
        EXISTS (
            SELECT 1
            FROM bid_openg_results r
            WHERE r.bid_ntce_no  = a.bid_ntce_no
              AND r.bid_ntce_ord = a.bid_ntce_ord
              AND r.category     = a.category
        ) AS matched
    FROM bid_announcements a
    WHERE a.category IN ('Thng', 'Cnstwk', 'Servc')
      AND a.openg_dt IS NOT NULL
      AND a.openg_dt >= NOW() - INTERVAL 30 DAY
      AND a.openg_dt <  NOW()
) t
JOIN bid_announcements a ON a.id = t.id
GROUP BY a.ntce_kind_nm
ORDER BY eligible_total DESC;
```

### 2.2 조건 2: 유찰 목록 상위 N건의 상태 일치

기대 집합을 고정하는 질의다. 목록 경로가 실행할 조건과 같은 조건으로 상위 20건을 뽑는다.

```sql
SELECT
    r.bid_ntce_no,
    r.bid_ntce_ord,
    r.category,
    r.rbid_no,
    r.progrs_div_cd_nm,
    r.openg_dt,
    a.bid_ntce_nm,
    a.dminstt_nm,
    a.ntce_kind_nm
FROM bid_openg_results r
JOIN bid_announcements a
  ON a.bid_ntce_no  = r.bid_ntce_no
 AND a.bid_ntce_ord = r.bid_ntce_ord
 AND a.category     = r.category
WHERE r.category IN ('Thng', 'Cnstwk', 'Servc')
  AND r.progrs_div_cd_nm = '유찰'
  AND r.openg_dt IS NOT NULL
  AND r.openg_dt >= NOW() - INTERVAL 30 DAY
  AND r.openg_dt <  NOW()
ORDER BY r.openg_dt DESC, r.bid_ntce_no DESC
LIMIT 20;
```

통과 기준은 두 가지다. 첫째, 20행이 반환되어야 한다. 20행보다 적으면 조인 키나 기간 조건이 목록 경로와 어긋난 것이다. 둘째, 20행의 `progrs_div_cd_nm` 이 모두 `유찰` 이어야 한다. 이 질의는 `WHERE` 로 이미 유찰만 고르므로 그 자체로는 자명하다. 그래서 아래 누출 검사를 함께 본다.

누출 검사는 같은 공고·차수·분류에 유찰과 비유찰 행이 공존하는 건수를 센다. 목록 경로 `_fetch_sample_announcements`(`src/rag/structured_data.py:2468-2474`)는 공고번호 기준으로 첫 행만 남기므로, 공존하는 공고에서 정렬 순서에 따라 비유찰 행이 표에 남을 수 있다.

```sql
SELECT COUNT(*) AS mixed_notices
FROM (
    SELECT r.bid_ntce_no, r.bid_ntce_ord, r.category
    FROM bid_openg_results r
    WHERE r.category IN ('Thng', 'Cnstwk', 'Servc')
      AND r.openg_dt IS NOT NULL
      AND r.openg_dt >= NOW() - INTERVAL 30 DAY
      AND r.openg_dt <  NOW()
    GROUP BY r.bid_ntce_no, r.bid_ntce_ord, r.category
    HAVING SUM(r.progrs_div_cd_nm = '유찰') > 0
       AND SUM(r.progrs_div_cd_nm <> '유찰') > 0
) m;
```

| `mixed_notices` | 판정 |
| ---: | --- |
| 0 | 조건 2 를 DB 데이터만으로 통과. 목록 시험은 3절 신규 시험으로 확인 |
| 1 이상 | `rbid_no` 단위 중복이 실제로 존재. 목록에서 공고번호 중복 제거를 쓰지 않거나, 유찰 행 우선 정렬을 명시해야 함 |

조건 2 는 SQL 만으로 끝낼 수 없다. 판정 대상이 "목록 경로가 내놓은 행" 이기 때문이다. T5 에서 `retrieve_structured_data` 를 `filters={"outcome": "유찰", "announcement_limit": 20}` 으로 직접 호출해 반환 표본의 상태가 전부 유찰인지 단언하는 시험을 함께 둔다. 이 시험은 표본 dict 에 `progrs_div_cd_nm` 이 실려야 성립하므로, 4절의 표본 outer join 이 선행 조건이다.

### 2.3 조건 3: 정의 질문 회귀

`detect_data_gap("유찰이 뭐야")` 는 현재 `_EXPLANATION`(`src/rag/data_gap_guard.py:61-65`)이 `뭐야` 를 잡고 `_ACTUAL_VALUE` 가 없어 `None` 을 반환한다. 가드 항목을 지운 뒤에도 정의 질문은 LLM 경로로 남는다. 기존 시험 `tests/test_definition_guard.py` 의 `UNLEARNED_TERMS`(`:62`)와 `UNLEARNED_PAIRS`(`:71`)가 `유찰` 정의 질문의 SQL 누출을 이미 막고 있다. 조건 3 은 이 시험과 아래 신규 단언으로 판정한다.

| 확인 항목 | 판정 방법 |
| --- | --- |
| 가드 미적용 | `detect_data_gap("유찰이 뭐야") is None` |
| 정형 경로 미진입 | `build_retrieval_plan("유찰이 뭐야").use_sql is False` |
| outcome 미설정 | `"outcome" not in build_retrieval_plan("유찰이 뭐야").filters` |

---

## 3. T5 에서 갱신·추가할 시험 목록

### 3.1 기존 유찰 미지원 안내를 단언하는 시험

`grep -rn "유찰" tests/` 결과와 대조했다. 가드 문구나 미지원 판정을 직접 단언하는 시험은 아래와 같다.

| 시험 (파일::이름) | 현재 단언 | T5 조치 |
| --- | --- | --- |
| `tests/test_data_gap_guard.py::test_detects_data_gap_items` | `DATA_GAP_CASES` 의 네 유찰 사례(`:47-50`)가 `유찰 상태` 를 반환 | 네 사례 삭제 |
| `tests/test_data_gap_guard.py::test_interpreter_blocks_capabilities` | `DATA_GAP_CASES` 전체를 파라미터로 받아 `data_gap` 파라미터를 단언 | 사례 삭제로 자동 정리. 추가 변경 없음 |
| `tests/test_data_gap_guard.py::test_sync_data_gap_skips_retrieval` | 같은 파라미터로 고정 안내와 `retrieval_mode="data_gap"` 단언 | 사례 삭제로 자동 정리 |
| `tests/test_data_gap_guard.py::test_every_item_has_a_fixed_message` | `DATA_GAP_CASES` 항목 집합과 `DATA_GAP_MESSAGES` 키 집합이 **같다**고 단언 | 문구를 남기면 실패. 포함 관계(`set(DATA_GAP_MESSAGES) <= items`)로 바꾸거나 유찰 키를 명시적으로 제외 |
| `tests/test_data_gap_guard.py::test_fixed_message_has_no_numbers_or_internal_terms` | `DATA_GAP_MESSAGES` 전체를 순회 | 문구를 남기면 그대로 통과. 변경 없음 |
| `tests/test_announcement_list_query.py::test_announcement_list_query_excludes_result_and_statistics_queries` (`:63`) | `"유찰 공고 5개 보여줘"` 의 `is_announcement_list_query` 가 **거짓**이라고 단언 | 참으로 바꾸고 양성 목록으로 이동. T5 라우팅 변경의 핵심 시험 |
| `tests/test_bid_number_lookup.py::test_bid_number_true_cases` (`:98`) | `"R26BK01778156 유찰이야?"` 가 공고번호 단건 필터로 라우팅된다고 단언 | 유지. outcome 과 충돌하지 않음 |

`tests/test_sajeong_competition_metric.py`(`:236`, `:254`)는 경쟁률 표본 안내 문구("유찰 공고는 표본에 포함되지 않습니다")를 단언할 뿐 가드와 무관하다. 변경하지 않는다. `tests/test_openg_results_collector.py`, `tests/test_openg_results_upsert.py`, `tests/test_backfill_openg_results.py` 는 `유찰` 을 데이터 값으로만 쓴다. 변경하지 않는다. `tests/fixtures/retrieval_plan_canonical_snapshot.json:474` 은 비교 질의 문장에 유찰이 들어간 스냅샷으로, T5 라우팅 변경이 계획 스냅샷을 바꾸는지 확인 대상이다.

### 3.2 신규 시험

| 시험 | 단언 |
| --- | --- |
| `tests/test_data_gap_guard.py` | `detect_data_gap("유찰이 뭐야") is None`, `detect_data_gap("유찰 공고 5개 보여줘") is None` |
| `tests/test_announcement_list_query.py` | `build_retrieval_plan("유찰 공고 5개 보여줘")` 의 `filters["outcome"] == "유찰"`, `filters["announcement_limit"] == 5`, `use_sql is True` |
| `tests/test_announcement_list_query.py` | `RetrievalPlan` 을 손으로 만들어 `retrieve_structured_data` 호출 시 반환 표본이 전부 유찰 (`isolated_db` 에 `BidAnnouncement` 1건 + `BidOpengResult` 유찰 1건 + 개찰완료 1건을 넣어 비유찰 배제 확인) |
| `tests/test_announcement_list_query.py` | outcome 이 없는 일반 공고 목록 질의는 `bid_openg_results` 를 조인하지 않음(결과 행 수 불변) |

---

## 4. structured 경로의 outcome 필터 확인 결과

### 4.1 현재 상태

`filters["outcome"]` 은 **어디에서도 세워지지 않는다.** 근거는 다음과 같다.

| 확인 | 결과 |
| --- | --- |
| `src/` 전체에서 `"outcome"` 문자열 | `src/app/core/observability.py:898` 의 LLM 호출 계측 속성 1건뿐. RAG 필터와 무관 |
| `filters` 에 상태 키를 넣는 코드 | `result_limit`(`src/rag/query_planning.py:3410`), `announcement_limit`(`:3413`) 만 확인됨. 상태 축 없음 |
| `_announcement_conditions` 판독 키 (`src/rag/structured_data.py:646-688`) | `institution_name`, `category`, `notice_kind`, `award_method`, 기간, 마감 창, 금액, `bid_ntce_no` 뿐. outcome 없음 |
| 계획 차단 | `src/app/services/planner_interpreter.py:127-134` 가 유찰 질의를 `data_gap` 으로 조기 반환. 계획 단계까지 오지 않음 |
| 목록 판정 | `src/rag/query_planning.py:2056` 이 `ANNOUNCEMENT_RESULT_STATUS_MARKERS`(`:1888`, 유찰 포함)로 공고 목록 판정을 거짓 처리. `announcement_limit` 이 실리지 않음 |

따라서 `src/rag/data_gap_guard.py:102` 만 지우면 유찰 질의는 정형 목록 경로가 아니라 벡터/LLM 경로로 흘러간다. 가드 해제와 목록 동작은 별개 변경이다.

### 4.2 필요한 변경 지점

| 파일:줄 | 함수 | 필요한 것 |
| --- | --- | --- |
| `src/rag/query_planning.py:2056` | `is_announcement_list_query` | 유찰 + 목록 표지 조합을 예외로 허용. 이 게이트를 열지 않으면 `:3412-3413` 에서 `announcement_limit` 이 설정되지 않아 목록 분기가 실행되지 않음 |
| `src/rag/query_planning.py:3086-3088`, `:3412-3413` | `build_retrieval_plan` | 유찰 목록 의도일 때 `filters["outcome"] = "유찰"` 설정. 결과·공고번호 단건·비교 질의에는 싣지 않도록 기존 조건과 같은 가드 적용 |
| `src/rag/structured_data.py:29-38` | import 블록 | `BidOpengResult` 추가 |
| `src/rag/structured_data.py:630-689` | `_announcement_conditions` | `filters.get("outcome") == "유찰"` 일 때 `BidOpengResult` EXISTS 서브쿼리 추가. 조인 키는 `(bid_ntce_no, bid_ntce_ord, category)`, 조건은 `progrs_div_cd_nm == "유찰"`. `rbid_no` 는 키에 넣지 않음 |
| `src/rag/structured_data.py:2427-2493` | `_fetch_sample_announcements` | 선택. 표에 유찰 라벨을 보여주거나 2.2절 시험에서 행별 상태를 단언하려면 `progrs_div_cd_nm` 을 select 에 추가해야 함. 현재 select 는 `:2446-2460` |
| `src/rag/structured_data.py:909-931` | `_result_availability_conditions` | 변경 없음. 설계 6.3절과 일치 |

`_announcement_conditions` 에 조건을 넣으면 `:1887`, `:2926`, `:3323`, `:3392` 경로에 함께 적용된다. `filters["outcome"]` 이 유찰 목록 계획에만 실리면 나머지 경로는 영향받지 않는다. 다만 `:2049-2066` 의 `_announcement_conditions_for` 는 별도 빌더이므로 outcome 을 쓰지 않는다. 축 비교 경로에서 유찰 조건이 필요하지 않다면 그대로 두는 것이 맞다.

가드 해제 뒤 `DATA_GAP_MESSAGES["유찰 상태"]` 는 참조 경로가 사라진다. `src/rag/engine.py:1590` 은 `detect_data_gap` 이 항목을 반환할 때만 이 dict 를 읽으므로, 항목을 지우면 도달하지 않는 문구가 된다. 설계 6.2절은 "적재 공백 구간의 폴백 문구로 재사용"이라고 적었지만, 현재 코드에 그 폴백을 호출하는 지점은 없다. 이 재사용을 실제로 구현할지 T5 에서 결정해야 한다.

---

## 5. 확인 못 한 항목

| 항목 | 사유 | T5 전 확인 방법 |
| --- | --- | --- |
| 조건 1 기준선 수치 | 1년 소급이 진행 중이라 분모·분자가 계속 변함 | 2.1절 질의를 소급 완료 후 실행해 측정값을 먼저 기록한 뒤 기준선 확정 |
| `rbid_no` 중복 실제 존재 여부 | DB 조회 금지. 설계 3.2절도 "확인 필요"로 남김 | 2.2절 `mixed_notices` 결과 및 유니크 키 위반 로그 확인 |
| 취소공고를 커버리지 분모에 포함할지 | 정책 미정 | 2.1절 분해 질의의 `ntce_kind_nm` 구성비를 보고 결정 |
| `DATA_GAP_MESSAGES["유찰 상태"]` 폴백 연결 지점 | 현재 코드에 호출 경로 없음 | T5 설계에서 재사용 여부 결정. 미구현이면 문구 삭제가 일관적 |

---

## 6. T5 착수 판정 요약

| 조건 | 현재 | T5 착수 가능 여부 |
| --- | --- | --- |
| 1. 적재 커버리지 | 측정 전. 소급 진행 중 | 소급 완료 후 2.1절 실행 필요 |
| 2. 목록 정확성 | 측정 전. 목록 경로에 outcome 자체가 없음 | 4.2절 계획·정형 변경 선행 필요 |
| 3. 정의 질문 회귀 | `_EXPLANATION` 우회로 이미 통과 | 회귀 시험으로 고정 필요 |

설계 6.1절의 세 조건은 모두 충족 전이다. T5 는 조건 1·2 측정값이 확정되고, 4.2절의 계획 계층 변경이 같은 작업에 포함될 때만 완결된다. 가드 항목 삭제는 그 변경의 마지막 단계여야 한다.
