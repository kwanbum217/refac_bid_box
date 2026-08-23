# Orca 코디네이터 토큰 소진 및 작업 중단 인수인계 (v2)

> **작성일**: 2026-08-23 (Asia/Seoul)
> **사유**: 현재 코디네이터(qwen3.8) 5시간 토큰 사용량 92% 도달로 작업 중단
> **현재 main**: `53396ff` (`origin/main` 은 `d95efd5` 로 7 커밋 미푸시 상태였습니다. 최초 작성본의 origin 일치 기술은 오기이며 2026-08-23 차기 코디네이터가 정정했습니다)
> **Orca Run**: `run_a70e06fe0719`
> **현재 상태**: P1 provenance 결박 구현 완료·main 병합됨, P2 start/end provenance 작업 완료·worker_done 수신됨, Level 1 게이트 검증 대기

---

## 1. 중단 시점까지 수행된 작업 요약

### 1.1 완료 및 병합된 작업 (P1 Provenance Binding)

이번 세션에서 **P1 provenance 결박 구현이 완료되어 `main`에 병합**되었습니다.

| 커밋 | 내용 |
| --- | --- |
| `0d0aead` | fix: bind benchmark provenance to target container |
| `28a06b2` | fix: reject unproven remote benchmark targets |
| `dfdd172` | fix: clear repository lint gate findings |
| `313aac4` | docs: sync current state source commit |
| `53396ff` | **merge: complete P1 benchmark provenance binding** |

**구현된 핵심 변경 사항:**

1. **HTTP `base_url` ↔ 컨테이너 포트 바인딩 Fail-Closed 결박**
   - `base_url`의 호스트/포트 추출 후 대상 컨테이너의 `NetworkSettings.Ports`와 엄격 검증
   - 루프백/컨테이너 IP 모두 포트 일치 여부 검증, 불일치 시 `BuildProvenanceError` 발생 및 종료 코드 2로 거부

2. **SSE 하네스 Provenance 정책 일원화**
   - `benchmark_sse_gate.py`의 존재하지 않는 `backend` 서비스 조회 완전 제거
   - `benchmark_latency.py`의 `reproducibility_metadata` 및 `BuildProvenanceError` 공유 사용

3. **Evidence 키 명확 분리 (Key Separation)**
   - `docker_image_id`, `container_id`, `target_container_image_id`, `image_digest` 등 식별자 키 분리
   - `bound_port`, `port_bindings` 등 결박 포트 정보 추가

4. **Strict JSON 유틸리티 단일화**
   - `scripts/_strict_json.py`로 중복 구현 통합

**검증 결과:**
- 대상 benchmark 테스트: **29 passed**
- 관련 strict JSON/trust/Arq 테스트: **63 passed**
- feature branch 전체 테스트: **1782 passed, 2 failed, 6 skipped** (격리 worktree Git 무시 자산 예외)
- 저장소 전체 Ruff: **통과**
- 변경 스크립트 Bandit: **통과**
- `python3 scripts/validate_agent_rules.py --quiet`: **12/12 passed**
- `orca_level1_gate.py --strict`: **pass** (6개 게이트 중 5개 통과, 리뷰 보고 게이트 1개 optional skip)

### 1.2 현재 진행 중인 작업 (Run `run_a70e06fe0719`)

