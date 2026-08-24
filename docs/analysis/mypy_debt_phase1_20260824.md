# mypy 부채 해소 1단계 분석 보고서 (2026-08-24)

> **작성일**: 2026-08-24
> **작업 브랜치**: `mypy-debt-phase1`
> **관련 과업**: `task_4a11c91c25e4` (외부 감사 P2-1)
> **대상 오류 코드**: `return-value`, `attr-defined`, `union-attr` (복구 완료), `assignment`, `arg-type` (차기 잔여 과업)

---

## 1. 개요 및 목적

`pyproject.toml`의 `[tool.mypy]` 설정에 전역 비활성화(`disable_error_code`)되어 있던 5종 오류 코드 중 실제 위반이 없거나 적은 3종(`return-value`, `attr-defined`, `union-attr`)을 복구하여 타입 검사 게이트의 실효성을 강화했습니다.

`# type: ignore` 주석을 추가하여 억제하는 방식을 배제하고, 코드 수준의 타입 정정 및 방어적 None 검사를 적용하여 위반을 전량 해소했습니다.

---

## 2. 작업 결과 요약

| 항목 | 작업 전 (2026-08-24 기준) | 작업 후 | 비고 |
| --- | --- | --- | --- |
| `disable_error_code` 목록 | 5종 (`union-attr`, `assignment`, `attr-defined`, `return-value`, `arg-type`) | 2종 (`assignment`, `arg-type`) | 3종 복구 완료 |
| `return-value` 위반 건수 | 0건 | 0건 | 즉시 복구 |
| `attr-defined` 위반 건수 | 2건 | 0건 | `BidResult` 비영속 속성 정의로 해소 |
| `union-attr` 위반 건수 | 9건 | 0건 | 방어적 None 가드 적용으로 해소 |
| 신규 추가된 `# type: ignore` | - | 0건 | 억제 주석 없음 |
| mypy 전체 검사 결과 (`src/`) | 통과 (5종 비활성화) | **통과** (3종 활성화, 0 오류) | 89개 소스 파일 검사 통과 |
| 단위/통합 테스트 | 1932 passed | **1932 passed** (100% 통과) | 런타임 회귀 없음 |

---

## 3. 세부 수정 내역

### 3.1 `pyproject.toml`
- `[tool.mypy]`의 `disable_error_code`에서 `union-attr`, `attr-defined`, `return-value`를 제거했습니다.
- `assignment`와 `arg-type` 2종만 잔여 부채로 유지했습니다.

### 3.2 `src/app/models/bids.py` (`attr-defined` 2건 해소)
- `BidResult` 모델에 `resolved_winning_rate: Decimal | None = None` 비영속 속성을 명시적으로 선언했습니다.
- `src/app/services/bid_queries.py:515, 517`에서 낙찰 상세 템플릿(`result_detail.html`) 렌더링을 위해 동적으로 할당하던 속성에 대해 발생하던 `attr-defined` 오류 2건을 안전하게 해소했습니다.

### 3.3 `src/app/services/kb_builder.py` (`union-attr` 1건 해소)
- `rebuild_knowledge_base` 함수의 증분 delta 모드 분기에서 `collected_since`의 `datetime | None` 유니온을 검증하는 방어적 None 가드(`since_repr = collected_since.isoformat() if collected_since is not None else ""`)를 적용하여 `union-attr` 오류 1건을 해소했습니다.

### 3.4 `src/app/services/automation_orchestrator.py` (`union-attr` 6건 해소)
- `cancel_automation_request` 함수에서 실행 상태 취소 처리 시 `if running:` 조건문을 `if running and execution is not None:`로 변경하여 `execution` 인스턴스에 대한 `union-attr` 오류 6건(`raw_status_payload`, `status`, `stage_status`, `ended_at`, `logs_summary`)을 해소했습니다.

### 3.5 `src/rag/llm.py` (`union-attr` 2건 해소)
- `GeminiBackend`의 `generate` 및 `stream_generate` 메서드 시작 지점에 `if self._client is None:` 예외 검사를 추가하여 `_client`의 None 가능성을 방어하고 `self._client.models` 접근 시 발생하던 `union-attr` 오류 2건을 해소했습니다.

---

## 4. 잔여 타입 부채 현황 (Phase 2 대상)

현재 `disable_error_code`에 남아 있는 `assignment`(16건) 및 `arg-type`(40건)의 파일별 분포는 다음과 같습니다 (총 56건, 11개 파일).

| 파일 경로 | 총 오류 건수 | `arg-type` | `assignment` | 주요 원인 및 특이사항 |
| --- | --- | --- | --- | --- |
| `src/app/main.py` | 20건 | 20건 | 0건 | FastAPI 초기화 및 미들웨어 kwargs 타입 불일치 |
| `src/ml/model_registry.py` | 8건 | 0건 | 8건 | 다형성 래퍼 할당 및 None 초기화 타입 호환 |
| `src/ml/trainer.py` | 8건 | 7건 | 1건 | LGBMRegressor 파라미터 언패킹 및 지표 할당 |
| `src/tasks/automation_tasks.py` | 6건 | 3건 | 3건 | `asyncio.to_thread` 콜백 시그니처 및 변수 재할당 |
| `src/app/services/collector_service.py` | 4건 | 4건 | 0건 | 수집 파라미터 딕셔너리 타입 좁히기 필요 |
| `src/app/services/kb_builder.py` | 3건 | 1건 | 2건 | ChromaDB 쿼리 메타데이터 타입 변환 |
| `src/rag/llm.py` | 3건 | 2건 | 1건 | Gemini Content 리스트 불변성(invariant) 및 백엔드 할당 |
| `src/app/api/v1/chatbot.py` | 1건 | 1건 | 0건 | `_PendingRagAnswer` kb_status 딕셔너리 타입 매핑 |
| `src/app/services/conversation_state.py` | 1건 | 0건 | 1건 | 세션 상태 딕셔너리 변수 재할당 |
| `src/app/services/home_context.py` | 1건 | 1건 | 0건 | 홈 화면 컨텍스트 인자 타입 |
| `src/app/services/tools/trend_analyzer.py` | 1건 | 1건 | 0건 | 추세 분석기 입력 파라미터 타입 |
| **합계** | **56건** | **40건** | **16건** | **11개 파일** |

---

## 5. 검증 결과

1. **mypy 정적 검사**: `uv run mypy src/` -> 89개 파일 무오류 통과.
2. **단위 및 통합 테스트**: `uv run pytest tests/ -q -m 'not data_assets'` -> 1932건 전량 통과.
3. **린터 및 포매터**: `uv run ruff check src/` -> 규칙 위반 0건 통과.
4. **에이전트 규칙 검증**: `python3 scripts/validate_agent_rules.py --quiet` -> 12/12 전 항목 통과.
