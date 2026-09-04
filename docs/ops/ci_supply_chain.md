# CI 공급망 보안 검증 운영 및 결함 조치

본 문서는 main CI의 `공급망 보안 검증` job에서 발생한 실패의 원인 실측 결과와 이를 정상화하기 위해 적용한 조치 내역을 기술합니다. 향후 유사한 실패가 발생했을 때 빠르게 원인을 파악하고 대응할 수 있도록 운영 절차를 함께 정리합니다.

## 1. 개요 및 배경

2026-09-04 main CI 실행(run 33829413176, job ID 100888992801)에서 `공급망 보안 검증` job이 약 16초 만에 실패하였습니다. 동일한 실패가 run 33826578141, 33824753851, 33780911757에서도 연속으로 관측되었습니다.

당시 CI 로그 마지막 줄에는 다음과 같은 메시지가 출력되었습니다.

```text
Trivy failed but result file not found: trivy-results.json
##[error]Process completed with exit code 1.
```

겉으로는 Trivy 스캔이 결과 파일을 생성하지 못해 실패한 것처럼 보였으나, 실제 원인은 선행 단계의 비정상 종료로 인해 Trivy 스캔 자체가 실행되지 못한 것이었습니다.

## 2. 실측 기반 원인 분석

`gh run view --job 100888992801 --log` 명령을 통해 job 전체 단계별 실행 내역과 타임스탬프를 실측하여 다음과 같은 사실을 확정하였습니다.

### 2.1 pip-audit 단계의 비정상 종료 (근본 원인)

`.github/workflows/ci.yml` 파일의 `Scan Python dependencies` 단계에서 실행된 명령은 다음과 같았습니다.

```bash
uvx --from pip-audit pip-audit -r /tmp/requirements.txt --strict $IGNORE_ARGS
```

실제 실행 로그:
```text
공급망 보안 검증	UNKNOWN STEP	2026-09-04T02:25:04.1817407Z uvx --from pip-audit pip-audit -r /tmp/requirements.txt --strict $IGNORE_ARGS
...
공급망 보안 검증	UNKNOWN STEP	2026-09-04T02:25:04.3172050Z ##[error]Process completed with exit code 1.
```

로컬 및 환경 실측 결과, `pip-audit` 도구에는 `--strict`라는 이름의 명령행 옵션 플래그가 존재하지 않습니다. `pip-audit`의 argparse 문법상 인식되지 않는 `--strict` 플래그는 위치 인자인 `project_path`로 파싱되며, `pip-audit`는 `-r/--requirement` 옵션과 `project_path`의 동시 지정을 허용하지 않으므로 다음과 같은 오류가 발생하며 즉시 종료 코드 2(또는 1)로 실패합니다.

```text
usage: pip-audit [-h] [-V] [-l] [-r REQUIREMENT] ... [project_path]
pip-audit: error: argument project_path: not allowed with argument -r/--requirement
```

### 2.2 후속 단계의 건너뜀(skipped) 및 trivy-results.json 부재

`Scan Python dependencies` 단계가 실패함에 따라 GitHub Actions의 기본 정책에 의해 이후 단계들이 전부 실행되지 않고 건너뛰어졌습니다.

- `Scan JavaScript dependencies`: skipped
- `Build application image`: skipped
- `Scan container image` (id: trivy-scan): skipped

이로 인해 Trivy 스캔은 실행조차 되지 못하였고, 결과 파일인 `trivy-results.json`은 파일시스템에 생성되지 않았습니다.

### 2.3 필터 단계의 misleading 에러 출력

`.github/workflows/ci.yml` 파일의 `Filter Trivy results against allowlist` 단계는 `if: always()` 조건으로 설정되어 있어, 이전 단계의 실패 여부와 무관하게 무조건 실행되었습니다.

해당 단계의 스크립트는 다음과 같았습니다.

```bash
if [ "${{ steps.trivy-scan.outcome }}" = "success" ]; then
  exit 0
fi
RESULT_PATH=${TRIVY_OUTPUT:-trivy-results.json}
if [ ! -f "$RESULT_PATH" ]; then
  echo "Trivy failed but result file not found: $RESULT_PATH" >&2
  exit 1
fi
```

