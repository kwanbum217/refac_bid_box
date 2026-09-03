# Orca 제어 평면 도구 사용 규약 (Control Plane Tools)

> **작성일**: 2026-08-16
> **상태**: 확정 정본
> **버전**: v1.0.0
> **대상**: Orca 코디네이터, 자동화 스크립트 작성자, 워커 에이전트
> **상위 규약**: [`AGENTS.md`](../../AGENTS.md) 4장, [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)
> **관련 문서**: [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md)

---

## 1. 개요 및 구성

본 문서는 Orca 다중 에이전트 환경에서 코디네이터의 제어 평면 자동화를 담당하는 핵심 CLI 도구들의 인터페이스 규약과 동작 원칙을 정의합니다.

| 도구 | 스크립트 경로 | 핵심 역할 |
| --- | --- | --- |
| **`orca_taskctl`** | `scripts/orca_taskctl.py` | Task Intent 파싱, Capsule 자동 확장, 워커 기동(Dispatch), 완료 검증(Finalize) 파이프라인 |
| **`orca_model_router`** | `scripts/orca_model_router.py` | 작업 위험도 분류, 모델 풀 선택·Probe, 역할별 rolling reliability 기록 |
| **`orca_skill_receipt`** | `scripts/orca_skill_receipt.py` | Orca 정본 스킬(`orca skills get orchestration`) 영수증 발급 및 2층 fail-closed 게이트 검증 |

---

## 2. Task Intent 스키마 (`ORCA_TASK_INTENT_V1`)

코디네이터가 수작업으로 전체 Capsule을 작성하는 대신, 5~10줄의 컴팩트한 YAML로 의도를 선언하면 `orca_taskctl`이 이를 정형화된 `ORCA_TASK_CAPSULE_V2`로 확장합니다.

### 2.1 필드 정의

| 필드 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `schema` | string | 필수 | `ORCA_TASK_INTENT_V1` | 스키마 식별자 |
| `role` | string | 선택 | `builder` | 워커 역할 (`builder`, `reviewer`, `investigator`, `benchmarker`, `documenter`) |
| `objective` | string | 선택 | `""` | 작업의 최종 완료 상태 요약 |
| `scope` | list[string] | 선택 | `[]` | 수정 대상 파일/디렉터리 목록 (`allowed_write_files`의 근거) |
| `acceptance` | list[string] | 선택 | `[]` | 기계적 완료 검증 단정 목록 |
| `risk` | string | 선택 | `medium` | 작업 위험도 등급 (`low`, `medium`, `high`) |
| `context` | string | 선택 | `""` | 작업 배경 및 선후행 맥락 (`why_now` 생성에 사용) |
| `task_id` | string | 선택 | 자동생성 | 고유 Task ID (미지정 시 `task_<uuid>` 또는 파일명 기반) |
| `mode` | string | 선택 | `worker` | 실행 모드 (`worker`, `reviewer`, `investigator`, `benchmarker`) |
| `report_path` | string | 선택 | 자동생성 | 결과 보고 JSON 경로 (`.orca/capsules/{task_id}/worker_done.json` 등) |
| `review_checklist` | list[object] | 조건부 | `[]` | **`role: reviewer`인 경우 1개 이상 필수**. `{id, question, defect_when, how}` 구조 |

> [!IMPORTANT]
> `role: reviewer`로 지정된 Intent에 `review_checklist`가 없거나 비어 있으면 `expand` 및 `dispatch` 단계에서 종료 코드 2로 즉시 거부됩니다.

---

## 3. `orca_taskctl` 도구 규약

`scripts/orca_taskctl.py`는 4개의 서브커맨드를 제공합니다.

### 3.1 서브커맨드 목록 및 인자

