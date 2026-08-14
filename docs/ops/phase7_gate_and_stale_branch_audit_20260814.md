# Phase 7 성능 게이트 표본 수 규약 및 미병합 브랜치 감사

> **작성일**: 2026-08-14
> **범위**: (A) Phase 7/G3 성능 게이트의 측정 표본 수 규약 존재 여부, (B) `feat/codex-task-routing` 및 `integrate/arq-worker-cutover` 미병합 브랜치 판정
> **판정 요약**: (A) 4개 항목 중 4개 규정 없음 -- 게이트에 구멍이 있습니다. (B) codex 브랜치는 추가 조사 필요, arq 브랜치는 폐기 판정

---

## A. Phase 7 성능 게이트 표본 수 규약 감사

### A.1 감사 대상 문서

Phase 7 또는 G3 성능 게이트를 정의하거나 참조하는 `docs/` 내 문서를 전수 탐색했습니다.

| 문서 | 게이트 관련 내용 |
| --- | --- |
| [`docs/design/REFACTORING_DESIGN.md:672-680`](../design/REFACTORING_DESIGN.md#L672-L680) | Phase 7 정의, P95 목표 수치, 실측 결과 기재 |
| [`docs/ops/phase7_cutover_report_20260804.md`](phase7_cutover_report_20260804.md) | G3 통과/보류 판정, 측정 조건 표 |
| [`docs/ops/latency_benchmark.md`](latency_benchmark.md) | 측정 도구, 표본 수, 서버 조건 기재 |
| [`docs/ops/phase7_latency_recheck_20260813.md`](phase7_latency_recheck_20260813.md) | 후보 A/B 재측정, 동시성별 판정 |
| [`docs/ops/phase8_predict_microbatch_20260814.md`](phase8_predict_microbatch_20260814.md) | 마이크로배칭 c10 반복 측정 |
| [`docs/design/sse_first_token_20260805.md`](../design/sse_first_token_20260805.md) | SSE 첫 토큰 측정, 표본 10회 |
| [`docs/handoff/2026-08-13_future_work_backlog.md:96-133`](../handoff/2026-08-13_future_work_backlog.md#L96-L133) | 컷오버 차단 해소, 완료 기준 |
| [`docs/handoff/2026-08-13_prediction_p95_diagnosis.md:210-233`](../handoff/2026-08-13_prediction_p95_diagnosis.md#L210-L233) | 재측정 매트릭스, 판정 기준 표 |
| [`docs/handoff/2026-08-14_session_handoff.md:58-76`](../handoff/2026-08-14_session_handoff.md#L58-L76) | 표본 수에 따라 통과/미달이 갈리는 문제 인식 |

### A.2 항목별 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| **측정 표본 수 (요청 몇 회)** | **규정 없음** | 문서마다 다른 표본 수를 사용합니다. `latency_benchmark.md:20`은 SSE 15회/예측 200회, `phase7_cutover_report_20260804.md:37`은 SSE 20회/예측 100회, `phase7_latency_recheck_20260813.md:46`은 예측 100회, `sse_first_token_20260805.md:92`는 10회입니다. 어떤 문서도 "게이트 통과 판정에는 N회 이상을 사용해야 한다"는 규약을 두지 않습니다. `2026-08-14_session_handoff.md:62-68`은 100회와 600회에서 판정이 갈리는 문제를 명시적으로 지적하면서도 규약을 제안하지 않았습니다 |
| **반복 회차 수 및 판정 통계량 (중앙값/최악값/평균)** | **규정 없음** | `phase8_predict_microbatch_20260814.md:51-53`은 c10을 3회 반복 측정했지만, 3회 중 어느 값(중앙값 107.6ms, 최솟값 67.0ms, 최댓값 163.3ms)을 게이트 판정에 쓰는지 정해져 있지 않습니다. `sse_first_token_20260805.md:88`은 장비 부하에 따라 P95가 4.41초에서 5.57초로 튀었다고 기록했으나 어느 실행의 값을 기준으로 삼는지 규정하지 않습니다. `2026-08-13_prediction_p95_diagnosis.md:214`는 "3회 반복"이라고 적었지만 3회의 대표값 선택 규칙은 없습니다 |
| **warmup 처리 방식** | **규정 없음** | `phase7_latency_recheck_20260813.md:50`은 "직후 예측 API만 같은 표본 수와 동시성으로 다시 측정"이라 했고, `prediction_p95_diagnosis.md:235-236`은 "cold 측정은 restart 직후 30초 안, warm은 cold 종료 후 2분 이상 경과"라 했습니다. 이는 특정 실험의 절차 기술이며, 게이트 판정에 warmup 요청을 포함하는지 제외하는지, 몇 회를 버리는지에 대한 공통 규약이 아닙니다. `phase7_cutover_report_20260804.md:150`은 "예열 상태 1.4ms"와 "기동 직후 19.1ms"를 구분하면서 후자를 채택했지만, 이 선택이 앞으로의 모든 게이트 판정에 적용된다는 규정은 없습니다 |
| **동시성 수준별 기준 (c1, c2, c4, c10 각각)** | **규정 없음** | `prediction_p95_diagnosis.md:231`은 "warm concurrency 10 P95 <= 100ms"를 목표로 적었고, `future_work_backlog.md:129-131`은 c10 P95 100ms 이하와 c1/c2/c4 역행 없음을 완료 기준으로 적었습니다. 그러나 이는 예측 API 한정의 작업 기준이며, c1/c2/c4 각각의 P95 목표 수치는 정의되어 있지 않습니다. SSE 엔드포인트는 동시성 수준별 기준 자체가 없습니다. `REFACTORING_DESIGN.md:66`의 "P95 레이턴시 50% 감소"는 어떤 동시성 조건에서의 50%인지 명시하지 않습니다 |

### A.3 감사 결론

Phase 7 성능 게이트는 **목표 수치(P95 100ms, 첫 토큰 3초, 전체 20초)만 규정하고 측정 프로토콜은 규정하지 않습니다.** 같은 코드가 표본 수 100회에서 c10 P95 107.6ms(미달), 600회에서 38~44ms(통과)로 갈리는 현상이 `2026-08-14_session_handoff.md:62-68`에 기록되어 있으며, 이는 게이트 프로토콜이 없어 판정이 측정 조건에 의존하는 직접적 결과입니다. 네 항목 모두 규정이 없다는 것 자체가 게이트의 구멍입니다.

---

## B. 미병합 브랜치 감사

### B.1 `feat/codex-task-routing`

#### 커밋 목록

```
70bd666 feat: Codex 작업 라우팅 스킬 추가
```

마지막 커밋 날짜: **2026-08-05 11:05:06 +0900** (9일 전)

#### 변경 규모

```
 .agents/skills/codex-task-router/SKILL.md          | 72 +++++++++++
 .agents/skills/codex-task-router/agents/openai.yaml|  4 ++
 .agents/skills/codex-task-router/references/routing-matrix.md | 62 ++++++++
 .antigravity/rules.md                              |  2 +
 .claude/skills/codex-task-router/SKILL.md          | 72 +++++++++++
 .claude/skills/codex-task-router/agents/openai.yaml|  4 ++
 .claude/skills/codex-task-router/references/routing-matrix.md | 62 ++++++++
 .codex/agents/explorer.toml                        | 12 ++++
 .codex/agents/implementer.toml                     | 12 ++++
 .codex/agents/risk-reviewer.toml                   | 12 ++++
 .codex/config.toml                                 |  7 +++
 .opencode/skills/codex-task-router/SKILL.md        | 72 +++++++++++
 .opencode/skills/codex-task-router/agents/openai.yaml |  4 ++
 .opencode/skills/codex-task-router/references/routing-matrix.md | 62 ++++++++
 AGENTS.md                                          |  4 +-
 SKILLS.md                                          |  3 +-
 docs/ops/multi_agent_setup.md                      |  4 +-
 17 files changed, 466 insertions(+), 4 deletions(-)
```

#### main 겹침 분석

| 파일 | 분석 |
| --- | --- |
| 14개 신규 파일(`.agents/skills/codex-task-router/`, `.claude/skills/codex-task-router/`, `.opencode/skills/codex-task-router/`, `.codex/`) | main에 존재하지 않습니다. 브랜치 고유 추가분입니다 |
| `AGENTS.md` | 브랜치는 0장 스킬 수를 "8개"에서 "8개와 운영 공통 3개"로, 9장 인덱스에 `codex-task-router` 행을 추가합니다. main의 현재 `AGENTS.md`는 0장을 "5개 CLI 동기화... 12개"로 이미 갱신했고 9장에 12개 스킬을 열거합니다. **main이 브랜치보다 더 최신 상태이며, 브랜치의 수정은 main의 현재 버전에 대해 충돌합니다** |
| `SKILLS.md` | 같은 양상입니다. 브랜치는 "8개"를 "8개와 운영 공통 3개"로 바꿨지만 main은 이미 "12개"입니다 |
| `docs/ops/multi_agent_setup.md` | 브랜치는 스킬 수와 `.codex/` 경로를 추가했지만, main 측도 이 파일을 별도로 갱신했습니다 |
| `.antigravity/rules.md` | main에 이미 존재합니다. 브랜치가 2줄을 추가합니다 |

#### 판정: **추가 조사 필요**

근거:
- **스킬 콘텐츠 자체**(14개 신규 파일)는 main에 반영되지 않았습니다. Codex 전용 에이전트 설정(`.codex/config.toml`, `.codex/agents/*.toml`)과 `codex-task-router` 스킬 3벌 미러가 해당됩니다.
- 그러나 **공유 문서 3개**(`AGENTS.md`, `SKILLS.md`, `docs/ops/multi_agent_setup.md`)는 main이 브랜치 분기 이후 대폭 갱신되어 단순 병합 시 충돌이 발생합니다. 스킬 수 표기("8개" -> main은 이미 "12개")가 충돌 지점입니다.
- Codex(GPT-5.6) 에이전트가 현재 워크플로에서 활발히 사용되는지, `codex-task-router` 스킬의 라우팅 매트릭스가 현행 스킬 인덱스(12개)와 정합하는지를 확인해야 합니다. 확인 없이 병합하면 `validate_agent_rules.py`가 실패할 수 있습니다.

### B.2 `integrate/arq-worker-cutover`

#### 커밋 목록

```
602072f fix: align home notice cards in three columns
81866a3 fix: prevent home notice card clipping
d0bc628 fix: prevent home card content overflow
bfece7e fix: restore home panel readability
59650d8 fix: show foreign bids and compact home panels
fd36084 fix: carry bid result context into ai chat
9c60f79 fix: expose recent bid panels on home
ecce945 docs: set Ollama SSE first-token target
c70fd55 fix: support MySQL UUID baseline migration
daa1287 merge: Arq 워커와 수동 재학습 실행 경로 통합
20f5692 feat: add confirmed manual retraining API
2d5a0c8 fix: run Arq worker in default Compose stack
```

마지막 커밋 날짜: **2026-08-05 15:22:05 +0900** (9일 전)

#### 변경 규모

```
35 files changed, 520 insertions(+), 90 deletions(-)
```

#### main 겹침 분석

| 구분 | 파일 수 | 내용 |
| --- | ---: | --- |
| 양쪽 모두 수정 | 32 | `.env.example`, `Makefile`, `README.md`, `docker-compose.yml`, 문서 8개, 마이그레이션 1개, 스크립트 1개, `src/` 12개, `tests/` 8개 |
| 브랜치만 수정 | 3 | `docs/ops/latency_benchmark.md`, `docs/README.md`, `docs/ops/cross_platform_guide.md` -- 이들도 main에서 별도로 수정되었습니다 |
| 브랜치 고유 신규 파일 | **0** | 없습니다 |

핵심 기능의 main 반영 상태입니다.

| 브랜치 기능 | main 반영 여부 |
| --- | --- |
| `docker-compose.yml` worker 서비스 추가 | **반영됨.** main의 worker 서비스가 브랜치보다 훨씬 상세합니다(SECRET_KEY, CORS, MEILI, G2B_SERVICE_KEY, KST 타임존 등 추가). 브랜치 버전은 하드코딩 패스워드에 환경변수 미참조로 열화된 상태입니다 |
| 수동 재학습 API (`automation.py`, `automation_tasks.py`) | **반영됨.** `src/app/api/v1/automation.py`, `src/tasks/automation_tasks.py` 모두 main에 존재하며 같은 기능의 더 발전된 버전입니다 |
| `worker.py` retrain cron | **반영됨.** main의 `worker.py`에 `weekly_retrain_task`, `manual_retrain_task`, `run_retrain_pipeline_task`가 모두 등록되어 있습니다 |
| MySQL UUID 마이그레이션 수정 | **반영됨.** `c70fd55`의 수정과 같은 내용이 main의 `99a3578`에 있습니다 |
| 홈 패널 UI (`index.html`, `home_context.py`) | **반영됨.** main에 이미 병합되어 있고 그 이후로도 추가 수정이 있었습니다 |
| AI 채팅 컨텍스트 (`chat.html`, `result_detail.html`) | **반영됨.** main의 `c844727`에 동일 기능이 병합되어 있습니다 |

#### 판정: **폐기**

근거:
- 브랜치의 12개 커밋이 다루는 기능(Arq 워커 Compose 통합, 수동 재학습 API, 홈 패널, AI 채팅 컨텍스트, MySQL UUID 수정)은 **전부 main에 다른 경로로 이미 반영**되어 있습니다.
- 브랜치 고유 신규 파일이 0개입니다. 35개 변경 파일 중 32개가 main에서도 수정되었으며, main 측이 더 발전된 상태입니다.
- 병합을 시도하면 32개 파일에서 충돌이 발생하고, 해결하더라도 main에 이미 있는 기능의 열화된 버전이 섞여 들어갈 위험이 있습니다.
- `docker-compose.yml`의 worker 서비스만 비교해도 main이 환경변수 분리, 보안 설정, KST 타임존, MeiliSearch 연동 등에서 우위입니다.

---

## 감사 기록

| 항목 | 값 |
| --- | --- |
| 감사 브랜치 | `audit/phase7-gate-stale-branches` |
| 기준 main 커밋 | `f5eb107` |
| 감사 수행자 | Antigravity (Claude Opus 4.6) |
| 감사 범위 | `docs/` 내 Phase 7 게이트 문서 9개, 로컬 브랜치 2개 |
