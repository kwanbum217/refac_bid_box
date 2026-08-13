# 후속 Task 착수 지시서 — legacy GET SSE 경로 이관

> **작성일**: 2026-08-12
> **작성자**: S7 (운영 노출 게이트와 챗봇 SSE 경로 정리)
> **상태**: 착수 대기
> **선행**: S7 브랜치 `kwanbum217/s7-prod-gate-sse` 병합 완료

---

## 1. 배경

S7 에서 legacy `GET /api/v1/chatbot/stream` 제거를 시도했으나, 호출부 전수
확인 결과 실사용처가 둘 있어 코디네이터 판단으로 이관을 분리했습니다.

| 호출부 | 위치 | 소비 방식 |
| --- | --- | --- |
| React 챗봇 화면 | `frontend/src/App.tsx:200` | `EventSource` |
| 레이턴시 벤치마크 | `scripts/benchmark_latency.py:138` | `httpx.stream("GET", ...)` |

분리 이유는 두 가지입니다. 첫째, `.github/workflows/ci.yml` 에 프런트엔드
테스트 레인이 없어(macOS/Windows pytest 뿐) React 재작성 회귀를 자동으로 잡을
수단이 없습니다. 둘째, `benchmark_latency.py` 는 Phase 7 레이턴시 기준선을 재는
스크립트라 측정 경로를 바꾸면 기록된 P95 첫토큰 수치와의 비교 가능성이 끊깁니다.

S7 이 이미 처리한 것은 다음입니다. 이 Task 에서 다시 하지 마십시오.

- legacy 경로의 예외 원문 노출 차단 (일반 문구 + `trace_id`)
- legacy 경로 docstring 에 정본 경로·계약 차이·쿼리 문자열 잔존 명시
- 모듈 docstring 라우트 표에 정본/legacy 구분 표기

---

## 2. 정본 경로의 SSE 계약

`POST /api/v1/chatbot/chat/stream` (`src/app/api/v1/chatbot.py:696-764`)

정본은 **named SSE event** 를 씁니다. `event: <name>` 다음 줄에 `data: <JSON>`
가 옵니다. 직렬화는 `_sse()` 한 곳(`chatbot.py:680`)에서만 합니다.

| event | 시점 | data 페이로드 |
| --- | --- | --- |
| `stage` | 파이프라인 단계 전환 | `{"stage": "planning"\|"answering", "message": str}` |
| `plan` | 플래너 결과 확정 후 | `{"plan_steps": [{"step_id": str, "kind": str, "tool": str}], "intent": str}` |
| `token` | LLM 토큰마다 | `{"text": str}` |
| `docs` | 벡터 검색 결과 도착 | `{"docs": list}` |
| `final` | 완료 | `ChatResponse` 전체 (`src/app/schemas/chatbot.py:31`) |
| `error` | 실패 | `{"message": str, "trace_id": str}` |

이벤트 순서는 `stage` -> (`plan`) -> (`token`...) -> `final` 입니다. 요청이
자동화 확인 대기나 보안 차단으로 조기 종료되면 `plan` 과 `token` 없이 곧바로
`final` 만 나갈 수 있습니다.

**정본은 `final` 이 정답입니다.** `token` 을 이어붙인 문자열을 본문으로 쓰지
마십시오. 출처 표기와 Answer Guard 교정이 `final` 에만 반영됩니다.

`final` 의 `ChatResponse` 에는 legacy 에 없는 것들이 실립니다.

| 필드 | 의미 |
| --- | --- |
| `mode` | `answer` 또는 `action` |
| `intent` | 플래너가 판정한 의도 |
| `visualizations` | 차트 페이로드 |
| `suggestions`, `advisory_signals` | 선제 운영 제안 |
| `plan_steps` | 실행된 계획 단계 |
| `session_key` | 대화 세션 키 (이후 요청에 되돌려 보내야 이력이 이어집니다) |
| `provenance` | `trace_id` 를 포함한 출처 정보 |
| `kb_status`, `llm_backend`, `latency_ms` | 부가 메타 |

요청 본문은 `ChatRequest` 입니다. `{"message": str, "session_key": str|null,
"confirmation_token": str}`.

---

## 3. legacy 계약과의 차이

`GET /api/v1/chatbot/stream?query=...&session_key=...`
(`src/app/api/v1/chatbot.py:797`)

legacy 는 **이름 없는 `data:` 프레임**만 보내고 종류를 payload 안의 `type`
필드로 구분합니다. `rag_engine.stream_tokens` 의 dict 를 거의 그대로 흘립니다.

