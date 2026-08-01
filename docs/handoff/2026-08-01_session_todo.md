# 세션 TODO (2026-08-01 기준)

> **작성일**: 2026-08-01
> **최종 갱신**: 2026-08-01 (세션 종료 시점)
> **상태**: Phase 0~6 완료, Phase 7 검증 잔존
> **기준 커밋**: `9a1a7c0` (main, origin 까지 push 완료)
> **테스트**: 196 passed / 1 skipped, `python scripts/validate_agent_rules.py` 6/6 PASS

---

## 재개 방법

작업 트리는 clean 이고 브랜치는 `main` 단독입니다. 미커밋 작업물이나 띄워둔 서버는 없습니다.

```bash
cd ~/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git pull

# 서버가 필요한 작업일 때만
redis-server --port 6379 --daemonize yes
.venv/bin/python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
# 워커까지 필요하면
.venv/bin/arq src.tasks.worker.WorkerSettings
```

화면은 `http://127.0.0.1:8000/` 입니다. Ollama 는 담당자 앱(`Ollama.app`)이 상시 구동하므로 별도 기동이 필요 없습니다.

**주의**: `dump.rdb` 가 Git 추적 파일이라 Redis 를 띄우면 변경으로 잡힙니다. 커밋 전에 `git checkout -- dump.rdb` 로 되돌리십시오. (`.gitignore` 처리 필요 — 아래 7번)

---

## 다음에 할 일

### 즉시 진행 가능 (서버 없이)

1. ~~**ChatAutomationApiTests 이식**~~ — **완료**. 상세는 아래 "ChatAutomationApiTests 이식 결과" 참조.
2. **주간 재학습 스케줄 추가** — `src/tasks/retrain_task.py`에 Arq 크론 설정 또는 `run_mode_matrix`에 `retrain` 모드 추가
3. **Alembic 마이그레이션 도입** — 원본 19개 히스토리 보존. `alembic init` → `autogenerate` → 기존 스키마와 정합성 검증
7. **`dump.rdb` Git 추적 해제** — Redis 런타임 스냅샷이라 실행할 때마다 변경됩니다. `git rm --cached dump.rdb` 후 `.gitignore` 등록

### 서버 필요 (Ollama + Redis)

4. **성능 벤치마크** — `scripts/benchmark_latency.py` 작성. SSE 첫 토큰 P95 3초, 전체 P95 20초 목표 측정
5. **재학습 E2E 검증** — 데이터→학습→평가→배포 전 주기 실증
6. **크로스 플랫폼 검증** — Windows 환경에서 Docker + Makefile 실행 확인

### 실기동 확인이 남은 항목

단위 테스트는 통과했으나 워커를 붙여 눈으로 확인하지 않은 부분입니다.

| 대상 | 확인할 것 |
| --- | --- |
| 챗봇 "요청 중지" 버튼 | 화면에서 눌렀을 때 실제 워커 작업이 죽는지 (`allow_abort_jobs` 경로) |
| 세션 사이드바 | 과거 대화를 눌렀을 때 `history`/`last_query` 로 대화창이 복원되는지 |
| 실행 재사용 | `full_validation` 을 두 번 승인했을 때 두 번째가 재사용으로 즉시 끝나는지 |

---

## 최근 세션 작업 요약 (2026-08-01)

| 커밋 | 내용 |
| --- | --- |
| `b6486ca` | 자동화 통합 테스트를 챗봇 경로 기준으로 재작성, `new_chat_session` URL 오타 수정 |
| `eabb9c1` | 원본 ChatAutomationApiTests 23개 이식, 누락 기능 5건 복원 |
| `8012ef1` | Arq 작업 중지(abort) 연결, 최근 실행 재사용 구현, 테스트 3개 추가 이식 |
| `9a1a7c0` | 콜백 도달성 판정을 Arq 기준으로 설계·구현 |

원본 재현율: ChatAutomationApiTests **26/28 이식** (제외 2건은 Arq 로 바꾼 이상 개념이 성립하지 않음).

---

