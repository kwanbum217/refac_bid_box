---
name: orca-section-coordination
description: refac_bid_box에서 둘 이상의 에이전트·섹션을 의존성, 공유 자원, 완료 검증과 함께 Orca로 조율할 때 사용합니다. 작업 분할, 병합 대기, 장시간 학습·색인, 교차 섹션 인수인계, 진행 현황 보고가 포함되면 반드시 호출합니다.
---

# Orca 섹션 협업 스킬 지침

본 스킬은 섹션별 작업을 단순 대화나 터미널 상태가 아니라 Orca의 Run, Task, Dispatch, `worker_done` 기록으로 관리합니다. 작업이 다른 작업의 시작 조건이면, 의존 작업의 검증된 완료 전에는 시작하지 않습니다.

## 1. 적용 조건

**같은 프로젝트에서 동시에 일한다는 사실만으로는 조율 사유가 되지 않습니다.**
겹치는 것이 있어야 조율합니다. 다음 중 하나라도 해당하면 작업 시작 전에 이
스킬을 사용합니다.

- 다른 섹션과 **같은 파일·브랜치·작업 트리**를 다룹니다.
- 한 작업의 산출물, 병합, 검증이 다음 작업의 시작 조건입니다.
- Git 병합, Docker·DB, 대량 색인, 장시간 ML 학습처럼 공유하거나 충돌할 수 있는 자원을 사용합니다.
- 사용자가 섹션의 진행률, 완료 여부, 대기 사유 또는 인수인계를 관리하려고 합니다.

적용하지 않는 경우입니다.

- 단일 에이전트의 독립적이고 짧은 읽기 전용 작업
- **파일·자원·순서가 다른 섹션과 겹치지 않는 작업.** 격리 작업 트리에서
  자기 브랜치의 새 파일만 만들고 검증까지 마치는 측정·문서화가 여기 해당합니다

경계가 애매하면 **무엇이 겹치는지 한 문장으로 적어 보십시오.** 적을 것이
없으면 조율 대상이 아닙니다. 겹치는 것이 생기는 시점(병합, 공유 자원 점유)에
그때 등록해도 늦지 않습니다.

## 2. 시작 계약

1. `orca status --json`으로 런타임을 확인하고, `orca skills get orchestration`의 현재 지침을 읽습니다.
2. 새 작업 묶음이면 `orca orchestration run-create`로 Run을 만들고, 이어받은 작업이면 Run·Task·Dispatch 상태를 읽어 현재 소유자를 확인합니다.
3. 모든 섹션을 Task로 등록합니다. 선행 조건은 `--deps`로 명시하고, Task 사양은 **Task Capsule v2 표준 포맷(`ORCA_TASK_CAPSULE_V2`)**을 준수하여 작성합니다. 사양에는 목표(`objective`), 선행 맥락(`why_now`), 기검증 사실(`ground_truth`), 허용 파일(`allowed_read_files`/`allowed_write_files`), 거부 기반 검색 범위(`search_scope`), 절대 금지(`forbidden`), 공유 자원(`shared_resources`), 검증 명령(`verification_commands`), 에스컬레이션 조건(`escalate_when`)을 엄격히 명시합니다. 상세는 [`docs/ops/orca_task_capsule_v2.md`](../../../docs/ops/orca_task_capsule_v2.md) 및 [`.agents/templates/task_capsule_v2.yaml`](../../../.agents/templates/task_capsule_v2.yaml)을 참조하십시오.
4. 병합, 데이터 변경, Docker Compose 제어, DB, ML 학습 장치, Meilisearch 색인 등 충돌 가능 자원은 한 Task만 소유하도록 합니다. 다른 Task는 의존성으로 대기시킵니다.
5. 독립 Task만 병렬 Dispatch합니다. 하나의 브랜치나 작업 트리에 동시에 쓰기 작업을 배정하면 안 됩니다. 미커밋 산출물을 이어받아야 하는 의존 작업만 같은 작업 트리에서 순차 실행합니다.
6. **동시 쓰기 워커는 3대를 넘기지 않습니다.** 작업 트리가 겹치지 않아도 적용됩니다. 코디네이터가 하나이므로 검증이 병목이 되면 미검증 병합 위험이 커집니다. 읽기 전용 워커는 상한에 포함하지 않습니다. `scripts/orca_taskctl.py dispatch` 가 이 상한을 기계로 강제하며, 점유 판정은 `task-list` 의 `dispatched` 상태로 합니다. `worker-list` 는 `worker-start` 워커만 보므로 쓰지 않습니다. 상세는 [`AGENTS.md`](../../../AGENTS.md) 4장 5.1.

### 2.1 표준 검증

Task 사양의 검증 명령에는 **최소한 다음 둘**을 포함합니다. 병합 시점에 처음
돌리면 실패가 늦게 드러납니다.

```bash
uv run pytest tests/ -q
python3 scripts/validate_agent_rules.py --quiet
```

문서만 바꾼 Task는 두 번째만으로 충분합니다. 운영 코드나 `src/ml/` 을 건드린
Task는 반드시 둘 다 돌립니다.

`scripts/orca_taskctl.py expand` 는 쓰기 범위가 요구하는 능력에 맞는 명령만
붙입니다. 문서 전용 범위에는 pytest 를 붙이지 않고, `frontend/` 가 있으면
frontend 검증을, Dockerfile 이나 compose 가 있으면 각 검증을 붙입니다. Capsule
을 손으로 쓸 때는 아래 표를 보고 직접 적어야 합니다.

