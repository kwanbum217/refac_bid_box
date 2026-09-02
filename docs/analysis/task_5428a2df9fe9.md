# Task 5428a2df9fe9 (Rework: task_b76567493e41) — main 병합 경로 전량 테스트 게이트 구축

> **작성일**: 2026-09-02
> **수정일**: 2026-09-02 (Rework)
> **작업 ID**: task_b76567493e41 (이전: task_5428a2df9fe9)
> **작성자**: Antigravity (dispatched worker)
> **상태**: 완료 (Succeeded)
> **버전**: v1.1.0

---

## 1. 배경 및 문제 정의

2026-09-02 익명 API 쿼터 변경(커밋 `e1d589e`)이 `src/app/api/v1/chatbot.py`의 라인 수를 560줄에서 565줄로 증가시켜 `tests/test_chatbot_api_split.py::test_chatbot_line_counts`를 깨뜨리는 회귀가 발생했습니다. 병합 전에 대상 테스트 파일만 부분 실행했기 때문에 해당 회귀가 감지되지 않은 채 `main`에 병합되었고, 결과적으로 5개 플랫폼 CI에서 연속 2회 적색 빌드가 발생했습니다.

AGENTS.md 6장은 `main` 병합 전 테스트 전량 통과를 필수로 규정하고 있었으나, 기존 `scripts/merge_verified_branch.py`를 거치지 않고 수동 `git merge --no-ff`를 실행할 경우 이를 기계적으로 차단하는 안전장치가 부재했습니다.

---

## 2. 해결 방안 및 설계 원칙

본 작업에서는 `pre-commit` 프레임워크의 `pre-merge-commit` 스테이지 훅을 활용하여 수동 `git merge`를 포함한 모든 병합 경로에서 전량 테스트 증거를 기계적으로 강제합니다.

### 2.1 핵심 설계 원칙

1. **Fail-Closed 검증**:
   - 전량 테스트 통과 증거가 없거나, 파일이 손상되었거나, 증거의 `exit_code != 0`이거나, 증거의 커밋 SHA가 병합 대상 커밋(`MERGE_HEAD`)과 다르거나, 개별 파일/노드만 돌린 부분 테스트 증거일 경우 병합 커밋 생성을 즉시 차단(종료 코드 1)합니다.
2. **전량 테스트(Full Suite) 엄격 검증**:
   - 증거 파일의 `command`, `suite`, `target`을 검증하여 특정 파일(`tests/test_*.py`)이나 하위 노드(`::`)만 실행한 증거를 fail-closed로 기각합니다.
   - `--record`는 항상 정본 전량 테스트 명령(`uv run pytest tests/ -q -m 'not data_assets'`)을 실행합니다.
3. **일반 커밋 속도 보존**:
   - 훅을 `pre-commit` 스테이지가 아닌 `pre-merge-commit` 스테이지에만 등록하여, 일반 작업 커밋 시 55초의 전량 테스트 비용이 발생하지 않습니다.
4. **Target Branch 제한 (`main` 전용)**:
   - 현재 체크아웃된 브랜치가 `main`일 때만 검증을 강제합니다. 작업 브랜치 간의 병합(`feature` -> `refactor` 등)은 검사를 건너뛰어 워커 개발 흐름을 저해하지 않습니다.
5. **Git Hook 설치 보장**:
   - `pre-commit install --hook-type pre-commit --hook-type pre-merge-commit` 또는 `python3 scripts/premerge_full_suite_gate.py --install-hooks`를 통해 pre-merge-commit 훅이 누락되지 않도록 설치 절차를 지원합니다.
6. **단일 우회 수단**:
   - 비상 시 우회 경로는 `BYPASS_PREMERGE_FULL_SUITE_GATE=1` 환경변수 단 하나로 제한하며, 우회 시 `sys.stderr`로 명시적 경고를 출력합니다.
7. **오프라인 동작 (네트워크/Docker 불요)**:
   - 외부 네트워크나 Docker 데몬 의존성 없이 표준 라이브러리와 git/pytest 실행만으로 완결됩니다.

---

## 3. 구현 내용

### 3.1 변경 파일 목록

| 파일 경로 | 변경 유형 | 설명 |
| --- | --- | --- |
| `scripts/premerge_full_suite_gate.py` | 신규 생성/수정 | pre-merge-commit 게이트, 전량 테스트 증거 생성/검증, hook 설치 도구 |
| `tests/test_premerge_full_suite_gate.py` | 신규 생성/수정 | 모의 러너 기반 단위 테스트 (15건) |
| `.pre-commit-config.yaml` | 수정 | `pre-merge-commit` 스테이지에 `premerge-full-suite-gate` 로컬 훅 등록 |
| `docs/ops/git_branching_strategy.md` | 수정 | hook 설치 및 전량 테스트 증거 필수 요건 문서화 |
| `docs/analysis/task_5428a2df9fe9.md` | 신규 생성/수정 | 본 작업 분석 및 결과 보고서 |

