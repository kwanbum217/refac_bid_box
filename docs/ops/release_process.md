# 릴리스 절차

> **작성일**: 2026-09-03
> **상태**: 운용 준비
> **정본 버전**: `pyproject.toml`의 `[project].version`

---

## 1. 운영 원칙

릴리스 버전은 `pyproject.toml`의 `[project].version` 하나만 읽습니다. 태그는 그 값에 `v` 접두사를 붙인 문자열로 자동 파생하므로, 워크플로 또는 문서에 특정 버전 값을 따로 적지 않습니다.

릴리스 시작 방식은 `workflow_dispatch`입니다. `main` 병합마다 자동 릴리스가 발생하면 담당자가 배포 시점을 통제할 수 없으므로, 담당자가 GitHub Actions에서 명시적으로 워크플로를 시작해야 합니다. Pull Request를 전제로 하지 않으며, 이 저장소의 1인 작업 및 직접 병합 규칙을 따릅니다.

## 2. 릴리스 실행

1. 작업 브랜치에서 변경을 완료하고 `main`에 병합합니다.
2. `main`의 CI가 성공할 때까지 기다립니다.
3. GitHub Actions의 `Release` 워크플로에서 `Run workflow`를 선택하고 `main`을 대상 브랜치로 지정합니다.
4. 워크플로가 릴리스 준비 상태를 검사합니다.
5. 검사가 통과하면 버전에서 태그를 파생하고 태그를 원격에 push합니다.
6. 직전 릴리스 태그 이후 커밋을 커밋 type별로 묶은 노트를 사용해 GitHub Release를 생성합니다.

워크플로는 실행 커밋을 `pyproject.toml`에서 읽은 버전과 비교하지 않고, 같은 파일을 다시 읽어 태그를 구성합니다. 따라서 버전 문자열을 사람이 워크플로에 복사해 넣는 단계가 없습니다.

## 3. 릴리스 준비 상태 게이트

`scripts/check_release_readiness.py`가 다음 네 조건을 모두 확인합니다. 하나라도 실패하면 종료 코드 1을 반환하고 태그 생성 단계로 진행하지 않습니다.

| 검사 | 기준 |
| --- | --- |
| 작업 트리 | 추적·미추적 변경이 모두 없어야 합니다. |
| 브랜치 | 현재 브랜치가 `main`이어야 합니다. |
| 태그 중복 | `v<project.version>` 태그가 로컬 저장소에 없어야 합니다. 전체 이력을 checkout하여 원격 태그도 조회합니다. |
| CI | 대상 커밋의 가장 최근 `CI` 워크플로 실행이 `completed` 및 `success`여야 합니다. |

CI 확인에는 GitHub Actions가 제공하는 `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_API_URL`을 사용합니다. CI 실행을 찾지 못하거나 실행 중이거나 실패한 경우 모두 게이트를 통과하지 못합니다.

## 4. 릴리스 노트

노트는 새 태그를 만들기 전에 직전 `v` 태그와 현재 HEAD 사이의 커밋을 읽어 생성합니다. 커밋 제목의 `type: subject` 또는 `type(scope): subject` 형식을 해석하고 다음 순서로 묶습니다.

| type | 노트 묶음 |
| --- | --- |
| `feat` | `feat` |
| `fix` | `fix` |
| `docs` | `docs` |
| `refactor` | `refactor` |
| `chore` | `chore` |
| `test` | `test` |
| `ci` | `ci` |
| 그 외 | `기타` |

직전 태그가 없으면 저장소의 전체 커밋을 대상으로 합니다. 커밋 type 규약을 지키면 다음 릴리스에서 변경 유형별 이력을 바로 확인할 수 있습니다.

## 5. 수동 복구 및 금지 사항

- 준비 상태 게이트를 우회하여 태그를 만들거나 GitHub Release를 생성하지 않습니다.
- 이 작업에서는 실제 태그를 생성하거나 원격에 push하지 않았습니다. 실제 태그 생성은 담당자가 `workflow_dispatch`를 실행할 때만 수행됩니다.
- Pull Request 생성은 이 저장소의 운영 규칙에 어긋납니다.
- 이미지 서명은 이 절차에 포함하지 않습니다. Docker 데몬과 키 관리 방침을 먼저 결정해야 하므로 후속 미결 항목입니다.

## 6. 검증 명령

변경 후 다음 명령을 실행합니다.

```bash
uv run pytest tests/ -q -m 'not data_assets'
uv run actionlint
python3 scripts/validate_agent_rules.py --quiet
```

격리 워크트리에는 원본 모델 가중치와 `chroma_db`가 없으므로 `data_assets` 표시는 이 검증에서 제외합니다. 이 환경에서 해당 자산 존재 검사 두 건이 실패하는 것은 릴리스 자동화 결함이 아닙니다.
