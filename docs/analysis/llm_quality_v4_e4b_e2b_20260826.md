# LLM 품질 v4 재측정 및 gemma4:e2b 승격 (거절 지시·fixture 확대 반영)

> **측정일**: 2026-08-26
> **소스**: `b4913fd` (dirty=false, 시작·종료 동일)
> **canonical**: true (양쪽)
> **fixture**: `data/eval/llm_quality_fixture_v1.json` (24문항, context_sufficient 16, refusal_expected 8)
> **조건**: 모델당 24문항 x 3회 = 72회차, 동일 소스·동일 fixture·동일 RAG 경로, 요청 실패 0건
> **원시 결과**: [`llm_quality_e4b_v4_20260826.json`](../../data/benchmarks/llm_quality_e4b_v4_20260826.json), [`llm_quality_e2b_v4_20260826.json`](../../data/benchmarks/llm_quality_e2b_v4_20260826.json)

---

## 1. v4 를 측정한 이유

v3(소스 `9516808`)에서 e2b 는 numeric 과 지연이 앞섰으나 미개찰 공고 q18 에서 3회 중
2회 과잉응답해 승격을 보류했습니다. 원인 조사 결과 `SYSTEM_PROMPT` 에 거절 지시가
한 문장도 없었습니다. 검색은 이미 16/16 이었으므로 검색이 아니라 생성 지시의 문제였습니다.

2026-08-26 에 두 가지를 바꾸고 재측정했습니다.

| 변경 | 내용 |
| --- | --- |
| 거절 지시 추가 | `src/rag/engine.py` `SYSTEM_PROMPT` 에 미개찰·개찰 전·미래 시점 미확정 정보 거절 지시와 사유 명시 지시를 넣고, 컨텍스트에 근거가 있으면 거절하지 않는다는 예외를 마지막에 두었습니다 |
| 거절 fixture 확대 | refusal_expected 문항을 3개에서 8개로 늘려(q20~q24 추가) 미개찰, 미래 시점 예측 요구, 지원 범위 밖, 문서에 없는 내부 비공개 정보, 공고만 있고 결과 없음 다섯 유형을 덮었습니다 |

거절 지시는 기존 목록 답변 지시와 0건 설명 지시를 무력화할 위험이 있었으므로,
과잉거절(답해야 하는데 거절)이 생기지 않는지를 함께 판정 대상으로 삼았습니다.

## 2. 재계산 결과 (raw 코드 독립 재계산)

| 지표 | e4b | e2b | 판정 |
| --- | ---: | ---: | --- |
| numeric 팩트 | 63/102 (61.8%) | **67/102 (65.7%)** | e2b 우세 |
| 문항 단위 numeric 전체 통과 | 12/48 | **16/48** | e2b 우세 |
| 근거 검색 성공 질의(context_sufficient) | 48/48 | 48/48 | 동일 |
| 기대 evidence ID hit 합계 | 51/51 | 51/51 | 동일 |
| 인용 표기(citation_required) | 48/48 | 48/48 | 동일 |
| `forbidden_literals` 위반 | 0 | 0 | 동일 |
| **과잉응답(거절해야 하는데 답함)** | **0/24** | **0/24** | 동일 |
| **과잉거절(답해야 하는데 거절)** | **0/48** | **0/48** | 동일 |
| 지연 P50 | 3,130.5ms | **2,681.6ms** | e2b 우세 |

### 2.1 거절 채점의 v3 대비 변화

| 모델 | v3 과잉응답 | v4 과잉응답 | refusal 표본 |
| --- | --- | --- | --- |
| e4b | 1건 (q18 r1) | **0건** | 9회차 → **24회차** |
| e2b | **2건 (q18 r1, r2)** | **0건** | 9회차 → **24회차** |

표본이 2.7배로 늘어난 상태에서 양쪽 모두 과잉응답이 사라졌습니다. 동시에 과잉거절도
0이므로 거절 지시가 정상 답변 경로를 훼손하지 않았습니다. numeric 과 evidence 가
v3 와 같은 수준을 유지한 것이 이를 뒷받침합니다.

---

## 3. 판정

**gemma4:e2b 를 서빙 기본 모델로 승격합니다.**

- e2b 가 열세인 지표가 하나도 없습니다. numeric(65.7% 대 61.8%), 문항 단위 통과
  (16/48 대 12/48), 지연 P50(-448.9ms)에서 앞서고, 근거 검색·evidence·인용·
  forbidden·거절 채점은 동등합니다.
- v3 에서 보류 사유였던 유일한 항목인 q18 과잉응답이 확대된 표본에서 재현되지
  않았습니다.
- 두 raw 모두 `canonical=true`, 소스 `b4913fd` 시작·종료 동일, 서빙 모델 결박 확인,
  요청 실패 0건입니다.

### 3.1 승격 적용 범위

| 대상 | 변경 |
| --- | --- |
| `src/app/core/config.py` | `OLLAMA_MODEL` 기본값 `gemma4:e2b` |
| `docker-compose.yml` | app·worker 서비스 fallback `gemma4:e2b` (2곳) |
| `.env.example` | `OLLAMA_MODEL=gemma4:e2b` |
| `AGENTS.md` | 기술 스택 표 LLM 항목 |

### 3.2 이 판정이 닫지 않는 것

| 항목 | 이유 |
| --- | --- |
| fixture 밖 일반화 | e2b 는 더 작은 모델입니다. 24문항 밖 실제 사용 질의에서의 품질은 이 측정이 답하지 않습니다 |
| numeric 절대 수치 | 65.7% 는 상대 우위일 뿐 절대 수준으로 낮습니다. 수치 정확도 개선은 별도 과제로 남습니다 |
| 지연 정본 판정 | 본 하네스는 부하 규약 미적용이며 초기 outlier 가 큽니다. 정식 레이턴시 판정은 `benchmark_rag_segments.py` 가 담당합니다 |

---

## 4. 재현 명령

```bash
docker compose up -d
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --expected-model gemma4:e2b --model-label gemma4:e2b \
  --app-container refac_bid_box-app-1 --repetitions 3 \
  --output data/benchmarks/llm_quality_e2b_v4_<날짜>.json

# 비교용 e4b 는 환경변수 오버라이드로 교체해 측정합니다
OLLAMA_MODEL=gemma4:e4b docker compose up -d app worker
```

작업 트리가 clean 해야 하고, **측정이 도는 동안 커밋·병합을 하지 않아야 합니다.**
2026-08-26 에 측정 중 병합으로 시작·종료 SHA 가 달라져 72회차가 fail-closed 로
폐기된 사례가 있습니다. provenance 결박이 의도대로 동작한 결과입니다.
