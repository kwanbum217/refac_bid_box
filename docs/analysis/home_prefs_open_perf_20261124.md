# 메인 화면 관심 조건 입찰 중 집계 성능 개선

> 작성일: 2026-11-24
> 작업: task_25fde35f4f26
> 브랜치: kwanbum217/home-prefs-perf
> 범위: `bid_preferences.count_open_servc_matching`, `list_open_servc_matching` 요청 경로 제거와 `(category, bid_clse_dt)` 인덱스 리비전

---

## 1. 문제

2026-11-24 메인 화면 확인 중 렌더링이 매우 느렸습니다. performance_schema 실측은 다음과 같습니다.

| 항목 | 값 |
| --- | --- |
| 문제 질의 | `COUNT(*)` + `EXISTS`(참가 지역) + `EXISTS`(면허 제한) + 최신 차수 `NOT EXISTS` |
| 요청당 실행 | 2회 (건수와 목록이 각각 집계) |
| 평균 소요 | 49.45초 |
| 최대 소요 | 60.5초 |
| 검사 행 | 1,022,268 |
| 입찰 중 용역 | 7,068건 (`category='Servc' AND bid_clse_dt >= NOW()`, 2026-11-24 실측) |

입찰 중 용역은 7,068건뿐인데 `bid_clse_dt` 를 선두로 쓰는 인덱스가 없어, 마감일로
먼저 좁히지 못하고 참가 지역·면허 제한 테이블을 넓게 훑었습니다. Docker 기동 직후
버퍼 풀이 차가웠고 같은 시각 다른 워커의 무거운 공고 질의가 겹친 것도 지연을 키웠습니다.

현행 계획(`EXPLAIN`, ANALYZE 아님)은 참가 지역 테이블을 `type=ALL` 로 약 436,180행
추정으로 먼저 훑은 뒤 공고 테이블을 PK 로 1행씩 붙입니다. `possible_keys` 에
`ix_bid_ann_cat_dt` 는 있지만 `(category, bid_clse_dt)` 조합은 없습니다.

---

## 2. 변경 A: 마감일 인덱스 리비전

| 항목 | 값 |
| --- | --- |
| 파일 | `migrations/versions/b8d9e0f1a2b3_add_bid_announcements_cat_clse_index.py` |
| revision | `b8d9e0f1a2b3` |
| down_revision | `d6e7f8a9b0c1` |
| 인덱스 | `ix_bid_ann_cat_clse` |
| 컬럼 | `(category, bid_clse_dt)` |
| unique | false |

- 등치 조건 `category` 를 선두에, 범위 조건 `bid_clse_dt` 를 다음에 두어 인덱스
  선두에서 좁힌 뒤 마감 임박 순서를 그대로 읽게 합니다.
- `upgrade()` 는 `_has_index()` 로 이미 있는 인덱스를 건너뛰고, `downgrade()` 는
  있을 때만 지웁니다. 기존 인덱스·컬럼은 건드리지 않습니다.
- Capsule 초안이 지정한 revision `b7c8d9e0f1a2` 는 이미
  `b7c8d9e0f1a2_add_accounts_session_generation.py` 가 쓰고 있어, 같은 ID 로 두면
  Alembic 이력을 두 갈래로 가릅니다. 코디네이터 승인으로 리비전 ID 와 파일 이름을
  `b8d9e0f1a2b3` 으로 맞췄습니다. `uv run alembic heads` 결과는
  `b8d9e0f1a2b3 (head)` 한 건입니다.
- 운영 DB 적용(alembic upgrade, DDL)은 하지 않았습니다. 리뷰 뒤 코디네이터가
  사용자 승인으로 적용하는 절차를 따릅니다.

---

## 3. 변경 B: 요청 경로 집계 제거와 예열

### 3.1 캐시 정책

| 키 | TTL | 쓰는 곳 | 읽는 곳 |
| --- | --- | --- | --- |
| `bid_prefs:open_servc_count:v2:<업종>:<지역>` | 600초 | worker 예열, 시험 즉시 집계 | 요청 경로 |
| `bid_prefs:open_servc_list:v2:<업종>:<지역>:<limit>` | 600초 | worker 예열, 시험 즉시 집계 | 요청 경로 |
| `bid_prefs:open_servc_count:stale:v2:<업종>:<지역>` | 86,400초 | worker 예열, 시험 즉시 집계 | 신선 키가 없을 때 |
| `bid_prefs:open_servc_list:stale:v2:<업종>:<지역>:<limit>` | 86,400초 | worker 예열, 시험 즉시 집계 | 신선 키가 없을 때 |

신선 키가 만료되면 보관 키의 마지막 성공 값을 보여 주므로, 예열이 한두 번 실패해도
화면이 '집계 중' 으로 되돌아가지 않습니다.

### 3.2 요청 경로

`get_home_summary` 는 `now is None` 인 요청 경로에서 `count_open_servc_matching` 과
`list_open_servc_matching` 을 부르고, 두 함수는 캐시만 읽습니다.

1. 신선 키가 있으면 그 값을 씁니다.
2. 없으면 보관 키의 마지막 성공 값을 씁니다.
3. 둘 다 없으면 `None` 을 돌려주고, 템플릿은 해당 패널에 '집계 중' 을 보여 줍니다.

요청 경로에서 `_query_open_servc_count`, `_query_open_servc_list` 는 호출되지
않습니다. `now` 를 넘기거나 `use_cache=False` 를 주는 시험 경로만 그 자리에서
집계합니다.

### 3.3 worker 예열

`warm_home_summary_cache` 가 기존 10분 주기 작업에서 다음을 수행합니다.

