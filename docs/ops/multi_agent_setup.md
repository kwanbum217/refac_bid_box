# 다중 에이전트 셋업 가이드

> **작성일**: 2026-07-31
> **수정일**: 2026-08-14
> **버전**: v1.1
> **목적**: opencode, Cursor, Codex, Claude Code, Antigravity 등 서로 다른 AI 코딩 에이전트를 돌아가며 사용해도, 세션 시작 시 동일한 프로젝트 규칙이 자동으로 로드되고 Orca로 섹션 협업을 조율하도록 하는 아키텍처를 설명합니다.

---

## 1. 핵심 원칙: 단일 진실 원천 (Single Source of Truth)

본 프로젝트는 **규칙을 한 곳(`AGENTS.md`)에서만 편집**하고, 각 에이전트가 요구하는 파일명은 `AGENTS.md`를 가리키는 얇은 진입점(thin pointer / 간접 참조)으로만 둡니다. 진입점 자체에 규칙 내용을 복사하지 않습니다.

```text
                 AGENTS.md  (정본, 유일한 편집 대상, 단일 자동 로드)
                      |
    +--------+--------+--------+--------+
    |        |        |        |        |
  Codex   opencode Antigravity Claude  Cursor
  (직접)  (직접)    (직접)    Code     .mdc
                              thin     간접참조
                              pointer
```

---

## 2. 에이전트별 자동 로드 매핑

