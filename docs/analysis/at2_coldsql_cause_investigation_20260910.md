# RAG 정형 질의 10만 ms SQL 지연 원인 조사

> 작성일: 2026-09-10
> 조사 Task: `task_12e0b6a575b7`
> 범위: 기존 측정 산출물, 허용된 하네스·애플리케이션 코드 판독
> 주의: 본 문서는 새 측정을 실행하지 않았으며 버퍼풀 가설을 다시 검증하지 않습니다.

## 1. 결론 요약

10만 ms 대 지연은 실제 MySQL 단일 쿼리 시간이라고 확정할 수 없습니다. 현재 근거상 가장 유력한 후보는 (1) 캐시 miss 때 정형 경로가 `LIKE '%...%'`, `GROUP BY`·임시 테이블·파일 정렬 및 `corrupted_probe`를 포함한 실시간 집계를 수행하는 비용, (2) 그 비용 또는 연결 획득 대기가 `sql_ms` 구간에 함께 계상되는 계측 범위입니다.

warmup 자체가 SQL 10만 ms를 만들었다고 판정할 근거는 부족합니다. 다만 warmup은 첫 fixture 문항을 직렬로 한 번만 실행하고, 성공한 warmup trace만 후처리에서 제외하므로 캐시·DB 연결 풀 상태를 바꾸는 교란 요인이며, 실패·타임아웃 warmup의 처리와 연결 재사용 효과를 별도로 기록하지 않는 결함 후보입니다.

현재 캡슐의 허용 읽기 범위에는 실제 fixture(`data/eval/llm_quality_fixture_v2.json`)와 정형 질의 구현(`src/rag/structured_data.py`, `src/rag/engine.py`)이 없습니다. 따라서 q03/q08/q25/q31의 정확한 질문 문장, 실행 SQL 목록, SQLAlchemy checkout 대기와 실제 쿼리 실행 시간의 귀속은 이 조사에서 확정하지 않았습니다.

## 2. 가설별 판정

| 순위 | 가설 | 판정 | 확인 근거 | 남은 불확실성 |
| ---: | --- | --- | --- | --- |
| 1 | 캐시 miss의 실시간 집계가 선행 와일드카드와 집계를 포함한다 | 강한 후보 | 기존 보고서는 날짜·기관명 필터에서 snapshot을 포기하고 live 집계로 간다고 기록합니다(`docs/analysis/rag_structured_sql_coldstart_20260830.md:35-44`). 실제 digest 상위 패턴도 `dminstt_nm LIKE '%...%'`, 여러 `GROUP BY`, `corrupted_probe`입니다(`docs/analysis/rag_structured_sql_coldstart_20260830.md:153-181`). | 해당 네 문항 각각의 SQL과 실행 시간은 구현 코드·fixture 직접 판독이 필요합니다. |
| 2 | `sql_ms`가 SQL 실행 외의 연결 획득 대기 또는 동기 DB 작업을 포함한다 | 유력하지만 미확정 | 운영 엔진은 `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`입니다(`src/app/core/db.py:18-24`). `/query`는 의존성으로 만든 동기 `Session`을 `await rag_engine.get_answer(...)`에 직접 전달합니다(`src/app/api/v1/chatbot.py:541-549`). | `rag_engine`의 segment timer 시작·종료 및 SQLAlchemy checkout 시점은 허용 범위 밖이라, 대기가 `sql_ms`인지 판정하지 못했습니다. |
| 3 | warmup 하네스가 지연을 만들거나 상태를 교란한다 | 지연의 직접 원인으로는 약함, 교란 후보로 유지 | warmup은 본 측정 직전에 첫 fixture 문항을 직렬로 1회 호출합니다(`scripts/benchmark_rag_segments.py:761-778`). 하네스 전체도 `query_fn`을 순차 호출하며 동시성은 없습니다(`scripts/benchmark_rag_segments.py:786-809`). | warmup과 본 요청의 서버 DB 세션·Redis 키·HTTP 연결 재사용 여부를 기록하지 않습니다. warmup timeout/실패 trace는 별도 표본·실패 목록에 남지 않습니다. |
| 4 | 동기 블로킹 I/O가 동시 요청을 서로 막았다 | 이번 측정의 1차 설명으로는 기각에 가까움 | 하네스의 본 측정 루프는 한 요청이 끝난 뒤 다음 요청을 보내는 직렬 구조입니다(`scripts/benchmark_rag_segments.py:786-809`). 따라서 이 하네스 자체에는 동시 요청 간 이벤트 루프 경합이 없습니다. | 운영 경로의 `/query`가 동기 DB 호출을 async coroutine 안에서 수행하는지는 `src/rag/engine.py` 확인 없이는 확정할 수 없습니다. 별도 동시성 실험에서는 여전히 중요한 가설입니다. |
| 5 | trace/log 수집 오류가 SQL 지연을 만들었다 | 낮은 후보 | 하네스는 응답 header의 trace와 로그 record를 1:1 대조하고, warmup 성공 trace를 기록에서 제외합니다(`scripts/benchmark_rag_segments.py:846-865`, `:891-895`). | warmup 실패·타임아웃 trace, 로그 수집 시점의 경계 오염 가능성은 별도 계측이 필요합니다. |