| 항목 | legacy | 정본 |
| --- | --- | --- |
| HTTP | `GET`, 질의가 쿼리 문자열 | `POST`, 질의가 요청 본문 |
| 프레임 | `data: {"type": ...}` | `event: <name>` + `data: {...}` |
| 종류 구분 | payload 의 `type` | SSE event 이름 |
| 이벤트 종류 | `docs`, `token`, `done`, `error` | `stage`, `plan`, `token`, `docs`, `final`, `error` |
| 정본 본문 | `done.final_answer` | `final` 의 `ChatResponse.answer` |
| 플래너·자동화 확인 | 없음 | 있음 |
| 차트 페이로드 | 없음 | `final.visualizations` |
| 세션 저장 | 없음 (읽기만, `session_key` 있을 때) | 있음 |
| DB 세션 | `SessionLocal()` 직접 개방 | `Depends(get_db)` |

`App.tsx:200` 이 지금 소비하는 것은 `docs`, `token`, `done` 셋뿐입니다.
`done.corrected_answer` 와 `done.final_answer` 를 무시하고 `token` 누적
문자열(`accumulated`)을 본문으로 씁니다. **이것이 현재 화면의 실질 결함입니다.**
Answer Guard 가 교정한 답이 아니라 LLM 원문이 남습니다.

---

## 4. 이관 시 깨질 수 있는 지점

| 위험 | 내용 | 대응 |
| --- | --- | --- |
| `EventSource` 는 POST 불가 | 브라우저 API 가 GET 전용입니다 | `fetch` + `ReadableStream` + `TextDecoder` 로 직접 파싱해야 합니다 |
| 프레임 파서 부재 | named event 를 읽으려면 `event:`/`data:` 를 라인 단위로 조립해야 합니다. 청크 경계가 프레임 중간을 자릅니다 | 버퍼를 유지하며 `\n\n` 로만 프레임을 확정하십시오. 청크마다 파싱하면 JSON 이 깨집니다 |
| 중지 버튼 | 지금은 `eventSource.close()` 입니다 | `AbortController` 로 대체해야 합니다 |
| 자동 재연결 소실 | `EventSource` 는 끊기면 자동 재접속합니다. `fetch` 는 하지 않습니다 | 현재 화면은 `onerror` 에서 곧바로 `close()` 하므로 실질 동작 차이는 없습니다. 재접속이 필요하면 명시적으로 구현하십시오 |
| 세션 이력 미연결 | 지금 화면은 `session_key` 를 보내지 않아 매 질문이 무맥락입니다 | `final.session_key` 를 상태에 보관하고 다음 요청에 실어야 합니다. 이건 이관의 부수 효과가 아니라 **기능 추가**이므로 별도로 검증하십시오 |
| 본문 정본 혼동 | `token` 누적을 계속 쓰면 교정이 사라집니다 | 스트리밍 중에는 `token` 누적으로 그리고, `final` 도착 시 `final.answer` 로 **교체**하십시오 |
| 신규 이벤트 무시 | `stage`, `plan` 이 처리되지 않으면 조용히 버려집니다 | 최소한 `stage.message` 를 진행 표시에 쓰십시오. 정본 경로는 플래너 단계가 있어 첫 토큰까지 시간이 더 걸립니다 |
| 오류 표시 | `error` 이벤트에 `trace_id` 가 실립니다 | 사용자에게 문구를 보여주고 `trace_id` 를 함께 노출하십시오. 문의 대응에 씁니다 |

---

## 5. `scripts/benchmark_latency.py` 판단

**경로를 바꾸는 대신 병행 측정을 권합니다.** 근거입니다.

1. 이 스크립트가 기록한 SSE 첫토큰 P95 는 Phase 7 기준선이고, 개선 이력
   (콜드 11.92초 -> 웜 0.61초, 사고 끔 0.41초)이 모두 legacy 경로 측정입니다.
   경로를 바꿔 버리면 이전 수치와 비교할 수 없어 기준선이 끊깁니다.
2. 두 경로의 첫토큰 시점은 구조적으로 다릅니다. 정본은 `stage`(planning) ->
   플래너 실행 -> `plan` -> `stage`(answering) 를 거친 뒤에야 첫 `token` 이
   나옵니다. 즉 정본의 첫토큰은 legacy 보다 **플래너 실행 시간만큼 느립니다.**
   같은 지표명으로 섞으면 회귀로 오독합니다.

따라서 이렇게 하십시오.

- legacy 측정을 그대로 남겨 기준선 연속성을 유지합니다.
- 정본 경로 측정을 **별도 지표로 추가**합니다. 최소 셋을 나눠 재십시오.
  `first_stage_ms`(요청 -> 첫 `stage`), `first_token_ms`(요청 -> 첫 `token`),
  `final_ms`(요청 -> `final`).
