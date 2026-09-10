# RAG 정형 질의 10만 ms SQL 지연 원인 조사

> 갱신일: 2026-09-10
> 조사 Task: `task_39ebe0ba85be`
> 범위: 기존 측정 산출물, 허용된 하네스·애플리케이션 코드 판독
> 주의: 본 문서는 새 측정을 실행하지 않았으며 버퍼풀 가설을 다시 검증하지 않습니다.

이번 갱신에서는 fixture 원문과 `src/rag` 코드를 대조하여 q03·q08·q25·q31의 공통 라우팅·필터를 확정하고, `sql_ms`가 `retrieve_structured_data()` 호출 전체를 계측한다는 점을 확정했습니다. 따라서 아래의 네 문항 공통점과 타이머 경계는 추론이 아니라 fixture·플래너·타이머 코드의 직접 판독 결과입니다.

## 1. 결론 요약

10만 ms 대 지연은 실제 MySQL 단일 쿼리 시간이라고 확정할 수 없습니다. 현재 근거상 가장 유력한 후보는 (1) 캐시 miss 때 정형 경로가 `LIKE '%...%'`, `GROUP BY`·임시 테이블·파일 정렬 및 `corrupted_probe`를 포함한 실시간 집계를 수행하는 비용, (2) 그 비용 또는 연결 획득 대기가 `sql_ms` 구간에 함께 계상되는 계측 범위입니다.

warmup 자체가 SQL 10만 ms를 만들었다고 판정할 근거는 부족합니다. 다만 warmup은 첫 fixture 문항을 직렬로 한 번만 실행하고, 성공한 warmup trace만 후처리에서 제외하므로 캐시·DB 연결 풀 상태를 바꾸는 교란 요인이며, 실패·타임아웃 warmup의 처리와 연결 재사용 효과를 별도로 기록하지 않는 결함 후보입니다.

이번 코드 판독으로 q03/q08/q25/q31의 공통 라우팅과 `sql_ms` 계측 경계는 확정했습니다. 다만 실제 DB에서 각 문항의 실행 시간·실행 계획을 새로 측정한 것은 아니므로, 97,087.81 ms의 개별 SQL별 귀속은 여전히 측정 과제로 남습니다.

## 2. 가설별 판정

| 순위 | 가설 | 판정 | 확인 근거 | 남은 불확실성 |
| ---: | --- | --- | --- | --- |
| 1 | 캐시 miss의 실시간 집계가 선행 와일드카드와 집계를 포함한다 | 강한 후보 | 네 문항 모두 fixture상 개별 공고의 낙찰 결과를 묻고, 플래너가 개체 지정·정형 통계 질의로 `use_sql=True`를 만듭니다(`src/rag/query_planning.py:368-383`, `:441-449`). q03/q08/q25/q31의 기관명 필터는 각각 광주·서울·세종·대전으로 추출됩니다(`src/rag/query_planning.py:430-433`). `_snapshot_scope`는 기관명 필터가 있으면 `None`을 반환합니다(`src/rag/structured_data.py:191-204`). | 실제 DB 실행 시간과 실행 계획은 측정하지 않았습니다. |
| 2 | `sql_ms`가 SQL 실행 외의 연결 획득 대기 또는 동기 DB 작업을 포함한다 | 계측 범위는 확정, 10만 ms의 직접 원인은 미확정 | `sql_ms` 타이머는 `retrieve_structured_data(db, plan)` 직전 시작해 반환 직후 끝납니다(`src/rag/engine.py:743-747`). 따라서 함수 내부의 캐시 조회·세션의 지연 checkout/SQL·다중 SQL·결과 조립·`corrupted_probe`가 포함됩니다. async 진입점은 전체 동기 경로를 `asyncio.to_thread`로 오프로드합니다(`src/rag/engine.py:1177-1185`). | 각 내부 작업의 실제 시간 비중과 checkout 대기량은 계측 없이는 분리할 수 없습니다. |
| 3 | warmup 하네스가 지연을 만들거나 상태를 교란한다 | 지연의 직접 원인으로는 약함, 교란 후보로 유지 | warmup은 본 측정 직전에 첫 fixture 문항을 직렬로 1회 호출합니다(`scripts/benchmark_rag_segments.py:761-778`). 하네스 전체도 `query_fn`을 순차 호출하며 동시성은 없습니다(`scripts/benchmark_rag_segments.py:786-809`). | warmup과 본 요청의 서버 DB 세션·Redis 키·HTTP 연결 재사용 여부를 기록하지 않습니다. warmup timeout/실패 trace는 별도 표본·실패 목록에 남지 않습니다. |
| 4 | 동기 블로킹 I/O가 동시 요청을 서로 막았다 | 이번 직렬 측정의 1차 설명으로는 기각에 가까움 | 정형 조회 함수 자체는 동기 SQLAlchemy 호출을 사용하지만(`src/rag/structured_data.py:637-747`), `get_answer()`가 `get_answer_sync()` 전체를 `asyncio.to_thread`로 감쌉니다(`src/rag/engine.py:1177-1185`). 하네스도 순차 호출입니다(`scripts/benchmark_rag_segments.py:786-809`). | 별도 동시성 실험에서 DB 풀 대기량이 증가하는지는 여전히 측정 대상입니다. |
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

