# Orca v2 Runtime Smoke & Agent Bootstrap Cost Measurement Report

> **작성일자**: 2026-08-15  
> **태스크 ID**: `task_e1378cb91479` (T6)  
> **실행 런**: `run_35e59701b435`  
> **역할**: Builder  
> **관련 문서**: 설계 23장 성공 지표, `docs/ops/orca_task_capsule_v2.md`

---

## 1. 개요 및 목적

Orca v2는 에이전트 자동 주입 문서를 `AGENTS.md` 단일 정본과 얇은 진입점(thin pointer) 구조로 전면 축소했습니다.
본 보고서는 설계 23장에서 요구하는 **성공 지표의 proxy 메트릭(문자 수, Character Count)**을 측정하는 신규 도구 `scripts/measure_agent_bootstrap_cost.py`의 구현 및 5대 CLI 진입점별 부트스트랩 비용 실측 결과를 기록합니다.

---

## 2. 5대 CLI 진입점별 부트스트랩 비용 실측 결과

### 2.1 실측 요약 표

`uv run python scripts/measure_agent_bootstrap_cost.py` 실행 결과:

```
==================================================================================
에이전트 부트스트랩 비용 측정 (설계 23장 Proxy 지표: 문자 수 기준)
==================================================================================
CLI            자동 로드 문서 경로                            문자 수       예산      사용률     상태
----------------------------------------------------------------------------------
Codex          AGENTS.md                             6,589    8,000    82.4%   PASS
opencode       AGENTS.md (via opencode.json)         6,589    8,000    82.4%   PASS
Antigravity    .antigravity/rules.md                 3,921   12,000    32.7%   PASS
Claude Code    CLAUDE.md                                46    8,000     0.6%   PASS
Cursor         .cursor/rules/ (13개 파일)               6,740   12,000    56.2%   PASS
----------------------------------------------------------------------------------
총 5개 CLI 진입점 측정 완료 (모두 예산 이내).
==================================================================================
```

### 2.2 JSON 포맷 출력 검증 (`--json`)

`uv run python scripts/measure_agent_bootstrap_cost.py --json` 실행 결과:

```json
{
  "schema": "ORCA_BOOTSTRAP_COST_REPORT_V1",
  "version": "1.0.0",
  "timestamp": "2026-08-14T16:40:07.451430+00:00",
  "total_clis": 5,
  "all_within_budget": true,
  "total_chars_across_clis": 23885,
  "max_char_cli": "Cursor",
  "max_char_count": 6740,
  "entries": [
    {
      "cli": "Codex",
      "description": "AGENTS.md 단일 정본",
      "paths": [
        "AGENTS.md"
      ],
      "display_path": "AGENTS.md",
      "exists": true,
      "char_count": 6589,
      "budget": 8000,
      "ratio": 0.8236,
      "ratio_pct": 82.36,
      "within_budget": true,
      "status": "PASS"
    },
    {
      "cli": "opencode",
      "description": "opencode.json instructions 자동 주입",
      "paths": [
        "AGENTS.md"
      ],
      "config_path": "opencode.json",
      "display_path": "AGENTS.md (via opencode.json)",
      "exists": true,
      "char_count": 6589,
      "budget": 8000,
      "ratio": 0.8236,
      "ratio_pct": 82.36,
      "within_budget": true,
      "status": "PASS"
    },
    {
      "cli": "Antigravity",
      "description": ".antigravity/rules.md 자동 주입",
      "paths": [
        ".antigravity/rules.md"
      ],
      "display_path": ".antigravity/rules.md",
      "exists": true,
      "char_count": 3921,
      "budget": 12000,
      "ratio": 0.3267,
      "ratio_pct": 32.67,
      "within_budget": true,
      "status": "PASS"
    },
    {
      "cli": "Claude Code",
      "description": "CLAUDE.md thin pointer",
      "paths": [
        "CLAUDE.md"
      ],
      "display_path": "CLAUDE.md",
      "exists": true,
      "char_count": 46,
      "budget": 8000,
      "ratio": 0.0057,
      "ratio_pct": 0.57,
      "within_budget": true,
      "status": "PASS"
    },
    {
      "cli": "Cursor",
      "description": ".cursor/rules/ 규칙 세트",
      "paths": [
        ".cursor/rules/00-core-guidelines.mdc",
        ".cursor/rules/01-foundation-setup.mdc",
        ".cursor/rules/02-data-preservation.mdc",
        ".cursor/rules/03-infrastructure-setup.mdc",
        ".cursor/rules/04-application-migration.mdc",
        ".cursor/rules/05-inference-rag-opt.mdc",
        ".cursor/rules/06-retraining-pipeline.mdc",
        ".cursor/rules/07-frontend-streaming.mdc",
        ".cursor/rules/08-validation-cutover.mdc",
        ".cursor/rules/09-git-workflow.mdc",
        ".cursor/rules/10-orca-section-coordination.mdc",
        ".cursor/rules/10-project-orchestrator.mdc",
        ".cursor/rules/11-servc-model-tuning.mdc"
      ],
      "display_path": ".cursor/rules/ (13개 파일)",
      "exists": true,
      "char_count": 6740,
      "budget": 12000,
      "ratio": 0.5617,
      "ratio_pct": 56.17,
      "within_budget": true,
      "status": "PASS"
    }
  ]
}
```

