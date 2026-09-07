# Task 60ec2a1417ac: 워커 런처 역할별 고지문 자동 분기 구현

> **작성일**: 2026-09-07
> **작성자**: 빌더 워커 (task_60ec2a1417ac)
> **대상 모듈**: `scripts/orca_worker_launch_common.py`, `scripts/orca_agy_launch.py`, `scripts/orca_kimi_launch.py`, `scripts/orca_qwen_launch.py`

---

## 1. 배경 및 목적

2026-09-07 Wave AI1에서 리뷰어 워커가 커밋할 변경사항이 없는 상태에서 커밋 강제 고지문(`COMMIT_NOTICE`)을 수신하여 리뷰어 계약(커밋 금지, 소스 수정 금지)과 충돌하며 작업이 정체되는 현상이 발생했습니다. 리뷰어의 산출물인 `review_done.json`은 `.orca/` 하위에 위치하여 `.gitignore` 대상이므로 커밋 수 0이 정상 상태입니다.

종전에는 `--no-commit-notice` 플래그가 존재했으나 코디네이터가 수동으로 기억하여 지정해야 했으며, 누락 시 워커가 차단되는 위험이 상존했습니다.

본 작업의 목적은 다음과 같습니다:
1. 고지문 리터럴을 `scripts/orca_worker_launch_common.py`에 단일화하여 중복 정의 제거.
2. 지시문 텍스트를 기반으로 리뷰어/빌더 역할을 자동 판정하는 로직(`detect_role`) 도입.
3. 리뷰어로 판정 시 커밋 강제 고지문 대신 리뷰어 계약 고지문(`REVIEWER_NOTICE`) 첨부.
4. 역할 판정 불가 시 종전 빌더 계약을 기본값으로 적용(fail-closed).
5. 3개 런처(`agy`, `kimi`, `qwen`)에 `--role` 인자(`auto`, `builder`, `reviewer`)를 제공하여 명시적 오버라이드 지원.
6. `--no-commit-notice` 플래그 지정 시 역할과 무관하게 모든 고지문 생략 보장.

---

## 2. 변경 내역 상세

### 2.1 공통 모듈 (`scripts/orca_worker_launch_common.py`)
- `COMMIT_NOTICE`: 종전 빌더용 커밋 강제 고지문 정의를 공통 상수로 일원화.
- `REVIEWER_NOTICE`: 소스 수정 금지, 커밋 금지, git add 금지, `review_done.json` 커밋 금지 및 `review_done.json` 작성과 `orca orchestration send --type worker_done` 전송 요건을 명시한 새 리뷰어 고지문 정의.
- `detect_role(prompt: str) -> str`: 지시문 텍스트 내 `ORCA_REVIEW_DONE_V2`, `review_done.json`, `role: reviewer` 표지를 검사하여 리뷰어로 판정하며, 표지가 없거나 불확실하면 `builder`로 반환(fail-closed).
- `resolve_notice(role: str = "auto", prompt: str = "") -> str`: `role`이 `auto`인 경우 `detect_role`을 통해 고지문을 결정하고, 명시된 경우 해당 역할에 맞는 고지문을 반환.
- `append_role_notice(prompt: str, *, role: str = "auto", no_commit_notice: bool = False) -> str`: `--no-commit-notice` 여부를 고려하여 prompt 뒤에 적절한 고지문을 결합.

### 2.2 세 런처 (`agy`, `kimi`, `qwen`)
- `scripts/orca_agy_launch.py`:
  - 중복 정의된 `COMMIT_NOTICE` 리터럴 제거 후 `common.COMMIT_NOTICE`, `common.REVIEWER_NOTICE` 참조.
  - `--role` CLI 인자 추가 (`choices=["auto", "builder", "reviewer"]`, 기본값 `"auto"`).
  - 지시문 결합 시 `common.append_role_notice` 호출.
- `scripts/orca_kimi_launch.py`:
  - `COMMIT_NOTICE` 리터럴 중복 제거 및 공통 상수 참조.
  - `--role` CLI 인자 추가.
  - `common.append_role_notice` 적용.
- `scripts/orca_qwen_launch.py`:
  - `COMMIT_NOTICE` 리터럴 중복 제거 및 공통 상수 참조.
  - `--role` CLI 인자 추가.
  - `common.append_role_notice` 적용.

### 2.3 테스트 보강
- `tests/test_orca_worker_launch_common.py`:
  - `test_detect_role_identifies_reviewer_indicators`: 리뷰어 표지 인식 검증.
  - `test_detect_role_identifies_builder`: 빌더 표지 인식 검증.
  - `test_detect_role_fails_closed_to_builder`: 역할 표지 부재/빈 문자열 시 빌더 반환 검증.
  - `test_reviewer_notice_contract_content`: 리뷰어 고지문 내 필수 계약 내용 검증.
  - `test_resolve_notice_with_auto`: `auto` 모드에서의 판정 및 고지문 매핑 검증.
  - `test_resolve_notice_role_override`: 명시적 role 인자에 의한 강제 오버라이드 검증.
  - `test_append_role_notice_respects_no_commit_notice`: `--no-commit-notice` 최우선 적용 검증.
  - `test_append_role_notice_appends_correct_notice`: 정상 추가 동작 검증.
- `tests/test_orca_agy_launch.py`:
  - 리뷰어 지시문 수신 시 `REVIEWER_NOTICE` 첨부 검증.
  - 리뷰어 지시문이라도 `--no-commit-notice` 지정 시 고지문 미첨부 검증.
  - `--role` 플래그를 통한 수동 오버라이드 동작 검증.
- `tests/test_orca_kimi_launch.py`:
  - 리뷰어 지시문 수신 시 `REVIEWER_NOTICE` 첨부 검증.
  - `--no-commit-notice` 지정 시 미첨부 검증.
  - `--role` 플래그를 통한 수동 오버라이드 동작 검증.

---

## 3. 검증 결과

1. **단위 및 회귀 테스트**:
   - `uv run pytest tests/test_orca_worker_launch_common.py tests/test_orca_agy_launch.py tests/test_orca_kimi_launch.py -q` -> 68 passed (100% 통과).
2. **에이전트 규칙 검증**:
   - `python3 scripts/validate_agent_rules.py --quiet` -> 20/20 통과.
3. **전체 테스트**:
   - `uv run pytest tests/ -q -m 'not data_assets'` -> 3,847 passed, 41 skipped, 3 deselected.
   - 단 1건 실패(`test_validate_doc_links.py::test_cli_execution`): Task 6304378e4a69 커밋(cc0625ba5)에서 생성된 `docs/analysis/task_6304378e4a69.md`의 `.orca` 하위 파일 링크 부재로 인한 기등록 레거시 결함으로, 본 Task 범위 밖의 사안임.

---

## 4. 결론

워커 런처 고지문 문자열이 공통 모듈로 단일화되었고, 역할 자동 판정 및 `--role` 수동 지정, `--no-commit-notice` 우선 규칙이 모두 충족되었습니다.
