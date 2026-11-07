# KST/UTC 혼용 수정 회귀 검증 (2026-11-07)

> 작성일: 2026-11-07
> Task: `task_fb88a48f9ae6`
> 브랜치: `kwanbum217/kst-now-fix`
> 선행 점검: [`docs/analysis/kst_utc_mixing_audit_20261107.md`](kst_utc_mixing_audit_20261107.md)
> 범위: 점검 문서 3.2·3.3 절의 어긋남 "있음" 지점 중 Task scope 파일. DB 스키마·데이터는 변경하지 않았다.

---

## 1. 결정 구현 요약

| 결정 | 채택안 | 구현 |
| --- | --- | --- |
| D1 | A + C | `src/app/core/timeutil.py` 에 `kst_now()`·`kst_today()` 추가, 모듈 주석을 두 계열 기준으로 정정 |
| D2 | 3.2·3.3 "있음" 전부 | scope 파일의 원문 계열 비교 지점을 `kst_now()`/`kst_today()` 로 교체 |
| D3 | 공용 승격 | `bid_queries` 지역 함수 `_kst_now` 를 제거하고 `timeutil.kst_now` 사용 |
| D4 | KST 달력 | `collector_service` 수집 창 종료일을 `kst_today()` 기준 어제로 변경 |
| D5 | 독립 착수 | 이 브랜치에서 `main` 기반으로 독립 구현. `e766fe27` 병합에 의존하지 않음 |

`timeutil.kst_now()`·`kst_today()` 는 선택 인자 `base_utc` 를 받는다. 호출부가 자기 모듈의 `utcnow()` 결과를 넘기면 기존 시험의 모듈 단위 `utcnow` monkeypatch 가 그대로 유효하다. 인자를 생략하면 내부에서 `utcnow()` 를 쓴다.

---

## 2. 변경 지점

### 2.1 원문 계열(A, KST naive) 비교

| 파일:줄 | 비교 대상 컬럼 | 변경 전 | 변경 후 |
| --- | --- | --- | --- |
| `src/app/services/bid_queries.py:1128` | `bid_announcements.bid_ntce_dt`·`bid_clse_dt`, `bid_results.rl_openg_dt` | `_kst_now()` | `kst_now(utcnow())` |
| `src/app/services/bid_queries.py:1203` | `bid_announcements.bid_clse_dt` (`uncollected_legacy`) | `utcnow()` | `kst_now(utcnow())` |
| `src/app/services/dashboard.py:402` | `bid_results.rl_openg_dt` (1년 창) | `utcnow()` | `kst_now(utcnow())` |
| `src/app/services/dashboard.py:626` | `bid_results.rl_openg_dt`·`bid_announcements.bid_ntce_dt` (1년 창) | `utcnow()` | `kst_now(utcnow())` |
| `src/app/services/compare_stats_snapshots.py:215` | `bid_announcements.bid_ntce_dt`·`bid_results.rl_openg_dt` (스냅샷 창) | `started - 365d` | `kst_now(started) - 365d` |
| `src/app/services/kb_builder.py:143` | `bid_announcements.bid_ntce_dt`·`bid_results.rl_openg_dt` (색인 창) | `utcnow() - 365d` | `kst_now(now) - 365d` |
| `src/app/services/sajeong_rate_stats.py:117` | `bid_prearng_prices.rl_openg_dt` | `utcnow() - window` | `kst_now(utcnow()) - window` |
| `src/tasks/automation_steps.py:240` | `bid_announcements.bid_ntce_dt`·`bid_results.rl_openg_dt` (7일 창) | `now - 7d` | `kst_now(now) - 7d` |
| `src/tasks/scheduled_tasks.py:928` | `bid_results.rl_openg_dt` (드리프트 평가 창) | `utcnow()` | `kst_now(utcnow())` |
| `src/tasks/scheduled_tasks.py:2380` | `bid_announcements.openg_dt` (예비가격 신규 선정) | `now or utcnow()` | `now or kst_now(utcnow())` |
| `scripts/backfill_bid_restrictions.py:71` | `bid_announcements.bid_clse_dt` | `utcnow()` | `kst_now(utcnow())` |
| `scripts/backfill_openg_results.py:242` | 기간 종료일 (`bid_openg_results.openg_dt` 질의) | `utcnow().date()` | `kst_today(utcnow())` |
| `scripts/backfill_from_g2b.py:70` | 기간 종료일 (공고·낙찰 원문 날짜 질의) | `utcnow().date()` | `kst_today(utcnow())` |
| `scripts/classify_band_regime.py:222` | 기간 종료일 (`bid_announcements.bid_ntce_dt` 질의) | `utcnow().date()` | `kst_today(utcnow())` |