1. 기존 4대 업종 입찰 중 건수·마감 구간을 집계해 기존 키를 채웁니다.
2. `account_bid_preferences` 의 저장된 관심 조건을 읽어, 같은 업종·지역 조합은
   한 번만 집계합니다. 빈 조건은 건너뜁니다.
3. 조건마다 `warm_open_servc_matching` 이 건수와 목록(기본 5건)을 집계해 신선 키와
   보관 키를 함께 채웁니다.
4. 한 조건이 실패해도 나머지를 계속 채우고, 반환값에 `matching_warmed`,
   `matching_failed` 를 넣습니다.

### 3.4 결과 값 불변

- 건수와 목록은 `_open_matching_conditions` 한 함수가 만든 같은 조건을 씁니다.
- 최신 차수 필터와 취소공고 제외도 기존과 같은 함수를 그대로 씁니다.
- 목록 정렬은 `bid_clse_dt ASC, id ASC`, 기본 limit 은 5로 바꾸지 않았습니다.
- 예열 값과 `use_cache=False` 즉시 집계 값의 건수·목록·순서가 같은지 시험 (d) 가
  고정합니다.

### 3.5 저장 직후 예열

`save_bid_preferences` 는 커밋을 호출자에게 맡기므로 저장 시점에 arq 큐로 예열을
넣으려면 `src/app/api/ui.py` 의 저장 경로와 worker 함수 등록을 함께 고쳐야 합니다.
이번 작업의 쓰기 허용 범위 밖이라 넣지 않았습니다. 저장 직후에는 다음 10분 예열
전까지 해당 패널이 '집계 중' 을 보일 수 있으며, 이는 Capsule 이 허용한 동작입니다.

---

## 4. 시험

`tests/test_home_prefs_open_perf_20261124.py` 가 Capsule 시험 (a)~(e)를 고정합니다.

| 구분 | 시험 | 확인 내용 |
| --- | --- | --- |
| (a) | `test_request_path_returns_pending_without_aggregating` | 캐시가 없을 때 요청 경로가 집계 함수를 부르지 않고 `None` 을 돌려줌 |
| (a) | `test_home_shows_pending_label_for_matching_panel` | 두 패널 모두 '집계 중', 관심 조건 건수 마커 없음 |
| (b) | `test_stale_cache_is_used_when_fresh_key_is_gone` | 보관 키만 있어도 건수·목록을 보여 줌 |
| (b) | `test_stale_cache_ttl_is_at_least_one_day` | 보관 TTL 24시간 이상, 신선 TTL 보다 김 |
| (c) | `test_warm_aggregates_each_distinct_condition_once` | 같은 조건 2계정도 1회 집계, 네 키를 채움 |
| (c) | `test_warm_continues_after_one_condition_fails` | 한 조건 실패에도 나머지 예열, 실패 건수 반환 |
| (d) | `test_warm_values_match_immediate_aggregation` | 예열 값과 `use_cache=False` 즉시 집계의 건수·목록·순서 동일 |
| (e) | `test_index_migration_follows_current_head_and_is_idempotent` | revision·down_revision·멱등 분기·컬럼 순서 |

기존 시험 두 곳은 요청 경로가 더 이상 즉시 집계하지 않는다는 계약에 맞춰 최소
수정했습니다.

- `tests/test_home_feedback_20261117.py::test_no_more_link_when_matching_count_is_five_or_less`:
  페이지 요청 전에 worker 와 같은 `warm_open_servc_matching` 으로 캐시를 채웁니다.
- `tests/test_home_cancelled_20261122.py::test_cache_keys_moved_past_cancelled_inflated_versions`:
  캐시 키 접두사 검증을 위해 직접 호출하던 두 함수에 `use_cache=False` 를 주어
  즉시 집계 경로를 유지합니다.

---

## 5. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest -q -m 'not data_assets' tests/test_home_prefs_open_perf_20261124.py` | 8 passed |
| `uv run alembic heads` | `b8d9e0f1a2b3 (head)` 1건 |
| `uv run mypy src` | Success: no issues found in 156 source files |
| `uv run pytest -q -m 'not data_assets' tests/` | 11,633 passed, 2 failed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
| `npm run build:css` | 성공 (`npm ci` 후) |
| `git diff --exit-code -- src/app/static/css/tailwind.css` | 차이 없음 |

전량 시험의 실패 2건은 `tests/test_g1_baseline_drift_gate.py` 의 기준선 드리프트
검사입니다. 새 인덱스가 `data/backups/schema_signature_baseline.json` 에 아직 없기
때문이며, 이 파일은 운영 DB 에 마이그레이션을 적용한 뒤
`uv run python scripts/verify_migration.py --generate-schema-baseline` 로 갱신하는
기존 절차(별도 chore 커밋)를 따릅니다. 이번 작업은 DDL·alembic upgrade 가 금지되어
있어 기준선을 갱신하지 않았습니다.

---

## 6. 운영 적용 순서

1. 리뷰와 병합.
2. 사용자 승인 아래 `alembic upgrade` 로 `ix_bid_ann_cat_clse` 적용.
3. `scripts/verify_migration.py --generate-schema-baseline` 로 G1 기준선 갱신.
4. worker 재배포로 10분 예열이 관심 조건 캐시를 채우기 시작.

인덱스 적용 전에는 예열 집계 한 건이 여전히 수십 초 걸릴 수 있습니다. 예열은
worker 전용이고 요청 경로는 캐시만 읽으므로 사용자 응답을 붙잡지는 않지만, 적용
전에는 예열 주기가 밀릴 수 있어 2번을 먼저 끝내는 편이 좋습니다.

---

## 7. 남은 일

- 운영 DB 적용 뒤 G1 스키마 기준선 갱신(코디네이터 절차).
- 저장 직후 예열이 필요하면 `ui.py` 저장 경로와 arq 작업 등록을 포함한 후속 작업.