| 서브커맨드 | 주요 인자 | 필수 여부 | 설명 |
| --- | --- | --- | --- |
| **`expand`** | `--intent <path>`<br>`--out <path>`<br>`--task-id <id>`<br>`--run-id <id>`<br>`--json` | `--intent` (필수)<br>`--out` (필수) | Task Intent YAML을 읽어 유효한 `ORCA_TASK_CAPSULE_V2` 파일로 확장합니다. |
| **`create`** | `--intent <path>`<br>`--run-id <id>`<br>`--task-id <id>`<br>`--capsule-dir <dir>`<br>`--task-title <text>`<br>`--display-name <text>`<br>`--deps <json>`<br>`--skip-skill-receipt`<br>`--json` | `--intent` (필수) | Intent를 Capsule로 확장하고 **Capsule 절대 경로를 담은 spec** 으로 Orca Task를 만듭니다. 정본 영수증 게이트를 기본 검증합니다. Dispatch 전에 이 명령을 씁니다. |
| **`dispatch`** | `--intent <path>`<br>`--repo <path>`<br>`--model <id>`<br>`--effort <level>`<br>`--task-id <id>`<br>`--run-id <id>`<br>`--capsule-dir <dir>`<br>`--agent <id>`<br>`--terminal <handle>`<br>`--worktree <sel>`<br>`--worktree-name <name>`<br>`--no-probe`<br>`--no-capsule-notice`<br>`--skip-skill-receipt`<br>`--dry-run`<br>`--json` | `--intent` (필수)<br>`--agent` 또는 `--terminal` 중 하나 | Intent를 Capsule로 확장한 뒤 워커를 기동하고 **Capsule 정본 경로 고지문을 자동 투입**합니다. `--effort`는 worker-start 경로에 전달되며 `--model`과 함께 지정해야 합니다 (모델 없는 effort 단독 지정 시 fail-closed 거부). 정본 영수증 게이트를 기본 검증합니다. |
| **`finalize`** | `--report <path>`<br>`--capsule <path>`<br>`--repo <path>`<br>`--worktree <path>`<br>`--base <ref>`<br>`--branch <ref>`<br>`--reviewer`<br>`--reviewer-model <id>`<br>`--json` | `--report` (필수)<br>`--capsule` (필수) | `worker_done` 보고 요약 -> Level 1 게이트 -> Level 2 리뷰어 검증을 일괄 실행하고 최종 판정합니다. |
| **`status`** | `--run-id <id>`<br>`--task-id <id>`<br>`--json` | 선택 | `orca orchestration task-list`를 호출하여 현재 Run/Task 상태를 조회합니다. |

### 3.2 Capsule 자동 확장 (`expand`) 규칙

`expand`는 규약 준수에 필요한 다음 필드들을 결정론적으로 채웁니다:

1. **반환 계약 및 보고 경로**: 일반 워커는 `ORCA_WORKER_DONE_V2` / `worker_done.json`, 리뷰어는 `ORCA_REVIEW_DONE_V2` / `review_done.json` 자동 설정.
2. **읽기/쓰기 범위 격리**: `allowed_write_files`는 `scope` 항목으로 구성되며, `allowed_read_files`는 Capsule 자기 경로 + `docs/context/CURRENT_STATE.md` + `allowed_write_files`를 합친 **진상위집합(superset)**으로 자동 구성됩니다.
3. **검색 범위 변환**: `scope`의 경로 패턴을 `search_scope.allowed_globs` 포맷으로 자동 변환합니다.
4. **예산 검증**: `char_len` 기준으로 Capsule 크기를 검사하여 일반 위험도는 8,000자, high 위험도는 12,000자 초과 시 경고를 출력합니다.

### 3.3 검증 및 판정 (`finalize`) 종료 코드 산출 규칙

`finalize`는 검증 파이프라인의 각 단계 결과를 취합하여 표준 종료 코드를 반환합니다.

| 단계 | 실행 도구 | 검증 내용 |
| --- | --- | --- |
| **1단계: 보고 요약** | `scripts/summarize_worker_done.py` | 보고서 JSON 파싱, 기본 계약 위반 검사, 다이제스트 생성 |
| **2단계: Level 1 게이트** | `scripts/orca_level1_gate.py` | Git diff 크기, 허용 파일 초과(scope excess), ruff, pytest 무결성 검증 |
| **3단계: Level 2 리뷰어** | `scripts/orca_run_reviewer.py` | `--reviewer` 플래그 지정 시 실행. 체크리스트 기반 독립 판정 |

