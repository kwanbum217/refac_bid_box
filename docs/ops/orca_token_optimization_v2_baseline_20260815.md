# Orca 코디네이터 토큰 최적화 v2 구현 전 기준선 감사

> **작성일**: 2026-08-15
> **작업 ID**: `task_11934dd738cf` (T0 기준선 감사와 설계 정본 등록)
> **기준 커밋 / 브랜치**: `021bfa3` / `kwanbum217/orca-v2-t0-baseline`
> **작성 주체**: Antigravity Gemini Flash High (Dispatched Worker)
> **설계 정본**: [`orca_coordinator_token_optimization_v2.md`](orca_coordinator_token_optimization_v2.md)
> **비협상 원칙**: 데이터 무손실(G1), train/serve 특징 단일화, 크로스 플랫폼(G2), 실측 기반 G3

---

## 1. 개요 및 목적

본 문서는 `Orca Coordinator Token Optimization v2` 구현에 착수하기 전, 현재 저장소(`refac_bid_box`)의 에이전트 부트스트랩 체계, 자동 로드 설정, 정합성 검증기, 최신 성능 운영 사실의 기준선(baseline)을 객관적으로 기록하기 위한 감사 보고서입니다.

외부 설계 원본(`/Users/kwanbum/Downloads/orca_coordinator_token_optimization_v2.md`, 1,033줄)은 [`orca_coordinator_token_optimization_v2.md`](orca_coordinator_token_optimization_v2.md)에 100% 동일하게 등록되었습니다. 본 T0 작업에서는 설계서 등록 및 본 감사 문서 작성 외의 코드, 검증기, 설정 파일 수정을 일체 수행하지 않았습니다.

---

## 2. 부트스트랩 및 컨텍스트 주입 구조 현황 (AS-IS)

### 2.1 파일별 자동 주입 및 참조 관계

현재 저장소의 에이전트 자동 주입 설정은 다음과 같이 구성되어 있습니다.

| 설정/파일 경로 | 라인 참조 | 현재 동작 및 주입 내용 |
| --- | --- | --- |
| `AGENTS.md` | `AGENTS.md:7` | `@/Users/kwanbum/orca/workspaces/refac_bid_box/orca-v2-t0-baseline/SKILLS.md` 구문을 통해 `SKILLS.md` 전체를 import하여 주입 |
| `opencode.json` | `opencode.json:3-6` | `"instructions": ["AGENTS.md", "SKILLS.md"]` 배열로 두 파일을 모두 자동 로드 목록에 등록 |
| `SKILLS.md` | `SKILLS.md:3-56` | `MANDATORY STARTUP SEQUENCE`를 통해 모든 에이전트가 `README.md` -> `docs/design/REFACTORING_DESIGN.md` -> 작업별 문서를 순차 정독하도록 강제 |
| `CLAUDE.md` | `CLAUDE.md:1` | `@AGENTS.md` thin pointer 한 줄로 구성되어 `AGENTS.md`를 주입 |
| `.cursor/rules/00-core-guidelines.mdc` | `00-core-guidelines.mdc` | `AGENTS.md` 참조 링크 및 핵심 요약 제공 |
| `.antigravity/rules.md` | `.antigravity/rules.md` | 12,000자 캡 내의 핵심 규칙 요약본 제공 |

### 2.2 전역 규칙과 워커 최적화 규칙 간의 충돌

현재 저장소 문서 체계에는 부트스트랩 규칙 간 충돌이 존재합니다.

1. **전역 규칙 (`SKILLS.md:3-56`)**: 모든 에이전트에게 시작 시 `README.md`, `docs/design/REFACTORING_DESIGN.md`, `AGENTS.md`를 전체 정독하도록 요구합니다.
2. **워커 조율 규칙 (`docs/ops/orca_orchestration_playbook.md:14-16`, `.agents/skills/orca-section-coordination/SKILL.md`)**: 워커에게 Task 사양을 자족적으로 전달하고, 전역 문서(`README.md`, `AGENTS.md`, `SKILLS.md`) 재독을 금지하도록 규정합니다.

이로 인해 작은 컨텍스트 윈도우를 가진 워커 모델이나 분당 토큰 한도가 제한된 프로바이더에서 불필요한 토큰 소비와 프롬프트 지연이 발생하고 있습니다.

---

## 3. 정합성 검증기 (`scripts/validate_agent_rules.py`) 현황

현재 `scripts/validate_agent_rules.py`는 pre-commit 훅과 CI에서 총 6개의 검사를 실행하여 구(舊) 규칙 구조를 엄격하게 강제하고 있습니다.

| 검사 함수 | 검증 대상 | 강제 조건 |
| --- | --- | --- |
| `check_claude_is_pointer()` | `CLAUDE.md` | `@AGENTS.md` import 포함 여부 및 정본 섹션 복사 금지 |
| `check_antigravity_rules()` | `.antigravity/rules.md` | 12,000자 이하 및 7개 필수 키워드(`데이터 무손실`, `Train/Serve`, `금지 행위`, `이모지`, `main`, `재학습`, `스킬 인덱스`) 포함 여부 |
| `check_cursor_references_agents()` | `.cursor/rules/00-core-guidelines.mdc` | `AGENTS.md` 문자열 포함 여부 |
| `check_opencode_json()` | `opencode.json` | `instructions` 배열 내 `AGENTS.md` 및 `SKILLS.md` 동시 포함 여부 |
| `check_skills_mirror()` | `.claude/skills`, `.opencode/skills` | `.agents/skills/` 디렉터리와의 1:1 내용 완전 일치 여부 |
| `check_agents_imports_skills()` | `AGENTS.md` | `@SKILLS.md` 구문 포함 여부 |

