# Orca 다중 섹션 오케스트레이션 실행 지침

> **작성일**: 2026-08-12
> **수정일**: 2026-08-15
> **버전**: v2.0.0
> **상태**: 실행 검증 완료. 2026-08-12 세션에서 7개 섹션(S1~S7)을 병렬 운영하고 전량 병합한 결과를 반영했습니다. Task Capsule v2 계약(자족적 워커 사양, 컴팩트 `worker_done`·아티팩트 분리)을 반영했습니다.
> **대상**: 이 저장소에서 코디네이터 역할을 맡는 사람 또는 에이전트
> **규약 정본**: [`AGENTS.md`](../../AGENTS.md) 4장, [`orca-section-coordination`](../../.agents/skills/orca-section-coordination/SKILL.md)
> **관련 문서**: [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md), [`multi_agent_setup.md`](multi_agent_setup.md), [`git_branching_strategy.md`](git_branching_strategy.md)

---

## 0. 이 문서의 위치

`AGENTS.md` 4장은 **무엇을 지켜야 하는가**를 정합니다.
`orca-section-coordination` 스킬은 **어떤 절차를 따르는가**를 정합니다.
본 문서는 **실제로 돌려 보니 어디서 깨졌는가**를 정합니다.

세 문서가 어긋나면 `AGENTS.md` 가 우선합니다. 본 문서는 그 규약을 대체하지
않고, 규약을 따르는 도중 사람이나 에이전트가 실제로 빠졌던 함정을 기록합니다.

**이 문서에 적힌 함정 대부분은 겉으로 정상으로 보입니다.** 그래서 절차를
지켰다고 생각하는 동안 시간이 흘러갑니다.

워커 실행 계약의 정본은 [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)
입니다. 워커 사양은 `ORCA_TASK_CAPSULE_V2` 형식으로 작성하고, 작업 완료
통보는 **컴팩트 `worker_done` 요약**과 **파일 아티팩트**로 분리합니다.

---

## 1. 사전 준비

| 순서 | 조치 | 확인 방법 |
| --- | --- | --- |
| 1 | Orca 런타임 기동 | `orca status --json` 의 `result.runtime.state == "ready"` 이고 `reachable == true` |
| 2 | 에이전트 계정과 잔여 한도 확인 | `orca account list --json` 의 `result.rateLimits` |
| 3 | 저장소 등록 | `orca repo add --path <저장소>` |
| 4 | 규약 파일 존재 확인 | `AGENTS.md` 4장, `.agents/skills/orca-section-coordination/SKILL.md` |

1번이 만족되지 않으면 **조율 작업을 시작하지 말고** 차단 사유를 보고합니다.
런타임 없이 진행한 작업을 오케스트레이션이라고 표현해서는 안 됩니다.

2번의 잔여 한도는 단순 참고값이 아니라 **모델 배정의 근거**입니다. 세션 창과
주간 창을 따로 보고, 각각의 리셋 시각까지 확인합니다. 리셋이 임박한 풀과
오래 버텨야 하는 풀에 같은 부하를 주면 뒤쪽 작업이 막힙니다.

---

## 2. 작업 분해

여기가 성패를 가릅니다. 뒤의 모든 절차는 이 단계가 옳다는 가정 위에 있습니다.

### 2.1 원칙

1. **소유 파일이 서로 겹치지 않도록** 섹션을 나눕니다. 겹치지 않는 것이 병렬화의
   전제입니다. 작업이 개념적으로 독립적으로 보이는 것은 근거가 되지 않습니다.
2. 나누기 전에 **실제 코드를 읽고** 파일 목록을 확정합니다. "이 기능은 이 파일에
   있을 것" 으로 나누면 워커가 소유 밖 파일을 만나 멈춥니다.
3. 공유 자원은 **한 Task 만 소유**합니다. 나머지는 `--deps` 로 대기시킵니다.
   코디네이터가 직접 소유해도 됩니다.
4. 겹치는데 나눠야 하면 병렬이 아니라 **순차 의존성**으로 겁니다.

### 2.2 이 저장소의 공유 자원

| 자원 | 왜 공유인가 |
| --- | --- |
| Docker Compose, MySQL, Redis, Meilisearch | 컨테이너 하나를 여러 섹션이 동시에 올리거나 내리면 서로 끊습니다 |
| `data/model_files/` 서빙 루트 | 격리 트리에 없습니다. 쓰는 작업은 주 저장소에서만 가능합니다 |
| `docs/servc_model_status.md`, `docs/README.md` | 여러 섹션이 같은 표를 고칩니다 |
| `src/ml/features.py` | 특징 정의를 바꾸면 다음 재학습이 자동으로 물고 갑니다 |
| `main` 브랜치 병합 | 코디네이터 전용입니다 |