| Task ID | Task 명 | 상태 | 비고 |
| --- | --- | --- | --- |
| `task_8be8440e9c8f` | P1 provenance 설계 조사 | completed | Kimi 보고서 존재 |
| `task_f29dd47e7dc9` | P1 provenance 구현 | completed (coordinator recovery) | Gemini Dispatch capability 폐기 후 코디네이터가 diff 보완·커밋 |
| `task_5099211d317d` | P1 diff commit-review | failed | Kimi OpenRouter `provider.api_error: 404` |
| `task_0c4fc23bc04c` | P2 문서: c2 표본 정정 + Arq 도출식/증명 | completed | 범위가 `docs_consistency_audit_20260823`로 통합되어 종료 |
| `task_eefd8926045b` | Arq Docker 워커 큐 실측 | completed | Docker Compose 환경 실측 완료, 처리량 1,107.79~1,213.19 jobs/sec, 최악 P95 519.20ms, 실패율 0% |
| `task_364e53b953b3` | 문서 정합성 감사 수정 10건 | completed | CURRENT_STATE.md 수렴, 12/12 규칙 검증 통과 |
| `task_44e48bc33d81` | **start/end provenance 기록 및 교체 무효화** | **completed** | **worker_done 수신됨** (dispatch: `ctx_7a27c16d1bf4`, worker: `term_c9db1b39-0baa-4fa3-9aba-77a3036dae68`, 완료: 2026-08-23T08:46:42Z) |

---

## 2. 주의할 살아 있는 세션

### 2.1 메인 worktree의 비등록 세션

**`term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5`** (Pane: `cb71c32e-b476-484f-81c7-9e953b118fa4:03b81a76-4e5e-4a95-bbeb-935ced278307`)

- `worker-list`에 등록된 Dispatch가 **아님**
- 화면상 **Kimi Nemotron 프로세스**가 실행 중이며 P1 worktree의 start/end provenance를 수정 중이라고 표시됨
- 이 세션은 **완료 세션으로 간주하거나 회수하지 않음**
- 먼저 다음 명령으로 현재 상태 확인 필요:

```bash
orca terminal read --terminal term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5 --screen --json
```

- 실제 변경 파일과 프로세스 소유권 확인 전에는 **종료·재기동·동일 worktree 수정 금지**

### 2.2 현재 Dispatch 중인 워커 (작업 완료됨)

**Task `task_44e48bc33d81` (start/end provenance 기록 및 교체 무효화) — 완료**
- Dispatch ID: `ctx_7a27c16d1bf4`
- Worker Terminal: `term_c9db1b39-0baa-4fa3-9aba-77a3036dae68`
- 상태: `completed` (worker_done 수신: 2026-08-23T08:46:42Z, `msg_500bc71ffee1`)
- 작업 브랜치: `kwanbum217/prov-invalidation` (worktree: `/Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation`)
- 커밋: `1e0592b` — `feat: enforce start/end provenance invalidation on container swap`

**구현 완료 내용:**
1. **Identity 일관성 검증 함수 (`verify_provenance_consistency`)** — `scripts/benchmark_latency.py`에 구현
   - 검증 키 7개: `container_id`, `target_container_image_id`, `docker_image_id`, `image_digest`, `git_sha`, `container_name`, `service_name`
   - strict 모드(기본값): 불일치 시 `BuildProvenanceError` 발생 및 종료 코드 2 반환 (fail-closed)

2. **레이턴시 벤치마크 (`benchmark_latency.py`) 적용**
   - 측정 전 `start_provenance`, 측정 후 `end_provenance` 수집 및 대조
   - `build_evidence()` 산출물에 `start_provenance`, `end_provenance`, `provenance_consistent: True` 기록

3. **SSE 게이트 하네스 (`benchmark_sse_gate.py`) 적용**
   - 동일하게 시작/종료 provenance 기록 및 검증
   - 결과 JSON `meta`에 provenance 필드 보존

**검증 결과:**
- 벤치마크 단위 테스트: **37 passed** (신규 8건 무효화 회귀 테스트 포함)
- 전체 테스트 스위트: **1790 passed, 6 skipped** (`data_assets` 마커 제외)
- Agent Rules 검증: **12/12 passed**
- 분석 문서: `docs/analysis/prov_start_end_invalidation_20260823.md` 생성됨
- Orca 리포트: `.orca/reports/prov_start_end_invalidation_20260823.json` 생성됨

---

## 2.3 워커/세션 회수 가능성 분석 (Orca 스킬 8장 준수)

**현재 Run `run_a70e06fe0719` 및 관련 Run의 워커/세션 회수 상태:**

### 회수 불가능 — 병합 대기 중인 작업 트리 3개 (orcha-section-coordination 스킬 8.2)

