# 세션 인수인계: 외부 감사 2건 종결, 검색 필터 결함 해소, LLM 품질 v2 재측정 (2026-08-25)

> **작성일**: 2026-08-25 (Asia/Seoul)
> **세션 시작 기준**: `3e9d014`
> **세션 종료 시 HEAD**: `b2e803b`
> **status**: current
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity Gemini 3.7 Flash (High/Medium), OpenCode DeepSeek V4 Flash, Kimi Code or-free/nemotron-ultra
> **Orca Run**: `run_b5e965d32b76` (전 Task 완료, 자원 반납 완료)

---

## 1. 이번 세션이 한 일

외부 감사 두 건(GPT, 독립 에이전트)의 지적 25건을 처리하고, 그 과정에서 감사가
잡지 못한 결함 다섯 건을 추가로 발견해 고쳤습니다.

| 구분 | 총계 | 결과 |
| --- | ---: | --- |
| GPT 지적 | 12 | 12 완료 |
| 독립 에이전트 지적 | 13 | 12 완료 + 1 기각 |
| 세션 중 추가 발견 | 5 | 5 완료 |

기각한 1건은 `docs/orca/` 인덱스 등재입니다. Git 추적 파일이 0건인 작업 산출물
디렉터리라 등재 대상이 아닙니다.

---

## 2. 감사가 잡지 못한 것을 세션 중에 발견했습니다

**이 다섯 건이 이번 세션에서 가장 중요한 산출입니다.** 감사 보고서에는 없었고,
검증을 실측으로 하다가 드러났습니다.

| 발견 | 기전 | 해소 |
| --- | --- | --- |
| CI 가 세션 시작 시점부터 빨간불 | GPT 는 "실패라고 볼 수 없다" 고 적었으나 `3e9d014` 의 run `32727481204` 은 5개 잡 중 4개가 실패 | `412d0c6`, `7f35a86` |
| 문서 링크 검증이 머신 의존 fail-open | 절대 경로를 **작성자 머신에 파일이 있으면 통과**시켜, 로컬은 green 이고 CI 3플랫폼이 33건으로 실패 | `412d0c6` |
| Windows 드라이브 절대 경로 | `Path` 조인이 드라이브 절대 경로를 만나면 root 를 버려, 위 수정이 Windows 에서만 뚫림 | `7f35a86` |
| `orca_taskctl` Capsule 경로 결함 | Task spec 은 변경 불가인데 잠정 경로로 만든 뒤 그 파일을 지워, 워커 3대가 동시에 없는 파일을 열었음 | `9ebab3e` |
| 거절 채점기 패턴 누락 | "포함되어 있지 않습니다" 계열이 없어 정상 거절이 과잉응답으로 오분류. e2b 거절 오답이 7건으로 부풀려졌고 실제는 2건 | `3b8e3bd` |

**교훈은 하나입니다. 로컬 green 은 CI green 이 아니고, 게이트 통과는 실측이
아닙니다.** 상세 기전은 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md)
21장에 남겼습니다.

---

## 3. 검색 필터 결함 (이번 세션 최대 성과)

`src/rag/vector_store.py` 의 `collection.query` 에 **`where` 절이 아예
없었습니다.** `build_retrieval_plan` 이 `category` 등을 계산해 `plan.filters` 에
담지만 벡터 검색에 전달되지 않았습니다.

필터를 적용하자 잠복해 있던 두 번째 결함이 드러났습니다. `CATEGORY_KEYWORDS` 가
딕셔너리 순서로 돌며 **첫 일치에서 break** 하여 "건축**공사** 감리 **용역**" 을
`Cnstwk` 로 분류했습니다. 실제 공고는 `Servc` 이므로 정답 문서가 필터에
걸러졌습니다. 한국어는 뒤에 오는 말이 핵이므로 마지막 일치를 채택해야 합니다.

실측 근거입니다. 주 저장소 `chroma_db`(512,348건)로 fixture 16문항 근거 적중을
직접 쟀습니다.

| 시점 | 근거 적중 |
| --- | ---: |
| main 기준선 | 15/16 |
| 1차 커밋(반려) | 14/16 |
| 재작업 병합본 | **16/16** |

**1차 커밋은 Level 1 게이트 6종과 단위 테스트를 전부 통과했지만 실제 검색은
회귀였습니다.** 실측하지 않았다면 병합됐을 것입니다.

부수 효과로 근접 중복 처리 과제가 불필요해졌습니다. 같은 사업의 공고가 9건일 때
결과 미보유 문서가 상위를 차지하던 문제가 `has_result` + `category` 필터로
해소됩니다.

---

## 4. LLM 품질 v2 재측정 결과

동일 소스(`1d51d38`, dirty=false), 동일 fixture, 모델당 57회차입니다.
원시 결과는 [`llm_quality_e4b_v2_20260825.json`](../../data/benchmarks/llm_quality_e4b_v2_20260825.json),
[`llm_quality_e2b_v2_20260825.json`](../../data/benchmarks/llm_quality_e2b_v2_20260825.json)
이고 분석은 [`llm_quality_v2_e4b_e2b_20260825.md`](../analysis/llm_quality_v2_e4b_e2b_20260825.md)
입니다.

| 지표 | e4b | e2b |
| --- | ---: | ---: |
| numeric 팩트 | 60/102 (58.8%) | 64/102 (62.7%) |
| 근거 검색 성공 | 45/48 | 45/48 |
| 지연 P50 | 3,656ms | 1,797ms (-50.8%) |
| 과잉응답(거절해야 하는데 답함) | **0건** | **2건 (q18)** |