Level 1 게이트 3 은 변경 파일이 요구하는 **검증 능력(capability)** 을 계산하고,
그 능력을 덮는 명령이 없으면 `--strict` 에서 실패합니다. 영역 하나로 묶으면 그
영역의 아무 명령이나 하나만 통과해도 덮인 것이 되므로 능력 단위로 봅니다.

| 변경 대상 | 요구 능력 | 덮는 명령 |
| --- | --- | --- |
| `frontend/**` | `frontend_test`, `frontend_build` | `npm --prefix frontend run test` / `... run build` |
| `Dockerfile*`, `.dockerignore` | `docker_build:<컨텍스트>` | `docker build ... <컨텍스트>` |
| `docker-compose*.yml` | `compose_config` | `docker compose config -q` |
| `.github/workflows/*.yml` | `workflow_lint` | `uv run actionlint` |
| 그 밖의 코드 | `backend_pytest` | `uv run pytest ...` |
| 문서(`.md`/`.rst`/`.adoc`) | 없음 | - |

`npm run lint` 처럼 능력 대응이 없는 스크립트는 실행은 되지만 아무 능력도 덮지
않습니다. test 와 build 를 함께 수행하는 통합 스크립트를 쓰려면 게이트의
`NPM_SCRIPT_CAPABILITIES` 에 이름을 등록합니다.

**Docker 는 AGENTS.md 4장의 공유 자원입니다.** docker 검증이 붙는 Task 는
`shared_resources` 에 `docker` 를 `exclusive` 로 선언해야 합니다.
`orca_taskctl.py expand` 가 능력 판정에서 이를 자동으로 붙이지만, Capsule 을
손으로 쓸 때는 직접 적어야 합니다. 쓰기 범위에 docker 가 없어도 검증 명령에
docker 를 직접 적으면 점유가 잡힙니다.

**docker_build 능력은 빌드 컨텍스트별로 갈립니다.** 루트 `.dockerignore` 가
`frontend/` 를 제외하므로 `docker build .` 은 `frontend/Dockerfile` 을 읽지도
않습니다. 컨텍스트를 구분하지 않으면 루트 빌드 하나가 모든 Dockerfile 을
검증한 것이 됩니다.

```bash
docker build -t refac-bid-box-root:orca-gate .           # docker_build:.
docker build -t refac-bid-box-frontend:orca-gate frontend # docker_build:frontend
```

셸 스크립트(`.sh`)는 저장소에 파일이 없어 별도 능력을 두지 않습니다. 러너
없는 능력을 미리 만들면 첫 파일이 생기는 순간 게이트가 교착합니다. 셸 스크립트를
도입할 때 shellcheck 와 함께 능력을 추가합니다.

실행되는 명령은 허용 목록(`uv run pytest ...`, `npm ci`, `npm run <script>`,
`docker build`, `docker compose config`, `uv run actionlint`)으로 제한되며,
그 밖의 문자열은 게이트 3 실패로 거부됩니다.

### 2.2 작업 트리는 Orca 를 정본으로 씁니다

섹션 작업용 격리 트리는 `orca worktree create` 로 만듭니다. `git worktree add`
로 만든 트리는 `orca worktree list` 에 잡히지 않아 코디네이터가 실제 점유
상태를 볼 수 없습니다.

이미 수동으로 만든 트리가 있으면 **Task 사양의 공유 자원 항목에 경로를 적어**
다른 섹션이 그 경로를 건드리지 않게 합니다. 작업이 끝나면 `git worktree remove`
로 정리하고 그 사실을 `worker_done` 에 남깁니다.

### 2.3 격리 트리의 알려진 검증 예외

격리 작업 트리에는 `.gitignore` 대상 산출물이 없습니다. 이 저장소에서는
`data/model_files/*/model.bin` 과 `chroma_db/` 가 여기 해당합니다.

    tests/test_data_preservation.py::test_model_bin_files_exist
    tests/test_data_preservation.py::test_chroma_db_exists

**이 둘이 격리 트리에서 실패하는 것은 정상입니다.** 주 저장소에서 해당 테스트만
단독 재실행해 통과를 확인하고, `worker_done` 에 그 사실을 함께 적습니다. 이
예외를 모르면 오탐으로 후속 Task 가 차단됩니다.

### 2.4 서빙 모델을 로드하는 작업은 주 저장소에서 돌리십시오

같은 이유로 **`data/model_files/*/model.bin` 을 읽는 스크립트는 격리 트리에서
동작하지 않습니다.** `ModelRegistry` 가 워크트리 루트 기준으로 경로를 잡아
"모델 파일을 찾을 수 없습니다" 로 전부 실패합니다.

    격리 트리에서 가능     parquet 만 읽는 측정, 학습, 문서 작업
    주 저장소에서만 가능   운영 경로 평가, 쌍대 검정, 승격, 서빙 실측

`compare_servc_models_paired.py`, `eval_servc_asof.py`,
`measure_serving_model.py` 가 후자입니다. 이 작업들은 서빙 루트라는 **공유
자원을 점유**하므로 Task 로 등록해 소유권을 명시하십시오.

