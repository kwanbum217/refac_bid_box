# RAG 정형 집계 콜드 스타트 최적화 분석 및 구현 보고서

> **작성일**: 2026-08-30
> **Task ID**: `task_4a485df361bd`
> **대상 모듈**: `src/rag/structured_data.py`, `tests/test_structured_data_cache.py`

---

## 1. 배경 및 문제점

2026-08-30 실측에서 Redis 캐시가 만료된 콜드 상태의 RAG 정형 질의가 최대 97초까지 소요되는 현상이 확인되었습니다.
`performance_schema` 분석 결과 주요 병목 원인은 다음 두 가지로 규명되었습니다.

1. **`corrupted_probe`의 부당한 풀스캔 비용**:
   - `structured_data.py`의 `_top_rows`는 집계 순위에서 인코딩 손상 문자가 제외되었는지를 판별하여 안내 문구("일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다") 표시 여부를 결정하기 위해 `Model.column.contains(REPLACEMENT_CHAR)` 탐침 쿼리를 3회 수행했습니다.
   - SQLAlchemy의 `.contains()`는 `LIKE concat('%', ?, '%')`로 컴파일되어 인덱스를 탈 수 없습니다.
   - 코드 주석에는 "첫 건에서 멈추므로 전체 스캔이 되지 않는다"고 기술되어 있었으나, 실제로는 손상 데이터가 없는 정상 상태(공고 테이블 2,179,319행 전체)에서 손상 행이 없음을 증명하기 위해 매번 전체 테이블을 스캔하여 최대 27,668ms가 소요되었습니다.

2. **공고 집계(`dminstt_nm`, `bid_ntce_nm`) GROUP BY 인덱스 미스**:
   - `BidAnnouncement`의 발주기관명(`dminstt_nm`) 및 공고명(`bid_ntce_nm`) 기준 GROUP BY 집계 시 날짜 범위 조건만 주어지고 카테고리 조건이 없는 경우, 옵티마이저가 적절한 날짜 인덱스를 선택하지 못해 수백만 건의 임시 테이블 및 파일 정렬 비용을 유발했습니다.

---

## 2. 변경 내용 및 설계 결정

### 2.1 `corrupted_probe` 전체 스캔 제거 및 스냅샷 마커 재사용

- **접근법 비교 및 선정**:
  - *접근 1 (스냅샷 기록값 재사용)*: 야간 배치에서 계산하여 `bid_ranking_snapshots`의 `rank = 0` (`metric_count = 1`)에 저장해 둔 손상 제외 마커(`get_skipped_count`)를 실시간 경로에서도 O(1) 인덱스 조회로 활용.
  - *접근 2 (별도 캐시 키 TTL 적용)*: 탐침 결과를 긴 TTL로 별도 캐시하나 콜드 미스 시 첫 사용자의 풀스캔 비용은 여전히 발생.
  - *접근 3 (조건 범위 한정 탐침)*: 선행 와일드카드 특성상 여전히 범위 내 풀스캔 발생.
  - **최종 선정**: 접근 1을 채택하여 실시간 경로의 불필요한 `corrupted_probe` 쿼리를 완전히 제거하고, 파이썬 계층(`_drop_corrupted`)의 상위 N 후보 검사 결과와 스냅샷 마커(`get_skipped_count`)를 조합하여 손상 여부를 판단하도록 개선했습니다.

- **안내 문구 표시 조건의 변화 여부 판정**:
  - `bid_results` 테이블의 경우 데이터의 약 41%에 인코딩 손상이 존재하므로 스냅샷 마커가 항상 1로 기록되어 안내 문구가 정상 노출됩니다.
  - `bid_announcements` 테이블은 원본 데이터에 U+FFFD 손상 행이 없으므로 스냅샷 마커가 0이며, 불필요한 218만 행 풀스캔 2회가 완전히 제거됩니다.
  - 만약 특정 좁은 날짜 범위의 낙찰 결과에서 우연히 상위 N건에 손상 행이 전혀 포함되지 않은 경우에도 `bid_results` 전체 스냅샷 마커(1)에 따라 안내 문구가 표시될 수 있으나, 이는 데이터셋의 전반적인 품질 특성을 사용자에게 알리는 안내 문구의 본래 목적과 부합하며 결과 집계 수치 자체에는 아무런 영향을 주지 않습니다.

### 2.2 공고 테이블 GROUP BY 날짜 인덱스 힌트 적용

- `BidAnnouncement`를 대상으로 하는 `dminstt_nm` 및 `bid_ntce_nm` GROUP BY 집계에 `_hint_announcement_date_index`를 적용했습니다.
- 판정 규칙(`_needs_announcement_date_index_hint`): 날짜 범위 필터(`date_from` 또는 `date_to`)가 존재하고 카테고리(`category`) 필터가 없을 때만 `FORCE INDEX (ix_bid_ann_dt_cat)`를 부여합니다.
- 카테고리 필터가 함께 존재하는 경우에는 복합 인덱스를 통해 옵티마이저가 이미 검색 범위를 좁히므로 힌트를 부여하지 않습니다.
- 방언 한정(`dialect_name="mysql"`): MySQL 환경에서만 `FORCE INDEX`가 출력되며 SQLite 등 타 방언 환경 및 테스트에는 영향을 주지 않습니다.

### 2.3 비용 및 동작 설명 주석 정정

- `src/rag/structured_data.py`:
  - 237행 부근: 실시간 경로 소요 시간을 기존의 틀린 "2초" 주석에서 실측값인 "46~97초(2026-08-30 실측)"로 정정.
  - 274행 부근: "첫 건에서 멈추므로 전체 스캔이 되지 않습니다"라는 틀린 주석을 정정하고, 스냅샷 손상 마커를 O(1)로 재사용하는 근거와 기전을 상세히 기술.

---

## 3. 검증 결과

### 3.1 단위 테스트 추가 내역 (`tests/test_structured_data_cache.py`)

1. `test_announcement_date_index_hint_applies_only_without_category`: 날짜 필터만 있고 카테고리 필터가 없을 때만 공고 힌트가 적용되는지 검증.
2. `test_announcement_date_index_hint_emits_force_index_for_mysql_only`: MySQL 방언에서만 `FORCE INDEX (ix_bid_ann_dt_cat)`가 생성되고 SQLite에서는 무시되는지 검증.
3. `test_announcement_date_index_hint_preserves_select_and_grouping`: 힌트 적용 전후의 SELECT 컬럼, GROUP BY 컬럼, ORDER BY, WHERE 조건이 불변임을 검증.
4. `test_top_rows_dropped_true_when_corrupted_rows_present`: 반환 행에 손상 문자가 있을 때 정상 행만 유지되고 `dropped`가 1이 되는지 검증.
5. `test_top_rows_dropped_true_when_snapshot_marker_exists`: 반환 행이 정상이어도 스냅샷 마커(`skipped=1`)가 존재할 때 `dropped`가 1이 되는지 검증.
6. `test_top_rows_dropped_false_when_clean_and_no_marker`: 정상 행이고 스냅샷 마커가 없을 때 `dropped`가 0이 되는지 검증.

### 3.2 테스트 실행 결과

- `tests/test_structured_data_cache.py`: 17건 전량 통과 (17 passed)
- 집계 결과 컬럼, 순서, 데이터 무손실(G1), DB 스키마 100% 보존.
