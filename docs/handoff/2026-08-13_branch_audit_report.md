# 미병합 브랜치 감사 보고 — fix/arq-worker-compose, task-976479dbe8cb

> **작성일**: 2026-08-13
> **작업**: Orca Task `task_5d5a75d49c54` — 2.2 미병합 브랜치 감사
> **작업 트리**: `branch-audit` 워크트리, 브랜치 `kwanbum217/branch-audit`
> **기준**: `origin/main` 최신 (`bb6d84d`), `git fetch origin` 후 검증
> **범위**: 코드·다른 파일 수정 없음. 감사 보고서 문서만 작성

---

## 1. 실행 명령

| 단계 | 명령 | 용도 |
| --- | --- | --- |
| 1 | `git fetch origin` | 원격 브랜치 최신화 |
| 2 | `git log --oneline -5 origin/fix/arq-worker-compose` | 브랜치 커밋 확인 |
| 3 | `git merge-base main origin/fix/arq-worker-compose` | 병합 기준점 확인 |
| 4 | `git diff --name-status main...origin/fix/arq-worker-compose` | triple-dot 변경 파일 목록 |
| 5 | `git show --stat 2d5a0c8`, `git show --stat 20f5692` | 커밋별 변경 파일·수치 |
| 6 | `git show main:docker-compose.yml`, `git show main:tests/test_worker_compose.py` | main 흡수 여부 확인 |
| 7 | `git grep -c "model_retrain\|retrain_only\|manual_retrain_task\|/run/retrain" main -- src tests` | 20f5692 흡수 여부 확인 |
| 8 | `git log --oneline -5 origin/task-976479dbe8cb`, `git merge-base main origin/task-976479dbe8cb` | 브랜치·기준점 확인 |
| 9 | `git diff --name-status main...origin/task-976479dbe8cb` | triple-dot 변경 파일 목록 |
| 10 | `git show main:frontend/src/sseParser.ts`, `git show main:frontend/src/App.tsx` | sseParser·POST named-SSE 흡수 여부 확인 |
| 11 | `git diff main origin/task-976479dbe8cb -- <파일별>` | 파일 단위 차이 확인 |
| 12 | `git cat-file -e main:tasks.json` | tasks.json 잔여 확인 |

---

## 2. 브랜치별 triple-dot과 현재 main 비교

### 2.1 `origin/fix/arq-worker-compose`

- **병합 기준점**: `8d13dad`
- **커밋**: `2d5a0c8` (fix: run Arq worker in default Compose stack), `20f5692` (feat: add confirmed manual retraining API)
- **triple-dot**: 17 파일 (`M` 16, `A` 1)

| 변경 파일 | 비교 결과 |
| --- | --- |
| `docker-compose.yml`, `Makefile`, `.env.example` | 2d5a0c8 대상. main 은 worker 서비스 + `command: ["arq", "src.tasks.worker.WorkerSettings"]` 를 더 발전된 형태로 보유 |
| `tests/test_worker_compose.py` (`A`) | main 은 동일 파일을 보유하되 **healthcheck 대기(7건)·CORS 전달·스케줄 비활성** 검증으로 확장됨 |
| `docs/ops/environment_variables.md` | main 은 `ML_WEEKLY_RETRAIN_ENABLED=false` 기본값과 문서화를 보유 |
| `src/app/api/v1/automation.py`, `src/app/services/action_catalog.py`, `src/app/services/automation_orchestrator.py`, `src/tasks/automation_tasks.py`, `src/tasks/run_mode_matrix.py`, `src/tasks/worker.py` | 20f5692 대상. main 에 `model_retrain` 액션·`retrain_only` run_mode·`manual_retrain_task`·`/run/retrain` 라우터 **모두 부재** (`git grep` 미매치) |
| `tests/test_automation_api.py`, `tests/test_automation_bundle_parity.py`, `tests/test_chatbot_core.py` | 20f5692 대상. main 에 재학습 API 테스트 부재 |
| `docs/changelogs/work_log.md`, `docs/design/REFACTORING_DESIGN.md`, `docs/ops/cross_platform_guide.md` | 문서 이력. 판정에 영향 없음 |

