# KST/UTC 시각 기준 혼용 전수 점검 (2026-11-07)

> 작성일: 2026-11-07
> Task: `task_b1fd06e6e29c`
> 브랜치: `kwanbum217/kst-utc-audit`
> 범위: `src/app`, `scripts` 의 시각 함수 사용 지점과 DB DateTime 컬럼 대조. **코드는 고치지 않는다(조사 전용).**
> 선행 결함: `e766fe27` 공고 상세 추천 마감 판정(KST 원문 시각을 `utcnow()` 로 비교해 9시간 어긋남)

---

## 1. 점검 배경과 판정 기준

### 1.1 확인된 선행 결함

`b1fd06e6e29c` 의 발단은 공고 상세 추천의 마감 판정이었다.

- `bid_announcements.bid_clse_dt` 는 나라장터 원문 `bidClseDt` 문자열을 **변환 없이** 저장한다(원문 시각 = KST naive).
- 판정은 `utcnow()`(UTC naive)를 썼다. 그 결과 마감 후 9시간 동안 마감된 공고가 "진행 중"으로 남았다.
- 재작업 `e766fe27` 은 `bid_queries._kst_now()` (`utcnow() + 9h`) 를 도입해 그 지점만 고쳤다.

이 문서는 **같은 유형이 저장소 전체에 얼마나 있는지**를 전수로 센다. 결론은 3·4절에 두고, 수정 방안은 채택하지 않는다(사용자 결정 항목).

### 1.2 판정 기준: 컬럼마다 "무엇이 값을 쓰는가"

시각 비교가 어긋나는지를 정하는 것은 비교 코드가 아니라 **컬럼에 값이 들어오는 경로**다. 저장소는 두 계열로 갈린다.

| 계열 | 값의 출처 | 실효 기준 | 근거 |
| --- | --- | --- | --- |
| A. 원문 계열 | 나라장터 OpenAPI 문자열을 `_parse_datetime`/`parse_changed_at` 로 그대로 파싱 | **KST naive** | `src/app/services/api_collector.py:113-122`, `src/app/services/demand_institutions.py:42-55` |
| B. 앱 계열 | `utcnow()` 또는 모델 `default=utcnow` | **UTC naive** | `src/app/core/timeutil.py:10-15` |

`_parse_datetime` 은 `datetime.strptime` 만 하고 tz 를 붙이지 않는다. 즉 문자열에 적힌 벽시계 시각이 그대로 남는다.

### 1.3 운영 DB 표본 대조 (원문 = 저장값)

`uv run python scripts/db_readonly_query.py` 로만 조회했다. `docker exec`, `mysql` 직접 호출, 쓰기는 쓰지 않았다.

| 테이블 | 컬럼 | 저장값 | 원문 필드 | 판정 |
| --- | --- | --- | --- | --- |
| `bid_announcements` (id 10352948) | `bid_ntce_dt` | `2026-11-06 15:48:49` | `bidNtceDt` = `2026-11-06 15:48:49` | A. 원문 일치 |
| `bid_announcements` (id 10352948) | `bid_clse_dt` | `2026-11-12 10:00:00` | `bidClseDt` = `2026-11-12 10:00:00` | A. 원문 일치 |
| `bid_announcements` (id 10352948) | `collected_at` | `2026-11-07 03:48:51` | 없음(앱 생성) | B. UTC |
| `bid_results` (id 4459531) | `rl_openg_dt` | `2026-11-06 14:22:02` | `rlOpengDt` = `2026-11-06 14:22:02` | A. 원문 일치 |
| `bid_openg_results` (id 1291871) | `openg_dt` | `2026-11-06 18:00:00` | `opengDt` = `2026-11-06 18:00:00` | A. 원문 일치 |
| `g2b_demand_institutions` (ZT06054) | `chg_dt` | `2026-10-14 11:08:48` | `chgDt` = `2026-10-14 11:08:48` | A. 원문 일치 |
| `bid_prearng_prices` (id 359421) | `rl_openg_dt` | `2026-10-13 16:06:07` | `rlOpengDt` 동일 | A. 원문 일치 |
| `bid_dataset_summaries` (announcement) | `rebuilt_at` | `2026-09-26 14:13:34` | 없음(앱 생성) | B. UTC |

