# 인수인계: 다중 에이전트 스킬 시스템 구축

> **작성일**: 2026-07-31
> **작성자**: ZCode 에이전트 (이전 세션)
> **인계 대상**: 다음 세션의 AI 에이전트 (Claude Code / Cursor / opencode / Codex / Antigravity)
> **작업**: refac_bid_box 프로젝트에 5개 CLI 동기화 스킬 시스템 구축
> **난이도**: 중상
> **예상 소요**: 토큰 약 30~40K (이전 세션 토큰 부족으로 인계)

---

## 0. 한 줄 요약

refac_bid_box 프로젝트에 **Phase 0~7 리팩토링 작업을 스킬로 만들어, 5개 CLI(opencode, Cursor, Codex, Claude Code, Antigravity) 어디서든 `/스킬명` 또는 자동으로 호출**할 수 있도록 구축하는 작업입니다. 참고 모델은 **Minchodan 프로젝트**의 다중 에이전트 스킬 시스템입니다.

---

## 1. 배경 — 왜 이 작업이 필요한가

### 1.1 프로젝트 컨텍스트

refac_bid_box는 기존 `bid_box`(Django 5.1.6 모놀리식 공공조달 입찰 예측 플랫폼)를 리팩토링하는 프로젝트입니다.

**3대 핵심 목표:**

| 목표 | 내용 |
| --- | --- |
| G1. 데이터 무손실 | DB 행 수·스키마 100% 보존, ML 가중치·벡터DB 무결성 |
| G2. 크로스 플랫폼 | macOS/Windows 동일 환경 (Docker + Makefile) |
| G3. 스택 최적화 | 레이턴시·정합성 개선, 비동기화, **train/serve skew 해결** (핵심) |

**재학습 파이프라인이 기존에 전무했으며**, 이번 리팩토링에서 신규 구축합니다 (설계서 7장 참조).

### 1.2 왜 스킬 시스템인가

사용자는 **5개 CLI 에이전트를 돌아가며 사용**합니다. 각 CLI가 세션 시작 시 동일한 규칙을 로드하도록 **규칙 파일 체인(AGENTS.md → SKILLS.md)**은 이미 구축 완료되었습니다 (이전 세션 작업). 이제 그 다음 단계로, **재학습 실행, 데이터 마이그레이션 검증, Phase별 구현** 등 반복 작업을 스킬로 만들어 어느 CLI에서든 명시적 호출(` /스킬명`)이 가능하도록 해야 합니다.

---

## 2. 현재 완료된 상태 (규칙 파일 체인) ★ 반드시 읽을 것

이미 다음 파일들이 구축되어 커밋되었습니다. **스킬 시스템은 이 위에 얹히는 구조입니다.**

### 2.1 규칙 파일 체인 (자동 로드, 키워드 불필요)

```
AGENTS.md (정본, SSoT)  ← 모든 CLI의 단일 진실 원천
   ↓ @SKILLS.md import
SKILLS.md (보조: 시작 시퀀스, 문서 규칙, 워크플로우)
   ↓
CLAUDE.md (thin pointer @AGENTS.md)        → Claude Code 자동 로드
.cursor/rules/00-core-guidelines.mdc        → Cursor 자동 로드 (alwaysApply)
opencode.json (instructions 배열)           → opencode 자동 로드
AGENTS.md 직접                               → Codex, Antigravity 자동 로드
```

### 2.2 현재 docs 구조 (간결화 완료)

```
docs/
├── README.md                 # 마스터 인덱스
├── design/
│   └── REFACTORING_DESIGN.md # ★ 전체 설계서 (핵심, 반드시 읽을 것)
├── migration/
│   ├── db_migration_runbook.md
│   └── ml_weights_verification.md
└── ops/
    ├── environment_variables.md
    ├── cross_platform_guide.md
    ├── git_branching_strategy.md
    └── multi_agent_setup.md  # ★ 다중 에이전트 매핑 문서 (반드시 읽을 것)
```

