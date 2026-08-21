# 워커 워크트리 준비 자동화 (`task_wt_prepare`) 분석 보고서

> **작성일**: 2026-08-22
> **작성자**: Orca Worker (`task_3df06e583522` / `task_wt_prepare`)
> **대상 도구**: `scripts/orca_prepare_worktree.py`, `tests/test_orca_prepare_worktree.py`, `docs/ops/agent_worker_launch_reference.md`

---

## 1. 개요 및 배경

2026-08-22 병렬 워커 운용 과정에서 다음과 같은 세 가지 반복 결함이 확인되었습니다.

1. **.env 누락**: `.env`는 Git 미추적 대상이므로 새 워크트리 생성 시 자동 복사되지 않아 수동 `cp`가 필요했고, 누락 시 환경변수 오류로 워커가 중단되었습니다.
2. **폴더 신뢰 다이얼로그 차단**: Antigravity CLI는 신뢰 폴더를 절대경로 단위로 관리하므로 새 워크트리마다 승인 다이얼로그가 떠서 Task 주입이 유실되고 사람이 직접 승인해야 했습니다.
3. **검증 생략 커밋**: 워커가 테스트 실패 상태에서 커밋했습니다. 다만 이 절의 2.1 실측이 보여주듯 원인은 pre-commit 훅 미동작이 아닙니다. 워크트리는 주 저장소의 `.git/hooks` 를 공유하므로 훅은 정상 동작했습니다. 실제 원인은 pre-commit 이 ruff, bandit, 규칙 검증만 돌리고 pytest 는 돌리지 않기 때문입니다. 테스트 실패는 커밋 시점에 걸리지 않고 Level 1 게이트 3 에서야 드러납니다. 이 도구는 훅 준비 누락을 막을 뿐 이 구멍을 닫지 못합니다.

본 작업은 이 세 가지 사전 준비 절차를 단일 스크립트(`scripts/orca_prepare_worktree.py`)로 묶어 자동화하고, 무변경 상태 판정 모드(`--check`)를 제공하여 준비 누락을 기계적으로 방지하는 것을 목표로 합니다.

---

## 2. Git Worktree와 pre-commit 메커니즘 실측 분석

### 2.1 Git Worktree 훅 공유 구조 실측

Git 저장소 및 워크트리 환경에서 hooks 디렉터리 참조 경로를 실측한 결과는 다음과 같습니다.

```bash
git rev-parse --git-path hooks
# 출력: /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/.git/hooks
```

- Git 2.9+ 환경에서 `git worktree`는 `core.hooksPath`가 명시되지 않는 한 주 저장소의 `.git/hooks` 디렉터리를 공용으로 참조합니다.
- 따라서 주 저장소에서 `pre-commit install`이 정상 수행되어 `.git/hooks/pre-commit` 실행 파일이 존재할 경우, 워크트리에서 `git commit`을 실행해도 주 저장소의 pre-commit 훅이 정상 트리거됩니다.

### 2.2 이전 워커에서 검증 생략 커밋이 발생한 실제 원인

1. **저장소 초기화 상태에서의 훅 부재**: 새 저장소 복제 또는 환경 구성 직후 `pre-commit install`이 실행되지 않은 상태에서 워크트리가 생성되면 `.git/hooks/pre-commit`이 존재하지 않아 훅이 전혀 실행되지 않습니다.
2. **워크트리 가상환경(.venv) 경로 및 상대 경로 오염**: `pre-commit install` 실행 시 `--config .pre-commit-config.yaml`을 명시하지 않으면 실행 디렉터리 기준 상대 경로(`../../.../.pre-commit-config.yaml`)가 공용 훅 파일에 하드코딩되어, 다른 워크트리에서 커밋 시 설정 파일을 찾지 못하고 에러가 발생하여 `--no-verify`로 우회될 위험이 있습니다.
3. **사전 검증 자동화 결여**: 워커 터미널 기동 전 워크트리의 hooks 설정 상태를 점검하는 기계적 게이트가 부재했습니다.

---

## 3. 구현 내용