B 계열 판정의 결정적 증거는 시각의 **방향**이다. 조회 시점의 DB UTC 현재 시각은 `2026-11-07 06:05:49` 이고 `MAX(bid_announcements.collected_at)` 는 `2026-11-07 03:48:54` 였다. 앱이 KST 로 값을 썼다면 최댓값이 현재 UTC 시각보다 9시간 **앞선다**. 앞서지 않으므로 B 계열은 UTC naive 다.

`information_schema.columns` 에서 `data_type IN ('datetime','timestamp')` 이면서 `column_default IS NOT NULL` 인 컬럼은 0건이었다. 즉 DB 기본값으로 채워지는 시각 컬럼은 없고, 모든 시각은 애플리케이션이 쓴다.

### 1.4 컨테이너 시간대가 만드는 함정

`docker-compose.yml:86`(app), `:175`(worker), `docker-compose.prod.yml:79,173,253` 이 모두 `TZ=Asia/Seoul` 이다. 그래서 같은 프로세스 안에서

- `utcnow()` → UTC naive (05:58)
- `date.today()`, `datetime.now()` → **KST** (14:58)

가 공존한다. 실측으로 확인했다(`TZ=Asia/Seoul` 에서 `date.today()=2026-11-07`, `datetime.now()=14:58`, `utcnow()=05:58`). 따라서 `date.today()` 는 A 계열에는 맞고 B 계열에는 9시간 앞서며, `utcnow()` 는 그 반대다. 2단계 표의 "현재 기준" 열은 이 둘을 구분해 적는다.

---

## 2. 1단계: DateTime 컬럼 기준표

### 2.1 조사 방법

`src/app/models/*.py` 에서 `DateTime` 을 전수 grep 했다(총 56개 컬럼, 28개 테이블). 각 컬럼마다 **값을 쓰는 코드 줄**을 찾아 A/B 를 판정하고, 표본 대조가 가능한 것은 1.3절에 적었다.

### 2.2 원문 계열(A, KST naive)

| 테이블.컬럼 | 쓰는 코드 | 표본 대조 |
| --- | --- | --- |
| `bid_announcements.bid_ntce_dt` | `api_collector.py:368` `_parse_datetime(bidNtceDt)` | 1.3 확인 |
| `bid_announcements.bid_clse_dt` | `api_collector.py:369` `_parse_datetime(bidClseDt)` | 1.3 확인 |
| `bid_announcements.openg_dt` | `api_collector.py:370` `_parse_datetime(opengDt)` | 원문 동일 필드 |
| `bid_results.rl_openg_dt` | `api_collector.py:330` `_parse_datetime(rlOpengDt)` | 1.3 확인 |
| `bid_openg_results.openg_dt` | `api_collector.py:677` | 1.3 확인 |
| `bid_prearng_prices.rl_openg_dt` | `api_collector.py:787` | 1.3 확인 |
| `bid_prearng_prices.mkng_dt` | `api_collector.py:788` | 원문 동일 필드 |
| `bid_prearng_prices.inpt_dt` | `api_collector.py:789` | 원문 동일 필드 |
| `bid_announcement_license_limits.rgst_dt` | `api_collector.py:578` | 원문 동일 필드 |
| `bid_announcement_participation_regions.rgst_dt` | `api_collector.py:590` | 원문 동일 필드 |
| `g2b_demand_institutions.chg_dt` | `demand_institutions.py:481` → `parse_changed_at` (`:42-55`) | 1.3 확인 |

`g2b_demand_institutions.rgst_dt` 는 `demand_institutions.py:480` 에서 `varchar(20)` 문자열로 저장되므로 DateTime 목록에서 제외했다(모델 `demand_institutions.py:29` 도 `String(20)`).

### 2.3 앱 계열(B, UTC naive)

모델 `default=utcnow` / `onupdate=utcnow` 로 선언되거나, 서비스에서 `utcnow()` 를 명시 대입한다.