## 3. warmup 하네스의 코드 판독

### 3.1 확인된 동작

1. `--warmup-rounds` 기본값은 1이며 `--no-warmup`이면 0입니다(`scripts/benchmark_rag_segments.py:649-658`, `:761-764`).
2. fixture가 있으면 warmup 질의는 `fixture_items[0]`의 `question` 또는 `query`입니다(`scripts/benchmark_rag_segments.py:765-773`). 즉 q03/q08/q25/q31만 선택한 측정에서도 warmup은 첫 번째로 정렬된 선택 문항 하나일 뿐, 네 문항 각각을 예열하지 않습니다.
3. warmup은 본 측정과 같은 `query_fn(..., timeout_sec)`을 호출하지만, 성공하고 trace header가 있는 경우에만 `warmup_traces`에 넣습니다(`scripts/benchmark_rag_segments.py:774-778`). 실패는 warmup 실패 목록이나 별도 카운터에 기록되지 않습니다.
4. `since` 시각은 warmup 직전이 아니라 warmup보다 먼저 취득됩니다(`scripts/benchmark_rag_segments.py:756-764`). 따라서 warmup 로그도 수집 대상이 되며, 성공 trace에 한해 후처리에서 제거됩니다(`scripts/benchmark_rag_segments.py:846-851`).
5. 본 측정은 `for planned in plan` 순차 루프입니다(`scripts/benchmark_rag_segments.py:786-809`). 이 코드만으로는 96개 요청이 동시에 DB 풀을 고갈시키는 설명은 성립하지 않습니다.

### 3.2 판정

warmup이 10만 ms SQL 지연을 직접 산출했다고 확정할 수는 없습니다. 오히려 warmup은 첫 문항의 Redis 캐시, 서버 측 SQLAlchemy pool의 idle 연결, DB 세션 상태를 바꾸고도 그 상태를 결과에 기록하지 않는 교란 요인입니다. 특히 `urllib.request.urlopen`을 매 요청마다 호출하는 `send_query`는 명시적인 클라이언트 연결 풀·keep-alive 세션을 관리하지 않습니다(`scripts/benchmark_rag_segments.py:419-444`). 서버 DB 연결 재사용은 `SessionLocal` 풀에 맡겨져 있으므로 warmup과 본 요청이 같은 DB 연결을 썼는지 현재 산출물만으로는 알 수 없습니다.

## 4. 네 문항 공통점

기존 산출물에서 직접 확인되는 공통점은 네 문항이 모두 cold 호출에서만 지연되었고, 모두 `use_sql=True`였다는 사실입니다(`docs/analysis/rag_structured_sql_coldstart_20260830.md:22-30`). 기존 보고서는 이 계열의 필터를 날짜 필터 또는 기관명으로 기록하고, snapshot을 포기한 뒤 live 집계로 전환한다고 설명합니다(`docs/analysis/rag_structured_sql_coldstart_20260830.md:35-44`). 또한 fixture 전체 32문항 중 이 경로가 4문항이었다고 기록되어 네 문항 집합과 일치합니다(`docs/analysis/rag_structured_sql_coldstart_20260830.md:89-90`).

다만 이는 기존 보고서의 요약 근거이지, 본 Task에서 fixture 원문을 직접 판독한 결과가 아닙니다. 정확한 공통 필드(날짜 범위, 기관명, 대상 테이블, 결과 행 수)는 fixture와 `structured_data.py`를 허용 범위에 추가한 뒤 확정해야 합니다. 현재 단계에서 “네 문항이 모두 특정 기관명 필터를 갖는다” 또는 “네 문항이 같은 테이블만 조회한다”고 단정하면 안 됩니다.

## 5. 동기 I/O와 연결 풀 귀속

`src/app/core/db.py`는 동기 SQLAlchemy `create_engine`과 동기 `Session`을 사용하고 pool 크기를 `10 + 최대 overflow 20`으로 설정합니다(`src/app/core/db.py:3-24`). `/query`는 FastAPI async endpoint이지만 `Depends(get_db)`로 받은 동기 Session을 `rag_engine.get_answer`에 전달합니다(`src/app/api/v1/chatbot.py:541-549`). 이 두 사실은 정형 경로가 동기 DB API를 사용할 가능성을 보여주지만, 실제 `retrieve_structured_data` 호출이 `asyncio.to_thread`로 감싸졌는지 여부는 현재 허용 파일만으로 확인할 수 없습니다.

따라서 “이벤트 루프 블로킹이 10만 ms의 원인”은 이번 직렬 측정의 확정 원인이 아닙니다. 동시에 요청을 보내는 별도 재현에서만 이 가설을 검증해야 하며, 직렬 하네스에서는 단일 요청의 DB 실행·풀 대기·기타 작업 시간이 그 요청의 `sql_ms`에 귀속되는지를 먼저 확인해야 합니다.

