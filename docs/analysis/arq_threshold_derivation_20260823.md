# Arq 게이트 절대 기준선(900 jobs/sec, 600ms P95) 도출 근거 분석

> **작성일**: 2026-08-23
> **목적**: `scripts/arq_gate.py`의 `RepetitionThresholds`에 정의된 절대 기준선(900 jobs/sec, 600ms P95)이 어느 측정에서 도출되었는지 근거를 명문화하고, 도출 관계가 성립하지 않을 경우 사후 보정임을 인정하며 잠정 일관성 봉투(provisional consistency envelope)로 개명한다.
> **정본 사양**: `.orca/capsules/arq_threshold_derivation_20260823/capsule.yaml`

---

## 1. 절대 기준선 정의 위치

`scripts/arq_gate.py:80-100`의 `RepetitionThresholds` 데이터클래스:

```python
@dataclass
class RepetitionThresholds:
    """반복 측정의 절대 기준선."""

    min_runs: int = 3
    min_throughput_tasks_per_sec: float = 900.0      # ← 절대 기준선: 처리량
    max_p95_latency_ms: float = 600.0                # ← 절대 기준선: P95 지연
    max_failure_rate: float = 0.0                    # ← 절대 기준선: 실패율
```

이 값들은 **코드에 하드코딩된 기본값**으로, 외부 설정 파일이나 환경변수에서 주입되지 않는다.

---

## 2. 저장소 내 실측 벤치마크 데이터 종합

모든 벤치마크는 `total_jobs=600`, `concurrency=10`(컨테이너 측정은 4), `job_delay_ms=0.0`, `poll_delay_sec=0.01` 조건에서 수행되었다.

| 측정 파일 | Git SHA | 처리량 (jobs/sec) | P95 지연 (ms) | 실패율 | 비고 |
| --- | --- | ---: | ---: | ---: | --- |
| `arq_throughput_20260823.json` (초기 대표) | ca3995d | **1,150.48** | **499.457** | 0.00% | 최초 단일 측정 |
| `arq_throughput_20260823_verification_r1.json` | e897a2f | **1,165.18** | **492.452** | 0.00% | 검증 1회차 |
| `arq_throughput_20260823_verification_r2.json` | e897a2f | **1,138.77** | **504.941** | 0.00% | 검증 2회차 (최악 대표) |
| `arq_throughput_20260823_verification_r3.json` | e897a2f | **1,158.08** | **495.597** | 0.00% | 검증 3회차 |
| `arq_worker_measure_20260823.json` | d95efd5 | **1,107.79** | **519.198** | 0.00% | 워커 단독 측정 |
| `arq_container_measure_20260823.json` | 7892951 | **1,636.00** | **352.614** | 0.00% | Docker 컨테이너 (concurrency=4) |

---

## 3. 절대 기준선(900/600)과 실측값의 정량 비교

| 지표 | 절대 기준선 | 실측 최솟값 | 실측 최댓값 | 실측 중앙값 | 기준선 대비 여유도 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **처리량 (jobs/sec)** | **900.0** | 1,107.79 | 1,636.00 | 1,150.48 | **+23.1% ~ +81.8%** (기준선보다 높음) |
| **P95 지연 (ms)** | **600.0** | 352.614 | 519.198 | 499.457 | **-13.4% ~ -41.2%** (기준선보다 낮음) |

**결론**: 모든 실측값이 절대 기준선을 **큰 폭으로 상회(처리량) 또는 하회(P95)**한다. 900 jobs/sec 또는 600ms P95에 근접하거나 이를 기준으로 삼을 만한 측정은 **단 하나도 존재하지 않는다**.

---

## 4. 도출식 역산 시도 및 결과

### 4.1 처리량: `baseline * factor = 900` 인 baseline 탐색

| 후보 baseline | 실측값 | 역산 factor | 평가 |
| --- | ---: | ---: | --- |
| 초기 대표 (1,150.48) | 1,150.48 | 0.782 | 임의의 0.78배, 의미 있는 safety factor 아님 |
| 검증 최악 (1,138.77) | 1,138.77 | 0.790 | 동일 |
| 워커 측정 (1,107.79) | 1,107.79 | 0.812 | 동일 |
| 컨테이너 (1,636.00) | 1,636.00 | 0.550 | 동일 |

