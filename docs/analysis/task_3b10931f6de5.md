# Windows CI Pytest 중단 원인 격리 및 대기 제거 분석 보고서

> **작성일**: 2026-09-01
> **Task ID**: `task_3b10931f6de5` (Capsule: `task_u1_windows_ci_hang`)
> **대상 파일**: `scripts/orca_taskctl.py`, `tests/test_orca_taskctl.py`
> **상태**: 완료 (Completed)

---

## 1. 개요 및 문제 정의

GitHub Actions 의 Windows CI 환경(Test `windows-latest, py3.11` job)에서 전체 테스트 2,076건 통과 후 `scripts/orca_taskctl.py:1464` (`time.sleep(max(0.2, poll_seconds))`)에서 `KeyboardInterrupt`로 비정상 중단되는 현상이 발생했습니다.

동일한 테스트 스위트가 Linux(Ubuntu) 및 macOS 에서는 통과하지만 Windows 환경에서만 타임아웃/시그널 인터럽트로 실패하는 원인을 격리하고, 단위 테스트가 실제 벽시계(wall-clock) 대기 시간을 소비하지 않도록 개선하는 것이 본 과업의 목표입니다. 운영 환경의 지시 도달 사후 검증(`verify_instruction_delivered`)의 fail-closed 불변식(`unreadable`, `not_observed`, `delivered`)은 그대로 보존합니다.

---

## 2. 근본 원인 분석 (Root Cause Analysis)

### 2.1 단위 테스트 내 실제 폴링 대기 누적 (120초 이상 소비)

`tests/test_orca_taskctl.py` 의 테스트 실행 시간을 프로파일링(`--durations=20`)한 결과, 아래 4개 단위 테스트가 각각 **30초 이상** 소모하고 있었습니다.

| 테스트 함수명 | 소요 시간 (수정 전) | 원인 |
| --- | :---: | --- |
| `test_dispatch_calls_auto_approve_and_mode_switch_on_antigravity` | **30.48s** | `verify_instruction_delivered` 미모킹으로 30초 대기 |
| `test_dispatch_skips_mode_switch_on_cursor_terminal` | **30.18s** | `verify_instruction_delivered` 미모킹으로 30초 대기 |
| `test_dispatch_suppresses_mode_switch_when_env_disabled` | **30.17s** | `verify_instruction_delivered` 미모킹으로 30초 대기 |
| `test_dispatch_skips_mode_switch_on_unrecognized_terminal` | **30.17s** | `verify_instruction_delivered` 미모킹으로 30초 대기 |

이 4개 테스트에서 `cmd_dispatch` 실행 시 고지문 전송(`_deliver_capsule_notice`) 후 생성된 `probe` 문자열에 대해 사후 도달 검증(`verify_instruction_delivered`)이 기본값 `wait_seconds=30`으로 호출되었습니다. 모의 터미널 화면에는 해당 probe 가 없었기 때문에 매 테스트마다 1초 간격(`poll_seconds=1.0`)으로 30회 `time.sleep`을 수행하며 30초를 온전히 소비했습니다.

4개 테스트만으로 **120.9초**가 낭비되었으며, 리소스가 제한적인 Windows CI 가상머신(2 vCPU)에서 전체 테스트 실행 시간이 342초를 초과하여 CI 러너 타임아웃 또는 외부 인터럽트(`KeyboardInterrupt`)가 발생했습니다. 인터럽트가 발생한 순간 프로세스가 실행 중이던 지점이 `verify_instruction_delivered` 내부의 `time.sleep(max(0.2, poll_seconds))` (1464행)이었던 것입니다.

### 2.2 `wait_seconds <= 0` 경로의 무지연 보장 필요성

`verify_instruction_delivered` 함수는 `wait_seconds=0` 지정 시 1회 관찰 후 즉시 빠져나가야 하나, Windows 플랫폼의 `time.monotonic()` 해상도(약 15.6ms) 특성 및 루프 조건문 구조에 따라 혹시라도 첫 회차에 탈출 조건을 만족하지 못하면 sleep 을 탈 위험이 있었습니다. 따라서 `wait_seconds <= 0`인 경우 루프 내에서 sleep 을 전혀 호출하지 않고 즉시 결과를 반환하도록 명시적인 탈출 가드가 필요했습니다.

---

## 3. 해결 방안 및 구현 내용 (Resolution Details)

### 3.1 `verify_instruction_delivered` 함수 개선 (`scripts/orca_taskctl.py`)

