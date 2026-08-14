# Phase 8 예측 서비스 GC 후보 설계 및 측정 계획

> **작성일**: 2026-08-14
> **작성자**: Antigravity (Orca 워커 task_5b35c27ab303)
> **브랜치**: perf/gc-tuning-candidates
> **근거 문서**: docs/ops/phase8_predict_tail_root_cause_20260814.md, docs/ops/phase8_predict_tail_merge_verdict_20260814.md
> **상태**: 구현 완료, 측정 대기

---

## 배경

generation-2 GC 가 c10 P99 지연 꼬리의 원인으로 특정됐습니다.
`gc.disable()` 실측에서 P99 가 77.7 ms에서 41.0 ms 로 내려갔으나,
gc.disable() 을 운영에 그대로 사용하면 장기 메모리 누증 위험이 있어 채택할 수 없습니다.
본 문서는 운영 채택 가능한 세 후보를 정의하고, 채택 기준과 측정 절차를 제시합니다.

---

## 환경변수 제어 방식

```
PREDICTION_GC_MODE=<후보명>
```

| 값 | 설명 |
| --- | --- |
| (빈 문자열 또는 미설정) | 기본 동작. gc 상태를 전혀 변경하지 않습니다. |
| `freeze` | 모델 가중치 객체를 영구 세대로 이동합니다. |
| `threshold` | gen1/gen2 GC 임계값을 올립니다. |
| `batch-disable` | 배치 스레드가 GC 를 끄고 일정 배치마다 수동 collect 합니다. **이름과 달리 프로세스 전역입니다** (아래 후보 C 참조). |

기본값(빈 문자열) 경로는 완전히 무비용입니다.
모듈 임포트 시 한 번 읽고, 요청 처리 경로에는 분기가 없습니다.

---

## 후보 설명

### 후보 A: freeze

**원리**

`ModelRegistry.load_all_models()` 직후 `gc.freeze()` 를 호출합니다.
CPython 3.12 이상에서 `gc.freeze()` 는 현재 힙에 있는 모든 객체를 영구 세대(generation 3)로 이동합니다.
영구 세대 객체는 이후 generation-2 순회 대상에서 제외됩니다.
모델 가중치(수백 MB)가 영구 세대로 이동하면 generation-2 순회 비용이 크게 줄어듭니다.

**위험 요소**

| 위험 | 설명 |
| --- | --- |
| 순환 참조 누증 | freeze 이후 생성된 객체가 freeze 된 객체를 참조하면 순환 참조가 회수되지 않을 수 있습니다. |
| 버전 의존성 | gc.freeze() 동작은 CPython 3.12 이상을 전제합니다. |
| 단발 효과 | 서버 재시작 시에만 적용되므로 온라인 리로드 시 재호출이 필요합니다. |

**채택을 위해 측정할 것**

- 10분 지속 부하 후 RSS 증가량
- c10 P99 지연

---

### 후보 B: threshold

**원리**

`gc.set_threshold(700, 20, 30)` 으로 gen1/gen2 임계값을 올립니다.
CPython 기본값은 `(700, 10, 10)` 입니다.
gen2 순회는 gen1 순회 `threshold2` 회마다, gen1 순회는 gen0 순회 `threshold1`
회마다 일어나므로 gen2 빈도는 두 값의 곱에 반비례합니다. 기본 10x10=100 에서
20x30=600 으로 올리면 **gen2 빈도가 약 1/6** 이 됩니다(1/3 이 아닙니다).
회수 자체는 유지되므로 지연 꼬리를 낮추면서 누증 위험은 낮습니다.
gen0 는 기본값을 유지해 단기 객체 회수를 보전합니다.

**임계값 근거**

| 세대 | 기본값 | 설정값 | 효과 |
| --- | --- | --- | --- |
| gen0 | 700 | 700 | 단기 객체 회수 유지 |
| gen1 | 10 | 20 | gen1->gen2 승격 빈도 50% 감소 |
| gen2 | 10 | 30 | generation-2 순회 빈도 약 67% 감소 |

gen2 를 무한정 올리면 순환 참조 객체가 오래 유지돼 메모리가 증가합니다.
30 은 메모리 누증과 지연 개선 사이의 보수적 타협점입니다.

**위험 요소**

| 위험 | 설명 |
| --- | --- |
| 순환 참조 누증 | GC 빈도가 줄어들면 순환 참조 회수가 늦어집니다. |
| 부분 개선 | freeze 보다 generation-2 제거 효과가 작습니다. |

**채택을 위해 측정할 것**

- 10분 지속 부하 후 RSS 증가량
- c10 P99 지연
- gc.get_count() 스냅샷으로 GC 발생 빈도 변화

---

### 후보 C: batch-disable

**원리**

마이크로배치 스레드(`prediction-microbatch-*`)가 기동 직후 `gc.disable()` 을
호출하고, 50 배치마다 `gc.collect()` 를 명시적으로 수행합니다.

