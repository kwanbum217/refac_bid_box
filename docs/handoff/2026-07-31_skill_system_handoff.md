# 인수인계: 다중 에이전트 스킬 시스템 구축

> **작성일**: 2026-07-31 (갱신: 외부 참조 제거, 자급자족형으로 재작성)
> **작성자**: ZCode 에이전트 (이전 세션)
> **인계 대상**: 다음 세션의 AI 에이전트 (Claude Code / Cursor / opencode / Codex / Antigravity)
> **작업**: refac_bid_box 프로젝트에 5개 CLI 동기화 스킬 시스템 구축
> **난이도**: 중상
> **예상 소요**: 토큰 약 30~40K

---

## 0. 한 줄 요약

refac_bid_box 프로젝트에 **Phase 0~7 리팩토링 작업을 스킬로 만들어, 5개 CLI(opencode, Cursor, Codex, Claude Code, Antigravity) 어디서든 `/스킬명` 또는 자동으로 호출**할 수 있도록 구축하는 작업입니다.

> **중요 (워크스페이스 격리)**: 본 문서는 refac_bid_box 워크스페이스 내에서만 작동하도록 작성되었습니다. 외부 디렉토리 참조를 일절 포함하지 않습니다. Antigravity 등 워크스페이스 외부 접근을 차단하는 CLI에서도 그대로 작동합니다. **외부 프로젝트(Minchodan 등)의 파일을 읽으려 시도하지 마십시오 — 권한 훅에 의해 차단됩니다.**

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
├── ops/
│   ├── environment_variables.md
│   ├── cross_platform_guide.md
│   ├── git_branching_strategy.md
│   └── multi_agent_setup.md  # ★ 다중 에이전트 매핑 문서 (반드시 읽을 것)
└── handoff/
    └── 2026-07-31_skill_system_handoff.md  # 본 문서