fixture 원문상 네 문항은 다음과 같습니다.

| 문항 | 질문의 형태 | 플래너 필터 | 기대 결과 |
| --- | --- | --- | --- |
| q03 | 광주시 사업의 공고번호·수요기관·낙찰업체·금액·낙찰률 | `category=Servc`, `institution_name=광주` | 근거 `bid_10153847`의 확정 낙찰 정보 |
| q08 | 서울회생법원 물품 단가계약의 같은 낙찰 속성 | `institution_name=서울` | 근거 `bid_10168836`의 확정 낙찰 정보 |
| q25 | 세종 스마트시티 공사의 최종 낙찰자·금액 | `category=Cnstwk`, `institution_name=세종` | 미래 시점이므로 데이터 부재 거절 |
| q31 | 대전 유성구 공고의 미등록 낙찰업체·금액 | `category=Cnstwk`, `institution_name=대전` | 낙찰 결과 미등록이므로 거절 |

네 문항 모두 공고명 또는 공고번호·기관명으로 특정 대상을 지목하고 낙찰 결과를 묻기 때문에 `is_entity_specific_query=True`, `is_result_query=True`, `use_sql=True`, `use_vector=True`, `use_lexical=True`가 됩니다(`src/rag/query_planning.py:154-186`, `:194-204`, `:368-383`, `:457-475`). 플래너는 연도만 포함된 공고명도 개체 질의에서는 날짜 hard filter로 승격하지 않습니다(`src/rag/query_planning.py:397-410`). 따라서 넷의 실제 공통점은 날짜 범위·카테고리·결과 존재 여부가 아니라, 기관명 필터를 가진 개체 지정 낙찰 질의라는 점입니다. 기관명 필터는 `_snapshot_scope`를 `None`으로 만들어 live 경로를 선택합니다(`src/rag/structured_data.py:191-204`).

## 5. 동기 I/O와 연결 풀 귀속

`src/app/core/db.py`는 동기 SQLAlchemy `create_engine`과 동기 `Session`을 사용합니다(`src/app/core/db.py:3-24`). 정형 함수도 `db.scalar`와 `db.execute`를 직접 호출합니다(`src/rag/structured_data.py:637-747`). 그러나 async `get_answer()`는 `get_answer_sync()` 전체를 `asyncio.to_thread`에 넘기므로 정형 DB 호출은 작업 스레드에서 실행됩니다(`src/rag/engine.py:1177-1185`); `/query`는 이 async 메서드를 await합니다(`src/app/api/v1/chatbot.py:541-547`). 따라서 “async coroutine이 이벤트 루프에서 동기 DB를 직접 호출한다”는 판정은 부정되며, 동시 요청에서의 스레드풀·DB 풀 경합은 별도 가설입니다.

`sql_ms`는 SQLAlchemy `Session.execute` 한 번만 감싸는 값이 아닙니다. 시작은 `retrieve_structured_data` 호출 직전이고 종료는 반환 직후입니다(`src/rag/engine.py:743-747`). 함수 내부에는 `_cached_aggregate` 두 회와 그 내부 Redis 캐시 조회 및 miss 시 SQL 실행(`src/rag/structured_data.py:414-436`, `:656-667`), 최근 결과·표본·시계열 조회(`src/rag/structured_data.py:669`, `:741-742`, `:545-555`), `_top_rows`의 캐시 조회·single-flight·순위 SQL·`corrupted_probe`(`src/rag/structured_data.py:348-411`)가 있습니다. 세션 객체 생성 자체는 `get_db`에서 timer 이전에 이뤄지지만(`src/app/core/db.py:32-38`), SQLAlchemy의 lazy checkout이 첫 DB 작업에서 발생하면 그 대기는 timer 안에 포함됩니다. 그러므로 `sql_ms`는 “실제 SQL 실행 시간”이 아니라 해당 정형 조회 함수의 계측 구간 값으로 표기해야 합니다.

## 6. 다음 실험과 판정 기준

실험은 코디네이터가 실행하십시오. 본 Task에서는 Docker 재시작·DB 조회·장시간 측정을 실행하지 않았습니다.