### 2.5 워커의 DB 조회는 전용 실행기로만 시키십시오

**워커에게 `docker exec ... mysql` 을 손으로 조립하게 하지 마십시오.** 자동 승인은
읽기 전용 `mysql -e` 만 허용하는데, 워커가 형태를 조금만 바꾸면(`sh -c` 로 감싸기,
환경변수 참조 방식 변경) 화이트리스트를 벗어나 **질의마다 사람 승인을 기다립니다.**
2026-09-01 에 낙찰하한율 조사 워커가 이 지점에서 반복해서 멈췄습니다.

```bash
uv run python scripts/db_readonly_query.py --sql "SELECT COUNT(*) FROM bid_results"
uv run python scripts/db_readonly_query.py --sql "SHOW TABLES" --format json --limit 50
```

`uv run python scripts/...` 는 이미 자동 승인 대상이라 워커가 멈추지 않습니다.
실행기는 `SELECT`·`SHOW`·`EXPLAIN`·`DESC`·`WITH` 로 시작하는 **단일 문장만** 통과시키고,
세미콜론 다중 문장과 `INTO OUTFILE` 같은 우회를 거부하며, `READ ONLY` 트랜잭션으로
드라이버 수준에서도 쓰기를 막습니다.

Capsule 의 `ground_truth` 에 이 명령 형태를 못 박으십시오. 형태를 자유롭게 두면
워커는 매번 다른 명령을 만들어 냅니다.

## 3. 감독 절차

1. 각 Task는 `orca orchestration worker-start` 또는 `dispatch --inject`로 Dispatch합니다. 사용자 요청에 모델·추론 수준이 있으면 해당 값도 Dispatch 시 반영합니다.
2. Dispatch 생성 직후 **워커가 지시를 실제로 받았는지**를 워커 쪽에서 확인합니다. `task-list`와 `dispatch-show`는 Orca 기록만 보여주므로 근거가 되지 않습니다. `dispatch --inject`가 `ok: true`를 반환하고 Task가 `dispatched`로 바뀌어도 전달은 실패할 수 있습니다. `orca terminal read --terminal <handle>`로 프롬프트가 비어 있지 않고 워커가 응답 중인지 확인합니다.
3. 기동 후 2분 안에 2번 확인을 하고, 이후 커밋 0건과 미커밋 변경 0건이 5분 이상 이어지면 정체로 판정해 터미널 출력을 다시 읽습니다. 진행 중이라고 보고하기 전에 이 확인을 거칩니다.
4. 장시간 작업은 터미널 출력만으로 완료라고 판단하지 않습니다. 코디네이터는 `check --wait --types worker_done,escalation,question`으로 상태를 기다립니다.
5. 워커는 검증이 끝난 뒤 **`ORCA_WORKER_DONE_V2` 계약**에 따라 `worker_done`을 정확히 한 번 전송합니다. 본문에는 3문장 요약(수행 내역, 발견 사항, 잔여 리스크)과 파일 아티팩트 경로를 명시합니다.
6. `worker_done`을 수신한 뒤 코디네이터는 결정론적 기계 검증과 독립 리뷰어 워커(`ORCA_REVIEW_DONE_V2`) 감사를 거쳐 핵심 diff를 검토한 후 다음 의존 Task를 시작합니다.
   - 반려 후 재작업은 완료된 Task 에 태우지 않습니다. 2차 `worker_done` 이 거부되어(`Rejected worker_done`) 반려 사유와 수용 판정이 이력에서 사라집니다. Task 를 `ready` 로 되돌려 재 Dispatch 하거나 재작업용 Task 를 새로 만들고, 새 `report_path` 를 함께 전달합니다.
7. 실패·차단은 완료로 바꾸지 않습니다. `escalate_when` 조건에 해당하면 워커는 스스로 범위를 넓히지 않고 `escalation` 또는 `question`으로 보고하며, 코디네이터가 추가 범위를 승인하거나 Task Capsule을 갱신합니다.

### 3.1 배정은 코디네이터 토큰을 기준으로 정합니다

**워커 풀은 여러 개이고 서로 독립이지만 코디네이터는 하나입니다.** 코디네이터가 마르면 조율 전체가 멈추므로, 배정의 첫 기준은 작업 난이도가 아니라 위임했을 때 코디네이터 토큰이 실제로 줄어드는지입니다.

| 작업 유형 | 처리 |
| --- | --- |
| 100줄 이상 분석·감사·측정 보고서, 낯선 코드 탐색이 섞인 작업 | **위임합니다.** 이득이 큽니다 |
| 긴 측정 실행 자체 | **위임하지 않습니다.** 배경 실행이 더 쌉니다 |
| 50줄 이하 짧은 판정 문서 | **위임하지 않습니다.** 부대 비용이 쓰는 비용과 비슷합니다 |
| 산출물 검증, 병합 판정, 게이트·승격 기준 제정, 되돌리기 어려운 조작 | **위임 금지** |

풀 배정 원칙입니다. 한 풀이 마르면 작업 등급을 낮추기 전에 **다른 풀의 같은 등급 모델을 먼저 확인합니다.**