**종료 코드 결정 규칙**:
- **`0` (통과)**: 모든 도구가 정상 실행되고, 계약 위반이나 게이트 실패가 0건인 경우.
- **`1` (검증 실패)**: 도구는 정상 실행되었으나 계약 위반, 게이트 반려, 리뷰어 defect가 확인된 경우.
- **`2` (도구/파싱 오류)**: 대상 파일 누락, JSON 파싱 실패, 하위 검증 도구 자체 비정상 종료 시.

### 3.4 Capsule 경로 전달 (2026-08-17 신설)

**`orca orchestration dispatch --inject` 는 Orca Task 의 `spec` 만 워커에게 전달합니다.** Capsule 경로도 내용도 들어가지 않습니다. 2026-08-17 첫 실사용에서 워커 3대 전부가 Capsule 을 읽지 못한 채 요약만 보고 작업해 파일명과 보고 계약을 위반했습니다. 근거: [`orca_do_not_repeat.md`](orca_do_not_repeat.md) 4.7

경로는 **두 층으로** 전달합니다.

| 층 | 수단 | 시점 |
| --- | --- | --- |
| 1차 (구조적) | `create` 가 Capsule 절대 경로를 Task `spec` 에 넣습니다 | Task 생성 시. `--inject` 프리앰블에 함께 실립니다 |
| 2차 (보강) | `dispatch` 가 기동 직후 `terminal send` 로 고지문을 투입합니다 | 부착 성공 직후 |

권장 순서입니다.

```bash
python3 scripts/orca_taskctl.py create --intent <intent> --run-id <run> \
  --capsule-dir /Users/kwanbum/orca/capsules/<run> --task-title "<제목>" --json

python3 scripts/orca_taskctl.py dispatch --intent <intent> --run-id <run> \
  --task-id <create 가 돌려준 id> --capsule <create 가 돌려준 capsule 경로> \
  --terminal <handle> --json
```

**`--capsule` 을 반드시 넘기십시오.** Orca 는 Task ID 를 스스로 발급하므로 `create` 가 쓴 Capsule 디렉터리 이름과 실제 Task ID 가 다릅니다. `--capsule` 없이 Dispatch 하면 `dispatch` 가 Task ID 기준으로 Capsule 을 새로 만들어 **같은 Task 에 Capsule 이 두 벌 생기고 Task `spec` 이 가리키는 쪽과 어긋납니다.** `--capsule` 을 주면 재확장하지 않고 그 파일을 그대로 쓰며, 파일이 없으면 기동하지 않고 종료 코드 2 로 거부합니다.

고지문에는 Capsule 절대 경로, `allowed_write_files` 준수, 허용 목록 밖 파일명 생성 금지, `commit_count: 0` 이면 `escalation`, 보고 경로, **그리고 `dispatch-show` 로 조회한 유효 `dispatchId`** 가 들어갑니다. 마지막 항목이 재 Dispatch 후 `capability is revoked` 거부를 막습니다.

Capsule 경로는 항상 `resolve()` 로 절대화됩니다. 워커는 다른 워크트리에서 돌기 때문에 상대 경로로는 파일을 찾지 못합니다.

전송이 실패하면 `capsule_notice.status` 가 `failed` 가 되고 **종료 코드 3** 을 돌려줍니다. **조용히 넘어가지 않습니다.** `--no-capsule-notice` 는 습관적으로 쓰지 않습니다.

**`dispatch` 및 `create` 종료 코드**입니다. 3 은 "워커는 떴지만 정본 지시가 도달했는지 확인하지 못했다" 는 뜻이며, 4 는 "정본 스킬 영수증이 없거나 만료되어 조율 작업을 시작할 수 없다"는 뜻입니다.

| 코드 | 의미 |
| :---: | --- |
| 0 | 기동 성공 + 지시 도달 확인 |
| 1 | 워커 기동 실패, 또는 동시 쓰기 워커 상한 초과로 거부 |
| 2 | 인자·파일·계약 오류 (Capsule 없음, `review_checklist` 누락 등) |
| 3 | 기동은 성공했으나 지시 도달 미확인 (신뢰 대화창 판정 불가, 터미널 미정착, 고지 전송 실패) |
| 4 | 정본 스킬(`orca skills get orchestration`) 영수증 부재·불일치·만료로 거부 |

