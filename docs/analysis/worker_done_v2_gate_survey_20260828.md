# ORCA_WORKER_DONE_V2 계약 게이트 여부 조사 보고서

> **작성일**: 2026-08-28
> **대상 Task**: task_28394bf3d41f
> **조사 범위**: 저장소 내 검증 스크립트 및 조정 로직 코드
> **방법**: 코드 정적 분석 (실행 없음)

---

## 1장. ORCA_WORKER_DONE_V2 필수 필드 전체

### 1.1 `scripts/summarize_worker_done.py` 의 `REQUIRED_FIELDS` (58-71행)

| 순번 | 필드명 | 비고 |
| --- | --- | --- |
| 1 | schema | "ORCA_WORKER_DONE_V2" 고정값 검증 (223-224행) |
| 2 | version | 빈 문자열 금지 (227-228행) |
| 3 | task_id | Capsule 과 일치해야 함 |
| 4 | status | `succeeded` 또는 `escalation`만 허용 (99-102행) |
| 5 | branch | 작업 브랜치명 |
| 6 | commit | 마지막 커밋 SHA (빈 문자열 허용) |
| 7 | commit_count | 정수, 음수 금지, 0이면 규약 3.3 검사 대상 (90-96행, 247-250행) |
| 8 | changed_files | 문자열 배열 (114-119행) |
| 9 | read_files | 문자열 배열 (114-119행) |
| 10 | verification | 객체 배열, 각 원소는 `command`, `result` 키 보유 (124-128행) |
| 11 | verdict | `pass`, `candidate`, `blocked`만 허용 (105-108행) |
| 12 | blocking_issues | 문자열 또는 객체 배열 (114-119행, 266-277행) |

### 1.2 `.agents/templates/worker_done_v2.json` 의 필드 구성

| 순번 | 필드명 | REQUIRED_FIELDS 포함 여부 |
| --- | --- | --- |
| 1 | schema | ✅ |
| 2 | version | ✅ |
| 3 | task_id | ✅ |
| 4 | dispatch_id | ❌ (템플릿만 존재) |
| 5 | status | ✅ |
| 6 | branch | ✅ |
| 7 | commit | ✅ |
| 8 | commit_count | ✅ |
| 9 | changed_files | ✅ |
| 10 | read_files | ✅ |
| 11 | verification | ✅ |
| 12 | metrics | ❌ (템플릿만 존재) |
| 13 | verdict | ✅ |
| 14 | blocking_issues | ✅ |
| 15 | remaining_risks | ❌ (템플릿만 존재) |
| 16 | artifacts | ❌ (템플릿만 존재) |
| 17 | reproduce | ❌ (템플릿만 존재) |

### 1.3 어긋난 항목 명시

| 구분 | 필드 | 설명 |
| --- | --- | --- |
| 템플릿에만 있고 REQUIRED_FIELDS에 없는 필드 | dispatch_id, metrics, remaining_risks, artifacts, reproduce | 워커가 템플릿을 보고 이 필드들을 채우면 검증기(`summarize_worker_done.py`)는 필수 필드 누락으로 **잡아내지 않음**. 단, 계약 비대(필드 길이 초과) 검사 대상이 될 수 있음 (282-286행). |
| REQUIRED_FIELDS에 있고 템플릿에 없는 필드 | 없음 | 모든 필수 필드는 템플릿에 포함됨. |

**결론**: 템플릿이 검증기보다 관대함. 워커가 템플릿을 충실히 따르면 검증 통과 가능성 높음.

---

## 2장. 현재 검증이 실제로 잡아내는 위반 유형

### 2.1 `scripts/summarize_worker_done.py` (종료 코드: 0=준수, 1=위반, 2=파싱/도구 오류)

