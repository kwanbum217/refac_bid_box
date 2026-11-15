# tests date bomb 점검 보고서

> 작성일: 2026-11-15
> 점검 기준 시각: 2026-11-15 (KST)
> 점검 범위: `tests/` 전체
> 정본 사양: `.orca/capsules/task_test_date_bomb_audit_20261115/capsule.yaml`

판별 기준은 다음과 같습니다. 시험이 고정 날짜·시각 리터럴로 데이터를 만들고, 검사 대상 코드가 그 시험 안에서 고정되지 않은 현재 시각(`kst_now`, `utcnow`, `datetime.now`, `date.today`, `time.time` 등)과 비교하면 후보입니다. 시험이 `now` 를 인자로 넘기거나 monkeypatch 로 고정하면 안전하며, 상대 시각(`utcnow() - timedelta(...)`)으로 데이터를 만드는 경우도 대체로 안전합니다.

---

## 1. 요약

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 검사한 시험 파일 수 | 581 | `tests/` 아래 `.py` 전체(fixtures, e2e 포함) |
| 검사한 시험 건수 | 10,909 통과 / 41 스킵 / 3 제외 / 2 xfail | `uv run pytest tests/ -q -m 'not data_assets'` |
| 정적 1차 후보 파일 수 | 46 | 고정 리터럴과 미고정 현재 시각 호출이 함께 있는 파일 |
| 정적 1차 후보 시험 수 | 1,080 | 위 46개 파일을 10개 기준일로 반복 실행한 건수 |
| 시각 이동 전량 실행에서 새로 드러난 후보 | 1 | `tests/test_vulnerability_allowlist.py::test_real_allowlist_satisfies_contract` |
| 고친 시험 수 | 0 | 2027-12-31 이전에 실패하는 date bomb 없음 |
| 표에만 기록한 항목 수 | 1 | 저장소 데이터 만료 게이트. 아래 2절과 4절 참조 |

결론은 다음과 같습니다. 2027-12-31 이전에 실패할 것으로 확인된 시험은 1건이며, 그 1건은 시험 결함이 아니라 공급망 예외 목록의 만료일을 현재 시각과 비교하는 의도된 게이트입니다. 시험 쪽에서 시각을 고정하면 이 게이트가 영구히 무력화되므로 수정하지 않았습니다. 나머지 후보는 모두 `now` 인자 전달, monkeypatch, 상대 시각 생성 중 하나로 이미 안전합니다.

---

## 2. 후보 표

`실패 시작 시각` 은 해당 시험이 실패하기 시작하는 날짜입니다. `없음` 은 고정 리터럴이 있더라도 현재 시각을 고정했거나 인자로 전달해 실제 시각에 의존하지 않는 경우입니다.

| 시험 경로::이름 | 고정 리터럴 | 비교하는 현재 시각 함수 (file:line) | 실패 시작 시각 | 처리 |
| --- | --- | --- | --- | --- |
| `tests/test_home_counts_fix_20261114.py::test_warm_task_fills_cache_with_long_ttl` | `BASE_TIME = datetime(2026, 11, 14, 12, 0)`, `bid_clse_dt = BASE_TIME + 1일` | `src/app/services/home_summary.py:211` `kst_now()` (시험 256행에서 monkeypatch) | 없음 | 수정 없음. 20e5f437 에서 이미 고정됨 |
| `tests/test_home_counts_fix_20261114.py::test_warm_schedule_task_returns_counts` | 같은 `BASE_TIME` | `src/app/services/home_summary.py:211` `kst_now()` (시험 270행에서 monkeypatch) | 없음 | 수정 없음. 20e5f437 에서 이미 고정됨 |
| `tests/test_kb_builder.py::test_memory_bound_announcements_query_streaming` | 2026-06-01 시드 | `src/app/services/kb_builder.py:142` `utcnow()` (시험 717행에서 monkeypatch) | 없음 | 수정 없음 |
| `tests/test_result_coverage.py::test_task_notifies_only_when_alert` | `W = date(2026, 8, 24)`, `AS_OF = W + 34일` | `src/tasks/coverage_tasks.py:67` `date.today()` (시험 669행에서 monkeypatch) | 없음 | 수정 없음 |
| `tests/test_this_week_window.py` 5건 | `date(2026, 10, 21)`, `date(2026, 10, 25)`, `date(2026, 10, 26)` | `src/rag/query_planning.py:853` `date.today()` (시험 58행 `_freeze`) | 없음 | 수정 없음 |
| `tests/test_vulnerability_allowlist.py::test_real_allowlist_satisfies_contract` | `.github/vulnerability-allowlist.yml` `python[0]` 의 `expires_on: 2027-03-31` | `tests/test_vulnerability_allowlist.py:87` `dt.date.today()` 로 `scripts/check_vulnerability_allowlist.py` 의 `validate(data, today)` 호출 | 2027-04-01 | 수정하지 않음. 만료 게이트이므로 시각 고정은 검사 무력화. 데이터 갱신은 쓰기 범위 밖 |
| `tests/test_mysql_stats_freshness_nightly.py::test_야간점검_조회시_쓰기명령이나_ANALYZE_실행_없음` | `NOW = datetime(2026, 9, 11, 12, 0)` | `src/app/services/mysql_stats_freshness.py:237` 의 DB `NOW()` 를 시험에서 같은 리터럴로 mock. 실시간 시계 미사용 | 없음 | 수정 없음 |
| `tests/test_institution_history.py::test_calculate_returns_default_when_insufficient_samples` 외 리터럴 시험 | `datetime(2024, 6, 15, 10, 0)` 등 | `src/ml/institution_history.py:113` `calculate_institution_win_rate` 에 `reference_date` 인자로 전달. `utcnow()` fallback 은 112행이며 리터럴 시험은 도달하지 않음 | 없음 | 수정 없음 |
| `tests/test_weekly_retrain_catchup.py` 32건 리터럴 | `datetime(2026, 9, 28, 0, 20)` 등 | `check_weekly_retrain_catchup_needed(now=...)` 로 인자 전달 | 없음 | 수정 없음 |
| `tests/test_announcement_list_query.py::test_void_announcement_list_widens_vague_recent_window_to_thirty_days` 외 | 문자열 날짜 4건 | `src/rag/query_planning.py:853` `date.today()` 이고, 시험도 140행에서 같은 `date.today()` 로 기대값을 만듦 | 없음 | 수정 없음 |
| `tests/test_dashboard_stats_parity.py`, `tests/test_axis_amount_trend_route.py`, `tests/test_bid_number_lookup.py`, `tests/test_rag_engine.py` 등 | 리터럴과 함께 `utcnow()`/`date.today()` 상대 시각으로 시드 | 비교 대상도 같은 시계를 쓰므로 실행일에 따라 결과가 바뀌지 않음 | 없음 | 수정 없음 |

