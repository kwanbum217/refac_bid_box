# RAG 정형 질의 SQL 콜드 스타트 풀스캔 규명 (2026-08-30)

> **작성일**: 2026-08-30
> **측정 HEAD**: `e18f591` (동결, dirty=false)
> **산출물**: [`rag_segments_warmup_20260830.json`](../../data/benchmarks/rag_segments_warmup_20260830.json)
> **결론**: Redis 캐시가 식으면 RAG 정형 질의가 최대 97초 걸립니다. 코드 주석은 이 비용을 2초로
> 적고 있으며 실측과 25~48배 차이입니다. 상세 페이지 쿼리(2026-08-30 시정)와 같은 계열의 결함입니다.

---

## 1. 발견 경위

warmup 단계를 추가한 뒤 구간 레이턴시를 재측정했습니다. warmup 은 기계적으로 정상
동작했으나(`warmup_excluded_count=1`, 성공 trace 96건 = 세그먼트 96건), **P99 와 max 가
오히려 크게 악화했습니다.**

| 구간 | 이전 P99 | 신 P99 | 이전 max | 신 max |
| --- | ---: | ---: | ---: | ---: |
| sql | 772.99 | **63,578.93** | 1,558.91 | **97,087.81** |
| total | 14,669.71 | **69,195.04** | 27,792.26 | **107,952.75** |

지연은 무작위가 아니었습니다. **q08, q25, q03, q31 네 문항의 cold 호출에만** 걸렸고
네 요청 모두 `use_sql=True` 였습니다.

```
route=개체 지정 질의, 정형 통계 질의  use_sql=True
  sql_ms=97087.81  vector_ms=5933.14  total_ms=107952.75
```

같은 네 문항을 곧바로 재측정하니 **sql P50 7.03ms, max 8.88ms** 였습니다.
**최대 10,900배 차이입니다.**

---

## 2. 기전

```
질의에 날짜 필터("2026년") 또는 기관명이 붙음
  -> _snapshot_scope() 가 None 을 반환해 사전 집계 스냅샷을 포기
  -> live_stmt 실시간 집계로 넘어감
  -> Redis 캐시 조회 (AGGREGATE_CACHE_TTL = 3,600초)
       hit  -> 7ms
       miss -> 전체 인덱스 스캔 + 임시 테이블 + 파일 정렬
               -> 46,579 ~ 97,088ms
```

`src/rag/structured_data.py:137-149` 의 `_snapshot_scope` 는 날짜나 기관명 필터가 붙으면
스냅샷을 포기합니다. 조합이 사실상 무한하기 때문이며 설계 자체는 타당합니다. 문제는
그 대체 경로의 비용입니다.

---

## 3. EXPLAIN 실측

| 쿼리 | type | key | rows | Extra |
| --- | --- | --- | ---: | --- |
| `GROUP BY bidwinnr_nm` (`bid_results`) | index | `ix_bid_results_bidwinnr_nm` | **3,267,347** | Using index; **Using temporary; Using filesort** |
| `GROUP BY dminstt_nm` (`bid_announcements`) | index | `bid_announcements_dminstt_nm_952da702` | **2,179,319** | Using index; **Using temporary; Using filesort** |
| `COUNT/AVG/SUM` (`bid_results`) | index | `ix_bid_results_cat_dt_stats` | 3,267,347 | Using index |

`GROUP BY` 두 쿼리가 전체 인덱스를 훑은 뒤 임시 테이블과 파일 정렬을 수행합니다.
버퍼 풀이 식어 있으면 그 인덱스 페이지를 디스크에서 읽어야 하므로 수십 초가 듭니다.

재현 명령은 8장에 있습니다.

---

## 4. 코드가 스스로 비용을 과소평가합니다

`src/rag/structured_data.py:236-238` 주석입니다.

> 스냅샷은 날짜 필터가 붙는 순간 포기합니다(`_snapshot_scope`). "2026년" 같은
> 흔한 표현이 곧 날짜 필터이므로 실시간 경로가 자주 타며, **그 경로가 캐시
> 없이는 매번 2초를 씁니다.** 같은 창을 다시 묻는 일이 잦으므로 캐시합니다.

**실측은 46~97초입니다. 주석의 25~48배입니다.**

원인은 측정 조건입니다. 버퍼 풀이 데워진 상태에서 재면 2초가 나오고, 식은 상태에서
재면 97초가 나옵니다. 2026-08-30 의 이전 구간 측정(M2)도 같은 함정에 빠져
sql P50 을 7.39ms 로 기록했습니다. 그 측정이 품질 측정 직후에 돌아 캐시가 이미
데워져 있었기 때문입니다.

---

## 5. 운영 영향

`AGGREGATE_CACHE_TTL = 3600` 이므로 **캐시가 만료될 때마다 다음 사용자 한 명이
최대 97초를 기다립니다.** 스냅샷은 category 조합만 미리 계산하므로 `"2026년"` 같은
흔한 표현이 들어간 질의는 전부 실시간 경로를 탑니다. fixture 32문항 중 4문항(12.5%)이
여기 해당했습니다.

Redis 재기동, TTL 만료, 신규 필터 조합이 전부 같은 결과를 냅니다.

---

## 6. 이전 판정 철회

이번 측정으로 2026-08-30 에 내린 판정 두 건을 철회합니다.