### 2.3 리팩토링 Phase 구조 (스킬의 원천)

`docs/design/REFACTORING_DESIGN.md` 8장에 8개 Phase가 정의되어 있습니다. **각 Phase가 하나의 스킬이 됩니다:**

| Phase | 이름 | 핵심 내용 |
| --- | --- | --- |
| 0 | foundation-setup | uv, Makefile, Dockerfile, CI, 린터 |
| 1 | data-preservation | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| 2 | infrastructure | ORM 이식, Redis, 태스크 큐 |
| 3 | application-migration | 백엔드 이식, 파일 분할, 비동기화 |
| 4 | inference-rag-opt | 싱글톤 로드, 가중치 외부화, RAG 비동기 |
| **5** | **retraining-pipeline** | **★ 핵심: 특징 함수, 데이터셋 빌더, 학습기, 레지스트리, 모니터링** |
| 6 | frontend-streaming | SSE/WebSocket, HTMX (선택) |
| 7 | validation-cutover | E2E, 벤치마크, 크로스플랫폼 검증 |

---

## 3. 참고 모델 — Minchodan 프로젝트 ★ 반드시 분석할 것

**가장 중요합니다.** Minchodan은 5명 팀이 7개 CLI를 쓰며 이미 검증된 다중 에이전트 스킬 시스템을 갖추고 있습니다. 이 구조를 그대로 모델로 삼으십시오.

### 3.1 Minchodan 위치

```
/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/Minchodan
```

### 3.2 Minchodan 스킬 디렉토리 구조 (반드시 직접 확인할 것)

```
Minchodan/
├── AGENTS.md                          # 정본 (refac_bid_box와 동일 패턴)
├── CLAUDE.md                          # thin pointer
├── SKILLS.md                          # 보조
├── .agents/skills/                    # ★ 스킬 정본 디렉토리
│   ├── websocket-gateway/
│   │   └── SKILL.md
│   ├── camera-frame-capture/
│   │   └── SKILL.md
│   ├── yolo-obstacle-detection/
│   │   ├── SKILL.md
│   │   └── references/                # 상세 레퍼런스 하위 디렉토리
│   │       └── implementation_detail.md
│   ├── integration-test-orchestrator/
│   │   └── SKILL.md
│   └── ... (총 12개 스킬)
├── .claude/skills/                    # ★ .agents/skills/ 의 미러 (내용 동일)
│   ├── websocket-gateway/SKILL.md
│   └── ... (.agents/skills/와 1:1 매칭)
├── .cursor/rules/                     # ★ Cursor 전용 (.mdc 포맷)
│   ├── 00-core-guidelines.mdc         # alwaysApply (항상 로드)
│   ├── 01-reflex-path-guard.mdc       # globs 기반 자동 첨부
│   ├── 02-stage1-websocket-gateway.mdc
│   └── ... (스킬당 1개 .mdc)
├── .antigravity/
│   └── rules.md                       # ★ Antigravity 요약본 (12,000자 캡 대응)
└── scripts/
    └── validate_agent_rules.py        # ★ 정합성 자동 검증 스크립트
```

### 3.3 반드시 읽어야 할 Minchodan 파일 (우선순위순)

| 순서 | 파일 | 이유 |
| --- | --- | --- |
| 1 | `Minchodan/docs/dev-guides/multi_agent_setup.md` | ★ 다중 에이전트 아키텍처 총서. 매핑 테이블, 편집 워크플로우, 검증 방법 |
| 2 | `Minchodan/.agents/skills/integration-test-orchestrator/SKILL.md` | ★ 가장 상세한 SKILL.md 예시. 구조·frontmatter·Mermaid·가드레일 참고 |
| 3 | `Minchodan/.agents/skills/yolo-obstacle-detection/` | `references/` 하위 디렉토리 구조 참고 |
| 4 | `Minchodan/.cursor/rules/02-stage1-websocket-gateway.mdc` | .mdc 포맷 변환 방식 참고 (`globs`, `alwaysApply`) |
| 5 | `Minchodan/scripts/validate_agent_rules.py` | 정합성 검증 스크립트 구조 참고 |

