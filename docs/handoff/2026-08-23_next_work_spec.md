# 잔여 과업 명세 (2026-08-23 세션 종료 시점)

> **작성일**: 2026-08-23 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **기준 커밋**: `684b437` (`origin/main` 동기화 완료)
> **현재 정본**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)
> **성격**: 다음 세션이 바로 착수할 수 있도록 과업마다 착수 조건, 절차, 완료 기준을 명세합니다

---

## 0. 우선순위 요약

| 순위 | 과업 | 차단 요인 | 예상 |
| :---: | --- | --- | --- |
| 1 | LLM 경로 최적화 비교 측정 | 없음 | 60~90분 |
| 2 | Windows CI 실제 green 확인 | 원격 CI 접근 | 20분 |
| 3 | Arq 정식 기준선 캘리브레이션 | 설계 필요 | 60분 |
| 4 | 프론트엔드 HTMX 도입 여부 결정 | **사용자 결정** | 결정 후 4~6시간 |
| 5 | Windows Docker Desktop 실기 | **장비 부재** | 장비 확보 후 |
| 6 | G3 전체 컷오버 판정 | 1~5 종료 | 60분 |

---

## 1. LLM 경로 최적화 비교 측정 (최우선)

### 1.1 착수 근거

2026-08-23 구간 실측에서 단발 질의 지연의 **97.6% 가 `llm_ms`** 임이 확정됐습니다
([`rag_segments_measure_20260823.md`](../analysis/rag_segments_measure_20260823.md)).
RAG 준비 전체가 P50 70ms 미만이라 그쪽은 손댈 이유가 없습니다. **LLM 경로가
유일한 유효 최적화 축입니다.**

### 1.2 후보와 근거

| 후보 | 근거 | 위험 |
| --- | --- | --- |
| `gemma4:e2b` (7.16GB) 교체 | 현재 `gemma4:e4b` 9.61GB. 이미 호스트에 있음 | 답변 품질 저하. 반드시 품질 비교 동반 |
| 출력 토큰 상한 조정 | `llm_ms` P50 3,227ms 대 P95 5,688ms 편차가 생성 길이에 비례할 가능성 | 답변 잘림 |
| 스트리밍 우선 응답 | SSE 첫 토큰 P95 는 이미 1,876ms 로 게이트 통과 | 단발 API 에는 미적용 |

### 1.3 절차

```bash
docker compose up -d app redis
curl -s http://localhost:8000/api/v1/health/ready    # ready 확인

# 기존 gemma4:e4b 결과는 진단용이며 강화된 하네스로 다시 측정합니다

# 후보 모델로 교체 측정
# .env 의 OLLAMA_MODEL 을 바꾸고 LATENCY_SEGMENT_LOGGING=true 를 임시 추가
# restart는 Compose 환경을 다시 적용하지 않으므로 컨테이너를 재생성합니다
docker compose up -d --force-recreate app
uv run python scripts/benchmark_rag_segments.py \
  --base-url http://127.0.0.1:8000 \
  --target-container refac_bid_box-app-1 \
  --expected-llm-model <모델> \
  --rounds 20 \
  --output data/benchmarks/rag_segments_<모델>_<날짜>.json

# .env 를 원복하고 app 컨테이너 재생성
```

### 1.4 완료 기준

- 기준선과 후보를 **같은 하네스, 같은 rounds** 로 측정하고 회차별 원시 JSON 을 모두 보존
- `llm_ms` P50·P95 개선폭을 수치로 제시
- **답변 품질 비교를 반드시 동반.** 속도만 보고 승격하지 않습니다
- `residual_ms` 가 여전히 0 에 수렴하는지 확인 (계측 사각지대 없음의 근거)

### 1.5 함정

- **단일 표본으로 판정하지 마십시오.** 2026-08-23 에 확인용 1회 질의에서
  `vector_ms=2,417ms` 가 나와 벡터 검색이 병목처럼 보였으나, 워밍 20회에서는
  69ms 였습니다. 재기동 직후 첫 질의는 콜드 로드 비용을 포함합니다
- 측정 중 다른 무엇도 Ollama 를 건드리면 안 됩니다. Ollama 는 생성을
  직렬화하므로 동시 요청이 상대 P95 에 섞입니다

---

## 2. Windows CI 실제 green 확인

### 2.1 상태

`tests/test_orca_trust_worktree.py` 의 `os.fork()` 는 2026-08-23 에 제거하고
OS advisory lock(POSIX `fcntl.flock`, Windows `msvcrt.locking`) 기반으로
재작성했습니다. **그러나 원격 Windows CI 가 실제로 green 인지는 미확인입니다.**

### 2.2 절차

```bash
gh run list --branch main --limit 5
gh run view <run-id>            # windows-latest job 결과 확인
```

### 2.3 완료 기준

- 최신 `main` 커밋에 대한 `windows-latest` job 이 success
- 성공하면 [`cross_platform_guide.md`](../ops/cross_platform_guide.md) 의 상태 줄과
  체크리스트, [`CURRENT_STATE.md`](../context/CURRENT_STATE.md) 의 G2 항목을 함께 갱신
- 실패하면 실패 원인을 새 과업으로 세우고 G2 표기는 그대로 둡니다

---

## 3. Arq 정식 기준선 캘리브레이션

### 3.1 상태