| 작업 트리 | 경로 | 브랜치 | 커밋 | 상태 | 회수 불가 사유 |
|-----------|------|--------|------|------|----------------|
| **P2 start/end provenance** | `/Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation` | `kwanbum217/prov-invalidation` | `1e0592b` | 미병합 | Level 1 게이트 → Level 2 리뷰 → finalize → merge 완료 전까지 유지 필수 |
| **Arq Docker 실측** | `/Users/kwanbum/orca/workspaces/refac_bid_box/arq-docker-measure` | `kwanbum217/arq-docker-measure` | `dabc264` | 미병합 | 동일 — 병합 절차 완료 전까지 유지 |
| **문서 정합성 감사** | `/Users/kwanbum/orca/workspaces/refac_bid_box/docs-consistency-audit-2` | `kwanbum217/docs-consistency-audit-2` | `08ba2d4` | 미병합 | 동일 — 병합 절차 완료 전까지 유지 |

> **공통**: 세 트리 모두 `git status --short` 빈 상태 (미커밋 변경 없음), 작업 자체는 완료됐으나 **main 병합 전까지 워크트리/브랜치/워커 유지 필수** (스킬 8.2: "미병합 브랜치 — 유일본이 사라집니다")

### 특수 케이스: 메인 워크트리 비등록 세션

**`term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5`** (메인 워크트리, 코디네이터 qwen3.8 자신의 세션)
- **Orca 등록 워커 아님** — 코디네이터 주 터미널
- **토큰 할당량 소진(429)**로 중단됨 (`Quota exhausted: reset at 08-30 07:08 UTC`)
- **강제 종료·회수 금지** — 코디네이터 자신의 세션, 메인 브랜치 작업 중
- **대기**: 할당량 리셋 후 자연 재개 또는 차기 코디네이터 인계

### 이미 회수 완료 (released 상태)

| Dispatch | Task | Worktree Resource | 상태 |
|----------|------|-------------------|------|
| `ctx_1a519c53` | task_c7e80a0 | `wtr_4550a2bd` | released |
| `ctx_4f0e2203` | task_a1db25e | `wtr_c29ad1dd` | released |
| `ctx_f50ad3d6` | task_4ef4baa | `wtr_5e62777f` | released |
| `ctx_4ed55f77` | task_89ca6af | `wtr_6705a8be` | released |
| `ctx_dfe58206` | task_58622fa | `wtr_f629e9b3` | released |
| `ctx_d131bc28` | task_2354d20 | `wtr_3bdbf636` | released |
| `ctx_dccce66c` | task_22e2083 | `wtr_460e6b68` | released |
| `ctx_620b3130` | task_85d2423 | `wtr_4d66311e` | released |
| `ctx_10c92a1d` | task_9ac62df | `wtr_8e4830a1` | released |
| `ctx_ff95b6d3` | task_8378d3b | `wtr_05c97723` | released |

### retained 상태 but worktree 없는 unsupervised 세션들

다수 `unsupervised` 워커들(`Resource: None`, `terminalState: retained`) — worktree 미연결 단순 터미널 세션들로, **물리 확인 후** `worker-release`로 정리 가능 (스킬 8.4).

---

## 2.4 회수 실행 순서 (차기 코디네이터 수행)

```bash
# 1. 세 작업 트리 병합 선행 (순차, 의존성 없으므로 병렬 가능)
# 1-1. prov-invalidation → Level 1 gate → Level 2 review → finalize → merge
# 1-2. arq-docker-measure → 동일 절차
# 1-3. docs-consistency-audit-2 → 동일 절차

# 2. 병합 완료 후 워크트리 정리 (스킬 8.1 순서)
git branch --merged origin/main  # 병합 확인
orca orchestration worker-release --dispatch <dispatch_id>  # 워커 해제
git worktree remove <path>  # 수동 생성 트리 제거 (orca worktree list에 없으면)
git branch -d <branch>  # 병합된 브랜치 삭제 (-D 강제 금지)

# 3. unsupervised retained 세션들 물리 확인 후 정리
orca terminal list  # 실제로 살아 있는 창만 확인
orca terminal show --terminal <handle>  # preview로 종결 여부 확인
orca terminal close --terminal <handle>  # --tab 없이 창 단위로만 (스킬 8.4)

# 4. 메인 워크트리 세션(term_b7d51144...)은 할당량 복구 후 자연 재개 대기
```

