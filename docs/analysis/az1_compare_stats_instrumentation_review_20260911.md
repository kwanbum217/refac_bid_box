# AZ1 compare-stats 구간 계측·측정 하네스 독립 검토

> 작성일: 2026-09-11
>
> 상태: 독립 검토 완료, 수용(pass)
>
> 대상: 브랜치 `kwanbum217/orca-az1` 커밋 `40cc943ef2d8ac20c03add100f6bbbfc37756c9b`
>
> 대상 파일: `src/app/core/latency_segments.py`, `src/app/services/dashboard.py`, `scripts/benchmark_compare_stats.py`, `tests/test_compare_stats_segments.py`, `docs/analysis/az1_compare_stats_instrumentation_20260911.md`
>
> 검토 Task: `task_9770ea9a94c0`

---

## 1. 판정

**수용한다.** 운영 기본 경로(플래그 꺼짐)에서 레코더 딕셔너리 생성, contextvar
설정, 이벤트 리스너 등록, 로그 기록이 일어나지 않는다. 반환 딕셔너리와 캐시
키와 TTL 판정은 계측 도입 전과 같다. 회차 짝짓기는 후보 0건·2건 이상을 무효로
남기고 집계에서 빼며, 명명 구간끼리의 중첩 이중 계상은 없다. 차단 결함은 없다.

이 계측은 이후 경로 최적화의 채택 여부를 판정할 근거를 만든다. 운영 경로에
부작용을 남기거나, 무효 표본을 집계에 섞거나, 중첩 구간을 소계에 두 번 넣는
방향만 결함으로 본다. 아래 2~6장이 그 판정의 근거다.

---

## 2. 플래그 꺼짐은 네 가지 부작용이 없다

`src/app/core/config.py:88` 의 `LATENCY_SEGMENT_LOGGING` 기본값은 `False` 다.

꺼진 상태에서 호출이 실제로 하는 일은 `_latency_enabled()` 의
`getattr(settings, "LATENCY_SEGMENT_LOGGING", False)` 뿐이다.

| 금지 동작 | 꺼진 상태에서 일어나는가 | 근거 |
| --- | --- | --- |
| contextvar 설정 | 아니오 | `open_compare_stats_record` 는 `src/app/core/latency_segments.py:106-107` 에서 `None` 을 바로 돌려주고 `_compare_stats_record.set` 에 닿지 않는다 |
| 이벤트 리스너 등록 | 아니오 | `_register_cursor_listeners` 는 `open_compare_stats_record` 의 활성 분기(`108행`)에서만 호출된다. `_latency_enabled()` 가 거짓이면 `87-90행` 에서 즉시 반환한다 |
| 로그 기록 | 아니오 | `log_compare_stats_segments` 는 `215-216행` 에서 즉시 반환한다 |
| 레코더 딕셔너리 생성 | 아니오 | `109-116행` 의 `record = {...}` 는 활성 분기 안에만 있다 |

`compare_stats_segment` 도 `149-151행` 에서 시간 측정 없이 `yield` 한다.
`close_compare_stats_record(None)` 는 `123-124행` 에서 즉시 반환한다.

`get_compare_stats_data` 는 플래그와 무관하게 아홉 개의 `with compare_stats_segment`
를 열지만, 꺼진 상태의 컨텍스트 매니저는 생성기 `yield` 만 하고 레코더에
쓰지 않는다. 코디네이터가 결함으로 지정한 네 동작은 발생하지 않는다.

리스너는 한 번 등록되면 프로세스 전역에 남고 해제 함수는 없다. 이는
`src/rag/structured_data.py:62-76` 과 같은 패턴이다. 운영 기본은 플래그가
꺼진 채로 프로세스가 뜨는 것이므로 등록 자체가 일어나지 않는다. 측정 세션이
플래그를 켰다가 재기동 없이 끄면 훅은 남지만, 그때도 리스너는 contextvar 가
비어 있으면 `63-66행`·`73-76행` 에서 바로 반환한다. 차단 사유가 아니다.

---

## 3. 반환값·캐시 키·TTL 은 바뀌지 않았다

`git diff main...HEAD -- src/app/services/dashboard.py` 는 import 한 줄과
`get_compare_stats_data` 의 계측 감싸기뿐이다. 관측 가능한 동작은 아래와 같다.

