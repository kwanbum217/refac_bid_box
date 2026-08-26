# 세션 인수인계: 감사 v4 잔여 조치, e2b 승격, Arq business E2E (2026-08-26)

> **작성일**: 2026-08-26 (Asia/Seoul)
> **세션 시작 HEAD**: `a8e1517`
> **세션 종료 HEAD**: `06e7b7b` (원격 반영 완료, CI run `32936414210` 5 job success)
> **status**: current
> **Orca Run**: `run_131c03ec7058`
> **역할**: coordinator (Claude Opus 5)

---

## 1. 이 세션이 한 일

외부 감사(GPT) 보고서의 지적 사항을 로컬 코드로 검증하고, 실제로 열려 있던 항목을
Orca 워커 5대로 병렬 처리했습니다.

**감사 보고서는 `c6ef35c` 기준이었고, 그 뒤 12개 커밋으로 P1 4건이 이미 닫혀
있었습니다.** 세션 초반 코드 검증으로 이를 확인했고, 실제 잔여는 v3 측정이 새로
드러낸 항목들이었습니다.

| Task | 워커 | 산출물 |
| --- | --- | --- |
| T1 | Gemini 3.7 Flash High | `SYSTEM_PROMPT` 미개찰·미래 시점 거절 지시 추가 |
| T2 | nemotron-3-ultra | refusal fixture 3 → 8문항(q20~q24), manifest 재생성 |
| T3 | cursor Composer 2.5 | Chart.js 3곳 + marked 로컬화, SHA-256 기록 |
| T4 | cursor Composer 2.5 | mypy override 부채 실측 인벤토리(20블록 55모듈 297건) |
| W1 | Gemini 3.7 Flash High | Vector 기간·기관 post-filter |
| W2 | cursor Composer 2.5 | mypy 1건짜리 17개 모듈 해소 |
| W3 | cursor Composer 2.5 | Tailwind 브라우저 JIT → 빌드타임 CSS |
| W4 | MiniMax M3 (free) | Arq business-task E2E 하네스 |
| W5 | MiniMax M3 (free) | `predict_price_api` 영향 조사 (세션 종료 시점 진행 중) |

## 2. 핵심 성과

### 2.1 gemma4:e2b 승격

v4 재측정(소스 `b4913fd`, canonical, 모델당 24문항 x 3회 = 72회차, 실패 0)에서
e2b 가 열세인 지표 없이 e4b 이상이었습니다.

| 지표 | e4b | e2b |
| --- | ---: | ---: |
| numeric 팩트 | 63/102 (61.8%) | **67/102 (65.7%)** |
| 문항 단위 통과 | 12/48 | **16/48** |
| 과잉응답 / 과잉거절 | 0/24 · 0/48 | 0/24 · 0/48 |
| 지연 P50 | 3,130.5ms | **2,681.6ms** |

v3 에서 승격을 막던 q18 과잉응답(e2b 2/3)은 거절 지시 추가와 fixture 확대 뒤
**표본이 2.7배로 늘어난 상태에서 0건**입니다. 사용자 승인 후 승격했습니다.
상세는 [`llm_quality_v4_e4b_e2b_20260826.md`](../analysis/llm_quality_v4_e4b_e2b_20260826.md).

### 2.2 Arq production business-task E2E 실측

격리 큐에서 실제 등록 task 2종 30/30 완주, 실패·누락 0, 종단 P50 5.5ms.
`pipeline_executions` 11행 불변, 운영 큐 무영향으로 **데이터 무변경**을 확인했습니다.
데이터를 바꾸는 task 는 인자로 들어와도 코드가 거부합니다.

### 2.3 워커 감시 도구화

감시를 지침이 아니라 도구로 강제했습니다. `scripts/orca_worker_watch.py` 가
워커별 커밋·미커밋·터미널 차단 신호를 한 명령으로 돌려주고, 사람 개입이 필요하면
종료 코드 1 을 냅니다. `AGENTS.md` 4장 8항과 조율 스킬 3.2.1 절에 상시 의무로
넣었습니다. 실제로 이 도구가 W3 의 인증 정체와 W2 커밋 완료를 잡았습니다.

---