### 2.3 겹침 판정 방법

경계가 애매하면 **무엇이 겹치는지 한 문장으로 적어 봅니다.** 적을 것이 없으면
조율 대상이 아닙니다. 겹치는 것이 생기는 시점에 등록해도 늦지 않습니다.

---

## 3. Task 명세 작성

### 3.1 공통 규약 문서를 먼저 만듭니다

섹션별 명세는 `ORCA_TASK_CAPSULE_V2` 스키마([`orca_task_capsule_v2.md`](orca_task_capsule_v2.md))
로 작성합니다. `objective`(완료 상태)와 `acceptance`(검증 기준)를 분리하고,
이미 확인된 사실은 `ground_truth`에 `recheck: false`로 넣어 재조사를 막습니다.
`allowed_read_files`·`allowed_write_files`·`search_scope`(`deny_by_default`)로
워커가 저장소 전체를 탐색하지 못하게 합니다. 워커는 자동 로드된 `AGENTS.md`와
주입된 Capsule만 사용하므로 전역 문서 재독 금지가 사양에 들어갑니다.

섹션별 명세 뒤에 붙일 공통 문서 하나를 만들고 다음을 담습니다.

| 항목 | 내용 |
| --- | --- |
| 절대 금지 | `main` 직접 커밋, PR 생성, 이모지, `.env` 커밋·노출, 소유 밖 파일 수정, DB 스키마 변경, 원본 데이터 변경, 병합 |
| 검증 명령 | 그 환경에서 실제로 되는 형태로. 이 저장소는 `python` 이 없어 `uv run python` 입니다 |
| 격리 트리 예외 | 아래 3.3 |
| 커밋 규칙 | `type: subject`, 한국어 제목 |
| `worker_done` 필수 항목 | 브랜치명, 커밋 수, 변경 파일 전체, 검증별 결과 건수, 설계 판단 근거, 남은 위험. 본문은 3문장 이내 요약이며 상세는 `reportPath` 아티팩트로 분리 |

마지막 항목에 **"검증을 돌리지 않았거나 커밋이 0 이면 `worker_done` 을 보내지
말고 `escalation` 을 보내라"** 를 명시합니다. 이 한 줄이 허위 완료 보고를
막습니다.

### 3.1.1 아티팩트 전달과 컴팩트 `worker_done` 은 분리합니다

상세 분석 문서(수십~수백 줄의 표·로그·설계 근거)는 `docs/analysis/` 등 파일
아티팩트로 저장소에 커밋하고, `worker_done` 의 `--body` 에는 **3문장 이내 요약**
(수행 내역, 발견 사항, 잔여 리스크)만 넣습니다. `--report-path` 나 아티팩트
목록을 payload 에 남겨 코디네이터가 필요한 경우에만 열어보게 합니다.
코디네이터는 보고 JSON 전문을 직접 읽지 않고 `python3 scripts/summarize_worker_done.py --report <보고> --capsule <Capsule>` 다이제스트로 수신합니다 (종료 코드: 0 계약 준수, 1 위반 있음, 2 파싱 실패).

| 전달 경로 | 내용 | 금지 |
| --- | --- | --- |
| 파일 아티팩트 | 상세 분석, 벤치마크 표, diff 분석 | 아티팩트만 두고 `worker_done` 없이 종료 |
| `worker_done` 본문 | 3문장 요약 + `reportPath` | 원시 로그·diff·긴 보고서 전문 붙여넣기 |

원시 로그나 diff 전문을 `--body` 에 붙이면 위임으로 절약한 코디네이터 토큰을
되돌립니다.

### 3.2 섹션별 명세에 넣을 네 가지

| 항목 | 작성 방법 |
| --- | --- |
| 왜 하는가 | 현재 코드의 결함을 `파일:줄` 로 인용합니다. 코드 조각을 붙입니다 |
| 요구사항 | 판단이 필요한 지점은 "직접 판단하고 근거를 남기라" 고 명시합니다 |
| 하지 말 것 | 다른 섹션의 소유 파일을 표로 나열합니다 |
| 테스트 항목 | 무엇이 통과해야 완료인지 목록으로 적습니다 |

**브랜치명을 명세에 적지 마십시오.** Orca 가 워크트리 생성 시 자기 규칙으로
브랜치를 팝니다. 명세에 다른 이름을 적으면 워커가 물어보며 멈추거나, 같은
커밋을 두 이름으로 푸시해 중복 브랜치를 남깁니다. 2026-08-12 세션에서 두 섹션이
이 두 가지를 각각 겪었습니다.

