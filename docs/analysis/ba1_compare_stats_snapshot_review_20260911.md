# BA1 compare-stats 사전 집계 스냅샷 전환 독립 검토

> **작성일**: 2026-09-11
> **검토 대상**: 브랜치 `kwanbum217/orca-ba1`, 커밋 `94a4766e2b55f732818ab05243ae5d380986838f`
> **대상 Task**: `task_e45ed533ee0a`
> **판정**: 통과
> **근거**: 코드 대조. 테스트는 재실행하지 않았고, 성능 수치는 새로 주장하지 않는다.

---

## 1. 결론

스냅샷 경로와 실시간 폴백 경로는 같은 질의·같은 금액 상한·같은 정렬·같은 상위 10 절단·같은 기관명 미제외 규칙을 쓴다. 스냅샷이 없거나 2일을 넘거나 payload 형태가 리스트/정수 규약을 벗어나면 실시간으로 돌아가며, 그 폴백이 응답을 stale 로 바꾸지 않는다. 재집계 실패는 야간 후속과 수집 직후 양쪽에서 삼켜지고, 마이그레이션은 새 테이블만 만든다.

차단 결함은 없다. 잔여 위험은 5절에 적는다.

---

## 2. 변경 범위

| 파일 | 역할 |
| --- | --- |
| `src/app/models/bids.py` | `BidCompareStatsSnapshot` 신설 |
| `src/app/services/compare_stats_snapshots.py` | 재집계·조회 신설 |
| `src/app/services/dashboard.py` | 조회 경로에 스냅샷 선행, 실시간 함수 추출 |
| `src/tasks/scheduled_tasks.py` | 야간·개발 최신화 후속에 재집계 |
| `src/app/services/collector_service.py` | 수집 직후 재집계 |
| `migrations/versions/b2c3d4e5f6a7_add_bid_compare_stats_snapshots.py` | 새 테이블만 생성 |
| `tests/test_compare_stats_snapshots.py` | 고정 테스트 신설 |

`git diff --name-only 94a4766^..94a4766` 기준 일곱 파일뿐이다. `pyproject.toml` 과 기존 테스트 파일은 없다.

---

## 3. 보류 지점 판정

### 3.1 스냅샷과 실시간 폴백의 결과 동등성

**판정: 같다.**

기관 상위 10 은 양쪽이 같은 식이다.

| 규칙 | 스냅샷 `src/app/services/compare_stats_snapshots.py:100` | 실시간 `src/app/services/dashboard.py:501` |
| --- | --- | --- |
| 금액 | `dashboard._announcement_amount_expr` 재사용 | 동일 함수 |
| 창 | `bid_ntce_dt >= one_year_ago` (365일) | 동일 |
| 기관 NULL | `dminstt_nm.is_not(None)` | 동일 |
| 손상명 제외 | 없음 | 없음 |
| 정렬 | `func.sum(amount_expr).desc()` | 동일 |
| 절단 | `limit(10)` | 동일 |
| 항목 키 | `name`, `total_base_amount`, `total_prce`, `count` | 동일 |
| `total_prce` | `total_base_amount` 와 같게 채움 | 동일 |

`_announcement_amount_expr` 는 `base_amount` 를 DECIMAL 로 캐스팅하고 100조 초과를 NULL 로 빼는 기존 식이다 (`src/app/services/dashboard.py:203`). 스냅샷이 이 식을 import 해서 쓰므로 이상치 규칙이 갈라지지 않는다.

매칭 건수 질의도 동일하다. 공고에 대해 최근 1년 `BidResult.rl_openg_dt` EXISTS 를 세고, 스냅샷만 `{"value": 정수}` 로 감싼 뒤 조회부가 `value` 를 풀어 응답의 `matched_count` 에 넣는다.

창의 시작 시각은 재집계 시점의 `utcnow()` 와 요청 시점의 `utcnow()` 로 각각 계산한다. 수 초 차이는 사전 집계의 본래 성격이며 질의 형태가 다른 것은 아니다. 동등성 테스트 `tests/test_compare_stats_snapshots.py:142` 가 같은 DB 에서 폴백 결과와 재집계 후 스냅샷 결과가 같다고 고정한다.

### 3.2 스냅샷 부재·손상·빈 payload

**판정: 화면을 깨뜨리는 차단 경로는 없다. 빈 리스트는 적법한 집계 결과로 취급한다.**

조회부 사용 조건은 `src/app/services/dashboard.py:568` 이다.