### 3.4 SKILL.md 표준 구조 (Minchodan에서 추출)

```markdown
---
name: 스킬명 (kebab-case)
description: |
  스킬이 언제 트리거되어야 하는지 설명. 이 description이 자동 트리거 매칭의 핵심.
  모델이 작업 요청을 보고 이 description과 매칭하면 스킬을 로드함.
---

# 스킬 제목

> **작성일**: YYYY-MM-DD
> **버전**: vX.Y.Z
> **설계 기준**: docs/... 참조 문서 목록
> **관련 스킬**: 다른 스킬 링크

---

## 개요
이 스킬이 해결하는 문제와 언제 사용하는지.

## 선행 의존성
| 구분 | 필수 요구사항 | 확인 명령 |

## 디렉토리 구조 및 핵심 자산
| 경로 | 역할 |

## 핵심 워크플로우
(mermaid 다이어그램)

## 단계별 실행
### 0. ...
### 1. ...

## 에이전트 권한 및 안전 가드레일
허용/금지 행동 표

## 세션 종료 시 정리

## 주의 사항
```

### 3.5 .mdc 포맷 (Cursor 전용) 표준 구조

```markdown
---
description: 스킬 설명 (한 줄)
globs: 작업 경로 패턴 (예: src/ml/**,src/tasks/**)
alwaysApply: false
---

# 스킬 제목

정본(.agents/skills/스킬명/SKILL.md)을 먼저 읽으라는 안내 + 핵심 계약 요약.
```

- `alwaysApply: true` → 항상 로드 (00-core-guidelines만 해당)
- `alwaysApply: false` + `globs` → 해당 경로 작업 시 자동 첨부

---

## 4. 구축해야 할 작업 상세 ★

### 4.1 작업 1: 스킬 정본 디렉토리 생성 (`.agents/skills/`)

refac_bid_box의 Phase 0~7에 대해 각각 스킬을 생성합니다.

**생성할 스킬 목록 (8개):**

| 스킬명 | Phase | globs (Cursor 자동첨부용) | 설계서 참조 |
| --- | --- | --- | --- |
| `foundation-setup` | 0 | `pyproject.toml`,`Makefile`,`Dockerfile`,`.github/**` | 설계서 8장 Phase 0 |
| `data-preservation` | 1 | `docs/migration/**`,`scripts/verify*` | 설계서 5장, 8장 Phase 1 |
| `infrastructure-setup` | 2 | `src/app/models/**`,`migrations/**`,`src/tasks/**` | 설계서 8장 Phase 2 |
| `application-migration` | 3 | `src/app/api/**`,`src/app/services/**` | 설계서 8장 Phase 3 |
| `inference-rag-opt` | 4 | `src/ml/**`,`src/rag/**` | 설계서 8장 Phase 4 |
| **`retraining-pipeline`** | **5** | **`src/ml/features.py`,`src/ml/dataset.py`,`src/ml/trainer.py`,`ml_registry/**`** | **설계서 7장 ★ 핵심** |
| `frontend-streaming` | 6 | `templates/**`,`src/app/api/chatbot*` | 설계서 8장 Phase 6 |
| `validation-cutover` | 7 | `tests/**`,`scripts/benchmark*` | 설계서 8장 Phase 7 |

**각 스킬 디렉토리 구조:**

```
.agents/skills/{스킬명}/
├── SKILL.md              # 메인 가이드 (frontmatter + 상세)
└── references/           # (선택) 상세 레퍼런스
    └── implementation_detail.md
```

**SKILL.md 작성 원칙:**

