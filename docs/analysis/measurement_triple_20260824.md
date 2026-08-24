# 측정 3종 실측 보고 (2026-08-24)

> **작성일**: 2026-08-24 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **기준 커밋**: `a9165f0` (측정 시점 워크트리 clean)
> **Orca Run**: `run_741ba9c544a9`
> **판정 근거**: [`../ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)

---

## 0. 요약

잔여 과업이던 측정 3종을 **조용한 호스트에서 순차로** 수행했습니다. 병렬 수행은
세 측정이 서로의 주변 부하가 되어 규약을 만족할 수 없으므로 채택하지 않았습니다.

| 측정 | 회차 | 부하 규약 | 결과 |
| --- | :---: | :---: | --- |
| Arq Docker synthetic | 3 | 통과 | 1,681~1,764 jobs/sec, P95 325~342ms |
| RAG 구간 분리 | 1 (20질의) | **위반, 기각** | 부하 median 36.15%. 재측정본은 [`llm_model_comparison_e4b_e2b_20260824.md`](llm_model_comparison_e4b_e2b_20260824.md) |
| Ollama Predict c4 / SSE c1 / Query c1 | 3 (+기각 1) | 통과 | 게이트 전 항목 달성 |

---

## 1. 측정 도중 발견한 하네스 결함 (수정함)

**첫 Arq 3회 시도가 2회차에서 fail-closed 로 중단됐습니다.** 원인이 하네스
자신이었습니다. 1회차가 `data/benchmarks/` 에 회차별 raw 를 쓰자 그 미추적
파일이 워크트리를 dirty 로 만들었고, 2회차의 source provenance 검사가 자기
산출물 때문에 측정을 거부했습니다.

    Provenance 검증 실패: Host/Git provenance check failed (fail-closed):
    git_dirty(source: /Users/kwanbum/.../refac_bid_box)

**`--repetitions` 가 구조적으로 완주할 수 없는 상태였습니다.** 감사가 요구한
"회차별 raw 보존" 자체가 불가능했습니다.

`is_source_dirty()` 를 `benchmark_provenance.py` 에 두어 `data/benchmarks/`
아래 **미추적 파일만** dirty 판정에서 제외했습니다. 추적 파일의 변경과 그 밖의
미추적 파일은 그대로 dirty 로 봅니다. 미추적 `.py` 가 import 될 수 있으므로
미추적 전체를 무시하지 않습니다. 두 Arq 하네스에 중복돼 있던 `get_git_status`
의 판정도 이 공통 함수로 모았습니다. 회귀 테스트 7건을 추가했습니다(`a9165f0`).

---

## 2. Arq Docker synthetic 3회

측정 대상은 **합성 noop 작업의 Arq 큐 경로**입니다. 운영 업무 태스크
(`collect_bids_task`, `update_kb_task`, 재학습)의 성능이 아닙니다.
`scripts/_bench_worker_settings.WorkerSettings` 를 쓰며 운영
`src/tasks/worker.py` 를 그대로 실행하지 않습니다.

| 회차 | 처리량 (jobs/sec) | P50 (ms) | P95 (ms) | P99 (ms) | 성공/실패 |
| :---: | ---: | ---: | ---: | ---: | :---: |
| r1 | 1,718.56 | 211.32 | 334.25 | 344.93 | 600 / 0 |
| r2 | 1,681.27 | 221.91 | 342.30 | 353.35 | 600 / 0 |
| r3 | 1,764.25 | 205.15 | 325.70 | 336.35 | 600 / 0 |

- 처리량 변동폭 4.9%, P95 변동폭 5.1%
- 잠정 일관성 봉투(900 jobs/sec, 600ms P95) 대비 전 회차 여유
- 회차별 raw: `data/benchmarks/arq_container_measure_20260824_r{1,2,3}.json`
- 대표 raw: `data/benchmarks/arq_container_measure_20260824.json`

**봉투를 정식 기준선으로 승격하지 않습니다.** 캘리브레이션 절차가 아직
실행되지 않았습니다. 3 장을 보십시오.

측정 시 1m load 는 26.9% / 24.1% / 40.7% 였습니다(14 코어). 회차 간 중앙
26.9%, 최대 40.7% 로 median 30% / max 50% 를 만족합니다. r3 의 상승은 당시
병렬로 돌던 읽기 전용 워커 2대의 영향입니다.

---

## 3. Arq 캘리브레이션 설계는 아직 그대로 실행할 수 없습니다

별도 Task 로 작성한 설계서
([`arq_calibration_design_20260824.md`](arq_calibration_design_20260824.md))를
실행 가능성 관점에서 대조한 결과
([`calibration_executability_20260824.md`](calibration_executability_20260824.md)),
**하네스 외부 수동 절차나 코드 수정이 필요한 지점이 7건** 있습니다. 대표적으로
호스트 부하 규약을 하네스가 기록만 하고 자동 거부하지 않으며, frozen baseline
대표값 선정식이 하네스의 자동 저장 방식(P95 최악값)과 다릅니다.

**따라서 이번 3회 측정은 캘리브레이션 런이 아닙니다.** 잠정 봉투는 그대로
유지합니다.

---

## 4. RAG 구간 분리 (강화 하네스)

`--expected-llm-model gemma4:e4b --strict` 로 20회 질의했고 20/20 레코드,
오류 0, exit 0 입니다. 런타임 모델 대조, HTTP 대상과 컨테이너 결박, 응답
trace 와 로그 1:1 대조가 모두 적용된 상태의 측정입니다.

| 구간 | P50 (ms) | P95 (ms) | max (ms) |
| --- | ---: | ---: | ---: |
| plan | 0.11 | 0.39 | 0.48 |
| sql | 0.00 | 76.24 | 1,216.14 |
| vector | 76.50 | 351.36 | 4,978.73 |
| kb | 0.00 | 0.00 | 0.00 |
| assembly | 0.09 | 0.22 | 0.33 |
| **llm** | **3,681.90** | **6,064.15** | 7,077.94 |
| guard | 0.06 | 0.31 | 0.47 |
| total | 3,762.48 | 7,284.70 | 9,160.40 |
| residual | 0.03 | 1.57 | 30.04 |

- **`llm_ms` 가 총합 P50 의 97.9%** 입니다. 다만 **이 회차는 주변 부하 median
  36.15% 로 규약을 넘겨 뒤에 기각했습니다.** 부하 규약을 지킨 정본은 97.5%,
  `llm_ms` P50 2,839.93ms 이며 [`llm_model_comparison_e4b_e2b_20260824.md`](llm_model_comparison_e4b_e2b_20260824.md) 에 있습니다
- `residual_ms` P50 0.03ms 로 계측 사각지대가 없습니다
- 원시: `data/benchmarks/rag_segments_e4b_20260824.json`

**LLM 경로가 유일한 유효 최적화 축이라는 판단이 이 측정으로 뒷받침됩니다.**
`vector_ms` max 4,978ms 는 콜드 로드 표본이며 P50 76ms 와 대비됩니다. 단일
표본으로 벡터 검색을 병목으로 지목하지 마십시오.

---

## 5. Ollama gemma4:e4b (Predict c4 / SSE c1 / Query c1)

**동시성이 항목마다 다릅니다.** 예측만 c4 이고 SSE 와 단발 질의는 순차(c1)
입니다. 이 측정을 "c4 기준선" 으로 뭉뚱그리지 마십시오. SSE 게이트 3초/20초는
c1 기준이며 c2 이상 기준은 아직 없습니다.

### 5.1 부하 규약 판정

| 회차 | median | max | 판정 |
| :---: | ---: | ---: | :---: |
| r1 | 26.44% | 34.86% | 통과 |
| ~~r2 (1차)~~ | ~~34.26%~~ | ~~49.62%~~ | **기각** |
| r2 (재측정) | 20.89% | 36.54% | 통과 |
| r3 | 25.68% | 32.10% | 통과 |

**1차 r2 는 median 30% 를 넘겨 규약대로 버렸습니다.** 기각 사실을 남기기 위해
`data/benchmarks/ollama_e4b_20260824_r2_discarded_ambient_load.json` 으로
보존했습니다. 삭제하지 마십시오. 기각 이력이 사라집니다.

### 5.2 결과

| 지표 | r1 P50 | r1 P95 | r2 P50 | r2 P95 | r3 P50 | r3 P95 | 게이트 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| SSE 첫 토큰 (c1) | 1.02s | 1.20s | 634ms | 1.18s | 628ms | 1.18s | P95 3.00s | 통과 |
| SSE 완료 (c1) | 3.97s | 6.83s | 2.73s | 7.15s | 3.52s | 7.77s | P95 20.00s | 통과 |
| 예측 API (c4, n=100) | 28.5ms | 32.4ms | 29.6ms | 37.4ms | 29.0ms | 37.9ms | P95 100ms | 통과 |
| 단발 질의 (c1, n=10) | 4.50s | 6.55s | 4.72s | 7.56s | 2.85s | 7.95s | - | - |

- SSE 첫 토큰 P95 는 3회 모두 1.2s 부근으로 안정적입니다
- SSE 완료 P95 는 6.83~7.77s 로 게이트의 3분의 1 수준입니다
- 예측 API P95 최악 37.9ms 로 게이트 100ms 에 여유가 큽니다
- 회차별 raw: `data/benchmarks/ollama_e4b_20260824_r{1,2,3}.json`

### 5.3 provenance

3회 전부 `target_source_git_dirty: false`, `OLLAMA_MODEL: gemma4:e4b`,
`LATENCY_SEGMENT_LOGGING: true` 로 기록됐습니다. 측정 대상 소스는 `a9165f0`
입니다.

---

## 6. 남은 것

| 항목 | 상태 |
| --- | --- |
| Arq 정식 기준선 캘리브레이션 | 설계 완료, 실행 불가 지점 7건 해소 후 수행 |
| LLM 후보 모델(`gemma4:e2b`) 속도·품질 비교 | 착수 가능. 기준선은 4 장이 대신함 |
| Windows Docker Desktop 실기 | 장비 부재로 차단 |
| G3 전체 컷오버 판정 | 위 3건 종료 후 |

`gemma4:e2b` 는 이미 호스트에 있습니다. 비교 시 `.env` 의 `OLLAMA_MODEL` 을
바꾸고 `docker compose up -d --force-recreate app` 으로 재생성한 뒤
`--expected-llm-model gemma4:e2b` 를 반드시 지정하십시오. `restart` 는 Compose
환경을 다시 주입하지 않습니다.

---

## 7. 알려진 잡음

`benchmark_latency.py` 가 Docker inspect 중
`<.NetworkSettings.IPAddress>: map has no entry for key "IPAddress"` 경고를
표준 출력에 냅니다. 측정과 provenance 기록에는 영향이 없으나 로그가
지저분해집니다. 컨테이너가 사용자 정의 네트워크에 있어 최상위 `IPAddress` 가
비어 있기 때문입니다.
