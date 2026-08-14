# Orca 다중 섹션 오케스트레이션 실행 지침

> **작성일**: 2026-08-12
> **버전**: v1.0.0
> **상태**: 실행 검증 완료. 2026-08-12 세션에서 7개 섹션(S1~S7)을 병렬 운영하고 전량 병합한 결과를 반영했습니다.
> **대상**: 이 저장소에서 코디네이터 역할을 맡는 사람 또는 에이전트
> **규약 정본**: [`AGENTS.md`](../../AGENTS.md) 4장, [`orca-section-coordination`](../../.agents/skills/orca-section-coordination/SKILL.md)
> **관련 문서**: [`multi_agent_setup.md`](multi_agent_setup.md), [`git_branching_strategy.md`](git_branching_strategy.md)

---

## 0. 이 문서의 위치

`AGENTS.md` 4장은 **무엇을 지켜야 하는가**를 정합니다.
`orca-section-coordination` 스킬은 **어떤 절차를 따르는가**를 정합니다.
본 문서는 **실제로 돌려 보니 어디서 깨졌는가**를 정합니다.

세 문서가 어긋나면 `AGENTS.md` 가 우선합니다. 본 문서는 그 규약을 대체하지
않고, 규약을 따르는 도중 사람이나 에이전트가 실제로 빠졌던 함정을 기록합니다.

**이 문서에 적힌 함정 대부분은 겉으로 정상으로 보입니다.** 그래서 절차를
지켰다고 생각하는 동안 시간이 흘러갑니다.

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

섹션별 명세 뒤에 붙일 공통 문서 하나를 만들고 다음을 담습니다.

| 항목 | 내용 |
| --- | --- |
| 절대 금지 | `main` 직접 커밋, PR 생성, 이모지, `.env` 커밋·노출, 소유 밖 파일 수정, DB 스키마 변경, 원본 데이터 변경, 병합 |
| 검증 명령 | 그 환경에서 실제로 되는 형태로. 이 저장소는 `python` 이 없어 `uv run python` 입니다 |
| 격리 트리 예외 | 아래 3.3 |
| 커밋 규칙 | `type: subject`, 한국어 제목 |
| `worker_done` 필수 항목 | 브랜치명, 커밋 수, 변경 파일 전체, 검증별 결과 건수, 설계 판단 근거, 남은 위험 |

마지막 항목에 **"검증을 돌리지 않았거나 커밋이 0 이면 `worker_done` 을 보내지
말고 `escalation` 을 보내라"** 를 명시합니다. 이 한 줄이 허위 완료 보고를
막습니다.

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

### 4.1 배정 기준

| 작업 성격 | 배정 |
| --- | --- |
| 설계 선택, 응답 계약 변경, 원인 규명 | 최상위 모델 + high |
| 사양이 확정된 절차적 구현, 테스트 추가 | 중간 모델 + medium |

잔여 한도가 적은 풀에는 절차적 작업을, 여유 있는 풀에 판단 작업을 줍니다.

### 4.2 모델 ID 는 계정 종류에 따라 다릅니다

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

### 5.2 재기동

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

### 6.2 `ask` 는 `reply` 로만 풀립니다

워커가 `orca orchestration ask` 로 물으면 **블로킹 대기**합니다.

```bash
orca orchestration reply --id <msg_id> --body "<답변>" --json
```

`orchestration send` 로 답하면 **워커는 계속 멈춰 있습니다.** 겉으로는 정상으로
보이고 heartbeat 만 없습니다. 2026-08-12 세션에서 한 섹션이 이 이유로 4분간
헛되이 멈춰 있었습니다.

`msg_id` 는 `orca orchestration inbox --json` 에서 찾습니다.

### 6.3 `worker_done` 이후 워커는 메시지를 받지 못합니다

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

### 6.4 메일함은 계속 비웁니다

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

### 7.1 순서

1. `git fetch origin`
2. **`git diff` 로 운영 코드를 직접 읽습니다**
3. `git merge --no-ff origin/<브랜치> -m "merge: <설명>"`
4. `uv run pytest tests/ -q`
5. `uv run python scripts/validate_agent_rules.py`
6. `uv run ruff check .`
7. `git push origin main`

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