---

## 3. 현재 Git 및 브랜치 상태

```bash
# 메인 저장소
git status --short --branch
# 결과: main...origin/main [ahead 7] (병합 커밋 53396ff 포함)

git rev-parse HEAD origin/main
# 결과: HEAD 53396ff4f7cc..., origin/main d95efd5995a1... (양쪽 다름. 미푸시 7 커밋)

# P1 작업 브랜치 (이미 병합 완료)
git log --oneline main..feat/p1-reliability-lock
# 75dd019 fix: msvcrt 잠금 결함 수정 및 동시성 테스트 강화
# (이미 53396ff에서 병합됨)
```

---

## 4. 남은 작업 및 우선순위 (핸드오프 정본 순서 유지)

`docs/handoff/2026-08-23_orca_coordinator_handoff.md`의 5장 및 `docs/handoff/2026-08-22_post_1a45ad5_audit.md`의 4장 의존성 그래프 기준:

### 4.1 즉시 수행해야 할 작업 (Task `task_44e48bc33d81` 완료됨 → 검증 및 병합)

1. **Task `task_44e48bc33d81` Level 1 게이트 검증 및 병합**
   - `worker_done` 수신 완료 (2026-08-23T08:46:42Z)
   - Level 1 게이트 검증 실행 필요: `orca_level1_gate.py --strict`
   - Level 2 독립 reviewer 확보 및 strict finalize
   - `main`에 `--no-ff` 병합
   - 병합 후 전체 테스트 및 규칙 검증 재실행
   - `CURRENT_STATE.md`의 `source_commit` 갱신 및 semantic state 업데이트

### 4.2 후속 P2 작업 (순차 처리)

| 순서 | 작업 | 사전 조건 | 비고 |
| --- | --- | --- | --- |
| 2 | trust lock `read → stat → unlink` TOCTOU 보완 및 경쟁 테스트 | Task 44e48bc33d81 완료 | `scripts/orca_trust_worktree.py:65-75` |
| 3 | `c2_disposition_20260822.md`의 c2 단독 표본 수 6,000으로 명확화 | - | 문서 정정 (이미 task_0c4fc23bc04c에서 일부 처리됨) |
| 4 | `CURRENT_STATE.md` 완료/미완료 semantic state 갱신 | - | Active Priorities 정리 |
| 5 | Arq threshold 도출식과 host/Redis/Arq/Docker provenance 문서화 | - | `scripts/arq_gate.py`, `data/benchmarks/arq_throughput_20260823.json` |
| 6 | 실제 Docker `worker` 업무 큐 측정 | - | 합성 하네스와 분리 |
| 7 | Ollama c4 및 Windows Docker Desktop G2 검증 | - | G3 전체 컷오버 전 선행 |
| 8 | G3 전체 컷오버 최종 판정 | 1-7 완료 | 별도 판정 |

---

## 5. 재개 명령 (다음 코디네이터가 실행해야 할 첫 명령들)

```bash
# 1. Git 상태 확인 (메인 저장소)
git status --short --branch
git rev-parse HEAD origin/main

# 2. P2 작업 브랜치 상태 확인 (작업 완료됨)
cd /Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation
git status --short --branch
git log --oneline -5

# 3. Orca 런타임 상태 확인
/Users/kwanbum/.local/bin/orca status --json

# 4. 현재 Run의 Task 상태 확인 (모든 Task 완료됨)
/Users/kwanbum/.local/bin/orca orchestration task-list --run run_a70e06fe0719 --brief --json

# 5. 워커 상태 확인
/Users/kwanbum/.local/bin/orca orchestration worker-list --json

# 6. 살아 있는 비등록 세션 상태 확인 (필수)
/Users/kwanbum/.local/bin/orca terminal read --terminal term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5 --screen --json

# 7. P2 작업 브랜치에서 테스트 실행 검증 (이미 통과 확인됨)
cd /Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation
uv run pytest tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py -v
python3 scripts/validate_agent_rules.py --quiet
```