### 3.1 v2 전환 시 검증기 영향도

v2 설계안에 따라 `opencode.json`의 instructions를 `AGENTS.md` 1개로 축소하고 `AGENTS.md` 내 `@SKILLS.md` 직결 구조를 선택적 참조로 개편할 경우, 검사 4(`check_opencode_json`) 및 검사 6(`check_agents_imports_skills`)의 검증 로직을 반드시 설정 변경과 함께 갱신해야 검증 실패를 방지할 수 있습니다.

---

## 4. 성능 지표 및 운영 사실 대조 (Stale vs Current)

### 4.1 예측 API 레이턴시 지표 대조

| 지표 / 측정 항목 | 과거 문서 기록 (Stale) | 최신 운영 정본 기록 (Current) | 출처 및 비고 |
| --- | ---: | ---: | --- |
| warm c10 P95 | 199.18ms (목표 미달 표기) | **56.45ms (목표 통과)** | `docs/handoff/2026-08-14_late_session_handoff.md:51-57` |
| warm c10 P50 | - | **42.45ms** | `PREDICTION_GC_MODE=freeze` 채택 결과 |
| warm c10 P99 | - | **62.08ms** | 최악 3회 측정 중 최악값 기준 |
| warm c10 Max | - | **73.01ms** | 100ms 초과 0건 (1,800회 측정) |
| 회귀 판정선 (P95 +10%) | - | **62.10ms** | `docs/ops/latency_gate_protocol.md` 기준 |

> **주의**: `README.md`에 남아 있는 199.18ms 수치는 구형 측정치(Stale)이며, 2026-08-14 후반 세션에서 확립된 정본 기준선은 `PREDICTION_GC_MODE=freeze` 기반의 56.45ms입니다.

### 4.2 SSE 스트리밍 레이턴시 지표 대조

`docs/handoff/2026-08-14_late_session_handoff.md:210-230`에서 레이턴시 게이트 규약(회차당 60표본, 3회차, warmup 제외, 주변부하 기록)을 만족하여 확립된 정본 기준선입니다.

| 지표 | 정본 대표값 (3회 최악) | 목표 기준 | 판정 | 회귀 판정선 (+10%) |
| --- | ---: | ---: | --- | ---: |
| 첫 토큰 P95 (c1) | **1522.41ms** | 3,000ms 이하 | **통과** | 1674.65ms |
| 전체 스트리밍 P95 (c1) | **8049.61ms** | 20,000ms 이하 | **통과** | 8854.57ms |

### 4.3 에이전트 CLI 기동 및 워커 운영 사실

`docs/ops/agent_worker_launch_reference.md` 및 `docs/handoff/2026-08-14_late_session_handoff.md:281-294`에 기록된 실측 운영 사실입니다.

1. **Antigravity CLI 기동**: `agy`에 대해 `dispatch --inject`를 수행하는 방식은 신뢰 확인 대화창에 키 입력이 소실되어 3/3 실패했습니다. 프로세스 실행 시점에 프롬프트를 인자로 전달하는 `agy --model <id> -i "<프롬프트>"` 방식이 신뢰성 높은 권장 기동 경로입니다.
2. **Cerebras / Gemma-4 31B 풀**: `opencode.json`이 `AGENTS.md`와 `SKILLS.md`를 모두 자동 주입하여 매 세션 약 16KB가 선행 로드되면서 분당 토큰 한도(TPM/RPM) 초과가 발생했습니다. v2 경량화(Task Capsule 중심 전달)의 직접적 필요 근거입니다.
3. **워커 보고 검증 원칙**: 워커의 자유형 요약 보고에는 착오가 발생할 수 있으므로, 코디네이터는 요약 텍스트만으로 판단하지 않고 실제 생성된 파일 artifact 및 deterministic 검증 결과를 직접 대조하여 병합 여부를 결정해야 합니다.

---

## 5. T0 작업 요약 및 향후 단계 가이드

1. **완료 내역**:
   - `docs/ops/orca_coordinator_token_optimization_v2.md` 정본 등록 완료 (1,033줄 원본 완전 일치 검증).
   - `docs/ops/orca_token_optimization_v2_baseline_20260815.md` 작성 완료 (부트스트랩 현황, 검증기 6개 규칙, Stale vs Current 데이터 기록).
2. **검증 결과**:
   - `cmp -s /Users/kwanbum/Downloads/orca_coordinator_token_optimization_v2.md docs/ops/orca_coordinator_token_optimization_v2.md` (일치 확인).
   - `python3 scripts/validate_agent_rules.py --quiet` (6/6 PASS).
   - `git diff --check` (공백 및 포맷 이상 없음).
3. **변경 격리 준수**:
   - 허용 파일 외 수정 없음 (`git status` 상 2개 파일 생성).
   - 저장소 소스 코드, DB, 도커, 의존성 무수정.