- `docs/design/REFACTORING_DESIGN.md`의 해당 Phase 섹션을 **근거**로 삼습니다.
- 핵심 특징(train/serve skew, 데이터 무손실 등)은 `AGENTS.md`의 비협상 원칙과 일치해야 합니다.
- **한국어 존댓말, 이모지 금지** (AGENTS.md 문서화 규칙 준수).
- Mermaid 다이어그램 적극 사용 (노드 텍스트 큰따옴표, `<br/>` 줄바꿈).
- `retraining-pipeline` 스킬이 가장 중요합니다 (설계서 7장 전체 차지).

### 4.2 작업 2: Claude Code 미러 생성 (`.claude/skills/`)

`.agents/skills/`의 내용을 `.claude/skills/`에 **1:1로 복사**합니다. Minchodan이 이 방식을 사용합니다.

```
.claude/skills/foundation-setup/SKILL.md      ← .agents/skills/와 동일
.claude/skills/retraining-pipeline/SKILL.md   ← 동일
...
```

> **이유**: Claude Code는 `.claude/skills/`를 네이티브로 스캔합니다. `.agents/skills/`는 다른 CLI용 표준 위치이므로 양쪽에 동일 내용이 있어야 합니다.

### 4.3 작업 3: Cursor 룰 생성 (`.cursor/rules/`)

각 스킬에 대해 `.mdc` 파일을 생성합니다. 이미 `00-core-guidelines.mdc`는 존재합니다.

**생성할 파일 (8개):**

```
.cursor/rules/
├── 00-core-guidelines.mdc          # (이미 존재, alwaysApply: true)
├── 01-foundation-setup.mdc         # globs: pyproject.toml,Makefile,...
├── 02-data-preservation.mdc        # globs: docs/migration/**
├── 03-infrastructure-setup.mdc     # globs: src/app/models/**
├── 04-application-migration.mdc    # globs: src/app/api/**
├── 05-inference-rag-opt.mdc        # globs: src/ml/**
├── 06-retraining-pipeline.mdc      # globs: src/ml/features.py,...
├── 07-frontend-streaming.mdc       # globs: templates/**
└── 08-validation-cutover.mdc       # globs: tests/**
```

**작성 원칙:**

- 정본(.agents/skills/)을 복사하지 않고, **핵심 요약 + 정본 참조 링크**만 제공 (Minchodan 방식).
- frontmatter `description`, `globs`, `alwaysApply: false` 설정.

### 4.4 작업 4: Antigravity 요약본 (`.antigravity/rules.md`)

Antigravity는 **파일당 12,000자 캡**이 있습니다. AGENTS.md 정본이 캡을 초과할 수 있으므로 핵심 규칙 요약본을 별도로 만듭니다.

**구조 (Minchodan 참고):**

```markdown
# refac_bid_box Antigravity 핵심 규칙 (요약본)

> 본 파일은 AGENTS.md 정본의 핵심 행동 규칙을 압축한 요약본입니다 (12,000자 이내).
> 충돌 시 AGENTS.md 정본이 우선합니다.

## 비협상 원칙
...
## 코딩 규칙
...
## 스킬 인덱스
...
```

### 4.5 작업 5: opencode 스킬 디렉토리 (`.opencode/skills/`)

opencode는 `SKILL.md`를 가진 폴더를 자동 발견합니다. `.agents/skills/`와 동일 구조로 생성합니다.

```
.opencode/skills/{스킬명}/SKILL.md
```

### 4.6 작업 6: 정합성 검증 스크립트 (`scripts/validate_agent_rules.py`)

Minchodan의 `scripts/validate_agent_rules.py`를 참고하여 아래를 검증하는 스크립트를 작성합니다.

**검증 항목:**