| 풀 | 배정 |
| --- | --- |
| Codex (`gpt-5.6-sol`, effort `high`) | 기본 코디네이터. 워커로 쓰지 않습니다 |
| Claude 구독 | 예비 코디네이터. 한도 여유가 있을 때만 수동 전환하며 워커로 쓰지 않습니다 |
| Antigravity Google (Gemini Flash) | 주력 워커. 분석·감사·측정·절차적 구현 |
| Antigravity Claude 계열 | 별도 풀이며 허용량이 적습니다. 판정 품질이 필요한 작업 |
| OpenCode 무료 (`opencode/nemotron-3.5-lightning-free`) | 실패해도 손실 없는 병렬 조사. 임계 경로 금지 |
| Cerebras (`cerebras/gpt-oss-120b`, 컨텍스트 65K) | 읽기 범위가 Capsule 로 이미 좁혀진 조사. 프로젝트 전체 탐색 불가 |

무료 풀은 **자동 선택 대상이 아닙니다.** `scripts/orca_model_router.py` 는 역할이 `builder` 또는 `investigator` 이고 위험도가 `low` 일 때만 `--allow-free` 로 엽니다. 쓰기 범위가 있으면 병합 전 검증 경고를 남기며, `reviewer` 는 임계 경로라 개방하지 않습니다. 산출물은 반드시 재검증합니다. 상세는 [`docs/ops/orca_control_plane_tools.md`](../../../docs/ops/orca_control_plane_tools.md) 4.3.1 절입니다.

위임하기로 정했으면 **사양이 코디네이터 비용을 결정합니다.** 사양을 Task Capsule v2로 자족적으로 작성하고 `README.md`·`AGENTS.md`·`SKILLS.md` 재독을 금지하며, 확정 사실은 "재조사 불필요" 로 명시하고, 보고 항목(커밋 수·해시, 회차별 값, 대표값, 판정, 차단 사유)을 지정합니다. 수치는 코디네이터가 한 명령으로 재계산할 수 있는 형태로 요구하고, 원시 출력은 워커 문서에 두어 코디네이터 컨텍스트에 넣지 않습니다.

**위임 절감률은 50~60% 이며 90% 가 아닙니다.** 검증이 필수이기 때문입니다. 2026-08-14 세션에서 워커 4대의 산출물 4건 모두에 오류가 있었고 전부 코디네이터 검증에서 발견됐습니다. 위임 이득을 계산할 때 검증 비용을 빼지 마십시오. 상세는 [`docs/ops/orca_orchestration_playbook.md`](../../../docs/ops/orca_orchestration_playbook.md) 4장입니다.

### 3.2 코디네이터 토큰을 태우는 것은 작업량이 아니라 왕복 횟수입니다

도구를 한 번 호출할 때마다 **그 시점까지의 대화 전체가 다시 전송됩니다.** 그래서
비용은 한 일의 양이 아니라 호출 횟수에 비례해 누적됩니다. 2026-08-19 세션에서
수정 9건을 처리하는 동안 도구를 70회 넘게 호출했고, 그 대부분이 아래 네 가지로
줄일 수 있는 것이었습니다.

| 낭비 | 대신 할 것 |
| --- | --- |
| 검증 명령을 한 줄씩 따로 실행 | 보고 검증·게이트·diff 를 **한 호출로 묶기** |
| 워커 터미널을 반복해서 읽기 | **git 관찰 가능 조건**으로 배경 대기 |
| 출력을 `tail` 로 통째로 받기 | python 한 줄로 **필요한 필드만** 추출 |
| 지시 준비를 틀려 정정 왕복 | Dispatch 전 점검표(3.3)를 먼저 통과 |

**워커 터미널을 폴링하지 마십시오.** 터미널 출력은 ANSI 장식과 넓은 여백이 대부분이라
정보량 대비 가장 비쌉니다. 진행 여부는 터미널이 아니라 저장소 상태로 봅니다.

```bash
# 나쁨: 상태를 알 때까지 반복해서 읽는다
orca terminal read --terminal <handle> | tail -20   # 여러 번

# 좋음: 커밋이 생길 때까지 배경에서 기다린다 (알림 1회)
until [ -n "$(git -C <worktree> log --oneline main..HEAD)" ]; do sleep 15; done
```

터미널 읽기는 **도달 확인(3장 2번), 정체 판정, 권한·질문 모달 처리** 세 경우에만 씁니다.

**출력은 문맥에 넣기 전에 줄이십시오.** 게이트와 테스트 출력은 판정 몇 줄이면 충분합니다.

```bash
# 나쁨
python3 scripts/orca_run_reviewer.py ... --json | tail -25

# 좋음
python3 scripts/orca_run_reviewer.py ... --json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(d['exit_code'], d.get('effective_verdict'), d.get('violations'))"
```

**이미 읽은 파일을 다시 읽지 마십시오.** 계약이나 형식을 확인할 일이 생기면 외부 문서를
시행착오로 받아 오지 말고 **저장소의 검증기 소스를 직접 읽습니다.** 정본이 거기 있습니다.

### 3.2.1 감시는 도구로 합니다 (`orca_worker_watch.py`)

**Dispatch 한 워커의 감시는 사용자가 지시해야 하는 일이 아니라 상시 의무입니다.**
지침으로만 두면 지켜지지 않습니다. 2026-08-26 세션에서 워커가 CLI 만족도 설문
프롬프트에 막혀 있었고, 부팅이 `not signed in` 에서 멈춘 사례가 세 번 있었으며,
그 중 일부는 사용자가 먼저 발견했습니다.