### 2.2 수집 창 종료일(D4)

| 파일:줄 | 대상 | 변경 전 | 변경 후 |
| --- | --- | --- | --- |
| `src/app/services/collector_service.py:132` | 수집 창 종료일 (`yesterday_str`) | `(utcnow() - 1d).date()` | `kst_today(utcnow()) - 1d` |

크론이 KST 02:00 이므로 UTC 기준 계산은 KST 달력 어제보다 하루 더 앞선 날짜를 만들었다. KST 달력 기준으로 바꿔 창이 하루 밀리지 않게 했다.

### 2.3 계열이 섞인 함수의 분리

`src/tasks/automation_steps.py:239-266` 은 한 함수에서 두 계열을 함께 비교한다. `kst_week_ago`(7일 창)는 `bid_ntce_dt`·`rl_openg_dt` 에, `utc_week_ago` 는 `collected_at` 에 쓴다. `today_start`·`stale_hours` 도 기존처럼 UTC 기준을 유지한다.

`src/app/services/kb_document_builder.py:204-219` 는 `one_year_ago`(KST)를 `bid_ntce_dt` 에, 새 선택 인자 `collected_one_year_ago`(UTC)를 `collected_at` 폴백(`:264`, `:274`)에 쓴다. `kb_builder` 가 두 기준을 함께 넘긴다. 인자를 생략하는 기존 호출은 종전과 같이 동작한다.

### 2.4 공용 헬퍼(D1·D3)

| 파일:줄 | 내용 |
| --- | --- |
| `src/app/core/timeutil.py:1-6` | 모듈 주석을 "앱이 쓰는 컬럼은 UTC naive, 나라장터 원문에서 온 컬럼은 KST naive" 로 정정 |
| `src/app/core/timeutil.py:19-27` | `kst_now()`: `utcnow()` + 고정 9시간, KST naive |
| `src/app/core/timeutil.py:30-35` | `kst_today()`: `kst_now().date()` |
| `src/app/services/bid_queries.py:1117` | 지역 함수 `_kst_now` 삭제. `timeutil.kst_now` 로 대체 |

`zoneinfo` 와 새 라이브러리는 쓰지 않았다. 한국은 일광절약시간이 없어 고정 +9시간이 맞다.

---

## 3. 의도적으로 UTC 를 유지한 지점

아래는 앱 계열(B, UTC naive) 컬럼과 비교하거나, 쓰기·경과 계측이라 기준을 바꾸면 결함이 되는 지점이다. 점검 문서 2.3절 표와 대조했다.

