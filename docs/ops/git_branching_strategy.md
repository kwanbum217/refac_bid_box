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

1. `main`에서 작업 브랜치 분기.
2. 작업 브랜치에서 커밋·푸시.
3. 작업 브랜치에서 전량 테스트를 실행하여 증거를 기록합니다.
   ```bash
   python3 scripts/premerge_full_suite_gate.py --record
   ```
   이 명령은 `uv run pytest tests/ -q`를 실행하고 `.cache/premerge_full_suite_evidence.json`에 현재 커밋 SHA와 테스트 통과 여부를 기록합니다.
4. strict `finalize`와 Level 1 PASS가 기록된 JSON 증거를 생성합니다. 증거에는 `execution_mode: strict`, source/target branch, 그리고 검증한 source commit이 포함되어야 하며 helper는 현재 source ref와 대조한 뒤 검증된 불변 commit SHA를 `git merge` 인자로 사용합니다. 병합은 아래 helper로만 실행하며, 증거 누락·실패·재사용 시 helper는 `git merge`를 호출하지 않습니다.
   - 테스트 전량 통과 (`pytest`)
   - `python scripts/validate_agent_rules.py` 통과
   - 데이터 무손실 영향 시 [migration/](../migration/) 검증 결과 확인
5. 담당자 확인 후 `main`으로 병합. 작업 단위를 이력에 남기기 위해 helper가 `--no-ff`를 사용합니다.
   - `main` 브랜치 병합 커밋 생성 시 pre-commit의 `pre-merge-commit` 훅인 [`scripts/premerge_full_suite_gate.py`](../../scripts/premerge_full_suite_gate.py)가 자동 실행됩니다.
   - 전량 테스트 통과 증거가 없거나, 증거의 커밋 해시가 병합 대상 커밋과 다르거나, 테스트 종료 코드가 0이 아닌 경우 fail-closed 방식으로 병합이 즉시 차단됩니다.
   - 비상 시 단일 우회 수단으로 `BYPASS_PREMERGE_FULL_SUITE_GATE=1` 환경변수를 사용할 수 있으며 사용 시 stderr에 경고가 출력됩니다.
6. 병합 후 `main` 푸시.

```bash
git checkout -b feature/example
# 작업, 커밋
git push origin feature/example

# 1) 전량 테스트 증거 기록
python3 scripts/premerge_full_suite_gate.py --record

# 2) main 체크아웃 및 검증 기반 병합 (pre-merge-commit 게이트 자동 검증)
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