| payload 상태 | 사용 여부 | 동작 |
| --- | --- | --- |
| 행 없음 | 불가 | 실시간 폴백 |
| `rebuilt_at` 없음 | 불가 (`is_snapshot_fresh(None)` 이 거짓) | 실시간 폴백 |
| 기관 payload 가 list 가 아님 (`dict`/`None`/문자열) | 불가 | 실시간 폴백 |
| 매칭 payload 가 dict 가 아니거나 `value` 가 int 가 아님 | 불가 | 실시간 폴백 |
| 신선한 빈 리스트 `[]` | 사용 | 상위 10 이 빈 배열. 실시간 집계가 데이터가 없을 때 내는 값과 같다 |
| 신선한 리스트인데 항목 키 누락 | 사용으로 분류된 뒤 `KeyError` | 아래 잔여 위험 |

형태가 다른 payload (`{}`, `None`, `"..."`, `{"value": "1"}`) 는 폴백한다. 예외로 compare-stats 전체가 실패하는 규약 위반 경로는, 재집계 작성기가 실제로 쓰는 형태에서는 열리지 않는다. 작성기는 항상 네 키 딕셔너리의 리스트와 `{"value": int}` 만 넣는다.

빈 리스트를 폴백 트리거로 쓰지 않은 것은 맞다. 데이터가 없을 때의 정상 결과까지 실시간 질의로 되돌리면 사전 집계를 무효로 만들기 때문이다. 데이터가 생긴 뒤 재집계가 빠진 경로에서 신선한 빈 스냅샷이 남으면 순위가 비어 보일 수 있다. 야간과 수집 직후는 재집계를 부르므로 운영 경로에서는 그 상태가 유지되지 않는다.

항목 키 누락 리스트는 `isinstance(..., list)` 만 통과한 뒤 `item["name"]` 에서 예외가 난다. 작성기가 그 형태를 쓰지 않으므로 차단으로 보지 않고 5절 잔여로 둔다.

### 3.3 2일 임계의 시간대와 경계

**판정: naive UTC 로 맞춰 있고, 경계는 규약과 같다.**

`utcnow()` 는 UTC naive 를 돌려준다 (`src/app/core/timeutil.py:10`). 모델 `rebuilt_at` 은 timezone 없는 `DateTime` 이고 재집계가 `utcnow()` 를 직접 넣는다.

`is_snapshot_fresh` (`src/app/services/compare_stats_snapshots.py:55`) 는 aware 값이 오면 UTC 로 변환한 뒤 tzinfo 를 떼고, naive 끼리 초 단위 나이를 계산한다. `get_snapshot_with_age` 도 같은 정규화를 한다. 호출부는 원본 `rebuilt_at` 을 `is_snapshot_fresh` 에 넘기므로 정규화가 두 번 적용되어도 결과는 같다.

비교는 `age_days <= 2` 이다. 규약은 "2일 이내면 스냅샷, 2일을 넘으면 폴백" 이므로 48.0시간은 스냅샷, 그 초과는 폴백이다. 테스트는 3일 된 스냅샷이 폴백하는 경우만 고정한다 (`tests/test_compare_stats_snapshots.py:207`). 정확히 2.0일 경계와 aware 입력은 테스트가 없다.

폴백은 `summaries_stale` 만으로 TTL 과 `:stale` 캐시 키를 정한다. 스냅샷 노후는 계산 경로만 바꾼다. 이는 최종 규약과 같다.

### 3.4 재집계 연결과 실패 격리

**판정: 야간과 수집 직후 양쪽에 연결됐고, 실패가 본 작업을 중단시키지 않는다. 기존 후속 집계와 같다.**

| 경로 | 위치 | 실패 처리 |
| --- | --- | --- |
| 야간 스케줄 | `src/tasks/scheduled_tasks.py:266` | `_rebuild_compare_stats_snapshots` 가 예외를 잡아 `{"status": "failed"}` 반환. `_mark_followup_failures` 가 `partial_success` 로만 올린다 |
| 개발 데이터 최신화 | `src/tasks/scheduled_tasks.py:336` | 동일 |
| 수집 직후 | `src/app/services/collector_service.py:221` | `rebuild_bid_dataset_summaries` 다음 try/except. 경고 로그만 남기고 캐시 예열을 계속한다 |

