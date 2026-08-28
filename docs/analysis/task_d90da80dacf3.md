# CPU utilization 계측의 순수 관측 시간 분리 분석 및 구현 보고서

> **작성일**: 2026-08-28
> **태스크**: task_d90da80dacf3 (run_973af8e258f4)
> **대상 파일**: [`scripts/benchmark_provenance.py`](../../scripts/benchmark_provenance.py), [`tests/test_cpu_utilization_metric.py`](../../tests/test_cpu_utilization_metric.py), [`tests/test_benchmark_provenance.py`](../../tests/test_benchmark_provenance.py)
> **근거 handoff**: [`docs/handoff/session_20260828_gpt_audit_p1p2_orca.md` §5.1](../handoff/session_20260828_gpt_audit_p1p2_orca.md)

---

## 1. 개요 및 배경

`scripts/benchmark_provenance.py`의 `measure_cpu_utilization`은 Linux 경로(`/proc/stat` 차분)에서 의도적 `time.sleep(sleep_dur)` (기본 0.05 초)을 두 번의 `read_proc_stat_ticks` 호출 사이에 둡니다. 그 결과로 리포트에 기록되는 `cpu_utilization_probe_ms`는 **의도적 대기 시간**을 포함한 총 소요 시간이라 macOS `ps` 기반 값과 물리적 의미가 다릅니다.

같은 방식(예: `proc_stat_delta`끼리) 비교 시에는 의미가 일치하지만, 관측 부하 자체의 비용을 따로 보고 싶을 때는 sleep 이 포함된 값이 방해가 됩니다. docs/handoff §5.1은 이를 "남은 작은 과제"로 기록해 두었고, 본 Task는 **의도적 대기를 제외한 순수 관측 시간**을 별도 키로 추가하는 것을 목표로 합니다.

핵심 결정:
- `cpu_utilization_probe_ms`의 기존 의미(대기 포함 총 소요 시간)와 값은 바꾸지 않습니다. 기존 키에 의존하는 회귀 테스트와 과거 리포트 해석이 깨지면 안 됩니다.
- `cpu_utilization_observation_ms` (신규): 의도적 대기 시간을 제외한 순수 관측 시간(ms).
  - Linux: 두 `read_proc_stat_ticks` 호출에 실제로 걸린 시간의 합.
  - macOS: 의도적 대기가 없으므로 `probe_ms`와 동일.
  - 미지원 플랫폼: 기존 규칙을 따라 `probe_ms`와 동일.
- `measure_cpu_utilization` 반환은 4 튜플 → 5 튜플로 확장하고, 두 호출부(`single_host_load_sample`, `HostLoadMonitor._sample`)를 모두 함께 갱신해 값이 리포트까지 전달되게 합니다.
- 실패 경로(`/proc/stat` 1·2차 읽기 실패 등)에서도 두 키가 모두 기록됩니다. 이는 "방식 식별자가 남는 것과 같은 원칙"입니다.

---

## 2. 주요 변경 사항

### 2.1 `measure_cpu_utilization` 반환 확장

`scripts/benchmark_provenance.py:981` 부근에서 함수 시그니처를
`(float | None, str | None, str, float)` → `(float | None, str | None, str, float, float)`로 확장하고, Linux 분기에서 두 번의 `read_proc_stat_ticks` 호출 시간을 누적해 `observation_ms`를 계산합니다.

```python
read_start_at = time.perf_counter()
start_ticks, start_err = read_proc_stat_ticks(proc_stat_path)
observation_ms += (time.perf_counter() - read_start_at) * 1000.0
# ... sleep (제외 대상) ...
read_start_at = time.perf_counter()
end_ticks, end_err = read_proc_stat_ticks(proc_stat_path)
observation_ms += (time.perf_counter() - read_start_at) * 1000.0
```

- macOS / 미지원 분기: 의도적 대기가 없거나 측정 자체가 없으므로 `observation_ms == probe_ms`.
- 함수 docstring의 Returns 절에 `probe_ms`(대기 포함)와 `observation_ms`(대기 제외)의 차이를 한 줄로 명시했습니다.

### 2.2 `single_host_load_sample` 결과 dict에 신규 키 추가

