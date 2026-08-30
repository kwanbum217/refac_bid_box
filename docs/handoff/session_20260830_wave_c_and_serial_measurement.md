# 인수인계: 2026-08-30 Wave C 병렬 시정과 직렬 측정 4건

> **작성일**: 2026-08-30
> **Run**: `run_76e5e9048113` (Wave C 3건)
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity `gemini-3.7-flash-high` 1대, `gemini-3.7-flash-medium` 1대, `claude-sonnet-4-6` 1대
> **리뷰어**: `claude-opus-4-6-thinking`, `claude-sonnet-4-6`, `gemini-3.7-flash-high` 각 1건
> **시작 HEAD**: `f448606` / **종료 HEAD**: 본 문서 병합 시점
> **결과**: Wave C Task 3건 전부 병합. 직렬 측정 M1~M4 전부 완료. 전량 2,752 passed

---

## 1. 이번 세션이 닫은 것

어제 핸드오프의 남은 과업 1~4순위를 전부 닫았습니다.

| 순서 | 과업 | 결과 |
| --- | --- | --- |
| 1 | q21 재순위 결함 수정 + 32문항 회귀 실측 | **완료.** 전 지표 만점 |
| 2 | 구간 레이턴시 정본 생성 | **완료.** vector 33.0% + llm 65.8% |
| 3 | 느린 문항 cold/warm 분해 | **완료.** 전제가 오류였음을 규명 |
| 4 | Servc 3,589 OOS Champion 고정 평가 | **완료.** 재학습 근거 없음 |
| 5 | Windows Docker Desktop 실기 | **장비 부재로 보류 유지** |

측정 상세는 [`serial_measurement_20260830.md`](../analysis/serial_measurement_20260830.md),
지표 정본은 [`CURRENT_STATE.md`](../context/CURRENT_STATE.md) 2.3~2.5 절입니다.

---

## 2. 가장 중요한 것: 검색 지표가 회귀를 가립니다

**q21 수정의 첫 측정은 q21 을 고쳤지만 q05 와 q08 을 깨뜨렸습니다.**

| 지표 | 이전 정본 | 1차 시정본 |
| --- | ---: | ---: |
| numeric | 138/144 | **132/144** |
| refusal | 93/96 | **90/96** |
| evidence recall | 0.9583 | 1.0000 |
| citation | 70/72 | 72/72 |

**recall 과 citation 이 만점이 된 채로 답변만 나빠졌습니다.** 검색 지표만 봤다면 전면
개선으로 판정했을 것입니다.

원인은 `retrieve_lexical_context` 가 `dataset = "announcement"` 로만 조회하고
`attributesToRetrieve` 에 `sucsf_bid_amt`, `bidwinnr_nm`, `sucsf_bid_rate` 를 담지
않는다는 점입니다. 포함 매칭 승격이 이 공고 전용 문서를 상위로 올려 결과 보유 문서를
`top_k=5` 밖으로 밀어냈습니다. 모델은 잘못 답한 것이 아니라 정직하게 거부했습니다.

**recall 은 기대 문서가 목록에 있기만 하면 1.0 입니다. 몇 위인지, 컨텍스트가 실제로
답을 담는지는 보지 않습니다.** 검색 관련 변경의 판정에는 반드시 numeric 과 refusal 을
함께 보십시오.

시정(`5f1dc86`)은 `engine.py` 의 Lexical 승격만 되돌리고 `vector_store.py` 재순위는
유지했습니다. q21 은 벡터 재순위만으로 해결됩니다. 회귀 고정 테스트를 추가했고 구
코드에서 실패·시정본에서 통과함을 확인했습니다. 회귀 측정은
`data/benchmarks/noncanonical/` 에 증거로 보존했습니다.

---

## 3. 측정에서 뒤집힌 두 전제

### 3.1 느린 문항 q03·q08·q25·q31 은 한 부류가 아닙니다

| 문항 | cold 총 | warm 총 | 실제 원인 |
| --- | ---: | ---: | --- |
| q03 | 10,805 | 3,471 | 벡터 콜드 미스 (6.8배). 캐시로 해소 |
| q08 | 6,897 | 6,123 | LLM 생성 4,742ms. 캐시로 해결 안 됨 |
| q25 | 1,898 | 2,172 | **느리지 않음** |
| q31 | 2,216 | 2,521 | **느리지 않음** |

**q25 와 q31 을 최적화 대상으로 다루지 마십시오.**

