# ChromaDB 클라이언트 싱글턴 전환 실측 (2026-11-11)

> 근거: `docs/analysis/feat_review_repro_20261111.md` (I-ai F-14 재현됨), AGENTS.md G3
> 범위: `src/rag/vector_store.py` 질의 경로, `src/app/api/v1/health.py` 헬스체크

## 변경

- `src/rag/chroma_client.py` 에 `get_chroma_client()`, `get_default_collection()`,
  `reset_chroma_client()` 를 두어 클라이언트와 기본 컬렉션 핸들을 프로세스 단위로 재사용한다.
- 컬렉션은 `embeddings.get_collection` 을 거쳐 bge-m3 임베딩 함수로 연다.
- 색인 전량 재구축 뒤 낡은 핸들이면 컬렉션 부재 계열 오류에서 한 번만 다시 연다.
- `kb_builder.py` 는 쓰기 경로라 이번 과업에서 바꾸지 않았다.

## 측정 방법

- `tests/test_chroma_client_singleton_20261111.py::test_query_latency_before_and_after`
- `tmp_path` 에 20건 컬렉션을 만들고 같은 질의를 top-5 로 조회한다.
- 워밍업 3회 뒤 전·후 각 40회를 재고 최근접 순위(nearest-rank) 백분위를 쓴다.
- 운영 `chroma_db/` 와 Redis 는 읽지도 쓰지도 않는다. 질의 결과 ID 동일성도 함께 단언한다.

## 결과

| 경로 | 회차 | P50 (ms) | P95 (ms) |
| --- | --- | --- | --- |
| 전: 요청마다 `PersistentClient` + `get_collection` | 40 | 1.326 | 1.524 |
| 후: 프로세스 접근자의 컬렉션 핸들 재사용 | 40 | 0.597 | 0.685 |

환경: macOS-27.2, Python 3.13.15, chromadb 0.6.3, 로컬 pytest 실행.
반복 실행에서도 전 P50 1.33~1.54ms, 후 P50 0.60~0.69ms 로 같은 방향이었다.

## 해석

- 요청마다 반복되던 클라이언트·컬렉션 생성 고정 비용이 사라져 P50 기준 약 55% 줄었다.
- 줄어든 것은 고정 비용이며 질의 자체(임베딩·HNSW) 비용은 그대로다.
- 컬렉션 규모와 무관한 비용이므로 운영 컬렉션에서도 같은 크기로 줄어든다.