절대 기준선 900 jobs/sec, 600ms P95 는 **사후 보정임이 확인**되어 잠정 일관성
봉투(provisional consistency envelope)로 개명했습니다
([`arq_threshold_derivation_20260823.md`](../analysis/arq_threshold_derivation_20260823.md)).
저장소의 어떤 측정에서도 일관된 도출 계수가 나오지 않습니다. `900/jps` 는
0.550~0.812, `600/p95` 는 1.156~1.702 로 흩어집니다.

### 3.2 필요한 것

**고정 조건 캘리브레이션 런**입니다. 다음을 모두 고정하고 충분한 회차를 돌려
frozen baseline 을 만든 뒤, 거기서 계수를 곱해 기준선을 도출합니다.

| 고정 대상 | 이유 |
| --- | --- |
| host load | 2026-08-23 실측에서 회차별 1m load 가 2.54~3.67 로 흔들렸습니다 |
| Redis 컨테이너·이미지 | provenance 로 이미 기록됩니다 |
| 워커 경로 | 컨테이너와 in-process 는 성능이 다릅니다 (1,636 대 966 jps) |
| `max_jobs`, 동시성 | 운영은 `max_jobs=4` |

### 3.3 완료 기준

- frozen baseline 파일 경로와 계수를 명시한 도출식이 문서에 들어갑니다
- `scripts/arq_gate.py` 의 값을 바꿀지 여부를 그 근거로 판단합니다
- 근거를 못 세우면 잠정 명칭을 유지합니다. **지어내지 마십시오**

---

## 4. 프론트엔드 HTMX 도입 여부 (사용자 결정 대기)

### 4.1 상태

[`FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md) 의 목표는 SSR + HTMX 이나
실제 템플릿은 jQuery 3.7.1 만 로드하고 HTMX 사용이 **0건**입니다. ADR 상태를
`목표 아키텍처 확정 / 구현 미완` 으로 정정해 두었습니다.

계획서는 [`htmx_migration_plan_20260823.md`](../design/htmx_migration_plan_20260823.md)
에 있으며 3안을 되돌리기 비용까지 비교했습니다.

| 안 | 내용 | 권고 |
| --- | --- | --- |
| A | HTMX 전면 도입 | |
| B | 부분 도입 (예측 폼·인증·데이터 로드) | **계획서 권고안** |
| C | ADR 개정, jQuery 유지 | |

### 4.2 다음 행동

**사용자가 안을 고르기 전에는 착수하지 않습니다.** 결정 후 안 B 기준 4~6시간
별도 과업으로 세웁니다.

---

## 5. Windows Docker Desktop 실기 (장비 부재로 차단)

Windows 실기 장비가 없어 진행 불가입니다. **장비 확보 전까지 G3 전체 컷오버를
PASS 로 판정하지 마십시오.** 개별 게이트 PASS 를 컷오버 PASS 로 승격하지 않는
것이 [`CURRENT_STATE.md`](../context/CURRENT_STATE.md) 의 원칙입니다.

---

## 6. G3 전체 컷오버 판정 (1~5 종료 후)

**코디네이터가 직접 판정하며 워커에게 위임하지 않습니다.** diff 와 원시 evidence
를 직접 대조합니다. 판정 근거는 [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
이며, 2026-08-14 이전 문서(예: `phase7_cutover_report_20260804.md`)는 근거로
쓰지 않습니다. 해당 문서에는 HISTORICAL 배너가 붙어 있습니다.

---

## 7. 다음 세션 첫 명령

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git branch --show-current                 # main 인지 반드시 확인
git status --short --branch
git worktree list                         # 주 저장소 하나만 있어야 정상

docker compose ps                         # 전부 내려간 상태로 종료했습니다
docker compose up -d app redis            # 측정이 필요하면
curl -s http://localhost:8000/api/v1/health/ready

python3 scripts/validate_agent_rules.py
uv run pytest tests/ -q -m 'not data_assets'
```

---

## 8. 운영 함정 (이번 세션에서 확인)

1. **워커에게 절대 경로를 주면 그 저장소로 갑니다.** 하루에 워커 4대가 격리
   트리를 벗어났고 하나는 주 저장소에서 브랜치를 만들어 코디네이터의 병합 2건이
   엉뚱한 브랜치에 쌓였습니다. `orca_taskctl.py` 가 이제 기계로 막습니다.
   상세는 [`orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 20장
2. **`git merge` 전에 `git branch --show-current` 를 확인합니다.** 브랜치 삭제
   전에는 `git log --oneline main..<branch>` 를 읽습니다
3. **워커 완료 판정에 공유 자원 반납을 포함합니다.** Arq 벤치마크 워커가 Redis
   컨테이너를 남겨 다음 라운드가 6379 포트 충돌로 10분을 잃었습니다
4. **워커의 succeeded 와 리뷰어의 pass 를 그대로 믿지 마십시오.** 이번 세션에
   리뷰어가 pass 준 브랜치에서 코디네이터가 결함을 두 번 찾았습니다
5. **단일 표본으로 결론짓지 마십시오.** 콜드 1회 값으로 병목을 잘못 지목한
   사례가 이번 세션에만 두 번 있었습니다
6. **Kimi `-p` 는 단발이라 중간 개입이 불가능합니다.** 자족적 Task 에만 주고,
   정체되면 코디네이터가 직접 수행하는 편이 빠릅니다