풀 대기 귀속도 현재 코드만으로 확정하지 못했습니다. `sql_ms`의 타이머가 SQLAlchemy `Session.execute` 내부만 감싸는지, 정형 질의 전체(캐시 조회·세션 checkout·여러 SQL·결과 조립)를 감싸는지 `src/rag/structured_data.py`와 `src/rag/engine.py`에서 확인해야 합니다. 따라서 97,087.81 ms를 “쿼리 실행 시간”이라고 부르지 말고, 현재는 “정형 SQL 구간 계측값”이라고 부르는 것이 정확합니다.

## 6. 다음 실험과 판정 기준

실험은 코디네이터가 실행하십시오. 본 Task에서는 Docker 재시작·DB 조회·장시간 측정을 실행하지 않았습니다.

| 목적 | 실행 방법 | 확정 기준 |
| --- | --- | --- |
| warmup 직접 효과 분리 | 동일한 4문항·동일 repetition으로 `--no-warmup`과 기본 warmup을 각각 실행하고, 각 요청의 trace별 SQL·Redis hit/miss·DB connection id를 함께 저장합니다. | warmup 유무에 따라 첫 대상 문항만 일관되게 악화되고, warmup trace 자체가 느리면 warmup 교란을 채택합니다. 두 조건의 대상 trace가 동일 분포면 warmup 직접 원인을 기각합니다. |
| warmup 요청 선택 영향 제거 | 4문항 각각을 첫 요청으로 두는 4개 순서를 사용하되, 각 조건에서 warmup 0회/1회를 비교합니다. | 항상 warmup 문항 또는 첫 cold 문항만 악화되면 캐시·연결 상태 교란입니다. 문항 자체가 반복적으로 악화되면 질의 형태 가설을 우선합니다. |
| 정확한 SQL 귀속 | 정형 경로에 SQLAlchemy `before_cursor_execute/after_cursor_execute`, `checkout/checkin` 타임스탬프를 trace_id와 함께 기록합니다. `sql_ms` timer의 시작·끝도 같은 trace로 기록합니다. | `checkout_wait + cursor_exec` 합이 `sql_ms`와 일치하면 구간이 풀 대기를 포함합니다. `cursor_exec`만 크면 DB 실행 비용입니다. 둘 다 작고 `sql_ms`만 크면 캐시·결과 조립·계측 범위 문제입니다. |
| 선행 와일드카드 확인 | q03/q08/q25/q31 각각의 생성 SQL을 캡처하고, 허용된 읽기 전용 실행기로 해당 SQL의 `EXPLAIN`을 수행합니다. | `LIKE '%...%'`, `possible_keys: None` 또는 대량 rows와 `Using temporary/filesort`가 네 문항의 cold SQL에 공통이면 live 집계 후보를 확정합니다. |
| `corrupted_probe` 기여도 확인 | 각 probe SQL에 별도 trace span을 붙여 probe별 실행 시간과 호출 횟수를 기록합니다. | probe 합계가 sql_ms의 큰 비율이면 probe를 별도 원인으로 확정하고, 작으면 주 원인 후보에서 내립니다. |
| 동기 블로킹 확인 | `/query`에 동일 4문항을 동시성 2, 4, 8로 보내고, 각 요청의 event-loop 대기·DB checkout wait·SQL 실행 시간을 비교합니다. | 동시성 증가에 따라 SQL 실행 시간은 일정한데 checkout/event-loop 대기만 증가하면 풀/동기 블로킹 가설을 확정합니다. 직렬·동시성 결과가 같으면 이 가설을 기각합니다. |
| 캐시 miss와 질의 형태 분리 | Redis 키를 문항별로 miss 상태에서 시작하여 첫 호출과 즉시 재호출을 비교하고, SQL trace를 함께 수집합니다. | 첫 호출만 느리고 재호출이 10 ms 안팎이면 캐시 miss 경로가 필요조건입니다. 재호출도 느리면 SQL 형태 또는 서버 경합을 우선 조사합니다. |

DB 계획 확인이 필요할 때는 반드시 다음 실행기 형식만 사용하십시오.

```bash
uv run python scripts/db_readonly_query.py --sql "EXPLAIN <단일 SELECT>"
```

`docker exec`, `docker compose exec`, 직접 `mysql`, 긴 벤치마크 실행은 이 조사 범위에서 사용하지 않았고 다음 실험에서도 코디네이터 승인 없이 사용하지 마십시오.

## 7. 확인하지 못한 사항

- 허용 읽기 범위에 fixture 원문이 없어 q03/q08/q25/q31의 정확한 질문·필터·기관명·기간·결과 행 수를 직접 대조하지 못했습니다.
- 허용 읽기 범위에 `src/rag/structured_data.py`와 `src/rag/engine.py`가 없어 실제 SQL 템플릿, `_snapshot_scope`, `corrupted_probe`, timer 경계, `asyncio.to_thread` 사용 여부를 직접 확인하지 못했습니다.
- 따라서 선행 와일드카드·probe·풀 대기를 10만 ms의 단일 확정 원인으로 단정하지 않았습니다. 기존 보고서의 digest/EXPLAIN 결과는 강한 후보 근거로만 사용했습니다.
- 버퍼풀 가설은 캡슐의 기검증 사실대로 이미 기각된 것으로 취급했으며, 재실험하지 않았습니다.