3 을 받으면 워커 터미널을 직접 확인한 뒤 진행합니다. 확인 없이 넘어가려면 `--allow-unverified-delivery` 를 명시해야 합니다. 4 를 받으면 `python3 scripts/orca_skill_receipt.py issue` 로 영수증을 갱신하거나 의도적 우회 시 `--skip-skill-receipt` 를 지정합니다.

### 3.5 Grok 워커 기동 및 터미널 부착 절차

Grok 워커는 `orca terminal create --worktree path:<워크트리> --command grok` 으로 TUI 대화형 세션을 먼저 띄운 뒤, `orca_taskctl dispatch --terminal <handle>` 로 붙입니다.

```bash
# 1. Grok TUI 터미널 생성 (대화형 TUI 기동)
orca terminal create --worktree path:<워크트리> --title "<섹션명>" --command grok

# 2. (선택) 워커 터미널 사전 준비
python3 scripts/orca_taskctl.py prepare-worker --terminal <handle> --cli-type grok

# 3. Task 생성 및 터미널 부착 Dispatch
python3 scripts/orca_taskctl.py create --intent <intent> --run-id <run> --capsule-dir .orca/capsules --json
python3 scripts/orca_taskctl.py dispatch --intent <intent> --terminal <handle> --capsule <capsule_path> --model grok-4.6 --json
```

`orca_taskctl` 은 `prepare-worker --cli-type grok` 및 `dispatch --terminal` 시 메타데이터, `--model` 또는 `orca terminal show` 명령을 통해 CLI 종류를 `grok` 으로 자동 식별하여 파일 편집 모드 전환 오동작 없이 안전하게 작업을 투입합니다.

---

## 4. `orca_model_router` 도구 규약

`scripts/orca_model_router.py`는 위험도 판정, 모델 풀 매핑, 가용성 검증과 실행 신뢰도 기록을 수행합니다.

### 4.1 서브커맨드 목록

| 서브커맨드 | 주요 인자 | 설명 |
| --- | --- | --- |
| **`classify`** | `--capsule <path>` 또는 `--objective <txt>` + `--why-now <txt>`<br>`--role <role>`<br>`--json` | 텍스트/Capsule을 분석해 위험도 등급(`high`, `medium`, `low`)과 권장 모델을 분류합니다. |
| **`probe`** | `--model <id>` (필수)<br>`--timeout <sec>`<br>`--json` | 대상 모델의 실제 호출 가용성을 테스트합니다. |
| **`route`** | `--capsule <path>` 또는 `--objective <txt>`<br>`--risk <level>`<br>`--role <role>`<br>`--model <id>`<br>`--no-probe`<br>`--json` | 위험도 분류와 probe 검증을 통합 수행하여 최종 모델 및 fallback 모델을 결정합니다. |
| **`list`** | 없음 | 등록된 모델 풀, 티어, 자동 선택 대상 여부를 출력합니다. |
| **`reliability-record`** | `--pool <name>`<br>`--role <role>`<br>`--status <succeeded\|failed>`<br>`--failure <kind>`<br>`--elapsed-sec <sec>`<br>`--observation-id <id>`<br>`--state <path>`<br>`--json` | 무료 풀 실행 결과를 역할별 최근 이력에 기록합니다. |

### 4.2 위험도 분류 (`classify_risk`) 규칙

- **대소문자 무관 (`re.IGNORECASE`)**: `DROP`, `drop`, `DB`, `db` 등 모든 케이스를 원문에서 검사합니다.
- **우선순위**: high 키워드가 1개라도 있으면 `high` -> medium 키워드가 있으면 `medium` -> 미매칭 시 `low`.
- **판정 근거 기록**: 매칭된 키워드 목록(`reasons`)을 함께 반환하여 판정 투명성을 제공합니다.

