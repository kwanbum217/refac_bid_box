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

`gh run view --job 100888992801 --log` 명령을 통해 job 전체 단계별 실행 내역과 로그 라인을 실측하여 원인을 확정하였습니다.

### 2.1 이전 시도(task_a48917d63a07)의 오진과 반려 사유

1. **오진 분석**: 이전 작업자는 로그의 마지막 에러 메시지만 보고 Trivy 스캔 실패로 예단을 내렸으며, `pip-audit`의 `--strict` 플래그가 존재하지 않는다는 잘못된 가정을 세워 플래그를 임의로 제거하였습니다. 또한 실행되지도 않은 Trivy 스캔에서 검출될 것이라 추측하여 allowlist에 2건의 CVE를 근거 없이 추가하였습니다.
2. **실제 사실**:
   - `pip-audit`의 `-S, --strict`는 실재하는 정규 플래그(`fail the entire audit if dependency collection fails`)입니다.
   - 취약점 게이트의 fail-closed 원칙상 엄격 검사 플래그를 임의로 제거하거나 실측되지 않은 CVE를 allowlist에 추가하는 것은 계약 위반입니다.

### 2.2 근본 원인: 러너 시스템 python3의 PyYAML 부재 (로그 라인 940-943)

`.github/workflows/ci.yml` 파일의 `Scan Python dependencies` 스텝에서 실행된 명령:

```bash
uv export --frozen --format requirements.txt --no-emit-project -o /tmp/requirements.txt
IGNORE_ARGS=$(python3 -c "import yaml
data = yaml.safe_load(open('.github/vulnerability-allowlist.yml')) or {}
print(' '.join('--ignore-vuln ' + e['id'] for e in data.get('python', [])))")
uvx --from pip-audit pip-audit -r /tmp/requirements.txt --strict $IGNORE_ARGS
```

실제 실행 로그 (run 33829413176, job ID 100888992801, 라인 940-943):

```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'yaml'
##[error]Process completed with exit code 1.
```

- GitHub Actions 러너(`ubuntu-latest`)에 설정된 시스템 `python3`(`/opt/hostedtoolcache/Python/3.11.16/x64/bin/python3`)에는 서드파티 패키지인 `PyYAML`이 설치되어 있지 않습니다.
- Bash의 `set -e` 환경에서 `IGNORE_ARGS=$(python3 -c "import yaml ...")` 실행 실패로 인해 스텝 전체가 즉시 exit code 1로 종료되었습니다.
- 따라서 실제 `pip-audit` 감사 명령은 실행조차 되지 못했습니다.

### 2.3 후속 단계 건너뜀 및 trivy-results.json 부재

`Scan Python dependencies` 스텝이 exit 1로 종료됨에 따라 GitHub Actions 기본 정책에 의해 이후 스텝들이 건너뛰어졌습니다.

- `Scan JavaScript dependencies`: skipped
- `Build application image`: skipped
- `Scan container image` (id: trivy-scan): skipped

Trivy 스캔 단계가 skipped 처리되었으므로 파일시스템에 `trivy-results.json` 파일이 생성되지 않았습니다.

### 2.4 필터 단계의 결과 파일 부재 실패

`Filter Trivy results against allowlist` 스텝은 `if: always()` 조건으로 설정되어 있어 선행 스텝 실패 여부와 관계없이 실행되었습니다.

스텝 내부 로직:
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

`steps.trivy-scan.outcome`은 `"skipped"`였으므로 파일 존재 여부 검사(`if [ ! -f "$RESULT_PATH" ]`)로 진입하였고, 파일이 없어 `Trivy failed but result file not found: trivy-results.json`를 출력하고 종료 코드 1로 실패하였습니다. 이 메시지가 로그 마지막 줄에 기록되어 선행 단계의 근본 원인을 가리는 착시를 유발했습니다.

## 3. 적용 조치

### 3.1 워크플로 수정 (`.github/workflows/ci.yml`)

1. **`uv run python` 호출로 전환**:
   - `Scan Python dependencies` 스텝에서 러너 시스템 `python3` 대신 uv 가상환경의 파이썬을 사용하는 `uv run python -c`로 변경하였습니다. uv 환경에는 프로젝트 의존성으로 `PyYAML`이 준비되어 있으므로 모듈 임포트 실패가 발생하지 않습니다.
   - `Scan JavaScript dependencies` 및 `Filter Trivy results against allowlist` 스텝의 인라인 파이썬 파싱 명령도 `uv run python -c`로 일관되게 변경하여 동일한 잠재 오류를 차단하였습니다.
2. **`pip-audit --strict` 플래그 유지**:
   - 의존성 수집 실패 시 전체 감사를 중단하는 `--strict` 플래그를 온전히 보존하여 엄격 검사 수준을 유지하였습니다.
3. **JavaScript 스캔 상대 경로 보정 유지**:
   - `working-directory: frontend` 설정에 맞게 `../.github/vulnerability-allowlist.yml` 상대 경로를 사용하도록 유지하였습니다.
4. **Fail-Closed 취약점 게이트 원칙 보존**:
   - `Filter Trivy results against allowlist` 스텝에 `continue-on-error`를 추가하지 않았습니다.
   - 결과 파일 부재 시 즉시 실패하는 분기를 유지하여 검사가 누락된 채 빌드가 통과하는 일이 없도록 하였습니다.
   - CRITICAL/HIGH 심각도 대상을 축소하지 않았습니다.

### 3.2 취약점 예외 목록 원복 (`.github/vulnerability-allowlist.yml`)

- 이전 시도에서 실측 근거 없이 추가되었던 Trivy 섹션 항목(`CVE-2026-23949`, `CVE-2026-24049`)을 제거하고 `trivy: []`로 원복하였습니다.
- `scripts/check_vulnerability_allowlist.py` 검증 결과 현재 등록된 4건(python 3건, npm 1건)이 모두 사유와 유효한 만료일을 갖추어 정상 통과함을 확인하였습니다.

## 4. 검증 결과

1. **워크플로 린트**:
   - 명령: `uv run actionlint`
   - exit_code: 0
   - 결과 요약: 오류 0건 (정상 종료)
2. **공급망 예외 목록 계약 검사**:
   - 명령: `uv run python scripts/check_vulnerability_allowlist.py`
   - exit_code: 0
   - 결과 요약: `공급망 예외 목록 검사 통과: 4건 (전부 사유와 유효한 만료일 보유)`
3. **로컬 pip-audit 엄격 검사**:
   - 명령: `uv export --frozen --format requirements.txt --no-emit-project -o /tmp/requirements.txt && uvx --from pip-audit pip-audit -r /tmp/requirements.txt --strict --ignore-vuln CVE-2026-45830 --ignore-vuln CVE-2026-45831 --ignore-vuln CVE-2026-45833`
   - exit_code: 0
   - 결과 요약: `No known vulnerabilities found, 3 ignored`
4. **에이전트 규칙 정합성 검증**:
   - 명령: `python3 scripts/validate_agent_rules.py --quiet`
   - exit_code: 0
   - 결과 요약: `검증 통과: 20/20 건.`