```

### 2.3 리팩토링 Phase 구조 (스킬의 원천)

`docs/design/REFACTORING_DESIGN.md` 8장에 8개 Phase가 정의되어 있습니다. **각 Phase가 하나의 스킬이 됩니다:**

| Phase | 이름 | 핵심 내용 |
| --- | --- | --- |
| 0 | foundation-setup | uv, Makefile, Dockerfile, CI, 린터 |
| 1 | data-preservation | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| 2 | infrastructure-setup | ORM 이식, Redis, 태스크 큐 |
| 3 | application-migration | 백엔드 이식, 파일 분할, 비동기화 |
| 4 | inference-rag-opt | 싱글톤 로드, 가중치 외부화, RAG 비동기 |
| **5** | **retraining-pipeline** | **★ 핵심: 특징 함수, 데이터셋 빌더, 학습기, 레지스트리, 모니터링** |
| 6 | frontend-streaming | SSE/WebSocket, HTMX (선택) |
| 7 | validation-cutover | E2E, 벤치마크, 크로스플랫폼 검증 |

---

## 3. 구축해야 할 작업 상세 ★

### 3.1 작업 1: 스킬 정본 디렉토리 생성 (`.agents/skills/`)

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

### 3.2 작업 2: Claude Code 미러 생성 (`.claude/skills/`)

`.agents/skills/`의 내용을 `.claude/skills/`에 **1:1로 복사**합니다.

```
.claude/skills/foundation-setup/SKILL.md      ← .agents/skills/와 동일
.claude/skills/retraining-pipeline/SKILL.md   ← 동일
...
```

> **이유**: Claude Code는 `.claude/skills/`를 네이티브로 스캔합니다.

### 3.3 작업 3: Cursor 룰 생성 (`.cursor/rules/`)

이미 `00-core-guidelines.mdc`는 존재합니다. 각 스킬에 대해 `.mdc` 파일을 추가로 생성합니다.

```
.cursor/rules/
├── 00-core-guidelines.mdc          # (이미 존재, alwaysApply: true)
├── 01-foundation-setup.mdc
├── 02-data-preservation.mdc
├── 03-infrastructure-setup.mdc
├── 04-application-migration.mdc
├── 05-inference-rag-opt.mdc
├── 06-retraining-pipeline.mdc
├── 07-frontend-streaming.mdc
└── 08-validation-cutover.mdc
```

### 3.4 작업 4: Antigravity 요약본 (`.antigravity/rules.md`)

Antigravity는 **파일당 12,000자 캡**이 있습니다. AGENTS.md 정본이 캡을 초과할 수 있으므로 핵심 규칙 요약본을 별도로 만듭니다.

### 3.5 작업 5: opencode 스킬 디렉토리 (`.opencode/skills/`)

`.agents/skills/`와 동일 구조로 생성합니다.

### 3.6 작업 6: 정합성 검증 스크립트 (`scripts/validate_agent_rules.py`)

§5의 완성된 스크립트를 그대로 저장합니다.

### 3.7 작업 7: 문서 갱신

- `AGENTS.md`에 스킬 인덱스 섹션 추가
- `SKILLS.md`의 SKILL 인덱스 업데이트
- `docs/ops/multi_agent_setup.md`에 스킬 디렉토리 설명 추가
- `docs/README.md`에 스킬 시스템 언급 추가

---

## 4. 표준 템플릿 ★ 그대로 사용할 것

### 4.1 SKILL.md 표준 구조

> 각 스킬의 `.agents/skills/{스킬명}/SKILL.md`와 `.claude/skills/{스킬명}/SKILL.md`에 사용합니다.

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
> **설계 기준**: docs/design/REFACTORING_DESIGN.md 의 Phase N 섹션
> **관련 스킬**: 다른 스킬 링크 (예: ../retraining-pipeline/SKILL.md)

---

## 개요

이 스킬이 해결하는 문제와 언제 사용하는지 설명합니다.
Phase N의 목표와 범위를 한두 문단으로 요약합니다.

## 선행 의존성

| 구분 | 필수 요구사항 | 확인 명령 |
| :--- | :--- | :--- |
| Docker | Docker Desktop 또는 Colima | `docker compose version` |
| ... | ... | ... |

## 디렉토리 구조 및 핵심 자산

| 경로 | 역할 |
| :--- | :--- |
| `docs/design/REFACTORING_DESIGN.md` | 전체 설계서 (본 스킬의 근거) |
| ... | ... |

## 핵심 워크플로우

(mermaid 다이어그램으로 Phase의 작업 흐름을 표현)

## 단계별 실행

### 0. 사전 확인
### 1. 첫 번째 단계
### 2. ...

## 에이전트 권한 및 안전 가드레일

| 허용 | 금지 |
| :--- | :--- |
| ... | 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반) |
| ... | 학습·추론 특징 생성 로직 분리 (train/serve skew 유발) |
| ... | `.env` 실제 값을 코드/문서에 노출 |

## 세션 종료 시 정리

## 주의 사항
```

### 4.2 .mdc 포맷 (Cursor 전용) 표준 구조

> `.cursor/rules/{NN}-{스킬명}.mdc`에 사용합니다. 정본을 복사하지 않고 핵심 요약 + 정본 참조만 제공합니다.

```markdown
---
description: 스킬 설명 (한 줄)
globs: 작업 경로 패턴 (예: src/ml/**,src/tasks/**)
alwaysApply: false
---

# 스킬 제목

해당 경로 작업 시 `.agents/skills/{스킬명}/SKILL.md`를 먼저 읽으십시오.

핵심 계약:
- 계약 1
- 계약 2
- 계약 3
```

- `alwaysApply: true` → 항상 로드 (`00-core-guidelines.mdc`만 해당)
- `alwaysApply: false` + `globs` → 해당 경로 작업 시 자동 첨부

### 4.3 .antigravity/rules.md 요약본 구조

> AGENTS.md 정본의 핵심 행동 규칙을 압축 (12,000자 이하). 핵심 섹션 7개 반드시 포함.