## 3. 미완료·후속 과제 (Next)

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| **mypy module debt** | **부분** | 297건 중 17개 모듈만 해소. 잔여 약 280건은 [`task_cd74b709edb0.md`](../analysis/task_cd74b709edb0.md) 5장 우선순위표대로 진행. 다음은 2건짜리 모듈 5개 |
| **`predict_price_api` 과거 결과 신뢰성** | **무효로 판정** | 3.1 절 참조. 두 스크립트의 과거 산출물은 전 표본이 skipped 였을 것이므로 재측정해야 함 |
| **Windows Docker Desktop 실기** | **불가** | 장비 부재. CI Windows job 은 green 이나 Docker 실기는 별개 |
| fixture 밖 일반화 | 미측정 | e2b 는 더 작은 모델. 24문항 밖 실제 질의 품질은 v4 가 답하지 않음 |
| numeric 절대 수치 | 낮음 | 65.7% 는 상대 우위일 뿐. 수치 정확도 개선은 별도 과제 |

### 3.0 착수 순서와 소요 추정

**권고 순서: `predict_price_api` 재측정 → mypy 부채.** mypy 는 기술부채라 미뤄도
손해가 누적되지 않지만, 재측정 쪽은 **잘못된 근거로 내린 용역 모델 판정이 남아
있는 상태**라 방치하면 그 위에 결정이 더 쌓입니다.

| 과제 | 병렬 | 직렬 | 비고 |
| --- | --- | --- | --- |
| `predict_price_api` 재측정 | **불가** | **1.5~3시간** | 측정이라 저장소 동결·공유 자원 점유가 필요합니다. 워커를 붙여도 대기만 합니다 |
| mypy 잔여 (~280건 / 38모듈) | **3~4.5시간** (워커 3대) | **6~9시간** | 아래 제약을 보십시오 |

**추정 근거**: 이번 세션 W2 가 17모듈 17건을 dispatch 에서 커밋까지 약 45분에
처리했습니다. 다만 그 17개는 전부 모듈당 1건짜리 단순 수정이었고, **잔여는 모듈당
평균 7.4건**이며 `arg-type` 217건이 소수 모듈에 몰려 있습니다(블록 13 은 2모듈에
34건). 난이도를 3~4배로 잡았습니다.

**mypy 병렬화 제약** — 워커를 무한정 늘릴 수 없습니다.

- 모든 워커가 `pyproject.toml` 의 override 목록을 고쳐야 해 충돌합니다.
  우회하려면 **워커별로 서로 다른 override 블록**을 배정해야 합니다(잔여 17블록이라
  3분할 가능). 4대 이상은 충돌 관리 비용이 이득을 넘어섭니다.
- 실작업이 1/3 로 줄어도 **검증은 코디네이터 하나라 병목**입니다. 조율 스킬 3.1 절
  기준 위임 절감률은 50~60% 이지 90% 가 아닙니다.

**목표치 조정**: 잔여 280건 전부는 현실적이지 않습니다. 인벤토리에 "SQLAlchemy
Result 타입", "numpy 제네릭" 같은 항목이 있는데 라이브러리 스텁 한계로
`type: ignore` 없이 못 고치는 경우가 나옵니다. 그런 모듈은 override 에 남기고
사유를 기록하는 것이 맞습니다. **200~240건 해소를 목표로 잡으십시오.**

### 3.1 이번 세션에서 발견한 실제 결함

**`predict_price_api` 인자 오바인딩.** 시그니처는
`(payload, request, db=Depends(get_db))` 인데 `scripts/eval_servc_api_path.py` 와
`scripts/eval_servc_interval_by_group.py` 가 `(payload, session)` 으로 호출해
DB 세션이 `request` 자리에 바인딩되고 `db` 는 `Depends` 객체를 받고 있었습니다.
호출부는 `d440ed6` 에서 고쳤습니다.

**과거 산출물은 무효로 판정합니다.** 근거는 세 가지입니다.

1. `predict_price_api` 는 본문 첫 동작으로 `_prediction_dispatch_wait_ms(request)`
   를 호출하고 그 안에서 `request.scope.get(...)` 을 읽습니다
   (`src/app/api/v1/predictions.py:56`). SQLAlchemy `Session` 에는 `scope` 속성이
   없어 **즉시 AttributeError 로 끊깁니다.**
2. 설령 통과해도 `db.get(BidAnnouncement, ...)` 에서 다시 끊깁니다. FastAPI
   `Depends` 객체에는 `get` 속성이 없습니다.
