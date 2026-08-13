# 착수 목록 — P0 후속 마감 이후

> **작성일**: 2026-08-13
> **기준 상태**: `main` `11d302b`, `origin` 동기화 완료, 미커밋 없음
> **직전 문서**: [`2026-08-11_next_session_todo.md`](2026-08-11_next_session_todo.md)
> **방침**: 용역(Servc) 우선

---

## 0. 세션 시작 시 먼저 할 것

| 순서 | 명령 | 이유 |
| --- | --- | --- |
| 1 | `orca orchestration check --ack <delivery_id>` | ack 하지 않으면 같은 배치가 계속 재배달됩니다 |
| 2 | `export PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin` | Docker CLI 가 기본 PATH 에 없습니다 |
| 3 | `docker compose up -d db redis meilisearch` | 서비스명은 `mysql` 이 아니라 `db` 입니다 |
| 4 | db 가 `healthy` 될 때까지 대기 | 준비 전에 pytest 를 돌리면 50건 실패로 오판합니다 |

---

## 1. 직전 세션에서 마감한 것

| 항목 | 결과 |
| --- | --- |
| A5 출처 가드 최종 검수 | `be14c58`. 타입 검증, 범주 집계, fail-closed 종료 코드 1 |
| A1~A5 통합 | `4107074` 에 최신 `main` 접합 후 `6285b73` 으로 `main` 병합 |
| 회귀 | 본 저장소 백엔드 963 passed 2 skipped, 프런트 11 passed, `validate_agent_rules` 6/6 |
| 섹션 자원 반납 | 워크트리 6개 해제, 원격 병합 완료 브랜치 26개 삭제 |
| Orca Antigravity 사용량 | 별도 저장소 `kwanbum217/antigravity-usage-status` 에 `88e37b6` 로컬 커밋 |

`2026-08-11` 목록의 **E(자원 정리)** 와 **B(`docs-env-contract`)** 는 종결되었습니다.

---

## 2. 착수 후보 (우선순위 순)

### 2.1 신 제도 표본 부족 — 최우선

2026-08-13 학습 프레임(`data/feature_store/dataset_Servc.parquet`) 실측입니다.

| 구분 | 건수 | 비중 |
| --- | ---: | ---: |
| 전체 라벨 보유 | 917,629 | 100% |
| 2026-05-26 이후(신 제도) | 11,712 | **1.276%** |

최신 공고일은 `2026-07-31` 입니다.

`src/ml/features.py:32` 의 `REGIME_SHIFT_DATE` 와 `features.py:268` 의
`is_post_regime_shift` 지시자는 **이미 존재합니다.** 문제는 지시자의 유무가
아니라 가중치입니다. 현재 들어오는 실제 요청은 사실상 전부 신 제도인데 학습
근거는 1.276% 뿐이고, 하한율이 2%p 일괄 인상된 체제라 구 제도 98.7% 가 평균을
끌어당깁니다.

지시자 하나로 절편만 옮기는 것으로 충분한지, 신 제도 표본 가중이나 별도 보정이
필요한지는 **측정으로 갈립니다.**

**상태 업데이트:** 레짐 대리 측정 완료와 Champion OOS 미판정 상태입니다.

### 2.2 미병합 브랜치 두 건 처분

| 브랜치 | 내용 | 판단 |
| --- | --- | --- |
| `fix/arq-worker-compose` | 17파일, 커밋 2건. `feat: add confirmed manual retraining API` 포함 | `main` 에 재학습 API 가 **없음을 확인**했습니다. 실질 미병합 기능입니다 |
| `task-976479dbe8cb` | A3 의 초기판 React SSE 이관 | `frontend/src/sseParser.ts` 와 CI 프런트 레인 모두 `main` 에 이미 있습니다. `tasks.json` 만 잔여 |

**상태 업데이트:** 브랜치 감사 완료 및 원격 두 건의 남은 결정 상태입니다.

### 2.3 legacy GET SSE 경로 제거

**완료되었습니다.** legacy `GET /api/v1/chatbot/stream`을 제거하고 모든
호출부를 정본 `POST /api/v1/chatbot/chat/stream`으로 전환했습니다.

| 조건 | 최종 상태 |
| --- | --- |
| 정본 첫 토큰 P95 | 1.721초, 목표 3초 통과 |
| 정본 전체 응답 P95 | 8.129초, 목표 20초 통과 |
| legacy GET 라우트 | 제거, 회귀 테스트에서 404 확인 |
| 정본 POST 라우트 | 유지, SSE 응답 회귀 테스트 통과 |

이로써 `SessionLocal()` 직접 사용과 테스트 `dependency_overrides` 우회 문제도
함께 제거되었습니다. 원시 표본과 판정 근거는
[`docs/ops/phase7_latency_recheck_20260813.md`](../ops/phase7_latency_recheck_20260813.md)에
기록했습니다.