```markdown
# refac_bid_box Antigravity 핵심 규칙 (요약본)

> 본 파일은 AGENTS.md 정본의 핵심 행동 규칙을 압축한 요약본입니다 (12,000자 이내).
> 충돌 시 AGENTS.md 정본이 우선합니다.

## 비협상 원칙
- 데이터 무손실: 기존 DB 테이블/컬럼명·타입 변경 금지.
- Train/Serve 특징 단일화: 특징 생성은 src/ml/features.py 단일 함수만 사용.
- 크로스 플랫폼: macOS/Windows Docker + Makefile 동일 환경.
- 시크릿 비기록: .env 실제 값은 문서/코드에 노출 금지.

## 코딩 규칙
- 한국어 존댓말, 이모지 금지.
- 프로젝트 루트 기준 경로.

## 금지 행위
- 기존 DB 스키마 변경 / 특징 로직 분리 / main push / .env 노출 / 라이브러리 무단 추가.

## Git 전략
- main 직접 push 금지, 브랜치→PR.
- 커밋: type: subject (feat/fix/docs/refactor/chore/test/ci).

## 스킬 인덱스
| 스킬 | Phase | 경로 |
| --- | --- | --- |
| foundation-setup | 0 | .agents/skills/foundation-setup/ |
| ... | ... | ... |

## 재학습 (핵심)
- train/serve skew 해소: 단일 features.py 사용.
- Champion/Challenger 게이트, 신규 모델 압도 시만 승격.

## 문서 규칙
- 메타데이터 블록(> 작성일/버전), 표 우선, Mermaid 다이어그램.
```

---

## 5. 정합성 검증 스크립트 (완성본) ★ 그대로 저장

> `scripts/validate_agent_rules.py`에 저장합니다. refac_bid_box 도메인에 맞춰 검증 항목을 조정했습니다.