| 테이블.컬럼 | 선언·대입 |
| --- | --- |
| `bid_announcements.collected_at` | `models/bids.py:396-398` default=utcnow |
| `bid_results.collected_at` | `models/bids.py:248-250` |
| `bid_openg_results.first_seen_at`, `last_seen_at`, `collected_at` | `models/openg_results.py:107-119`; `collector_service.py:294,302-304` |
| `bid_prearng_prices.collected_at` | `models/prearng_prices.py:109-111` |
| `bid_announcement_license_limits.collected_at` | `models/bid_restrictions.py:64-66` |
| `bid_announcement_participation_regions.collected_at` | `models/bid_restrictions.py:97-99` |
| `g2b_demand_institutions.fetched_at` | `models/demand_institutions.py:31-32`; `demand_institutions.py:483` |
| `bid_dataset_summaries.source_latest_collected_at`, `rebuilt_at` | `models/bids.py:521-530` |
| `bid_ranking_snapshots.rebuilt_at` | `models/bids.py:572-578` |
| `bid_compare_stats_snapshots.rebuilt_at` | `models/bids.py:603-609` |
| `institution_win_rate_stats.rebuilt_at` | `models/bids.py:652-658` |
| `institution_sajeong_rate_stats.rebuilt_at` | `models/prearng_prices.py:162-166`; `sajeong_rate_stats.py:153` |
| `bid_announcement_regime.classified_at` | `models/announcement_regime.py:81-83` |
| `automation_requests.created_at/confirmed_at/started_at/completed_at` | `models/chatbot.py:81-84`; `automation_orchestrator.py:272,303,309,436,486,496,515,555,562` |
| `chat_session_states.created_at/updated_at` | `models/chatbot.py:114-117`; `conversation_state.py:356,373` |
| `automation_subscriptions.last_run_at/next_run_at/created_at/updated_at` | `models/chatbot.py:147-155` (현재 쓰기 호출부 없음) |
| `knowledge_base_status.last_embedding_at/updated_at` | `models/chatbot.py:174-182`; `kb_builder.py:96,235,250` |
| `pipeline_executions.started_at/ended_at/created_at/updated_at` | `models/chatbot.py:215-235` |
| `accounts_customuser.last_login/date_joined` | `models/accounts.py:34,44`; `api/ui.py:803`, `api/v1/accounts.py:457,495,581` |
| `accounts_session_generation.updated_at` | `models/accounts.py:79`; `core/security.py:334` |
| `account_company_profiles.created_at/updated_at` | `models/company_profiles.py:92-94` |
| `account_qualification_facts.created_at/updated_at` | `models/company_profiles.py:138-140` |
| `account_consent_events.consented_at` | `models/company_profiles.py:167`; `api/v1/accounts.py:457` |
| `bid_evaluation_profiles.created_at/updated_at` | `models/evaluations.py:62-64` |
| `bid_evaluation_snapshots.created_at` | `models/evaluations.py:106` |
| `prediction_results.predicted_at` | `models/predictions.py:43` |
| `retrain_logs.created_at` | `models/predictions.py:58` |

### 2.4 1단계 판정 요약

- 원문 계열 11개 컬럼이 **KST naive** 다. 공고·낙찰·개찰·예비가격·기관변경 시각이 모두 여기 들어간다.
- 앱 계열 45개 컬럼이 **UTC naive** 다. 수집·집계·세션·동의 시각이 여기 들어간다.
- **같은 테이블 안에 두 계열이 섞여 있다.** `bid_announcements` 는 `bid_ntce_dt`/`bid_clse_dt`/`openg_dt` 가 KST 이고 `collected_at` 이 UTC 다. `bid_openg_results` 도 `openg_dt`(KST) 와 `first_seen_at`(UTC) 이 한 행에 공존한다. 이것이 이 결함 유형의 구조적 원인이다.
- `features.py` 가 `openg_dt`, `bid_clse_dt`, `bid_ntce_dt` 를 한 기준 시각으로 함께 쓰고(`src/ml/features.py:173`), `_resolve_reference_date` 도 같은 셋을 쓴다(`src/ml/institution_history.py:98`). 셋 다 A 계열이라 **특징 내부는 정합**하다. 그러나 fallback 이 `pd.Timestamp.now()`(`features.py:177`)와 `utcnow()`(`institution_history.py:110`)여서, 세 값이 모두 없을 때만 9시간 어긋난다.

