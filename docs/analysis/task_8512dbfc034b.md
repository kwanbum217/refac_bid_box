# Task 8512dbfc034b 분석 및 완료 보고서: 비명령 프롬프트 안전 자동 해제 계층 구축

> **작성일**: 2026-08-30
> **Task ID**: `task_8512dbfc034b`
> **상태**: 완료 (Succeeded)

---

## 1. 개요 및 배경

2026-08-29 워커 운영 세션에서 Antigravity 워커 2대가 CLI 만족도 설문 프롬프트(`How's the CLI experience so far? ... [0] Skip`)에 걸려 진행이 정체되는 문제가 관측되었습니다. 기존 `scripts/orca_auto_approve.py`는 셸 명령 승인 대화창(`Requesting permission for: ... Do you want to proceed?`)만 처리하고 있어 명령이 아닌 대화형 프롬프트를 인식하지 못했습니다.

본 작업에서는 승인 감시기가 작업 결과 및 저장소 상태에 무해한 비명령 프롬프트를 화이트리스트 기반으로 안전하게 자동 해제하도록 확장하고, 위험 확인에 대한 보호 장치와 반복 응답 상한을 구현하였습니다.

---

## 2. 주요 구현 내용

### 2.1 비명령 프롬프트 화이트리스트 계층 (`SAFE_NON_COMMAND_PROMPTS`)
- 셸 명령 승인 경로와 완전히 분리된 비명령 프롬프트 판정 계층(`match_safe_prompt`)을 신설했습니다.
- CLI 만족도 설문(`cli_satisfaction_survey`)을 화이트리스트 상수로 등록하고 `0`(Skip) 전송을 매핑했습니다.
- 각 항목에 전송 키와 안전 사유를 명시하여 무분별한 자동 응답을 원천 차단(fail-closed)했습니다.

### 2.2 위험 프롬프트 보류 및 보호 장치 (`DANGEROUS_PROMPT_PATTERNS`, `check_dangerous_prompt`)
- 파일 삭제, 자격증명/인증 입력, 결제/과금, 원격 반영/배포, 권한 상승 등 되돌리기 어렵거나 외부에 영향을 주는 프롬프트 패턴을 탐지합니다.
- 위험 프롬프트 감지 시 자동 응답을 일절 수행하지 않고 `[보류]` 로그를 남겨 운영자/사람의 판단에 위임합니다.

### 2.3 반복 응답 상한 (`MAX_PROMPT_REPEATS`)
- 동일 비명령 프롬프트가 지속 노출될 때 무한 루프로 입력을 전송하지 않도록 `MAX_PROMPT_REPEATS = 3` 상한을 적용했습니다.
- 3회 초과 시 자동 응답을 중단하고 `[경고] ... (사람 개입 필요)` 신호를 로그에 출력합니다.

---

## 3. 검증 결과

| 검증 항목 | 명령어 | 결과 |
| --- | --- | --- |
| 단위 및 회귀 테스트 | `uv run pytest tests/test_orca_auto_approve.py tests/test_orca_auto_approve_attach.py -q` | 191 passed |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m "not data_assets"` | 2642 passed, 6 skipped |
| 린터 검사 | `uv run ruff check src/ scripts/ tests/` | All checks passed |
| 다중 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 12/12 passed |

---

## 4. 변경 파일 목록

- `scripts/orca_auto_approve.py`: 비명령 프롬프트 화이트리스트, 위험 프롬프트 탐지, 반복 상한 및 자동 해제 루프 추가
- `tests/test_orca_auto_approve.py`: 비명령 프롬프트 인식, 위험 프롬프트 보류, 반복 상한 단위/회귀 테스트 추가
- `docs/analysis/task_8512dbfc034b.md`: 작업 완료 및 검증 분석 보고서
