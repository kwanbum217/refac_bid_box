# 벤치마크 호스트 부하 및 CPU Utilization 계측 정본 분석 보고서

> **작성일**: 2026-08-28
> **작업 ID**: `task_ac1c2f9da231`
> **관련 규약**: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
> **대상 모듈**: `scripts/benchmark_provenance.py`, `scripts/benchmark_latency.py`, `tests/test_cpu_utilization_metric.py`

---

## 1. 배경 및 목적

기존 벤치마크 하네스는 호스트 부하 지표로 1분 load average를 논리 코어 수로 나눈 `normalized_load_1m_percent`(하위 호환 `per_core_percent`)만을 수집·기록했습니다.
그러나 load average는 실행 대기 및 I/O 대기 큐에 머무는 프로세스 수의 1분 이동 평균으로, 측정 표본 구간 동안 CPU 코어가 실제로 연산에 사용된 실제 CPU 사용률(CPU Utilization %)을 직접적으로 나타내지 못합니다.

본 과업에서는 외부 의존성(psutil 등)을 일절 추가하지 않고, 표준 라이브러리와 OS 기본 인터페이스만을 사용하여 크로스플랫폼(macOS/Linux) 실제 CPU utilization 계측 체계를 구축하고 벤치마크 리포트에 정규화 load average와 함께 독립 필드로 보존합니다.

---

## 2. 두 지표의 정의 및 비교

| 비교 항목 | 정규화 1분 Load Average (`normalized_load_1m_percent`) | 실제 CPU Utilization (`cpu_utilization_percent`) |
| :--- | :--- | :--- |
| **정의** | 1분 OS load average / 논리 CPU 코어 수 x 100(%) | 표본 구간 동안 CPU가 유휴(idle) 상태가 아닌 연산 상태였던 시간 비율(%) |
| **측정 대상** | CPU 실행 대기 큐 + 디스크 I/O 대기 큐 프로세스 수 | CPU 코어의 실제 연산 틱(User, System, Nice, Steal 등) 소모량 |
| **반응 시차** | 1분 지수 감쇄 평균으로 수십 초의 시차가 발생함 | 측정 표본 구간(차분 구간) 동안의 즉각적인 실시간 사용률 |
| **수치 범위** | 병목/대기열 증가 시 100%를 초과할 수 있음 | 0.0% ~ 100.0% 범위로 엄격히 한정됨 |
| **데이터 원천** | `os.getloadavg()` (POSIX 커널 인터페이스) | Linux: `/proc/stat` 차분 / macOS: `ps -A -o %cpu` |
| **하위 호환 필드** | `per_core_percent` (동일 값 보존) | `cpu_utilization_percent` (신규 필드 추가) |

---

## 3. 판정 기준 및 용도 구분

벤치마크 수행 및 결과 분석 시 두 지표는 상호 보완적으로 사용되며, 각각 다음 판정에 적용됩니다.

### 3.1 주변 부하 규약 판정 (Ambient Load Protocol Gate)
- **사용 지표**: `normalized_load_1m_percent` (중앙값/최대값)
- **판정 기준**: 중앙값 **30.0% 이하**, 최대값 **50.0% 이하** (`docs/ops/latency_gate_protocol.md` 5.3절)
- **적용 이유**: 벤치마크 측정 외부에 다른 백그라운드 프로세스, 빌드, 컨테이너가 시스템 자원을 잠식하고 있는지 전반적인 시스템 포화도를 검증하는 게이트입니다.

### 3.2 G3 성능 최적화 및 CPU 부하 분석 (Stack Optimization & Profiling)
- **사용 지표**: `cpu_utilization_percent` (표본별 통계: min, median, max)
- **판정 기준**: 서비스 엔드포인트별(예측 API 마이크로배칭, SSE LLM 스트리밍, Arq 태스크 큐 등) 실제 CPU 소비율 분석
- **적용 이유**: 단일 요청 및 배치 처리 시 CPU 바운드 연산의 병목 여부, 멀티프로세스/스레드 스케일링 효율, 유휴 시간 대비 실제 컴퓨팅 자원 활용률을 판단하는 기술적 근거로 활용합니다.

---

## 4. 플랫폼별 계측 기전 및 외부 의존성 배제

신규 라이브러리 추가 금지 원칙에 따라 `psutil` 등 외부 의존성을 일체 사용하지 않고 표준 인터페이스로 구현되었습니다.

### 4.1 Linux 환경 (`/proc/stat` 두 시점 차분)
- `/proc/stat`의 첫 번째 `cpu` 라인에서 `user`, `nice`, `system`, `idle`, `iowait`, `irq`, `softirq`, `steal` 틱을 파싱합니다.
- 총 틱 $\text{total} = \sum \text{ticks}$, 유휴 틱 $\text{idle\_total} = \text{idle} + \text{iowait}$을 계산합니다.
- 모니터링 시작/종료 또는 표본 주기 간격 $t_1, t_2$의 차분을 계산합니다:
  $$\text{utilization(\%)} = \frac{\Delta\text{total} - \Delta\text{idle\_total}}{\Delta\text{total}} \times 100.0$$
- $\Delta\text{total} \le 0$인 카운터 롤오버나 정체 시 `(None, "non_positive_total_ticks_delta")`로 안전하게 처리합니다.

### 4.2 macOS 환경 (`ps` 기반 정규화)
- `ps -A -o %cpu` 명령을 표준 라이브러리 `subprocess`로 실행하여 프로세스별 CPU 사용률을 파싱합니다.
- 프로세스별 사용률 합계를 논리 CPU 코어 수(`os.cpu_count()`)로 나누어 시스템 전체 CPU utilization(%)을 산출하고 `[0.0, 100.0]` 범위로 클램핑합니다.
- 명령 실패나 출력 형식 이상 시 `(None, reason)`을 반환합니다.

### 4.3 Windows 및 기타 미지원 플랫폼 (Graceful Fallback)
- 지원되지 않는 플랫폼(`win32` 등)에서는 `cpu_utilization_percent`를 `None`으로 기록하고 `cpu_utilization_unavailable_reason`에 `"unsupported_platform: win32"`를 남깁니다.
- 예외를 발생시키지 않으며, 벤치마크 하네스와 리포트 생성은 중단 없이 정상 완주합니다.

---

## 5. 리포트 데이터 스키마 및 호환성

`scripts/benchmark_provenance.py`의 `single_host_load_sample()`, `compute_host_load_stats()`, `HostLoadMonitor`는 다음 구조로 리포트를 생성합니다.

```json
{
  "cpu_count": 8,
  "samples": [
    {
      "observed_at_utc": "2026-08-28T05:50:00+00:00",
      "load_1m": 1.20,
      "cpu_count": 8,
      "normalized_load_1m_percent": 15.0,
      "per_core_percent": 15.0,
      "cpu_utilization_percent": 24.5,
      "cpu_utilization_unavailable_reason": null
    }
  ],
  "load_1m": { "min": 1.10, "median": 1.20, "max": 1.35 },
  "normalized_load_1m_percent": { "min": 13.75, "median": 15.0, "max": 16.88 },
  "per_core_percent": { "min": 13.75, "median": 15.0, "max": 16.88 },
  "cpu_utilization_percent": { "min": 18.2, "median": 24.5, "max": 31.0 }
}
```

기존 `load_1m`, `normalized_load_1m_percent`, `per_core_percent` 필드는 원형 그대로 보존되어 기존 규약 검증기와의 100% 하위 호환성을 보장합니다.