| 항목 | 도입 전 | 도입 후 | 판정 |
| --- | --- | --- | --- |
| 반환 키 | `announce_count`, `announce_total_base_amount`, `announce_total_prce`, `result_count`, `result_total_amt`, `matched_count`, `announce_by_month`, `result_by_month`, `agency_announce_top10` | 동일 | 불변 |
| 캐시 키 | `_compare_stats_cache_key(...)` 후 stale 이면 `:stale` 접미사 | `src/app/services/dashboard.py:507-509` 동일 | 불변 |
| TTL | stale 이면 `COMPARE_STATS_STALE_CACHE_TTL`, 아니면 `COMPARE_STATS_CACHE_TTL` | `593행` 동일 | 불변 |
| 캐시 적중 조기 반환 | `if data: return data` | `513-515행` 에서 `cache_hit = True` 만 추가한 뒤 같은 `data` 를 반환 | 불변 |

쿼리식, `_build_monthly_counts` 인자, 기관 상위 10 집계, 반환 딕셔너리 조립은
감싸기만 바뀌었다. 캐시 적중 경로의 `return data` 도 `finally` 에서 로그를
남긴 뒤 같은 객체를 돌려준다.

---

## 4. 회차 짝짓기는 모호하면 무효이고 집계에 안 섞인다

하네스는 마지막 줄을 집지 않는다. 각 회차 호출 직전의 로그 줄 수를 기억하고
그 인덱스 이후만 후보로 삼는다.

```text
scripts/benchmark_compare_stats.py:155-164  pair_round_candidates
scripts/benchmark_compare_stats.py:167-199  classify_round
scripts/benchmark_compare_stats.py:229-260  summarize_rounds
scripts/benchmark_compare_stats.py:404-415  회차 루프
```

| 후보 수 | 결과 | 집계 |
| --- | --- | --- |
| 0 | `valid=False`, `invalid_reason=no_candidate` | 제외 |
| 2 이상 | `valid=False`, `invalid_reason=ambiguous`, `candidate_count` 기록 | 제외 |
| 1, JSON 파싱 실패 | `valid=False`, `invalid_reason=parse_error` | 제외 |
| 1, 파싱 성공 | `valid=True`, 원값 보존 | 포함 |

무효 회차는 `rounds` 배열에 이유와 함께 남고, `summarize_rounds` 는
`entry.get("valid")` 인 항목만 모아 P50·최소·최대·합계를 낸다.
`tests/test_compare_stats_segments.py:142-219` 가 경계 이후만 고르기, 0건·2건
무효, 유효 원값 보존, 무효 회차 집계 제외를 값으로 단언한다. 조용히 버리거나
추측으로 채우는 분기는 없다.

남은 잔여는 후보가 정확히 하나인데 그 한 줄이 이전 회차의 지연 로그이거나
동시 요청의 줄인 경우다. 그때는 유효로 기록된다. 요청 상관 ID 가 로그에 없어
이 한 줄 오귀속은 코드만으로 막을 수 없다. 다만 직전 회차가 줄을 못 집어
무효가 된 뒤에 그 줄이 다음 회차에 혼자 나타나는 전형적인 지연은, 다음 회차
자신의 줄이 같이 보이면 `ambiguous` 로 무효가 된다. 집계에 무효 표본이 섞이는
경로는 닫혀 있다. 차단 사유가 아니다.

---

## 5. 명명 구간은 중첩되지 않는다

아홉 구간은 `get_compare_stats_data` 안에서 형제 순서로만 열린다.
한 명명 구간이 다른 명명 구간을 감싸지 않는다. RAG 경로에서
`corrupted_probe_ms` 가 `top_rows_N` 안에 들어가 소계가 이중 계상되던
형태가 아니다.

`cursor_ms` 는 레코더가 살아있는 동안의 SQLAlchemy 커서 시간의 합이다.
SQL 을 실행하는 명명 구간(`announcement_summary`, `result_summary`,
`matched_count`, `announce_by_month`, `result_by_month`,
`agency_announce_top10`)의 구간 값과 축이 달라 겹친다. 이 겹침은 이중 계상이
아니라 두 축이다.

`residual_ms` 는 `src/app/core/latency_segments.py:130` 에서
`total_ms - cursor_ms` 로 계산되며, 음수가 되지 않게 자른다. 명명 구간
소계를 `cursor_ms` 에 더하는 식은 코드와 결과 JSON 어디에도 없다.
산출물 `docs/analysis/az1_compare_stats_instrumentation_20260911.md:29-30` 도
`residual_ms` 정의를 그 식으로만 적는다. 이후 측정자가 명명 구간 합과
`cursor_ms` 를 더하면 SQL 을 두 번 세게 되므로, 그 오독만 잔여로 남긴다.
구현 결함은 아니다.

