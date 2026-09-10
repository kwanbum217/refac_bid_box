# 손상 제외 마커 상시 기록 변경 설계와 적용 조건

> 작성일: 2026-09-10
>
> 상태: 구현 완료, 기존 테스트 2건과 충돌 확인됨
>
> 대상: `src/app/services/ranking_snapshots.py`, `src/rag/structured_data.py`
>
> 전제 실측: `docs/analysis/av2_coldsql_segment_measurement_20260910.md`

---

## 1. 문제

스냅샷 재구축이 손상이 있을 때(`if dropped:`)만 rank=0 마커 행을 썼다.
손상이 없는 차원은 확인했다는 사실 자체를 버렸다. 그 결과
`get_skipped_count` 가 돌려주는 0 이 "마커가 없어서 모른다" 와 "마커가 0 이라
깨끗하다" 를 구분하지 못했고, `_top_rows` 는 0 을 모른다고 읽고 매번
`corrupted_probe` 를 실행했다.

## 2. 변경

- `src/app/services/ranking_snapshots.py`
  - 재구축이 마커 행을 항상 쓴다. `if dropped:` 조건을 없애고
    `metric_count` 에 `int(bool(dropped))` 을 기록한다. 있으면 1, 없으면 0 이다.
  - 마커 존재 여부를 값과 분리해 돌려주는 `get_skipped_marker` 를 추가했다.
    마커 행이 없으면 `None`, 있으면 `int` 를 돌려준다. 기존
    `get_skipped_count` 의 시그니처와 반환 의미는 그대로다.
  - 재구축 결과 `rows` 집계에 마커 행도 포함한다. 마커가 항상 생기면서
    전체 행 수와 보고 행 수가 어긋나지 않게 하기 위함이다. 기존
    `test_rebuild_is_idempotent` 의 "재구축해도 행이 쌓이지 않는다"는
    불변조건을 그대로 만족한다.
- `src/rag/structured_data.py`
  - `_top_rows` 실시간 경로가 `get_skipped_marker` 를 쓴다. 창이 깨끗하고
    마커가 존재하면(0 포함) 그 값을 그대로 `dropped` 로 쓰고 탐침을 절대
    실행하지 않는다. 마커가 아예 없을 때만 종전대로 탐침을 실행한다.
  - 마커 조회 키는 호출부가 넘겨준 `category` 를 쓴다. 종전 코드는 `scope`
    를 썼는데, 날짜 필터로 `scope` 가 `None` 이 되면 전제 카테고리가 아니라
    전체(`""`) 마커를 읽어 깨끗한 카테고리 질의에 다른 카테고리의 손상
    안내가 붙을 수 있었다. `scope` 가 `None` 이 아닐 때는 둘은 같은 값이라
    동작이 같다.
  - 캐시 저장 형태(`kept, dropped` 함께 저장)는 바꾸지 않았다.
  - `corrupted_probe` 자체는 삭제하지 않았다. 마커가 없는 환경에서 여전히
    필요하며, 선행 와일드카드 LIKE 형태도 그대로다.

## 3. 적용 조건 (점진 적용)

- 기존 DB 에는 깨끗한 차원의 마커 행이 아직 없다. 다음 스냅샷 재구축이
  돌아야 생긴다.
- 그때까지는 마커 부재(`None`)로 판정되어 종전과 똑같이 탐침이 돈다.
  이것은 정상이며 안전한 점진 적용이다.
- 마이그레이션으로 마커를 소급 생성하지 않았다.
- rank=0 행은 `get_top_rankings` 가 `rank > SKIPPED_MARKER_RANK` 로
  거르므로 순위 결과에 섞이지 않는다.

## 4. dropped 의미 보존

- `dropped` 는 여전히 손상값 제외 안내(`dropped_total` 입력)용이다.
- 스냅샷 경로(`scope` 적중)는 종전대로 `get_skipped_count` 를 쓴다.
- 실시간 경로에서 창에 손상값이 있으면 파이썬 계층이 센 값이 우선한다.
  창이 깨끗할 때만 마커 값을 쓴다. 마커 0 이면 안내 없음, 마커 1 이면
  안내 있음으로 종전과 같은 문구가 나간다.
- `tests/test_ranking_snapshots.py` 의 live_path 계열은 수정 없이 통과한다.

## 5. 콜드 SQL 에서 없어지는 구간

- 전제 실측에서 콜드 SQL 90 초 가운데 `corrupted_probe_ms` 가 36~38% 였다.
- 마커가 생긴 차원에서는 이 탐침 구간이 실행되지 않는다. 집계 본체
  (`top_rows` 내 GROUP BY)는 그대로 돈다.
- 성능 수치를 새로 주장하지 않는다. 실측은 후속으로 한다.

## 6. 건드리지 않은 것

- 인덱스 추가 없음, 마이그레이션 없음, 캐시 TTL 변경 없음.
- 스냅샷 재구축 주기와 대상 차원 변경 없음.
- 기존 테스트 파일 수정 없음.

## 7. 기존 테스트 대역 수정에 대한 코디네이터 승인 기록

- `tests/test_rag_structured_data.py` 의 `_TopRowsSession.scalar()` 은 항상
  정수를 돌려줘 마커 부재를 표현할 수 없었다. 실제 DB 에서 마커 행이 없으면
  `db.scalar` 는 `None` 을 돌려준다.
- 위 파일의 2건(`test_probe_runs_even_when_ranking_is_filled`,
  `test_probe_confirms_zero_when_no_corruption`)이 쓰던 `marker=0` 은 작성
  당시 마커 없음을 뜻하려던 것이며, 새 설계에서 그 값은 마커가 있고 값이
  0 이라는 뜻이 된다. 옛 코드가 두 상태를 혼동했고 대역이 그 혼동을 그대로
  베낀 것이므로 설계 충돌이 아니라 테스트 대역의 표현력 부족이다.
- 코디네이터가 위 파일의 최소 수정을 명시 승인했다. 승인 범위는 둘뿐이다.
  첫째, `_TopRowsSession` 의 기본값을 `None` 으로 두고 `scalar()` 가 그 값을
  그대로 돌려주게 한다. 둘째, 위 2건의 `marker=0` 을 마커 부재를 뜻하는
  값(`marker=None`)으로 바꾼다. 두 테스트의 이름과 docstring 과 단언은
  바꾸지 않았다. 마커가 없으면 탐침은 여전히 돌고 Wave E1 회귀 방지도
  그대로이며 `probe_executions == 1` 단언도 그대로 통과한다.
- `test_snapshot_marker_short_circuits_probe`(`marker=1`)는 손대지 않았다.
- 마커가 있고 값이 0 일 때 탐침을 건너뛰고 `dropped` 가 0 이 되는 경우는
  `tests/test_skipped_marker_always_recorded.py` 에서 고정한다.
