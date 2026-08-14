# Orca v2 계약 Cross-CLI 결정론적 검증 보고서 (T6)

> **작성일**: 2026-08-15
> **버전**: v1.1.0
> **태스크 ID**: task_38c10122a443
> **디스패치 ID**: ctx_4bbe2f6216ae
> **검증 대상**: Orca Task Capsule v2 자동 로드 진입점 및 결정론적 검증기 (Cross-CLI)
> **관련 문서**: [`docs/ops/orca_task_capsule_v2.md`](orca_task_capsule_v2.md), [`docs/ops/multi_agent_setup.md`](multi_agent_setup.md), [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`scripts/validate_agent_rules.py`](../../scripts/validate_agent_rules.py)

---

## 1. 개요 및 목적

본 보고서는 Orca Task Capsule v2 체계에서 병합된 규칙 자동 로드 계약이 지원 대상 5대 CLI 진입점(Codex, opencode, Antigravity, Claude Code, Cursor) 및 결정론적 검증기(`scripts/validate_agent_rules.py`)의 설정 및 진입점 정적 정합성을 검증한 결과입니다.

주요 검증 범위:
1. 5대 AI 코딩 CLI 진입점 파일 및 설정의 단일 진실 원천(`AGENTS.md`) 참조 정합성 (정적 검증)
2. 결정론적 검증기(`scripts/validate_agent_rules.py`)의 9대 규칙 전량 통과 여부
3. 레거시 이중 주입(예: `opencode.json` 내 `SKILLS.md` 동시 주입, `AGENTS.md` 내 `@SKILLS.md` 참조) 및 변조 입력에 대한 검증기의 기각(Fail-closed) 동작
4. 3방향 스킬 미러(`.agents/skills`, `.claude/skills`, `.opencode/skills`)의 바이트 단위 완전 일치 여부

---

## 2. CLI 진입점 및 설정 정적 검증

5개 CLI 환경의 진입점 파일과 설정값을 정적 검증하여 확인하였습니다.

| CLI 도구 | 자동 로드 진입점 | 진입점 방식 | 실측 상태 | 판정 |
| :--- | :--- | :--- | :--- | :---: |
| **Codex CLI** | `AGENTS.md` | 정본 직접 로드 | 6개 부트스트랩 섹션 및 비협상 원칙 포함, `@SKILLS.md` 미참조 확인 | **통과** |
| **opencode CLI** | `opencode.json` | instructions 단일 배열 | `instructions: ["AGENTS.md"]` 단일 배열 확인 (추가/빈 배열/문자열 없음) | **통과** |
| **Antigravity CLI** | `.antigravity/rules.md` | 요약본 로드 | 3,921자 (12,000자 상한 대비 8,079자 여유), 7개 필수 키워드 완비 | **통과** |
| **Claude Code CLI** | `CLAUDE.md` | Thin Pointer | `@AGENTS.md` 1개 지시어만 포함 (4줄, 54바이트), 정본 섹션 복사 0건 | **통과** |
| **Cursor CLI** | `.cursor/rules/00-core-guidelines.mdc` | 간접 참조 규칙 | `alwaysApply: true`, `globs: "**/*"`, `AGENTS.md` 정본 참조 확인 | **통과** |

---

## 3. 결정론적 유효성 검증기 실행 결과

결정론적 유효성 검증기(`scripts/validate_agent_rules.py`)를 실행하여 9개 검사 항목을 확인하였습니다.

### 3.1 실행 명령

```bash
python3 scripts/validate_agent_rules.py
```

### 3.2 실행 결과

