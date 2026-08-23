# 단발 질의 RAG 구간 실측 (2026-08-23)

> **작성일**: 2026-08-23 (Asia/Seoul)
> **하네스**: [`scripts/benchmark_rag_segments.py`](../../scripts/benchmark_rag_segments.py)
> **원시 증거**: [`data/benchmarks/rag_segments_20260823.json`](../../data/benchmarks/rag_segments_20260823.json)
> **표본**: 단발 질의 20회, 오류 0건, 구간 레코드 20건

---

## 1. 결과

| 구간 | P50 (ms) | P95 (ms) | 최대 (ms) | P50 비중 |
| --- | ---: | ---: | ---: | ---: |
| `plan_ms` | 0.1 | 0.2 | 0.2 | 0.0% |
| `sql_ms` | 0.0 | 26.4 | 33.7 | 0.0% |
| `vector_ms` | 69.2 | 113.7 | 140.3 | 2.1% |
| `kb_ms` | 0.0 | 0.0 | 0.0 | 0.0% |
| `assembly_ms` | 0.1 | 0.1 | 0.2 | 0.0% |
| **`llm_ms`** | **3,226.7** | **5,688.4** | **6,896.3** | **97.6%** |
| `guard_ms` | 0.0 | 0.2 | 0.8 | 0.0% |
| `residual_ms` | 0.0 | 0.1 | 0.1 | 0.0% |
| `total_ms` | 3,305.1 | 5,756.9 | 6,963.0 | |

---

## 2. 판정

**단발 질의 지연의 97.6% 는 LLM 생성(`llm_ms`)입니다.** RAG 준비 전체
(`plan` + `sql` + `vector` + `kb` + `assembly`)를 합쳐도 P50 기준 70ms 미만이며
2.1% 를 넘지 않습니다.

따라서 다음이 확정됩니다.

| 최적화 방향 | 판정 |
| --- | --- |
| RAG 준비 경로(SQL, 벡터 검색, 프롬프트 조립) 개선 | **효과 없음.** 전체의 2% 미만 |
| LLM 경로(모델 크기, 양자화, 스트리밍, 토큰 수) 개선 | **유일하게 유효** |

2026-08-23 Ollama c4 실측에서 워밍 상태 단발 질의가 2.1~9.0초로 4배 흔들렸던
원인도 `llm_ms` 입니다. `llm_ms` 의 P50 3,226.7ms 대 P95 5,688.4ms 비율이
전체 분포의 편차를 그대로 설명합니다.

`residual_ms` 가 P95 에서 0.1ms 이므로 계측되지 않은 구간은 없습니다. 위
결론에 사각지대가 없다는 뜻입니다.

---

## 3. 측정 전에 고친 결함 두 가지

### 3.1 계측 로그가 애초에 나가지 못했습니다

`src/rag/engine.py` 의 구간 계측은 2026-08-22 에 들어갔으나 오늘까지 한 번도
실측에 쓰이지 못했습니다. 원인은 하네스 부재만이 아니었습니다.

```
LATENCY_SEGMENT_LOGGING = True
logger effective level = 30 (WARNING)
INFO 통과? False
```

계측은 `logger.info` 로 나가는데 컨테이너 런타임의 루트 로거가 WARNING 이고
핸들러가 없어, **플래그를 켜도 로그가 한 줄도 나오지 않았습니다.**
`src/app/main.py` 의 lifespan 에서 플래그가 켜진 경우에만 해당 로거의 레벨과
핸들러를 보강하도록 고쳤습니다. 플래그가 꺼져 있으면 아무것도 바꾸지 않습니다.

### 3.2 `docker logs --since` 가 타임존 없이 전달됐습니다

하네스가 UTC 시각을 타임존 표기 없이 넘겨, docker 가 이를 로컬 시각(KST)으로
해석했습니다. 9시간 과거부터의 로그가 집계에 섞일 수 있었습니다. `Z` 를 붙이고
회귀 테스트 2건을 추가했습니다.

---

## 4. 단일 표본으로 결론짓지 마십시오

측정 직전 확인용으로 보낸 질의 1회에서 `vector_ms=2,417ms`, `llm_ms=2,728ms`
가 나와 벡터 검색이 LLM 과 대등해 보였습니다. **틀린 관측이었습니다.** 그것은
컨테이너 재기동 직후 첫 질의의 벡터 인덱스 콜드 로드 비용이며, 워밍 20회
분포에서 `vector_ms` 는 P50 69.2ms 로 떨어집니다.

같은 이유로 앞서 "단발 질의 10.25초" 도 콜드 단일 표본이었고 워밍 중앙값은
3.3~5.2초입니다.

---

## 5. 재현 절차

`LATENCY_SEGMENT_LOGGING` 은 `.env` 의 운영 기본값이 아닙니다. 측정 중에만 켜고
끝나면 되돌립니다.

```bash
docker compose up -d app redis
# .env 에 LATENCY_SEGMENT_LOGGING=true 를 임시로 추가
docker compose restart app
curl -s http://localhost:8000/api/v1/health/ready

uv run python scripts/benchmark_rag_segments.py \
  --base-url http://127.0.0.1:8000 \
  --target-container refac_bid_box-app-1 \
  --rounds 20 \
  --output data/benchmarks/rag_segments_<날짜>.json

# .env 를 원복하고 app 재기동
```

---

## 6. 후속 과업

`llm_ms` 가 유일한 유효 최적화 축이므로 다음을 검토합니다.

| 후보 | 근거 |
| --- | --- |
| 더 작은 모델 (`gemma4:e2b` 7.16GB) | 현재 `gemma4:e4b` 9.61GB |
| 출력 토큰 상한 조정 | `llm_ms` 편차가 생성 길이에 비례할 가능성 |
| 스트리밍 우선 응답 | 첫 토큰 P95 는 이미 1,876ms 로 게이트 통과 |

비교 측정은 반드시 같은 하네스로 수행하고 회차별 원시 JSON 을 모두 보존합니다.