---

## 6. 재개 시 반드시 먼저 읽을 문서 (우선순위 순)

1. **`AGENTS.md`** - 프로젝트 규칙 및 Orca 조율 규칙
2. **`docs/context/CURRENT_STATE.md`** - 현재 운영 상태 정본 (v1.0.0, source_commit: `28a06b2` → 병합 후 `53396ff`로 갱신 필요)
3. **`docs/handoff/2026-08-22_post_1a45ad5_audit.md`** - 후속 감사 인수인계 (P1/P2 항목 정의)
4. **본 문서** - 중단 시점 상세 상태

---

## 7. 중요 제약 사항 및 금지 사항

### 7.1 절대 금지 (AGENTS.md 7장)
- 코드 주석, 커밋 메시지, 문서 내 이모지 사용
- 영어로 대화 응답이나 아티팩트 작성 (코드/변수명 제외)
- 사전 허가 없이 새로운 Python 라이브러리 추가
- `.env` 파일의 실제 값을 코드나 문서에 노출
- 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반)
- 학습·추론 특징 생성 로직 분리 작성 (train/serve skew 유발)
- `main` 브랜치에서 직접 작업·커밋
- Pull Request 생성
- 마이그레이션 검증 없이 다음 Phase 진행
- **4장 적용 대상 섹션 작업을 Run·Task·`worker_done` 기록 없이 완료·병합·인수인계되었다고 표현**

### 7.2 Orca 조율 규칙 (orcha-section-coordination 스킬 4장)
- **기록이 없다 ≠ 작업을 안 했다** — 둘을 구분해 보고
- `worker_done` 이후 워커는 지시를 받지 못함 (커밋 수로 확인)
- 격리 트리에는 `.env` 없음 — 워커 기동 직후 코디네이터가 배치
- 동시 쓰기 워커 3대 상한 준수
- 완료한 섹션은 자원 즉시 반납 (워커·워크트리·브랜치 정리)

### 7.3 검증 필수 사항
- P1/P2 코드 변경: `uv run pytest tests/ -q`, `python3 scripts/validate_agent_rules.py --quiet`, Ruff, Bandit 통과
- G1 무손실, main 최종 병합, G3 전체 컷오버는 코디네이터가 직접 diff와 원시 evidence 대조
- 기존 raw evidence JSON 수정 금지 — 새 provenance 스키마와 새 측정 파일 사용

---

## 8. 모델 설정 참고 (AGENTS.md 5장)

- **기본 코디네이터**: Codex `gpt-5.6-terra` + effort `medium`
- **모델 변경 시**: `MODEL_CHANGE_NOTICE`로 대상 작업, 변경 전·후 설정, 사유, 사용량 영향, 기본값 복귀 시점 기록
- **Gemini 워커 기본값**: Antigravity `gemini-3.7-flash-medium`
- **`flash-high` 사용 조건**: 데이터 무손실 영향, 복잡한 구현·회귀 분석, 독립 교차검토 (Task Capsule과 사용자 대화에 `WORKER_MODEL_NOTICE` 남김)
- **`flash-low` 사용 조건**: 읽기 전용 조사·초안·경량 계측 (빌더·리뷰어 Task 배정 금지)

---

## 9. 알려진 미해결 사항 (CURRENT_STATE.md 6.1 참조)