---

## 3. 2단계: 비교 지점 전수표

### 3.1 조사 방법

리뷰어가 쓰는 명령과 같은 grep 을 돌렸다.

```
grep -rn 'utcnow()\|datetime.now(\|date.today()' src/app --include=*.py
```

`src/app` 의 파이썬 파일에서 59줄이 나왔다(`core/timeutil.py` 자체의 정의·주석 3줄 포함). 이 중 **컬럼과 시각을 비교하거나 창(window)을 계산하는 지점**만 추렸다. 값을 쓰기만 하는 지점(대입)과 경과시간 계측(레이턴시)은 비교가 아니므로 뺐다. `scripts` 는 같은 방식으로 훑어 컬럼 비교가 있는 지점만 넣었다.

### 3.2 어긋남 판정표 (src/app)

| 파일:줄 | 비교 대상 컬럼 | 현재 기준 | 컬럼 기준 | 어긋남 | 사용자 영향 |
| --- | --- | --- | --- | --- | --- |
| `services/bid_queries.py:967` | `bid_clse_dt` (`uncollected_legacy`) | `utcnow()` UTC | KST | **있음 (9h)** | 공고 상세 제한정보 안내. 마감 후 9시간 동안 옛 공고를 "수집 전 진행 중"으로 표시 |
| `services/dashboard.py:403,422,434,449` | `bid_results.rl_openg_dt` | `utcnow()-365d` | KST | **있음 (9h)** | 대시보드 기관·업체 TOP10, 월별 추세의 1년 경계가 9시간 앞. 경계 부근 1일치만 영향 |
| `services/dashboard.py:517,540` | `bid_announcements.bid_ntce_dt` | `utcnow()-365d` | KST | **있음 (9h)** | 비교통계 기관별 공고 TOP10, 공고 월별 건수의 1년 경계 |
| `services/dashboard.py:550` | `bid_results.rl_openg_dt` | `utcnow()` | KST | **있음 (9h)** | 위와 같은 경계 |
| `services/dashboard.py:627` | 위 4개 경로의 `one_year_ago` | `utcnow()-365d` | KST | **있음 (9h)** | `get_compare_stats_data` 폴백 집계 |
| `services/compare_stats_snapshots.py:155,180,195,207` | `bid_ntce_dt`, `rl_openg_dt` | `utcnow()-365d` | KST | **있음 (9h)** | 스냅샷 재집계. 스냅샷이 하루 1회라 경계 1일치만 어긋남 |
| `services/compare_stats_snapshots.py:215` | 같음 (재집계 기준) | `utcnow()` | KST | **있음 (9h)** | 같음 |
| `services/kb_builder.py:142,200` | `bid_ntce_dt`, `rl_openg_dt` | `utcnow()-365d` | KST | **있음 (9h)** | RAG 지식베이스 색인 1년 경계. 경계 부근 공고가 색인에서 빠지거나 남음 |
| `services/kb_document_builder.py:218,228` | `bid_ntce_dt` | `utcnow()-365d` | KST | **있음 (9h)** | 위 색인 대상 선정 |
| `services/sajeong_rate_stats.py:117,128` | `bid_prearng_prices.rl_openg_dt` | `utcnow()-window` | KST | **있음 (9h)** | 사정률 분포 집계 창 경계. 경계 1일치 |
| `services/collector_service.py:132` | (A계열 아님) 수집 창 종료일 | `utcnow()` | KST 벽시계 | **있음 (9h)** | KST 00:00~09:00 실행 시 "어제"가 하루 전으로 계산돼 창이 하루 밀림. 크론이 KST 02:00 이라 상시 해당 |
| `services/collector_service.py:174,184` | `bid_ntce_dt`/`rl_openg_dt` **max** | 비교 아님(체크포인트) | KST | 없음 | max 날짜만 쓰므로 기준 무관 |
| `services/collector_service.py:252,294` | `collected_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/ranking_snapshots.py:141` | `rebuilt_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/ranking_snapshots.py:163,215` | `rebuilt_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/advisory_engine.py:46,53` | `knowledge_base_status.updated_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/advisory_engine.py:190,193,206` | `automation_requests.created_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/automation_orchestrator.py:343,346` | `pipeline_executions.ended_at/started_at/created_at` | `utcnow()` | UTC | 없음 | 일치 |
| `api/v1/chatbot_confirmation.py:50,57` | `automation_requests.created_at` | `utcnow()-24h` | UTC | 없음 | 일치 |
| `services/result_coverage.py:665` | (억제 만료일, 컬럼 아님) | `date.today()` KST | — | 없음 | A계열 날짜와 같은 달력 |
| `services/mysql_stats_freshness.py:240` | InnoDB 통계 시각 | `datetime.now()` | MySQL `NOW()` | 없음(대체 경로) | `parse_last_update` 실패 시에만. `NOW()` 는 DB 세션 TZ(SYSTEM=UTC) |
| `core/security.py:334` | `session_generations.updated_at` | `utcnow()` | UTC | 없음 | 일치 |
| `services/demand_institutions.py:518` | (API 질의 종료일) | `date.today()` KST | — | 없음 | 원문 날짜 질의라 KST 달력이 맞음 |
| `services/demand_institutions.py:506` | `chg_dt` (max) | 비교 아님 | KST | 없음 | max 날짜만 씀 |