### 3.3 격리 트리의 알려진 검증 예외

```
tests/test_data_preservation.py::test_model_bin_files_exist
tests/test_data_preservation.py::test_chroma_db_exists
```

`data/model_files/*/model.bin` 과 `chroma_db/` 는 Git 미추적이라 격리 트리에
따라오지 않습니다. **이 둘의 실패는 정상이며 차단 사유가 아닙니다.** 명세에
미리 적어 두지 않으면 워커가 오탐으로 멈춥니다.

같은 이유로 서빙 모델을 실제 로드하는 검증은 격리 트리에서 불가능합니다.

| 격리 트리에서 가능 | 주 저장소에서만 가능 |
| --- | --- |
| parquet 만 읽는 측정, 학습, 문서 작업 | 운영 경로 평가, 쌍대 검정, 승격, 서빙 실측 |

---

## 4. 모델과 추론 수준 배정

### 4.1 코디네이터 토큰이 가장 희소한 자원입니다

**코디네이터가 마르면 오케스트레이션 전체가 멈춥니다.** 워커 풀은 여러 개이고
서로 독립이지만 코디네이터는 하나입니다. 따라서 배정의 첫 기준은 작업 난이도가
아니라 **"이 작업을 위임하면 코디네이터 토큰이 실제로 줄어드는가"** 입니다.

#### 위임이 이득인 조건

**산출물이 크고 검증이 쓰기보다 값쌀 때**입니다. 2026-08-14 세션 실측입니다.

| 작업 유형 | 위임 이득 | 근거 |
| --- | --- | --- |
| 분석·감사·측정 보고서 (100줄 이상) | **큼** | 워커 4대가 130~316줄 산출. 직접 쓰는 비용이 검증 비용보다 훨씬 큼 |
| 낯선 하네스 점검과 수정이 섞인 측정 | **큼** | 코드 탐색 비용이 코디네이터 컨텍스트에 들어오지 않음 |
| 긴 측정 실행 자체 | **없음. 손해** | 배경 실행하면 요약 몇 줄만 들어옵니다. 위임하면 사양 작성 + 전달 확인 + 보고 읽기가 순수 추가분 |
| 짧은 판정 문서 (50줄 이하) | **없음** | 워크트리 생성·사양·전달 확인·문서 읽기·수치 검증·체리픽·병합이 붙어 직접 쓰는 것과 비슷하거나 더 듦 |
| 승격·게이트·병합 판정 | **위임 금지** | 4.4 |

**절감률은 50~60% 이며 90% 가 아닙니다.** 검증이 필수라서입니다. 위임은 쓰는
비용을 없애지만 검증 비용은 남깁니다.

### 4.2 풀 목록과 배정

한도가 여러 풀로 나뉘어 있다는 것이 핵심입니다. **한 풀이 마르면 작업 등급을
낮추기 전에 다른 풀의 같은 등급 모델을 먼저 확인하십시오.**

| 풀 | 성격 | 배정할 작업 |
| --- | --- | --- |
| Claude 구독 | **코디네이터 전용.** 워커로 쓰지 않습니다 | 4.4 의 코디네이터 몫 |
| Antigravity Google (`gemini-3.7-flash-high`) | 허용량이 가장 큼. **주력 워커** | 분석, 감사, 측정, 통계, 절차적 구현 |
| Antigravity Claude (`claude-opus-4-6-thinking`, `claude-sonnet-4-6`) | 별도 풀. **허용량 적음** | 판정 품질이 필요한 감사, 신중한 리팩터 |
| Codex (`gpt-5.6-luna` 등) | 주간 창. 소진되기 쉬움 | 주간 잔량이 넉넉할 때만. 측정·구현에 신뢰할 만함 |
| OpenCode 무료 (`opencode/*-free`) | 비용 0. **신뢰성 낮음** | 실패해도 손실이 없는 병렬 조사. 임계 경로에 두지 마십시오 |

