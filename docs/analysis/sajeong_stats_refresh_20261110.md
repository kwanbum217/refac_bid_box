# 기관별 사정률 통계 재집계 연결과 예비가격 일일 수집 중단 원인

> **작성일**: 2026-11-10
> **작성자**: Orca builder (task_6907b4cd4456)
> **범위**: I-ai 검토 F-02 (기관별 사정률 통계가 2026-10-07 이후 재집계되지 않음) 수정과 `prearng_daily` 수집 중단 원인 조사
> **코드 변경**: `src/app/services/prearng_dminstt_link.py`(신규), `src/app/services/sajeong_rate_stats.py`, `src/tasks/scheduled_tasks.py`, `scripts/link_prearng_dminstt.py`, 시험 3종
> **DB 변경**: 없음. 운영 DB 는 `scripts/db_readonly_query.py` 로 읽기 전용 조회만 했고 `--execute` 와 재집계 함수 실제 실행은 하지 않았다.
> **근거**: `.orca/capsules/task_6907b4cd4456/capsule.yaml`, [prearng_dminstt_match_20261007.md](prearng_dminstt_match_20261007.md)

---

## 1. 결론 요약

| 질문 | 판정 | 근거 |
| --- | --- | --- |
| 사정률 통계가 왜 2026-10-07 에 멈췄는가 | `rebuild_institution_sajeong_rate_stats` 의 **운영 호출부가 없었다** | `git grep` 결과 HEAD 에서 호출은 시험뿐이고 수집 경로에 없다([실측]) |
| 예비가격 일일 증분이 통계를 갱신하는가 | **이제 갱신한다** | `prearng_daily_task` 가 `saved > 0` 일 때 연결·재집계를 호출(2장) |
| 2026-10-17 이후 수집이 끊긴 원인 | **실패가 아니라 06:00 KST 크론 슬롯 누락** | 마지막 실행 2026-10-18 06:00 KST, 이후 워커가 그 시각에 떠 있지 않았음(4장, [실측]+[추정]) |
| 실패 메시지가 남아 있는가 | **남길 곳이 없다** | 스케줄 원장은 Redis 키(7일 TTL)뿐이고 DB 표가 아니다(4.1, [실측=코드]) |
| 남은 일 | 운영 DB 에서 1회 수동 연결·재집계, 기동 시 따라잡기, 영속 원장 | 5장 |

---

## 2. F-02 수정

### 2.1 결함

`institution_sajeong_rate_stats` 전 행의 `rebuilt_at` 이 2026-10-07 07:13:23 으로 같았다. 재집계 함수는 존재하지만 어느 수집 경로에서도 부르지 않아, 이후 적재분이 표에 반영되지 않았다.

| 항목 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 호출부 | 없음 | `prearng_daily_task` 적재 직후 |
| 호출 조건 | - | `saved > 0` (전량 성공·부분 실패 모두) |
| 연결 로직 | `scripts/link_prearng_dminstt.py` 에만 존재 | 서비스 모듈 1곳, 스크립트와 태스크가 공유 |

### 2.2 실행 순서

`prearng_daily_task` 는 다음 순서로 동작한다.

1. 신규 용역 공고 선택 (스레드 전용 세션)
2. 예비가격 단건 수집·적재 (스레드 전용 세션, `saved` 반환)
3. `saved > 0` 이면 스레드 안에서 세션을 새로 열어
   - `link_prearng_dminstt(session)` 로 비어 있는 `dminstt_nm` 을 공고 원장 값으로 채우고 commit
   - `rebuild_institution_sajeong_rate_stats(session)` 로 기관·지역·업종 scope 재집계
4. 반환 dict 에 `linked`, `stats_rebuilt` 를 더한다.

후속 단계 예외는 `logger.exception` 으로만 남기고 수집 결과 `status` 를 바꾸지 않는다. 연결이 실패해도 재집계는 별도로 시도하며, 재집계가 실패하면 `stats_rebuilt` 가 `None` 이 된다. `saved == 0` 이거나 신규 공고가 없어 `skipped` 이면 연결·재집계를 부르지 않는다.