`scripts/benchmark_provenance.py:1080` 부근에서 반환 dict에
`cpu_utilization_observation_ms`를 추가합니다. `cpu_util_sampler`를 통한 주입 경로(테스트가 `cpu_util_sampler`를 람다로 넣는 경로)와 `measure_cpu_utilization` 직접 호출 경로 모두 5 튜플을 unpack 하도록 갱신했습니다. 함수 docstring의 키 목록에도 두 키의 차이를 명시했습니다.

### 2.3 `HostLoadMonitor._sample` 갱신

`scripts/benchmark_provenance.py:1280` 부근의 백그라운드 샘플러는 자체적으로 `read_proc_stat_ticks`를 한 번만 부르고 나머지는 `self.sampler()`(=`single_host_load_sample`)에 위임합니다. 따라서 `_sample`에서도 동일한 1회 read 시간을 누적해 `cpu_utilization_observation_ms`를 표본에 기록해야 합니다. 이 경로가 누락되면 백그라운드 표본 통계에서 두 키가 어긋나므로 호출부 두 곳을 함께 갱신하는 acceptance 조건을 만족합니다.

### 2.4 회귀 테스트 추가 (`tests/test_cpu_utilization_metric.py`)

신규 `TestObservationTimeSeparation` 클래스에서 Capsule이 명시한 (a)~(e) 5개 시나리오를 고정합니다.

| 시나리오 | 검증 내용 |
| --- | --- |
| (a) Linux `observation_ms < probe_ms` | `time.sleep`을 즉시 반환하는 가짜로 모킹해 `probe_ms`가 sleep 만큼 부풀어도 `observation_ms`는 그대로 유지됨을 확인 |
| (b) sleep 모킹이 관측 시간을 부풀리지 않음 | (a) 의 핵심. 가짜 sleep 이 0초이므로 `observation_ms < probe_ms`이고 둘 다 매우 작음 |
| (c) macOS `observation_ms == probe_ms` | `command_runner`로 `ps` 출력을 주입해 `observation_ms == probe_ms` 검증 |
| (d) proc/stat 읽기 실패에서도 두 키 존재 | `proc_stat_not_found`/`proc_stat_parse_failed` 두 경로에서 `probe_ms`와 `observation_ms`가 모두 0 이상 |
| (e) `HostLoadMonitor` 표본에 두 키 포함 | `tmp_path`에 `/proc/stat`을 두고 모니터 시작/정지, 모든 표본이 `cpu_utilization_observation_ms`를 가지며 `probe_ms` 이하임을 검증 |

또한 기존 4 튜플 unpack이 5개였던 모든 호출(`tests/test_cpu_utilization_metric.py:132`, `tests/test_benchmark_provenance.py:401/440/453/465/477/490`)을 5 튜플로 갱신해 의미가 깨지지 않도록 했습니다.

`time.sleep`을 모킹할 때 monkeypatch 종료 시 원본을 복원하도록 의식적으로 `monkeypatch.setattr(time, "sleep", real_sleep)`을 명시해 다른 테스트로의 누수를 방지했습니다.

---

## 3. 검증 결과

| 검증 항목 | 명령 | 결과 |
| --- | --- | --- |
| 대상 테스트 | `uv run pytest tests/test_cpu_utilization_metric.py tests/test_benchmark_provenance.py -q` | 106 passed |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | 통과 (자동 검증) |
| 린트 | `uv run ruff check src/ scripts/ tests/` | 통과 (자동 검증) |
| 에이전트 규칙 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 (자동 검증) |

---

## 4. 변경 파일 요약

- `scripts/benchmark_provenance.py`: `measure_cpu_utilization` 5 튜플 반환, `single_host_load_sample` 결과 dict 확장, `HostLoadMonitor._sample` 표본 확장, 관련 docstring 갱신.
- `tests/test_cpu_utilization_metric.py`: 신규 `TestObservationTimeSeparation` 클래스, 기존 4 튜플 unpack 1 곳 갱신.
- `tests/test_benchmark_provenance.py`: 기존 4 튜플 unpack 4 곳 / mock 2 곳을 5 튜플에 맞게 갱신.
- `docs/analysis/task_d90da80dacf3.md`: 본 보고서.

호출부 누락, 기존 키 의미 변경, 실패 경로 누락, 실제 sleep 사용, 범위 외 파일 수정 — 다섯 가지 review checklist 항목 모두 위반 없음을 확인했습니다.