### 3.2 실제 최악은 문항이 아니라 워밍업 부재입니다

지목되지 않았던 q01 이 cold 총 27,792ms(벡터 26,097ms)로 전 구간 max 와 일치합니다.
두 측정에서 교차 확인했습니다. M1 정본에서도 q01 r1 이 28,646ms 로 최대였고
r2 19,620 -> r3 11,746 으로 단조 감소합니다. 프로세스 재기동 직후 첫 요청 비용입니다.

**`benchmark_rag_segments.py` 에 warmup 단계가 없습니다.**
`latency_gate_protocol.md` 는 warmup 제외를 요구합니다. 이 산출물의 P99 와 max 를
게이트 판정선으로 쓰지 마십시오. 구간별 비중은 워밍업과 무관하므로 유효합니다.

### 3.3 cold 가 warm 보다 P50 이 빠릅니다

total P50 은 cold 3,624.59ms, warm 4,026.55ms 로 cold 가 402ms 빠릅니다. 원인은
`llm_ms` 이며 Ollama 직렬 처리로 warm 이 앞선 요청의 잔여 부하를 받습니다. **콜드
페널티는 중앙값이 아니라 꼬리에 있습니다.**

---

## 4. Servc 는 모델이 아니라 데이터 문제입니다

| 집단 | 건수 | MAE | 0.5%p 적중 |
| --- | ---: | ---: | ---: |
| `with_lwlt` | 2,233 (62.2%) | **0.6288** | **79.36%** |
| `missing_lwlt` | 1,356 (37.8%) | **2.0943** | **35.25%** |

전체 MAE 1.1825 는 성질이 다른 두 집단의 평균일 뿐입니다. 중앙 절대오차 0.2412 와
MAE 1.1825 의 차이, RMSE 2.629 가 오차의 꼬리 집중을 뒷받침합니다.

**재학습 게이트 3,098건을 491건 초과했으나 성능 저하가 없어 즉시 재학습 근거는
없습니다.** 개선 경로는 재학습이 아니라 낙찰하한율 결측 보전입니다.

---

## 5. 워커 운용에서 확인한 것

### 5.1 라우터 배정표는 풀 잔량을 보지 않습니다

`scripts/orca_model_router.py:943-963` 의 (role, risk) 표는 `reviewer/high` 한 칸을
빼고 전 조합에서 Gemini flash 를 1순위로 둡니다. 품질만 보고 풀별 소모량은 보지
않으므로 **코디네이터가 균등 배분을 따로 판단해야 합니다.**

**Antigravity Claude 계열은 5시간 한도가 병목입니다.** 주간 한도가 73% 남은 상태에서
워커 1대와 리뷰어 2건만으로 5시간 창이 18% 까지 떨어졌습니다.

### 5.2 Claude 계열 워커는 명령 형태 때문에 매번 승인 대기에 걸립니다

`scripts/orca_auto_approve.py` 는 `&&`, 파이프, 리다이렉트가 섞인 명령을 안전상
자동 승인하지 않습니다. Claude 계열 워커는 모든 bash 명령을
`cd <절대경로> && ... 2>&1 | tail` 형태로 내므로 100% 보류에 걸립니다. Gemini 워커는
명령이 단순해 걸리지 않습니다.

**Capsule 고지문에 명령 형태 제약을 넣으십시오.** `cd` 금지, `&&` 연결 금지,
파이프·리다이렉트 금지. 안전 장치를 낮추지 마십시오.

### 5.3 워커 보고 부정확이 2건 있었고 게이트가 잡았습니다

| Task | 위반 |
| --- | --- |
| C1 | 테스트 통과 건수를 2,687 로 보고(실제 2,689) |
| C2 | `validate_agent_rules.py` exit_code 를 0 으로 보고(실제 1) |

둘 다 게이트 6(보고 진실성)이 검출했습니다. **다음 Capsule 의 acceptance 최상단에
"검증 출력의 요약 줄을 그대로 옮겨 적을 것"을 명시하십시오.**

### 5.4 cursor 를 못 쓰는 이유는 토큰이 아니라 요금제입니다

`cursor-agent models` 에 `composer-2.5` 를 포함한 named model 이 전부 보이지만,
`cursor-agent -p --model <이름>` 은 다음으로 거부합니다(3회 재현).

```
ActionRequiredError: Named models unavailable
Free plans can only use Auto. Switch to Auto or upgrade plans to continue.
```

