# RAG 수치 누락(낙찰금액·낙찰률) 결정론적 검출기 구현 분석서

> **작성일**: 2026-08-26
> **작업 ID**: `task_eab38e36551f`
> **작성자**: Orca Builder Worker

---

## 1. 배경 및 목적

2026-08-26 v4 분석 결과, RAG numeric 오답의 83~85%가 검색 실패가 아닌 LLM 생성 답변에서의 진술 누락(낙찰금액·낙찰률 미언급)으로 판명되었습니다.
SYSTEM_PROMPT에 누락 금지 지시를 추가했으나, 이는 확률적 완화책이므로 실제 답변에서 누락이 발생했을 때 사후 분석 및 재측정에서 회귀를 즉각 파악하기 위한 결정론적 검출기(Deterministic Omission Detector)를 구축했습니다.

---

## 2. 설계 및 구현 세부사항

### 2.1 원칙 준수
1. **답변 문자열 불변 원칙**: 답변 텍스트를 임의로 수정하거나 교정하지 않고, 검출 및 구조화 로깅만 수행합니다.
2. **설정 플래그 제어**: `settings.NUMERIC_OMISSION_DETECTION` (기본값 `False`) 플래그로 켜고 끌 수 있으며, 비활성 시 정규식 추출 및 추가 연산/로깅 오버헤드가 발생하지 않습니다.
3. **결정론적 추출 및 판정**:
   - 검색 컨텍스트의 대괄호 라벨(`[낙찰금액]`, `[낙찰률]`)로부터 대상 수치를 정확히 추출합니다.
   - 쉼표 표기(예: `1074000`, `1,074,000`) 및 소수점/부동소수점 포맷(예: `90.1950`, `90.195`)을 고려하여 답변 텍스트 내 존재 여부를 확인합니다.

### 2.2 변경 파일 목록

| 파일 경로 | 주요 변경 내용 |
| --- | --- |
| `src/app/core/config.py` | `NUMERIC_OMISSION_DETECTION: bool = False` 설정 필드 추가 |
| `src/rag/engine.py` | `extract_numeric_context_values`, `check_numeric_omissions` 구현, `_apply_answer_guard` 및 `get_answer_sync`, `stream_tokens` 연동, `__all__` 등록 |
| `tests/test_rag_engine.py` | 수치 추출, 기본 비활성, 정상(누락 없음), 금액 누락, 낙찰률 누락, 동시 누락, 텍스트 불변성, E2E 연동 단위 테스트 추가 |

---

## 3. 검증 결과

| 검증 항목 | 실행 명령어 | 결과 |
| --- | --- | --- |
| 단위 테스트 (RAG 엔진) | `uv run pytest tests/test_rag_engine.py -q` | 35 통과 (100%) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | 2215 통과, 6 스킵 |
| 정적 린터 검사 | `uv run ruff check src tests` | 통과 (All checks passed) |
| 정적 타입 검사 | `uv run mypy src/` | 통과 (0 issues in 89 files) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 12/12 건 전량 통과 |

---

## 4. 구조화 로그 스키마

누락 검출 시 `logging.warning`으로 아래와 같은 구조화 로그가 출력됩니다:

```text
rag_numeric_omission: trace_id={trace_id} missing_types={missing_types} missing_count={total_missing_count} missing_amounts={missing_amounts} missing_rates={missing_rates}
```

- `extra["omission_detected"]`: `True`
- `extra["missing_types"]`: `["amount"]`, `["rate"]`, 또는 `["amount", "rate"]`
- `extra["missing_count"]`: 누락된 수치 항목 총 건수 (정수)
- `extra["missing_amounts"]`: 누락된 낙찰금액 문자열 목록
- `extra["missing_rates"]`: 누락된 낙찰률 문자열 목록