### 2.4 운영 컷오버 전 점검

| 항목 | 현재 | 조치 |
| --- | --- | --- |
| `Dockerfile:10` | Dockerfile 교정 완료 | 오타 수정 및 apt 캐시 제거 정상화 |
| `CORS_ALLOWED_ORIGINS` | 검증기 완비, `.env` 는 `development` | 운영 전환 시 실제 오리진 지정. 비거나 와일드카드면 기동을 거부합니다(의도된 동작) |
| 쿠키 `samesite="lax"` | `src/app/api/v1/accounts.py:141` | CORS 를 좁힌 뒤 `strict` 상향 검토. 지금은 lax 가 방어선입니다 |
| Phase 7 P95 실측 | P95 후보 A와 B 실측 완료 | 두 후보 모두 100ms 미달 확인 |

권장: **Opus 5 / effort low~medium**. 절차적입니다.

### 2.5 ML 후속 (2026-08-11 목록의 잔여분)

| 항목 | 내용 | 권장 |
| --- | --- | --- |
| A0 하한율 결측 재분해 | 2025-01 원천 전환 이후 표본으로 재분해. 지시자 하나로 부족한지 판정 | Opus 5 / high |
| A1 제도 플래그 특징 | 미사용 플래그 5개. `indstrytyLmtYn` 편향 0.42%p (t +19.4 / -10.5) | Opus 5 / high |
| A2 Cnstwk parquet 재생성 | 구형 12컬럼이라 `lwlt_rate` 포함 16필드 결손, 1,358,882행 | 용역이 아니므로 **방침 확인 선행** |
| C Thng 후속 | 재생성물 검증 완료, 연기 상태 | 보류 유지 |
| D 적격심사 피복률 | t 가 전부 -1.6 미만이라 유의하지 않음 | **지금 손대지 말 것** |

A1 의 `prdctClsfcLmtYn` 과 `rbidPermsnYn` 은 2025-01 전환이 있어 그대로 넣으면
두 체제를 한 수준으로 섞습니다. 기존 `is_post_regime_shift` 는 2026-05-26
경계라 별도 지시자가 필요합니다.

---

## 3. 권장 착수 순서

2.1 → 2.2 → 2.4 → 2.3 → 2.5

2.1 을 앞에 두는 이유는 이것만이 **지금 사용자에게 나가는 예측값의 정확도**에
직접 걸려 있기 때문입니다. 나머지는 위생과 부채입니다.

---

## 4. 하지 말 것

| 항목 | 이유 |
| --- | --- |
| LightGBMLSS, NGBoost 도입 | 2026-08-11 기각. `servc_interval_coverage_recheck_20260811.md` |
| `asignBdgtAmt`, `cntrctCnclsMthdNm` 특징 추가 | 기존 `base_amount`, `cntrct_mthd_nm` 과 100% 동일. 중복 |
| 잔차 후처리 계열 재시도 | 다섯 축 전부 기각됨 |
| 분위 `num_leaves` 127/255 | 세 분할 전부에서 63 최소 |
| `quantile` alpha 조정 | 분할 변동 안이었음 |

착수 전 `servc-model-tuning` 스킬의 기각 목록을 먼저 읽으십시오.

---

## 5. 재개 시 함정

| 항목 | 내용 |
| --- | --- |
| pytest 조기 실행 | db `healthy` 전에 돌리면 50건 실패. 컨테이너 준비를 먼저 확인 |
| 격리 트리 검증 예외 | `test_model_bin_files_exist`, `test_chroma_db_exists` 실패는 정상. 주 저장소에서 단독 재실행 |
| 운영 경로 스크립트 | `model.bin` 을 읽으므로 격리 트리에서 동작하지 않습니다. 주 저장소에서만 실행 |
| 격리 트리 `.env` | Git 미추적이라 따라가지 않습니다. 워커 기동 직후 코디네이터가 배치 |
| Orca Run 바인딩 | `run-use --id <run>` 입니다. `--run` 은 없는 플래그입니다 |
| Orca Task 갱신 | `task-update --id <task>` 입니다. `--task` 는 `dispatch-show` 전용입니다 |
| Orca 메시지 | `--ack <delivery_id>` 없이는 같은 배치가 계속 재배달됩니다 |
| `orchestration ask` | `send` 로는 풀리지 않습니다. `reply --id <msg_id>` 만 해제합니다 |
| Compose 서비스명 | MySQL 서비스는 `db` 입니다. `mysql` 이 아닙니다 |
| curl 한글 질의 | 미인코딩 UTF-8 은 uvicorn 이 400 으로 거부. `--data-urlencode` 사용 |
| UI 측정 | 목록 페이지는 로그인 필수. 임시 계정은 반드시 삭제하고 사용자 4명 복귀 확인 |

상세 조율 절차는 [`../ops/orca_orchestration_playbook.md`](../ops/orca_orchestration_playbook.md) 를 따르십시오.