### 2.3 세션 경계

`Session` 은 이벤트 루프에서 만들지 않는다. 조회·적재·후속 집계 각각 `asyncio.to_thread` 안에서 `SessionLocal()` 로 열고 `finally` 에서 닫는다. 시험 `test_daily_task_creates_sessions_inside_worker_threads` 가 세 번의 세션이 모두 워커 스레드에서 생성됨을 단언한다.

### 2.4 단일 함수화

연결 규칙(차수 정규화, 조인 SQL, 매칭 집계)을 `src/app/services/prearng_dminstt_link.py` 로 옮겼다. `scripts/link_prearng_dminstt.py` 는 같은 이름을 재수출하고 엔진 생성·출력만 담당한다. CLI 동작과 문구는 바꾸지 않았다. 시험 두 곳이 스크립트와 태스크가 같은 함수 객체를 쓰는지 확인한다.

---

## 3. DB 실측 (읽기 전용)

### 3.1 예비가격 적재 이력

```sql
SELECT DATE(collected_at) AS d, COUNT(*) AS c,
       MIN(collected_at) AS first_at, MAX(collected_at) AS last_at
FROM bid_prearng_prices
WHERE collected_at >= '2026-10-01'
GROUP BY DATE(collected_at) ORDER BY d;
```

```
d          | c      | first_at            | last_at
-----------+--------+---------------------+--------------------
2026-10-06 | 353012 | 2026-10-06 13:56:56 | 2026-10-06 14:49:44
2026-10-17 | 30     | 2026-10-17 21:00:59 | 2026-10-17 21:10:03
```

- `collected_at` 은 `utcnow()` 기본값이므로 UTC 다. 마지막 적재 2026-10-17 21:00 UTC 는 **2026-10-18 06:00 KST** 이고, `PREARNG_DAILY_HOUR = 6` 크론과 일치한다([실측]).
- 2026-10-06 은 소급 적재 353,012건, 2026-10-17 은 일일 증분 1회 30건이다.
- `rl_openg_dt` 최대값(2026-10-14)은 수집 시점 지표가 아니다. 이번 30건에는 2015~2023년 공고의 재입찰 차수가 섞여 있어 실제 개찰일이 훨씬 과거다. 수집 시점은 반드시 `collected_at` 으로 판단해야 한다([실측]).

### 3.2 사정률 통계 신선도

```sql
SELECT scope, COUNT(*) AS c, MAX(sample_count) AS max_sample, MAX(rebuilt_at) AS max_rebuilt
FROM institution_sajeong_rate_stats GROUP BY scope;
```

```
scope       | c    | max_sample | max_rebuilt
------------+------+------------+--------------------
category    | 1    | 224142     | 2026-10-07 07:13:23
institution | 1043 | 1441       | 2026-10-07 07:13:23
region      | 16   | 29093      | 2026-10-07 07:13:23
```

전 1,060행이 2026-10-07 07:13:23 에 만들어졌고 이후 재집계 흔적이 없다([실측]). 이 표가 F-02 의 직접 증거다.

### 3.3 연결 대기 행

```sql
SELECT COUNT(*) AS c FROM bid_prearng_prices
WHERE dminstt_nm IS NULL OR dminstt_nm = '';
```

```
c
-----
118
```

- 118건 = 2026-10-06 소급분 중 공고 원장에 없는 88건 + 2026-10-17 증분 30건([실측]).
- 증분 30건만 대상으로 조인 가능성을 확인한 결과 **30건 모두 연결 가능**했다. 새 경로가 운영에서 한 번 돌면 이 30건의 `dminstt_nm` 이 채워지고, 그 값이 다음 재집계의 institution scope 표본이 된다([실측]).

---

## 4. 2026-10-17 이후 수집 중단 원인