**상시 감시 자동 기동은 워커 기동 절차의 필수 강제 조항입니다.** `scripts/orca_taskctl.py dispatch` 는 워커 기동 성공 시 상시 감시기(`scripts/orca_worker_watch.py --watch`)를 배경 프로세스로 자동 기동하며, 이미 실행 중이면 단일 인스턴스로 재사용합니다. 또한 권한 자동 승인 감시기 부착 실패 시 `dispatch` 는 fail-closed 원칙에 따라 기본값에서 즉시 거부(종료 코드 2)합니다. 의도적 우회는 명시 플래그(`--skip-auto-approve-check`) 지정 시에만 허용되며 경고가 남습니다.

```bash
python3 scripts/orca_worker_watch.py          # 사람이 읽는 요약 (1회)
python3 scripts/orca_worker_watch.py --json   # 기계 판독
python3 scripts/orca_worker_watch.py --watch  # 상시 감시 루프 (기동 시 자동 부착)
```

워커별 커밋 수, 미커밋 변경 수, 연결된 터미널, 차단 신호와 해제 방법을 한 번에
돌려줍니다. **종료 코드 1 은 사람 개입이 필요한 차단이 있다는 뜻입니다.** 그때는
조치 전에 다음 Task 를 Dispatch 하지 않습니다.

| 언제 | 무엇을 |
| --- | --- |
| Dispatch 직후 | 도달 확인과 함께 1회 |
| 진행·완료·차단을 사용자에게 보고하기 전 | 반드시 1회 |
| `worker_done` 을 ack 한 직후 | 완료 세션 회수. `python3 scripts/orca_settled_session_audit.py` |
| 대기 중 주기적으로 | 터미널 폴링 대신 이 명령으로 |

탐지하는 차단 신호는 신뢰 대화창(Antigravity·Cursor), 인증 정체, CLI 설문,
권한 요청, 진행 확인 프롬프트입니다. 화면 **끝부분만** 검사하므로 이미 승인하고
지나간 대화창을 차단으로 오판하지 않습니다.

**커밋 0 · 미커밋 0 이 계속되면 터미널을 직접 읽으십시오.** 도구는 이 상태를
정체로 단정하지 않고 참고로만 표시합니다. 조사 단계일 수도 있기 때문입니다.

### 3.3 Dispatch 전 점검표

지시 준비가 틀리면 워커당 정정 왕복이 한 번씩 더 들고, 권한 모달처럼 사람이 직접
개입해야 하는 상황도 생깁니다. **아래를 통과하기 전에 Dispatch 하지 마십시오.**

| 점검 | 이유 |
| --- | --- |
| Capsule 을 워크트리 안에 복사했는가 | `.orca/` 는 gitignore 대상이라 워크트리에 없습니다 |
| **워커에게 주는 경로가 전부 워크트리 상대 경로인가** | **절대 경로는 워커를 그 저장소로 데려갑니다.** 2026-08-23 에 서로 다른 CLI 의 워커 4대가 전부 주 저장소로 이동했고, 하나는 거기서 브랜치를 만들어 코디네이터의 병합 2건이 엉뚱한 브랜치에 쌓였습니다. `orca_taskctl.py` 가 기계로 강제하지만 Intent 의 `allowed_read_files` 와 `report_path` 는 작성자 책임입니다. `docs/ops/orca_do_not_repeat.md` 20장 |
| 지시문이 작업 트리 경계를 명시하는가 | "현재 작업 디렉터리를 벗어나면 계약 위반" 을 고지문에 넣습니다 |
| `task-create --spec` 의 Capsule 경로가 실제 경로인가 | 워커는 Capsule 고지문보다 TASK 블록을 먼저 읽습니다. 자리표시자를 남기면 없는 파일을 엽니다 |
| `review_checklist` 가 있는가 | 없으면 Level 2 를 실행할 수 없습니다. 항목 키는 `id`·`question`·`defect_when` 이고 `defect_when` 은 산문이 아니라 `yes`/`no` 극성입니다 |
| `.env` 를 워크트리에 배치했는가 | 10장 |
| `escalate_when` 에 사실 불일치 조항이 있는가 | `ground_truth` 가 틀릴 수 있습니다. 2026-08-19 에 "호출부는 3곳" 이 실제로 4곳이었고, 이 조항 덕에 드러났습니다 |
| 검증 명령이 acceptance 를 실제로 검사하는가 | 워커가 통과시킬 수 없는 사양은 왕복만 늘립니다 |
| 직전 completed Task 의 워커 터미널을 회수했는가 | 안 하면 `orca_settled_session_audit.py` 가 Dispatch 를 거부합니다 |

`dispatch` 가 `terminal_not_settled` 로 종료 코드 3 을 내는 것은 **오탐입니다.** 판정이
Dispatch 전에 이루어지고 이후 재확인이 없습니다. `orca terminal read` 로 도달을 한 번
확인하고 진행하십시오.

### 3.4 `check --ack` 는 메시지 ID 가 아니라 배치 ID 를 받습니다

`orca orchestration check` 는 **배치(delivery) 단위**로 메시지를 돌려줍니다. 응답 최상위의
`deliveryId` 가 그 배치의 식별자이고, `messages[].id`(`msg_...`)는 배치 안의 개별
메시지입니다. **`--ack` 에 넘겨야 하는 것은 `deliveryId` 입니다.**