구간 사이(`is_stale`·캐시 키 계산, `utcnow`, TTL 재계산)는 명명 구간에 안
들어가고 `total_ms` 에는 들어간다. 빠진 틈이지 중첩이 아니다.

---

## 6. 계측 예외는 요청을 실패시키지 않는다

| 지점 | 삼킴 |
| --- | --- |
| 레코더 열기 | `src/app/services/dashboard.py:493-497` |
| 리스너 전후 훅 | `src/app/core/latency_segments.py:63-69`, `72-84` |
| 리스너 등록 | `100-101행` |
| 구간 기록 | `136-143행`, `164-167행` |
| 레코더 닫기 | `125-133행` |
| 페이로드·로그 | `204-210행`, `217-227행` |
| 정리 `finally` | `src/app/services/dashboard.py:597-602` |

`tests/test_compare_stats_segments.py:121-139` 는 `close_compare_stats_record` 와
`log_compare_stats_segments` 가 예외를 내도 반환 딕셔너리 키가 그대로임을
단언한다.

`compare_stats_segment` 의 `finally` 안 `return`(`164-167행`)은 기록 예외가
본문 예외와 겹치면 본문 예외까지 삼킬 수 있다. 계측이 요청을 실패시키는
방향이 아니라, 본문 실패를 가릴 수 있는 반대 방향의 잔여다. 플래그 기본값
꺼짐에서는 이 `finally` 기록 분기에 들어가지 않는다. 차단하지 않는다.

---

## 7. 화이트리스트·범위·규약

`scripts/orca_auto_approve.py:1169-1171` 의 `UV_RUN_ALLOWED_SCRIPTS` 는
`scripts/db_readonly_query.py` 와 `scripts/compare_rag_segments.py` 두 개뿐이다.
`benchmark_compare_stats` 문자열은 그 파일에 없다. `--evict-cache` 의 Redis
`DEL` 경로는 사람 승인 없이 열리지 않는다.

`git diff --name-only main...HEAD` 의 변경 파일은 허용된 다섯 개뿐이다.
`src/rag/structured_data.py` 와 `src/rag/engine.py` 의 diff 는 비어 있다.
`pyproject.toml` 과 `uv.lock` 은 이번 커밋에 없다.

산출물 문서는 계측 도구만 작성했고 측정을 실행하지 않았다고 명시한다
(`docs/analysis/az1_compare_stats_instrumentation_20260911.md:3`, `115-117`).
새 성능 수치를 주장하지 않으며, 시간 분기에 확정·개선 판정을 두지 않는다.

테스트는 `tests/test_compare_stats_segments.py` 신설뿐이고 기존 테스트 파일은
수정되지 않았다. 빈 `pass` 테스트가 없다.

빌더 `worker_done.json` 은
`.orca/capsules/task_22b15bf3f458/worker_done.json` 에 있고
`schema=ORCA_WORKER_DONE_V2`, `version=2.1.0`, `task_id=task_22b15bf3f458`,
`branch=kwanbum217/orca-az1`, `commit_count=1`,
`commit_shas=["40cc943ef2d8ac20c03add100f6bbbfc37756c9b"]`,
변경 파일 다섯, `blocking_issues=[]` 를 갖춘다.

---

## 8. 잔여

- 플래그가 꺼져 있어도 `get_compare_stats_data` 는 아홉 번 컨텍스트 매니저를
  연다. 레코더·리스너·로그는 없지만 생성기 진입 비용은 있다. 지정된 네
  부작용은 아니다.
- 로그 한 줄이 지연되어 다음 회차의 유일한 후보가 되면 그 회차는 유효로
  남는다. 무효 표본이 집계에 섞이는 것과는 다른 잔여 오귀속이다.
- 명명 구간 합과 `cursor_ms` 를 더하면 SQL 을 두 번 세게 된다. 코드는 그렇게
  더하지 않는다.
- 플래그 꺼진 채로 `get_compare_stats_data` 를 통과하는 무동작 테스트는 없다.
  레코더 API 직접 호출 테스트(`tests/test_compare_stats_segments.py:63-76`)만
  있다. 코드 추적으로 무동작은 확인했다.