## ChatAutomationApiTests 이식 결과

원본 클래스는 **28개**입니다 (`apps/chatbot/tests.py:784-1798`). **26개 이식 완료**, 2개는 Arq 로 바꾼 이상 대응 개념이 성립하지 않아 제외했습니다.

| 이식본 파일 | 테스트 수 | 범위 |
| --- | ---: | --- |
| `tests/test_chatbot_integration.py` | 15 | 세션 전환, 자동화 요청, 텍스트 승인, 진행 상황, 챗봇 화면 |
| `tests/test_chatbot_prediction.py` | 6 | 투찰가 예측, 답변 모드 계약, 대화 상태 영속 |
| `tests/test_automation_status_api.py` | 12 | 콜백 인증, 상태 조회, 실행 중지, 최근 실행 재사용, 확인 실행 |

제외한 2개와 사유입니다.

| 원본 테스트 | 제외 사유 |
| --- | --- |
| `test_chat_api_falls_back_to_polling_for_loopback_callback_base_url` | 전제가 반전됩니다. 원본은 외부 SaaS 인 Harness 가 사설망으로 들어올 수 없어 loopback/private 주소를 거부했습니다. Arq 워커는 같은 Docker 네트워크 안에 있어 사설 주소가 오히려 정상 설정이므로, 규칙을 그대로 옮기면 정상 배포에서 콜백이 영구히 꺼집니다. 판정 자체는 Arq 기준으로 새로 설계해 구현했습니다 (아래 참조) |
| `test_confirm_reuses_recent_harness_summary_without_new_run` | 원격 Harness API 이력을 끌어와 로컬에 적재하는 흐름입니다. Arq 는 외부 실행 레지스트리가 없고 `pipeline_executions` 가 이미 유일한 진실 원천이라 로컬 재사용 테스트와 같은 것이 됩니다 |

### 이식 과정에서 복원한 누락 기능

테스트가 통과하지 않아 드러난 실제 이식 누락분입니다. 테스트를 고치지 않고 구현을 채웠습니다.

| 대상 | 누락 내용 |
| --- | --- |
| `src/app/api/v1/chatbot.py` | 텍스트 승인("승인 후 실행해줘")과 `confirmation_token` 처리 자체가 없었습니다 |
| `src/app/api/v1/chatbot.py` | 답변 모드가 `suggestions`/`advisory_signals` 를 전혀 싣지 않았습니다 |
| `src/app/schemas/chatbot.py` | 세션 전환 응답에 `last_query`/`history` 가 없어 `chat.html:1734` 의 대화 복원이 동작하지 않았습니다 |
| `src/app/services/conversation_state.py` | 사용자 고정 메모리(`user:{id}`)가 통째로 빠져 세션 간 필터가 이어지지 않았습니다 |
| `src/app/services/automation_orchestrator.py` | `_step_status_lines` 가 "Step 진행 상황" 머리글, 단계 순서, 요약 표기를 누락했습니다 |
| `src/app/services/automation_orchestrator.py` | 실행 중지가 DB 레코드만 바꾸고 워커 작업은 방치했습니다. Arq 작업 ID 를 남기지 않아 붙잡을 핸들조차 없었습니다 |
| `src/app/services/automation_orchestrator.py` | 고비용 작업의 최근 성공 실행 재사용이 없어 승인할 때마다 무조건 새로 실행했습니다 |

### 실행 중지 (Arq abort) 구현 메모

`abort_arq_job` 은 arq 의 `Job.abort()` 를 쓰지 않습니다. `Job.abort()` 는 중단 신호를 넣은 뒤 워커의 확인 결과까지 기다리므로, 중지 버튼이 워커 응답만큼(기본 무한, 지정 시 timeout 만큼) 멈춥니다. 신호 전달까지만 수행해 응답을 즉시 돌려주고, `worker_abort_requested` 플래그도 "실제 중단됨"이 아니라 "중단 신호를 전달함"을 뜻합니다.

