# Git 브랜치 전략

> **작성일**: 2026-07-31
> **정정일**: 2026-08-01
> **버전**: v1.1.0
> **상태**: 운용 중

본 저장소는 **1인 작업**입니다. 리뷰어가 없어 Pull Request 와 `dev` 통합 브랜치를 두지 않습니다.
초판에 기술되어 있던 `dev` 기반 PR 모델은 실제로 운용된 적이 없어 정정했습니다.

---

## 1. 브랜치 모델

| 브랜치 | 용도 | 규칙 |
| --- | --- | --- |
| `main` | 운영 반영 가능 안정 버전 | 직접 작업·커밋 금지, 작업 브랜치 병합으로만 갱신 |
| `feature/*` | 개별 기능 개발 | `main`에서 분기 |
| `refactor/*` | 리팩토링 단위 작업 | `main`에서 분기 |
| `phase/*` | Phase 단위 작업 | `main`에서 분기 |
| `fix/*` | 버그 수정 | `main`에서 분기 |
| `docs/*` | 문서 작업 | `main`에서 분기 |

---

## 2. 브랜치 명명 규칙

```
feature/retraining-trainer
refactor/restore-original-parity
phase5/retraining-pipeline
fix/db-connection-timeout
docs/migration-runbook
```

---

## 3. 커밋 메시지 규칙

형식: `type: subject`

| type | 용도 |
| --- | --- |
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `chore` | 빌드, 설정, 의존성 |
| `test` | 테스트 추가/수정 |
| `ci` | CI 구성 |

예:
```
feat: add retraining trainer with LightGBM
fix: remove hardcoded DEFAULT_INST_RATE in features
docs: add phase5 retraining design
```

- 이모지 사용 금지.
- subject는 간결하게, 영어 또는 한국어 가능 (코드는 영어 권장).

---

## 4. 병합 프로세스 (PR 없음)

### 4.1 사전 준비: Git Hook 설치
`prepare-commit-msg` 훅이 활성화되어 있어야 `git merge` 시점에 게이트가 정상 동작합니다.

> **설치 환경 주의사항**: Git 훅 설치는 반드시 **주 저장소(main repository) 루트**에서 실행해야 합니다. 격리 워크트리(worktree)에서 실행할 경우 생성되는 `.git/hooks/prepare-commit-msg` 내부의 `INSTALL_PYTHON` 경로가 워크트리의 가상환경(`.venv`)을 가리키게 되어, 작업 완료 후 워크트리를 삭제했을 때 훅이 깨지는 현상이 발생합니다.

```bash
# 주 저장소 루트에서 pre-commit 및 prepare-commit-msg 훅을 모두 설치
uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg
# 또는
python3 scripts/premerge_full_suite_gate.py --install-hooks
```

#### 훅 미설치 시 현상 및 자동 검출
- **미설치 시 현상**: `prepare-commit-msg` 훅이 설치되지 않으면 `merge_verified_branch.py` 헬퍼를 거치지 않고 수동으로 `git merge --no-ff`를 실행할 때 전량 테스트 증거 유무와 무관하게 병합이 통과(fail-open)됩니다.
- **자동 검출**: `scripts/validate_agent_rules.py`가 `.pre-commit-config.yaml`의 모든 `stages`를 읽어 대응하는 `.git/hooks/<stage>` 파일의 실존 및 실행 권한을 검사합니다. 실패 시 아래 설치 명령을 그대로 출력합니다.
  `uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg`
- **CI 예외**: CI는 훅을 설치하지 않으므로 표준 환경변수 `CI=true`인 경우에만 이 로컬 훅 검사를 건너뜁니다. 로컬 실행에서 임의 환경변수로 검사를 끄는 용도는 지원하지 않습니다.
- **워크트리 준비**: `scripts/orca_prepare_worktree.py`는 설정의 모든 stage를 확인·설치하며, 설치 명령은 주 저장소 루트에서 실행하여 워크트리 제거 후에도 훅이 깨지지 않게 합니다.