`steps.trivy-scan`의 실행 결과는 skipped였으므로 `steps.trivy-scan.outcome`은 `"skipped"`였습니다. 스크립트는 `"success"`가 아니라는 이유로 파일 존재 여부 검사로 진입하였고, 파일이 없자 `Trivy failed but result file not found: trivy-results.json`를 출력하며 종료 코드 1로 실패하였습니다. 이것이 로그의 마지막 줄에 찍혀 실제 실패 원인을 가리고 있었습니다.

### 2.4 JavaScript 스캔 단계의 경로 결함

동일한 워크플로의 `Scan JavaScript dependencies` 단계는 `working-directory: frontend`로 지정되어 있습니다. 그러나 내부 파이썬 스크립트에서 `.github/vulnerability-allowlist.yml`을 상대 경로로 읽고 있었습니다. `frontend` 디렉터리 기준으로는 `../.github/vulnerability-allowlist.yml`이어야 하므로, npm audit이 취약점을 감지해 필터 스크립트로 넘어갔을 때 `FileNotFoundError`로 실패할 수 있는 결함이 잠재되어 있었습니다.

## 3. 적용 조치

### 3.1 워크플로 수정 (`.github/workflows/ci.yml`)

1. `Scan Python dependencies` 단계에서 잘못 지정된 `--strict` 플래그를 제거하고 사유 주석을 기재하였습니다.
   ```bash
   # pip-audit 에는 --strict 플래그가 없으며 -r 과 함께 전달되면 위치 인자(project_path)로
   # 오인되어 상호 배타 에러로 비정상 종료합니다. 엄격 검사는 $IGNORE_ARGS 로 통제합니다.
   uvx --from pip-audit pip-audit -r /tmp/requirements.txt $IGNORE_ARGS
   ```
2. `Scan JavaScript dependencies` 단계의 allowlist 경로를 `working-directory: frontend`에 맞게 `../.github/vulnerability-allowlist.yml`로 보정하였습니다.
3. 게이트의 fail-closed 속성을 유지하기 위해 `Filter Trivy results against allowlist` 단계의 `if: always()` 조건과 파일 부재 시 즉시 실패하는 분기 로직은 그대로 보존하였습니다.

### 3.2 취약점 예외 목록 등록 (`.github/vulnerability-allowlist.yml`)

Trivy 스캔이 정상 실행되면 베이스 이미지(`python:3.11-slim`) 및 가상환경 생성 과정에서 포함된 의존성에 대해 HIGH 심각도 취약점이 검출됩니다(과거 정상 run 33653723011 실측 기록: `CVE-2026-23949`, `CVE-2026-24049`).

`docs/ops/supply_chain_policy.md` 정책에 따라 `.github/vulnerability-allowlist.yml`의 `trivy` 섹션에 필수 4개 필드(`id`, `package`, `reason`, `expires_on`)를 모두 갖추어 예외를 등록하였습니다.

- `CVE-2026-23949` (`jaraco.context`): 베이스 이미지 번들 라이브러리로 직접 호출 경로가 없고 런타임 비-root 격리 구동으로 영향이 제한적입니다 (만료일: 2026-12-31).
- `CVE-2026-24049` (`wheel`): 가상환경 생성 시 기본 포함된 라이브러리로 런타임 환경에서 외부 wheel 설치 경로가 차단되어 있습니다 (만료일: 2026-12-31).

`scripts/check_vulnerability_allowlist.py` 검증을 수행하여 6건의 예외 항목이 모두 계약을 준수함을 확인하였습니다.

## 4. 검증 결과

1. 워크플로 린트: `uv run actionlint` 실행 결과 오류 0건으로 정상 통과하였습니다.
2. 예외 목록 계약 검사: `uv run python scripts/check_vulnerability_allowlist.py` 실행 결과 6건 모두 계약을 통과하였습니다.
3. 에이전트 규칙 정합성: `python3 scripts/validate_agent_rules.py --quiet` 실행 결과 20/20건 통과하였습니다.
4. 회귀 테스트: `uv run pytest tests/ -q -m 'not data_assets'` 전량 통과를 확인하였습니다.