### 3.3 어긋남 판정표 (그 밖의 호출 경로)

| 파일:줄 | 비교 대상 | 현재 기준 | 컬럼 기준 | 어긋남 | 영향 |
| --- | --- | --- | --- | --- | --- |
| `src/tasks/automation_steps.py:239-250` | `bid_ntce_dt`, `rl_openg_dt` | `utcnow()-7d` | KST | **있음 (9h)** | 자동화 "최근 7일 신규" 건수. 경계 9시간 |
| `src/tasks/automation_steps.py:34,254,259,279` | `collected_at` | `utcnow()` | UTC | 없음 | 기준 일치 |
| `src/tasks/scheduled_tasks.py:2380-2390` | `bid_announcements.openg_dt >= utcnow()-lookback` | UTC | KST | **있음 (9h)** | 예비가격 신규 용역 공고 선정 창 경계 9시간 |
| `src/tasks/scheduled_tasks.py:928-930` | `bid_results.rl_openg_dt` (드리프트 평가 창) | `utcnow()` | KST | **있음 (9h)** | 드리프트 평가 구간 경계. 경계 부근 몇 시간 |
| `src/tasks/scheduled_tasks.py:2462` | `bid_announcements.bid_ntce_dt` (띠 판별 lookback) | `utcnow().date()` | KST | **있음 (9h)** | KST 00:00~09:00 에는 시작일이 하루 앞. 대상 1일치 |
| `src/ml/features.py:177` | 기준 시각 fallback | `pd.Timestamp.now()` KST | KST | 없음 | A계열과 같은 달력(세 값이 모두 없을 때만) |
| `src/ml/institution_history.py:110` | 기준 시각 fallback | `utcnow()` UTC | KST | **있음 (9h)** | 특징 3종이 전부 없을 때만. 정상 경로에서는 안 탐 |
| `scripts/backfill_bid_restrictions.py:71` | `bid_clse_dt >= utcnow()` | UTC | KST | **있음 (9h)** | 백필 대상 시작일 산정. 운영 상시 경로 아님 |
| `scripts/backfill_openg_results.py:242` | (기간 종료일) | `utcnow().date()` | KST | **있음 (9h)** | 기본 종료일이 KST 00:00~09:00 에 하루 앞 |
| `scripts/backfill_from_g2b.py:70` | (기간 종료일) | `utcnow().date()` | KST | **있음 (9h)** | 같음 |
| `scripts/classify_band_regime.py:222` | (기간 종료일) | `utcnow().date()` | KST | **있음 (9h)** | 같음 |
| `scripts/backfill_openg_results.py:157,207` | 원장 `updated_at` | `utcnow()` | UTC(앱) | 없음 | 일치 |
| `scripts/run_data_reconciliation.py:419` | `collected_at` 재색인 창 | `utcnow()` | UTC | 없음 | 일치 |
| `scripts/sync_search_index.py:24` | `collected_at` 증분 창 | `utcnow()` | UTC | 없음 | 일치 |
| `scripts/backfill_openg_results.py`·`classify_band_regime.py:544` | `first_seen_at`/`classified_at` | `utcnow()` | UTC | 없음 | 일치 |
| `scripts/report_rule_coverage.py:490,673` | `bid_ntce_dt` 창 | `date.today()` KST | KST | 없음 | A계열과 같은 달력 |
| `scripts/result_match_rate_report.py:136` | `bid_ntce_dt`/`rl_openg_dt` 창 | `date.today()` KST | KST | 없음 | 같음 |