### 4.1 스케줄 기록은 Redis 에만 있고 7일 뒤 사라진다

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 기록 함수 | `_record_schedule` → `record_schedule_result` | `src/tasks/scheduled_tasks.py`, `src/tasks/worker.py` |
| 저장 위치 | Redis 키 `bidbox:worker:schedules` | `worker.py` `SCHEDULE_STATUS_KEY` |
| TTL | `OBSERVATION_TTL_SECONDS = 7 * 24 * 60 * 60` | `worker.py` |
| DB 표 | 없음 | `record_schedule_result` 는 Redis 쓰기만 한다 |

- 따라서 "수집 기록"은 DB 이력이 아니라 Redis 스냅샷이며, 워커가 7일 이상 돌지 않으면 흔적이 사라진다([실측=코드]).
- 실패 메시지는 더 남지 않는다. `notify_task_failure` 는 웹훅 발신만 하고, `prearng_daily_task` 는 부분 실패 시 그 알림조차 부르지 않는다. 실패는 `partial_failure` 반환값이 Redis 에 `success=false` 로 기록되는 것이 전부다([실측=코드]).
- 이 조사에서 Redis 원장을 직접 읽지 않았다. 위 코드 사실과 DB 실측만으로 판정했다.

### 4.2 마지막 실행과 그 이후

| 시각 (UTC) | 시각 (KST) | 사건 | 근거 |
| --- | --- | --- | --- |
| 2026-10-17 21:00~21:10 | 2026-10-18 06:00~06:10 | 일일 증분 30건 적재 | `collected_at` [실측] |
| 2026-10-18 ~ 2026-11-10 | - | 06:00 크론 실행 흔적 없음 | `collected_at` 최대값 [실측] |

같은 기간 공고 원장 수집은 계속됐다. 다만 시각이 전부 KST 낮 시간대다.

```sql
SELECT DATE(collected_at) AS d, HOUR(collected_at) AS h, COUNT(*) AS c
FROM bid_announcements WHERE collected_at >= '2026-10-17'
GROUP BY DATE(collected_at), HOUR(collected_at) ORDER BY d, h;
```

```
d          | h  | c
-----------+----+------
2026-10-17 | 4  | 3504
2026-10-18 | 11 | 31
2026-10-19 | 3  | 27
2026-10-20 | 4  | 2076
2026-10-21 | 4  | 2020
2026-10-22 | 11 | 1968
2026-10-24 | 5  | 3494
2026-10-26 | 2  | 34
2026-10-28 | 2  | 3972
2026-10-29 | 6  | 2144
2026-11-04 | 12 | 7829
2026-11-06 | 0  | 4266
2026-11-07 | 3  | 1539
2026-11-09 | 4  | 50
2026-11-10 | 6  | 2254
```

UTC 0~12시는 KST 09~21시다. 즉 이 기간 수집은 모두 작업 세션 중에 일어났고, 02:00·06:00 KST 야간 크론이 돈 흔적은 없다([실측]). 이 저장소의 운영 방식은 세션 종료 시 Docker 를 내리는 것이므로, 워커 컨테이너도 세션 동안만 살아 있다([추정] — 실행 환경의 상시 가동 여부를 영속 기록으로 확인할 수 없다).

### 4.3 코드 쪽 조건

| 조건 | 값 | 결과 |
| --- | --- | --- |
| 크론 등록 | `cron(prearng_daily_task, hour=6, minute=0)` | 등록 자체는 정상 |
| `run_at_startup` | `False` | 워커가 06:00 이후에 떠도 즉시 실행하지 않음 |
| 놓친 슬롯 보정 | 없음 | 따라잡기는 `nightly_schedule`·`development_data_refresh` 두 갈래뿐 |
| 조회 창 | `PREARNG_DAILY_LOOKBACK_DAYS = 14` | 15일 넘게 놓치면 그 사이 개찰 공고는 영구 누락 |

