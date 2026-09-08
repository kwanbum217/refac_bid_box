# 런처 테스트의 실제 분리 프로세스 생성 부작용 제거 (task_82b9a808dc6a)

> **작업**: 런처 테스트(`tests/test_orca_agy_launch.py`, `tests/test_orca_kimi_launch.py`) 실행 시 실제 분리 프로세스가 뜨는 부작용을 제거하고, 기계로 강제하는 회귀 테스트 및 안전망을 구축한다.
> **배경**: 2026-09-07 세션 종료 점검에서 `orca_agy_launch.py --setup-permissions` 형태의 분리 프로세스 18개가 코디네이터 터미널 핸들을 들고 백그라운드에 살아 있는 것이 발견되었다. 테스트 실행만으로 실제 자식 프로세스가 `start_new_session=True` 로 분리 기동되는 결함이다.
> **판정**: `tests/conftest.py` 에 전역 기본 안전망을 추가하고, `tests/test_orca_agy_launch.py` 및 `tests/test_orca_kimi_launch.py` 에 파일별 `autouse` 안전망 픽스처와 `subprocess.Popen` 미호출 단언 회귀 테스트를 배치했다. `tests/test_orca_worker_launch_common.py` 에도 기본 `spawn_fn` 경로의 안전망 동작 단언 회귀 테스트를 추가했다. 운영 코드(`scripts/`)는 일체 수정하지 않았다.

---

## 1. 원인 분석

| 항목 | 내용 |
| --- | --- |
| 증상 | 테스트 실행 시 `scripts/orca_agy_launch.py --setup-permissions <handle> <model>` 및 `scripts/orca_kimi_launch.py --setup-permissions <handle> <model>` 프로세스가 다수 백그라운드에 잔류 |
| 원인 경로 1 | `scripts/orca_agy_launch.py` 의 `main()` 은 `os.execvpe` 직전에 `common.schedule_permission_setup(...)` 을 호출한다. `ORCA_TERMINAL_HANDLE` 환경변수가 존재하면 `spawn_permission_setup(term, model)` 을 부르고, 이는 기본 `popen=subprocess.Popen` 으로 분리 세션(`start_new_session=True`) 자식을 띄운다. `test_orca_agy_launch.py` 의 기존 테스트 8곳이 `main()` 을 호출하면서 `mod.os.execvpe` 만 패치하고 `spawn_permission_setup` 은 패치하지 않았다. |
| 원인 경로 2 | `scripts/orca_kimi_launch.py` 의 `main()` 도 `schedule_permission_setup(...)` 을 호출한다. `test_orca_kimi_launch.py` 에서 `test_kimi_launcher_schedules_permission_setup` 1곳만 `spawn_permission_setup` 을 패치했고, `main()` 을 호출하는 다른 8개 테스트는 패치하지 않아 프로세스를 그대로 띄웠다. |
| 실측 baseline | 시정 전 `ORCA_TERMINAL_HANDLE=term_PROBE_AM1` 로 대상 테스트 실행 시 `pgrep -fl 'setup-permissions term_PROBE_AM1'` 에 14개 실제 분리 프로세스가 기동됨을 확인했다 (AGY 6개, Kimi 8개). |

---

## 2. 해결 및 안전망 설계

### 2.1 3계층 안전망 구조

```
+-------------------------------------------------------------------------+
| 계층 1: tests/conftest.py (전역 autouse 픽스처)                         |
|   - scripts.orca_worker_launch_common.spawn_permission_setup 을 대역화  |
|   - popen is subprocess.Popen 인 경우 실제 프로세스 생성을 차단         |
|   - schedule_permission_setup.__kwdefaults__['spawn_fn'] 안전 대역 바인딩 |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| 계층 2: tests/test_orca_agy_launch.py & test_orca_kimi_launch.py        |
|   - 각 파일 단위 autouse 픽스처 (_guard_agy_..., _guard_kimi_...) 배치  |
|   - 파일 단독 실행 시에도 기본적으로 권한 설정 프로세스 생성 완전 차단  |
|   - 명시적 popen 대역이나 관찰용 lambda 주입 시 정상 동작 보존          |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| 계층 3: 회귀 테스트 (기계적 강제)                                       |
|   - subprocess.Popen 이 호출되지 않았음을 직접 단언                      |
|   - test_main_never_calls_popen_for_permission_setup (AGY)              |
|   - test_main_never_calls_popen_for_permission_setup (KIMI)             |
|   - test_schedule_permission_setup_default_spawn_never_calls_popen      |
+-------------------------------------------------------------------------+
```

### 2.2 운영 동작 및 기존 검증 계약 보존

1. **운영 코드 무수정**: `scripts/` 아래의 코드는 단 한 줄도 수정하지 않았다. 실제 워커 기동 시의 권한 설정 예약 동작은 그대로 유지된다.
2. **명시적 대역 전달 지원**: `test_spawn_permission_setup_detaches_child_session` 및 `test_launcher_schedules_permission_setup` 처럼 테스트가 명시적으로 `popen=fake_popen` 을 넘기는 경우, `safe_spawn` 은 원본 로직을 호출하여 `start_new_session=True` 등 인자 계약 검증을 그대로 수행한다.
3. **명시적 spawn_fn 대역 지원**: `test_kimi_launcher_schedules_permission_setup` 처럼 테스트 함수 내에서 `monkeypatch.setattr("scripts.orca_kimi_launch.spawn_permission_setup", ...)` 로 관찰용 대역을 끼우는 경우, pytest 의 LIFO 특성상 해당 테스트의 monkeypatch 가 우선 적용되어 기존 테스트가 통과한다.

---

## 3. 검증 결과

### 3.1 실측 검증 표

| 검증 단계 | 명령 | 결과 |
| --- | --- | --- |
| 1. 잔류 프로세스 부재 확인 | `ORCA_TERMINAL_HANDLE=term_PROBE_AM1 uv run pytest tests/test_orca_agy_launch.py tests/test_orca_kimi_launch.py tests/test_orca_worker_launch_common.py -q` 실행 후 `pgrep -fl 'setup-permissions term_PROBE_AM1'` | **프로세스 0건 (pgrep exit code 1, 출력 없음)** |
| 2. 런처 대상 전량 통과 | `uv run pytest tests/test_orca_agy_launch.py tests/test_orca_kimi_launch.py tests/test_orca_worker_launch_common.py -q` | **77 passed in 3.64s** |
| 3. 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | **20/20 통과** |
| 4. 회귀 테스트 단언 | 3개 신규 회귀 테스트에서 `len(popen_called) == 0` 검증 | **전량 통과** |

### 3.2 변경 파일 목록

| 파일 | 변경 요약 |
| --- | --- |
| `tests/conftest.py` | `_disable_orca_auto_approve` 픽스처 확장: `spawn_permission_setup` 대역화 및 기본 `spawn_fn` 안전망 바인딩 |
| `tests/test_orca_agy_launch.py` | `_guard_agy_permission_setup` autouse 픽스처 및 `test_main_never_calls_popen_for_permission_setup` 회귀 테스트 추가 |
| `tests/test_orca_kimi_launch.py` | `_guard_kimi_permission_setup` autouse 픽스처 및 `test_main_never_calls_popen_for_permission_setup` 회귀 테스트 추가 |
| `tests/test_orca_worker_launch_common.py` | `test_schedule_permission_setup_default_spawn_never_calls_popen` 회귀 테스트 추가 |
