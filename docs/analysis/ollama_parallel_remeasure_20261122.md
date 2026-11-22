# Ollama 병렬도 재측정 보고서

> **측정일**: 2026-11-22
> **기준 커밋**: `4cbd0233`
> **대상**: 호스트 Ollama 0.40.17, 모델 `gemma4:e2b`(운영 기본), 개발 맥(Apple M4 Pro, 메모리 24GB)
> **판정**: 병렬도 미설정은 사실상 직렬 처리임을 확인. 챗봇 동시 상한 2를 유지하는 동안은 병렬도 변경 이득이 작아 현행 유지, 상한을 4로 올릴 때 `OLLAMA_NUM_PARALLEL=4` 를 함께 적용
> **선행 측정**: [`docs/ops/sse_rebaseline_and_ollama_parallel_20260814.md`](../ops/sse_rebaseline_and_ollama_parallel_20260814.md)(병렬도 4 측정 중단), [`ollama_c4_measure_20260823.md`](ollama_c4_measure_20260823.md)(주변 부하로 기준선 불가)

---

## 1. 목적

2026-11-20 동시 접속 점검(H1)에서 "챗봇 LLM 이 동시에 1건만 처리한다" 는 판단의 근거가 2026-08-14 측정(당시 다른 모델·버전)뿐이었다. 2026-11-22 챗봇 동시 실행 상한을 보수값 2로 도입하면서(병합 `98c168ba`), 현재 Ollama 버전에서 실제 병렬도와 병렬도 설정의 효과를 다시 재어 상한 값의 근거를 마련한다.

---

## 2. 방법

| 항목 | 내용 |
| --- | --- |
| 비교 대상 | 운영 Ollama(포트 11434, `OLLAMA_NUM_PARALLEL` 미설정), 임시 Ollama 병렬도 2(포트 11435), 병렬도 4(포트 11436) |
| 운영 설정 | 변경하지 않음. 임시 인스턴스는 같은 모델 저장소를 쓰고 측정 뒤 종료 |
| 요청 옵션 | 앱(`src/rag/llm.py` `_payload`)과 같게 `think: false`, `temperature: 0.2`, `keep_alive: -1`. 비교를 위해 `num_predict: 160` |
| 프롬프트 | 시스템 지시 + 근거 문단(약 1,500자) + 질문 4종 순환. 요청마다 고유 문구를 앞에 붙여 프롬프트 캐시 재사용을 막음 |
| 응답 길이 | "다섯 문장으로 자세히" 지시로 평균 118~149토큰 |
| 동시성 | 1, 2, 4(본 측정), 8(1차 탐색). 동시성마다 5회, 운영·병렬도 4를 번갈아 2반복 |
| 지표 | 첫 토큰 시간(TTFT) p50·p95, 전체 응답 시간 p50·p95, 합산 처리량(초당 생성 토큰) |
| 측정 중 상태 | 워커·병합 없음(저장소 고정), 앱 챗봇 요청 없음 |

---

## 3. 결과

### 3.1 확증 측정 (동시성별 5회 × 2반복, 범위는 두 반복의 값)

| 병렬도 | c1 TTFT p50 | c1 전체 p50 | c2 TTFT p95 | c2 전체 p95 | c4 TTFT p95 | c4 전체 p95 | 합산 처리량 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 미설정(운영) | 0.23초 | 1.42~1.60초 | 1.99~2.00초 | 3.18~3.42초 | 5.21~5.55초 | 6.49~6.69초 | 86~89토큰/s, 동시성과 무관 |
| 4 | 0.64초 | 1.76~1.97초 | 1.33~1.39초 | 3.41~4.70초 | 2.59~2.77초 | 5.51~5.73초 | c1 66~70, c4 105~110토큰/s |

### 3.2 1차 탐색 (동시성별 3회)

| 병렬도 | c4 TTFT p95 | c8 TTFT p95 | c8 전체 p95 | c8 합산 처리량 |
| --- | --- | --- | --- | --- |
| 미설정 | 4.97초 | 11.94초 | 13.16초 | 87토큰/s |
| 2 | 4.88초 | 11.53초 | 13.40초 | 88토큰/s |
| 4 | 2.54초 | 7.61초 | 10.08초 | 116토큰/s |

---

## 4. 해석

1. **미설정은 직렬 처리다.** 합산 처리량이 동시성 1·2·4·8 에서 86~89토큰/s 로 고정이다. 동시 요청은 줄을 서며 첫 토큰 대기가 동시성에 비례해 늘어난다(c4 p95 약 5.4초, c8 약 12초). 2026-08-14 의 "Ollama 인스턴스 1개가 생성을 직렬 처리" 판단이 현재 버전에서도 맞다.
2. **병렬도 2는 이득이 없다.** 처리량과 대기 모두 미설정과 같은 수준이다.
3. **병렬도 4는 동시 부하에서만 유리하다.** c4 첫 토큰 p95 가 절반(5.4초 → 2.7초)으로 줄고 합산 처리량이 약 20~25% 늘지만, 단건 첫 토큰이 0.23초에서 0.64초로 늦고 단건 처리량도 낮다.
4. **현재 챗봇 동시 상한 2에서는 변경 이득이 작다.** c2 첫 토큰 p95 는 2.0초 → 1.4초로 줄지만 전체 응답 p95 는 비슷하거나 늦다(3.2~3.4초 대 3.4~4.7초).