| 위험도 등급 | 대표 키워드 (정규식 단어 경계 매칭) |
| --- | --- |
| **`high`** | `merge`, `병합`, `deploy`, `배포`, `DB`, `database`, `schema`, `스키마`, `migration`, `마이그레이션`, `DROP`, `DELETE`, `promotion`, `승격`, `cutover`, `컷오버`, `production`, `운영`, `retrain`, `재학습`, `security`, `보안`, `secret`, `시크릿` |
| **`medium`** | `refactor`, `리팩토링`, `optimize`, `최적화`, `performance`, `성능`, `model`, `모델`, `API`, `endpoint`, `엔드포인트`, `config`, `설정`, `cache`, `캐시` |
| **`low`** | `doc`, `문서`, `test`, `테스트`, `lint`, `format`, `포맷`, `typo`, `comment`, `주석`, `rename`, `chore` |

### 4.3 모델 풀 정책 (`MODEL_POOL`)

| 풀 이름 | 모델 ID | 프로바이더 | 티어 | 자동 선택 (`auto_selectable`) | 적합 역할 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| `gemini-flash-high` | `gemini-3.8-flash-high` | gemini | primary | **대상 (True)** | builder, reviewer, investigator, benchmarker, documenter | 주력 워커. 분석·감사·구현 |
| `gemini-flash-medium` | `gemini-3.8-flash-medium` | gemini | primary | **대상 (True)** | builder, reviewer, investigator, benchmarker, documenter | medium 이하 주력 워커 |
| `gemini-flash-low` | `gemini-3.8-flash-low` | gemini | primary | **대상 (True)** | investigator, benchmarker, documenter | 지연 우선 조사·계측·문서화 |
| `gemini-3.7-flash-high` | `gemini-3.7-flash-high` | gemini | secondary | **비대상 (False)** | builder, reviewer, investigator, benchmarker, documenter | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `gemini-3.7-flash-medium` | `gemini-3.7-flash-medium` | gemini | secondary | **비대상 (False)** | builder, reviewer, investigator, benchmarker, documenter | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `gemini-3.7-flash-low` | `gemini-3.7-flash-low` | gemini | secondary | **비대상 (False)** | investigator, benchmarker, documenter | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `claude-sonnet` | `claude-sonnet-5` | claude | secondary | **대상 (True)** | reviewer, builder | 로컬 Claude Pro 전용 풀 (/opt/homebrew/bin/claude). contextWindow 1M, effort medium. WORKER_MODEL_NOTICE 후 명시 배정하는 수동 보조 워커. probe 전송은 claude-cli 경로 분리 |
| `grok-4.6` | `grok-4.6` | grok | secondary | **비대상 (False)** | reviewer, builder, investigator | SuperGrok 로컬 Grok CLI (/opt/homebrew/bin/grok). effort high 는 코디네이터 등급으로 워커 자동 배정 제외, 워커 등급은 medium/low. WORKER_MODEL_NOTICE 후 명시 배정 |
| `grok-4.5` | `grok-4.5` | grok | secondary | **비대상 (False)** | reviewer, builder, investigator | SuperGrok 로컬 Grok CLI (/opt/homebrew/bin/grok). grok-4.5 워커 모델. WORKER_MODEL_NOTICE 후 명시 배정 |
| `claude-opus` | `claude-opus-5` | claude | coordinator_reserve | **비대상 (False)** | (워커 사용 불가) | 예비 코디네이터. 워커 지정 시 거부 |
| `codex` | `gpt-5.6-terra` | codex | coordinator | **비대상 (False)** | (워커 사용 불가) | **기본 코디네이터 (medium). 기본값 변경 전 `MODEL_CHANGE_NOTICE`, Sol High는 사용자 승인 후 고위험 최종 판정에만 수동 사용하며 워커 지정 시 거부(오류)** |
| `opencode-free` | `opencode/nemotron-3.5-lightning-free` | opencode | free | **비대상 (False)** | (격리) | 장문 지시 붕괴 실측으로 재시험 전 배정 중단 |
| `cerebras-oss` | `cerebras/gpt-oss-120b` | cerebras | free | **비대상 (False)** | investigator | 컨텍스트 65,536 / 출력 8,192. Capsule 범위 작업 전용 |

> **모델 ID 는 반드시 실측으로 확인한 값만 적습니다.** 2026-08-16 까지 `opencode-free` 의 ID 가
> 자리표시자 `opencode-free` 였고 실제 호출 시 `Model not found` 였습니다. `opencode` 는
> `provider/model` 형식을 요구하며 실재 모델 목록은 `opencode models` 로 확인합니다.
> `codex` 의 프로바이더도 `opencode` 로 잘못돼 있었습니다. 자리표시자 ID 는 probe 가
> 항상 실패하므로 그 풀을 조용히 사용 불가로 만듭니다.