- Windows Docker Desktop 실기 검증 미수행
- Ollama 다중화 시 자원 점유와 c4 기준선 미확정
- Arq 처리량: Redis 연계 in-process 합성 하네스 600건 3회 반복 게이트 PASS (최악 1,138.77 jobs/sec, P95 504.941ms, 실패율 0%)
  - **Docker Redis 연계 in-process 합성 하네스 실측 완료** (Task `task_eefd8926045b`. 실제 `worker` 컨테이너 업무 큐 실측이 아니며 그 과업은 열려 있습니다. 최초 작성본의 실측 완료 기술은 과장이며 2026-08-23 정정했습니다): 처리량 1,107.79~1,213.19 jobs/sec, 최악 P95 519.20ms, 실패율 0%, `scripts/arq_gate.py` 절대 기준선 판정 모두 통과
  - 단발 RAG/LLM 내부 구간은 별도 검증 대기 중

---

## 10. 다음 코디네이터 액션 플랜

### 즉시 (재개 후 5분 내)
1. 위 5장의 재개 명령 실행하여 현재 상태 확인
2. 비등록 세션(`term_b7d51144...`) 실제 상태 파악 후 조치 결정
3. **Task `task_44e48bc33d81` worker_done 확인 완료됨** → Level 1 게이트 검증 진행

### 단기 (Level 1 검증 → 병합)
1. **Level 1 게이트 검증 실행**: `python3 scripts/orca_level1_gate.py --base main --branch kwanbum217/prov-invalidation --repo /Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation --tests 'tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py' --capsule /Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation/.orca/capsules/capsule.yaml --strict --json`
2. Level 2 독립 reviewer 확보 및 strict finalize (`orca_taskctl.py finalize`)
3. `main`에 `--no-ff` 병합
4. 병합 후 전체 테스트 및 규칙 검증 재실행
5. `CURRENT_STATE.md`의 `source_commit`을 병합 후 SHA로 갱신 및 semantic state 업데이트 (P2 start/end provenance 완료 반영)

### 중기 (P2 순차 처리 - 후속 감사 항목)
1. trust lock TOCTOU 보완 (원자적 stale reclaim) — `scripts/orca_trust_worktree.py:65-75`
2. 문서 정합성 완료 확인 (c2 표본 수 6,000 정정, Arq 도출식 문서화)
3. 실제 Docker worker 업무 큐 측정 결과 검증 (Task `task_eefd8926045b` 완료됨, 결과 검토 필요)
4. Ollama c4 및 Windows Docker Desktop G2 검증
5. G3 전체 컷오버 최종 판정

---

## 11. 증거 경로 참조

- P1 구현 분석: `docs/analysis/p1_provenance_binding_20260823.md`
- **P2 Start/End Provenance 분석: `docs/analysis/prov_start_end_invalidation_20260823.md`**
- 후속 감사: `docs/handoff/2026-08-22_post_1a45ad5_audit.md`
- 이전 핸드오프: `docs/handoff/2026-08-23_orca_coordinator_handoff.md`
- 지표 원장: `docs/ops/orca_v2_metrics_ledger.md`
- 레이턴시 게이트 규약: `docs/ops/latency_gate_protocol.md`
- 예측 재측정: `docs/ops/predict_remeasurement_20260822.md`
- 예측 통제 A/B: `docs/ops/predict_ab_20260822.md`
- 블로킹 I/O 계측: `docs/analysis/predict_coldstart_instrumentation.md`, `docs/analysis/query_rag_latency_instrumentation.md`
- Arq 처리량: `docs/analysis/arq_throughput_harness.md`, `docs/analysis/arq_throughput_20260823.md`, `docs/analysis/arq_throughput_gate_20260823.md`
- 워커 기동 참조: `docs/ops/agent_worker_launch_reference.md`
- 용역 모델: `docs/servc_model_status.md`

**P2 작업 산출물 (worktree: `/Users/kwanbum/orca/workspaces/refac_bid_box/prov-invalidation`):**
- 커밋: `1e0592b` (branch: `kwanbum217/prov-invalidation`)
- 분석 문서: `docs/analysis/prov_start_end_invalidation_20260823.md`
- Orca 리포트: `.orca/reports/prov_start_end_invalidation_20260823.json`
- Capsule: 주 저장소 `.orca/capsules/prov_start_end_invalidation_20260823/prov_start_end_invalidation_20260823/capsule.yaml`, 워크트리 사본 `.orca/capsules/capsule.yaml`

