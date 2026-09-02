# Task 5428a2df9fe9 (Rework: task_ae2326230f1f, task_44fb2650dae9, task_b76567493e41) — main 병합 경로 전량 테스트 게이트 구축

> **작성일**: 2026-09-02
> **수정일**: 2026-09-02 (Rework: task_ae2326230f1f)
> **작업 ID**: task_ae2326230f1f (이전: task_44fb2650dae9, task_b76567493e41, task_5428a2df9fe9)
> **작성자**: Antigravity (dispatched worker)
> **상태**: 완료 (Succeeded)
> **버전**: v1.3.0

---

## 1. 배경 및 문제 정의

2026-09-02 익명 API 쿼터 변경(커밋 `e1d589e`)이 `src/app/api/v1/chatbot.py`의 라인 수를 560줄에서 565줄로 증가시켜 `tests/test_chatbot_api_split.py::test_chatbot_line_counts`를 깨뜨리는 회귀가 발생했습니다. 병합 전에 대상 테스트 파일만 부분 실행했기 때문에 해당 회귀가 감지되지 않은 채 `main`에 병합되었고, 결과적으로 5개 플랫폼 CI에서 연속 2회 적색 빌드가 발생했습니다.

AGENTS.md 6장은 `main` 병합 전 테스트 전량 통과를 필수로 규정하고 있었으나, 기존 `scripts/merge_verified_branch.py`를 거치지 않고 수동 `git merge --no-ff`를 실행할 경우 이를 기계적으로 차단하는 안전장치가 부재했습니다.

---

## 2. 해결 방안 및 설계 원칙

본 작업에서는 `pre-commit` 프레임워크의 `prepare-commit-msg` 스테이지 훅을 활용하여 수동 `git merge`를 포함한 모든 병합 경로에서 전량 테스트 증거를 기계적으로 강제합니다.

### 2.1 핵심 설계 원칙

1. **Fail-Closed 검증**:
   - 전량 테스트 통과 증거가 없거나, 파일이 손상되었거나, 증거의 `exit_code != 0`이거나, 증거의 커밋 SHA가 병합 대상 커밋(`MERGE_HEAD`)과 다르거나, 개별 파일/노드만 돌린 부분 테스트 증거일 경우 병합 커밋 생성을 즉시 차단(종료 코드 1)합니다.
2. **전량 테스트(Full Suite) 엄격 검증**:
   - 증거 파일의 `command`, `suite`, `target`을 검증하여 특정 파일(`tests/test_*.py`)이나 하위 노드(`::`)만 실행한 증거를 fail-closed로 기각합니다.
   - `--record`는 항상 정본 전량 테스트 명령(`uv run pytest tests/ -q -m 'not data_assets'`)을 실행합니다.
3. **일반 커밋 속도 보존 (Commit Source 필터링)**:
   - 훅을 `prepare-commit-msg` 스테이지에 등록하고 두 번째 인자인 `commit_source`가 `merge`인 경우에만 게이트를 실행합니다. 일반 커밋(`message`, `template`, `commit`, `squash`, 인자 없음)은 즉시 통과(<1ms)하여 일상적인 작업 속도를 보존합니다.
4. **Target Branch 제한 (`main` 전용)**:
   - 현재 체크아웃된 브랜치가 `main`일 때만 검증을 강제합니다. 작업 브랜치 간의 병합(`feature` -> `refactor` 등)은 검사를 건너뛰어 워커 개발 흐름을 저해하지 않습니다.
5. **Git Hook 설치 보장 및 주 저장소 격리**:
   - `pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg` 또는 `python3 scripts/premerge_full_suite_gate.py --install-hooks`를 주 저장소(main repository) 루트에서 설치하도록 규정하여 워크트리 가상환경 결박 문제를 차단합니다.
6. **단일 우회 수단**:
   - 비상 시 우회 경로는 `BYPASS_PREMERGE_FULL_SUITE_GATE=1` 환경변수 단 하나로 제한하며, 우회 시 `sys.stderr`로 명시적 경고를 출력합니다.
7. **오프라인 동작 (네트워크/Docker 불요)**:
   - 외부 네트워크나 Docker 데몬 의존성 없이 표준 라이브러리와 git/pytest 실행만으로 완결됩니다.

---

## 3. 재작업 결함 분석 및 조치 내역 (task_44fb2650dae9 / task_b76567493e41 피드백 해소)

