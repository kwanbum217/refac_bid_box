# AW1 손상 마커 상시 기록 변경 독립 검토

> 검토일: 2026-09-10
>
> 대상 커밋: `70632c4` (`kwanbum217/orca-aw1`)
>
> 대상 빌더 Task: `task_f62b6f867a3c`
>
> 판정: pass. 차단 결함 없음.

검토 범위는 빌더가 고친 다섯 파일이다. 경로는 저장소 실재 경로만 쓴다.

| 구분 | 경로 |
| --- | --- |
| 빌더 변경 | `src/app/services/ranking_snapshots.py` |
| 빌더 변경 | `src/rag/structured_data.py` |
| 빌더 변경 | `tests/test_skipped_marker_always_recorded.py` |
| 빌더 변경 | `tests/test_rag_structured_data.py` |
| 빌더 변경 | `docs/analysis/aw1_skipped_marker_always_20260910.md` |
| 리뷰어가 읽기만 함 | `tests/test_ranking_snapshots.py` |
| 이 문서 | `docs/analysis/aw1_skipped_marker_always_review_20260910.md` |
| 기계 보고 | `.orca/capsules/task_93c8d740a1e7/review_done.json` |

`src/ranking_snapshots.py` 라는 경로는 존재하지 않는다. 스냅샷 구현의 정본은
`src/app/services/ranking_snapshots.py` 이다. `tests/test_ranking_snapshots.py` 는
빌더가 고치지 않았고, 리뷰어가 live_path 계열 단언이 유지됐는지 확인하려고
읽기만 했다.

성능은 검토 대상이 아니다. 테스트는 재실행하지 않았다.

---

## 1. 종합

재구축이 손상이 없을 때도 rank=0 마커를 `metric_count` 0 으로 남기고,
실시간 경로는 마커가 있으면(0 포함) 탐침을 건너뛴다. `dropped` 는 여전히
손상 제외 안내의 진릿값 입력이다. 마커가 정확하면 안내 문구는 옛 동작과
같다. 마커 0 에서 탐침을 생략하는 차이만 의도된 개선이다.

코디네이터가 보류한 지점의 짧은 답은 다음과 같다.

| 보류 지점 | 판정 |
| --- | --- |
| 다섯 조합의 dropped | 1·2·3·5는 옛 동작과 같다. 4(파이썬 0, 마커 0)만 탐침을 생략하며, 재구축 시점 탐침이 이미 깨끗함을 확인한 값이라 안내 문구는 같다. |
| 마커 이후 신규 손상의 안내 지연 | 허용 가능. 순위 자체는 `exclude_corrupted` 가 계속 거른다. 지연은 안내 문구뿐이고, 옛 코드도 마커 1 이면 탐침을 건너뛰었다. |
| `written` 카운터 | 로그와 반환 `rows` 만 커진다. 제어 흐름은 바꾸지 않는다. |
| `get_skipped_count` | 죽은 코드가 아니다. 스냅샷 적중 경로가 계속 부른다. 시그니처와 반환 의미는 그대로다. |
| 기존 테스트 수정 | 승인 범위 3줄뿐이다. 이름·docstring·`probe_executions` 단언은 그대로다. |

---

## 2. 다섯 조합의 dropped

실시간 경로의 새 분기는 `src/rag/structured_data.py` 549-557행이다.
창에서 파이썬이 센 값이 있으면 그 값이 이기고, 창이 깨끗하면
`src/app/services/ranking_snapshots.py` 269-286행의 `get_skipped_marker` 를
읽는다. 마커가 있으면 `dropped = marker` 이고 탐침은 돌지 않는다.
마커가 없을 때만 종전대로 `corrupted_probe` 를 실행한다.

안내 문구는 `src/rag/structured_data.py` 776행의 `if dropped_total:` 이다.
숫자의 크기보다 0 이 아닌지가 동작이다.

| 조합 | 새 동작 | 옛 동작 | 판정 |
| --- | --- | --- | --- |
| 1. 파이썬이 셈, 마커 있음 | 파이썬 건수, 탐침 생략 | 동일 | 보존 |
| 2. 파이썬이 셈, 마커 없음 | 파이썬 건수, 탐침 생략 | 동일 | 보존 |
| 3. 파이썬 0, 마커 1 | `dropped=1`, 탐침 생략 | `get_skipped_count` 가 1 을 돌려 탐침 생략 | 보존 |
| 4. 파이썬 0, 마커 0 | `dropped=0`, 탐침 생략 | `get_skipped_count` 가 0 을 돌려 탐침 실행 | 의도된 개선. 재구축 `_compute_rows` 115-122행이 이미 LIMIT 1 탐침으로 깨끗함을 확인했으므로, 마커가 정확하면 옛 탐침 결과도 0 이라 안내 문구는 같다. |
| 5. 파이썬 0, 마커 없음 | 탐침 실행 | 탐침 실행 | 보존. 기존 DB 의 깨끗한 차원은 다음 재구축 전까지 이 경로다. |