| 철회 대상 | 이유 |
| --- | --- |
| "q25, q31 은 최적화 대상이 아니다" | warm 상태만 보고 내린 판정입니다. cold 에서 61.8초, 46.6초입니다 |
| "느린 문항의 지배적 원인은 벡터 콜드 미스" | 벡터도 요인이나 지배 요인은 SQL 이었습니다 |

**단일 측정으로 판정하지 마십시오.** 캐시 상태가 다르면 같은 코드가 10,900배 다른
수치를 냅니다.

---

## 7. 남은 과업

| 순서 | 작업 | 근거 |
| --- | --- | --- |
| 1 | `GROUP BY` 두 쿼리의 임시 테이블·파일 정렬 제거 또는 사전 집계 확대 | 3장 |
| 2 | 스냅샷 적용 범위를 날짜 필터가 붙는 질의까지 넓힐 수 있는지 검토 | 2장 |
| 3 | 주석의 "2초" 를 실측값으로 정정 | 4장 |
| 4 | 캐시 만료 시 사용자가 대기하지 않도록 갱신 전략 검토 | 5장 |

**G3 컷오버 판정 전에 닫아야 합니다.** 2026-08-30 에 시정한 상세 페이지 쿼리와
같은 계열이며 사용자 체감 영향은 더 큽니다.

---

## 8. 재현

```bash
# 1. 캐시가 식은 상태에서 네 문항 측정 (Redis TTL 3,600초 경과 후)
uv run python scripts/benchmark_rag_segments.py \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --item-ids q03,q08,q25,q31 --repetitions 2 --no-warmup \
  --expected-llm-model gemma4:e2b --output /tmp/cold.json

# 2. 곧바로 다시 측정 (캐시 적중)
uv run python scripts/benchmark_rag_segments.py \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --item-ids q03,q08,q25,q31 --repetitions 2 --no-warmup \
  --expected-llm-model gemma4:e2b --output /tmp/warm.json

# 3. EXPLAIN 확인
uv run python - <<'EOF'
from sqlalchemy import text
from src.app.core.db import engine
sql = ("SELECT bidwinnr_nm, COUNT(id) AS c FROM bid_results "
       "GROUP BY bidwinnr_nm ORDER BY c DESC LIMIT 10")
with engine.connect() as conn:
    for r in conn.execute(text("EXPLAIN " + sql)):
        print(dict(r._mapping))
EOF
```

---

## 9. 정정: 비용 귀속이 부분적으로 틀렸습니다 (2026-08-30 추가)

3장에서 `GROUP BY bidwinnr_nm` 을 주 원인으로 지목했으나, **97초를 실제로 소비한
쿼리를 확인하지 않고 EXPLAIN 결과가 나쁜 후보 하나를 고른 것이었습니다.**
`performance_schema.events_statements_summary_by_digest` 로 확인한 실제 분포입니다.

| 순위 | 쿼리 | 누적 | 최대 |
| :---: | --- | ---: | ---: |
| 1 | `COUNT(bid_announcements.id) WHERE dminstt_nm LIKE concat('%',?,'%')` | 89.09s | 15,539ms |
| 2 | `bidwinnr_nm GROUP BY` (시정 완료) | 78.41s | 23,030ms |
| 3 | `dminstt_nm GROUP BY` | 72.09s | 13,160ms |
| 4 | `bid_ntce_nm GROUP BY` | 69.92s | 12,648ms |
| 5~8 | `bid_announcements.id WHERE ... LIKE concat('%',?,'%')` | 67s, 67s, 46s | 최대 27,668ms |

**시정한 것은 8개 중 하나이며 전체의 약 15%입니다.** 지배 패턴은 선행 와일드카드
`LIKE '%...%'` 계열이며 어떤 인덱스도 쓸 수 없어 항상 2,179,319행을 훑습니다.
SQLAlchemy 의 `.contains()` 가 이 형태로 컴파일됩니다.

### 9.1 `corrupted_probe` 가 가장 부당한 비용입니다

`structured_data.py:545,563,581` 의 `corrupted_probe` 는 `dminstt_nm.contains(U+FFFD)`
로 손상 문자를 찾으며, 결과는 **안내 문구 한 줄의 표시 여부**에만 쓰입니다
(`_build_hints` 의 "일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다").

`structured_data.py:274` 주석은 "첫 건에서 멈추므로 전체 스캔이 되지 않습니다" 라고
적고 있으나 **손상 행이 있을 때만 참입니다.** 없으면 없음을 증명하려고 전체를 훑고,
그것이 정상 상태입니다. 실시간 집계마다 3회 돕니다.

`structured_data.py:237` 의 "2초" 주석에 이어 **두 번째로 발견된 틀린 비용 주석**입니다.

### 9.2 시정한 변경은 유지합니다

같은 조건에서 13,446ms 가 698ms 로 떨어지고(19.3배) 반환 15행이 완전히 동일하며
누적 2위 소비자이므로 되돌리지 않습니다. **부분 개선이지 해결이 아니라는 점만
정정합니다.**

### 9.3 남은 과업

| 순서 | 작업 |
| --- | --- |
| 1 | `corrupted_probe` 3건의 비용 제거 |
| 2 | `dminstt_nm`, `bid_ntce_nm` 의 `contains()` 선행 와일드카드 대체 |
| 3 | `dminstt_nm`, `bid_ntce_nm` GROUP BY 에 날짜 인덱스 힌트 적용 |