| 결함 | 원인 분석 | 조치 내역 |
| --- | --- | --- |
| **1. pre-merge-commit 훅에서 MERGE_HEAD 미존재** | Git 생명주기 상 `pre-merge-commit` 시점에는 `.git`에 `AUTO_MERGE`만 존재하고 `MERGE_HEAD`/`MERGE_MSG`는 아직 미생성 상태임이 실측 확인됨 | 훅 스테이지를 `pre-merge-commit`에서 `prepare-commit-msg`로 이전. 해당 시점에는 `$2=merge` 인자와 함께 `MERGE_HEAD`가 안정적으로 존재함 |
| **2. 일반 커밋 속도 저하 방지** | `prepare-commit-msg`는 일반 커밋 시에도 호출됨 | `sys.argv[2]`(`commit_source`)가 `merge`인 경우에만 게이트를 실행하고, `message`, `template`, `commit`, `squash` 및 소스 미지정 일반 커밋은 즉시 통과(exit 0)하도록 분기 처리 |
| **3. 워크트리 증거 파일 불일치** | 상대 경로(`.cache/...`) 사용 시 워크트리의 `--record` 결과가 주 저장소 병합 훅에서 보이지 않음 | `resolve_evidence_path()`를 신설하여 `git rev-parse --git-common-dir`를 기준으로 주 저장소 공통 `.cache/premerge_full_suite_evidence.json`을 단일 경로로 사용 |
| **4. 워크트리 훅 설치 시 .venv 깨짐** | 워크트리에서 `pre-commit install` 실행 시 훅의 `INSTALL_PYTHON`이 워크트리 `.venv`를 가리켜 워크트리 삭제 후 훅 파손 | 훅 설치는 반드시 주 저장소 루트에서 수행하도록 경고 메시지 출력 및 `git_branching_strategy.md`에 문서화. 미설치 시 fail-open 증상과 기계적 검증을 후속 과제로 명시 |

---

## 4. 구현 내용

### 4.1 변경 파일 목록

| 파일 경로 | 변경 유형 | 설명 |
| --- | --- | --- |
| `scripts/premerge_full_suite_gate.py` | 수정 | prepare-commit-msg 스테이지 지원, commit_source 기반 병합 선별, git-path/git-common-dir 경로 해소 |
| `tests/test_premerge_full_suite_gate.py` | 수정 | 모의 러너 기반 단위 테스트 23건 (commit_source 분기, 위치 인자 파싱, 훅 설치 검증 포함) |
| `.pre-commit-config.yaml` | 수정 | `prepare-commit-msg` 스테이지에 `premerge-full-suite-gate` 로컬 훅 등록 |
| `docs/ops/git_branching_strategy.md` | 수정 | prepare-commit-msg 훅 설치, 주 저장소 기준 설치, 미설치 시 현상 및 후속 과제 문서화 |
| `docs/analysis/task_5428a2df9fe9.md` | 수정 | 본 작업 분석 및 Rework 결과 보고서 |

### 4.2 게이트 동작 흐름

```
[git commit / git merge 실행]
         │
         ▼
[prepare-commit-msg 훅: scripts/premerge_full_suite_gate.py]
         │
         ├─► [BYPASS_PREMERGE_FULL_SUITE_GATE=1 ?] ──Yes──► [stderr 경고 후 통과 (exit 0)]
         │
         ├─► [commit_source != "merge" (일반 커밋) ?] ───Yes──► [검사 건너뜀 (exit 0)]
         │
         ├─► [현재 브랜치가 main 이 아닌가 ?] ───Yes──► [검사 건너뜀 (exit 0)]
         │
         ├─► [MERGE_HEAD 커밋 확인] ───실패──► [병합 거부 (exit 1)]
         │
         ├─► [git-common-dir 기준 .cache/premerge_full_suite_evidence.json 로드] ───부재/파싱실패──► [병합 거부 (exit 1)]
         │
         ├─► [전량 테스트 명령 및 suite/target 검증] ───부분실행기각──► [병합 거부 (exit 1)]
         │
         ├─► [증거 exit_code == 0 검사] ───실패──► [병합 거부 (exit 1)]
         │
         ├─► [증거 commit SHA == MERGE_HEAD 검사] ───불일치──► [병합 거부 (exit 1)]
         │
         ▼
[전량 테스트 증거 검증 통과 (exit 0) -> 병합 커밋 생성 완료]
```