1. **시간 및 슬립 함수 주입성 지원**: 키워드 전용 인자 `_time_monotonic: Any = None`, `_time_sleep: Any = None`을 추가하여 테스트에서 실제 지연 없이 가상 클록 및 가상 슬립을 주입할 수 있도록 개선했습니다. 인자가 주어지지 않은 운영 환경에서는 기존과 동일하게 `time.monotonic`과 `time.sleep`을 동적으로 호출합니다.
2. **`wait_seconds <= 0` 시 sleep 미호출 보장**: `if wait_seconds <= 0 or get_time() >= deadline:` 조건을 두어, 즉시 검사 모드(`wait_seconds <= 0`)에서는 1회 판정 후 sleep 없이 결과를 즉시 반환하도록 확정했습니다.
3. **fail-closed 원칙 유지**: 지시 도달 확인 실패 시 `unreadable` (화면 읽기 불가) 및 `not_observed` (화면은 읽었으나 표지 미발견) 반환 체계를 100% 보존했습니다.

```python
def verify_instruction_delivered(
    handle: str,
    markers: list[str],
    timeout: int = 30,
    wait_seconds: int = 30,
    poll_seconds: float = 1.0,
    *,
    _time_monotonic: Any = None,
    _time_sleep: Any = None,
) -> str:
    get_time = _time_monotonic if _time_monotonic is not None else time.monotonic
    sleep_fn = _time_sleep if _time_sleep is not None else time.sleep
    deadline = get_time() + max(0, wait_seconds)
    unreadable_only = True
    while True:
        text = terminal_tail(handle, timeout=timeout)
        if text is not None:
            unreadable_only = False
            if instruction_observed(text, markers):
                return "delivered"
        if wait_seconds <= 0 or get_time() >= deadline:
            return "unreadable" if unreadable_only else "not_observed"
        sleep_fn(max(0.2, poll_seconds))
```

### 3.2 단위 테스트 개선 및 회귀 테스트 추가 (`tests/test_orca_taskctl.py`)

1. **`verify_instruction_delivered` 미모킹 테스트 보완**: 모드 전환 및 자동 승인을 검증하는 5개 dispatch 테스트에 `verify_instruction_delivered` 모킹(`lambda *a, **k: "delivered"`)을 추가하여 불필요한 30초 대기를 제거했습니다.
2. **기타 대기 경로 모킹**: `enable_file_edit_auto_approve` 및 `dispatch_with_fallback` 관련 단위 테스트에 `time.sleep` 모킹을 적용하여 잔여 대기 시간을 제거했습니다.
3. **회귀 테스트 2종 추가**:
   - `test_verify_instruction_delivered_wait_zero_never_calls_sleep`: `wait_seconds=0` 일 때 `unreadable`, `not_observed`, `delivered` 전 경로에서 `time.sleep`이 0회 호출됨을 단정.
   - `test_verify_instruction_delivered_injected_clock_and_sleep`: 가상 클록과 가상 슬립 함수 주입을 통한 폴링 및 데드라인 도달 로직 검증.

---

## 4. 기각한 대안 (Rejected Alternatives)

| 기각된 대안 | 기각 사유 |
| --- | --- |
| 운영 환경의 `wait_seconds` 기본값 축소 (예: 30초 -> 2초) | 워커 CLI 기동 및 프롬프트 준비 시간 편차로 인해 정상 기동 중인 워커에 대해 지시 미도달 오탐이 발생할 위험이 있습니다 (반복 금지 원칙). |
| 도달 미확인 시 기본값을 `delivered`로 완화 (fail-open) | 신뢰 대화창이나 CLI 정체로 인해 지시가 유실되었음에도 성공으로 오판하는 치명적 제어 평면 결함을 유발하므로 기각합니다 (불변식 위반). |
| Windows CI 에서 `test_orca_taskctl.py` 제외 | 크로스 플랫폼 표준 검증(G2) 원칙에 위배되며, 플랫폼 독립적 코드의 정합성을 지속 검증해야 하므로 기각합니다. |

---

## 5. 검증 결과 (Verification Results)

### 5.1 `tests/test_orca_taskctl.py` 실행 성능

- 수정 전: 187 passed in **126.84s** (2분 6초)
- 수정 후: 189 passed in **1.58s** (**약 80배 단축**)

### 5.2 전체 테스트 스위트 및 규칙 검증

| 검증 명령 | 결과 | 상세 |
| --- | :---: | --- |
| `uv run pytest tests/test_orca_taskctl.py -q` | **통과** | 189 passed in 1.58s |
| `uv run pytest tests/ -q -m "not data_assets"` | **통과** | 3,013 passed, 15 skipped, 3 deselected in 109.15s |
| `python3 scripts/validate_agent_rules.py --quiet` | **통과** | 16/16 규칙 검증 통과 |

---

## 6. 결론

Windows CI 에서 발생했던 pytest `KeyboardInterrupt` 현상의 근본 원인이 단위 테스트 내 `verify_instruction_delivered` 미모킹으로 인한 120초 이상의 폴링 sleep 누적이었음을 규명하고, 함수 내 무지연 탈출 가드 추가 및 테스트 모킹/가상 클록 주입을 통해 전체 189개 테스트가 1.58초 만에 완료되도록 최적화했습니다. 운영 경로의 fail-closed 불변식은 완전히 보존되었습니다.