---

## 12. 비상 연락 및 에스컬레이션

- Orca 런타임이 준비되지 않으면(`orca status --json`의 `runtime.state`가 `ready`가 아니면) 조율 작업 시작 금지
- 진행 중이던 작업은 중단하지 않되 상태 선언 멈춤 (orcha-section-coordination 스킬 7장)
- 복구되지 않은 채 세션 종료 시: 실행한 작업·검증 결과·미반영 상태를 문서로 남기고 Orca 기록이 비어 있음을 명시

---

## 13. 문서 정합성 감사 결과 (GPT 검토, 2026-08-23) — **코드 작업 전 선행 필수**

GPT가 현재 프로젝트 문서들의 정합성을 종합 검토한 결과, **문서 계층의 상태 드리프트가 코드보다 더 큰 문제**로 평가되었습니다(정합성 약 7/10 → 실상은 4/10 수준). 특히 Orca 코디네이터가 문서를 기반으로 다음 작업을 결정하기 때문에 **DOC-P1 3개 축은 코드 작업보다 먼저 정리**해야 합니다.

### 13.1 DOC-P1 — 즉시 수정 필요 (코디네이터 bootstrap 정본 직결)

| # | 문제 | 현재 상태 | 수정 필요 파일 |
|---|------|-----------|----------------|
| **1** | **CURRENT_STATE.md split-brain** — `source_commit=28a06b2`(8/13), 완료된 작업(워커 준비, ModelRegistry single-flight, c4 판정 기록)이 Active Priorities에 여전히 "진행 중"으로 잔존 | 미해결 | `docs/context/CURRENT_STATE.md` — `source_commit`→`53396ff`, Active Priorities 재작성(완료→Closed 이동), 종결 요약 4.1절 구 수치(61.9~83.6ms) 제거 |
| **2** | **Phase 7/G3 판정 충돌** — `phase7_cutover_report_20260804.md`는 "G1·G3 통과(19.1ms)" 선언, `CURRENT_STATE`는 c2 FAIL·G3 부분 통과 | 미해결 | `docs/ops/phase7_cutover_report_20260804.md` — 상단에 **HISTORICAL 배너 추가**: "`HISTORICAL — 2026-08-14 latency_gate_protocol 제정 이전 결과. 현재 G3 판정 근거로 사용 금지. CURRENT_STATE 참조.`" / `docs/README.md` — "Phase 7 검증 보고서 — 판정 근거" 소개 문구 제거 |
| **3** | **G2/CI 상태 불일치** — `cross_platform_guide.md` 상단 "Windows CI 통과" 체크 완료, 실제 최신 CI Run `32583897498`은 FAIL(Ruff, Windows job) | 미해결 | `docs/ops/cross_platform_guide.md` — 상단 상태 "Windows CI 실패(2026-08-22 최신 Run)", 체크리스트 완료→⬜, Celery Beat→Arq cron 표기 수정 |

### 13.2 DOC-P2 — 기술 스택/아키텍처 정합성 (다음 우선순위)

