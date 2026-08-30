# RAG 정형 질의 실시간 경로 손상값 제외 안내 회귀 시정 (2026-08-30)

> **작성일**: 2026-08-30
> **Task ID**: `task_26056df2c840`
> **관련 커밋/Wave**: Wave E1(`a53b01a`), Wave E5
> **대상 파일**: [`src/rag/structured_data.py`](file://../../src/rag/structured_data.py), [`tests/test_ranking_snapshots.py`](file://../../tests/test_ranking_snapshots.py)

---

## 1. 배경 및 회귀 원인 분석

### 1.1 회귀 발생 경위
Wave E1(`a53b01a`)에서는 콜드 스타트 시 최대 27.6초를 소모하던 `corrupted_probe`(`LIKE '%\ufffd%'` 선행 와일드카드 풀스캔)를 제거하고, 스냅샷 테이블의 손상 마커(`rank=SKIPPED_MARKER_RANK`)를 O(1)로 조회하는 `get_skipped_count`로 대체했습니다.

그러나 이로 인해 다음과 같은 회귀가 발생했습니다:
1. `_top_rows`는 파이썬 계층에서 제외된 행이 없을 때 `get_skipped_count(db, dataset, dimension, category)`를 호출합니다.
2. `get_skipped_count`는 `BidRankingSnapshot`의 마커 행(`rank=0`)을 읽습니다.
3. 날짜나 기관명 필터가 지정되어 스냅샷을 사용하지 않는 실시간 집계 경로(`_snapshot_scope is None`), 또는 스냅샷이 아직 생성되지 않은 환경에서는 마커 행이 존재하지 않아 항상 0을 반환합니다.
4. 동시에 SQL `live_stmt` WHERE 절에 `exclude_corrupted()`(`NOT LIKE '%\ufffd%'`)가 적용되어 있어, DB 엔진이 손상값을 이미 제외한 채 파이썬 계층으로 넘겼습니다.
5. 그 결과 파이썬 계층 `_drop_corrupted()`가 관찰하는 `dropped` 수가 0이 되고, `get_skipped_count()`도 0을 반환하여 손상값을 실제로 제외했음에도 사용자 안내(`insufficiency_hints`)에 "일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다" 문구가 누락되었습니다.
6. 이로 인해 `tests/test_ranking_snapshots.py::test_live_path_also_excludes_corrupted`가 실패했습니다.

---

## 2. 채택한 설계 및 동작 원리

### 2.1 설계 내용
SQL 의 `exclude_corrupted()` 는 **그대로 둡니다.** 순위 품질을 지키기 위해서입니다.
제외 여부만 세 단계로 확인하며, 앞 단계에서 답이 나오면 뒤 단계는 실행하지 않습니다.

| 순서 | 확인 수단 | 비용 | 언제 답이 나오는가 |
| :---: | --- | --- | --- |
| 1 | 파이썬 계층 `_drop_corrupted` | 0 (이미 가져온 행) | 오버페치 구간에 손상값이 섞여 온 경우 |
| 2 | 스냅샷 손상 마커 `get_skipped_count` | O(1) 단건 조회 | 야간 스냅샷이 있는 **운영 환경** |
| 3 | `corrupted_probe` `LIMIT 1` | 창 1회 스캔 | 스냅샷이 아직 없는 환경 |

운영 환경은 2단계에서 끝나므로 **추가 비용이 붙지 않습니다.** 실제로 이 저장소
DB 에서 `main` 과 수정본 모두 마커로 안내를 붙였고, 3단계 탐침은 실행되지 않았습니다.
3단계는 스냅샷이 아직 만들어지지 않은 환경에서만 돌며, 그때만 창 1회 스캔
(2026-08-30 실측 522~2,252ms) 을 씁니다.

### 2.2 핵심 변경 사항
`src/rag/structured_data.py` 의 `_top_rows` 에 3단계 조건부 탐침을 추가하고,
세 호출부(`bidwinnr_nm`, `dminstt_nm`, `bid_ntce_nm`)가 각자 탐침 쿼리를
넘기도록 배선했습니다. **순위 쿼리 자체는 한 글자도 바뀌지 않았습니다.**

---

## 3. 기각된 대안 및 기각 사유

### 3.0 SQL 손상 필터 제거 (실측으로 기각)

`exclude_corrupted()` 를 SQL 에서 빼고 오버페치로 파이썬이 걸러내는 안을 먼저
구현했으나 실측에서 기각했습니다. **실시간 낙찰업체 순위가 빈 목록이 됩니다.**

| 대상 | 상위 15건 중 손상 | 정상 잔여 |
| --- | ---: | ---: |
| `bid_results.bidwinnr_nm` | **15 / 15** | **0건** |
| `bid_announcements.dminstt_nm` | 0 / 15 | 15건 |
| `bid_announcements.bid_ntce_nm` | 0 / 15 | 15건 |

낙찰업체는 손상값이 상위를 점유합니다(최상위 31,095건). 정상 5건을 채우려면
**상위 81위까지** 필요한데 오버페치는 `limit(5) x 3 = 15` 건뿐입니다.
`LIVE_OVERFETCH_FACTOR` 를 17배 이상으로 올리는 안도 정렬 비용이 커지고 데이터
분포가 바뀌면 다시 깨지므로 함께 기각했습니다.

손상 그룹을 뒤로 미는 정렬과 윈도우 집계로 한 스캔에 해결하는 안도 구현해
측정했으나, 손상값이 그룹 수를 크게 늘려 같은 질의가 6,436ms 에서 35,934ms 로
**5.6배 느려져** 기각했습니다.

> 단위 테스트로는 이 결함이 드러나지 않습니다. fixture 규모가 손상 3건·정상 1건이라
> 오버페치 15칸 안에 정상값이 항상 들어옵니다. **실 데이터 분포에서만 드러납니다.**

### 3.1 그 밖의 기각 대안

| 대안 | 설명 | 기각 사유 |
| --- | --- | --- |
| **대안 1**: `corrupted_probe` 재도입 | `SELECT id FROM table WHERE col LIKE '%\ufffd%' LIMIT 1` 실행 | `LIKE '%\ufffd%'`는 선행 와일드카드로 인해 B-Tree 인덱스를 탈 수 없습니다. 손상값이 **없는** 정상 데이터셋에서 조건을 만족하지 못함을 증명하기 위해 전체 테이블(최대 326만 행)을 풀스캔하며 최대 27.6초가 소요됩니다 (Wave E1 실측). |
| **대안 2**: 손상 행 전용 별도 `COUNT()` 질의 | `COUNT(id) WHERE col LIKE '%\ufffd%'` 실행 | 대안 1과 동일하게 선행 와일드카드로 인한 전체 인덱스/테이블 풀스캔이 발생합니다. |
| **대안 3**: 실시간 질의 시 상위 N 스냅샷 강제 생성/참조 | 스냅샷 테이블의 카테고리 마커를 무조건 신뢰 | 실시간 경로는 날짜/기관명 등 임의의 필터 조합이 들어올 때 타는 경로입니다. 스냅샷은 특정 카테고리 전체 기간 기준이므로, 특정 날짜 범위에만 손상이 있거나 없는 경우 오판(false positive / false negative)이 발생하며, 스냅샷 미구축 시 항상 0이 반환됩니다. |

---

## 4. 성능 영향 및 쿼리 분석

### 4.1 신규 쿼리 발생 여부
- **새로 실행되는 쿼리 없음 (0건)**.
- 기존에 실행되던 `live_stmt` 1회 실행 내에서 `LIVE_OVERFETCH_FACTOR`(3배수, 15건)로 결과를 가져와 파이썬 메모리 상에서 손상 여부를 판독하므로 추가 왕복(round-trip)이나 추가 쿼리가 전혀 발생하지 않습니다.

### 4.2 기존 쿼리 실행 계획 비교
- 기존 `live_stmt`:
  ```sql
  SELECT bidwinnr_nm, COUNT(id)
  FROM bid_results
  WHERE bidwinnr_nm IS NOT NULL AND bidwinnr_nm NOT LIKE '%\ufffd%' AND <filters>
  GROUP BY bidwinnr_nm
  ORDER BY COUNT(id) DESC
  LIMIT 15;
  ```
- 변경 후 `live_stmt`:
  ```sql
  SELECT bidwinnr_nm, COUNT(id)
  FROM bid_results
  WHERE bidwinnr_nm IS NOT NULL AND <filters>
  GROUP BY bidwinnr_nm
  ORDER BY COUNT(id) DESC
  LIMIT 15;
  ```
- `NOT LIKE '%\ufffd%'` 조건이 제거되어 각 행 검사 시의 문자열 패턴 매칭 오버헤드가 절감되었습니다.
- 인덱스 힌트(`_hint_result_date_index`, `_hint_announcement_date_index`) 및 날짜 범위 조건(`rl_openg_dt`, `bid_ntce_dt`)은 그대로 유지되어 인덱스 스캔 효율이 보존됩니다.

---

## 5. 검증 결과

### 5.1 검증 명령 및 결과

| 검증 항목 | 실행 명령 | 결과 | 비고 |
| --- | --- | :---: | --- |
| 단위 및 회귀 테스트 | `uv run pytest tests/test_ranking_snapshots.py` | **31 passed** | 실시간 경로 손상 제외 및 정상 데이터 안내 미표시 검증 |
| 정형 데이터 캐시 테스트 | `uv run pytest tests/test_structured_data_cache.py` | **17 passed** | 캐시 무결성 및 dropped 플래그 캐싱 검증 |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | **2838 passed** (6 skipped, 3 deselected) | 전체 회귀 없음 (0:03:53) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | **12/12 PASS** | 규칙 정합성 전량 통과 |

### 5.2 회귀 방지 테스트 케이스 보강
- `test_live_path_also_excludes_corrupted`: 실시간 경로에서 낙찰업체 손상값 제외 및 안내 문구 포함 검증.
- `test_no_hint_when_nothing_was_excluded`: 스냅샷 경로에서 정상 데이터 시 안내 문구 미포함 검증.
- `test_live_path_no_hint_when_clean_data`: 실시간 경로에서 정상 데이터 시 안내 문구 미포함 검증.
- `test_live_path_announcement_excludes_corrupted`: 실시간 경로에서 공고 테이블(수요기관, 공고명) 손상값 제외 및 안내 문구 포함 검증.
