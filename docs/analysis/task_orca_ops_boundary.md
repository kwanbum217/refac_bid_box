# Orca 제어 평면 격리 및 신뢰 잠금 경계 개선 보고서

> **작성일**: 2026-08-24
> **작성자**: Antigravity Gemini Flash High (Worker)
> **작업 ID**: `task_de10912b240e`
> **관련 문서**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`docs/ops/orca_task_capsule_v2.md`](../ops/orca_task_capsule_v2.md)

---

## 1. 개요 및 배경

본 작업은 Orca 다중 에이전트 환경에서 발생한 두 가지 핵심 경계 결함을 해결하기 위해 수행되었습니다.

1. **신뢰 잠금(Trust Lock)의 지원 부재 시 Fail-Open 및 Windows 비정상 종료 회귀**:
   - `fcntl` 및 `msvcrt` 가 모두 지원되지 않는 플랫폼에서 경고만 출력하고 임계구역을 잠금 없이 실행하던 fail-open 취약점 제거.
   - Windows CI 환경에서 비정상 종료 회귀 복구 테스트 중 강제 잠금 점유 상태에서 발생하던 `PermissionError` 안정화.
2. **Task Capsule 및 제어 평면 경로의 Worktree 탈출(Containment Breach) 방지**:
   - `scope`, `read_scope`, `report_path`, `capsule_path` 에 절대경로(POSIX, Windows drive/UNC) 또는 상위 디렉터리 탐색(`..`), 홈 디렉터리(`~`)가 주입되어 워커가 작업 트리를 벗어나는 문제 방지.
   - 의도 파싱(`parse_intent`), Capsule 확장(`expand_intent_to_capsule`), 고지문 생성(`build_capsule_notice`), Task spec 생성(`build_task_spec`), 디스패치(`cmd_dispatch`) 전 구간에 걸친 기계적 containment 검증 구현.

---

## 2. 결함 원인 분석 및 해결 방안

### 2.1 신뢰 잠금 Fail-Closed 및 Windows 회귀 분석

| 항목 | 기존 동작 및 문제점 | 개선 내용 |
| --- | --- | --- |
| 잠금 모듈 부재 | `_LOCK_AVAILABLE` 이 `False` 일 때 경고 로그 후 `yield` (Fail-Open) | 명확한 `RuntimeError` 를 발생시키고 임계구역 진입 전 작업 중단 (Fail-Closed) |
| Windows 회귀 테스트 | `_settings_lock()` 컨텍스트 블록 내부에서 `lock_file.read_text()` 를 호출하여 Windows Mandatory Locking 에 의한 `PermissionError` (Errno 13) 발생 | 락 컨텍스트 블록 종료 후 해제된 상태에서 `lock_file` 토큰을 검증하도록 테스트 구조 안정화 |

### 2.2 Worktree Containment 기계적 검증

워크트리 외부로의 경로 유출을 차단하기 위해 `validate_contained_path` 헬퍼 함수를 도입하고 모든 경로 수신부에 적용하였습니다.

| 대상 경로 | 검증 및 차단 기준 | 대응 조치 |
| --- | --- | --- |
| **절대경로** | POSIX `/...`, Windows `C:\...`, `c:/...`, `D:...`, UNC `\\...`, `//...` | `ValueError` 발생 및 CLI 종료 코드 2 반환 |
| **상위 탐색** | `..`, `../...`, `a/../../b` 등 경로 세그먼트 내 `..` 포함 | `ValueError` 발생 및 CLI 종료 코드 2 반환 |
| **홈 디렉터리** | `~/...` | `ValueError` 발생 및 CLI 종료 코드 2 반환 |
| **Capsule 상대경로** | `worktree_relative_capsule_path` 를 통한 `.orca/capsules/...` 표준화 | 워커에 절대경로를 노출하지 않고 상대경로만 전달 |
| **보고서 경로** | 고지문 및 Intent 확장 시 `report_path` 상대경로 강제 | 절대경로 전달 차단 및 worktree-relative 경로 표준화 |

---

## 3. 구현 내역 상세

### 3.1 `scripts/orca_trust_worktree.py`
- `_settings_lock`: `not _LOCK_AVAILABLE` 일 때 즉시 `RuntimeError` 를 발생시켜 임계구역 실행을 방지.

### 3.2 `scripts/orca_taskctl.py`
- `validate_contained_path`: POSIX 및 Windows 경로 객체(`PurePosixPath`, `PureWindowsPath`), UNC, 드라이브 레터, `..` 세그먼트, `~` 접두사를 기계적으로 검사하여 거부.
- `parse_intent`: Intent 파싱 시 `scope`, `read_scope`, `report_path` 에 대해 containment 검증 수행.
- `expand_intent_to_capsule`: Capsule 확장 시 `allowed_read_files`, `allowed_write_files`, `report_path`, `capsule_path` 검증.
- `build_capsule_notice` & `build_task_spec`: 워커 고지문 및 spec 생성 시 Capsule 상대경로 및 `report_path` 검증.
- `cmd_expand`, `cmd_create`, `cmd_dispatch`: 잘못된 경로 입력 시 명확한 에러 메시지와 함께 종료 코드 2 반환.

### 3.3 `tests/test_orca_trust_worktree.py`
- `test_settings_lock_abnormal_termination_recovery`: Windows CI 호환 락 획득 후 토큰 검증 위치 조정.
- `test_settings_lock_fails_closed_when_no_lock_available`: 모듈 monkeypatch 를 통한 fail-closed 동작 검증 테스트 추가.

### 3.4 `tests/test_orca_taskctl.py`
- 기존 절대 `report_path` 기대 테스트를 상대경로 및 거부 계약 테스트로 전환.
- `validate_contained_path` 반례 테스트(POSIX, Windows, UNC, traversal, empty 등) 추가.
- `scope`, `read_scope`, `report_path` 의 비정상 입력에 대한 거부 테스트 추가.
- 정상 상대경로 및 glob 패턴(`src/...`, `tests/**`) 호환성 테스트 추가.
- CLI 서브커맨드(`expand`, `dispatch`)의 비정상 입력에 대한 종료 코드 2 반환 테스트 추가.

---

## 4. 검증 결과

```text
============================== 검증 요약 ==============================
1. 단위 및 제어 평면 테스트 (pytest):
   - tests/test_orca_trust_worktree.py: 10 passed (100%)
   - tests/test_orca_taskctl.py: 130 passed (100%)
2. 전체 회귀 테스트:
   - uv run pytest tests/ -q -m 'not data_assets': 1837 passed, 6 skipped, 0 failed
3. 에이전트 규칙 정합성 검증:
   - python3 scripts/validate_agent_rules.py --quiet: 12/12 PASS
======================================================================
```
