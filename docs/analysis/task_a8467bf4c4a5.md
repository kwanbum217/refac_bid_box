# Task a8467bf4c4a5 분석 및 구현 보고서

> **작성일**: 2026-08-26
> **작성자**: Orca Worker (`task_a8467bf4c4a5`)
> **대상 작업**: `src/rag/engine.py` SYSTEM_PROMPT 미개찰·미확정 정보 거절 지시 추가 및 회귀 방지 테스트

---

## 1. 개요 및 배경

2026-08-25 LLM 품질 v3 측정 과정에서 미개찰 공고 관련 질의(fixture `q18`: 내일 오후 2시 개찰 예정 사업의 사전 확정 예정가격 및 1순위 낙찰업체 질의)에 대해 모델이 근거 없이 가상 정보를 답변하는 과잉응답(hallucination) 결함이 확인되었습니다.

기존 `SYSTEM_PROMPT`에는 인라인 인용, 통계/추세 매핑, 목록 답변, 요청 기간 0건 안내, 분야 코드 치환, canvas 시각화 지시만 정의되어 있었고, 미개찰·개찰 전·미래 시점 또는 비공개 확정 전 정보에 대한 거절 지시가 부재했습니다.

본 작업에서는 정상 질의(16문항)에 대한 답변 지시 및 0건 설명 지시를 100% 보존하면서, 미개찰·미확정 정보 질의에 대해 확인 불가 사유를 밝히고 정중히 거절하도록 지시를 추가했습니다.

---

## 2. 변경 내용 상세

### 2.1 `src/rag/engine.py` (SYSTEM_PROMPT)

기존 문장의 삭제나 변형 없이 아래 순서로 지시 문구를 배치했습니다.

1. **미개찰·미확정 정보 거절 지시**:
   - `미개찰 공고, 개찰 전 또는 미래 시점 질의처럼 아직 개찰되지 않았거나 확정되지 않은 예정가격, 1순위 낙찰업체, 낙찰금액, 낙찰률 등의 정보는 컨텍스트에 근거가 없다면 절대로 추정하거나 임의 예시로 제시하지 말고 확인 불가함을 명시하여 답변을 거절하세요.`
2. **거절 사유 명시 지시**:
   - `거절할 때는 개찰 전 미확정 정보이거나 비공개 내부 정보여서 제공할 수 없다는 사유를 한 문장으로 명확히 밝히세요.`
3. **근거 존재 시 거절 지시 미적용 예외 조항**:
   - `다만 제공된 검색 컨텍스트에 실제 근거가 있으면 위 거절 지시를 적용하지 말고 정상적으로 답변하세요.`

### 2.2 `tests/test_rag_engine.py` (회귀 테스트)

SYSTEM_PROMPT의 거절 지시 및 기존 지시 보존을 검증하는 4개의 단위 테스트를 추가했습니다.

| 테스트 함수명 | 검증 항목 | 결과 |
| --- | --- | :---: |
| `test_system_prompt_refusal_instructions_unopened_and_unconfirmed` | 미개찰·개찰 전·미래 시점 및 예정가격/낙찰업체/낙찰금액/낙찰률 거절 지시와 사유 명시 지시 존재 검증 | 통과 |
| `test_system_prompt_refusal_exception_when_evidence_present` | 검색 컨텍스트에 실제 근거가 있을 경우 거절하지 않고 정상 답변하는 예외 조건 명시 검증 | 통과 |
| `test_system_prompt_preserves_existing_instructions_and_zero_count` | 기존 목록 답변 지시 및 요청 기간 0건 설명 지시 훼손 여부 검증 | 통과 |
| `test_system_prompt_preserves_category_wording_and_canvas_instructions` | 분야 코드(Servc 등) 노출 금지 및 canvas 태그 시각화 지시 보존 검증 | 통과 |

---

## 3. 검증 결과

| 검증 항목 | 실행 명령 | 결과 |
| --- | --- | :---: |
| RAG 엔진 단위 테스트 | `uv run pytest tests/test_rag_engine.py -q` | **24/24 통과** |
| 전체 단위/통합 테스트 (non-data_assets) | `uv run pytest tests/ -q -m 'not data_assets'` | **2131/2131 통과** |
| 코드 스타일 및 린터 검사 | `uv run ruff check src/ tests/` | **통과 (0 errors)** |
| 다중 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | **12/12 통과** |

---

## 4. 검토 체크리스트 점검

- [x] **기존 지시 삭감 없음 (`existing_instruction_removed`)**: `git diff` 기준 기존 문장 삭제 0줄.
- [x] **과잉거절 방지 (`overbroad_refusal`)**: 컨텍스트에 실제 근거가 있을 경우 정상 답변 예외 명시.
- [x] **0건 설명 지시 충돌 없음 (`zero_count_conflict`)**: 0건 설명 지시 보존 및 명확히 구분.
- [x] **허용 범위 준수 (`scope_creep`)**: `allowed_write_files` 범위 내 파일만 수정.
- [x] **측정 및 외부 호출 없음 (`measurement_run`)**: 불필요한 모델 기동이나 벤치마크 미실행.