```python
#!/usr/bin/env python3
"""
다중 에이전트 규칙 자동 로드 통합 정합성 검증 스크립트 (pre-commit).

단일 진실 원천(AGENTS.md) + 얇은 진입점(thin pointer/요약본) 아키텍처가
깨지지 않았는지 커밋 직전에 검증합니다.

검증 항목:
  1. CLAUDE.md 가 @AGENTS.md thin pointer 인지 (정본 복사 금지)
  2. .antigravity/rules.md 가 존재 + 12,000자 이하 + 핵심 섹션 포함
  3. .cursor/rules/00-core-guidelines.mdc 가 AGENTS.md 참조 여부
  4. .agents/skills/ 와 .claude/skills/ 내용 동일성 (미러 정합성)
  5. AGENTS.md 에 @SKILLS.md import 구문 존재 여부
  6. opencode.json instructions 배열 포함 여부

사용:
  python scripts/validate_agent_rules.py          # 전체 검증
  python scripts/validate_agent_rules.py --quiet   # 요약만

pre-commit 연동:
  .git/hooks/pre-commit 에서 본 스크립트 호출.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ANTIGRAVITY_CHAR_CAP = 12000

AGENTS_MD = PROJECT_ROOT / "AGENTS.md"
SKILLS_MD = PROJECT_ROOT / "SKILLS.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
ANTIGRAVITY_RULES = PROJECT_ROOT / ".antigravity" / "rules.md"
CURSOR_CORE_RULE = PROJECT_ROOT / ".cursor" / "rules" / "00-core-guidelines.mdc"
OPENCODE_JSON = PROJECT_ROOT / "opencode.json"
AGENTS_SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
CLAUDE_SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"

# .antigravity/rules.md 요약본이 반드시 포함해야 할 핵심 키워드 (드리프트 탐지용)
ANTIGRAVITY_REQUIRED_SECTIONS = [
    "데이터 무손실",
    "Train/Serve",
    "금지 행위",
    "이모지",
    "main",
    "재학습",
    "스킬 인덱스",
]


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str = "") -> None:
        self.name = name
        self.ok = ok
        self.detail = detail

    def format(self, quiet: bool = False) -> str:
        tag = "PASS" if self.ok else "FAIL"
        line = f"[{tag}] {self.name}"
        if not quiet and self.detail:
            line += f"\n       {self.detail}"
        return line


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def check_claude_is_pointer() -> CheckResult:
    if not CLAUDE_MD.exists():
        return CheckResult("CLAUDE.md thin pointer", False, "CLAUDE.md 파일 없음")
    content = read_text(CLAUDE_MD)
    has_import = "@AGENTS.md" in content
    canonical_markers = ["## 2. 기술 스택", "## 3. 코딩 규칙", "## 6. 금지 행위"]
    copied_count = sum(1 for marker in canonical_markers if marker in content)
    is_pointer = has_import and copied_count == 0
    if is_pointer:
        return CheckResult("CLAUDE.md thin pointer", True, "@AGENTS.md import 포함, 정본 미복사")
    detail = f"@AGENTS.md import={'있음' if has_import else '없음'}, 정본 섹션 {copied_count}개 복사됨"
    return CheckResult("CLAUDE.md thin pointer", False, detail)


def check_antigravity_rules() -> CheckResult:
    if not ANTIGRAVITY_RULES.exists():
        return CheckResult(".antigravity/rules.md", False, "파일 없음")
    content = read_text(ANTIGRAVITY_RULES)
    char_count = len(content)
    if char_count > ANTIGRAVITY_CHAR_CAP:
        over = char_count - ANTIGRAVITY_CHAR_CAP
        return CheckResult(".antigravity/rules.md", False, f"{char_count:,}자, 캡 초과 {over:,}자")
    missing = [s for s in ANTIGRAVITY_REQUIRED_SECTIONS if s not in content]
    if missing:
        return CheckResult(".antigravity/rules.md", False, f"핵심 키워드 누락: {missing}")
    margin = ANTIGRAVITY_CHAR_CAP - char_count
    return CheckResult(
        ".antigravity/rules.md", True,
        f"{char_count:,}자 (여유 {margin:,}자), 핵심 섹션 포함",
    )


def check_cursor_references_agents() -> CheckResult:
    if not CURSOR_CORE_RULE.exists():
        return CheckResult(".cursor core rule AGENTS.md 참조", False, "00-core-guidelines.mdc 없음")
    content = read_text(CURSOR_CORE_RULE)
    if "AGENTS.md" in content:
        return CheckResult(".cursor core rule AGENTS.md 참조", True, "AGENTS.md 참조 확인")
    return CheckResult(".cursor core rule AGENTS.md 참조", False, "AGENTS.md 참조 문구 없음")


def check_opencode_json() -> CheckResult:
    if not OPENCODE_JSON.exists():
        return CheckResult("opencode.json instructions", False, "opencode.json 없음")
    try:
        data = json.loads(read_text(OPENCODE_JSON))
        instructions = data.get("instructions", [])
        has_agents = "AGENTS.md" in instructions
        has_skills = "SKILLS.md" in instructions
        if has_agents and has_skills:
            return CheckResult("opencode.json instructions", True, "AGENTS.md, SKILLS.md 포함")
        missing = []
        if not has_agents:
            missing.append("AGENTS.md")
        if not has_skills:
            missing.append("SKILLS.md")
        return CheckResult("opencode.json instructions", False, f"누락: {missing}")
    except json.JSONDecodeError as e:
        return CheckResult("opencode.json instructions", False, f"JSON 파싱 실패: {e}")


def _dir_trees_equal(dir_a: Path, dir_b: Path) -> tuple[bool, list[str]]:
    diffs: list[str] = []
    if not dir_a.exists() and not dir_b.exists():
        return True, []
    if not dir_a.exists():
        return False, [f"정본 없음: {dir_a}"]
    if not dir_b.exists():
        return False, [f"사본 없음: {dir_b}"]
    deep = filecmp.dircmp(dir_a, dir_b)
    _collect_dircmp_diffs(deep, dir_a, dir_b, diffs)
    return len(diffs) == 0, diffs


def _collect_dircmp_diffs(dc: filecmp.dircmp, root_a: Path, root_b: Path, diffs: list[str]) -> None:
    if dc.left_only:
        diffs.append(f"정본에만: {[str(root_a / n) for n in dc.left_only]}")
    if dc.right_only:
        diffs.append(f"사본에만: {[str(root_b / n) for n in dc.right_only]}")
    if dc.diff_files:
        diffs.append(f"내용 상이: {[str(root_a / n) for n in dc.diff_files]}")
    for sub_name, sub_dc in dc.subdirs.items():
        _collect_dircmp_diffs(sub_dc, root_a / sub_name, root_b / sub_name, diffs)


def check_skills_mirror() -> CheckResult:
    equal, diffs = _dir_trees_equal(AGENTS_SKILLS_DIR, CLAUDE_SKILLS_DIR)
    if equal:
        return CheckResult(".agents/skills 와 .claude/skills 미러", True, "내용 완전 일치")
    detail = f"{len(diffs)}건 차이: " + " | ".join(diffs[:3])
    if len(diffs) > 3:
        detail += f" ... 외 {len(diffs) - 3}건"
    return CheckResult(".agents/skills 와 .claude/skills 미러", False, detail)


def check_agents_imports_skills() -> CheckResult:
    content = read_text(AGENTS_MD)
    if "@SKILLS.md" in content:
        return CheckResult("AGENTS.md @SKILLS.md import", True, "import 구문 존재")
    return CheckResult("AGENTS.md @SKILLS.md import", False, "@SKILLS.md 구문 없음")


def run_all_checks(quiet: bool = False) -> int:
    checks: list[CheckResult] = [
        check_claude_is_pointer(),
        check_antigravity_rules(),
        check_cursor_references_agents(),
        check_opencode_json(),
        check_skills_mirror(),
        check_agents_imports_skills(),
    ]
    print("=" * 60)
    print("다중 에이전트 규칙 정합성 검증 (pre-commit)")
    print("=" * 60)
    for chk in checks:
        print(chk.format(quiet=quiet))
    failed = [c for c in checks if not c.ok]
    print("-" * 60)
    if failed:
        print(f"검증 실패: {len(failed)}/{len(checks)} 건. 커밋을 중단합니다.")
        return 1
    print(f"검증 통과: {len(checks)}/{len(checks)} 건.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="다중 에이전트 규칙 정합성 검증 (pre-commit)")
    parser.add_argument("--quiet", action="store_true", help="요약만 출력")
    args = parser.parse_args()
    return run_all_checks(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
```