---

## 3. 분석 및 시사점

1. **단일 진실 원천 유지 (`AGENTS.md`)**:
   - `Codex` 및 `opencode` 진입점 모두 `AGENTS.md` 6,589자를 자동 로드하여 예산(8,000자) 대비 82.4% 수준에서 안정적으로 관리되고 있습니다.
2. **초경량 진입점 (`CLAUDE.md`)**:
   - `CLAUDE.md`는 정본 내용을 중복 복사하지 않고 `@AGENTS.md` import 포인터만 유지하여 단 46자(예산의 0.6%)만 소비합니다.
3. **요약본 규칙 관리 (`Antigravity`, `Cursor`)**:
   - `.antigravity/rules.md`는 3,921자(예산 12,000자 대비 32.7%)로 컴팩트하게 축약되어 있습니다.
   - Cursor 전용 13개 규칙 파일은 총 6,740자(예산 12,000자 대비 56.2%)로 유지되어 각 CLI 부트스트랩 비용이 모두 상한선 이내입니다.
4. **문자 수(Proxy 지표) 계산 정확도**:
   - UTF-8 인코딩 바이트 수가 아닌 파이썬 `len()` 기반 문자 수로 산출하여 언어별 바이트 가중치 왜곡 없이 설계 기준과 일치하도록 구현되었습니다.

---

## 4. 검증 결과 요약

| 검증 명령 | 결과 | 상세 |
|:---|:---:|:---|
| `uv run python scripts/measure_agent_bootstrap_cost.py` | PASS | 5개 CLI 진입점 표 출력 완료 (모두 예산 이내) |
| `uv run python scripts/measure_agent_bootstrap_cost.py --json` | PASS | `ORCA_BOOTSTRAP_COST_REPORT_V1` JSON 스키마 준수 출력 |
| `uv run pytest tests/test_measure_agent_bootstrap_cost.py -q` | PASS | 7개 단위 테스트 전량 통과 (100%) |
| `uv run pytest tests/test_validate_agent_rules.py -q` | PASS | 19개 단위 테스트 전량 통과 (100%) |
| `uv run ruff check scripts tests` | PASS | 코드 스타일 및 린트 검사 통과 (All checks passed) |
| `uv run python scripts/validate_agent_rules.py` | PASS | 다중 에이전트 규칙 정합성 검증 12/12 항목 통과 |

---

## 코디네이터 검증 (T6 실행 검증 판정)

> **검증일**: 2026-08-15
> **검증자**: 코디네이터 (Claude Opus 5)
> **판정**: **설계 20장 완료 기준 10번 충족.** Capsule -> worker_done 흐름이 실제 워커에서 확인됐습니다
> **의의**: 기존 T6 보고서([`orca_v2_cross_cli_validation_20260815.md`](orca_v2_cross_cli_validation_20260815.md))는 **정적 검증**이었고 이 절이 그 공백을 메웁니다

### V.1 왜 실행 검증이 따로 필요했는가

기존 T6 보고서는 자신의 범위를 "진입점 파일 및 설정의 정적 정합성" 으로 명시합니다.
설정이 완벽해도 지시가 워커에 도달하지 않는 실패가 실재하므로 정적 검증으로는
설계 20장 10번을 충족할 수 없습니다.

2026-08-14 세션에서 `dispatch --inject` 가 `ok: true` 를 반환하고 Task 가
`dispatched` 로 바뀌었는데 워커 3대가 6분간 빈 프롬프트였습니다. **설정 정합성은
그때도 통과 상태였습니다.**

### V.2 실행 조건