워커 쪽 `allow_abort_jobs = True`(`src/tasks/worker.py`)가 켜져 있어야 동작합니다. 실제 워커를 띄워 10초 태스크를 중간에 죽이는 것까지 확인했습니다.

### 재사용 정책

`full_validation` 만 대상이며(`REUSABLE_ACTIONS`), 신선도 창은 72시간(`REUSE_MAX_AGE_HOURS`)입니다. `AUTOMATION_REUSE_RECENT=false` 로 끌 수 있습니다.

### 작성 규칙

자동화 관련 테스트는 반드시 `/api/v1/chatbot/chat` 을 거쳐 작성합니다. 자동화 엔드포인트를 직접 호출하면 원본이 검증하려던 계획 수립 경로를 건너뛰고 `tests/test_automation_api.py` 와 중복됩니다.

---

## 콜백 도달성 판정 (Arq 기준 신규 설계)

`_callback_metadata` 가 읽던 `callback_mode`/`callback_configured` 를 아무도 채우지 않아 모든 작업이 기본값 `polling` 으로 보고되던 문제를 해결했습니다. 검증은 `tests/test_callback_delivery.py` (21건).

### 원본과 무엇이 다른가

원본의 질문은 "외부 SaaS 가 우리 망으로 들어올 수 있는가" 였고, 그래서 사설 대역 전체를 거부했습니다. Arq 의 질문은 "워커의 단계별 보고가 요청 레코드까지 돌아올 수 있는가" 이고, 워커는 이미 같은 네트워크 안에 있습니다. 따라서 판정 축이 바뀝니다.

| 축 | 원본 (Harness) | 이식본 (Arq) |
| --- | --- | --- |
| 호출자 위치 | 외부 클라우드 | 같은 네트워크 |
| 사설 주소 | 거부 | **허용** (`http://app:8000` 이 정상) |
| 루프백 | 거부 | 거부 (사유가 다름: 워커 자기 자신을 가리킴) |
| 경로 종류 | callback / polling | **direct** / callback / polling |

`direct` 는 원본에 없던 모드입니다. 번들 워커는 앱과 같은 DB 를 보므로 HTTP 를 거치지 않고 `apply_callback_payload` 로 바로 기록합니다. 이게 기본 구성이자 가장 확실한 경로인데, 기존 코드는 이 경우를 `polling` 이라 잘못 안내하고 있었습니다.

### 판정 규칙

`resolve_callback_delivery(job_id)` (`automation_orchestrator.py`)

| `AUTOMATION_CALLBACK_BASE_URL` | `AUTOMATION_WORKER_SHARES_DB` | 모드 |
| --- | --- | --- |
| 없음 | `true` | `direct` |
| 없음 | `false` | `polling` |
| 정상 주소 | 무관 | `callback` |
| 루프백 / 형식 오류 | `true` | `direct` (안내 문구 첨부) |
| 루프백 / 형식 오류 | `false` | `polling` (안내 문구 첨부) |

판정 결과는 요청 생성 시점에 `AutomationRequest.payload` 에 기록되어 `job` 응답 계약과 답변 문구에 그대로 실립니다.

### 워커 보고 경로

`_report`(`src/tasks/automation_tasks.py`)는 `callback_url` 이 있으면 HTTP 로 보내고, 없거나 전송이 실패하면 같은 페이로드를 DB 에 기록합니다. 전송 실패로 단계 보고가 유실되지 않습니다. 실제 uvicorn 을 띄워 워커 → API → 요청 레코드 왕복까지 확인했습니다.

`callback_url`/`callback_token` 은 `callback` 모드일 때만 워커에 전달합니다. `direct` 모드에서는 빈 값을 넘겨 불필요한 HTTP 왕복과 토큰 노출을 만들지 않습니다.
---

## 참조

- 인수인계: `docs/handoff/2026-07-31_parity_restoration_handoff.md`
- 설계서 체크리스트: `docs/design/REFACTORING_DESIGN.md` Phase 7
- 프론트엔드 결정: `docs/design/FRONTEND_DECISION.md`
- 테스트 현황: 196 passed / 1 skipped (21개 파일)