```bash
# 나쁨: 개별 메시지 ID 를 넘긴다
orca orchestration check --ack msg_88456b5c227b
#   -> stale_delivery: Delivery msg_... does not belong to this Run.

# 좋음: 배치 ID 를 넘긴다
orca orchestration check --ack delivery_869ead08c441
```

**오류 문구가 오해를 부릅니다.** "does not belong to this Run" 은 Run 바인딩 문제처럼
읽히지만 실제 원인은 식별자 종류가 틀린 것입니다. 2026-08-19 세션에서 이 문구를 보고
Run 을 전부 순회하며 재시도했고, 그동안 배달이 쌓여 같은 알림이 반복해서 떴습니다.

배치는 FIFO 로 하나씩 나옵니다. **한 번 ack 하면 다음 배치가 나오므로, 비어질 때까지
돌려야 합니다.**

```bash
while :; do
  out=$(orca orchestration check --json)
  did=$(echo "$out" | python3 -c "import json,sys; print(json.load(sys.stdin).get('result',{}).get('deliveryId') or '')")
  [ -z "$did" ] && break
  echo "$out" | python3 -c "
import json,sys
for m in json.load(sys.stdin)['result']['messages']: print(m['type'], m['subject'])"
  orca orchestration check --ack "$did" >/dev/null
done
```

**소진하지 않으면 `question` 을 놓칩니다.** 2026-08-19 에 워커의 `question` 이 두 번째
배치에 들어 있었는데, 첫 배치를 ack 하지 않아 정규 경로로는 보이지 않았습니다. 마침
터미널 출력에서 발견해 답했으나, 그러지 않았다면 워커가 응답 대기로 멈춰 있었을
것입니다. **배달 소진은 선택이 아니라 감독 절차의 일부입니다.**

## 4. 보고 및 완료 계약 (Worker Done v2 & Review Done v2)

### 4.1 아티팩트 보고서와 Orca 수명주기 통보의 분리 (필수 규칙)

> **핵심 원칙**:
> 상세 분석 문서(Artifact Report)는 Orca 수명주기 `worker_done` 통보를 **보강(augment)**하는 것이며, 결코 **대체(replace)**할 수 없습니다.

1. **상세 분석 및 측정 산출물**: 수십~수백 줄의 분석 결과, 벤치마크 데이터, 설계 근거는 `docs/analysis/`, `docs/ops/`, `data/benchmarks/` 등의 파일 아티팩트로 저장소에 커밋합니다.
2. **수명주기 완료 통보 (`worker_done`)**: 작업 완료 시 반드시 CLI 명령(`orca orchestration send --type worker_done ...`)을 실행해야만 Orca 런타임 상의 Task가 완료 처리되고 코디네이터가 후속 DAG 작업을 진행할 수 있습니다.
3. **컴팩트 페이로드 원칙**:
   - `worker_done` 명령의 `--body`는 반드시 3문장 이내의 요약(수행 내역, 발견 사항, 잔여 리스크)으로 작성합니다.
   - 대량의 로그, diff 전체를 본문에 복사하지 않고 `--report-path` 또는 아티팩트 경로로 전달합니다.
   - 코드 변경이 요구된 작업에서 커밋 수가 0(`commit_count: 0`)이면 `succeeded`를 전송하지 않고 `escalation`을 전송합니다.
   - 코디네이터는 보고 JSON 전문을 직접 읽지 않고 `python3 scripts/summarize_worker_done.py --report <보고> --capsule <Capsule>` 다이제스트로 수신합니다 (종료 코드: 0 계약 준수, 1 위반 있음, 2 파싱 실패).

### 4.2 3단계 검증 프로세스 (Builder -> Reviewer -> Coordinator)

코디네이터는 워커 산출물을 무검증 신뢰하지 않고 다음 3단계로 검증합니다.

1. **Level 1 (결정론적 기계 검증)**: 코디네이터가 `python3 scripts/orca_level1_gate.py` 단일 호출로 6대 게이트(변경 파일, 범위, 테스트, 규칙, 린터, 리뷰 보고)를 한 번에 검증합니다 (종료 코드: 0 통과, 1 게이트 실패, 2 도구 오류).
   ```bash
   python3 scripts/orca_level1_gate.py --base main --branch <작업브랜치> --repo <워크트리경로> --tests '<대상 테스트>' --capsule <Capsule 경로>
   ```
   이 두 도구는 2026-08-15 첫 실사용에서 실제 계약 위반 4건(필수 필드 누락: version, branch, commit_count, blocking_issues)을 검출했습니다.
2. **Level 2 (독립 리뷰어 워커)**: 독립된 리뷰어 모델이 `ORCA_REVIEW_DONE_V2` 계약([`.agents/templates/review_done_v2.json`](../../../.agents/templates/review_done_v2.json))에 따라 acceptance criteria, 회귀 위험, G1(데이터 무손실), Train/Serve 단일화, 동시성 결함, 스코프 초과 수정을 교차 검증합니다.
3. **Level 3 (코디네이터 핵심 diff 검토)**: 핵심 알고리즘, DB 변경점, 모델 승격 게이트 등 비가역적 위험 지점만 선별하여 최종 병합을 결정합니다.

## 5. 상태 표현과 인수인계

사용자에게는 다음 상태를 구분하여 보고합니다.