3. 두 스크립트는 이 예외를 `except Exception` 으로 잡아
   `records.append({"bid_id": ..., "skipped": ...})` 로 처리하고 계속 진행합니다
   (`scripts/eval_servc_api_path.py:133-138`). 주석은 "기초금액·예정가격이 없는
   공고는 422 로 끊긴다. 정상 동작" 이라고 되어 있어, **전 표본이 skipped 인
   상태가 정상으로 보였을 것입니다.**

즉 이 경로로 낸 평가 수치는 표본이 비었거나, 예측값이 하나도 집계되지 않은
결과였을 가능성이 큽니다. **용역 모델 판정에 이 두 스크립트의 과거 산출물을
근거로 쓰지 마십시오.** 고쳐진 호출부로 재측정한 뒤 다시 판정해야 합니다.

---

## 4. 코디네이터가 저지른 실수 (반복 방지)

| 실수 | 대가 | 방지책 |
| --- | --- | --- |
| 측정 중 main 병합 | e4b 72회차 전량 폐기 | [[measurement-requires-frozen-repo]] 메모리, 측정 전 병합 대기 브랜치를 먼저 정리 |
| 워커 터미널 오폭 | 초기 작업 유실 | close 대상 핸들을 반드시 재확인 |
| kimi 를 런처 명세 없이 기동 | 재기동 2회 | `agent_worker_launch_reference.md` 를 워커 기동 전에 읽을 것 |
| 단위 테스트만 보고 병합 | 동작하지 않는 Arq 하네스 병합 | **측정·실행 스크립트는 병합 전에 반드시 한 번 실행할 것** |
| 전체 테스트 실패를 뭉뚱그려 판단 | W3 가 깬 테스트를 놓침 | 실패 목록을 건별로 원인 확인 |
| `sleep` 없는 폴링 루프 | 아무것도 기다리지 못하고 호출만 소모 | 조율 스킬 3.2 절 준수 |

## 5. 도구 사용 시 주의

- `dispatch` 의 `agent_prompt_stalled` / `instruction_not_observed` /
  `agent_prompt_blocked` 는 **대부분 오탐**입니다. 터미널을 한 번 읽고 진행합니다.
- **Antigravity 는 `agy --model <id>` 로 띄우면 부팅이 멈춥니다.** `agy` 로 띄운 뒤
  `/model` 메뉴에서 모델과 effort(←/→)를 고릅니다.
- **kimi 런처(`orca_kimi_launch.py`)는 2026-08-26 에 두 번 모두 Node 크래시**로
  죽었습니다(`AgentActivityView.dispose`). 대화형 kimi 자체는 정상 동작하므로
  런처 경로의 문제로 보이며 원인 조사가 필요합니다. 임시 우회는 opencode 의
  `openrouter/minimax/minimax-m3:free` 로 같은 모델을 태우는 것입니다.
- Capsule 의 `allowed_write_files` 에 디렉터리를 적을 때는 `dir/**` 형태도 함께
  넣어야 게이트 2 가 하위 파일을 인정합니다.

## 6. 재현·확인 명령

```bash
# 워커 감시 (종료 코드 1 이면 사람 개입 필요)
python3 scripts/orca_worker_watch.py

# Arq business-task E2E (격리 큐, 데이터 무변경)
uv run python scripts/benchmark_arq_business_e2e.py \
  --repetitions 3 --jobs 5 --timeout 120 \
  --output data/benchmarks/arq_business_e2e_<날짜>.json

# LLM 품질 측정 (작업 트리 clean, 측정 중 커밋·병합 금지)
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v1.json \
  --expected-model gemma4:e2b --model-label gemma4:e2b \
  --app-container refac_bid_box-app-1 --repetitions 3 \
  --output data/benchmarks/llm_quality_e2b_v5_<날짜>.json
```

## 7. 자원 정리 상태

| 대상 | 상태 |
| --- | --- |
| T1~T4, W1~W4 워크트리 | **정리 완료** (병합 확인 후 제거) |
| W5 워크트리 | 정리 완료. kimi CLI 가 워크트리에서 기동되지 않아 조사는 코디네이터가 직접 수행 |
| 작업 브랜치 | W5 를 제외하고 전부 삭제 |
| Docker | `refac_bid_box` compose 5개 기동 상태, 서빙 모델 `gemma4:e2b` |
| 사용자 kimi 세션 | 주 저장소 경로에 활성. 대화용이며 파일 수정 안 함 |