스냅샷 적중 경로(`src/rag/structured_data.py` 529행)는 종전대로
`get_skipped_count` 를 쓴다. 재구축 뒤에는 마커가 항상 있으므로 0 과 1 이
갈린다.

---

## 3. 마커 이후 신규 손상의 안내 지연

마커는 야간·수집 직후 재구축 시점의 사실이다. 그 뒤 수집으로 손상 행이
들어오면 이 변경은 탐침을 건너뛰므로, 다음 재구축까지 안내가 뜨지 않을 수
있다.

이 지연은 허용 가능하다.

1. 순위 값은 실시간 경로의 `exclude_corrupted` 가 계속 거른다. 손상값이
   상위권에 오르지 않는다. 지연되는 것은 안내 문구뿐이다.
2. 옛 동작도 마커가 1 이면 탐침을 건너뛰었다. 스냅샷 시점 사실을 이미
   신뢰하고 있었다. 이번 변경은 그 신뢰를 깨끗한 차원(마커 0)에도 같은
   규칙으로 확장한 것이다.
3. 수집이 성공하면 `src/tasks/scheduled_tasks.py` 263행이 재구축을 호출한다.
   일 단위 차원(`bidwinnr_nm`, `dminstt_nm`)은 그 주기에 맞춰 마커가 갱신된다.
   주간 차원 `bid_ntce_nm` 은 최대 7일이지만, 그 차원의 스냅샷 순위 자체도
   같은 주기로 낡은 값이다. 무제한 지연이 아니다.

---

## 4. written 카운터

`src/app/services/ranking_snapshots.py` 197행이 마커 행마다 `written` 을
1 늘린다. 예전에는 마커를 쓸 때도 이 카운터에 넣지 않았다.

소비처는 로그, 반환 dict 의 `rows`, 스케줄 `outcome["ranking_snapshots"]`
뿐이다. `_mark_followup_failures` 는 `status == "failed"` 만 본다.
`rows` 숫자의 의미는 "이번에 쓴 행 수" 로 마커를 포함하게 되어 실제 테이블
행 수와 맞춰졌다. `tests/test_ranking_snapshots.py` 118-124행의
`total == second` 불변조건이 오히려 정확해진다. 제어 흐름을 바꾸지 않는다.

---

## 5. get_skipped_count

죽은 코드가 아니다. `src/rag/structured_data.py` 529행 스냅샷 적중 경로가
계속 부른다. 시그니처 `(db, dataset, dimension, category) -> int` 와
`int(value or 0)` 반환은 그대로다. 삭제는 이 검토의 범위가 아니다.

---

## 6. 기존 테스트와 범위

`tests/test_rag_structured_data.py` 의 차분은 3줄뿐이다.

- `_TopRowsSession` 기본값 `marker=None`
- `test_probe_runs_even_when_ranking_is_filled` 의 `marker=None`
- `test_probe_confirms_zero_when_no_corruption` 의 `marker=None`

이름, docstring, `assert dropped`, `live_executions`, `probe_executions == 1`
은 그대로다. `tests/test_ranking_snapshots.py` 의 live_path 계열은 수정하지
않았다.

인덱스, 마이그레이션, 캐시 TTL, `corrupted_probe` LIKE 형태는 그대로다.
`get_top_rankings` (`src/app/services/ranking_snapshots.py` 245행)가
`rank > SKIPPED_MARKER_RANK` 로 거르므로 마커 행은 순위 결과에 섞이지 않는다.
`src/` 안의 다른 `BidRankingSnapshot` 읽기는 재구축, 나이, 마커 전용 조회뿐이다.

새 테스트 `tests/test_skipped_marker_always_recorded.py` 는 탐침 호출 횟수로
검증하고, 빈 테스트나 새 의존성은 없다.

비차단: `tests/test_rag_structured_data.py` 151-160행
`test_probe_outcome_is_cached` 는 승인 범위 밖이라 `marker=0` 을 그대로
두었다. 새 의미에서 마커 0 은 탐침을 생략하므로 이 테스트는 더 이상 탐침
결과 캐시를 고정하지 않는다. 캐시 저장 형태 자체는 그대로라 차단 사유는
아니다.

빌더 분석 문서 2절은 종전 실시간 경로가 `scope` 로 마커를 읽었다고 적었으나,
실제 old diff 의 `get_skipped_count` 인자는 이미 `category` 였다. 문서 표현
오류일 뿐 코드 결함은 아니다.

---

## 7. 리뷰어 산출물

이 검토가 만든 파일은 둘뿐이다.

- `docs/analysis/aw1_skipped_marker_always_review_20260910.md`
- `.orca/capsules/task_93c8d740a1e7/review_done.json`

빌더가 고친 파일은 리뷰어 `files_modified` 에 넣지 않는다.