### 3.4 grep 전량 대조: 비교가 아니어서 제외한 지점

리뷰 기준 "2단계 표에 빠진 비교 지점이 있는가"를 검증할 수 있게, 59줄을 전부 분류했다. 아래는 **값을 쓰기만 하거나 경과시간을 재는** 지점이라 판정표에서 뺀 것이다.

| 파일:줄 | 성격 | 제외 이유 |
| --- | --- | --- |
| `core/timeutil.py:10,13,15` | `utcnow()` 정의·주석 | 기준 함수 자체 |
| `core/security.py:334` | `session_generations.updated_at` 대입 | 쓰기 전용, 비교 없음 |
| `core/observability.py:136,186` | `last_export_at` 대입 | 텔레메트리 쓰기 전용 |
| `api/v1/accounts.py:457,495,581` | `consented_at`/`date_joined`/`last_login` 대입 | 쓰기 전용 |
| `api/ui.py:803` | `last_login` 대입 | 쓰기 전용 |
| `api/v1/chatbot.py:472` | trace_id 문자열 생성 | 시각 비교 아님 |
| `api/v1/chatbot.py:505,531` | 레이턴시 구간 계측 | 같은 출처끼리의 차 |
| `services/kb_builder.py:96,235` | `updated_at`/`embedded_at` 대입 | 쓰기 전용 |
| `services/automation_jobs.py:171,203` | `started_at`/`ended_at` 대입 | 쓰기 전용 |
| `services/ranking_snapshots.py:163,215` | 재집계 경과 계측 | 같은 출처끼리의 차 |
| `services/dashboard.py:262` | `summary.rebuilt_at` 대입 | 쓰기 전용 |
| `services/demand_institutions.py:483` | `fetched_at` 대입 | 쓰기 전용 |
| `services/automation_orchestrator.py:272,303,309,383,384,436,479,486,496,515,545,555,562` | 요청·실행 시각 대입 | 쓰기 전용 |
| `services/conversation_state.py:356,373` | `updated_at` 대입 | 쓰기 전용 |
| `services/sajeong_rate_stats.py:153` | `rebuilt_at` 대입 | 쓰기 전용 |
| `services/compare_stats_snapshots.py:101,134,214,220,241` | `rebuilt_at`(UTC) 과 `utcnow()` 비교 | 양쪽 모두 UTC naive 라 어긋나지 않음 |
| `services/restore_drill_freshness.py:239` | 복원 드릴 보고서 파일 시각과 `now` | DB 컬럼이 아님. 보고서 JSON 메타데이터 비교 |

`services/collector_service.py:252,294` 는 `collected_at`·`first_seen_at` 에 `utcnow()` 를 대입하는 쓰기지만, 2.3절에서 그 컬럼의 기준을 판정하는 근거라 표에 남겼다. `services/dashboard.py:402,626` 은 같은 파일의 `one_year_ago` 계산 지점이라 3.2 표의 `dashboard.py` 행에 함께 적었다.

### 3.5 이미 고친 지점

| 파일:줄 | 내용 | 상태 |
| --- | --- | --- |
| `services/bid_queries.py` `_kst_now()` + `get_announcement_detail` `now = _kst_now()` | 추천 마감 필터, 최근 30일 창, 과거 사례 365일 창 | `e766fe27` 로 수정됨. **현재 브랜치에는 아직 없음** (`kwanbum217/detail-recommend`, `kwanbum217/integ-20261107b` 에만 존재) |

