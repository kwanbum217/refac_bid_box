# Orca 제어 평면 도구 사용 규약 (Control Plane Tools)

> **작성일**: 2026-08-16
> **상태**: 확정 정본
> **버전**: v1.0.0
> **대상**: Orca 코디네이터, 자동화 스크립트 작성자, 워커 에이전트
> **상위 규약**: [`AGENTS.md`](../../AGENTS.md) 4장, [`orca_task_capsule_v2.md`](orca_task_capsule_v2.md)
> **관련 문서**: [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md)

---

## 1. 개요 및 구성

본 문서는 Orca 다중 에이전트 환경에서 코디네이터의 제어 평면 자동화를 담당하는 두 핵심 CLI 도구의 인터페이스 규약과 동작 원칙을 정의합니다.

| 도구 | 스크립트 경로 | 핵심 역할 |
| --- | --- | --- |
| **`orca_taskctl`** | `scripts/orca_taskctl.py` | Task Intent 파싱, Capsule 자동 확장, 워커 기동(Dispatch), 완료 검증(Finalize) 파이프라인 |
| **`orca_model_router`** | `scripts/orca_model_router.py` | 작업 위험도 분류(Risk Classification), 최적 모델 풀 선택, 모델 가용성 Probe |

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
| **`dispatch`** | `--intent <path>`<br>`--repo <path>`<br>`--model <id>`<br>`--task-id <id>`<br>`--run-id <id>`<br>`--capsule-dir <dir>`<br>`--agent <id>`<br>`--terminal <handle>`<br>`--no-probe`<br>`--dry-run`<br>`--json` | `--intent` (필수) | Intent를 Capsule로 확장한 후 `orca orchestration worker-start`로 워커를 기동합니다. |
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

---

## 4. `orca_model_router` 도구 규약

`scripts/orca_model_router.py`는 위험도 판정, 모델 풀 매핑, 가용성 검증을 수행합니다.

### 4.1 서브커맨드 목록

| 서브커맨드 | 주요 인자 | 설명 |
| --- | --- | --- |
| **`classify`** | `--capsule <path>` 또는 `--objective <txt>` + `--why-now <txt>`<br>`--role <role>`<br>`--json` | 텍스트/Capsule을 분석해 위험도 등급(`high`, `medium`, `low`)과 권장 모델을 분류합니다. |
| **`probe`** | `--model <id>` (필수)<br>`--timeout <sec>`<br>`--json` | 대상 모델의 실제 호출 가용성을 테스트합니다. |
| **`route`** | `--capsule <path>` 또는 `--objective <txt>`<br>`--risk <level>`<br>`--role <role>`<br>`--model <id>`<br>`--no-probe`<br>`--json` | 위험도 분류와 probe 검증을 통합 수행하여 최종 모델 및 fallback 모델을 결정합니다. |
| **`list`** | 없음 | 등록된 모델 풀, 티어, 자동 선택 대상 여부를 출력합니다. |

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
| `gemini-flash-high` | `gemini-3.7-flash-high` | gemini | primary | **대상 (True)** | builder, reviewer, investigator, benchmarker, documenter | 주력 워커. 분석·감사·구현 |
| `gemini-flash-medium` | `gemini-3.7-flash-medium` | gemini | primary | **대상 (True)** | investigator, documenter | 읽기 전용 조사 및 문서화 |
| `claude-sonnet` | `claude-sonnet-4-6` | claude | secondary | **대상 (True)** | reviewer, builder | 고품질 판정 필요 작업 |
| `claude-opus` | `claude-opus-5` | claude | coordinator | **비대상 (False)** | (워커 사용 불가) | **코디네이터 전용. 워커 지정 시 거부(오류)** |
| `codex` | `codex` | opencode | secondary | **비대상 (False)** | investigator, documenter | 주간 잔량이 넉넉할 때만 수동 지정 |
| `opencode-free` | `opencode-free` | opencode | free | **비대상 (False)** | investigator | 실패해도 무방한 병렬 조사. 임계 경로 금지 |

### 4.4 모델 가용성 Probe 판정 기준

`probe_model`은 프로바이더별 실제 CLI 명령을 실행하여 가용성을 판정합니다:
- **`gemini` / `claude`**: `agy --model {model} --print ping --print-timeout 15s`
- **`opencode`**: `opencode run --model {model} ping`

**가용 판정 조건**:
1. 하위 프로세스 종료 코드가 `0`이어야 합니다.
2. **실제 응답 본문(`stdout.strip()`)이 비어 있지 않아야 합니다** (응답 없는 거짓 양성 차단).
3. `stderr`에 치명적인 디렉터리 오류(`Error:`, `Failed to`)가 없어야 합니다 (단순 경고나 버전 안내는 허용).

비정상 종료 시 원인을 분류하여 상세 내용(`detail`)에 기록합니다:
- 할당량 초과: `quota`, `resource_exhausted`, `429`
- 인증 실패: `unauthorized`, `forbidden`, `auth`, `api_key`, `401`, `403`
- 명령어/모델 없음: `not found`, `no such file`
- 타임아웃: 지정된 제한 시간 초과