### 4.2 병합 단계
1. `main`에서 작업 브랜치 분기.
2. 작업 브랜치에서 커밋·푸시.
3. 작업 브랜치(또는 워크트리)에서 전량 테스트를 실행하여 증거를 기록합니다.
   ```bash
   python3 scripts/premerge_full_suite_gate.py --record
   ```
   이 명령은 `uv run pytest tests/ -q -m 'not data_assets'`를 실행하고 `git rev-parse --git-common-dir`를 기반으로 주 저장소의 공통 `.cache/premerge_full_suite_evidence.json`에 현재 커밋 SHA와 전량 테스트 통과 증거를 기록합니다. 워크트리에서 실행해도 주 저장소 공통 캐시에 기록되므로 주 저장소 병합 훅에서 즉시 공유됩니다. 개별 파일이나 하위 집합만 실행된 부분 테스트 증거는 게이트에서 기각됩니다.
4. strict `finalize`와 Level 1 PASS가 기록된 JSON 증거를 생성합니다. 증거에는 `execution_mode: strict`, source/target branch, 그리고 검증한 source commit이 포함되어야 하며 helper는 현재 source ref와 대조한 뒤 검증된 불변 commit SHA를 `git merge` 인자로 사용합니다. 병합은 아래 helper로만 실행하며, 증거 누락·실패·재사용 시 helper는 `git merge`를 호출하지 않습니다.
   - 테스트 전량 통과 (`pytest`)
   - `python scripts/validate_agent_rules.py` 통과
   - 데이터 무손실 영향 시 [migration/](../migration/) 검증 결과 확인
5. 담당자 확인 후 `main`으로 병합. 작업 단위를 이력에 남기기 위해 helper가 `--no-ff`를 사용합니다.
   - `main` 브랜치 병합 커밋 생성 시 pre-commit의 `prepare-commit-msg` 훅인 [`scripts/premerge_full_suite_gate.py`](../../scripts/premerge_full_suite_gate.py)가 자동 실행됩니다.
   - 훅 내부에서는 commit source가 `merge`인지 확인하고, `MERGE_HEAD`로 대상 커밋을 확인하여 주 저장소 공통 `.cache/premerge_full_suite_evidence.json`을 검증합니다. 일반 커밋(`message`, `template`, `commit`, `squash` 등)은 즉시 통과하므로 개발 속도에 영향이 없습니다.
   - 전량 테스트 통과 증거가 없거나, 개별 파일만 돌린 부분 테스트 증거이거나, 증거의 커밋 해시가 병합 대상 커밋과 다르거나, 테스트 종료 코드가 0이 아닌 경우 fail-closed 방식으로 병합이 즉시 차단됩니다.
   - 비상 시 단일 우회 수단으로 `BYPASS_PREMERGE_FULL_SUITE_GATE=1` 환경변수를 사용할 수 있으며 사용 시 stderr에 경고가 출력됩니다.
6. 병합 후 `main` 푸시.

```bash
git checkout -b feature/example
# 작업, 커밋
git push origin feature/example

# 1) 전량 테스트 증거 기록 (워크트리에서도 주 저장소 공통 위치에 기록됨)
python3 scripts/premerge_full_suite_gate.py --record

# 2) main 체크아웃 및 검증 기반 병합 (prepare-commit-msg 게이트 자동 검증)
git checkout main
python3 scripts/merge_verified_branch.py \
  --source-branch feature/example \
  --target-branch main \
  --finalize-evidence <strict-finalize-evidence.json> \
  --message "merge: <요약>"
git push origin main
```

> Pull Request 는 생성하지 않습니다. 에이전트도 이 규칙을 따릅니다.

---

## 5. 작업 완료 시

- [changelogs/work_log.md](../changelogs/work_log.md)에 엔트리 추가.
- 관련 문서 갱신 여부 확인.
