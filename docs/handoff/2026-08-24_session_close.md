# 세션 종료 인수인계 (2026-08-24)

> **작성일**: 2026-08-24 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **기준 커밋**: `d0f74d1` (`origin/main` 동기화 완료)
> **현재 정본**: [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)
> **상태**: 이번 세션 과업 전부 종결. 측정 3종·모델 비교 완료, `main` 병합 완료

---

## 0. 이번 세션에서 끝낸 것

| 과업 | 결과 | 근거 |
| --- | --- | --- |
| 외부 감사 13항목 검증 | 전부 해소 확인 | [`gpt_audit_reverification_20260824.md`](../analysis/gpt_audit_reverification_20260824.md), [`audit_items_8_9_12_verification_20260824.md`](../analysis/audit_items_8_9_12_verification_20260824.md) |
| 크로스 플랫폼 CI 복구 | **3플랫폼 green** | run `32703990405` (`a203286`) |
| Arq Docker synthetic 3회 | 회차별 raw 보존 | [`measurement_triple_20260824.md`](../analysis/measurement_triple_20260824.md) |
| 강화 RAG 하네스 측정 | 완료 | 같은 문서 |
| Ollama 규약 준수 3회 | 게이트 전 항목 통과 | 같은 문서 |
| `gemma4:e2b` 비교 | **승격 안 함** | [`llm_model_comparison_e4b_e2b_20260824.md`](../analysis/llm_model_comparison_e4b_e2b_20260824.md) |
| Arq 캘리브레이션 설계 | 작성 + 실행가능성 대조 | [`arq_calibration_design_20260824.md`](../analysis/arq_calibration_design_20260824.md), [`calibration_executability_20260824.md`](../analysis/calibration_executability_20260824.md) |

`main` 병합 3건: `a203286`, `582d207`, `d0f74d1` (+ 인용 정정 `8d483e4`).

---

## 1. 다음 세션 우선순위

| 순위 | 과업 | 차단 요인 | 예상 |
| :---: | --- | --- | --- |
| 1 | LLM 품질 평가 세트 구축 후 e2b 재판정 | 없음 | 90~120분 |
| 2 | Arq 캘리브레이션 실행 불가 7건 해소 | 없음 | 90분 |
| 3 | 프론트엔드 HTMX 도입 여부 결정 | **사용자 결정** | 결정 후 4~6시간 |
| 4 | Windows Docker Desktop 실기 | **장비 부재** | 장비 확보 후 |
| 5 | G3 전체 컷오버 판정 | 1~4 종료 | 60분 |

---

## 2. 과업 1: LLM 품질 평가 세트 (최우선)

### 2.1 왜 지금인가

`gemma4:e2b` 는 **속도에서 확정적으로 우세**합니다. `llm_ms` P50 -54.1%,
P95 -26.2% 입니다. 승격을 막는 것은 속도가 아니라 품질 근거의 부재 하나뿐이며,
그 부재는 평가 세트를 만들면 바로 해소됩니다.

### 2.2 이번 세션 품질 비교가 판정 불가였던 이유

정본 질의 5종 중 **4종이 컨텍스트 부족으로 두 모델 다 답변을 거절**했습니다.
정작 생성 품질이 갈리는 구간을 재지 못했습니다. 컨텍스트가 충분했던 것은
"2025년 물품 낙찰 평균 낙찰률" 하나이고, 그 문항은 DB 집계 경로라 LLM 이
수치를 만들지 않아 두 모델 결과가 완전히 같았습니다.

### 2.3 절차

```bash
docker compose up -d app redis
curl -s http://localhost:8000/api/v1/health/ready
```

1. **컨텍스트가 충분한 질의를 최소 15문항 확보합니다.** ChromaDB `bidding_kb`
   에 실제로 근거가 있는 주제를 골라야 합니다. 거절 답변이 나오는 질의는
   품질 변별에 쓸모가 없습니다
2. 각 질의를 **모델당 3회 반복**합니다. 1회 답변으로는 모델 차이와 생성
   변동을 구분할 수 없습니다