| 상태 | 의미 |
| --- | --- |
| 등록됨 | Run과 Task는 존재하지만 아직 Dispatch되지 않았습니다. |
| 진행 중 | 유효한 Dispatch가 있고 워커가 작업 중입니다. |
| 검증 완료 | `worker_done`과 요구 검증 결과가 확인되었습니다. |
| 병합 완료 | 검증된 브랜치가 `main`에 `--no-ff`로 병합되고 원격 반영까지 확인되었습니다. |
| 차단됨 | 사용자 결정 또는 외부 상태가 없으면 진행할 수 없습니다. |

"작업 중", "병합됨", "다른 섹션이 시작 가능" 같은 표현은 위의 Orca 상태와 검증 근거가 있을 때만 사용합니다. 세션 종료 시에는 Run의 미완료 Task, 소유자, 의존성, 다음 명령 또는 사용자 결정 사항을 하나의 인수인계로 남깁니다.

## 6. Git 및 안전 규칙

- **`git merge` 직전마다 `git branch --show-current` 로 주 저장소가 `main` 인지 확인합니다.** 워커를 격리 트리에 붙였다는 사실은 주 저장소가 안전하다는 보장이 아닙니다. 2026-08-23 에 워커가 주 저장소에서 브랜치를 만들어 병합 2건이 그 위에 쌓였습니다.
- **브랜치를 삭제하기 전에 `git log --oneline main..<branch>` 결과를 읽습니다.** 출력만 하고 넘어가면 지우는 순간 알 수 없습니다. `-D` 는 병합 확인 후에만 씁니다.
- Git 병합 Task는 작업 브랜치의 테스트와 `python3 scripts/validate_agent_rules.py --quiet` 통과를 확인한 뒤에만 수행합니다.
- 워커의 완료 보고는 병합 권한이 아닙니다. 병합 Task를 별도로 등록했거나 사용자가 명시적으로 승인한 경우에만 병합합니다.
- 다른 섹션의 미커밋 변경을 덮어쓰거나, 활성 Dispatch가 소유한 파일을 수정하지 않습니다.
- Orca 런타임이나 실험 기능이 준비되지 않았으면, 조율 작업을 시작하지 말고 원인을 보고합니다. 일반 하위 에이전트 실행을 Orca로 조율했다고 표현해서는 안 됩니다.
- 준비 판정은 `orca status --json` 의 `result.runtime.state` 가 `ready` 이고 `reachable` 이 참인 경우입니다.

## 7. 진행 중 런타임이 끊긴 경우

시작 전 차단(6장)과 **진행 중 단절**은 다르게 다룹니다. 장시간 학습이나 색인이
돌는 중에 조율 계층만 끊겼다고 해서 그 작업을 버리지 않습니다.

1. **작업 자체는 계속합니다.** 이미 실행 중인 학습·색인·측정을 중단하지 않습니다.
2. **상태 선언을 멈춥니다.** 런타임이 복구될 때까지 `worker_done`·완료·병합
   가능을 선언하지 않습니다. 5장의 상태 어휘도 쓰지 않습니다.
3. **되돌리기 어려운 작업을 새로 시작하지 않습니다.** 병합, 승격, 데이터 변경,
   공유 자원 점유가 여기 해당합니다. 조율 없이 하면 다른 섹션과 충돌합니다.
4. 복구되면 그동안의 진행을 Task 에 반영한 뒤 정상 절차로 돌아갑니다.
5. 복구되지 않은 채 세션을 끝내야 하면, 실행한 작업·검증 결과·미반영 상태를
   문서로 남기고 사용자에게 Orca 기록이 비어 있다는 사실을 명시합니다.

**"기록이 없다" 와 "작업을 안 했다" 는 다릅니다.** 둘을 구분해 보고하십시오.

---

## 8. 완료한 섹션은 자원을 반납합니다

**회수는 병합의 후속 작업이 아니라 `worker_done` ack 의 일부입니다.**
Task 가 `completed` 가 되었는데 워커 창이 남아 있으면 조율이 끝난 것이
아닙니다. 2026-09-01 에 워커 4대의 `worker_done` 을 처리하고도 하위 세션을
남겨 사용자가 먼저 지적했습니다. 원격 푸시나 `origin/main` 반영을 기다리면
창은 그 사이 계속 점유됩니다.

`python3 scripts/orca_settled_session_audit.py` 가 이 잔류를 검사합니다.
`scripts/orca_taskctl.py dispatch` 는 잔류가 있으면 종료 코드 1 로 거부합니다.
`orca_worker_watch.py` 는 같은 상태를 `[차단:회수 대기]` 로 표시합니다.

### 8.1 반납 순서

| 순서 | 조치 | 명령 | 시점 |
| --- | --- | --- | --- |
| 1 | Dispatch 가 `completed` 인지 확인 | `orca orchestration dispatch-show --task <id> --json` | `worker_done` ack 직후 |
| 2 | 워커 터미널 해제 | `orca orchestration worker-release --dispatch <id>` | 병합 전 |
| 3 | `retained` 로 남은 창만 닫기 | `orca terminal close --terminal <handle>` (`--tab` 금지) | 병합 전 |
| 4 | 로컬 `main` 에 병합된 트리만 제거 | `git worktree remove <path>` | 로컬 병합 후 |
| 5 | 병합 완료 브랜치 삭제 | `git log --oneline main..<branch>` 를 읽은 뒤 `git branch -d` | 로컬 병합 후 |