### 3.2 게이트 동작 흐름

```
[git merge 실행 (main 브랜치)]
         │
         ▼
[pre-merge-commit 훅: scripts/premerge_full_suite_gate.py]
         │
         ├─► [BYPASS_PREMERGE_FULL_SUITE_GATE=1 ?] ──Yes──► [stderr 경고 후 통과 (exit 0)]
         │
         ├─► [현재 브랜치가 main 이 아닌가 ?] ───Yes──► [검사 건너뜀 (exit 0)]
         │
         ├─► [MERGE_HEAD 커밋 확인] ───실패──► [병합 거부 (exit 1)]
         │
         ├─► [.cache/premerge_full_suite_evidence.json 로드] ───부재/파싱실패──► [병합 거부 (exit 1)]
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

## 4. 검증 결과

### 4.1 단위 테스트

- **실행 명령**: `uv run pytest tests/test_premerge_full_suite_gate.py -v`
- **결과**: `15 passed, 1 warning in 0.06s`
- **검증 항목**:
  - 단일 우회 환경변수(`BYPASS_PREMERGE_FULL_SUITE_GATE`) 동작 및 stderr 경고
  - non-main 브랜치 시 검사 자동 건너뜀
  - `MERGE_HEAD` 미확인 시 fail-closed 거부
  - 증거 파일 부재, 손상, 비 dict 구조 시 fail-closed 거부
  - 증거 내 `exit_code != 0` 시 거부
  - 부분 테스트(특정 파일/하위 노드 실행) 증거 기각 (`is_full_suite_command`)
  - 증거 커밋 해시 불일치 시 재사용 거부 (stale evidence 차단)
  - 증거 커밋 해시 일치 및 `exit_code == 0`, 전량 대상 시 정상 통과
  - `--record` 모드 정상 실행 및 증거 JSON 기록
  - `--record` 실패 시 non-zero 종료 코드 기록
  - `--install-hooks` 동작 검증
  - CLI 인자 파싱 및 dispatch

### 4.2 저장소 전량 테스트

- **실행 명령**: `uv run pytest tests/ -q -m 'not data_assets'`
- **결과**: `3220 passed, 35 skipped, 3 deselected, 311 warnings in 57.94s`
- **참고 사항**: 격리 워크트리 환경에는 원본 대용량 데이터 자산(`data/model_files/`, `chroma_db/`)이 배치되지 않으므로, `tests/test_data_preservation.py`의 자산 존재 검사 2건은 Capsule 사양(`ground_truth` #64)에 명시된 대로 `-m 'not data_assets'`로 제외되었습니다.

### 4.3 정적 분석 및 다중 에이전트 규칙 검증

- **규칙 검증**: `python3 scripts/validate_agent_rules.py --quiet`
  - 결과: `검증 통과: 17/17 건`
- **린터 검증**: `uv run ruff check . --output-format concise`
  - 결과: `All checks passed!`
- **포맷 검증**: `uv run ruff format --check .`
  - 결과: `All files already formatted`
- **보안 검사**: `uv run bandit -c pyproject.toml -r src/ scripts/`
  - 결과: `No issues identified. (57,532 LOC scanned)`

---

## 5. 결론 및 기대 효과

1. **우회 경로 원천 차단**: `pre-commit`의 `pre-merge-commit` 훅을 통해 `merge_verified_branch.py` 헬퍼를 거치지 않고 직접 실행하는 수동 `git merge --no-ff` 명령에서도 전량 테스트 통과 증거를 기계적으로 강제합니다.
2. **부분 테스트 증거 기각**: 특정 파일이나 하위 집합만 실행하여 획득한 증거를 게이트 차원에서 엄격히 기각하므로 `e1d589e`와 같은 누락 사고를 방지합니다.
3. **커밋 단위 정합성 보장**: 테스트 증거가 특정 커밋 해시에 엄격히 바인딩되므로 이전 커밋의 낡은 증거(stale evidence)를 재사용하여 회귀를 통과시키는 행위가 불가능합니다.
4. **개발 생산성 유지**: 일반 작업 커밋 및 `feature` 브랜치 간 병합에는 게이트가 발동하지 않으므로 일상적인 개발 속도에 부정적 영향을 주지 않습니다.