**어떤 실측값에도 일관된 승수(factor)로 900을 설명할 수 없다.** 승수가 0.55~0.81 사이로 분산되며, 통계적 근거(예: 평균 - 2σ, 분위수 등)로 도출되지 않는다.

### 4.2 P95 지연: `baseline * factor = 600` 인 baseline 탐색

| 후보 baseline | 실측값 | 역산 factor | 평가 |
| --- | ---: | ---: | --- |
| 초기 대표 (499.457) | 499.457 | 1.201 | 임의의 1.20배 |
| 검증 최악 (504.941) | 504.941 | 1.188 | 동일 |
| 워커 측정 (519.198) | 519.198 | 1.156 | 동일 |
| 컨테이너 (352.614) | 352.614 | 1.702 | 동일 |

**마찬가지로 어떤 실측값에도 일관된 승수로 600을 설명할 수 없다.** 승수가 1.15~1.70 사이로 분산된다.

### 4.3 통계적 도출 시도 (평균 ± kσ, 분위수 등)

검증 3회차(처리량: 1165.18, 1138.77, 1158.08 / P95: 492.452, 504.941, 495.597)로 표본 통계량 계산:

- **처리량**: 평균 1154.01, 표준편차 13.34 → 평균 - 2σ = 1127.33, 최소값 = 1138.77
- **P95**: 평균 497.66, 표준편차 6.38 → 평균 + 2σ = 510.43, 최대값 = 504.94

**900과 600은 어떤 통계적 도출식(평균 ± kσ, 분위수, 최악값 × safety factor)에서도 나오지 않는다.**

---

## 5. 기존 문서의 서술 검토

`docs/ops/arq_threshold_provenance_20260823.md`의 2.2절 "절대 기준선" 표:

| 지표 | 절대 기준선 | 비고 |
| --- | :---: | --- |
| 최소 초당 처리량 | `>= 900.0 tasks/sec` | **합성 작업 기준 인메모리 큐 최소 처리 성능** |
| 최대 P95 지연 | `<= 600.0 ms` | **인메모리 큐 enqueue-to-complete 상한** |

"합성 작업 기준 최소 처리 성능", "인메모리 큐 상한"이라는 **정성적 서술만 있을 뿐**, 구체적인 측정값·도출식·데이터 출처는 **없다**. 이는 사후 보정(post-hoc calibration)임을 시인하는 서술이다.

---

## 6. 판정: 사후 보정임을 인정하고 잠정 일관성 봉투로 개명

### 6.1 판단 근거

1. **실측 근거 부재**: 저장소의 어떤 벤치마크 측정에서도 900 jobs/sec 또는 600ms P95에 근접하는 값이 관측되지 않음
2. **도출식 부재**: 평균 ± kσ, 분위수, 최악값 × safety factor 등 어떤 통계적 도출식으로도 900/600을 재현할 수 없음
3. **문서 서술의 성격**: "최소 처리 성능", "상한"이라는 정성적 표현만 있고 정량적 출처가 없음 → 사후 합리화(post-hoc rationalization)

### 6.2 개명: 잠정 일관성 봉투 (Provisional Consistency Envelope)

| 기존 명칭 | 개명 후 명칭 | 성격 |
| --- | --- | --- |
| 절대 기준선 (Absolute Baseline) | **잠정 일관성 봉투 (Provisional Consistency Envelope)** | 실측 분포를 포괄하는 **보수적 여유 구간**임을 명시 |
| `min_throughput_tasks_per_sec = 900.0` | `provisional_min_throughput_tasks_per_sec = 900.0` | 실측 최솟값(1,107.79) 대비 **+23% 여유** |
| `max_p95_latency_ms = 600.0` | `provisional_max_p95_latency_ms = 600.0` | 실측 최댓값(519.198) 대비 **-13% 여유** |

> **잠정 일관성 봉투의 정의**: "현재까지 관측된 모든 실측 분포를 확실하게 포괄하며, 향후 정식 기준선 도출을 위한 최소 측정 조건이 충족될 때까지 한시적으로 사용하는 보수적 판정 구간."

---

## 7. 정식 기준선 도출을 위해 필요한 후속 측정 조건