| 위반 유형 | 검출 위치 (파일:행) | 종료 코드 | 비고 |
| --- | --- | --- | --- |
| 필수 필드 누락 | summarize_worker_done.py:218-220 | 1 | REQUIRED_FIELDS 12개 전부 검사 |
| schema 값 불일치 | summarize_worker_done.py:223-224 | 1 | "ORCA_WORKER_DONE_V2" 강제 |
| version 빈 값 | summarize_worker_done.py:227-228 | 1 | 공백만 있는 경우도 잡음 |
| commit_count 타입 위반 (bool/문자열/음수) | summarize_worker_done.py:90-96 | 1 | `check_field_types()` 내부 |
| status 허용값 외 값 | summarize_worker_done.py:99-102 | 1 | `succeeded`, `escalation`만 허용 |
| verdict 허용값 외 값 | summarize_worker_done.py:105-108 | 1 | `pass`, `candidate`, `blocked`만 허용 |
| changed_files/read_files/blocking_issues 비배열 | summarize_worker_done.py:114-119 | 1 | 배열 타입 강제, 원소도 문자열 강제 |
| verification 비배열 또는 원소 비객체 | summarize_worker_done.py:124-128 | 1 | 객체 배열 강제 |
| 규약 3.3 위반: succeeded + commit_count=0 (쓰기 Task) | summarize_worker_done.py:247-250 | 1 | 읽기 전용 Task(allowed_write_files 빈 목록) 예외 |
| allowed_write_files 범위 초과 | summarize_worker_done.py:260-262 | 1 | `write_scope_excess()` 사용, Capsule 대조 |
| verdict 격하: blocking_issues 존재인데 pass/candidate 선언 | summarize_worker_done.py:273-277 | 1 | 실효 verdict를 `blocked`로 정정 |
| 계약 비대: 단일 필드 길이 초과 | summarize_worker_done.py:282-286 | 1 | 기본 600자, `--field-max-chars`로 조정 가능 |

### 2.2 `scripts/orca_level1_gate.py` (종료 코드: 0=통과, 1=게이트 실패, 2=도구 오류)

