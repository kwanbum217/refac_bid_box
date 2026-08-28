# Task 완료 보고서: task_ac1c2f9da231 (실제 CPU Utilization 계측 도입)

> **Task ID**: `task_ac1c2f9da231`
> **Dispatch ID**: `ctx_c6a204f8ec02`
> **작업 브랜치**: `kwanbum217/t5-cpu-util`
> **작성일**: 2026-08-28

---

## 1. 과업 개요

- **목표**: 벤치마크 리포트에 실제 CPU utilization 계측을 도입하여, 기존 1분 normalized load average 지표와 함께 독립 필드로 기록하고 모니터링 체계를 고도화.
- **제약 조건**:
  - `psutil` 등 신규 외부 의존성 추가 금지 (표준 라이브러리 및 OS 기본 명령만 사용).
  - macOS와 Linux 2개 플랫폼 모두 지원, 미지원 플랫폼(Windows 등) 및 실패 시 None 및 사유 기록으로 Graceful fallback.
  - 기존 필드명(`load_1m`, `normalized_load_1m_percent`, `per_core_percent`) 100% 보존.

---

## 2. 주요 변경 내역

1. **`scripts/benchmark_provenance.py`**:
   - `parse_proc_stat(stat_text)`: Linux `/proc/stat` 내용에서 총 틱과 유휴 틱(`idle + iowait`) 파싱.
   - `read_proc_stat_ticks(proc_stat_path)`: `/proc/stat` 파일 안전 읽기 및 오류 핸들링.
   - `calculate_cpu_utilization_from_ticks(start_ticks, end_ticks)`: 두 시점 틱 차분 기반 CPU utilization(%) 계산 (0.0% ~ 100.0% 클램핑).
   - `measure_macos_cpu_utilization(command_runner, cpu_count)`: macOS `ps -A -o %cpu` 프로세스 점유율 합산 및 코어 수 정규화.
   - `measure_cpu_utilization(...)`: 크로스플랫폼 통합 계측 헬퍼.
   - `single_host_load_sample(...)`: 단일 호스트 부하 및 `cpu_utilization_percent`, `cpu_utilization_unavailable_reason` 스냅샷 수집.
   - `compute_host_load_stats(...)`: 표본 목록으로부터 `cpu_utilization_percent` min/median/max 통계 및 불가 사유 산출.
   - `HostLoadMonitor`: 백그라운드 모니터링 주기 동안 Linux `/proc/stat` 틱 차분 및 macOS 실시간 사용률 자동 수집.

2. **`scripts/benchmark_latency.py`**:
   - 신규 CPU utilization 헬퍼 함수들(`parse_proc_stat`, `read_proc_stat_ticks`, `calculate_cpu_utilization_from_ticks`, `measure_macos_cpu_utilization`, `measure_cpu_utilization`) 재수출 및 `single_host_load_sample` 인자 포워딩.

3. **`tests/test_cpu_utilization_metric.py`**:
   - (a) `/proc/stat` 대역 입력 및 다중 컴포넌트 틱(user, system, iowait, steal 등) 파싱/계산 단위 테스트.
   - (b) 비정상 델타, 누락 파일, 깨진 파일, macOS ps 실패, Windows 미지원 플랫폼에서의 Graceful fallback 및 사유 기록 검증.
   - (c) 기존 `load_1m`, `normalized_load_1m_percent`, `per_core_percent` 필드 보존 및 `check_ambient_load_protocol` 정합성 검증.
   - (d) macOS ps 프로세스 점유율 합산 및 코어 수 정규화 계산 검증.

4. **`docs/analysis/cpu_utilization_metric_20260828.md`**:
   - `normalized_load_1m_percent`와 `cpu_utilization_percent`의 상세 정의, 물리적 차이, 용도 구분(주변 부하 규약 vs G3 부하 분석) 명시.

---

## 3. 수용 기준(Acceptance Criteria) 대조

| 수용 기준 | 달성 여부 | 검증 근거 |
| :--- | :---: | :--- |
| **실제 CPU utilization이 리포트에 기록된다** | **충족** | `single_host_load_sample`, `compute_host_load_stats`, `HostLoadMonitor`에서 `cpu_utilization_percent` 필드 산출 및 리포트 포함 |
| **외부 라이브러리를 추가하지 않았다** | **충족** | `pyproject.toml` 무변경, Python 표준 라이브러리(`os`, `subprocess`, `time`, `statistics`) 및 OS 기본 명령(`ps`, `/proc/stat`)만 사용 |
| **측정 불가 시에도 벤치마크가 중단되지 않는다** | **충족** | Windows/미지원 플랫폼 및 I/O 실패 시 `None`과 `cpu_utilization_unavailable_reason`을 남기고 fail-safe 완주 |
| **기존 load average 필드와 테스트가 유지된다** | **충족** | `load_1m`, `normalized_load_1m_percent`, `per_core_percent` 필드명 및 산출 로직 100% 불변, 전체 벤치마크 테스트 통과 |

---

## 4. 검증 결과

1. **CPU Utilization 회귀 테스트**:
   - `uv run pytest tests/test_cpu_utilization_metric.py tests/test_benchmark_provenance.py tests/test_benchmark_latency.py -q`
   - 결과: **136 passed, 0 failed** (100% 통과).

2. **규칙 정합성 검증**:
   - `python3 scripts/validate_agent_rules.py --quiet`
   - 결과: **12/12 건 통과**.
