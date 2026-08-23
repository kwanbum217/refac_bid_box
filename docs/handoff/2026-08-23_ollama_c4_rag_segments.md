# Ollama c4 및 RAG 구간 계측 인수인계 (2026-08-23 야간)

> **작성일**: 2026-08-23 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **Orca Run**: `run_a70e06fe0719`
> **사유**: 사용자 장비 가용 시각 21:00 마감. 20:35 하드컷 적용
> **현재 정본**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 이번 라운드 구성

| 트랙 | 과업 | 모델 | 자원 |
| --- | --- | --- | --- |
| A | Ollama `gemma4:e4b` c4 레이턴시 실측 | Antigravity `gemini-3.7-flash-medium` | 완료·병합 |
| B | 단발 RAG 구간 분리 수집 하네스 작성 | Kimi `or-free/nemotron-ultra` -> **코디네이터 직접** | 완료·병합 |

트랙 B 의 Kimi 워커는 착수 19:55 부터 20:13 까지 18분간 설계만 서술하고 파일을
한 개도 만들지 못했습니다. 화면에 같은 문장이 세 번 반복되는 정체 신호가
나타났고 `-p` 단발이라 중간 개입이 불가능해, 사용자 판단으로 중단하고
코디네이터가 직접 작성했습니다. 워커가 남긴 설계 서술 중 "구간 로그는 서버
쪽에서 나오므로 HTTP 응답만으로 수집할 수 없고 `trace_id` 로 조인해야 한다" 는
지적은 정확했고 그대로 구현에 반영했습니다.

**두 측정은 병렬이 불가능합니다.** 둘 다 같은 `app` 컨테이너와 같은 호스트 Ollama
인스턴스를 씁니다. Ollama 는 생성 요청을 직렬화하므로 동시에 돌리면 서로의 대기
시간이 상대 P95 에 섞여 양쪽 수치가 오염됩니다. 자원 경합이 아니라 측정 오염이라
"느려도 병렬" 이 성립하지 않습니다. 그래서 B 는 도구 작성까지만 하고 실측은
다음 세션으로 넘겼습니다.

---

## 2. 측정 환경 실측값

| 항목 | 값 |
| --- | --- |
| 단발 질의 (워밍, 10회 x 3회차) | 최소 2,142ms / 중앙 5,229ms / 최대 9,037ms |
| 단발 질의 P95 (최악 회차) | **8,668.2ms** |
| SSE 첫 토큰 P95 (최악) | **1,876.0ms** |
| SSE 완료 P95 (최악) | **8,579.6ms** |
| 예측 P95 c4 (최악) | **38.2ms** |
| 오류 | 3회 전부 **0건** |
| LLM | Ollama `gemma4:e4b` 9.61GB, 호스트 11434 |
| 기동 서비스 | `app`, `redis`, `db`, `meilisearch` |
| 하네스 기본값 | `--query-rounds 10`, `--sse-rounds 20`, `--predict-rounds 100 --predict-concurrency 10` |

`meilisearch` 는 `app` 의 `depends_on` 으로 자동 기동됐습니다. 코디네이터가
의도한 것은 `app` 과 `redis` 뿐이었습니다.

---

## 3. 착수 전 해결한 장애

**앞선 Arq 컨테이너 벤치마크 워커가 자기가 띄운 Redis 컨테이너를 정리하지 않고
남겼습니다.** Capsule 의 "측정 종료 후 직접 기동한 추가 컨테이너 정리" 조건
위반입니다.

| 증상 | 원인 |
| --- | --- |
| `app` 이 3분 넘게 `health: starting` | compose `redis` 가 6379 바인딩 실패 |
| `redis.exceptions.ConnectionError: Name or service not known` | 바인딩 실패한 `redis` 컨테이너가 네트워크에 미부착 |
| `docker network connect` 도 실패 | 잔존 `arq-docker-measure-redis-1` 이 6379 점유 |

조치: 잔존 컨테이너를 `redis-cli SHUTDOWN NOSAVE` 로 내려 `dump.rdb` 생성을 피한 뒤
제거하고, 그 네트워크도 지우고, compose `redis` 를 재생성했습니다. `app` 이
`ready` 로 전환됐습니다.

**교훈**: 워커 완료를 판정할 때 코드와 문서뿐 아니라 **공유 자원 반납 여부까지
확인해야 합니다.** 이번에는 확인하지 않아 다음 라운드가 10분을 잃었습니다.

---

## 4. 다음 세션 재개 절차

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git branch --show-current            # main 인지 반드시 확인
git status --short --branch
docker compose ps

# 스택 기동 (필요 시)
docker compose up -d app redis
curl -s http://localhost:8000/api/v1/health/ready