```text
============================================================
다중 에이전트 규칙 정합성 검증 (pre-commit / v2)
============================================================
[PASS] CLAUDE.md thin pointer
       @AGENTS.md import 포함, 정본 미복사
[PASS] .antigravity/rules.md
       3,921자 (여유 8,079자), 핵심 섹션 포함
[PASS] .cursor core rule AGENTS.md 참조
       AGENTS.md 참조 확인
[PASS] opencode.json instructions v2 단일 주입
       AGENTS.md 단일 자동 로드 확인 (instructions == ["AGENTS.md"])
[PASS] 스킬 미러 정합성
       .claude/skills, .opencode/skills 내용 완전 일치
[PASS] AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)
       단일 부트스트랩 정본 확인 (@SKILLS.md 미참조, 비협상 원칙 완비)
[PASS] Task Capsule v2 규약 문서
       docs/ops/orca_task_capsule_v2.md 규약 완비
[PASS] Task Capsule v2 템플릿 정합성
       task_capsule_v2.yaml, worker_done_v2.json, review_done_v2.json 스키마 검증 통과
[PASS] orca-section-coordination v2 스킬
       orca-section-coordination 스킬 내 v2 계약 포함 확인
------------------------------------------------------------
검증 통과: 9/9 건.
```

요약 모드 검증 명령(`python3 scripts/validate_agent_rules.py --quiet`)에서도 종료 코드 0으로 9건 전량 정상 통과하였습니다.

---

## 4. 레거시 이중 주입 및 변조 입력 기각 테스트 (Negative Testing)

결정론적 검증기가 비정상 입력이나 레거시 v1 이중 주입 형식을 감지했을 때 정상적으로 실패(Fail)를 반환하는지 격리 환경에서 테스트하였습니다.

### 4.1 테스트 케이스 및 실측 결과

| 번호 | 테스트 대상 및 시나리오 | 입력값 | 예상 결과 | 실측 결과 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| N1 | `opencode.json` 레거시 이중 주입 | `{"instructions": ["AGENTS.md", "SKILLS.md"]}` | FAIL (이중 주입 감지) | `[FAIL] SKILLS.md 이중 주입 감지` | **통과** |
| N2 | `opencode.json` 문자열 타입 오류 | `{"instructions": "AGENTS.md"}` | FAIL (타입 위반) | `[FAIL] instructions 타입 위반 (JSON 배열만 허용)` | **통과** |
| N3 | `opencode.json` 빈 배열 입력 | `{"instructions": []}` | FAIL (빈 배열 위반) | `[FAIL] 빈 배열 (v2 단일 주입 위반)` | **통과** |
| N4 | `opencode.json` 추가 파일 주입 | `{"instructions": ["AGENTS.md", "EXTRA.md"]}` | FAIL (추가 항목 위반) | `[FAIL] 추가 항목 포함 (정확히 ["AGENTS.md"] 배열만 허용)` | **통과** |
| N5 | `opencode.json` 정상 단일 주입 | `{"instructions": ["AGENTS.md"]}` | PASS | `[PASS] AGENTS.md 단일 자동 로드 확인` | **통과** |
| N6 | `AGENTS.md` 레거시 `@SKILLS.md` 참조 | `@SKILLS.md` 포함 본문 | FAIL (레거시 참조 감지) | `[FAIL] AGENTS.md 에 레거시 @SKILLS.md import 구문 존재` | **통과** |
| N7 | `AGENTS.md` 정상 정본 | 필수 키워드 포함 본문 | PASS | `[PASS] 단일 부트스트랩 정본 확인` | **통과** |
| N8 | `CLAUDE.md` 정본 섹션 복제 | `@AGENTS.md` + `## 1. 프로젝트 개요` 복제 | FAIL (정본 복사 감지) | `[FAIL] 정본 섹션 1개 복사됨` | **통과** |
| N9 | `CLAUDE.md` 정상 Thin Pointer | `@AGENTS.md` 단일 참조 | PASS | `[PASS] @AGENTS.md import 포함, 정본 미복사` | **통과** |
| N10 | `.cursor` 규칙 정본 미참조 | `AGENTS.md` 참조 문구 없음 | FAIL (참조 누락) | `[FAIL] AGENTS.md 참조 문구 없음` | **통과** |
| N11 | `.cursor` 규칙 정상 참조 | `AGENTS.md` 참조 문구 포함 | PASS | `[PASS] AGENTS.md 참조 확인` | **통과** |
| N12 | 스킬 미러 불일치(Drift) | `.opencode/skills` 파일 내용 변조 | FAIL (내용 상이 감지) | `[FAIL] 내용 상이` | **통과** |

