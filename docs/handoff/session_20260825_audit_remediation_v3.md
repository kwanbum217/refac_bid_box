# 세션 인수인계: LLM 품질 v3 (검색 개선 반영) 재측정 및 정본 동기화 (2026-08-25)

> **작성일**: 2026-08-25 (Asia/Seoul)
> **세션 시작 기준**: `9516808`
> **세션 종료 시 HEAD**: `4164291` (LLM v3 evidence 반영 커밋)
> **status**: current
> **Orca Dispatch**: `ctx_9db06edf8f93`
> **Orca Task**: `task_389e15173471`
> **역할**: builder (LLM v3 canonical raw 검증·보존, 분석·CURRENT_STATE·handoff 동기화)

---

## 1. 이번 세션이 한 일

검색 필터 결함 해소(`0559a36`, 근거 적중 16/16)를 반영한 **LLM 품질 v3
재측정** raw 를 헤드 `9516808` 에서 코드로 독립 재계산해 정본임을 확인하고,
분석 문서·CURRENT_STATE·handoff 를 동기화했습니다.

| 작업 | 결과 |
| --- | --- |
| raw 재계산 | e4b/e2b 각 57회차, canonical=true, 소스 `9516808`, dirty=false(시작·종료), 요청 실패 0건 확인 |
| 분석 문서 | `docs/analysis/llm_quality_v3_e4b_e2b_20260825.md` 작성 |
| CURRENT_STATE | `source_commit` → `9516808`, v3 미측정 문구를 실측 결과로 대체 (8,000자 이내 유지) |
| handoff | 본 문서 |

## 2. v3 재계산 결과 (raw 코드 독립 재계산)

| 지표 | e4b | e2b |
| --- | ---: | ---: |
| numeric 팩트 | 63/102 (61.8%) | **69/102 (67.6%)** |
| 문항 단위 numeric 전체 통과 | 12/48 | **18/48** |
| 근거 검색(context_sufficient) | 51/51 | 51/51 |
| 인용 표기 | 47/48 | **48/48** |
| 지연 P50 | 3,593.7ms | **3,005.4ms** |
| 과잉응답(q18) | **1건 (r1)** | **2건 (r1, r2)** |

**판정: e2b 승격 보류.** e2b 는 numeric·지연·인용에서 우세하고 근거 검색은
동일(51/51)하지만, 미개찰 공고 q18 에서 3회 중 2회 과잉응답해 근거 없는 정보를
사실처럼 제시하는 안전성 결함이 재현됐습니다. v2(2/3)와 동일하게 재현되어 검색
개선이 이 문제를 해소하지 못했습니다.

> **지연 주의**: 본 하네스는 부하 규약 미적용이며 초기 outlier(콜드스타트)가 커서
> latency P50 은 품질 판정의 단독 근거로 쓰지 않습니다. 정식 레이턴시 판정은
> `benchmark_rag_segments.py` 가 담당합니다.

---

## 3. 완료 사항 (Done)

- 두 raw 의 canonical/source/model/count/지표를 코드로 독립 재계산해 보고했습니다.
  (e4b numeric 63/102, e2b 69/102, evidence hit 양쪽 51/51, latency P50 e4b
  3,593.7ms / e2b 3,005.4ms, q18 과잉응답 e4b 1건·e2b 2건)
- e2b 의 numeric 우위와 q18 안전성 열세를 함께 기록하고 승격을 보류했습니다.
- `CURRENT_STATE.md` 의 `source_commit` 을 `9516808` 로 갱신하고 기존 v3
  미측정 문구를 실제 결과로 대체했습니다.
- `CURRENT_STATE.md` 8,000자 예산을 유지했습니다(현재 약 7,989자).
- 새 handoff(본 문서)에 완료·미완료·재현 명령·Docker e4b 복원 및 shutdown 상태를
  명시했습니다.

## 4. 미완료·후속 과제 (Next)

| 항목 | 근거 |
| --- | --- |
| e2b 승격 | q18 과잉응답이 0 이 되어야 재검토. 미개찰·미래 시점 거절 지시를 RAG 프롬프트에서 강화 |
| 거절 기대 문항 확충 | 거절 문항이 3개뿐이라 q18 하나가 판정을 좌우. 미개찰·미래 시점·타국 사업 유형 추가 (fixture 변경 시 `build_llm_fixture_manifest.py` 로 manifest 재생성 필수) |
| Chart.js CDN 로컬화 | `bids/dashboard.html` 등 3개 템플릿 |
| Tailwind 운영 빌드 | 현재는 `cdn.tailwindcss.com` 스크립트 로컬 배치만 함 |
| Windows Docker Desktop 실기 검증 | 장비 부재로 보류. G2 컷오버의 마지막 항목 |

## 5. 재현 명령

```bash
# e4b 측정 (작업 트리 clean, 워커 미가동, 부하 규약 준수 전제)
docker compose up -d
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --expected-model gemma4:e4b --model-label gemma4:e4b \
  --app-container refac_bid_box-app-1 --repetitions 3 \
  --output data/benchmarks/llm_quality_e4b_v3_<날짜>.json

# e2b 측정 (모델 교체는 환경변수 오버라이드)
OLLAMA_MODEL=gemma4:e2b docker compose up -d app worker
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --expected-model gemma4:e2b --model-label gemma4:e2b \
  --app-container refac_bid_box-app-1 --repetitions 3 \
  --output data/benchmarks/llm_quality_e2b_v3_<날짜>.json

# 측정 후 e4b 복원
OLLAMA_MODEL=gemma4:e4b docker compose up -d app worker
```

작업 트리가 clean 해야 하고(dirty 면 종료 코드 3), 워커가 돌지 않아야 합니다.
모델 교체는 `.env` 수정 대신 환경변수 오버라이드로 합니다.

## 6. Docker 상태 및 shutdown

| 항목 | 상태 |
| --- | --- |
| 컨테이너 | `refac_bid_box` compose 프로젝트 5개(app healthy·worker·redis·db·meilisearch) 기동 상태 |
| 서빙 모델 | **`gemma4:e4b` 로 복원 완료** (측정 종료 후 정상 서빙 모델로 되돌림) |
| 작업 트리 | 본 작업 브랜치 `kwanbum217/audit-v3-evidence-9516808` 에서 커밋 예정 |
| 원격 Windows CI | 미수행 (장비 부재) |

> **shutdown 안내**: 스택을 내리려면 `docker compose down` 를 사용합니다. 단, DB·벡터
> 데이터 무손실(G1)이 우선이므로 운영 중엔 임의 중단하지 않습니다. 서빙 모델은
> 항상 기본 `gemma4:e4b` 로 유지합니다.