---

## 6. 에이전트 배분 방침 (2026-08-13 확정)

메인 코디네이터는 **GPT** 입니다. 이 시점의 잔여 한도는 Claude 5시간 창 69%,
GPT 주간 100%(리셋 직후), Antigravity 5시간 창 87% 입니다. 희소한 것은 Claude
총량이 아니라 **5시간 창 안의 Claude** 이므로, GPT 를 주력으로 돌리고 Claude 는
판정이 갈리는 지점에만 씁니다.

### 6.1 과제별 배정

| 과제 | 성격 | 배정 | effort |
| --- | --- | --- | --- |
| 2.1 신 제도 표본 부족 | 판정. 조치 여부 자체가 결론 | Claude Opus 5 | high |
| 2.5 A0 하한율 결측 재분해 | 판정 | Claude Opus 5 또는 GPT | high |
| 2.5 A1 제도 플래그 특징 | 실험 + 판정 | GPT | high |
| 2.2 미병합 브랜치 재검증 | 기계적. 테스트가 정오를 가림 | GPT | medium |
| 2.3 legacy GET SSE 제거 | 실측 해석이 들어감 | GPT | medium |
| 2.4 `Dockerfile` 오타 한 줄 | 순수 기계적 | 무료 모델 | low |
| 2.4 CORS·SameSite 상향 | 보안 계약 | GPT 이상 | medium |
| 문서 색인·changelog 갱신 | 기계적 | 무료 모델 / Antigravity | low |

### 6.2 무료 모델 사용 기준

**자동 검증이 정오를 판정해 주는 작업만** 넘깁니다. 테스트가 빨간불이면 틀린
것이고 초록불이면 맞은 것인 작업은 안전합니다. 반대로 유의성 판단, 승격 여부,
회귀 여부처럼 **기준을 사람이 정해야 하는 작업은 넘기지 않습니다.**

공유 자원 소유권(`main` 병합, 서빙 루트 점유, DB, 대량 색인)도 무료 모델에
주지 않습니다.

### 6.3 Ollama gemma4:e4b 용도 충돌

`gemma4:e4b` 는 이 프로젝트의 **RAG 생성 백엔드**입니다
(`docker-compose.yml:31`, 호스트 11434 재사용). 코딩 에이전트로 같은 인스턴스를
점유하면 챗봇 응답이 느려지고, **2.3 과 2.4 의 P95 첫토큰 실측 중에는 측정
자체가 오염됩니다.**

| 상황 | 규칙 |
| --- | --- |
| 벤치마크 실행 중 | 코딩 에이전트로 병행 사용 금지 |
| 평상시 코더로 사용 | 별도 모델·별도 포트로 분리 |

### 6.4 절감분의 일부는 검증에 되돌립니다

2026-08-12 Antigravity 워커는 완료 보고를 냈고 Task 도 `completed` 로 보였으나,
실제로는 테스트 파일이 셸 이스케이프째 기록돼 스위트가 파싱조차 되지 않았고,
파서에는 사용량 버킷이 통째로 사라지는 결함이 있었으며, 입력이 같고 기대만
반대인 테스트 두 건이 공존했습니다.

값싼 모델을 쓰면 비용이 사라지는 것이 아니라 **검증 쪽으로 이동합니다.**

| 역할 | 담당 |
| --- | --- |
| 구현 | GPT / Antigravity / 무료 모델 |
| 병합 전 diff 검토와 접합부 검증 | Claude 또는 GPT 중 상위 |
| 승격·컷오버 판정 | Claude Opus 5 |

**워커 보고를 병합 근거로 쓰지 않습니다.** 코디네이터가 `git diff` 를 직접
봅니다. A5 의 예외 누출 회귀도 워커 보고에는 없었고 병합 전 diff 검토에서
잡혔습니다.

---

## 7. 저장소 밖에 남긴 것

Orca 앱 저장소(`/Users/kwanbum/Documents/korea_IT/orca`)의 Antigravity 사용량
연동은 브랜치 `kwanbum217/antigravity-usage-status` 에 `88e37b6` 으로 **로컬
커밋만** 되어 있습니다. `origin` 이 상류 `stablyai/orca` 라 push 하지
않았습니다. 워크트리는 해제했고 브랜치는 남겼으므로 이 브랜치가 유일본입니다.

검증 상태는 rate-limits·status-bar 696건 통과, `pnpm typecheck` 통과, 변경 영역
oxlint 오류 0건입니다. 저장소 전량 vitest 는 50,669 통과 / 2 실패이며 실패는
`src/relay/agent-exec-handler.test.ts` 로, 이 브랜치가 `src/relay` 를 전혀
변경하지 않았으므로 상위 `main`(`09ec516`)에서 승계된 기존 실패입니다.
UI 실측(Electron Playwright)은 수행하지 않았습니다.