이 브랜치는 `main`(=`8e612506`)에서 갈라졌고 `e766fe27` 은 조상이 아니다. 그래서 `bid_queries.py:967` 의 `uncollected_legacy` 가 이 워크트리에서는 여전히 원래 코드다. 재작업 문서 8.3절이 "범위 밖 관찰"로 남긴 지점과 같은 줄이다.

### 3.6 2단계 정량 (운영 DB)

9시간 어긋남이 실제로 몇 건을 잘못 분류하는지 셌다. 2026-11-06(금) 마감 분포로 계산했다.

| 항목 | 값 |
| --- | --- |
| 2026-11-06 하루 마감 공고 | 1,679건 |
| 그중 KST 05:58~14:58 구간 마감(= UTC 기준으로는 아직 안 지난 구간) | 1,422건 |
| 최근 표본(`bid_ntce_dt >= 2026-10-01`, 마감일 보유 44,285건)의 마감 시각 최빈값 | `10:00` (27,177건 = 61.4%) |

마감 시각이 `10:00` 에 몰려 있는 것이 결정적이다. `utcnow()` 는 KST 10:00 마감 공고를 **KST 19:00 까지** "마감 전"으로 본다. 마감이 가장 몰린 시각대가 정확히 오차 구간 안에 들어간다.

조회 시점(2026-11-07 06:05 UTC = 토요일 15:05 KST)에는 그 구간에 걸린 행이 0건이었다. 주말이라 마감이 없기 때문이고, 이는 결함이 없다는 뜻이 아니라 **측정 시점이 오차 구간 밖**이라는 뜻이다.

---

## 4. 3단계: 수정 방안 비교 (결정하지 않음)

세 방안의 성질만 적는다. 채택은 5절의 사용자 결정 항목이다.

### 4.1 방안 A: 공용 `kst_now()` 헬퍼 도입

- `core/timeutil.py` 에 `kst_now()` 를 두고, A계열 컬럼과 비교하는 지점만 이 함수를 쓰게 바꾼다.
- 장점: 오차가 발생하는 **한 곳**에서 기준을 명시한다. `e766fe27` 이 국소적으로 쓴 방식과 같다.
- 단점: 비교 지점마다 "이 컬럼은 A계열인가"를 사람이 판단해야 한다. 2.4절처럼 한 테이블에 두 계열이 섞여 있어 호출부 판단이 틀리면 같은 결함이 재발한다.
- 손대야 할 지점: 3.2·3.3절에서 "있음"으로 표시된 20여 곳.

### 4.2 방안 B: 컬럼별 정규화(저장 시 UTC 통일 또는 조회 시 KST 변환)

- A계열 컬럼을 UTC naive 로 정규화해 저장하거나, 조회 시 KST 로 맞춘다.
- 장점: 구조적으로 한 계열만 남아 판단 실수가 사라진다.
- 단점: **G1 데이터 무손실과 충돌**한다. `bid_announcements`·`bid_results` 는 300만 행 규모이고, 값을 다시 쓰는 마이그레이션은 원본 행 값 변경이다. `AGENTS.md` 3장 5항(데이터 보존: 기존 DB 테이블명·컬럼명·타입 변경 금지)과 7장 금지 행위 5의 취지에도 닿는다. 조회 시 변환은 인덱스를 못 타 300만 행 경로의 레이턴시 게이트(G3)를 건드린다.
- 참고: 원문 시각을 그대로 보존하는 것 자체가 G1 의 요구이기도 하다.

### 4.3 방안 C: 주석·문서만 정정

- `timeutil.py:3` 의 "DB 의 DateTime 컬럼은 UTC naive 값을 저장합니다" 를 "앱이 쓰는 컬럼은 UTC naive, 원문에서 온 컬럼은 KST naive" 로 고친다.
- 장점: 비용이 가장 낮고 위험이 없다. 잘못된 전제가 다음 사람에게 전파되는 것을 막는다.
- 단점: 실제 9시간 오차는 그대로 남는다. `bid_clse_dt` 류를 `utcnow()` 와 비교하는 코드는 계속 틀린 답을 낸다.