# RAG 구간 실측 (트랙 B 하네스가 병합되어 있으면)
# LATENCY_SEGMENT_LOGGING 을 .env 에 임시로 켠 뒤 app 재기동, 측정 후 되돌린다
uv run python scripts/benchmark_rag_segments.py --help
```

`LATENCY_SEGMENT_LOGGING` 은 `.env` 에 없습니다. 측정 중에만 켜고 끝나면 되돌리는
것이 사용자 결정입니다. 운영 기본값을 바꾸지 마십시오.

---

## 5. 남은 과업

| 순위 | 과업 | 차단 요인 |
| --- | --- | --- |
| 1 | ~~단발 RAG 구간 실측~~ | **2026-08-23 종결.** `llm_ms` 가 97.6% ([`rag_segments_measure_20260823.md`](../analysis/rag_segments_measure_20260823.md)) |
| 1-2 | **LLM 경로 최적화** | RAG 준비는 2.1% 미만이라 손댈 이유가 없습니다. 모델 크기, 양자화, 출력 토큰만 유효합니다 |
| 2 | Arq 정식 기준선 캘리브레이션 | 잠정 일관성 봉투가 사후 보정임이 확인됨. 고정 조건 런 설계 필요 |
| 3 | Windows CI 실제 green 확인 | `os.fork()` 는 제거됐으나 원격 CI 결과 미확인 |
| 4 | Windows Docker Desktop 실기 | **장비 부재로 차단** |
| 5 | 프론트엔드 HTMX 도입 여부 | **사용자 결정 대기.** 권고안은 안 B 부분 도입 |
| 6 | G3 전체 컷오버 판정 | 위 종료 후. 코디네이터가 직접 판정하며 위임하지 않음 |

---

## 6. 컨테이너 상태

이번 세션에서 `app`, `redis`, `meilisearch` 를 기동했고 `db` 는 이전부터 떠
있었습니다. 사용자 장비 종료로 함께 내려갑니다. 다음 세션에서 다시 기동하십시오.

---

## 7. 콜드 스타트 가설 기각

단발 질의가 느린 원인이 Ollama 모델 로딩 아니냐는 물음이 있었고, r1 데이터로
확인한 결과 **콜드 스타트로는 설명되지 않습니다.**

```
3014.8  2680.9  9036.8  5303.3  5476.2  ...  4455.8  2142.1  6713.0  5155.3  5964.8
```

- 첫 요청 3,015ms 가 중앙값 5,303ms 보다 오히려 빠릅니다
- 최대 9,037ms 는 첫 번째가 아니라 세 번째에 나옵니다
- 끝부분에도 6,713ms 가 나옵니다

워밍업 곡선이 아니라 전 구간에 흩어진 변동입니다. 측정 시작 70초 전에 질의를
한 번 보내 콜드 스타트 비용은 이미 소진된 상태였습니다.

따라서 다음 질문은 "모델 로딩인가" 가 아니라 **"워밍 상태에서 2.1초와 9.0초를
가르는 것이 LLM 생성인가 RAG 준비인가"** 입니다. 이것이 RAG 구간 하네스가
답할 질문입니다.

---

## 8. provenance 체인 검증

이번 측정이 2026-08-23 에 구축한 provenance 체인 전체를 실제로 검증했습니다.
r1 evidence 의 `meta` 에 다음이 자동 기록됐습니다.

| 키 | 값 | 출처 |
| --- | --- | --- |
| `bound_port` | 8000 | P1 base_url 컨테이너 결박 |
| `provenance_consistent` | True | 시작·종료 교체 무효화 |
| `target_source_mount` | 주 저장소 `/src` | 런타임 소스 provenance |
| `target_source_git_sha` | `1331e35...` | 동일 |
| `target_source_git_dirty` | False | dirty 거부 게이트 |
| `perf_config.LLM_PROVIDER` | `ollama` | 성능 설정 스냅샷 |
| `perf_config.OLLAMA_MODEL` | `gemma4:e4b` | 동일 |

허용 목록 밖 비밀값은 하나도 담기지 않았습니다.

---

## 9. 단발 RAG 구간 실측 결과 (같은 날 후속 수행)

`.env` 에 `LATENCY_SEGMENT_LOGGING` 을 임시로 켜고 20회 측정한 뒤 원복했습니다.
백업과 완전 일치를 확인했습니다.

| 구간 | P50 (ms) | P95 (ms) | P50 비중 |
| --- | ---: | ---: | ---: |
| `llm_ms` | 3,226.7 | 5,688.4 | **97.6%** |
| `vector_ms` | 69.2 | 113.7 | 2.1% |
| `sql_ms` | 0.0 | 26.4 | 0.0% |
| `residual_ms` | 0.0 | 0.1 | 0.0% |

측정을 막고 있던 결함 두 가지를 함께 고쳤습니다.

1. **계측 로그가 애초에 나가지 못했습니다.** 컨테이너 루트 로거가 WARNING 이고
   핸들러가 없어 `logger.info` 가 필터링됐습니다. 플래그를 켜도 한 줄도 나오지
   않았고, 이것이 2026-08-22 계측이 실측에 쓰이지 못한 진짜 이유입니다.
2. **하네스가 `docker logs --since` 에 타임존 없는 UTC 를 넘겼습니다.** docker 가
   로컬(KST)로 해석해 9시간 과거 로그가 섞일 수 있었습니다.

**단일 표본으로 결론짓지 마십시오.** 측정 직전 확인용 질의 1회에서
`vector_ms=2,417ms` 가 나와 벡터 검색이 LLM 과 대등해 보였으나, 그것은 재기동
직후 벡터 인덱스 콜드 로드였고 워밍 20회에서는 69ms 였습니다.
