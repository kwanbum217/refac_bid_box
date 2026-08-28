# Task task_072fc411a3dc — 백필 후 하류 동기화 오케스트레이션 및 정합성 검증 자동화

> **작성일**: 2026-08-28
> **태스크 ID**: `task_072fc411a3dc`
> **역할**: Builder
> **상태**: 완료

---

## 1. 개요 및 배경

2026-08-28 외부 감사에서 지적된 P1 결함을 해결하기 위해 백필 이후 하류 동기화(파생 집계, ChromaDB KB 색인, Meilisearch 색인, 정합성 차집합 검사)를 자동화하였습니다.

### 배경 문제
- `scripts/backfill_from_g2b.py`는 공고/낙찰 수집 후 대시보드 요약 집계까지만 갱신하고, ChromaDB KB 색인, Meilisearch 색인, 기관 통계(`institution_win_rate_stats`), 순위 스냅샷(`ranking_snapshots`)을 수행하지 않고 안내문만 출력하는 구조였습니다.
- 2026-08-27 수동 실행 누락으로 인해 낙찰결과 9,798건이 DB에만 존재하고 KB에 색인되지 않아 평가 측정이 무효화되는 문제가 발생했습니다.

---

## 2. 주요 변경 사항

### 2.1 하류 동기화 오케스트레이터 (`scripts/run_data_reconciliation.py`) 신설
기존 구현된 서비스 로직을 재사용하여 순차적으로 실행하고 데이터 정합성을 검증하는 오케스트레이션 진입점을 구축했습니다.

1. **실행 순서**:
   - **1단계 (파생 집계)**: `rebuild_institution_stats(session)`, `rebuild_ranking_snapshots(session)`
   - **2단계 (ChromaDB KB 색인)**: `rebuild_knowledge_base(db, collected_since=target_since)`
   - **3단계 (Meilisearch 검색 색인)**: `sync_search_index(db, collected_since=target_since)`
   - **4단계 (정합성 검사)**: `verify_reconciliation(db, collected_since=...)`
2. **Fail-Closed 기전**:
   - 각 단계 중 하나라도 예외가 발생하거나 실패할 경우 즉시 중단하고 종료 코드 1로 종료 (후속 단계 실행 차단).
3. **정합성 차집합 검증**:
   - 대상 구간 DB 낙찰결과 식별자 집합과 ChromaDB 색인 식별자 집합, Meilisearch 검색 색인 식별자 집합의 차집합(`DB - KB`, `DB - Search`)을 계산.
   - 어느 한쪽이라도 누락 건수가 존재하면 누락 건수와 예시 식별자를 출력하고 종료 코드 1로 종료.
   - 전 단계와 정합성 검사가 모두 통과(차집합 0건)했을 때만 종료 코드 0 반환.
4. **옵션 및 안전장치**:
   - `--since`, `--until`, `--since-hours`를 통해 대상 구간을 명시적으로 제한.
   - 대상 구간 인자가 없으면 전체 재색인 위험을 방지하기 위해 fail-closed(종료 코드 1)로 차단.
   - 실제 단계를 호출하지 않고 실행 계획만 확인하는 `--dry-run` 지원.

### 2.2 G2B 백필 스크립트 연동 (`scripts/backfill_from_g2b.py`)
- `--sync-downstream` CLI 옵션을 추가하여 백필 완료 직후 `run_reconciliation`을 자동 호출하고 하류 동기화 종료 코드를 백필 종료 코드로 전파.
- `--sync-downstream` 미지정 시 종전의 동작과 주의 안내문을 유지하되, `--sync-downstream` 옵션에 대한 안내를 추가.

### 2.3 단위 테스트 (`tests/test_run_data_reconciliation.py`)
격리된 Mock 환경에서 다음 핵심 요구사항을 9개 단위 테스트로 고정:
- 단계 실행 순서 고정 (`파생 집계` -> `KB 색인` -> `검색 색인` -> `정합성 검사`)
- 단계 실패 시 후속 단계 차단 (fail-closed)
- 정합성 차집합 발생 시 종료 코드 1 반환
- 전 단계 및 정합성 검사 정상 시 종료 코드 0 반환
- `--dry-run` 시 실제 핸들러 미호출 검증
- 대상 구간 미지정 시 오류 종료 검증
- `verify_reconciliation` 차집합 계산 로직 검증
- `backfill_from_g2b.py`의 `--sync-downstream` 플래그 및 종료 코드 전파 검증

---

## 3. 검증 결과

- `uv run pytest tests/test_run_data_reconciliation.py -v`: 9개 테스트 통과 (0.04s)
- `uv run pytest tests/ -q -m 'not data_assets'`: 2255개 전체 테스트 통과
- `uv run ruff check src/ scripts/ tests/`: 린트 통과 (All checks passed)
- `python3 scripts/validate_agent_rules.py --quiet`: 다중 에이전트 규칙 12/12 통과
- DB 스키마, 컬럼명, 타입 변경 없음 (G1 무손실 준수)
- 신규 외부 라이브러리 추가 없음