**이름이 오해를 부릅니다. `gc.disable()` 은 스레드 한정이 아니라 프로세스
전역입니다.** CPython 에는 스레드별 GC 제어가 없으며 GIL 과도 무관합니다.
따라서 이 모드는 "배치 스레드만 GC 를 끄는" 것이 아니라 **프로세스 전체의 자동
회수를 끄고 회수 시점만 배치 경계로 옮기는** 것입니다. 요청 처리 외의 코드
경로(수집 태스크, RAG, 웹 요청)도 같은 영향을 받습니다.

이 오해는 초기 서술에 있었고 코디네이터 검수에서 정정했습니다. 세 후보 중
위험이 가장 큰 것이 이 후보이며, RSS 추이 확인 없이 채택하면 안 됩니다.

**위험 요소**

| 위험 | 설명 |
| --- | --- |
| 프로세스 전역 영향 | 배치 스레드뿐 아니라 수집·RAG·웹 요청 경로의 자동 회수까지 멈춥니다 |
| 수동 collect 타이밍 | 50 배치 사이에 순환 참조가 누증될 수 있습니다. |
| 구현 복잡도 | 다른 두 후보보다 코드 경로가 복잡합니다. |

**채택을 위해 측정할 것**

- 10분 지속 부하 후 RSS 증가량
- c10 P99 지연
- gc.get_count() 스냅샷으로 collect 사이 누증 확인

---

## 채택 기준 (제안)

아래 기준을 모두 충족하는 후보만 채택을 검토합니다.

| 지표 | 기준값 | 근거 |
| --- | --- | --- |
| c10 P99 지연 | 50 ms 이하 | gc.disable() 실측 41.0 ms 에 안전 마진 포함 |
| 10분 지속 부하 RSS 증가 | 200 MB 이하 | 운영 서버 여유 메모리 기준 보수적 설정 |
| 기본 모드 대비 P99 개선 | 20% 이상 | 단순 노이즈가 아닌 유의미한 개선 |

기준을 충족하는 후보가 여럿이면 RSS 증가량이 가장 작은 후보를 우선합니다.
어느 후보도 기준을 충족하지 못하면 현재 기본 동작을 유지합니다.

---

## 측정 절차

### 공통 준비

서버를 측정할 GC 모드로 시작합니다.

```bash
PREDICTION_GC_MODE=<후보명> uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

측정 스크립트를 실행합니다.

```bash
python scripts/measure_predict_rss.py \
    --base-url http://localhost:8000 \
    --duration-seconds 600 \
    --concurrency 10 \
    --sample-interval-seconds 5 \
    --out results/gc_<후보명>_$(date +%Y%m%d_%H%M%S).json
```

### 기본 모드(대조군)

```bash
PREDICTION_GC_MODE= uvicorn src.app.main:app --host 0.0.0.0 --port 8000
python scripts/measure_predict_rss.py \
    --base-url http://localhost:8000 \
    --duration-seconds 600 \
    --concurrency 10 \
    --sample-interval-seconds 5 \
    --out results/gc_default_$(date +%Y%m%d_%H%M%S).json
```

### freeze 후보

```bash
PREDICTION_GC_MODE=freeze uvicorn src.app.main:app --host 0.0.0.0 --port 8000
python scripts/measure_predict_rss.py \
    --base-url http://localhost:8000 \
    --duration-seconds 600 \
    --concurrency 10 \
    --sample-interval-seconds 5 \
    --out results/gc_freeze_$(date +%Y%m%d_%H%M%S).json
```

### threshold 후보

```bash
PREDICTION_GC_MODE=threshold uvicorn src.app.main:app --host 0.0.0.0 --port 8000
python scripts/measure_predict_rss.py \
    --base-url http://localhost:8000 \
    --duration-seconds 600 \
    --concurrency 10 \
    --sample-interval-seconds 5 \
    --out results/gc_threshold_$(date +%Y%m%d_%H%M%S).json
```

### batch-disable 후보

```bash
PREDICTION_GC_MODE=batch-disable uvicorn src.app.main:app --host 0.0.0.0 --port 8000
python scripts/measure_predict_rss.py \
    --base-url http://localhost:8000 \
    --duration-seconds 600 \
    --concurrency 10 \
    --sample-interval-seconds 5 \
    --out results/gc_batch_disable_$(date +%Y%m%d_%H%M%S).json
```

---

## 주의 사항

- 각 후보를 측정할 때 다른 부하 발생 프로세스를 중단하고 측정합니다. 동일 장비에서 다른 에이전트가 작업 중이면 측정값이 오염됩니다.
- 각 후보마다 서버를 재시작하고 5분 웜업 후 측정을 시작합니다.
- 측정 결과 JSON 을 보존해 비교 근거로 남깁니다.
- 어느 후보가 좋다는 결론은 측정 완료 후에만 내립니다.