3. 모델 교체는 반드시 컨테이너 재생성으로 합니다. `restart` 는 Compose 환경을
   다시 주입하지 않습니다

```bash
OLLAMA_MODEL=gemma4:e2b LATENCY_SEGMENT_LOGGING=true \
  docker compose up -d --force-recreate app
docker inspect refac_bid_box-app-1 --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep OLLAMA_MODEL          # 실제 교체 확인
```

4. SSE 경로 품질도 함께 봅니다. 이번 비교는 단발 질의만 봤습니다

### 2.4 완료 기준

- 컨텍스트 충분 질의 15문항 이상, 모델당 3회 반복
- 정확도(사실 오류·환각), 근거 표기 정합, 서술 충실도를 각각 판정
- 승격 또는 기각을 명시. **속도만으로 승격하지 않습니다**

### 2.5 함정

- **부하 조건을 반드시 같게 하십시오.** 이번 세션 첫 비교가 정확히 이것 때문에
  무효였습니다. e4b 를 워커 가동 중(median 36.1%)에, e2b 를 조용한
  호스트(22.5%)에 재서 -64.6% 라는 부풀린 값이 나왔습니다. 같은 조건에서
  다시 재니 -54.1% 였습니다
- **교란 여부는 데이터로 확인할 수 있습니다.** LLM 만 바꿨는데 `vector_ms` 나
  `sql_ms` 가 같이 개선되면 그 비교는 오염된 것입니다
- 측정 전 `python3 -c "import os;print(os.getloadavg()[0]/14)"` 로 부하율을
  확인하고 0.30 아래에서 시작하십시오

---

## 3. 과업 2: Arq 캘리브레이션 실행 불가 7건

설계서는 있으나 **그대로 실행할 수 없습니다.**
[`calibration_executability_20260824.md`](../analysis/calibration_executability_20260824.md)
가 7건을 열거합니다. 대표적인 것입니다.

| 지점 | 문제 | 대안 |
| --- | --- | --- |
| 호스트 부하 규약 | 하네스가 기록만 하고 자동 거부하지 않음 | 하네스에 게이트를 넣거나 외부 사전 검증 |
| frozen baseline 경로 | `<mode>/<git_sha_short>` 디렉터리를 자동 생성하지 않음 | 실행 전 `mkdir -p` |
| 대표값 선정 | 하네스는 P95 최악값을 저장, 설계서는 분위수 식 | `_r*.json` 을 직접 읽어 계산 |
| provenance `unknown` | 하네스가 `unknown` 으로 채워 통과시킴 | 수동 기각 판정 |

**해소 전에는 잠정 일관성 봉투(900 jobs/sec, 600ms P95)를 유지합니다.**
이번 3회 측정은 캘리브레이션 런이 아닙니다.

---

## 4. 결정 대기: 프론트엔드 HTMX

