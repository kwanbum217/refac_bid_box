# Meilisearch 증분 동기화 최신 차수 판정 범위 축소 (2026-11-16)

> 작성일: 2026-11-16
> 작업: task_060dbad308c2
> 범위: `sync_search_index(collected_since=...)` 경로의 최신 차수 판정 SQL

---

## 1. 배경과 원인

2026-11-16 실서버 측정에서 낮 시간 증분 수집 한 회차의 수집은 24초였지만,
`sync_search_index(collected_since=회차 시작 시각)`는 공고 193건을 색인하는 데
157초가 걸렸습니다. 이 동기화는 평일 하루 14회 돕니다.

원인은 `search_index._latest_announcements`가 `bid_queries.latest_announcement_filter`
를 쓰는 구조입니다. 이 함수의 순위 계산 서브쿼리는

```sql
row_number() OVER (PARTITION BY bid_ntce_no, category ORDER BY bid_ntce_ord DESC, ...)
```

를 `bid_announcements` 213만 행 전체에 계산한 뒤, 바깥에서 `collected_at >= :since`
조건으로 거릅니다. 실제로 필요한 파티션은 이번 수집분이 속한 수백 개뿐인데도
매 회차 213만 행 filesort 를 먼저 치렀습니다.

---

## 2. 변경

| 파일 | 위치 | 내용 |
| --- | --- | --- |
| `src/app/services/bid_queries.py` | `latest_announcement_filter` (403행) | 선택 인자 `collected_since` 추가. 주어지면 순위 계산 서브쿼리 안에 파티션 존재 조건을 넣는다 |
| `src/app/services/search_index.py` | `_latest_announcements` (353행) | 증분 동기화가 `collected_since`를 필터 함수에 그대로 넘긴다 |
| `tests/test_search_index_incremental_20261116.py` | 신규 | 계약 시험 (a)~(d)와 동기화 진입점 시험 |
| `docs/analysis/search_sync_incremental_20261116.md` | 신규 | 이 보고서 |

증분 경로의 순위 서브쿼리는 다음 조건을 갖습니다.

```sql
WHERE EXISTS (
    SELECT 1
    FROM bid_announcements AS incremental_ann
    WHERE incremental_ann.collected_at >= :since
      AND incremental_ann.bid_ntce_no = bid_announcements.bid_ntce_no
      AND incremental_ann.category = bid_announcements.category
)
```

파티션 안의 **모든 차수 행이 그대로 순위 대상**입니다. 수집일 조건은 파티션을
고르는 데만 쓰고, 어떤 행이 최신 차수인지 판정하는 식에는 들어가지 않습니다.
따라서 최신 차수가 이번에 들어온 행이 아니어도 같은 파티션의 최신 행을 고르는
의미가 유지됩니다. 바깥의 `collected_at >= :since` 조건도 종전과 같이 남습니다.

색인 문서 집합과 내용은 바뀌지 않습니다. 순위 대상 행이 전체에서 영향 파티션으로
줄어들 뿐, 각 파티션에서 고르는 행과 바깥 수집일 조건은 동일합니다.

`collected_since`가 없는 전체 동기화 경로는 인자 기본값이 `None`이라 기존 SQL과
같습니다. `bid_queries.py` 765행 부근의 `list_announcements` 호출부도 인자를
넘기지 않으므로 SQL 이 바뀌지 않습니다. 새 인덱스, 마이그레이션, 스키마 변경은
없습니다.

---

## 3. 동작 확인

### 3.1 계약 시험

| 구분 | 시험 | 확인 내용 |
| --- | --- | --- |
| (a) | `test_incremental_sync_indexes_new_latest_ordinal` | 차수 000(어제)·001(오늘)이면 증분 결과는 001 하나 |
| (b) | `test_incremental_sync_does_not_promote_older_ordinal` | 차수 001(어제)·000(오늘)이면 결과가 비고, 기존 필터 결과와 같다 |
| (c) | `test_incremental_sync_sql_limits_ranked_partitions` | 컴파일된 SQL 의 순위 서브쿼리 안에 EXISTS/IN 조건이 있다 |
| (d) | `test_incremental_sync_matches_legacy_filter_across_partitions` | 여러 파티션 조합과 세 가지 `since` 값에서 증분 결과 ID 집합이 기존 필터 결과와 정확히 같다 |
| 보조 | `test_full_sync_sql_keeps_unrestricted_ranking` | `collected_since` 없으면 EXISTS·별칭이 없는 기존 SQL |
| 보조 | `test_sync_path_uses_incremental_ranking` | `search_index._latest_announcements` 가 증분·전체 양쪽에서 기대 ID 집합을 낸다 |

시험은 SQLite 인메모리 픽스처만 쓰며 실제 MySQL·Meilisearch·Redis 에 연결하지
않습니다.

```text
uv run pytest tests/test_search_index_incremental_20261116.py tests/test_search_index.py \
  tests/test_search_index_parity.py tests/test_meili_delete_sync_20261111.py -q
79 passed
```

### 3.2 운영 DB EXPLAIN 비교

읽기 전용 `scripts/db_readonly_query.py`로 EXPLAIN 만 받았습니다. 무거운 SELECT
실행 시간은 재지 않았습니다. 비교에 쓴 `since`는 `2026-11-16 04:00:00`이고, 이
구간의 `bid_announcements` 행 수는 1,157건입니다.

수정 전 (전체 순위):

| select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- |
| PRIMARY | bid_announcements | range | ix_bid_ann_collected | 1,157 | Using index condition |
| PRIMARY | derived2 | ref | auto_key0 | 10 | Using index |
| DERIVED | bid_announcements | ALL | 없음 | 2,135,045 | Using filesort |

수정 후 (파티션 한정 순위):

| select_type | table | type | key | rows | Extra |
| --- | --- | --- | --- | --- | --- |
| PRIMARY | derived2 | ALL | 없음 | 578 | Using where |
| PRIMARY | bid_announcements | eq_ref | PRIMARY | 1 | Using where |
| DERIVED | incremental_ann | range | ix_bid_ann_collected | 1,157 | Using index condition; Using temporary; Using filesort; Start temporary |
| DERIVED | bid_announcements | ref | bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq | 1 | Using index condition; End temporary |

수정 전에는 순위 서브쿼리가 213만 행 전체를 ALL 로 읽어 filesort 했습니다. 수정
후에는 `ix_bid_ann_collected` 범위로 이번 수집분 1,157행을 먼저 읽고, 공고번호
유일 인덱스로 해당 파티션 행만 붙여 순위를 매깁니다. 전체 테이블 스캔과 213만 행
정렬이 사라졌습니다.

---

## 4. 남은 확인

- 실서버 회차 시간 단축 폭은 코디네이터가 병합 뒤 실제 증분 수집 회차로 잽니다.
- 전체 동기화와 `list_announcements` SQL 은 종전과 같으므로 그쪽 레이턴시 변화는
  기대하지 않습니다.