야간 래퍼 (`src/tasks/scheduled_tasks.py:382`) 는 `_rebuild_ranking_snapshots` 와 같은 형태다. `FOLLOWUP_KEYS` 에 `compare_stats_snapshots` 가 들어가 실패가 조용히 `success` 로 남지 않는다. 새 크론은 없다.

### 3.5 마이그레이션과 기존 스키마

**판정: 기존 테이블·컬럼을 건드리지 않고, downgrade 는 새 테이블만 지우며, 단일 head 다.**

- 리비전 `b2c3d4e5f6a7`, down `a1b2c3d4e5f6`
- `upgrade` 는 `bid_compare_stats_snapshots` 만 `create_table` (인덱스 없음)
- `downgrade` 는 그 테이블만 `drop_table`
- `a1b2c3d4e5f6` 의 자식은 이 파일뿐이고, 이 리비전을 down 으로 가리키는 파일은 없다. 마이그레이션 디렉터리 head 는 `b2c3d4e5f6a7` 하나다

`BidCompareStatsSnapshot` 은 기존 모델 사이에 삽입만 했고 기존 컬럼 정의는 바뀌지 않았다. 운영 DB 에 적용한 흔적은 보고와 diff 에 없다.

---

## 4. 체크리스트 요약

| id | 질문 | 답 | 결함 |
| --- | --- | --- | --- |
| existing_schema_changed | 기존 테이블이나 컬럼을 변경했는가 | no | 아니오 |
| payload_shape_matches | 두 스냅샷의 payload 형태가 사양과 같은가 | yes | 아니오 |
| amount_expr_reused | 금액 집계가 `_announcement_amount_expr` 를 재사용하는가 | yes | 아니오 |
| corruption_filter_added | 기관명 손상값 제외를 새로 넣었는가 | no | 아니오 |
| snapshot_short_circuits | 스냅샷이 있을 때 실시간 집계가 실행되지 않는가 | yes | 아니오 |
| fallback_preserved | 없거나 낡으면 실시간 폴백이고 TTL 이 종전과 같은가 | yes | 아니오 |
| response_semantics_changed | 반환 키·값 형태·캐시 키·TTL 판정이 바뀌었는가 | no | 아니오 |
| rebuild_wired | 야간과 수집 직후 양쪽에 재집계가 연결됐는가 | yes | 아니오 |
| new_cron_added | 새 크론이나 새 스케줄러를 만들었는가 | no | 아니오 |
| segment_names_preserved | 구간 이름이 유지되고 스냅샷과 폴백을 구분할 수 있는가 | yes | 아니오 |
| migration_applied_to_db | 운영 DB 에 마이그레이션을 적용했는가 | no | 아니오 |
| out_of_scope_optimization | 인덱스를 만들거나 월별 두 집계를 건드렸는가 | no | 아니오 |
| new_package_added | 새 외부 패키지를 추가했는가 | no | 아니오 |
| test_quality | 빈 테스트나 동어반복이 있거나 기존 테스트를 수정했는가 | no | 아니오 |
| scope_exceeded | 허용된 일곱 파일 밖을 수정했는가 | no | 아니오 |
| worker_done_report_present | worker_done.json 이 있고 필수 필드를 갖췄는가 | yes | 아니오 |

구간 이름 아홉 개는 `src/app/core/latency_segments.py:33` 그대로다. 스냅샷/폴백 구분은 `src/app/services/dashboard.py:646` 의 정보 로그와, 계측이 켜졌을 때 `matched_count`·`agency_announce_top10` 구간의 시간 차이로 가능하다. 구간 JSON 자체에 source 필드는 없다.

---

## 5. 잔여 위험과 빠진 테스트

차단은 아니다.

1. 신선한 리스트인데 항목 키가 없으면 `get_compare_stats_data` 가 `KeyError` 로 실패한다. 작성기가 그 형태를 쓰지 않는다.
2. 빈 DB 에서 재집계한 뒤, 재집계 없는 적재만 하면 2일 동안 빈 순위가 남을 수 있다. 야간·수집 직후는 재집계한다.
3. 구간 JSON 에 스냅샷/폴백 태그가 없어, 계측 로그만으로 경로를 가르려면 정보 로그 또는 구간 시간에 의존한다.
4. 2.0일 경계와 aware `rebuilt_at` 을 고정하는 테스트가 없다.
5. 재집계 실패가 야간·수집을 중단하지 않음을 코드로 확인했으나 그 경로의 단위 테스트는 없다.

성능 수치는 재측정하지 않았다. 병합 후 코디네이터가 측정한다.