기동 경로와 모델 ID 는
[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 를 따릅니다.

#### 2026-08-14 관찰된 워커 특성

| 워커 | 관찰 |
| --- | --- |
| `gemini-3.7-flash-high` | 수치 정확도 높음. 통계·측정에 적합. 주 저장소에서는 색인 때문에 기동이 멈추므로 격리 워크트리 필수 |
| `claude-opus-4-6-thinking` | 감사에서 파일·줄 인용까지 정확. 대신 `git diff main...branch` 를 merge base 기준으로 오독 |
| `claude-sonnet-4-6` | 구현 품질 양호. 사실 주장에 오류(스레드별 GC 가능) |
| Codex `gpt-5.6-luna` high | 미달을 미달로 정직하게 보고. 커밋 없이 `worker_done` 을 보내는 경향 |
| OpenCode GLM-4.7 Flash (Free) | 지시 대신 문서 재독에 맴돌다 타임아웃. 사용 중단 |

### 4.3 코디네이터 비용을 줄이는 사양 작성법

위임하기로 정했으면 **사양이 코디네이터 비용을 결정합니다.**

| 방법 | 이유 |
| --- | --- |
| **사양을 자족적으로 씁니다.** `README.md`·`AGENTS.md`·`SKILLS.md` 재독을 명시 금지 | 재독에 맴돌다 타임아웃한 사례가 있습니다. 워커 시간과 코디네이터 재작업 비용이 함께 듭니다 |
| **확정된 사실을 사양에 넣고 "재조사 불필요" 라고 적습니다** | 워커가 이미 아는 것을 다시 조사하면 결과가 늦고, 코디네이터가 그 결과를 다시 검증해야 합니다 |
| **보고에 넣을 항목을 지정합니다** (커밋 수·해시, 회차별 값, 대표값, 판정, 차단 사유) | 되묻는 왕복이 가장 비쌉니다 |
| **코디네이터가 한 명령으로 재계산할 수 있는 형태로 수치를 요구합니다** | 검증이 수십 줄 읽기에서 한 번 실행으로 줄어듭니다 |
| **원시 출력은 워커 문서에 두고 코디네이터 컨텍스트에 넣지 않습니다** | 45만 줄 diff 를 `--stat` 으로만 보고 코드 4개 파일만 읽어 판정한 사례가 있습니다 |
| **독립 작업만 병렬로 띄웁니다** | 순서 조율이 코디네이터 왕복을 만듭니다 |

### 4.4 위임하지 않는 것

아래는 코디네이터가 직접 합니다. **비용 절감의 대상이 아닙니다.**

| 항목 | 이유 |
| --- | --- |
| 워커 산출물 검증 | 2026-08-14 세션에서 **워커 4대 4건 모두 오류가 있었습니다.** 검증을 생략하면 오류가 `main` 에 들어갑니다 |
| 병합 판정과 `git diff` 확인 | 플레이북 7.2 |
| 게이트·승격 기준 제정 | 규약 성격이며 워커가 정하면 검증에 같은 비용이 듭니다 |
| 되돌리기 어려운 조작 | 브랜치 삭제, 스키마 변경, 데이터 삭제, 외부 발신 |

**검증에서 오류가 나온 4건입니다.** 위임의 이득을 계산할 때 이 비용을 빼지
마십시오.

| 워커 | 검증에서 잡은 것 |
| --- | --- |
| P4 | 부트스트랩이 실측과 4배 어긋남(요청 독립 가정 위반) |
| P5 | 브랜치 고유 파일 0개 주장 → 실제 4개 |
| P6 | "GIL 로 스레드별 GC 제어 가능" 은 사실 아님 |
| P7 | `champion_summary.json` 미참조 주장 → 실제 참조되며 병합 시 허위 성능 정보 노출 |

### 4.5 모델 ID 는 계정 종류에 따라 다릅니다

제공자별 기동 경로, 확인된 모델 ID, 기동 실패 시 우회는
[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 를
따릅니다. **"경로를 못 찾아 쓸 수 없다" 고 판정하기 전에 그 문서를 먼저
확인하십시오.**


**틀린 모델 ID 를 주면 워커가 기동 직후 죽는데, Orca 는 Task 를 `dispatched`,
워커를 `ready` 로 표시합니다.** heartbeat 도 오지 않을 뿐 오류로 보이지
않습니다.

2026-08-12 세션에서 Codex 워커 3개가 이렇게 15분간 죽어 있었습니다.

```
The 'gpt-5.1-codex' model is not supported when using Codex with a ChatGPT account.
```

발견 경로는 커밋 수와 변경 파일이 계속 0 인 것을 이상하게 여겨
`orca terminal list --json` 의 `preview` 를 직접 읽은 것이었습니다.

사용 가능한 모델은 기동 전에 확인합니다.

```bash
python3 -c "
import json
d=json.load(open('/Users/<user>/.codex/models_cache.json'))
..."
```

### 4.6 v2 모델 라우팅 원칙 (불변)

아래는 위 표들이 사실을 추가해도 바뀌지 않는 배정 원칙입니다.

| 역할 | 기본 배정 | 금지 |
| --- | --- | --- |
| **빌더 워커 (주력)** | Antigravity Gemini Flash High (`gemini-3.7-flash-high`) | 임계 경로를 저가·무료 모델에 배정 |
| **OpenCode 무료** (`opencode/*-free`) | 결정론적·병렬 조사 전용 (자동 검증이 정오를 판정하는 작업) | 공유 자원 소유권, 승격·판정·병합 근거 |
| **병합·판정·게이트** | 코디네이터 전용 | 워커 위임, `worker_done` 은 병합 권한이 아님 |

상세 역할별 추론 수준 정책은
[`orca_coordinator_token_optimization_v2.md`](orca_coordinator_token_optimization_v2.md)
11장을 따릅니다.

---

## 5. 기동 절차

```bash
# 1. Run 생성 (--objective 입니다. --title 은 없습니다)
orca orchestration run-create --objective "<목표>" --json

# 2. Task 등록. 선행 조건은 --deps 로 명시
orca orchestration task-create --task-title "<제목>" --display-name "S1" \
  --spec "$(cat s1.md)

---

$(cat common.md)" --json

# 3. ready 로 전환. 이 단계를 빠뜨리면 task_not_startable 로 거부됩니다
orca orchestration task-update --id <task_id> --status ready --json

# 4. 워커 기동
orca orchestration worker-start --task <task_id> \
  --agent <claude|codex> --model <model_id> --effort <level> \
  --worktree new-top-level --name <이름> --repo path:<저장소 절대경로> --json
```

### 5.1 기동 직후 반드시 할 일

```bash
cp <주 저장소>/.env <워크트리>/.env
```

`.env` 는 Git 미추적이라 새 워크트리에 따라가지 않습니다. 이 저장소는
`Settings()` 가 `SECRET_KEY` 를 필수로 검증하므로, **없으면 설정을 읽는 코드가
전부 실패합니다.** 워커가 스스로 진단하기 어려운 실패입니다.

값을 문서나 커밋에 남기지 마십시오. 워커에게도 커밋 금지를 함께 지시합니다.

gitignore 대상 데이터가 필요한 섹션이면 그것도 복사합니다. 예를 들어
`data/analysis/` 의 parquet 을 읽는 섹션은 해당 디렉터리를 복사해 주고
**읽기 전용임을 명세에 적습니다.**

### 5.2 주입이 도달했는지 워커 쪽에서 확인하십시오

**`dispatch --inject` 는 조용히 실패합니다.** 2026-08-14 세션에서 워커 3대가
6분 동안 아무 일도 하지 않았고, 코디네이터는 그것을 "지시서를 읽는 중" 으로
보고했습니다.

| 신호 | 그때 값 | 실제 |
| --- | --- | --- |
| `dispatch --inject` 반환 | `ok: true`, dispatch id 발급 | 전달 실패 |
| Task status | `dispatched` | 워커는 아무것도 받지 않음 |
| `orchestration check --terminal` | `No messages.` | 주입이 유일한 전달 경로였고 사라짐 |
| 워크트리 | 커밋 0, 미커밋 0 | 정체 |

원인은 **CLI 부팅 중 워크스페이스 신뢰 확인 대화창**입니다. Antigravity CLI 는
기동 시 `No, exit` 선택지가 있는 대화창을 띄우며, 그 시점에 주입된 키 입력은
대화창에 먹혀 사라집니다. Orca 쪽 기록은 정상으로 남습니다.

따라서 Dispatch 직후 **워커 터미널을 직접 읽습니다.**

```bash
orca terminal read --terminal <handle> | tail -8
```

프롬프트가 비어 있으면 도달하지 않은 것입니다. 배너와 빈 `>` 만 보이는 상태를
"준비됨" 으로 읽지 마십시오.

도달하지 않았을 때 재주입은 거부됩니다(`only ready tasks can be dispatched`).
`terminal send` 로 직접 전달합니다. 이때 `worker_done` 명령 전문을 함께 넣어야
합니다. 주입 preamble 이 사라졌으므로 워커는 보고 방법을 모릅니다.

```bash
orca terminal send --terminal <handle> --enter --text \
  "지시서 파일 <경로> 를 읽고 수행하십시오. 완료 후: orca orchestration send \
   --to run:<run_id> --type worker_done --task-id <task_id> \
   --dispatch-id <dispatch_id> --outcome succeeded --subject '...' --body '...'"
```

`worker-start --agent claude|codex|cursor` 경로는 이 문제가 없습니다. 감독
워커로 등록되어 `worker-read` 로 출력을 읽을 수 있습니다. **`terminal create` +
주입 경로는 `worker-list` 와 `worker-read` 에 나타나지 않으므로** 관측 수단이
`terminal read` 하나뿐입니다. 이 차이를 알고 배정하십시오.

### 5.3 재기동

모델 ID 오류처럼 워커가 죽었을 때입니다. 워크트리에 변경이 없으면 그대로
재사용하므로 잃는 것이 없습니다.

```bash
orca orchestration worker-stop --dispatch <dispatch_id> --json
orca orchestration worker-start --task <task_id> \
  --agent codex --model <올바른 id> --effort medium \
  --worktree path:<워크트리 절대경로> --retry-of <이전 dispatch_id> --json
```

기존 워크트리를 쓸 때는 생성 플래그(`--name`, `--repo`, `--base-branch` 등)를
쓸 수 없습니다.

---

## 6. 감독

대부분의 사고가 여기서 납니다.

### 6.1 상태 표시를 믿지 마십시오

**Task status 와 worker status 는 거짓 양성이 있습니다.** 죽은 워커도
`dispatched` / `ready` 로 보입니다. 판단 근거는 둘뿐입니다.

```bash
git -C <워크트리> log --oneline main..HEAD | wc -l
git -C <워크트리> status --short
orca terminal list --worktree path:<워크트리> --json   # preview 를 읽습니다
```

`worker_done` 이 왔는데 커밋이 0 이면 병합할 대상이 없다는 뜻입니다. 보고
내용과 무관하게 완료로 처리하지 마십시오.

### 6.2 정체 판정 기준

"진행 중" 이라고 보고하기 전에 아래를 통과해야 합니다. 근거 없이 진행 중이라고
쓰면 유휴 워커를 작업 중으로 잘못 보고하게 됩니다.

| 시점 | 확인 | 통과 조건 |
| --- | --- | --- |
| Dispatch 직후 2분 내 | `orca terminal read` | 프롬프트가 비어 있지 않고 응답 중 |
| 이후 5분 주기 | 커밋 수와 미커밋 변경 수 | 둘 중 하나가 증가 |
| 커밋 0 + 미커밋 0 이 5분 이상 | `orca terminal read` 재확인 | 응답 중이면 계속, 프롬프트가 비어 있으면 정체 |

**프로세스 생존은 진척의 근거가 아닙니다.** `ps` 로 CLI 가 떠 있는 것을 확인해도
지시를 못 받았으면 아무 일도 하지 않습니다. 2026-08-14 세션에서 코디네이터가
정확히 이 오류를 냈습니다. `ps` 로 3대 생존을 확인하고 "지시서를 읽는 단계" 로
보고했으나 실제로는 빈 프롬프트였습니다.

읽기 단계와 정체는 **터미널 출력으로만** 구분됩니다.

### 6.2.1 반려 후 재작업은 완료된 Task 에 태우지 마십시오

Level 1 이나 Level 3 에서 결함을 찾아 반려할 때, 이미 `completed` 인 Task 의
터미널에 지시만 보내면 워커는 정상적으로 고칩니다. 그러나 두 번째
`worker_done` 은 Orca 가 거부합니다.

```text
Rejected worker_done: <원래 제목>
```

Task 를 두 번 완료할 수 없기 때문입니다. 결과로 다음이 남습니다.

| 남는 것 | 사라지는 것 |
| --- | --- |
| 워커의 수정 커밋 | 재작업 지시의 근거와 수용 판정 |
| `Rejected` 메시지 | 2차 검증 결과의 수명주기 기록 |

산출물은 커밋에 남으므로 병합 판단은 가능합니다. 하지만 **왜 반려했고 무엇이
고쳐졌는지가 이력에 남지 않아** 다음 세션이 경위를 복원할 수 없습니다.
2026-08-15 에 세 워커 모두 이 상태가 되어 `Rejected worker_done` 8건이
쌓였습니다.

반려 후 재작업은 다음 둘 중 하나로 합니다.

```bash
# 방법 A: 같은 Task 를 ready 로 되돌린 뒤 재 Dispatch
orca orchestration task-update --id <task_id> --status ready --json
orca orchestration dispatch --task <task_id> --to <handle> --inject --json

# 방법 B: 재작업용 Task 를 새로 만들고 원 Task 를 선행 의존성으로 둔다
orca orchestration task-create --run <run_id> --task-title "<원제목> 반려 수정" \
  --deps '["<원 task_id>"]' --spec "<새 Capsule 경로 안내>" --json
```

어느 쪽이든 **새 `report_path` 를 함께 줍니다.** 같은 경로를 쓰면 1차 보고가
덮여 사라집니다 (규약 [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md) 2.9.3).

방법 B 가 이력 보존에는 낫습니다. 반려 사유가 별도 Task 사양으로 남기
때문입니다. 방법 A 는 왕복 지표(`roundtrips`)를 한 Task 에 모아 볼 수 있습니다.

### 6.3 `ask` 는 `reply` 로만 풀립니다

워커가 `orca orchestration ask` 로 물으면 **블로킹 대기**합니다.

```bash
orca orchestration reply --id <msg_id> --body "<답변>" --json
```

`orchestration send` 로 답하면 **워커는 계속 멈춰 있습니다.** 겉으로는 정상으로
보이고 heartbeat 만 없습니다. 2026-08-12 세션에서 한 섹션이 이 이유로 4분간
헛되이 멈춰 있었습니다.

`msg_id` 는 `orca orchestration inbox --json` 에서 찾습니다.

### 6.4 `worker_done` 이후 워커는 메시지를 받지 못합니다

`orchestration send` 는 워커가 `check` 를 실행해야 도착합니다. `worker_done` 을
보내고 턴을 끝낸 워커는 `check` 를 돌리지 않습니다.

```bash
orca terminal send --terminal <handle> --text "<지시>" --enter
```

**`--enter` 를 빠뜨리면 텍스트가 입력창에 남기만 하고 전달되지 않습니다.**
화면에는 보이므로 보낸 것으로 착각하기 쉽습니다.

사람이 하위 창에 직접 타이핑하다 Enter 를 누르지 않은 미전송 지시도 같은
상태로 남습니다. 유휴로 보이는 워커는 `preview` 를 먼저 확인하십시오.
2026-08-12 세션에서 완료된 섹션의 입력창에 사람이 남긴 미전송 지시가 발견됐고,
코디네이터가 `--enter` 만 보내 제출했습니다.

### 6.5 메일함은 계속 비웁니다

```bash
orca orchestration check --json
orca orchestration check --ack <delivery_id> --json
```

`--ack` 하지 않으면 같은 메시지가 재배달되어 다음 세션 시작 때까지 알림이
반복됩니다. 코디네이터가 `run:` 앞으로 보낸 공지는 **자기 자신에게도
배달**되므로 그것도 ack 해야 합니다.

`check --json` 은 여러 JSON 객체를 연달아 출력할 수 있습니다. 파싱할 때
`json.JSONDecoder().raw_decode` 를 반복 호출하십시오. 단순 `json.load` 는
실패합니다.

---

## 7. 병합

### 7.1 수신 및 병합 순서

1. **`worker_done` 수신 및 다이제스트 검증**: 코디네이터는 보고 JSON 전문을 직접 읽지 않고 다이제스트 도구로 검증 및 요약을 받습니다.
   ```bash
   python3 scripts/summarize_worker_done.py --report <보고> --capsule <Capsule>
   ```
   (종료 코드: `0` 계약 준수, `1` 위반 있음, `2` 파싱 실패)
2. **Level 1 (결정론적 기계 검증)**: 5대 게이트(변경 파일, 범위, 테스트, 규칙, 리뷰 보고)를 단일 게이트 도구 호출로 수행합니다.
   ```bash
   python3 scripts/orca_level1_gate.py --base main --branch <작업브랜치> --repo <워크트리경로> --tests '<대상 테스트>' --capsule <Capsule 경로>
   ```
   (종료 코드: `0` 통과, `1` 게이트 실패, `2` 도구 오류)
   이 두 도구는 2026-08-15 첫 실사용에서 실제 계약 위반 4건을 검출했습니다. 검출 대상은 필수 필드 누락 version branch commit_count blocking_issues 였습니다.
3. `git fetch origin`
4. **`git diff` 로 운영 코드를 직접 읽습니다**
5. `git merge --no-ff origin/<브랜치> -m "merge: <설명>"`
6. `uv run pytest tests/ -q`
7. `uv run python scripts/validate_agent_rules.py`
8. `uv run ruff check .`
9. `git push origin main`

병합은 코디네이터만 합니다. **`worker_done` 은 병합 권한이 아닙니다.**

### 7.2 워커 보고를 그대로 믿고 병합하지 마십시오

2026-08-12 세션에서 완료 보고된 섹션의 응답 스키마에 예외 원문 노출이 있었고,
`git diff` 를 읽어서 찾았습니다. 워커의 보고서에는 그 내용이 없었습니다.
설계가 좋은 섹션에서도 이런 것이 나옵니다.

### 7.3 통과 건수를 기록하십시오

병합마다 이전 대비 늘어난 테스트 수가 그 섹션의 신규 테스트 수와 맞는지
확인합니다. 2026-08-12 세션 기록입니다.

| 병합 | 통과 | 증가 |
| --- | --- | --- |
| 기준선 | 823 | — |
| S1 | 827 | +4 |
| S3 | 836 | +9 |
| S6 | 838 | +2 |
| S2, S7 | 863 | +25 |

### 7.4 접합부를 따로 확인하십시오

**섹션별로는 전부 통과해도 합치면 깨지는 것이 있습니다.** 섹션 경계에 걸친
계약은 어느 섹션의 테스트도 검증하지 않습니다.

2026-08-12 세션 실례입니다. 한 섹션이 `ENVIRONMENT=production` 에서
`CORS_ALLOWED_ORIGINS` 를 필수로 만들었는데, 그 변수를 컨테이너에 전달하는
`docker-compose.yml` 은 다른 섹션 소유라 수정되지 않았습니다. 이미지에 `.env`
가 없으므로(`.dockerignore`) **운영 배포 시 app 과 worker 가 기동 즉시
죽는 상태**였습니다. 두 섹션의 테스트는 모두 통과했습니다.

접합부는 추측하지 말고 실측합니다.

```bash
uv run python -c "
from src.app.core.config import Settings
try: Settings(_env_file=None, ENVIRONMENT='production', ...)
except Exception as exc: print('기동 실패:', exc)
"
docker compose config --quiet
```

### 7.5 코디네이터의 수정도 브랜치를 거칩니다

접합부 수정이라도 `main` 에 직접 커밋하지 않습니다. 브랜치를 파고
`--no-ff` 로 병합합니다. 재발 방지 테스트를 함께 넣습니다.

---

## 8. 정리

| 순서 | 조치 | 명령 |
| --- | --- | --- |
| 1 | 완전 병합 확인 | `git branch --merged origin/main` |
| 2 | 워커와 워크트리 해제 | `orca orchestration worker-release --dispatch <id>` |
| 3 | 수동 생성 트리 제거 | `git worktree remove <path>` |
| 4 | 병합 완료 브랜치 삭제 | `git branch -d <branch>` |

`git branch -d` 가 거부하면 **아직 병합되지 않았다는 뜻입니다. `-D` 로 강제하지
마십시오.**

재사용된 터미널은 `worker-release` 로 닫히지 않고 `retained` 로 돌아옵니다.

```bash
orca terminal list --json
orca terminal show --terminal <handle>    # preview 로 종결 여부와 tabId 확인
orca terminal close --terminal <handle>   # --tab 없이 창 단위로만
```

**`--tab` 을 쓰지 마십시오.** 워커 창이 코디네이터와 같은 탭의 분할 창인 경우가
있고, 그때 `--tab` 은 코디네이터까지 닫아 조율이 끊깁니다.

다른 섹션이 하나라도 돌고 있으면 일괄 정리를 하지 않습니다.

---

## 9. 상태 어휘

사용자에게 보고할 때 아래를 구분합니다. 근거 없이 상위 상태를 쓰지 마십시오.

| 상태 | 조건 |
| --- | --- |
| 등록됨 | Run 과 Task 는 있으나 Dispatch 전 |
| 진행 중 | 유효한 Dispatch 가 있고 커밋 또는 변경 파일로 활동이 확인됨 |
| 검증 완료 | `worker_done` 과 요구 검증 결과가 확인됨 |
| 병합 완료 | 검증된 브랜치가 `main` 에 `--no-ff` 로 병합되고 원격 반영까지 확인됨 |
| 차단됨 | 사용자 결정 또는 외부 상태 없이는 진행 불가 |

**"기록이 없다" 와 "작업을 안 했다" 는 다릅니다.** 런타임이 끊긴 채 작업이
진행된 경우 둘을 구분해 보고합니다.

---

## 10. 함정 요약

빠뜨리기 쉬운 순서로 정렬했습니다.

| # | 함정 | 증상 |
| --- | --- | --- |
| 1 | 틀린 모델 ID | 워커가 죽었는데 Task 는 `dispatched`, 워커는 `ready` |
| 2 | `.env` 미배치 | 설정을 읽는 코드 전부 실패. 워커가 원인을 못 찾음 |
| 3 | `ask` 에 `send` 로 답함 | 워커가 무한 블로킹. 겉으로는 정상 |
| 4 | `terminal send` 에 `--enter` 누락 | 텍스트가 입력창에 남기만 함 |
| 5 | `worker_done` 이후 `send` | 아무도 읽지 않음 |
| 6 | `task-update --status ready` 누락 | `task_not_startable` |
| 7 | 명세에 브랜치명 지정 | 워커가 멈춰 묻거나 중복 브랜치 생성 |
| 8 | 격리 트리 예외 미고지 | 정상 실패를 차단 사유로 오해 |
| 9 | 접합부 미검증 | 섹션별 통과, 합치면 운영 기동 실패 |
| 10 | `--ack` 누락 | 같은 메시지 무한 재배달 |
| 11 | `--tab` 으로 터미널 닫기 | 코디네이터까지 닫혀 조율 중단 |
| 12 | `git branch -D` 강제 | 미병합 유일본 소실 |
