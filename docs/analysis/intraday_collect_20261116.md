# 낮 시간 증분 수집 크론 도입 (2026-11-16)

> 작성일: 2026-11-16
> 작업: task_f887b9b62e26
> 범위: 오늘(KST) 입찰공고 증분 수집과 이번 회차 검색 색인 반영

---

## 1. 배경

기존 수집은 `development_data_refresh_task`가 매일 02:00에 한 번 돌며 어제까지의
데이터만 채웠습니다. 그 결과 당일 공고가 다음 날 새벽까지 웹에 보이지 않았습니다.
웹 목록은 Meilisearch 읽기 모델을 보므로, 색인 반영도 함께 필요했습니다.

코디네이터 실측 기준 `collect_bids(db, start_date='20261116', end_date='20261116')`
한 회는 G2B API 13회 시도, 공고 931건 적재에 약 30초였습니다. 뒤따르는 대시보드
집계 재계산(`refresh_aggregates`)만 수 분이 걸리므로 낮 회차에서는 끕니다.

---

## 2. 구현 위치

| 항목 | 위치 | 내용 |
| --- | --- | --- |
| 설정 | `src/app/core/config.py` | `INTRADAY_COLLECT_ENABLED` 기본 True |
| 태스크 | `src/tasks/scheduled_tasks.py` | `intraday_collect_task`, `_intraday_collect_thread` |
| 크론 등록 | `src/tasks/worker.py` | 평일·주말 두 항목, `functions` 등록 |
| 체크포인트 제외 | `src/app/services/collector_service.py` | `resolve_collection_window` 공고·결과 MAX 조건 |
| 따라잡기 제외 | `src/tasks/scheduled_tasks.py` | `get_latest_collection_time` 오늘 공고 제외 |
| 환경 변수 예시 | `.env.example` | `INTRADAY_COLLECT_ENABLED=true` |
| 운영 문서 | `docs/ops/scheduling.md`, `docs/ops/environment_variables.md` | 크론 표, 겹침 방지, 설정 표 |
| 시험 | `tests/test_intraday_collect_20261116.py` | 계약 시험 (a)~(g) |

---

## 3. 동작

1. `INTRADAY_COLLECT_ENABLED`가 False면 `skipped:disabled`.
2. 무거운 작업 잠금이 잡혀 있으면 대기하지 않고 `skipped:heavy_task_running`.
3. `acquire_schedule_claim('intraday_collect', key='bidbox:schedule:collection_claim',
   ttl_seconds=1800)`이 acquired가 아니면 `skipped`.
4. `heavy_task_guard('intraday_collect')` 안에서 `today=kst_today(utcnow())`를
   `YYYYMMDD`로 만들고 `collect_bids(start_date=today, end_date=today,
   fetch_type='announce', refresh_aggregates=False)`를 호출합니다. 공고 4종과
   면허제한·참가가능지역만 수집하고 낙찰·개찰 결과, KB 재구축, 집계 재계산은
   하지 않습니다.
5. `MEILI_ENABLED`이면 시작 시각 이후 적재분만 `sync_search_index(db,
   collected_since=시작 시각)`으로 반영합니다.
6. `finally`에서 자기 토큰으로만 claim을 해제합니다.

수집과 색인은 스레드 전용 세션에서 수행합니다. `collect_bids`는 async 함수지만
동기 Session으로 배치 적재를 하므로, 관리 API와 같이 스레드 전용 이벤트 루프에서
돌려 워커 이벤트 루프를 막지 않습니다.

### 3.1 크론 시각

| 구분 | 발화 시각 | timeout |
| --- | --- | --- |
| 평일 | 07~20시 매시 10분 (14회) | 3600초 |
| 주말 | 12시 10분 (1회) | 3600초 |

원안은 900초였습니다. 기존 `test_cron_timeout_exceeds_default_job_timeout`이 모든
크론에 `timeout_s > WorkerSettings.job_timeout(1800)`을 요구해 900초와 충돌했고,
코디네이터 승인으로 3600초로 맞췄습니다. 실제 회차는 30초 안팎이며 수집 claim
TTL(1800초) 안에서 끝납니다.

---

## 4. 야간 수집·따라잡기 보호

낮 수집이 오늘 공고를 넣으면 `MAX(bid_ntce_dt)`와 `MAX(collected_at)`이 오늘로
올라갑니다. 이 상태에서 며칠 치 수집이 비면 야간 수집이 빠진 날을 건너뛰고,
02:00 슬롯을 놓쳐도 기동 따라잡기가 발화하지 않습니다.

- `resolve_collection_window`: 공고 `bid_ntce_dt`, 결과 `rl_openg_dt` 모두 오늘(KST)
  0시 이전 행만 체크포인트로 봅니다.
- `get_latest_collection_time`: `bid_ntce_dt`가 오늘(KST) 0시 이전인 행의
  `MAX(collected_at)`만 봅니다. 이 함수의 운영 호출부는 따라잡기 판정 한 곳입니다.

---

## 5. 시험

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_intraday_collect_20261116.py tests/test_collector_catchup.py tests/test_schedule_catchup.py tests/test_scheduled_tasks.py tests/test_env_doc_parity.py -q` | 107 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 11046 passed, 41 skipped, 2 xfailed |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과 22/22 |
| `uv run ruff check` (변경 파일) | All checks passed |

신규 시험은 실제 DB·Redis·G2B API·Meilisearch에 연결하지 않고 monkeypatch와 고정
시각만 사용합니다. `tests/test_data_preservation.py`의 데이터 자산 시험 2건은 격리
워크트리에 `data/model_files`, `chroma_db`가 없어 제외 대상입니다.

---

## 6. 남은 위험

- API 호출량: 회당 약 13회, 평일 14회차면 하루 약 182회(주말 13회). 나라장터
  동시 요청 상한과 일일 트래픽 정책 안에 있는지 병합 후 운영 로그로 확인해야
  합니다.
- 색인 부하: 회당 최대 수백~900여 건의 공고를 Meilisearch에 upsert합니다.
  `MEILI_ENABLED=false`면 색인을 건너뛰어 웹 목록에는 반영되지 않습니다.
- 겹침 회피: 야간 수집·따라잡기·KB 재구축·재학습이 잠금을 잡고 있으면 낮 회차는
  `skipped`로 끝납니다. 오래 걸리는 작업이 낮 시간에 겹치면 당일 노출이 다음
  회차로 밀릴 수 있습니다.
- 대시보드 집계: 낮 회차는 집계를 재계산하지 않으므로 상단 요약 수치는
  `warm_home_summary_task`(10분 주기) 예열과 야간 집계를 따릅니다.
- timeout 3600초는 원안 900초에서 정책 시험에 맞춰 조정한 값입니다. 실행 시간이
  길어져 잡이 겹칠 때는 수집 claim(1800초)이 먼저 만료될 수 있으므로, 실측 소요가
  30분을 넘는 경우 TTL 재검토가 필요합니다.

실서버 회차 검증(실제 적재 건수, 색인 반영, 크론 실행 이력)은 병합 뒤
코디네이터가 수행합니다.