### 4.4 방안별 비교

| 기준 | A. 공용 헬퍼 | B. 컬럼 정규화 | C. 주석 정정 |
| --- | --- | --- | --- |
| 9시간 오차 제거 | 예 (호출부 정확할 때) | 예 | 아니오 |
| G1 데이터 무손실 | 영향 없음 | **충돌 위험** | 영향 없음 |
| G3 레이턴시 | 영향 없음 | 조회 변환 시 악화 | 영향 없음 |
| 재발 방지 강도 | 중 (판단 의존) | 높음 (구조) | 낮음 |
| 변경 범위 | 20여 지점 | 마이그레이션 + 전 경로 | 1개 문서 |

### 4.5 이 절이 결정하지 않는 것

어느 방안을 채택할지, 어느 지점을 먼저 고칠지, `e766fe27` 의 `_kst_now()` 를 공용으로 승격할지는 **정하지 않았다**. 5절의 결정 항목으로 넘긴다.

---

## 5. 사용자 결정 항목

| # | 결정할 것 | 선택지 | 이 문서가 제공하는 근거 |
| --- | --- | --- | --- |
| D1 | 수정 방안 | 4.1 A / 4.2 B / 4.3 C / 조합 | 4.4 비교표, 2.4 계열 혼재 |
| D2 | 적용 범위 | 3.2 의 20여 지점 전부 / 사용자 노출도 높은 것만 / `bid_clse_dt` 마감 판정류만 | 3.2·3.3 영향 열, 3.6 정량 |
| D3 | `_kst_now()` 처리 | `e766fe27` 의 지역 함수 유지 / `core/timeutil.py` 로 승격 / 다른 이름으로 신설 | `e766fe27` diff, 3.5 |
| D4 | 수집 창 기준 | `utcnow()` 유지 / `date.today()` 로 변경 | `collector_service.py:132`, 크론이 KST 02:00 인 사실 |
| D5 | 선행 조건 | `e766fe27` 병합 후 착수 / 이 브랜치에서 독립 착수 | 3.5(이 브랜치에 미반영) |

D4 는 성격이 다르다. 나머지는 "A계열 컬럼에 UTC 시계를 쓴다"이지만, `collector_service.py:132` 는 **A계열 컬럼이 아니라 API 질의 날짜**를 만든다. 수집 창은 원문 날짜 체계로 질의하므로 KST 달력이 맞고, 지금은 UTC 라서 KST 00:00~09:00 에 하루 밀린다. 크론이 KST 02:00(`src/tasks/worker.py:447`)이라 이 경로는 **매일** 해당한다.

---

## 6. 범위와 한계

- 코드는 고치지 않았다. 변경 파일은 이 문서 하나다.
- DB 는 `uv run python scripts/db_readonly_query.py --sql` 의 단일 `SELECT`/`DESC` 만 썼다. `docker exec`, `docker compose exec`, `mysql` 직접 호출, `sh -c` 래핑, 쓰기 트랜잭션은 쓰지 않았다. `raw_data LIKE` 전체 스캔도 쓰지 않았다.
- `src/rag` 는 3.2·3.3 표에 별도 행으로 넣지 않았다. 마감·기간 창이 모두 `date.today()`(KST)로 만들어지고 A계열 컬럼과 같은 달력이므로 어긋남이 없다. 다만 `structured_data.py:508-510` 처럼 그 KST 날짜를 `bid_clse_dt` 에 직접 비교하는 구조라, D1 에서 B안(컬럼 UTC 정규화)을 고르면 이 경로도 함께 손대야 한다.
- 3.2 표의 정량 영향은 "9시간"과 "경계 1일치"로 적었다. 365일 창 경계에서 실제로 몇 건이 뒤집히는지는 창 경계가 매일 이동하므로 건수로 고정하지 않았다.
- 표본 대조는 각 테이블 3행 이하다. 전수 대조가 아니라 **기준 판정을 위한 표본**이다.
- 3.6 의 1,422건은 2026-11-06 하루 마감치를 그날 KST 14:58 시점으로 계산한 값이다. 다른 요일·시각은 값이 달라진다.