### 4.3.1 저가·무료 풀 조건부 개방 (`--allow-free`)

무료 풀은 기본적으로 자동 선택 대상이 아닙니다(`auto_selectable: False`). 다음 **세 조건을
모두** 만족할 때만 `--allow-free` 로 주 모델이 될 수 있습니다.

| 조건 | 값 | 근거 |
| --- | --- | --- |
| 역할 | `builder`, `investigator` | 실측한 두 역할만 개방. `reviewer` 는 임계 경로 |
| 위험도 | `low` | `medium` 이상은 재작업 비용이 개방 이득을 넘음 |
| 쓰기 범위 | 허용하되 병합 전 검증 경고 | Level 1·테스트·코디네이터 검토를 생략할 수 없음 |

조건 판정은 `free_pool_eligibility()` 가 담당하고, Capsule 을 읽을 수 없으면 fail-closed 로
쓰기 있음으로 봅니다. 무료 풀이 실제로 선택되면 두 경고가 반드시 발행됩니다.

1. 산출물 재검증 필수 및 임계 경로 금지
2. 컨텍스트 한도 경고. `max_tokens` 가 200,000 미만이면 그 수치를, 미확인이면 미확인 사실을 알립니다

`codex` 는 코디네이터 풀이므로 `FREE_POOL_ORDER` 에 넣지 않습니다.

### 4.3.2 역할별 rolling reliability

`data/model_reliability_history.json`은 Git 미추적 운영 상태입니다. 풀·역할별 최근
10회 결과를 보며, 3회 미만은 순위를 바꾸지 않습니다. 최근 성공률이 50% 미만이면
강등하고 3회 연속 실패하면 해당 역할 후보에서 제외합니다. builder 결과는
investigator 순서에 영향을 주지 않습니다.

`orca_taskctl dispatch`가 무료 풀의 모델·역할·시작 시각을 Capsule 옆
`routing.json`에 기록하고, `finalize`가 검증 종료 코드 0·1을 성공·실패로 한 번만
반영합니다. 도구 오류인 종료 코드 2는 모델 결과로 단정하지 않습니다. 벤치마크
러너는 종료 코드·커밋 유무·시한 초과를 직접 기록합니다. 실행 식별자로 중복
Finalize나 재수집도 한 번만 반영합니다.

### 4.4 모델 가용성 Probe 판정 기준

`probe_model`은 프로바이더별 실제 CLI 명령을 실행하여 가용성을 판정합니다:
- **`gemini` / `claude`**: `agy --model {model} --print ping --print-timeout 15s`
- **`opencode` / `cerebras`**: `opencode run --model {model} ping`
- **`codex`**: `codex exec ping`

`stdin` 은 `subprocess.DEVNULL` 로 닫습니다. `codex` 는 stdin 이 열려 있으면 추가 입력을
기다려 타임아웃을 소진할 수 있습니다.

`cerebras` 프로바이더는 `opencode.json` 이 `{env:CEREBRAS_API_KEY}` 로 **프로세스
환경변수**를 읽습니다. 저장소 `.env` 는 셸로 export 되지 않으므로 probe 가 `.env` 에서
키를 읽어 subprocess `env` 로만 전달합니다. **키 값은 로그·예외·경고·문서 어디에도
출력하지 않으며**, 없을 때는 값 대신 `CEREBRAS_API_KEY 미설정` 사실만 알립니다.

**가용 판정 조건**:
1. 하위 프로세스 종료 코드가 `0`이어야 합니다.
2. **실제 응답 본문(`stdout.strip()`)이 비어 있지 않아야 합니다** (응답 없는 거짓 양성 차단).
3. `stderr`에 치명적인 디렉터리 오류(`Error:`, `Failed to`)가 없어야 합니다 (단순 경고나 버전 안내는 허용).