06:00 KST 고정 크론 + `run_at_startup=False` + 따라잡기 없음의 조합은 "워커가 그 시각에 떠 있어야만 실행"을 뜻한다. 마지막 실행이 2026-10-18 06:00 KST 인 것은 10-17 세션이 밤을 넘겨 워커가 살아 있었기 때문이고, 이후 세션은 모두 06:00 전에 끝나 슬롯이 비었다([추정]).

### 4.4 판정

- **코드 결함이 아니다.** 크론은 등록돼 있고, 마지막 실행은 정상 적재됐다. 끊긴 것은 실행 자체가 아니라 실행 기회다.
- **실패 메시지는 존재할 수 없다.** 실패를 남길 영속 저장소가 없고, 설령 2026-10-17 부분 실패가 있었더라도 Redis TTL 7일이 지나 사라졌다([실측=코드]).
- 확정할 수 없는 부분: 2026-10-18 06:00 실행이 `success` 인지 `partial_failure` 인지. 30건이 적재된 사실만 확인된다([미확정]).

---

## 5. 남은 위험과 후속

| 항목 | 내용 | 이번 범위 |
| --- | --- | --- |
| 운영 1회 반영 | 배포 후 `prearng_daily_task` 1회 실행 또는 연결·재집계 수동 실행으로 30건과 10-07 이후 적재분을 표에 반영 | 미실행 (운영 쓰기 금지) |
| 기동 시 따라잡기 | `prearng_daily` 도 `run_schedule_catchup_task` 대상에 넣어 마지막 실행이 오래됐으면 즉시 보정 | 미구현 |
| 영속 스케줄 원장 | Redis TTL 대신 DB 표에 마지막 실행·실패 사유를 남겨 7일 뒤 증거가 사라지지 않게 함 | 미구현 |
| 부분 실패 알림 | `prearng_daily_task` 부분 실패 시 `notify_task_failure` 호출 | 미구현 |

14일 창을 넘겨 누락된 공고는 소급 수집(`stream_servc_prearng_range`) 없이는 채워지지 않는다. 다음 세션에서 범위를 정해 다뤄야 한다.

---

## 6. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_sajeong_stats_refresh_20261110.py tests/test_prearng_daily_schedule.py tests/test_link_prearng_dminstt.py -q` | 24 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10,677 passed, 41 skipped, 2 xfailed, **1 failed** (범위 밖, 6.1) |
| `uv run mypy src` | Success: no issues found in 146 source files |
| `uv run ruff check <변경 파일>` | All checks passed |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |

### 6.1 범위 밖 전량 시험 실패 1건

`tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once` 가 422 를 받아 실패했다. 422 는 `src/app/api/v1/documents.py:228` 의 10초 추출 제한이며, 1만 건 넘는 전량 실행 부하에서 추출 스레드가 제한을 넘긴 것이다. 해당 파일 단독 실행은 14 passed·1 skipped, 문서 추출 시험군 4개 파일 실행도 117 passed·1 skipped 로 통과했다. 이 Task 는 OCR·문서 추출 코드를 건드리지 않았으므로 범위 밖 부하 의존 실패로 판단한다.

### 6.2 기존 시험 단언 변경 사유

| 파일 | 변경 | 사유 |
| --- | --- | --- |
| `tests/test_prearng_daily_schedule.py` | `fake_env` 에 연결·재집계 대역 추가, `_FakeSession` 에 commit·rollback 추가 | 후속 단계가 세션을 커밋·롤백하므로 대역 계약을 맞춤 |
| 같은 파일 | 성공·부분 실패 기대 dict 에 `linked`·`stats_rebuilt` 추가 | 반환 계약에 후속 결과 키가 늘어남 |
| 같은 파일 | 스레드 세션 수 2 → 3 | 후속 집계가 세 번째 스레드 세션을 연다 |
| 같은 파일 | `link_prearng_dminstt`·`rebuild_institution_sajeong_rate_stats` 대역 주입 | 실제 서비스가 대역 세션에 SQL 을 던지지 않게 함 |