잠정 봉투를 정식 기준선(Formal Baseline)으로 대체하려면 다음 조건을 충족하는 **전용 캘리브레이션 런**이 필요하다.

| 조건 | 상세 | 비고 |
| --- | --- | --- |
| **C1. 독립 반복 10회 이상** | 동일 구성(잡 600개, concurrency 10, delay 0)에서 10회 이상 독립 실행 | 중심극한정리에 의한 통계적 안정성 확보 |
| **C2. 환경 고정 및 기록** | Host OS/CPU, Redis 버전/모드, Arq 버전, Docker 이미지 SHA, 호스트 로드 평균을 매 회차 기록 | Provenance 완전성 |
| **C3. 워커·컨테이너 각각 측정** | In-process 워커(현재)와 Docker 컨테이너 워커를 각각 C1 조건으로 측정 | 배포 환경별 기준선 분리 |
| **C4. 부하 변이 포함** | `job_delay_ms` 0/1/5/10ms, `concurrency` 5/10/20 등 운영 유사 변이 조건 추가 | 단일 포인트 추정 회피 |
| **C5. 통계적 도출식 합의** | 예: "중앙값 - 1.5σ", "5% 분위수", "최소값 × 0.95" 중 하나를 팀 합의로 고정 | 임의성 제거 |

이 조건이 충족되면:

```python
# 정식 기준선 예시 (C1~C5 충족 후 산출)
class FormalRepetitionThresholds:
    min_runs: int = 3
    min_throughput_tasks_per_sec: float = 1050.0  # 예: 중앙값 - 1.5σ
    max_p95_latency_ms: float = 540.0             # 예: 95% 분위수
    max_failure_rate: float = 0.0
```

---

## 8. 상대 회귀 임계값(GateThresholds)과의 역할 구분

| 구분 | 상대 회귀 임계값 (`GateThresholds`) | 잠정 일관성 봉투 (`RepetitionThresholds`) |
| --- | --- | --- |
| **비교 대상** | baseline 표본 vs current 표본 (페어 비교) | 단일 표본 vs 고정 상수 (절대 판정) |
| **의미** | "이전 버전 대비 퇴행했는가?" | "최소 운용 품질을 충족하는가?" |
| **도출 근거** | `latency_gate_protocol.md`의 -10%/+10%/+1pp 원칙 | **실측 근거 없음 (잠정 봉투)** |
| **적용 시점** | 배포 전 회귀 검증 (CI/CD 게이트) | 신규 환경/리팩토링 후 최초 적합성 확인 |
| **실패 시 의미** | 성능 퇴행 의심 → 롤백/조사 | 환경 부적합 또는 측정 조건 미충족 → 재측정 필요 |

---

## 9. 요약 및 액션 아이템

1. **900 jobs/sec, 600ms P95는 어떤 측정에서도 도출되지 않음** → 사후 보정임을 문서화 완료
2. **`RepetitionThresholds` → `ProvisionalConsistencyEnvelope`로 개명** (코드 수정은 별도 Task에서 수행, 본 Task는 문서만 변경)
3. **정식 기준선 도출을 위한 캘리브레이션 런(C1~C5) 기획 필요** → 후속 Task로 분리 권장
4. **상대 회귀 임계값과 절대/잠정 기준선의 역할 차이를 문서와 코드 주석에 명시** → 혼동 방지

---

## 부록: 원시 데이터 참조 경로

| 파일 | 경로 |
| --- | --- |
| 초기 대표 측정 | `data/benchmarks/arq_throughput_20260823.json` |
| 검증 1회차 | `data/benchmarks/arq_throughput_20260823_verification_r1.json` |
| 검증 2회차 | `data/benchmarks/arq_throughput_20260823_verification_r2.json` |
| 검증 3회차 | `data/benchmarks/arq_throughput_20260823_verification_r3.json` |
| 워커 단독 측정 | `data/benchmarks/arq_worker_measure_20260823.json` |
| 컨테이너 측정 | `data/benchmarks/arq_container_measure_20260823.json` |
| 게이트 판정 모듈 | `scripts/arq_gate.py` |
| 기존 Provenance 문서 | `docs/ops/arq_threshold_provenance_20260823.md` |
| 게이트 판정 기록 | `docs/analysis/arq_throughput_gate_20260823.md` |
