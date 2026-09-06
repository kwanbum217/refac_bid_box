# RAG 콜드 SQL 3과제 처리 보고 (task_ef2f12867e6a)

> **작성일**: 2026-09-06
> **Task**: task_ef2f12867e6a
> **정본**: `.orca/capsules/task_ef2f12867e6a/capsule.yaml`
> **분석 문서**: `docs/analysis/rag_structured_sql_coldstart_20260830.md` 9.3절

---

## 1. 결론

세 과제 중 코드를 바꾼 것은 없습니다. 바꾸지 않은 것이 아니라 바꿀 수
없음을 확인한 것입니다. 각 과제의 판정은 다음과 같습니다.

| 순서 | 과제 | 판정 |
| --- | --- | --- |
| 1 | `corrupted_probe` 3건의 비용 제거 | 미처리 (유지). 게이팅을 시도했다가 기존 테스트 2건이 깨져 원복했습니다. |
| 2 | `dminstt_nm`, `bid_ntce_nm` `contains()` 선행 와일드카드 대체 | 미처리. B-트리로 탈 방법이 없고 대체는 결과 집합을 바꿉니다. |
| 3 | 두 컬럼 GROUP BY 날짜 인덱스 힌트 | 확인 완료. 힌트가 이미 붙어 있고 옵티마이저도 자발적으로 날짜 범위를 탑니다. |

검색 결과 집합과 안내 문구에 차이가 없으므로 사용자 가시 동작은 그대로입니다.
DB 스키마 변경, 새 인덱스, 마이그레이션, FULLTEXT 도입, 컨테이너·`.env`
조작은 일절 없습니다.

---

## 2. 과제별 근거

### 2.1 corrupted_probe (미처리, 유지)

`src/rag/structured_data.py` 의 `_top_rows` 는 순위 창이 깨끗하고 스냅샷
마커(`get_skipped_count`, `bid_ranking_snapshots` 단일 조회)도 없으면
차원 3곳에서 `REPLACEMENT_CHAR` 탐침을 `LIMIT 1` 로 돕니다. 순위가 채워졌을
때만 탐침을 생략하는 게이팅을 적용했더니 기존 테스트 2건이 실패했습니다.

- `tests/test_ranking_snapshots.py::test_live_path_also_excludes_corrupted`
- `tests/test_ranking_snapshots.py::test_live_path_announcement_excludes_corrupted`

두 테스트는 SQL 의 `exclude_corrupted` 가 손상값을 먼저 걸러 보낸 상태에서
순위가 깨끗한 행으로 채워져도 "인코딩" 안내가 붙어야 함을 고정합니다.
가져온 창이 깨끗한 것과 전체 결과에 손상이 없는 것은 다르므로, 게이팅은
Wave E1 회귀를 재현하는 변경이었습니다. 즉시 원복했고 해당 테스트는 다시
통과합니다.

탐침 비용 실측(2026-09-06 EXPLAIN, `scripts/db_readonly_query.py`):

- 탐침(날짜 조건 없음): `type: index`, `key: ix_bid_results_bidwinnr_nm`,
  `rows: 3,118,641`, `possible_keys: None`
- 탐침(날짜 조건 있음, 2026년): `type: range`,
  `key: bid_results_rl_openg_dt_00b70e7a`, `rows: 501,266`

선행 와일드카드 exact 존재 확인을 스캔 없이 수행할 방법은 스키마 변경 없이
없으며, 스키마·인덱스 변경은 범위 밖이므로 탐침을 유지합니다. 판단 근거를
코드 주석(`_top_rows` 탐침 블록)과 신규 회귀 테스트
`tests/test_rag_structured_data.py` 5건으로 고정했습니다.

### 2.2 contains 선행 와일드카드 (미처리)

사용자 기관명 필터(`_result_conditions` 146행, `_announcement_conditions`
172행, `_result_availability_conditions` 269행)는 `contains()` 그대로 둡니다.

- 기관명 COUNT(날짜 조건 없음): `type: index`,
  `key: bid_announcements_dminstt_nm_952da702`, `rows: 2,295,025`,
  `possible_keys: None`. 쓸 수 있는 키 자체가 없습니다.
- 기관명 COUNT(날짜 조건 있음): `type: range`,
  `key: bid_announcements_bid_ntce_dt_c42f1afb`, `rows: 707,124`.
  날짜 범위는 타지만 LIKE 필터 707,124행 평가는 남습니다.

전방 일치나 등가 조건으로 바꾸면 결과 집합이 달라지고, FULLTEXT와 새
인덱스는 기각됐거나 범위 밖입니다. 안전하게 처리 가능한 대체가 없습니다.

### 2.3 GROUP BY 날짜 인덱스 힌트 (확인 완료, 추가 변경 없음)

두 공고 집계(`dminstt_nm`, `bid_ntce_nm` GROUP BY)에
`_hint_announcement_date_index` 가 이미 적용돼 있습니다.

- `dminstt_nm` GROUP BY(힌트 없음): `type: range`,
  `key: bid_announcements_bid_ntce_dt_c42f1afb`, `rows: 707,124`,
  `Extra: Using index condition; Using where; Using temporary; Using filesort`
- `dminstt_nm` GROUP BY(힌트 있음): `type: range`, `key: ix_bid_ann_dt_cat`,
  `rows: 736,148`, Extra 동일
- `bid_ntce_nm` GROUP BY도 같은 계열(힌트 없음 707,124행, 힌트 있음 736,148행)

옵티마이저가 힌트 없이도 날짜 범위를 자발 선택하므로 접근 경로 변화가
없습니다. 코드를 더 건드릴 이유가 없습니다.

---

## 3. 변경 파일

- `src/rag/structured_data.py`: 탐침 블록 주석에 유지 근거와 비용 실측 기록 (동작 변경 없음)
- `tests/test_rag_structured_data.py`: 탐침 실행 계약 회귀 테스트 5건 (신규)
- `docs/analysis/rag_structured_sql_coldstart_20260830.md`: 9.3절 처리 결과 갱신
- `docs/analysis/task_ef2f12867e6a.md`: 본 보고서 (신규)

---

## 4. 검증 결과

- `uv run pytest tests/test_rag_structured_data.py -q`: 6 passed
- `uv run pytest tests/ -q -m "not data_assets"`: 3740 passed, 32 skipped (전량 통과)
- `uv run mypy src`: Success, no issues found in 93 source files
- `python3 scripts/validate_agent_rules.py --quiet`: 검증 통과 20/20건

전량 테스트는 mypy 와 병렬 실행 시 부하로 429 계열 6건이 간헐 실패했으나,
단독 재실행에서 전량 통과했습니다. `data_assets` 제외는 격리 워크트리에
`data/model_files` 와 `chroma_db` 가 없기 때문이며 변경과 무관합니다.
DB 조회는 전부 `scripts/db_readonly_query.py` 로 수행했고 `docker`·`mysql`
직접 호출과 콜드 스타트 벤치마크, 컨테이너 재기동은 하지 않았습니다.