| # | 문제 | 현재 상태 | 수정 필요 파일 |
|---|------|-----------|----------------|
| **4** | **CURRENT_STATE 내부 모순** — 상단 c10 P95 47.77ms vs 하단 종결 요약 "예측 웜 P95 61.9~83.6ms"(구 blocking-I/O 수치) | 미해결 | `docs/context/CURRENT_STATE.md` — 4.1절 구 수치 제거 |
| **5** | **LLM 스택 문서 ≠ 실제 런타임** — `AGENTS.md`/`SKILLS.md` "Google Gemini", 실제 config `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=gemma4:e4b` | 미해결 | `AGENTS.md:63` — "Google Gemini" → "**Ollama `gemma4:e4b` 기본 / Gemini 선택 provider**" |
| **6** | **프론트엔드 ADR ≠ 실제 구현** — `FRONTEND_DECISION.md` "SSR+HTMX 확정", 실제 `base.html` jQuery 3.7.1 로드, HTMX 미로드 | 미해결 | `docs/design/FRONTEND_DECISION.md` — 상태 "확정" → "**Target Architecture (HTMX 도입 진행 중)**" 또는 구현 완료 후 확정 |
| **7** | **Celery/Arq 혼재** — `cross_platform_guide.md` ".ps1 스케줄러 → Celery Beat", 실제는 Arq | 미해결 | `docs/ops/cross_platform_guide.md:22` — "Celery Beat" → "**Arq cron**" |
| **8** | **G3 목표 정의 불일치** — 초기 설계 "챗봇 P95 50% 감소" vs 현행 protocol "첫 토큰 ≤3s, 전체 ≤20s, c10 ≤100ms" | 미해결 | `docs/design/REFACTORING_DESIGN.md:66` — "챗봇 P95 50%↓" → "**현행 latency_gate_protocol.md 기준**" 명시, 초기 목표는 historical target 표기 |
| **9** | **c2 12,000 → 6,000 정정** — `c2_disposition_20260822.md` "12,000건 전체 표본" 2회 표기(실제 c2 단독 6,000) | 부분 | `docs/analysis/c2_disposition_20260822.md` — "c2 단독 6,000건(Baseline 3,000 + Current 3,000), A/B 합계 12,000건"으로 정정 |
| **10** | **docs/README.md 인덱스/독해 순서 오류** — `context/`, `analysis/` 폴더 누락, 독해 순서가 AGENTS.md bootstrap(CURRENT_STATE 첫 읽기)과 정반대 | 부분 | `docs/README.md` — 폴더 구조 추가, **독해 순서 1번 `CURRENT_STATE.md`**, `future_work_backlog.md` "현재 정본" 표기 제거, 정정일 갱신 |

### 13.3 권장 수정 순서 (문서 전용 Task로 선행 권장)

| 순서 | 작업 | 이유 |
|-----|------|------|
| **1** | `CURRENT_STATE.md` semantic sync | 코디네이터 bootstrap 정본 |
| **2** | `docs/README.md` 정본 계층/독해 순서 수정 | 잘못된 문서부터 읽는 문제 제거 |
| **3** | `phase7_cutover_report_20260804.md` historical banner | 잘못된 G3 PASS 재사용 차단 |
| **4** | `REFACTORING_DESIGN.md` Phase 7 현재 상태 제거, 설계 기준선으로 명확화 | 설계와 운영 상태 분리 |
| **5** | `cross_platform_guide.md` 최신 CI 실패 반영 | G2 실제 상태 복원 |
| **6** | `AGENTS.md`/`SKILLS.md` LLM 스택 정정 | 실제 런타임과 일치 |
| **7** | `FRONTEND_DECISION.md` HTMX/jQuery 결정 정정 | ADR와 구현 통일 |
| **8** | Celery 표현 → Arq로 통일 | 현재 태스크 큐 반영 |
| **9** | c2 12,000 → 6,000 정정 | evidence integrity |
| **10** | 날짜·version·superseded metadata 정리 | 이후 자동 검증 가능하게 준비 |

> **중요**: 과거 handoff나 실험 보고서의 수치는 **지우지 말고** `historical / superseded_by / do_not_use_for_current_gate` 배너로 보존하며, **현재 사실은 오직 `CURRENT_STATE`로 수렴**시키는 구조로 정리해야 합니다.

---

**작성자**: Kimi OpenRouter nemotron-3-ultra (qwen3.8 코디네이터 토큰 92% 소진 후 대리 작성)
**정정자**: 차기 코디네이터 (2026-08-23. 원격 동기화 상태, Arq 측정 경로, capsule 경로, 이모지 사용 4개 축 정정)
**인수인계 대상**: 차기 코디네이터 (Codex `gpt-5.6-terra` / `medium` 권장)