---

## 5. 결정과 후속

| 항목 | 내용 |
| --- | --- |
| 현행 | 챗봇 동시 상한 2(`CHATBOT_MAX_CONCURRENT_REQUESTS`), Ollama 병렬도 미설정 유지 |
| 상한 상향 시 | 동시 사용자가 늘어 상한을 4로 올릴 때 `OLLAMA_NUM_PARALLEL=4` 를 함께 적용한다. 대기 첫 토큰 p95 가 절반이 되는 근거는 3.1절 |
| 재측정 | 운영 서버가 정해지면 같은 방법으로 다시 잰다. 결과는 하드웨어(GPU·메모리 대역폭)에 크게 좌우된다 |

---

## 6. 한계

- 개발 맥 한 대에서 잰 값이며, 측정 중 임시 Ollama 인스턴스가 함께 떠 있어 메모리를 나눠 썼다(1차 탐색 3개, 확증 2개).
- 앱을 거치지 않은 Ollama 직접 호출 측정이다. 앱의 근거 준비(SQL·벡터 검색) 시간은 포함하지 않는다.
- 응답 길이를 지시문으로 맞췄으나 요청마다 118~149토큰으로 차이가 있어, 처리량은 합산 토큰 기준으로 비교했다.

---

## 7. 재현

호스트에서 임시 인스턴스를 띄운 뒤 아래 스크립트를 포트별로 실행한다. 운영 Ollama 설정은 바꾸지 않는다.

```bash
OLLAMA_NUM_PARALLEL=4 OLLAMA_HOST=127.0.0.1:11436 OLLAMA_KEEP_ALIVE=-1 ollama serve &
python3 ollama_par_bench.py 11434 1,2,4 5
python3 ollama_par_bench.py 11436 1,2,4 5
```

```python
"""Ollama 동시 요청 벤치마크: 첫 토큰(TTFT)과 전체 응답 시간을 동시성별로 잰다."""
import json
import statistics
import sys
import threading
import time
import urllib.request
import uuid

PORT = int(sys.argv[1])
LEVELS = [int(x) for x in sys.argv[2].split(",")]
ROUNDS = int(sys.argv[3])
URL = f"http://localhost:{PORT}/api/chat"
SYSTEM = "당신은 공공조달 입찰 분석 도우미입니다. 주어진 근거만으로 한국어로 간결하게 답합니다."
CONTEXT = (
    "근거: 최근 5년 인천 용역 낙찰 18,050건, 평균 낙찰률 89.50%. 청소 공고 652건 평균 88.93%. "
    "기관별 상위: 인천광역시 1,203건, 인천국제공항공사 842건, 인천교통공사 611건. "
    "업체별 상위: 가 업체 87건, 나 업체 64건, 다 업체 51건. 월별 추이는 큰 변동이 없다. "
) * 6
QUESTIONS = ["인천 청소 용역 낙찰률을 근거와 함께 설명해 줘", "인천 경비 용역 입찰 전략을 알려줘",
             "인천 용역 낙찰률 추이를 요약해 줘", "인천 위생관리 용역 주요 기관을 알려줘"]


def one(q, out):
    payload = {"model": "gemma4:e2b", "stream": True, "keep_alive": -1, "think": False,
               "options": {"temperature": 0.2, "num_predict": 160},
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": f"요청번호 {uuid.uuid4().hex}\n" + CONTEXT
                             + "\n질문: " + q + " (근거 수치를 들어 다섯 문장으로 자세히)"}]}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); ttft = None; ntok = 0
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:
            if not line.strip():
                continue
            d = json.loads(line)
            if ttft is None and d.get("message", {}).get("content"):
                ttft = time.perf_counter() - t0
            if d.get("done"):
                ntok = d.get("eval_count") or 0
                break
    out.append((ttft or float("nan"), time.perf_counter() - t0, ntok))


def p95(v):
    v = sorted(v); return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]


one(QUESTIONS[0], [])  # 예열
for c in LEVELS:
    res = []
    t_wall = time.perf_counter()
    for r in range(ROUNDS):
        th = [threading.Thread(target=one, args=(QUESTIONS[i % 4], res)) for i in range(c)]
        [t.start() for t in th]; [t.join() for t in th]
    wall = time.perf_counter() - t_wall
    ttft = [x[0] for x in res]; tot = [x[1] for x in res]
    print(f"port={PORT} c={c} n={len(res)} TTFT p50={statistics.median(ttft):.2f}s p95={p95(ttft):.2f}s | "
          f"전체 p50={statistics.median(tot):.2f}s p95={p95(tot):.2f}s | 처리량 {len(res)/wall:.2f}건/s | "
          f"평균 생성 {statistics.mean([x[2] for x in res]):.0f}토큰 | 합산 {sum(x[2] for x in res)/wall:.0f}토큰/s",
          flush=True)
```