`git branch -d` 는 병합되지 않은 브랜치를 거부합니다. **`-D` 로 강제하지
마십시오.** 거부당했다는 것은 아직 병합되지 않았다는 뜻이고, 그때는
정리 대상이 아닙니다. 원격 `origin/main` 미반영은 터미널 회수를 미루는
사유가 아닙니다.

### 8.2 정리하면 안 되는 것

| 대상 | 이유 |
| --- | --- |
| 활성 Dispatch 가 소유한 트리 | 그 섹션이 깨집니다 |
| 미병합 브랜치 | 유일본이 사라집니다 |
| 다른 섹션의 미커밋 변경이 있는 트리 | 남의 작업입니다. 소유 섹션이 처리합니다 |

**다른 섹션이 하나라도 돌고 있으면 일괄 정리를 하지 마십시오.** 활성 트리를
잘못 건드리면 복구할 수 없습니다. 전부 끝난 뒤 한 번에 하는 편이 판단이
단순하고 안전합니다.

### 8.3 정리 시점

| 시점 | 범위 |
| --- | --- |
| Task 병합 직후 | 그 Task 의 워커와 트리만 |
| Run 종료 시 | 그 Run 의 완료 Task 전부 |
| 세션 종료 시 | 활성 섹션이 없을 때만 일괄 |

정리한 사실은 `worker_done` 또는 종료 인수인계에 남깁니다. **"정리했다" 와
"정리하지 않았다" 를 구분해 적으십시오.** 적지 않으면 다음 사람이 남은
트리를 활성으로 오해합니다.

### 8.4 `worker-release` 로 닫히지 않는 터미널

`worker-release` 는 **재사용된 터미널을 닫지 않습니다.** 워커가
`reused_agent_terminal` 로 떴으면 호출이 `retained` 로 돌아오고 창은 남습니다.
`worker-show` 의 `effects` 에서 `action` 을 보면 구분됩니다.

이때는 실물을 직접 확인하고 창 단위로 닫습니다.

```bash
orca terminal list                      # 실제로 살아 있는 창만 나옵니다
orca terminal show --terminal <handle>  # preview 로 종결 여부와 tabId 확인
orca terminal close --terminal <handle> # --tab 없이 창 단위로만
```

**`--tab` 을 쓰지 마십시오.** 워커 창이 코디네이터와 같은 탭의 분할 창인
경우가 있고, 그때 `--tab` 은 코디네이터까지 닫아 조율이 끊깁니다. 닫기 전에
`tabId` 가 자기 것과 같은지 반드시 확인하십시오.

닫기 전에 `preview` 로 그 섹션이 실제로 끝났는지 봅니다. 병합 완료 SHA 나
`worker_done` 흔적이 없으면 닫지 마십시오. `worker-list` 의 기록은 이미 사라진
터미널도 `retained` 로 남아 있어 실물 판단 근거가 되지 않습니다.

---

## 9. `worker_done` 이후 워커는 지시를 받지 못합니다

`orca orchestration send` 는 **워커가 `check` 를 실행해야 도착합니다.** 워커가
`worker_done` 을 보내고 턴을 끝내면 그 뒤에 보낸 메시지는 아무도 읽지 않습니다.

겉으로는 정상입니다. Task 는 `completed` 로 보이고 heartbeat 만 없을 뿐이라,
코디네이터가 지시를 보내 놓고 반영되기를 기다리는 동안 그 섹션은 유휴로
남습니다.

**커밋 수로 확인하십시오.** 보고와 실제 상태가 어긋나는 지점입니다.

```bash
git -C <worktree> log --oneline main..HEAD | wc -l
git -C <worktree> status --short
```

`worker_done` 이 왔는데 커밋이 0 이면 병합할 대상이 없다는 뜻입니다. 보고
내용과 무관하게 완료로 처리하지 마십시오.

유휴 워커에 지시를 전달하려면 터미널에 직접 입력합니다.

```bash
orca terminal send --terminal <handle> --text "<지시>" --enter
```

`--enter` 를 빠뜨리면 텍스트가 입력창에 남기만 하고 전달되지 않습니다. 화면에는
보이므로 보낸 것으로 착각하기 쉽습니다. 사람이 하위 창에 직접 입력한 미전송
텍스트도 같은 상태로 남아 있을 수 있으니, 유휴로 보이면 `terminal show` 의
`preview` 를 먼저 확인하십시오.

---

## 10. 격리 트리에는 `.env` 가 없습니다

`.env` 는 Git 미추적이라 새 워크트리에 따라가지 않습니다. 이 저장소는
`Settings()` 가 `SECRET_KEY` 를 필수로 검증하므로, `.env` 가 없으면 애플리케이션
설정을 읽는 코드가 전부 실패합니다. DB 접속도 마찬가지입니다.

워커를 띄운 직후 코디네이터가 배치하십시오. 워커가 스스로 진단하기 어려운
실패입니다.

```bash
cp <주 저장소>/.env <워크트리>/.env
```

값을 문서나 커밋에 남기지 마십시오. `.env` 는 `.gitignore` 대상이라 커밋되지
않지만, 워커에게 커밋 금지를 함께 지시하십시오.
