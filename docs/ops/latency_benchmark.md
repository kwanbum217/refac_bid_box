# 레이턴시 벤치마크 결과

> **작성일**: 2026-08-02
> **버전**: v1.0.0
> **상태**: 기준선 측정 완료, 목표 2건 미달
> **측정 도구**: [`scripts/benchmark_latency.py`](../../scripts/benchmark_latency.py) (`make benchmark`)

---

## 1. 측정 조건

실제로 기동 중인 서버에 HTTP 로 붙어 측정합니다. `TestClient` 는 ASGI 를 인프로세스로 호출해 네트워크와 이벤트 루프 경합을 건너뛰므로 체감 레이턴시를 재지 못합니다.

| 항목 | 값 |
| --- | --- |
| 측정일 | 2026-08-02 |
| 서버 | uvicorn 단일 워커, `127.0.0.1:8000` |
| DB | MariaDB 12.3 (`bid_announcements` 1,839,088행 / `bid_results` 3,002,254행) |
| LLM | Ollama `gemma4:e4b` (로컬) |
| 표본 | SSE 15회, 예측 API 200회 |
| 질의 | 5종 순환 (캐시 적중 회피) |

---

## 2. 결과

| 구간 | P50 | P95 | P99 | 목표 | 판정 |
| --- | ---: | ---: | ---: | ---: | --- |
| SSE 첫 토큰 | 10.35s | 42.83s | 43.01s | P95 3s | **미달** |
| SSE 전체 응답 | 10.65s | 43.03s | 43.21s | P95 20s | **미달** |
| 낙찰가 예측 API | 0.7ms | 1.0ms | 1.5ms | P95 100ms | 달성 |

예측 API 는 목표 대비 **100배 여유**입니다. 앱 시작 시 싱글톤 모델 로드(설계서 133행)가 의도대로 동작합니다.

---

## 3. 미달 원인 두 가지

### 3.1 SSE 가 실제 스트리밍이 아님

첫 토큰 P50 10.35초, 전체 P50 10.65초로 **차이가 0.3초뿐**입니다. 스트리밍의 체감 개선 효과가 사실상 없습니다.

`HybridRAGEngine.stream_tokens` (`src/rag/engine.py:799`)가 원인입니다.

```python
bundle = await self.get_answer(...)      # 답변을 전부 생성한 뒤
yield {"type": "docs", ...}
for i in range(0, len(text), chunk_size):
    yield {"type": "token", "text": text[i : i + chunk_size]}   # 완성본을 40자씩 자름
```

LLM 백엔드(`src/rag/llm.py`)도 `"stream": False` 로 호출합니다. 구조상 첫 토큰이 전체 생성 완료보다 빨라질 수 없습니다.

설계서 651행이 SSE 목표를 세운 이유가 "LLM 절대 시간이 늘었으니 체감 레이턴시로 만회한다" 였는데, 그 만회 장치가 동작하지 않는 상태입니다.

### 3.2 집계 질의 SQL 이 33초

질의별로 분해하면 P95 를 끌어올린 것은 특정 질의 하나입니다.

| 질의 | SSE 전체 |
| --- | ---: |
| 2025년 물품 낙찰 평균 낙찰률 알려줘 | 43.26s / 42.93s / 42.60s |
| 수요기관별 낙찰 금액 상위는 어디야 | 15.28s / 13.07s |
| 적격심사 기준이 어떻게 되나요 | 약 9s |

느린 질의를 단계별로 나눈 결과입니다.

| 단계 | 소요 |
| --- | ---: |
| 검색 계획 수립 | 0.00s |
| **SQL 검색** | **33.00s** |
| 벡터 검색 | 0.00s |
| LLM 생성 | 9.59s |

LLM 이 아니라 **SQL 이 병목**입니다. 컨텍스트는 377자에 불과합니다.

`retrieve_structured_data` 가 던지는 6개 쿼리 중 3개가 전체 시간을 씁니다.

| 쿼리 | 소요 | EXPLAIN |
| --- | ---: | --- |
| `bid_results` 낙찰업체 상위5 | 8.77s | `range` / `Using temporary; Using filesort` / 약 162만행 |
| `bid_announcements` 수요기관 상위5 | 10.43s | `range` / `Using temporary; Using filesort` / 약 187만행 |
| `bid_announcements` 공고명 상위5 | 12.15s | `range` / `Using temporary; Using filesort` / 약 187만행 |
| 낙찰 집계(count/avg/sum) | 1.60s | - |
| 공고 건수 | 0.15s | - |
| 최근 공고 3건 | 0.00s | - |

세 쿼리 모두 `category` 로 걸러낸 뒤 고카디널리티 문자열 컬럼으로 `GROUP BY` 합니다. 현재 인덱스는 `category` 단일 컬럼이라 범위를 좁힌 뒤 임시 테이블과 파일소트로 집계합니다.

`category` 는 값이 3종뿐이라(`Cnstwk` 125만, `Servc` 89만, `Thng` 86만) 단일 컬럼 인덱스로는 거의 걸러지지 않습니다.

---

## 4. 개선 방향

| 대상 | 방법 | 예상 효과 |
| --- | --- | --- |
| SQL 집계 | `(category, bidwinnr_nm)`, `(category, dminstt_nm)`, `(category, bid_ntce_nm)` 복합 인덱스 | 임시 테이블/파일소트 제거 |
| SQL 집계 (대안) | `bid_dataset_summaries` 처럼 상위 N 스냅샷을 미리 집계 | 조회를 상수 시간으로 |
| SSE | Ollama `/api/chat` 을 `stream: True` 로 호출하고 토큰을 그대로 흘려보냄 | 첫 토큰을 생성 완료와 분리 |

복합 인덱스는 원본 Django 스키마에 없는 것이라 추가 시 [`django_migration_history.md`](../migration/django_migration_history.md) 기준선 이후의 Alembic 리비전으로 관리하고, `tests/test_model_schema_parity.py` 의 `PRODUCTION_INDEX_NAMES` 를 함께 갱신해야 합니다.

SSE 진짜 스트리밍은 답변 후처리(Answer Guard, 카테고리 표기 정규화)가 완성본을 전제로 하므로, 스트리밍 중 교정이 필요한 경우를 어떻게 다룰지 결정이 필요합니다.

---

## 5. 재현 방법

```bash
redis-server --port 6379 --daemonize yes --save ''
.venv/bin/python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000 &
make benchmark
```

옵션으로 표본 수를 조절합니다.

```bash
python scripts/benchmark_latency.py --sse-rounds 15 --predict-rounds 200 --query-rounds 8
```