| 항목 | 값 |
| --- | --- |
| Task | `task_e1378cb91479` |
| 워크트리 | `orca worktree create` 로 생성한 `t6-runtime-smoke` |
| 워커 | Antigravity `gemini-3.7-flash-high` |
| 전달 방식 | `agy --model <id> -i "<Capsule 경로 지시>"` (인자 주입) |
| Capsule 크기 | **2,941자** (설계 5장 일반 Capsule 예산 4,000자 이내) |

### V.3 Capsule 격리가 실제로 작동했습니다

**이것이 이번 검증의 핵심 결과입니다.** Capsule 의 `allowed_read_files` 4개와
워커가 실제로 읽은 파일이 정확히 일치했습니다.

| Capsule `allowed_read_files` | 실제 Read 호출 |
| --- | --- |
| `scripts/validate_agent_rules.py` | 있음 |
| `tests/test_validate_agent_rules.py` | 있음 |
| `opencode.json` | 있음 |
| `CLAUDE.md` | 있음 |

금지 문서 재독은 **0건**입니다.

```
Read( ... README.md | SKILLS.md | REFACTORING_DESIGN.md | AGENTS.md | handoff )  ->  0회
```

근거는 워커의 자기 보고가 아니라 **코디네이터가 터미널 출력에서 직접 센 `Read()`
호출**입니다. 워커 보고를 판정 근거로 쓰지 않는 원칙을 이 검증에도 적용했습니다.

### V.4 acceptance 독립 재검산

Capsule 의 acceptance 6개를 코디네이터가 직접 재실행했습니다.

| 조건 | 결과 |
| --- | --- |
| 5개 CLI 행 출력 | 통과. Codex/opencode/Antigravity/Claude Code/Cursor |
| `--json` 유효성 | 통과. `schema`, `all_within_budget` 등 키 확인 |
| 단위 테스트 | **7 passed** (요구 최소 4개) |
| `ruff check scripts tests` | 통과 |
| `validate_agent_rules` | **12/12** |
| 문자 수 기준 (바이트 아님) | 통과. AGENTS.md 6,589자로 일치 |

### V.5 부트스트랩 비용 최초 실측

이 smoke 가 만든 도구로 §23 proxy 지표의 첫 값을 얻었습니다.

| CLI | 자동 로드 문서 | 문자 수 | 예산 | 사용률 |
| --- | --- | ---: | ---: | ---: |
| Codex | `AGENTS.md` | 6,589 | 8,000 | 82.4% |
| opencode | `AGENTS.md` (via `opencode.json`) | 6,589 | 8,000 | 82.4% |
| Antigravity | `.antigravity/rules.md` | 3,921 | 12,000 | 32.7% |
| Claude Code | `CLAUDE.md` | 46 | 8,000 | 0.6% |
| Cursor | `.cursor/rules/` (13개) | 6,740 | 12,000 | 56.2% |

5개 진입점 전부 예산 이내입니다. **이 값이 v2 이후 기준선입니다.**

### V.6 발견 — `agy -i` 도 신뢰 대화창 뒤에서 대기합니다

**어제 기록을 부분 정정합니다.** `agy -i` 를 "프롬프트가 프로세스 인자라 유실
지점이 없는 권장 경로" 로 적었는데, 유실되지는 않지만 **워크스페이스 신뢰 확인
대화창이 승인되기 전까지 실행이 시작되지 않습니다.**

```
Do you trust the contents of this project?
> Yes, I trust this folder
  No, exit
```

`orca worktree create` 로 만든 새 경로는 이 대화창을 반드시 띄웁니다. 엔터 1회
승인 후 즉시 진행했습니다.

| 경로 | 대화창 영향 |
| --- | --- |
| `dispatch --inject` | 키 입력이 대화창에 먹혀 **유실** |
| `agy -i "<프롬프트>"` | 유실 없음. 다만 **승인까지 대기** |

따라서 기동 절차는 **"띄운다 -> 신뢰 승인 엔터 -> `terminal read` 로 진행 확인"**
세 단계이며, 두 번째를 빼면 워커가 유휴로 보입니다.

### V.7 남은 것

설계 20장 10번은 충족됐습니다. **다만 CLI 1종(Antigravity)에서만 확인했습니다.**
설계 17장 T6 은 "가능한 CLI 에서 1회씩" 을 요구하므로 OpenCode 계열 1종 추가
확인이 남습니다. 무료 풀은 임계 경로가 아니므로 우선순위는 낮습니다.

§23 성공 지표의 전후 비교는 **before 데이터를 이제 확보할 수 없습니다.** v2 이전
상태로 되돌려 재측정하는 비용이 크므로, V.5 를 v2 이후 기준선으로 두고 이후 Task
계측을 누적하는 방식이 현실적입니다.
