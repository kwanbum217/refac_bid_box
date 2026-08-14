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