### 2.2 `origin/task-976479dbe8cb`

- **병합 기준점**: `4679bc7`
- **커밋**: `761d032` (feat: migrate React chatbot to POST named-SSE path)
- **triple-dot**: 7 파일 (`M` 4, `A` 3)

| 변경 파일 | 비교 결과 |
| --- | --- |
| `frontend/src/App.tsx` | main 은 `POST /api/v1/chatbot/chat/stream` 호출을 **더 발전된 `chatStreamHandler.ts`(`processChatStream`, `buildChatRequestBody`) 기반**으로 보유 |
| `frontend/src/sseParser.ts` (`A`) | main 에 동일 파일 존재. `chatStreamHandler.ts` 가 이를 임포트해 확장 |
| `frontend/src/sseParser.test.ts` (`A`) | main 에 동일 파일 존재 (`node:test` 기반) |
| `frontend/package.json` | main 은 프런트 테스트 실행(`npm run test`)을 보유 |
| `.github/workflows/ci.yml` | main 은 프런트 워크디렉터리·`npm run test` 스텝을 보유 |
| `scripts/benchmark_latency.py` | main 과 **diff 0 라인 (동일)** |
| `tasks.json` (`A`) | **main 에 없음** (`git cat-file -e` fatal). 유일 잔여 산출물 |

---

## 3. 브랜치별 판정

### 3.1 `origin/fix/arq-worker-compose` — 부분 흡수 + 후속 재구현 판정

| 구분 | 판정 | 근거 |
| --- | --- | --- |
| `2d5a0c8` (Compose Arq worker) | **흡수됨** | main 은 동일 배선을 healthcheck·CORS 전달 등 더 발전된 계약으로 보유 (`test_worker_compose.py` 4개 테스트) |
| `20f5692` (수동 확인형 재학습 API) | **미흡수 → 최신 main 기준 별도 재구현 후속 작업** | main 소스·테스트에 `model_retrain`/`retrain_only`/`manual_retrain_task`/`/run/retrain` 전부 부재 |
| 브랜치 전체 병합 | **금지** | 병합 기준점 `8d13dad` 가 main(`bb6d84d`)보다 오래된 기반이라 충돌·퇴행 위험. 기능만 선별해 최신 main 에서 재구현하는 방향으로 판정 |

**후속 작업 권고**: 재학습 파이프라인(re-training) 진척과 맞물려 `model_retrain` 액션·`/run/retrain` 라우터·`retrain_only` run_mode 를 최신 main 에서 재구현하고, 자동화 테스트(`test_automation_api.py`, `test_automation_bundle_parity.py`)와 함께 병합할 것을 제안.

### 3.2 `origin/task-976479dbe8cb` — 흡수 + 삭제 후보

| 구분 | 판정 | 근거 |
| --- | --- | --- |
| `761d032` (React POST named-SSE) | **흡수됨** | main 에 POST named-SSE 정본(`POST /api/v1/chatbot/chat/stream`), `sseParser.ts`, `sseParser.test.ts`, `chatStreamHandler.ts`, CI 프런트 테스트가 더 발전된 형태로 존재. `benchmark_latency.py` 는 동일 |
| `tasks.json` | **삭제 후보** | Orca debug 산출물로 추정되는 JSON (runId·pane key 등). main 에 미존재, 앱에서 참조되지 않는 유일 잔여 |
| 브랜치 삭제·병합 | **실행하지 않음** | 감사 범위는 판정만. `tasks.json` 제거 판단·브랜치 정리는 담당자 결정 사항으로 남김 |

---

## 4. 검증 결과

| 항목 | 결과 |
| --- | --- |
| `uv run python scripts/validate_agent_rules.py` | 통과 |
| `git diff --check` | 오류 없음 |
| 커밋 | `docs: 미병합 브랜치 두 건을 재검증한다` — 문서 파일만 add |
| 푸시 | `git push -u origin kwanbum217/branch-audit` |