**pre-commit 훅 (`.git/hooks/pre-commit`):**

```bash
#!/bin/sh
if git diff --cached --name-only | grep -qE '^(AGENTS\.md|CLAUDE\.md|SKILLS\.md|\.antigravity/|\.agents/skills/|\.claude/skills/|\.cursor/|opencode\.json)'; then
    echo "[pre-commit] 다중 에이전트 규칙 정합성 검증..."
    python scripts/validate_agent_rules.py --quiet || exit 1
fi
```

```bash
chmod +x .git/hooks/pre-commit
```

---

## 6. 트리거 방식 정리 (사용자에게 설명할 내용)

| CLI | 호출 방법 | 자동 트리거 | 신뢰도 |
| --- | --- | --- | --- |
| Claude Code | `/project:스킬명` (예: `/project:retraining-pipeline`) | description 매칭 | 낮음 (불안정) |
| opencode | 자연어 "retraining 스킬 사용" 또는 폴더 참조 | 폴더명 + description 매칭 | 중간 |
| Cursor | 해당 `globs` 경로 작업 시 `.mdc` 자동 첨부 | `globs` 매칭 | 중간-높음 |
| Codex | AGENTS.md의 스킬 인덱스 참조 지시 | - | 수동 |
| Antigravity | `.antigravity/rules.md`의 스킬 인덱스 참조 | - | 수동 |

> **중요**: 자동 트리거는 CLI마다 신뢰도가 다릅니다. 가장 신뢰할 수 있는 방법은 명시적 수동 호출입니다.