테스트 결과: pytest 11개 단위 테스트 함수 전량 통과(`11 passed, 0 failed` in `tests/test_validate_agent_rules.py`) 및 12개 핵심 시나리오(N1~N12) 전량 예상과 정확히 일치하여 정상 기각 및 정상 수락이 확인되었습니다.

---

## 5. 스킬 디렉터리 3방향 미러 동일성 검증

프로젝트 내 존재하는 3개 스킬 디렉터리(`.agents/skills`, `.claude/skills`, `.opencode/skills`)의 12개 스킬 전체에 대해 디렉터리 트리 재귀 비교(`filecmp.dircmp`)를 수행하였습니다.

### 5.1 검증 대상 12개 스킬

1. `application-migration`
2. `data-preservation`
3. `foundation-setup`
4. `frontend-streaming`
5. `git-workflow`
6. `inference-rag-opt`
7. `infrastructure-setup`
8. `orca-section-coordination`
9. `project-orchestrator`
10. `retraining-pipeline`
11. `servc-model-tuning`
12. `validation-cutover`

### 5.2 검증 결과

- `.agents/skills` vs `.claude/skills`: 차이 0건 (완전 일치)
- `.agents/skills` vs `.opencode/skills`: 차이 0건 (완전 일치)

---

## 6. Task Capsule v2 템플릿 및 규약 정합성

Task Capsule v2 관련 템플릿과 규약 문서의 정합성을 검증하였습니다.

| 대상 파일 | 형식 | 필수 검증 항목 | 검증 결과 |
| :--- | :--- | :--- | :---: |
| `docs/ops/orca_task_capsule_v2.md` | Markdown | 규약 핵심 키워드 5종 포함 (`ORCA_TASK_CAPSULE_V2`, `ORCA_WORKER_DONE_V2`, `ORCA_REVIEW_DONE_V2`, `3단계 검증`, `자족적 실행 계약`) | **통과** |
| `.agents/templates/task_capsule_v2.yaml` | YAML | `schema: ORCA_TASK_CAPSULE_V2`, `version: 2.0.0`, 필수 키 19개 완비 | **통과** |
| `.agents/templates/worker_done_v2.json` | JSON | `schema: ORCA_WORKER_DONE_V2`, `version: 2.0.0`, 필수 키 16개 완비 | **통과** |
| `.agents/templates/review_done_v2.json` | JSON | `schema: ORCA_REVIEW_DONE_V2`, `version: 2.0.0`, 필수 키 9개 완비 | **통과** |
| `.agents/skills/orca-section-coordination/SKILL.md` | Markdown | v2 계약 키워드 3종 완비 | **통과** |

---

## 7. 종합 판정 및 결론

T6 태스크 요구사항에 따른 모든 Acceptance Criteria를 충족하였습니다.

1. **진입점 및 설정 정적 검증 완료**: Codex, opencode, Antigravity, Claude Code, Cursor 등 5대 CLI 진입점 및 설정 파일이 단일 진실 원천(`AGENTS.md`) 및 얇은 진입점 계약에 부합함을 확인.
2. **레거시 이중 주입 기각 검증 완료**: pytest 11개 단위 테스트 전량 통과(`11 passed`) 및 12개 핵심 시나리오(N1~N12)를 통해 `opencode.json` 내 `SKILLS.md` 이중 주입, 비정상 타입, `AGENTS.md` 내 `@SKILLS.md` 레거시 참조 등 정상 기각/수락 확인.
3. **스킬 미러 동일성 검증 완료**: 3개 스킬 디렉터리 12개 스킬에 대해 바이트 단위 완전 일치 확인.
4. **제품/규칙 무수정 원칙 준수**: 기존 제품 코드, 규칙 정본, 템플릿, 검증기, 설정 파일 일체 수정 없이 읽기 전용 검증 완료.
5. **보고서 산출 완료**: `docs/ops/orca_v2_cross_cli_validation_20260815.md` 작성 완료.