### 3.1 `scripts/orca_prepare_worktree.py`

워크트리 경로와 주 저장소 경로를 전달받아 순차적으로 3단계를 수행합니다.

| 단계 | 항목 | 동작 내용 | 비고 |
| --- | --- | --- | --- |
| 1단계 | `.env` 배치 | 주 저장소의 `.env`를 워크트리로 복사 (`shutil.copy2`) | 이미 존재 시 스킵, 값 일절 미출력 |
| 2단계 | 신뢰 등록 | `scripts/orca_trust_worktree.py` 연동 등록 | `settings.json`, `trustedFolders.json` 갱신 |
| 3단계 | pre-commit 점검 | `git rev-parse --git-path hooks` 기반 훅 실존 확인 및 `pre-commit install` 실행 | 미설치 시 자동 설치 |

#### `--check` 모드
- 파일 및 설정을 일절 변경하지 않고 3개 항목의 준비 상태만 판정합니다.
- 하나라도 미준비 상태인 경우 종료 코드 1을 반환하며, 모두 준비된 경우 0을 반환합니다.

### 3.2 `tests/test_orca_prepare_worktree.py`

격리된 `tmp_path` 환경에서 가짜 저장소 및 워크트리를 생성하여 검증하는 8개 단위 테스트를 구현했습니다.

- `test_unprepared_worktree_check_fails`: 미준비 워크트리에서 `--check` 실행 시 종료 코드 1 반환 및 파일 미생성 검증.
- `test_prepare_worktree_then_check_passes`: 준비 파이프라인 정상 완료 후 `--check` 실행 시 0 반환 검증.
- `test_prepare_worktree_skips_already_prepared`: 준비 완료 상태에서 재실행 시 멱등성 및 스킵 동작 검증.
- `test_env_content_is_never_printed`: `.env`의 민감한 토큰/키가 stdout/stderr에 노출되지 않음을 검증.
- `test_missing_repo_env_fails`: 주 저장소 `.env` 부재 시 정상 실패 처리 검증.
- `test_invalid_worktree_path`: 유효하지 않은 경로 전달 시 예외 처리 검증.
- `test_cli_main_entrypoint`: CLI 인수 파싱(`--repo`, `--check`) 정상 동작 검증.
- `test_real_gemini_files_untouched`: monkeypatch를 통해 사용자 홈 디렉터리(`~/.gemini`)의 실제 파일이 일절 변경되지 않음을 보증.

### 3.3 문서 반영 (`docs/ops/agent_worker_launch_reference.md`)

- 2절의 기존 2단계(`.env` 수동 cp) 및 3단계(`orca_trust_worktree.py` 호출)를 `uv run python scripts/orca_prepare_worktree.py <워크트리>` 1줄로 통합.
- 2.1절에 pre-commit 확인 및 `--check` 옵션 설명 추가.
- `source_commit` 자동 갱신은 코디네이터 소유 파일과의 충돌 방지를 위해 이번 범위에서 제외되었음을 미해결 항목으로 명시.

---

## 4. 검증 결과

```bash
# 1. orca_prepare_worktree 단위 테스트
uv run pytest tests/test_orca_prepare_worktree.py -v
# 결과: 8 passed in 1.63s

# 2. 에이전트 규칙 및 스킬 정합성 검증
python3 scripts/validate_agent_rules.py --quiet
# 결과: 종료 코드 0

# 3. 백엔드 전체 테스트 회귀 검증
uv run pytest tests/ -q -m 'not data_assets'
# 결과: 1673 passed, 6 skipped, 3 deselected in 112s
```

---

## 5. 결론 및 미해결 항목

- 워커 워크트리 준비의 3대 필수 요건(.env, Antigravity 신뢰, pre-commit)이 단일 도구 및 단일 명령으로 완전 자동화되었습니다.
- **미해결 항목**: `source_commit` 자동 갱신은 코디네이터가 관리하는 Intent/Capsule 파일과의 충돌을 방지하기 위해 본 워커 준비 범위에서 의도적으로 제외되었습니다.
