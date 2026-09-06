# 게이트 3 pytest 실패 노드 단독 재시도 변경 기록

> **작성일**: 2026-09-06
> **작업 ID**: `task_217271924829`
> **대상**: `scripts/orca_level1_gate.py`, `tests/test_orca_level1_gate.py`
> **검증 결과**: `tests/test_orca_level1_gate.py` 45건 통과, 규칙 검증 20/20 통과

---

## 1. 배경

2026-09-06 Wave AA~AD에서 게이트가 테스트 실패를 네 번 보고했고 네 번 모두 단독 재실행에서 통과했습니다. 원인은 워커와 리뷰어와 게이트가 같은 머신에서 전량 스위트를 겹쳐 돌린 부하 오탐입니다. 게이트 3은 첫 실패를 최종 실패로 바로 처리했고 단독 재시도 분기가 없었습니다.

## 2. 변경 내용

| 파일 | 변경 |
| --- | --- |
| `scripts/orca_level1_gate.py` | `build_pytest_retry_argv` 추가, `run_gate3_tests`에 실패 노드 1회 단독 재실행 분기 추가 |
| `tests/test_orca_level1_gate.py` | 재시도 관련 회귀 4건 추가 |
| `docs/analysis/task_af1_gate_retry.md` | 본 변경 요약과 재시도 조건 기록 |

재실행이 전부 통과하면 게이트 3은 통과하고 요약에 오탐 건수를 명시합니다. 재실행이 하나라도 실패하면 실패를 유지합니다. 첫 실행 실패는 `raw_data`의 `first_run`에 그대로 남고 재시도 결과는 `retry`에 남습니다.

## 3. 재시도 조건

| 조건 | 동작 |
| --- | --- |
| pytest 명령이 실패하고 `failed_nodes`가 있을 때 | `uv run pytest <node>... -q`로 노드만 1회 재실행 |
| `failed_nodes`가 비어 있을 때 | 재시도 없이 기존처럼 실패 |
| pytest가 아닌 검증 명령(`npm`, `mypy`, `docker`, `actionlint` 등) | 재시도하지 않음 |
| 통과한 명령 | 다시 돌리지 않음 |
| 재시도 횟수 | 실패한 노드 대상 최대 1회, 원 명령 전량 재실행 금지 |
| 게이트 6 테스트 건수 대조 | 완화하지 않음, 본 Task는 게이트 3 실행 루프만 수정 |

## 4. 검증 결과

| 검증 항목 | 명령어 | 결과 |
| --- | --- | --- |
| 게이트 회귀 테스트 | `uv run pytest tests/test_orca_level1_gate.py -q` | 통과 |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
| 린터 | `uv run ruff check scripts/orca_level1_gate.py tests/test_orca_level1_gate.py` | 통과 |