비정상 종료 시 원인을 분류하여 상세 내용(`detail`)에 기록합니다:
- 할당량 초과: `quota`, `resource_exhausted`, `429`
- 인증 실패: `unauthorized`, `forbidden`, `auth`, `api_key`, `401`, `403`
- 명령어/모델 없음: `not found`, `no such file`
- 타임아웃: 지정된 제한 시간 초과

---

## 5. `orca_skill_receipt` 도구 및 정본 영수증 게이트

`scripts/orca_skill_receipt.py`는 코디네이터가 Orca 정본 스킬(`orca skills get orchestration`)을 확인하지 않고 워커를 띄우는 것을 기계적으로 방지하는 **2층 방어 체계**의 핵심 도구입니다.

### 5.1 2층 방어 체계 아키텍처

| 계층 | 구성 요소 | 동작 방식 | 실패 시 영향 |
| --- | --- | --- | --- |
| **1층 (자동 주입)** | `.claude/settings.json` `SessionStart` 훅 | 세션 시작 시 `python3 scripts/orca_skill_receipt.py issue \|\| true` 자동 실행 | 실패해도 세션 시작을 차단하지 않음 (fail-open) |
| **2층 (엄격 게이트)** | `scripts/orca_taskctl.py` `create` / `dispatch` | 정본 영수증의 실시간 유효성(`sha256`, `appVersion`, 세션 핸들) 대조 | 영수증 부재 또는 불일치 시 종료 코드 `4`로 즉시 거부 (fail-closed) |

### 5.2 영수증 데이터 스키마 (`ORCA_SKILL_RECEIPT_V1`)

영수증 파일은 `.orca/skill_receipt.json` 에 Git 미추적으로 저장됩니다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `schema` | string | `ORCA_SKILL_RECEIPT_V1` |
| `skill_name` | string | 대상 스킬 식별자 (`orchestration`) |
| `canonical_command` | string | 정본 조회 명령 (`orca skills get orchestration`) |
| `sha256` | string | 발급 시점의 정본 스킬 본문 SHA-256 다이제스트 |
| `app_version` | string | 발급 시점의 Orca 런타임 버전 (`result.runtime.appVersion`) |
| `coordinator_handle` | string \| null | 발급한 코디네이터 터미널 핸들 |
| `issued_at` | number | 발급 시각 Unix 타임스탬프 |
| `issued_at_iso` | string | 발급 시각 ISO 8601 문자열 |

### 5.3 실시간 검증 (`verify`) 및 거부 기준

게이트 검증(`verify_skill_receipt`)은 단순히 영수증 파일 존재 여부만 보지 않고, **그 자리에서 정본과 런타임 상태를 실시간 재조회**하여 대조합니다:

1. **파일 존재 및 스키마 검증**: 영수증 파일이 없거나 JSON 파싱에 실패하면 즉시 거부.
2. **런타임 버전 대조**: 실시간 `orca status --json` 의 `appVersion` 과 영수증의 `app_version` 이 다르면 거부 (Orca 업데이트 후 낡은 스킬 지침 방지).
3. **정본 내용 SHA-256 대조**: 실시간 `orca skills get orchestration` 의 해시와 영수증의 `sha256` 이 다르면 거부 (정본 문서 갱신 후 낡은 지침 재사용 방지).
4. **코디네이터 세션 대조**: 영수증의 `coordinator_handle` 과 현재 세션 핸들이 상이하면 타 세션 영수증 재사용으로 간주하여 거부. (핸들 조회가 불가한 환경에서는 해당 항목만 건너뛰고 나머지 검사 유지).

### 5.4 CLI 서브커맨드 및 해소 명령

- **발급 (단일 명령)**:
  ```bash
  python3 scripts/orca_skill_receipt.py issue
  ```
- **검증**:
  ```bash
  python3 scripts/orca_skill_receipt.py verify
  ```
- **단일 우회 플래그 (`--skip-skill-receipt`)**:
  게이트를 의도적으로 우회해야 하는 긴급 상황에서는 `create` 및 `dispatch` 서브커맨드에 `--skip-skill-receipt` 를 지정합니다. 사용 시 stderr 에 경고가 출력되고 Dispatch 기록에 보존됩니다. 환경변수를 통한 추가 우회는 엄격히 금지됩니다.