---

## 5. 검증 결과

### 5.1 단위 테스트

- **실행 명령**: `uv run pytest tests/test_premerge_full_suite_gate.py -v`
- **결과**: `23 passed, 1 warning in 0.11s`
- **검증 항목**:
  - 단일 우회 환경변수(`BYPASS_PREMERGE_FULL_SUITE_GATE`) 동작 및 stderr 경고
  - non-main 브랜치 시 검사 자동 건너뜀
  - `commit_source != "merge"` (message, template, commit, squash, none) 시 즉시 통과
  - `commit_source == "merge"` 시 main 브랜치에서 게이트 엄격 실행
  - prepare-commit-msg 위치 인자($1 msg_file, $2 source) 정상 파싱 및 dispatch
  - `MERGE_HEAD` 미확인 시 fail-closed 거부
  - `git rev-parse --git-path MERGE_HEAD` 파일 직접 읽기 검증
  - `git rev-parse --verify MERGE_HEAD` 폴백 검증
  - `git-common-dir` 기반 워크트리 공통 증거 경로 해소 검증
  - 명시적 커스텀 증거 경로 오버라이드 검증
  - 증거 파일 부재, 손상, 비 dict 구조 시 fail-closed 거부
  - 증거 내 `exit_code != 0` 시 거부
  - 부분 테스트(특정 파일/하위 노드 실행) 증거 기각 (`is_full_suite_command`)
  - 증거 커밋 해시 불일치 시 재사용 거부 (stale evidence 차단)
  - 증거 커밋 해시 일치 및 `exit_code == 0`, 전량 대상 시 정상 통과
  - `--record` 모드 정상 실행 및 증거 JSON 기록
  - `--record` 실패 시 non-zero 종료 코드 기록
  - `--install-hooks` 동작 검증 및 워크트리 실행 시 주의 경고 검증
  - CLI 인자 파싱 및 dispatch

### 5.2 저장소 전량 테스트

- **실행 명령**: `uv run pytest tests/ -q -m 'not data_assets'`
- **결과**: `3229 passed, 35 skipped, 3 deselected, 311 warnings in 53.50s`
- **참고 사항**: 격리 워크트리 환경에는 원본 대용량 데이터 자산(`data/model_files/`, `chroma_db/`)이 배치되지 않으므로, `tests/test_data_preservation.py`의 자산 존재 검사 2건은 Capsule 사양(`ground_truth` #64)에 명시된 대로 `-m 'not data_assets'`로 제외되었습니다.

### 5.3 정적 분석 및 다중 에이전트 규칙 검증

- **규칙 검증**: `python3 scripts/validate_agent_rules.py --quiet`
  - 결과: `검증 통과: 17/17 건`
- **린터 검증**: `uv run ruff check . --output-format concise`
  - 결과: `All checks passed!`
- **포맷 검증**: `uv run ruff format --check .`
  - 결과: `All files already formatted`
- **보안 검사**: `uv run bandit -c pyproject.toml -r src/ scripts/`
  - 결과: `No issues identified. (57,673 LOC scanned)`

---

## 6. 결론 및 기대 효과

1. **우회 경로 원천 차단**: `pre-commit`의 `prepare-commit-msg` 훅을 통해 수동 `git merge --no-ff` 명령에서도 전량 테스트 통과 증거를 기계적으로 강제합니다.
2. **안정적인 Git 생명주기 결합**: `prepare-commit-msg` 시점의 `commit_source == "merge"` 및 `MERGE_HEAD` 가용성을 활용하여 거짓 양성/부재 오류 없이 정확히 병합만을 타깃팅합니다.
3. **워크트리-주저장소 완전 호환**: `git-common-dir` 기반 단일 증거 파일 경로 공유를 통해 워크트리와 주 저장소 간 증거를 완벽히 연동합니다.
4. **부분 테스트 증거 기각**: 특정 파일이나 하위 집합만 실행하여 획득한 증거를 게이트 차원에서 엄격히 기각하므로 `e1d589e`와 같은 누락 사고를 방지합니다.
5. **개발 생산성 유지**: 일반 작업 커밋 및 `feature` 브랜치 간 병합에는 게이트가 발동하지 않으므로 일상적인 개발 속도에 일체 부정적 영향을 주지 않습니다.