[`FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md) 의 목표는 SSR + HTMX
이나 실제 템플릿은 jQuery 만 로드하고 HTMX 사용이 0건입니다. 계획서는
[`htmx_migration_plan_20260823.md`](../design/htmx_migration_plan_20260823.md)
에 있고 안 B(부분 도입)가 권고안입니다. **사용자가 안을 고르기 전에는
착수하지 않습니다.**

---

## 5. 차단: Windows Docker Desktop 실기

장비가 없어 진행 불가입니다. **장비 확보 전까지 G3 전체 컷오버를 PASS 로
판정하지 마십시오.** Windows CI 는 green 이지만 CI green 과 실기 검증은
다릅니다.

---

## 6. 다음 세션 첫 명령

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git branch --show-current                 # main 인지 확인
git status --short --branch
git worktree list                         # 주 저장소 하나만 있어야 정상

python3 scripts/validate_agent_rules.py
uv run pytest tests/ -q

# 측정이 필요하면
docker compose up -d app redis
curl -s http://localhost:8000/api/v1/health/ready
```

---

## 7. 종료 시 자원 상태

| 자원 | 상태 |
| --- | --- |
| 워크트리 | 주 저장소 하나만 남김. 워커 트리 전부 회수 |
| 브랜치 | 이번 세션 작업 브랜치 전부 병합 후 삭제 |
| 프로젝트 Docker 컨테이너 | `docker compose down` 으로 내림. **볼륨은 삭제하지 않음** |
| Ollama | launch agent 와 `ollama serve` 종료. **모델 데이터 삭제하지 않음** |
| Orca 터미널 | 전부 닫음 |
| 다른 프로젝트 컨테이너 | **건드리지 않음.** `minchodan-*`, `my-board-web` 은 이전부터 Exited 상태 |

`data/benchmarks/` 의 기각본 2건을 **삭제하지 마십시오.** 기각 이력이
사라집니다.

    rag_segments_e4b_20260824_discarded_ambient_load.json
    ollama_e4b_20260824_r2_discarded_ambient_load.json

---

## 8. 이번 세션 운영 교훈

1. **로컬 게이트 통과를 크로스 플랫폼 통과로 읽지 마십시오.** macOS 로컬에서
   1,915건 전부 통과한 브랜치가 Windows 에서 3건 실패했습니다. 작업 브랜치를
   `feature/**` 로 push 하면 `main` 병합 전에 CI 3플랫폼을 미리 받습니다
2. **크로스 플랫폼 수정은 한 번의 CI green 을 볼 때까지 완료가 아닙니다.**
   세 라운드가 필요했고, 한 라운드의 수정이 다음 라운드의 실패를 만들었습니다.
   운영 코드를 POSIX 로 고정하자 테스트 기대값이 역슬래시를 기대해 어긋났습니다
3. **워커 터미널은 커밋이 아니라 `worker_done` 수신으로 닫습니다.** 커밋만 보고
   닫았다가 두 워커의 `worker_done` 이 capability 회수 후 도착해 거부됐고,
   Task 가 `ready` 로 되돌아갔습니다. 산출물은 멀쩡했지만 수명주기 기록이
   비었습니다. `check --wait --types worker_done` 으로 받고 `worker-release`
   하십시오
4. **측정을 병렬로 돌리지 마십시오.** 세 측정이 서로의 주변 부하가 되어 셋 다
   게이트를 못 넘습니다. 측정은 순차, 그 주변 작업만 병렬입니다
5. **비교 측정은 부하 조건을 맞춘 뒤에 하십시오.** 8장 2번과 같은 종류의
   실수를 이번 세션에 한 번 더 했습니다
6. **DeepSeek V4 Flash 는 현재 쓸 수 없습니다.**
   `opencode/deepseek-v4-flash-free` 는 무료 풀에서 사라져 `Model not found`
   이고, `opencode-go/deepseek-v4-flash` 와 `deepseek-v4-pro` 는 중국 호스팅
   **명시적 opt-in** 을 요구해 거부됩니다. opencode-go 풀 자체는 정상이며
   `opencode-go/kimi-k2.7-code` 는 probe 통과했습니다. 무료만 쓰려면
   `opencode/mimo-v2.5-free` 를 쓰십시오
7. **`taskctl dispatch` 가 주입하는 Capsule 경로는 Intent 파일명에서
   파생됩니다.** `--task-id` 로 실제 Orca ID 를 줘도 주입 문구는 파생 경로를
   가리켜 워커가 없는 파일을 엽니다. 파생 경로에 Capsule 사본을 두거나
   Dispatch 직후 `terminal send` 로 정정하십시오
8. **`agent_prompt_stalled` 는 오탐입니다.** 이번 세션 워커 4대 전부 이 오류
   뒤에 정상적으로 지시를 받았습니다. 터미널을 읽어 도달을 확인하고 진행하십시오
9. **코디네이터 터미널의 Run 바인딩은 세션 중에 풀릴 수 있습니다.**
   `task-create` 가 "no longer bound to Run" 을 내면
   `orca orchestration run-create --objective ...` 로 새 Run 을 만드십시오.
   `--title` 은 없는 플래그입니다