| 파일:줄 | 대상 | 이유 |
| --- | --- | --- |
| `src/app/services/dashboard.py:262` | `bid_dataset_summaries.rebuilt_at` | B계열 쓰기 |
| `src/app/services/compare_stats_snapshots.py:101,134` | `rebuilt_at` 신선도·나이 | B계열 비교 |
| `src/app/services/compare_stats_snapshots.py:214,220,241` | 재집계 시작·`rebuilt_at`·경과 초 | B계열 쓰기/계측 |
| `src/app/services/kb_builder.py:96,235` | `updated_at`, `last_embedding_at` | B계열 쓰기 |
| `src/app/services/sajeong_rate_stats.py:153` | `rebuilt_at` | B계열 쓰기 |
| `src/app/services/collector_service.py:252,294` | `collected_at`, `first_seen_at`, `last_seen_at` | B계열 쓰기 |
| `src/tasks/automation_steps.py:32,242,273` | `collected_at` 오늘 집계, `stale_hours` | B계열 비교 |
| `src/tasks/automation_steps.py:241,259,265` | `utc_week_ago` 로 `collected_at` 필터 | B계열 비교 |
| `src/tasks/scheduled_tasks.py:227,1413` | 실행 시각·쿨다운 | B계열 |
| `src/tasks/scheduled_tasks.py:1228,1492` | 상태 문자열·타임존 해석 | 시각 비교 아님 |
| `src/tasks/scheduled_tasks.py:1649,1727,1887,1939` | 수집·재학습·드리프트·커버리지 슬롯 | UTC 상태 원장과 비교 |
| `scripts/backfill_openg_results.py:157,207` | 원장 `updated_at` | 파일 메타데이터 |
| `scripts/backfill_from_g2b.py:69` | `started_at` (하류 동기화 기준) | UTC 경과·전달값 |
| `scripts/classify_band_regime.py:544` | `classified_at` | B계열 쓰기 |

추가로 `scripts/backfill_bid_restrictions.py:130` 의 `date.today()` 는 컨테이너 `TZ=Asia/Seoul` 에서 이미 KST 달력이므로 그대로 두었다.

---

## 4. 시험

### 4.1 신규 시험

`tests/test_kst_now_fix_20261107.py` 에 5건을 추가했다.

| 시험 | 단언 |
| --- | --- |
| `test_kst_now_adds_nine_hours` | `kst_now()` = `utcnow()` + 9시간 |
| `test_kst_today_uses_kst_calendar` | UTC 16:00 = KST 다음 날 |
| `test_uncollected_legacy_uses_kst_closing_time` | KST 10:00 마감 공고가 KST 10:30 에 마감으로 판정 |
| `test_collection_window_end_is_kst_yesterday` | KST 02:00 실행 시 창 종료일이 KST 기준 어제 |
| `test_dashboard_one_year_window_starts_from_kst` | 1년 창 경계가 KST 기준 |

### 4.2 기존 시험

기존 시험의 단언을 삭제하거나 바꾸지 않았다. `tests/test_detail_recommendations.py`, `tests/test_kb_builder.py`, `tests/test_collector_catchup.py`, `tests/test_collection_gap_alerts.py`, `tests/test_collect_partial_failure.py`, `tests/test_collector_exists_check.py`, `tests/test_dashboard_compare_stats_exists.py`, `tests/test_compare_stats_segments.py` 는 모듈 전역 `utcnow` 를 monkeypatch 한다. `kst_now(utcnow())` 형태로 호출부의 `utcnow` 결과를 넘겨 그 고정이 계속 유효하도록 했다.

| 구분 | 파일 | 변경 |
| --- | --- | --- |
| 기존 단언 변경 | 없음 | 없음 |
| 기존 시험 파일 수정 | 없음 | 없음 |

---

## 5. 범위 밖 관찰

`src/ml/institution_history.py:110` 의 `utcnow()` fallback 은 특징 3종이 모두 없을 때만 타는 경로라 이번 범위에서 고치지 않았다. 학습·추론 특징 단일화 규칙(`src/ml/features.py`) 대상이므로 별도 과제로 남긴다. 같은 이유로 `src/ml/features.py:177` 의 `pd.Timestamp.now()` 도 손대지 않았다.

`src/rag/structured_data.py` 는 `date.today()`(KST)로 만든 날짜를 원문 계열 컬럼에 비교하므로 어긋남이 없다. 이번 변경은 그 경로를 건드리지 않았다.

---

## 6. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_kst_now_fix_20261107.py tests/test_detail_recommendations.py -q` | 13 passed |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10537 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
| `uv run ruff check <변경 파일>` | All checks passed |