- 두 경로를 같은 질의 집합으로 재고, 차이를 플래너 비용으로 귀속시켜 기록합니다.
- legacy 호출부를 실제로 지우는 시점은 정본 지표가 목표를 만족한 뒤입니다.
  그때 legacy 측정 코드도 함께 지우고, 기준선 문서에 전환 지점을 남깁니다.

---

## 6. 검증 방법

이 Task 의 완료 조건입니다. 하나라도 못 하면 `escalation` 입니다.

### 6.1 자동 검증

```bash
uv run pytest tests/ -q
uv run python scripts/validate_agent_rules.py
uv run ruff check .
```

격리 트리의 알려진 예외 2건(`tests/test_data_preservation.py::test_model_bin_files_exist`,
`::test_chroma_db_exists`)은 차단 사유가 아닙니다.

추가할 테스트입니다.

- 정본 SSE 프레임 파서 단위 테스트. **청크 경계가 프레임 중간을 자르는
  입력**을 반드시 포함하십시오. 이게 가장 깨지기 쉽습니다.
- `final.answer` 가 `token` 누적과 다를 때 화면 본문이 `final.answer` 로
  교체되는지.
- `final.session_key` 가 다음 요청 본문에 실리는지.

프런트엔드 테스트 레인이 없다는 것이 이 Task 의 최대 위험입니다. 파서를
`App.tsx` 안에 인라인으로 두지 말고 별도 모듈로 빼서 테스트 가능하게 만들고,
CI 에 프런트엔드 레인을 추가할지 코디네이터에게 확인하십시오.

### 6.2 수동 검증 (컨테이너 필요, 코디네이터에게 요청)

격리 트리에는 `chroma_db/` 와 `data/model_files/*/model.bin` 이 따라오지
않으므로 직접 하지 말고 `escalation` 으로 요청하십시오.

1. 챗봇 화면에서 질문 -> 토큰이 흐르고 `final` 도착 시 본문이 교체되는지
2. 연속 질문 두 번 -> 두 번째 답변이 첫 질문 맥락을 잇는지 (`session_key`)
3. 중지 버튼 -> 스트림이 실제로 끊기는지
4. 차트를 요구하는 질의 -> `final.visualizations` 가 화면에 그려지는지
5. 자동화 확인이 필요한 질의 -> 확인 흐름이 나타나는지 (legacy 에는 없던 기능)
6. LLM 백엔드를 강제로 죽인 뒤 질의 -> `error` 문구와 `trace_id` 가 보이고
   예외 원문이 안 보이는지

---

## 7. 소유 파일 (이 Task)

| 파일 | 비고 |
| --- | --- |
| `frontend/src/App.tsx` | SSE 소비부 재작성 |
| `frontend/src/` 신규 파서 모듈 | 테스트 가능하게 분리 |
| `scripts/benchmark_latency.py` | 정본 경로 지표 **추가** (legacy 측정 유지) |
| `src/app/api/v1/chatbot.py` | legacy 경로 제거는 마지막 단계에서만 |
| `tests/` | 관련 테스트 |
| `docs/design/frontend_react_reproduction_design.md`, `docs/design/FRONTEND_DECISION.md` | legacy 경로 서술 갱신 |

`src/app/core/config.py`, `src/app/main.py` 는 건드릴 이유가 없습니다.
`src/rag/engine.py` 의 `stream_tokens` 이벤트 루프 블로킹은 여전히 범위 밖입니다.

---

## 8. 남은 미해결 사항

legacy 경로가 `Depends(get_db)` 가 아니라 `SessionLocal()` 을 직접 엽니다
(`chatbot.py` 의 `stream_chatbot`). 테스트의 `dependency_overrides` 를 우회해
격리 DB 가 아닌 곳을 볼 수 있습니다. S7 에서는 코디네이터 지시에 따라 legacy
경로의 동작을 바꾸지 않았습니다. 경로를 제거하면 함께 사라지므로 별도 수정보다
제거를 기다리는 편이 낫습니다. 제거가 더 늦어지면 이것만 따로 고치십시오.

---

## 9. 완료 처리 (2026-08-13)

정본 경로 레이턴시 벤치마크 결과, 첫 토큰 P95 1.721초와 전체 응답 P95
8.129초로 목표 게이트를 통과했습니다. 이를 바탕으로 legacy
`GET /api/v1/chatbot/stream`을 제거하고 정본
`POST /api/v1/chatbot/chat/stream`으로 단일화했습니다.

완료 커밋 계보는 다음과 같습니다.

- `1cda4e4`: 레거시 엔드포인트 삭제 및 벤치마크 단일화
- `016d4cf`: 리뷰 코멘트 반영 및 문서 정합성 정리 완료

원시 표본과 전체 판정은
[`docs/ops/phase7_latency_recheck_20260813.md`](../ops/phase7_latency_recheck_20260813.md)에
기록했습니다.