무료 등급에서 쓸 수 있는 것은 `auto` 뿐이고, auto 는 어느 모델이 처리했는지 사후
확정할 수 없어 `reviewer` 에 배정하지 않습니다. **유료 전환 시 named model 이 열리므로
그때 `cursor-composer` 항목을 라우터에 등록하십시오.**

---

## 6. 반복해서 걸린 운영 마찰

### 6.1 `CURRENT_STATE.md` 드리프트가 병합마다 재발합니다

`validate_agent_rules.py` 의 `source_commit` 허용 드리프트는 5인데, 워커 브랜치가
커밋 2건 이상이면 곧바로 넘깁니다. 이번 세션에서 3회 갱신했습니다.

**갱신 커밋 자체가 main 을 2 앞세우므로 어떤 값으로도 수렴하지 않는 경우가
있습니다.** C3 은 이 이유로 게이트 2건이 실패했고, 실질 품질 게이트(범위·테스트·
린터·Level 2)가 전부 통과한 것을 확인한 뒤 병합하고 main 에서 12/12 를 확정했습니다.
**허용치 조정 또는 판정 기준을 merge-base 기준으로 바꾸는 것을 검토하십시오.**

### 6.2 Level 1 게이트의 `--tests` 는 pytest 인자만 받습니다

`orca_level1_gate.py:624` 가 `["uv","run","pytest",*args]` 로 조립합니다.
`--tests 'uv run pytest tests/x.py -q'` 를 넘기면 `pytest uv run pytest ...` 가 되어
`ERROR: file or directory not found: uv` 로 오탐 실패합니다.
**`--tests 'tests/x.py -q'` 형식으로 주십시오.**

### 6.3 Capsule 은 워크트리에 직접 복사해야 합니다

`.orca/` 가 gitignore 대상이라 워크트리에 따라가지 않습니다. 이번에 워커가
"정본 사양이 없다" 고 판단하고 자체 해석으로 진행했습니다. **`terminal create` 직후
`.env` 와 함께 Capsule 을 복사하고 경로를 고지하십시오.**

### 6.4 Capsule 의 `ground_truth` 를 문서에서 옮겨 적지 마십시오

C1 Capsule 에 "`MEILI_ENABLED` 기본값은 False" 로 적었으나 **실제 컨테이너는 `true`**
였습니다. 코디네이터가 분석 문서 서술을 실행 환경 확인 없이 옮긴 것입니다. 이 오류가
Lexical 회귀를 예측하지 못한 직접 원인입니다. **런타임 사실은 컨테이너에서 직접
확인하십시오.**

---

## 7. 다음 세션 착수 순서

| 순서 | 작업 | 근거 |
| --- | --- | --- |
| **1** | `benchmark_rag_segments.py` warmup 단계 추가 후 P99·max 재측정 | 3.2 |
| **2** | Servc `missing_lwlt` 1,356건 결측 원인 조사와 보전 경로 설계 | 4 |
| **3** | vector 구간 최적화 (전체 지연의 33.0%) | `serial_measurement_20260830.md` 4장 |
| 4 | `CURRENT_STATE` 드리프트 판정을 merge-base 기준으로 전환 | 6.1 |
| 5 | Windows Docker Desktop 실기 | **장비 부재로 보류** |
| 마지막 | G3 cutover 최종 판정 | 위 완료 후 |

**1~3 은 병렬 가능합니다.** 1은 스크립트 수정, 2는 DB 읽기 조사, 3은 코드 최적화로
파일이 겹치지 않습니다. 다만 **측정 실행은 여전히 직렬**이며 저장소 동결이 필요합니다.

---

## 8. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| 워크트리 | 전부 반납. 주 저장소만 남음 |
| 작업 브랜치 | 전부 병합 후 삭제 |
| 워커 터미널 | 전부 종료 |
| Docker | app, db, redis, meilisearch, worker 기동 중 |
| `.env` | `LATENCY_SEGMENT_LOGGING` 원복(`false`). 백업 `/tmp/env_backup_20260830` |
| 전량 테스트 | 2,752 passed, 2 skipped, 실패 0 |
| 규칙 검증 | 12/12 통과 |

---

## 9. 다음 세션 첫 명령

```bash
cat docs/context/CURRENT_STATE.md
docker compose up -d && docker compose ps

# 측정 전 반드시 확인 (비어 있어야 함)
git status --porcelain
```