**e2b 를 승격하지 않았습니다.** 속도와 numeric 은 앞서지만, 미개찰 공고를 묻는
q18 에서 3회 중 2회 근거 없이 답변을 시작했습니다.

**v1 결과(`llm_quality_*_20260824.json`)는 채점 기준이 달라 무효입니다.**
비교에 쓰지 마십시오.

---

## 5. 다음 세션에서 먼저 볼 것

### 5.1 검색 개선분을 반영한 v2 재측정 (최우선)

v2 측정은 `1d51d38` 에서 했고 검색 필터 수정은 `0559a36` 입니다. **현재 품질
수치는 검색 개선 이전 값입니다.** 근거 적중이 15/16 에서 16/16 으로 올랐으므로
numeric 정확도도 함께 움직일 수 있습니다.

```bash
docker compose up -d
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --expected-model gemma4:e4b --model-label gemma4:e4b \
  --app-container refac_bid_box-app-1 --repetitions 3 \
  --output data/benchmarks/llm_quality_e4b_v3_<날짜>.json
```

전제 조건입니다. 작업 트리가 clean 해야 하고(dirty 면 종료 코드 3), 워커가 돌지
않아야 하며(주변 부하 규약), 모델 교체는 `.env` 수정 대신
`OLLAMA_MODEL=gemma4:e2b docker compose up -d app worker` 로 하십시오. 측정 후
`gemma4:e4b` 로 되돌려야 합니다.

### 5.2 거절 기대 문항 표본이 얇습니다

**q18 하나가 e2b 승격 여부를 결정하고 있습니다.** 거절 기대 문항이 3개뿐이고
회차가 3회입니다. 미개찰, 미래 시점, 타국 사업 유형을 늘려 판정 신뢰도를
올리십시오. fixture 를 늘리면
`uv run python scripts/build_llm_fixture_manifest.py` 로 evidence manifest 를
반드시 다시 생성해야 합니다. 안 하면 검증이 fail-closed 로 막습니다.

### 5.3 생성 품질이 남은 병목입니다

정답 문서가 컨텍스트에 들어간 상태에서도 요구 수치의 37.5% 를 놓칩니다.

| 구분 | numeric 정확도 |
| --- | ---: |
| 근거 검색 성공(45회차) | 60/96 (62.5%) |
| 근거 검색 실패(3회차) | 0/6 |

**임베딩 문제가 아닙니다.** 검색 recall 은 성공 시 1.0 입니다. 프롬프트에서
요구 수치를 빠짐없이 답하도록 강제하는 방향이 우선입니다. 임베딩 모델 교체는
보존된 `bidding_kb` 정합성(G1) 위반이므로 검토 대상이 아닙니다.

### 5.4 남은 후속 과제

| 항목 | 근거 |
| --- | --- |
| Chart.js CDN 로컬화 | `bids/dashboard.html` 등 3개 템플릿. `base.html` 은 이번에 해소 |
| Tailwind 운영 빌드 | 현재는 `cdn.tailwindcss.com` 스크립트를 로컬 배치만 함. 브라우저 JIT 컴파일러라 운영 대상이 아님 |
| mypy 부채 축소 | 전역 disable 은 제거했고 모듈별 override 로 남음. 현황은 [`../ops/mypy_debt_reduction.md`](../ops/mypy_debt_reduction.md) |
| 호스트 포트 노출(3306/6379/7700) | 개발 편의로 유지 중. 운영 전환 시 검토 |
| Windows Docker Desktop 실기 검증 | 장비 부재로 보류. G2 컷오버의 마지막 항목 |

---

## 6. 워커 운용에서 배운 것

**게이트 통과를 병합 근거로 쓰지 마십시오.** 이번 세션에서 반려한 3건 모두
Level 1 게이트를 통과한 상태였습니다.

| Task | 게이트 | 실측 판정 |
| --- | --- | --- |
| RAG 의도 라우팅 | 통과 | 반례 2건으로 반려. 순수 집계 질의가 개체 질의로 오분류 |
| fixture manifest | 통과 | 실제 ChromaDB 에서 SQL 스키마 불일치로 반려 |
| 벡터 필터 적용 | 통과 | 실측 15/16 -> 14/16 회귀로 반려 |

반려할 때는 **재현 가능한 반례와 검증된 개선안을 함께** 주십시오. 코디네이터가
실측으로 확인한 값을 ground truth 로 넣으면 워커가 한 번에 고칩니다.

그 밖의 함정은 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 21장과
[`../ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
에 기록했습니다. one-shot 워커(Kimi)가 커밋 없이 완료를 선언한 사고, 정체 감시가
세션 종료를 못 잡는 문제, macOS bash 3.2 에서 즉사한 감시 스크립트가 포함됩니다.

---

## 7. 자원 상태

| 항목 | 상태 |
| --- | --- |
| 워크트리 | 전부 해제. `git worktree list` 에 주 저장소만 남음 |
| 작업 브랜치 | 병합 후 5개 전부 삭제 |
| 워커 터미널 | 5개 전부 close |
| Orca Run `run_b5e965d32b76` | 전 Task 완료 |
| 주 저장소 | clean, `origin/main` 동기화 완료 |
| 컨테이너 | `docker compose` 스택 기동 상태. 서빙 모델 `gemma4:e4b` 로 복구됨 |

`.env` 는 수정하지 않았습니다. 모델 교체는 환경변수 오버라이드로 했습니다.