정적 1차 후보 46개 파일 전체는 2026-11-16 부터 2027-03-01 까지 10개 기준일(평일 전체와 월말·월초 포함)에서 1,080건 전부 통과했습니다. 2027-12-25 전량 실행에서도 이 파일들에서 실패는 없었습니다. 요일이나 월 경계에만 드러나는 실패는 없었습니다.

---

## 3. 고친 시험별 재현·통과 근거

고친 시험은 없습니다. 따라서 시험 코드에 대한 `git diff main...HEAD -- tests/` 는 빈 결과입니다.

표에만 기록한 1건은 다음과 같이 실패 시작 시각을 실측했습니다. 시각 이동은 커밋하지 않은 임시 pytest 플러그인으로 수행했으며, `src.app.core.timeutil` 의 `utcnow`/`kst_now`/`kst_today` 와 각 모듈의 `datetime`/`date` 호출만 이동 기준 시각으로 대체했습니다.

| 기준일 | 이동 일수 | 명령 | 결과 |
| --- | --- | --- | --- |
| 2027-03-31 | 136 | `TIMEBOMB_OFFSET_DAYS=136 uv run pytest tests/test_vulnerability_allowlist.py::test_real_allowlist_satisfies_contract -q -p timebomb` | 통과 |
| 2027-04-01 | 137 | 같은 명령, `TIMEBOMB_OFFSET_DAYS=137` | 실패. `assert ['python[0]: ... 취약점을 해결하십시오'] == []` |

전량 실행 근거는 다음과 같습니다.

| 실행 | 명령 | 결과 |
| --- | --- | --- |
| 기준 시각(2026-11-15) | `uv run pytest tests/ -q -m 'not data_assets'` | 10,909 통과, 41 스킵, 3 제외, 2 xfail |
| 2027-12-25 | `TIMEBOMB_OFFSET_DAYS=405` + 임시 플러그인으로 같은 전량 실행 | 10,908 통과, 실패 1건(공급망 예외 만료 게이트) |

임시 플러그인과 실행 로그는 저장소에 커밋하지 않았습니다.

---

## 4. 확인하지 못한 것

1. `tests/test_vulnerability_allowlist.py::test_real_allowlist_satisfies_contract` 는 2027-04-01 부터 실패합니다. 원인은 시험 코드가 아니라 `.github/vulnerability-allowlist.yml` 의 `python[0]` 항목 `expires_on: 2027-03-31` 이며, 이 파일은 이번 작업의 쓰기 범위가 아닙니다. 시험 쪽에서 기준일을 고정하면 만료 감시가 사라지므로 손대지 않았습니다. 조치하려면 목록 항목을 갱신하거나 이 시험을 정기 갱신 알림으로 대체하는 결정이 먼저 필요합니다.
2. `-m 'not data_assets'` 로 제외한 3건(`tests/test_data_preservation.py`)은 격리 워크트리에 모델 가중치와 `chroma_db` 가 없어 실패하는 것으로 정상이며, 시각과 무관합니다.
3. 41건은 실행 환경 때문에 스킵되었습니다. 모델 가중치 부재, MySQL 미접속, 브라우저 바이너리 부재(e2e), `node`/`make` 부재, OCR 엔진 부재 등입니다. 스킵된 시험은 정적 검토만 했고 시각 이동 실행으로 확인하지는 못했습니다.
4. 실제 MySQL·Redis·Meilisearch 를 쓰지 않았습니다. DB 서버 시계(`NOW()`, `CURDATE()`)를 읽는 경로는 이번 시각 이동 방식으로 검증할 수 없으며, 저장소 데이터 만료 게이트처럼 운영 데이터에 날짜가 박힌 경우는 별도 점검이 필요합니다.
5. 시각 이동은 파이썬 수준의 `timeutil` 함수와 모듈의 `datetime`/`date` 호출만 대체합니다. 네이티브 확장이나 서드파티 내부에서 직접 시스템 시계를 읽는 경로는 검증 범위 밖입니다.