| 항목 | 내용 |
| --- | --- |
| CLAUDE.md thin pointer | `@AGENTS.md` import 포함 + 정본 미복사 |
| `.antigravity/rules.md` | 존재 + 12,000자 이하 + 핵심 섹션 포함 |
| `.cursor` core rule | `00-core-guidelines.mdc`가 AGENTS.md 참조 |
| 스킬 미러 | `.agents/skills/` 와 `.claude/skills/` 내용 동일 |
| AGENTS.md import | `@SKILLS.md` 구문 존재 |
| opencode.json | instructions 배열에 AGENTS.md, SKILLS.md 포함 |

**pre-commit 훅 연동** (`.git/hooks/pre-commit`):

```bash
#!/bin/sh
if git diff --cached --name-only | grep -qE '^(AGENTS\.md|CLAUDE\.md|SKILLS\.md|\.antigravity/|\.agents/skills/|\.claude/skills/|\.cursor/)'; then
    echo "[pre-commit] 다중 에이전트 규칙 정합성 검증..."
    python scripts/validate_agent_rules.py --quiet || exit 1
fi
```

### 4.7 작업 7: 문서 갱신

- `AGENTS.md`에 **스킬 인덱스 섹션** 추가 (8개 스킬 표, SKILLS.md의 SKILL 인덱스 참고).
- `SKILLS.md`의 "SKILL 인덱스" 섹션 업데이트 (현재 Phase 가이드 링크 → 실제 스킬 링크로).
- `docs/ops/multi_agent_setup.md` §3에 각 CLI의 스킬 디렉토리 설명 추가.
- `docs/README.md`에 스킬 시스템 언급 추가.

---

## 5. 트리거 방식 정리 (사용자에게 설명할 내용)

스킬 시스템 구축 후 사용자가 스킬을 호출하는 방법:

| CLI | 호출 방법 | 자동 트리거 |
| --- | --- | --- |
| Claude Code | `/project:스킬명` (예: `/project:retraining-pipeline`) | description 매칭 (불안정) |
| opencode | 자연어 "retraining 스킬 사용" 또는 폴더 참조 | 폴더명 + description 매칭 |
| Cursor | 해당 `globs` 경로 작업 시 `.mdc` 자동 첨부 | `globs` 매칭 (안정적) |
| Codex | AGENTS.md의 스킬 인덱스 참조 지시 | - |
| Antigravity | `.antigravity/rules.md`의 스킬 인덱스 참조 | - |

> **중요**: 자동 트리거는 CLI마다 신뢰도가 다릅니다. 가장 신뢰할 수 있는 방법은 명시적 수동 호출입니다. 사용자에게 이 사실을 안내하십시오.

---

## 6. 비협상 원칙 (스킬 작성 시 반드시 준수)

이 원칙들은 `AGENTS.md`와 `SKILLS.md`에 정의되어 있으며, 스킬 내용과 충돌해서는 안 됩니다.

1. **데이터 무손실**: 기존 DB 테이블/컬럼명·타입 변경 금지.
2. **Train/Serve 특징 단일화**: 특징 생성은 `src/ml/features.py` 단일 함수만 사용. 하드코딩 상수(`DEFAULT_INST_RATE` 등) 제거.
3. **크로스 플랫폼**: macOS/Windows Docker + Makefile 동일 환경.
4. **시크릿 비기록**: `.env` 실제 값은 문서/코드에 노출 금지.
5. **한국어 존댓말, 이모지 금지**: 모든 스킬 문서에 적용.
6. **규칙 단일 진실 원천**: 코딩 규칙은 AGENTS.md에서만, 스킬에는 복사하지 않음 (참조만).

---

## 7. 작업 재개 절차