---

## 7. 비협상 원칙 (스킬 작성 시 반드시 준수)

이 원칙들은 `AGENTS.md`에 정의되어 있으며, 스킬 내용과 충돌해서는 안 됩니다.

1. **데이터 무손실**: 기존 DB 테이블/컬럼명·타입 변경 금지.
2. **Train/Serve 특징 단일화**: 특징 생성은 `src/ml/features.py` 단일 함수만 사용. 하드코딩 상수(`DEFAULT_INST_RATE` 등) 제거.
3. **크로스 플랫폼**: macOS/Windows Docker + Makefile 동일 환경.
4. **시크릿 비기록**: `.env` 실제 값은 문서/코드에 노출 금지.
5. **한국어 존댓말, 이모지 금지**: 모든 스킬 문서에 적용.
6. **규칙 단일 진실 원천**: 코딩 규칙은 AGENTS.md에서만, 스킬에는 복사하지 않음 (참조만).

---

## 8. 작업 재개 절차

1. **본 인수인계 문서를 처음부터 끝까지 읽습니다.** (외부 파일 참조 없음, 자급자족형)
2. `AGENTS.md`, `SKILLS.md`를 읽습니다. (자동 로드됨)
3. `docs/design/REFACTORING_DESIGN.md` (특히 7장 재학습, 8장 로드맵)를 읽습니다.
4. `docs/ops/multi_agent_setup.md`를 읽습니다.
5. §3의 작업 1~7을 순서대로 실행합니다. §4의 템플릿과 §5의 스크립트를 그대로 사용합니다.
6. 각 작업 완료 후 커밋합니다.

> **외부 프로젝트(Minchodan)를 참조할 필요가 없습니다.** 본 문서에 모든 템플릿과 스크립트가 포함되어 있습니다. 외부 디렉토리 접근은 워크스페이스 격리 권한 훅에 의해 차단됩니다.

---

## 9. 트러블슈팅 / 주의사항

| 이슈 | 대응 |
| --- | --- |
| "Tool call denied by pre-tool hook" | 워크스페이스 외부 파일 접근 시도. 본 문서는 자급자족형이므로 외부 접근 불필요. |
| 12,000자 캡 (Antigravity) | `.antigravity/rules.md`는 핵심만 압축. 정본은 AGENTS.md. |
| 스킬 미러 동기화 | `.agents/skills/` 수정 시 반드시 `.claude/skills/`에도 반영. 검증 스크립트로 확인. |
| 자동 트리거 불안정 | 사용자에게 수동 호출(`/스킬명`) 권장 안내. |
| 토큰 부족 | 8개 스킬을 한 번에 다 만들지 말고, **Phase 5(retraining-pipeline)를 최우선**으로 구축 후 점진적 추가. |

---

## 10. 완료 기준 (Definition of Done)

- [ ] `.agents/skills/` 에 8개 스킬 생성 (각 SKILL.md + 선택 references/)
- [ ] `.claude/skills/` 에 동일 8개 스킬 미러
- [ ] `.cursor/rules/` 에 8개 `.mdc` 파일 (00-core 제외)
- [ ] `.antigravity/rules.md` 요약본 생성 (12,000자 이하, 핵심 키워드 7개 포함)
- [ ] `.opencode/skills/` 에 8개 스킬
- [ ] `scripts/validate_agent_rules.py` 정합성 검증 스크립트 (§5 그대로 사용)
- [ ] `.git/hooks/pre-commit` 훅 연동
- [ ] `AGENTS.md` 스킬 인덱스 섹션 추가
- [ ] `SKILLS.md` SKILL 인덱스 업데이트
- [ ] `docs/ops/multi_agent_setup.md` 스킬 디렉토리 설명 추가
- [ ] `scripts/validate_agent_rules.py` 실행 시 전체 PASS
- [ ] 모든 커밋 완료 + GitHub 푸시

---

_본 인수인계 문서는 외부 파일 참조 없이 자급자족하도록 작성되었습니다._