| 목적 | 실행 방법 | 확정 기준 |
| --- | --- | --- |
| warmup 직접 효과 분리 | 동일한 4문항·동일 repetition으로 `--no-warmup`과 기본 warmup을 각각 실행하고, 각 요청의 trace별 SQL·Redis hit/miss·DB connection id를 함께 저장합니다. | warmup 유무에 따라 첫 대상 문항만 일관되게 악화되고, warmup trace 자체가 느리면 warmup 교란을 채택합니다. 두 조건의 대상 trace가 동일 분포면 warmup 직접 원인을 기각합니다. |
| warmup 요청 선택 영향 제거 | 4문항 각각을 첫 요청으로 두는 4개 순서를 사용하되, 각 조건에서 warmup 0회/1회를 비교합니다. | 항상 warmup 문항 또는 첫 cold 문항만 악화되면 캐시·연결 상태 교란입니다. 문항 자체가 반복적으로 악화되면 질의 형태 가설을 우선합니다. |
| 정확한 SQL 귀속 | 정형 경로에 SQLAlchemy `before_cursor_execute/after_cursor_execute`, `checkout/checkin` 타임스탬프를 trace_id와 함께 기록합니다. `sql_ms` timer의 시작·끝도 같은 trace로 기록합니다. | `checkout_wait + cursor_exec` 합과 함수 내부 부수 작업을 함께 비교해 97,087.81 ms의 구성비를 분리합니다. |
| 선행 와일드카드 및 live SQL 확인 | 네 문항은 기관명 필터 때문에 `_snapshot_scope=None`으로 live 경로를 타는 사실이 확정됐습니다. 생성 SQL을 캡처하고 허용된 읽기 전용 실행기로 단일 SELECT의 `EXPLAIN`만 수행합니다. | `dminstt_nm LIKE '%...%'`가 실제 SQL에 남고 대량 rows 또는 `Using temporary/filesort`가 확인되면 live 집계 비용 후보를 실행 계획 근거로 확정합니다. |
| `corrupted_probe` 기여도 확인 | 각 probe SQL에 별도 trace span을 붙여 probe별 실행 시간과 호출 횟수를 기록합니다. | probe 합계가 sql_ms의 큰 비율이면 probe를 별도 원인으로 확정하고, 작으면 주 원인 후보에서 내립니다. |
| 동기 블로킹 확인 | `/query`에 동일 4문항을 동시성 2, 4, 8로 보내고, 각 요청의 event-loop 대기·DB checkout wait·SQL 실행 시간을 비교합니다. | 동시성 증가에 따라 SQL 실행 시간은 일정한데 checkout/event-loop 대기만 증가하면 풀/동기 블로킹 가설을 확정합니다. 직렬·동시성 결과가 같으면 이 가설을 기각합니다. |
| 캐시 miss와 질의 형태 분리 | Redis 키를 문항별로 miss 상태에서 시작하여 첫 호출과 즉시 재호출을 비교하고, SQL trace를 함께 수집합니다. | 첫 호출만 느리고 재호출이 10 ms 안팎이면 캐시 miss 경로가 필요조건입니다. 재호출도 느리면 SQL 형태 또는 서버 경합을 우선 조사합니다. |

DB 계획 확인이 필요할 때는 반드시 다음 실행기 형식만 사용하십시오.

```bash
uv run python scripts/db_readonly_query.py --sql "EXPLAIN <단일 SELECT>"
```

`docker exec`, `docker compose exec`, 직접 `mysql`, 긴 벤치마크 실행은 이 조사 범위에서 사용하지 않았고 다음 실험에서도 코디네이터 승인 없이 사용하지 마십시오.

## 7. 확인 결과와 남은 사항

- 해소: fixture 원문과 플래너 코드로 q03/q08/q25/q31의 질문 형태, 기관명 필터, 카테고리 차이, 결과 기대 형태를 대조했습니다. 넷의 공통점은 기관명 필터를 가진 개체 지정 낙찰 질의이며, 날짜 범위 공통점은 없습니다.
- 해소: `sql_ms`의 시작·종료를 확인했습니다. 캐시 조회, 첫 SQL의 lazy checkout 대기, 함수 내부 모든 SQL, 결과 조립, `corrupted_probe`가 포함되고, 플래너·lexical/vector 검색·KB 상태·최종 answer assembly는 포함되지 않습니다.
- 해소: 정형 DB 호출은 동기 SQLAlchemy API이지만 `get_answer()`가 `asyncio.to_thread`로 전체 동기 경로를 오프로드합니다. 따라서 이벤트 루프 직접 블로킹은 이 경로의 코드 판정이 아닙니다.
- 남음: 네 문항의 개별 SQL 실행 시간, checkout 대기, `corrupted_probe` 비중은 새 계측 없이는 분리할 수 없습니다. 선행 와일드카드·probe·풀 대기를 10만 ms의 단일 확정 원인으로 단정하지 않습니다.
- 버퍼풀 가설은 캡슐의 기검증 사실대로 이미 기각된 것으로 취급했으며, 재실험하지 않았습니다.