| 게이트 | 검증 내용 | 실패 시 종료 코드 | 주요 검출 위치 |
| --- | --- | --- | --- |
| 게이트 1: 변경 파일 | `git diff --name-status -z` 로 변경/신규/rename 파일 확인 | 1 (도구 오류만 2) | orca_level1_gate.py:129-176, 268-296 |
| 게이트 2: 범위 검증 | `allowed_write_files` 초과 파일 검출 | 1 | orca_level1_gate.py:299-341 |
| 게이트 3: 테스트/검증 명령 실행 | Capsule `verification_commands` 실행, 능력 커버리지 확인 | 1 | orca_level1_gate.py:596-725 |
| 게이트 4: 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` 실행 | 1 | orca_level1_gate.py:738-765 |
| 게이트 4b: 린터 | `uv run ruff check .` 저장소 전체 실행 | 1 | orca_level1_gate.py:768-800 |
| 게이트 5: 리뷰 보고 계약 | `validate_review_report.py` 평가 (review_checklist 대조) | 1 | orca_level1_gate.py:803-853 |

**공통**: `--strict` 옵션 시 건너뛴 필수 게이트도 실패로 간주 (orca_level1_gate.py:971-972행).

---

## 3장. 검증이 잡아내지 못하는 위반 유형

| 위반 유형 | 이유 | 코드 근거 |
| --- | --- | --- |
| 필수 필드가 존재하나 값이 빈 문자열/빈 배열 | `schema`, `version`만 빈 값 검사, 나머지 필드는 존재 여부만 확인 | summarize_worker_done.py:218-228행, `check_field_types()`는 타입만 봄 |
| commit SHA가 실제 git 역사에 없는 값 | 문자열 타입만 검사, `git rev-parse`로 실존성 미확인 | summarize_worker_done.py:90-96행, orca_level1_gate.py:1511-1521행은 Level 1 게이트에서만 확인 |
| branch가 실제 존재하지 않는 브랜치명 | 동일, Level 1 게이트에서만 `git rev-parse --verify`로 확인 | orca_level1_gate.py:1511-1533행 |
| changed_files에 실제 커밋되지 않은 파일 포함 | Level 1 게이트 1의 `git diff` 결과와 대조하지 않음 (summarize 단계에서) | summarize_worker_done.py에는 대조 로직 없음 |
| read_files에 실제로 읽지 않은 파일 포함 | 검증 수단 없음 (워커 자기 보고만 있음) | — |
| verification의 command/result가 허위/조작 | 실제 명령 실행 결과와 대조하지 않음 | summarize_worker_done.py:363-393행은 요약만 함 |
| blocking_issues가 비어있으나 실제 차단 사유 존재 | 워커가 누락 보고하면 격하 로직 작동 안 함 | summarize_worker_done.py:266-277행 |
| verdict="candidate"이나 실질은 "blocked" (차단 미보고) | blocking_issues 기반 격하만 수행, 내용적 타당성 미검증 | 동일 |
| ORCA_WORKER_DONE_V2 외 스키마 사용 (schema 필드는 다른 값) | schema 불일치는 잡으나, 스키마 구조 자체가 다른 경우 완전 차단 못 함 | summarize_worker_done.py:223-224행 |

**핵심 한계**: 검증기는 **보고서의 형식적 완결성**과 **git 수준의 사실관계(변경 파일, 커밋 존재)**만 확인함. 워커가 보고서 내용(작업 내용, 검증 결과, 차단 사유)을 허위로 작성해도 **형식만 맞으면 통과**함.

---

## 4장. 자동 호출 여부 판정

### 4.1 `scripts/orca_taskctl.py` 내 호출 지점

| 단계 | 호출 함수 | 호출 위치 (파일:행) | 비고 |
| --- | --- | --- | --- |
| 1단계: 요약/계약 검증 | `summarize_worker_done.py` | orca_taskctl.py:1468-1495 | `finalize_task()` 내부, `--json` 옵션으로 실행 |
| 2단계: Level 1 게이트 | `orca_level1_gate.py` | orca_taskctl.py:1535-1568 | 동일 함수 내부, `--json` `--strict` 옵션으로 실행 |
| 3단계: 리뷰어 (선택) | `orca_run_reviewer.py` | orca_taskctl.py:1571-1620 | `run_reviewer=True` 시에만 실행 |

### 4.2 자동 호출 조건

- `finalize_task()`는 `orca_taskctl.py`의 `cmd_finalize()` 핸들러에서 호출됨 (1800행대 이후, 읽지 않은 부분).
- CLI 명령 `python3 scripts/orca_taskctl.py finalize --report <경로> --capsule <경로> ...`로 수동 실행 필요.
- **CI/CD 파이프라인(.github/workflows/) 내 자동 호출 여부는 이번 조사 범위 밖** (실행하지 않음).

**결론**: `finalize` 서브커맨드를 통해 **명시적으로 실행해야 하는 게이트**임. 푸시/병합 훅 등에서 자동으로 돌지 않음(코드상 확인 불가). 사람(코디네이터)이 `finalize`를 호출해야 검증이 작동함.

---

## 5장. 감사 지적 타당성 판정

**판정: 부분 타당 (일부 타당, 일부 부당)**

### 5.1 타당한 부분 (지적 맞음)

1. **워커 행동 강제 게이트 아님**: 워커가 `worker_done`을 보내기 전에 검증이 개입하지 않음. 워커가 허위 보고를 해도 `finalize` 단계에서만 걸러짐.
2. **내용 진실성 미검증**: 형식과 git 사실관계만 확인, 작업 내용·검증 결과·차단 사유의 진실성은 검증 못 함 (3장 참조).
3. **자동화되지 않음**: `finalize` 명령은 코디네이터가 수동 실행해야 함. 사전 병합 훅 등에서 자동 차단되지 않음.

### 5.2 부당한 부분 (지적 틀림)

1. **게이트가 아예 없는 것 아님**: `summarize_worker_done.py`(종료 코드 0/1/2)와 `orca_level1_gate.py`(6개 게이트, 종료 코드 0/1/2)가 **실제 작동하는 기계 검증 게이트**로 존재함.
2. **자동 호출 경로 존재함**: `orca_taskctl.py:1467-1568`에서 `finalize_task()`가 두 검증을 순차 실행함. 코디네이터가 `finalize`를 호출하면 무조건 검증됨.
3. **규약 3.3(무작업 완료 보고 금지) 강제됨**: `commit_count == 0`인데 `status == succeeded`인 쓰기 Task를 `summarize_worker_done.py:247-250`에서 위반으로 잡음.
4. **범위 위반 강제됨**: `allowed_write_files` 초과를 `summarize_worker_done.py:260-262`와 Level 1 게이트 2에서 이중으로 잡음.

### 5.3 종합 판단

감사 지적 **"문서 규칙일 뿐 강제 게이트가 아니다"**는 **게이트의 존재 여부**로는 틀렸으나, **게이트의 실효성(내용 진실성 검증 부재, 자동화 미흡)** 관점에서는 맞음. 따라서 **부분 타당**으로 판정.

---

## 6장. 게이트화를 위해 남은 최소 변경 지점

| 대상 파일 | 함수/위치 | 추가할 내용 (지목만) |
| --- | --- | --- |
| `scripts/summarize_worker_done.py` | `check_field_types()` 이후 새 함수 | `commit` 값이 `git rev-parse --verify <commit>`로 실제 존재하는지 검증. `branch`가 `git show-ref --verify refs/heads/<branch>`로 실존하는지 검증. |
| `scripts/summarize_worker_done.py` | `summarize_worker_report()` 끝부분 | `changed_files`가 Level 1 게이트 1의 `git diff` 결과와 일치하는지 대조 (Capsule 경로 전달 필요). |
| `scripts/orca_level1_gate.py` | `run_gate1_changed_files()` 반환값 활용 | 게이트 1 결과(`changed_files`)를 `summarize_worker_done`의 `changed_files`와 비교하는 로직을 게이트 2 또는 새 게이트로 추가. |
| `scripts/orca_taskctl.py` | `finalize_task()` 내부 | `summarize_worker_done` 실행 후 반환된 `changed_files`와 Level 1 게이트 1의 `changed_files`를 대조하여 불일치 시 `gate_fail = True`. |
| `scripts/orca_contract.py` | 신규 헬퍼 함수 | `verify_commit_exists(repo, commit_sha)`, `verify_branch_exists(repo, branch)`, `verify_changed_files_match(repo, base, branch, reported_files)` 등 진실성 검증 유틸리티 추가. |
| `scripts/orca_level1_gate.py` | `run_gate3_tests()` 이후 | `verification` 배열의 각 `command`가 실제 실행되었는지, `result`가 실제 출력과 일치하는지 검증하는 게이트 추가 (선택적, 비용 고려). |

**우선순위**: 1) commit/branch 실존성 검증 → 2) changed_files 대조 → 3) verification 결과 대조.

---

## 7장. 확인하지 못한 것과 그 이유

| 미확인 사항 | 이유 |
| --- | --- |
| `orca_run_reviewer.py`의 동작 방식 및 리뷰어 게이트 상세 | 허용 읽기 파일 목록에 없음 (`scripts/orca_run_reviewer.py` 미포함). 캡슐의 `forbidden`에도 전체 재독 금지. |
| CI/CD 파이프라인(`.github/workflows/`)에서 `finalize` 자동 호출 여부 | 워크플로우 파일 읽기 권한 없음. 실행 게이트의 **자동화 완성도**를 판단하려면 워크플로우 확인이 필요함. |
| `orca orchestration` CLI 명령들의 실제 동작 (dispatch, worker-start, finalize 등) | 캡슐 명시: "orca 명령을 실제로 실행하지 않는다. 워커를 기동하지 않는다." (capsule.yaml:33-35행). |
| `scripts/validate_agent_rules.py`의 구체적 검증 규칙 | 허용 읽기 파일 목록에 없음. |
| 실제 운영 중인 Run/Task에서 `finalize`가 매번 호출되는지 여부 | 런타임 상태 조회 필요 (orca 명령 실행 금지). |
| `scripts/orca_worker_watch.py`의 감시 로직 | 허용 읽기 파일 목록에 없음. |

---

## 부록: 인용 파일 목록

| 파일 경로 | 주요 인용 구간 |
| --- | --- |
| `scripts/summarize_worker_done.py` | 58-71행(REQUIRED_FIELDS), 83-130행(check_field_types), 218-228행(필수/값 검사), 247-250행(규약 3.3), 260-262행(범위 초과), 273-277행(verdict 격하), 282-286행(계약 비대) |
| `scripts/orca_level1_gate.py` | 129-176행(git 변경 파일), 299-341행(게이트 2), 596-725행(게이트 3), 738-765행(게이트 4), 768-800행(게이트 4b), 803-853행(게이트 5) |
| `scripts/orca_taskctl.py` | 1467-1495행(summarize 호출), 1535-1568행(Level 1 게이트 호출), 1421-1631행(finalize_task 전체) |
| `scripts/orca_contract.py` | 221-243행(scope_excess, write_scope_excess), 254-269행(load_report) |
| `.agents/templates/worker_done_v2.json` | 전체 41행 (템플릿 필드 구성) |
| `.orca/capsules/task_t5_worker_done_gate_survey/capsule.yaml` | 8-35행(objective, ground_truth), 77-86행(required_change, acceptance) |

---
*보고서 끝*
