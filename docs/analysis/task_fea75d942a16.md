# Task 분석 및 검증 보고서 (`task_fea75d942a16`)

> **작성일**: 2026-08-25
> **수정일**: 2026-08-25 (ChromaDB 4개 테이블 스키마 조인 및 배치 파라미터 바인딩 반영)
> **작성자**: Orca Worker (Antigravity)
> **대상 작업**: `task_fea75d942a16` (LLM 품질 fixture 근거 ID 검증 fail-open 제거 및 경량 evidence manifest 도입)
> **관련 문서**: [`docs/analysis/llm_quality_fixture_20260824.md`](llm_quality_fixture_20260824.md)

---

## 1. 개요 및 배경

### 1.1 문제 정의
기존 `scripts/validate_llm_quality_fixture.py`는 로컬 및 CI 환경에서 ChromaDB SQLite 파일(`chroma.sqlite3`)을 찾을 수 없으면 "실재 검증 건너뜀"으로 처리하고 종료 코드 0으로 통과하는 **Fail-Open 결함**이 있었습니다.
ChromaDB 데이터베이스 자산은 대용량 바이너리로 Git에 추적되지 않으므로, GitHub CI 및 격리 워크트리 환경에서는 가상의 허위 근거 ID를 입력해도 CI가 이를 차단하지 못하는 안전 공백이 존재했습니다.

### 1.2 해결 방안
1. **경량 Evidence Manifest 스키마 정의**: Git에 추적 가능한 최소 크기의 JSON manifest (`data/eval/llm_quality_evidence_manifest.json`)를 도입하여 각 근거 ID의 문서 SHA-256 해시와 메타데이터를 보관합니다.
2. **생성기 스크립트 작성 (`scripts/build_llm_fixture_manifest.py`)**: ChromaDB 4개 테이블(`collections`, `segments`, `embeddings`, `embedding_metadata`)의 정밀 조인 및 파라미터 바인딩 배치 `IN` 쿼리를 통해 fixture가 요구하는 `expected_evidence_ids`만 추출하여 manifest를 생성합니다. ChromaDB가 없거나 ID가 누락되면 부분 manifest를 쓰지 않고 0이 아닌 종료 코드로 즉시 중단합니다.
3. **Fail-Closed 검증기 개편 (`scripts/validate_llm_quality_fixture.py`)**: manifest 파일 부재, 필수 필드 누락, ID 불일치 시 검증을 실패 처리합니다. 과도기 전용 명시적 옵트아웃 플래그(`--skip-manifest-check`)를 지원하되 기본값은 Fail-Closed입니다.

---

## 2. ChromaDB 실제 스키마 및 조회 구조

### 2.1 테이블 구조
- `collections(id, name)`: 컬렉션 메타데이터 (`bidding_kb`)
- `segments(id, type, scope, collection)`: `segments.collection`이 `collections.id`를 참조
- `embeddings(id, segment_id, embedding_id, seq_id, created_at)`: `embeddings.segment_id`가 `segments.id`를 참조
- `embedding_metadata(id, key, string_value, int_value, float_value, bool_value)`: `embedding_metadata.id`가 `embeddings.id`를 참조하며 문서 본문은 `key = 'chroma:document'`의 `string_value`에 보관

### 2.2 배치 조회 쿼리 (파라미터 바인딩)
```sql
SELECT e.embedding_id, em.string_value
FROM embeddings e
JOIN segments s ON s.id = e.segment_id
JOIN collections col ON col.id = s.collection
JOIN embedding_metadata em ON em.id = e.id AND em.key = ?
WHERE col.name = ? AND e.embedding_id IN (?, ?, ...)
```

---

## 3. Manifest 사양 및 규약

### 3.1 스키마 사양
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `schema_version` | string | 스키마 버전 (예: `"1.0.0"`) |
| `created_at` | string | ISO 8601 UTC 생성 일시 |
| `collection_name` | string | 대상 ChromaDB 컬렉션 이름 (`"bidding_kb"`) |
| `total_collection_documents` | integer | 컬렉션 내 전체 문서 수 (512,348건) |
| `item_count` | integer | manifest에 수록된 근거 ID 수 (17건) |
| `entries` | list[dict] | 개별 근거 문서 항목 (`evidence_id`, `content_hash`, `doc_length`) |

### 3.2 Entry 필드 규약
- `evidence_id`: 비어있지 않은 문자열 (예: `"bid_10015927"`)
- `content_hash`: `"sha256:<64자리 16진수>"` 형식 (UTF-8 인코딩 문서 본문의 SHA-256 해시)
- `doc_length`: 정수 (문서 본문 길이)

---

## 4. 구현 및 테스트 내용

### 4.1 `scripts/build_llm_fixture_manifest.py`
- ChromaDB 4개 테이블 스키마에 부합하는 조인 쿼리 구현.
- 배치 `IN` 절 및 파라미터 바인딩 적용.
- 누락 ID 감지 시 부분 manifest 작성 방지 및 누락 ID 목록 출력.

### 4.2 `scripts/validate_llm_quality_fixture.py`
- manifest 무결성 및 fixture `expected_evidence_ids` 100% 대조 검증 (Fail-Closed).
- `verify_evidence_ids_in_kb()` 역시 4개 테이블 조인 스키마에 맞추어 수정.

### 4.3 단위 테스트 (`tests/test_build_llm_fixture_manifest.py`, `tests/test_validate_llm_quality_fixture.py`)
- 실제 4개 테이블 스키마를 반영한 mock 데이터베이스 구축.
- ChromaDB 부재 fail-closed, 참조 ID 한정 추출, 부분 manifest 미작성, 스키마 검증 전량 통과.

---

## 5. 검증 결과

| 검증 항목 | 명령어 | 결과 |
| :--- | :--- | :--- |
| 신규/수정 단위 테스트 | `uv run pytest tests/test_validate_llm_quality_fixture.py tests/test_build_llm_fixture_manifest.py -q` | **28/28 passed** |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | **2049 passed, 6 skipped** |
| 린터 검사 | `uv run ruff check scripts/ tests/` | **All checks passed** |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | **12/12 passed** |

---

## 6. 코디네이터 후속 조치 안내

코디네이터는 ChromaDB 원본 자산(`chroma_db/chroma.sqlite3`)이 존재하는 주 저장소 호스트에서 다음 명령을 실행하여 정본 manifest를 1회 생성 및 커밋해 주시기 바랍니다:

```bash
uv run python scripts/build_llm_fixture_manifest.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --output data/eval/llm_quality_evidence_manifest.json
```