| 에이전트 | 자동 로드 파일 | 진입점 방식 | 근거 |
| :--- | :--- | :--- | :--- |
| **Codex CLI** | `AGENTS.md` | 정본 직접 | [OpenAI 공식](https://learn.chatgpt.com/docs/agent-configuration/agents-md) — 작업 전 AGENTS.md를 항상 읽음 |
| **opencode CLI** | `AGENTS.md` | instructions 단일 지정 | [OpenCode config](https://opencode.ai/docs/config/) — `instructions: ["AGENTS.md"]` |
| **Antigravity CLI** | `AGENTS.md` | 정본 직접 | [Google 공식 best practices](https://antigravity.google/docs/cli/best-practices) — workspace root의 AGENTS.md 권장 |
| **Claude Code CLI** | `CLAUDE.md` | thin pointer (`@AGENTS.md`) | Claude Code는 CLAUDE.md를 항상 읽음; import로 AGENTS.md 주입 |
| **Cursor CLI** | `.cursor/rules/*.mdc` | 간접 참조 | [Cursor Rules](https://cursor.com/docs/rules) — `00-core-guidelines.mdc`가 AGENTS.md 참조 |

> 참고: `AGENTS.md`는 60,000개 이상의 오픈소스 프로젝트가 채택한 [교차 도구 표준](https://agents.md/)입니다. Codex, opencode, Antigravity 3개 CLI가 이를 직접 읽습니다.

---

## 3. 각 진입점의 역할과 동작

### 3.1 AGENTS.md (정본)

- 프로젝트 규칙의 **유일한 편집 대상**이자 모든 에이전트의 **단일 자동 로드 정본**입니다.
- 비협상 원칙(G1/G2/G3), 코딩 규칙, 절대 금지 행위, Orca 다중 섹션 조율 규칙을 정의합니다.
- 역할별 부트스트랩 모드(Coordinator, Orca Worker, Reviewer, Standalone)를 정의하여 불필요한 전체 문서 재독을 방지합니다.

### 3.2 SKILLS.md (선택형 컨텍스트 & 스킬 인덱스)

- Coordinator 및 Standalone 에이전트용 선택형 참조 인덱스입니다.
- 프로젝트 현재 상태([`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)) 안내, 작업 유형별 참조 문서 매핑, 서비스 품질 우선 원칙, 문서화 표준을 제공합니다.
- Orca 워커는 본 문서를 읽지 않으며, 코디네이터가 주입한 `ORCA_TASK_CAPSULE_V2`의 허용 파일 목록만 따릅니다.

### 3.3 CLAUDE.md (thin pointer)

- Claude Code는 `CLAUDE.md`를 자동 읽습니다.
- 본 파일은 `@AGENTS.md` import 한 줄만 포함하며, Claude Code가 import를 확장해 AGENTS.md 전체를 주입합니다.
- 규칙을 직접 적지 않습니다 (드리프트 방지).

### 3.4 opencode.json (opencode 전용)

- opencode CLI는 `opencode.json`의 `instructions` 배열을 통해 자동 로드 대상을 지정합니다.
- 본 프로젝트에서는 `["AGENTS.md"]`로 단일화하여 Cerebras 및 소형 컨텍스트 모델의 토큰 오버헤드를 방지합니다.

### 3.5 .cursor/rules/00-core-guidelines.mdc (Cursor 전용)

- Cursor는 루트 마크다운을 파일명으로 자동 인식하지 않으므로 `.cursor/rules/*.mdc` 독점 포맷을 사용합니다.
- `00-core-guidelines.mdc`(`alwaysApply: true`)가 항상 로드되며 AGENTS.md를 참조합니다.
- 정본 규칙을 복사하지 않고, 핵심 요약 + 정본 링크만 제공합니다.

---

## 4. 규칙 편집 워크플로우

### 4.1 규칙 변경 시

1. **`AGENTS.md`만 편집합니다.**
2. 핵심 규칙(비협상 원칙, 코딩 규칙, 금지 행위) 변경 시 `SKILLS.md` 및 요약본(`.antigravity/rules.md`, `.cursor/rules/00-core-guidelines.mdc`)의 정합성을 확인합니다.
3. `python scripts/validate_agent_rules.py`로 정합성을 검증합니다.

### 4.2 절대 하면 안 되는 행위

- `CLAUDE.md`에 규칙 내용을 직접 적기 (단일 소스 붕괴).
- `.cursor/rules/*.mdc`에 정본(AGENTS.md)과 다른 규칙을 적기.
- `AGENTS.md`와 `SKILLS.md`에 상충하는 코딩 규칙을 적기.

---

## 5. Orca 섹션 조율 규약

두 섹션 이상의 작업, 작업 간 병합·검증 의존성, 공유 자원 사용이 있으면 모든 에이전트는 `.agents/skills/orca-section-coordination/SKILL.md`를 먼저 읽습니다. 코디네이터는 Orca Run에 각 섹션을 Task로 등록하고, 의존성·공유 자원 소유자·완료 기준을 명시합니다.

| 단계 | Orca 기록 | 다음 단계 조건 |
| :--- | :--- | :--- |
| 계획 | Run + Task | 의존성·소유자·검증 기준 등록 |
| 실행 | Dispatch | 독립 Task만 병렬 실행 |
| 완료 | `worker_done` | 검증 결과와 변경 파일 확인 |
| 후속 작업 | 의존 Task Dispatch | 선행 Task의 검증 완료 |
| 병합 | 별도 Git Task | 테스트·규칙 검증·사용자 승인 확인 |

터미널 출력, 채팅의 구두 보고, 단순 프로세스 종료는 완료·병합·후속 작업 시작의 근거가 아닙니다. Orca 런타임을 이용할 수 없으면 조율 작업을 시작하지 않고 차단 원인을 보고합니다.

---

## 6. 신규 에이전트 추가 체크리스트

새로운 에이전트를 도입할 때의 진입점 추가 절차입니다.

| 단계 | 확인 사항 |
| :--- | :--- |
| 1 | 해당 에이전트가 `AGENTS.md`를 네이티브로 읽는가? → 그러면 진입점 추가 불필요 |
| 2 | 별도 파일명을 요구하는가? (예: `FOO.md`) → thin pointer(`@AGENTS.md`) 또는 symlink 생성 |
| 3 | 독점 포맷인가? (예: Cursor `.mdc`) → 해당 포맷에 맞춰 AGENTS.md 참조 파일 생성 |
| 4 | 본 가이드 §2 매핑 테이블에 신규 에이전트 행 추가 |

---

## 7. 관련 파일 인덱스

| 파일 | 역할 |
| :--- | :--- |
| `AGENTS.md` | 규칙 정본 (단일 진실 원천) |
| `SKILLS.md` | 시작 시퀀스, 문서 규칙, 워크플로우 체크리스트 |
| `CLAUDE.md` | Claude Code thin pointer (`@AGENTS.md`) |
| `opencode.json` | opencode instructions 설정 |
| `.antigravity/rules.md` | Antigravity 핵심 규칙 요약본 (12,000자 캡 준수) |
| `.cursor/rules/*.mdc` | Cursor 핵심 규칙 (00-core) 및 Phase 0~7 스킬 규칙 (01~08) |
| `.agents/skills/{스킬명}/` | 스킬 정본 (Phase 0~7 8개 스킬) |
| `.claude/skills/{스킬명}/` | Claude Code 전용 스킬 1:1 미러 |
| `.opencode/skills/{스킬명}/` | opencode 전용 스킬 1:1 미러 |
| `.agents/skills/orca-section-coordination/` | Orca 기반 다중 섹션 조율 스킬 정본 |
| `scripts/validate_agent_rules.py` | 정합성 자동 검증 스크립트 (pre-commit 연동) |


---

## 8. 참고 자료

- [AGENTS.md 공식 표준](https://agents.md/)
- [OpenAI Codex — AGENTS.md 가이드](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenCode — Config 문서](https://opencode.ai/docs/config/)
- [Google Antigravity — Best Practices](https://antigravity.google/docs/cli/best-practices)
- [Cursor — Rules 문서](https://cursor.com/docs/rules)
- [CLAUDE.md vs AGENTS.md 비교 (2026)](https://agyn.io/blog/claude-md-agents-md-compatibility)