1. **본 인수인계 문서를 처음부터 끝까지 읽습니다.**
2. `refac_bid_box/AGENTS.md`, `SKILLS.md`, `docs/design/REFACTORING_DESIGN.md` (특히 7장 재학습, 8장 로드맵)를 읽습니다.
3. `refac_bid_box/docs/ops/multi_agent_setup.md`를 읽습니다.
4. **Minchodan 참고 모델 분석** (§3.3 파일 목록 순서대로):
   - `Minchodan/docs/dev-guides/multi_agent_setup.md`
   - `Minchodan/.agents/skills/integration-test-orchestrator/SKILL.md`
   - `Minchodan/.cursor/rules/02-stage1-websocket-gateway.mdc`
   - `Minchodan/scripts/validate_agent_rules.py`
5. 작업 1~7을 순서대로 실행합니다.
6. 각 작업 완료 후 커밋합니다.

---

## 8. 트러블슈팅 / 주의사항

| 이슈 | 대응 |
| --- | --- |
| Minchodan 스킬이 iOS/모바일 특화라 refac_bid_box에 안 맞음 | 도메인(입찰예측/재학습)에 맞게 내용 재작성. 구조·패턴만 차용 |
| 12,000자 캡 (Antigravity) | `.antigravity/rules.md`는 핵심만 압축. 정본은 AGENTS.md |
| 스킬 미러 동기화 | `.agents/skills/` 수정 시 반드시 `.claude/skills/`에도 반영. 검증 스크립트로 확인 |
| 자동 트리거 불안정 | 사용자에게 수동 호출(`/스킬명`) 권장 안내 |
| 토큰 부족 | 8개 스킬을 한 번에 다 만들지 말고, **Phase 5(retraining-pipeline)를 최우선**으로 구축 후 나머지는 점진적 추가 |

---

## 9. 관련 파일 인덱스

### refac_bid_box (작업 대상)

| 파일 | 역할 |
| --- | --- |
| `AGENTS.md` | 규칙 정본 (스킬 인덱스 추가 예정) |
| `SKILLS.md` | 보조 규칙 (SKILL 인덱스 섹션 있음, 업데이트 예정) |
| `docs/design/REFACTORING_DESIGN.md` | ★ 전체 설계서 (스킬 내용의 근거) |
| `docs/ops/multi_agent_setup.md` | 다중 에이전트 매핑 (스킬 디렉토리 설명 추가 예정) |

### Minchodan (참고 모델)

| 파일 | 역할 |
| --- | --- |
| `Minchodan/docs/dev-guides/multi_agent_setup.md` | ★ 아키텍처 총서 |
| `Minchodan/.agents/skills/*/SKILL.md` | 스킬 정본 예시들 |
| `Minchodan/.claude/skills/*/SKILL.md` | 미러 예시 |
| `Minchodan/.cursor/rules/*.mdc` | Cursor 포맷 예시 |
| `Minchodan/.antigravity/rules.md` | Antigravity 요약본 예시 |
| `Minchodan/scripts/validate_agent_rules.py` | 검증 스크립트 예시 |

---

## 10. 완료 기준 (Definition of Done)

- [ ] `.agents/skills/` 에 8개 스킬 생성 (각 SKILL.md + 선택 references/)
- [ ] `.claude/skills/` 에 동일 8개 스킬 미러
- [ ] `.cursor/rules/` 에 8개 `.mdc` 파일 (00-core 제외)
- [ ] `.antigravity/rules.md` 요약본 생성 (12,000자 이하)
- [ ] `.opencode/skills/` 에 8개 스킬
- [ ] `scripts/validate_agent_rules.py` 정합성 검증 스크립트
- [ ] `.git/hooks/pre-commit` 훅 연동
- [ ] `AGENTS.md` 스킬 인덱스 섹션 추가
- [ ] `SKILLS.md` SKILL 인덱스 업데이트
- [ ] `docs/ops/multi_agent_setup.md` 스킬 디렉토리 설명 추가
- [ ] 모든 커밋 완료 + GitHub 푸시

---

_본 인수인계 문서는 다음 세션 에이전트가 밑바닥부터 조사하지 않고 바로 작업을 시작할 수 있도록 작성되었습니다._
