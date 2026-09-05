# 공급망 스캔 정책

> **버전**: 1.4.0
> **최종 갱신**: 2026-09-05
> **소유**: 1인 개발 담당자

본 문서는 refac_bid_box 저장소가 의존하는 외부 패키지와 컨테이너 이미지에 대해
공급망 보안 스캔을 어떻게 운영할지를 정리한다. 2026-09-03 외부 감사에서 P2 로
지적된 "스캔은 보고만 하고 CI 게이트에 연결되지 않는다" 문제를 해결하기 위한
정책이다.

## 1. 적용 범위

| 스캔 도구 | 대상 | 임계값 | 실패 시 CI 동작 |
|---|---|---|---|
| pip-audit | Python 의존성 (`uv export` 결과) | CRITICAL, HIGH | 비정상 종료로 CI 실패 |
| npm audit | 프론트엔드 의존성 (`frontend/`) | high, critical | 비정상 종료로 CI 실패 |
| Trivy | 컨테이너 이미지 (`refac-bid-box:ci`) | CRITICAL, HIGH | 비정상 종료로 CI 실패 |

세 스캔은 모두 차단 모드다. `|| true`, `exit-code: 0`, `continue-on-error` 로
실패를 삼키는 표현이 워크플로에 다시 들어오면 즉시 차단한다.
단, 스캐너 스텝(Trivy)의 `exit-code: 0` 은 후속 판정 스텝이 단독 게이트이고 결과 파일 부재 시 fail-closed 인 경우에만 허용된다.
그 근거는 스캐너 스텝이 비정상 종료(exit 1)하면 allowlist 필터링 판정 스텝 및 동일 빌드의 SBOM 생성·업로드 스텝이 조기 중단(skip)되는
워크플로 구조 결함을 방지하고, 스캔 결과 파일 생성과 차단 판정 책임을 명확히 분리하기 위함이다.
후속 판정 스텝은 결과 파일 부재 시 즉시 차단(exit 1), allowlist 외 CRITICAL/HIGH 취약점 잔존 시 즉시 차단(exit 1)을 수행하므로
게이트 강도는 축소되지 않는다.

## 2. 차단 임계

한 번에 너무 많이 막으면 작업 흐름이 마비되므로, 임계는 다음 원칙을 따른다.
- **CRITICAL** 과 **HIGH** 는 즉시 차단한다.
- **MEDIUM** 이하와 `ignore-unfixed: true` 로 상류에 픽스가 없는 항목은
  차단 대상에서 제외한다.

차단 임계를 임의로 낮추지 않는다. 검출된 항목이 통과해야 할 정당한 사유가 있을
때만 예외 목록에 등록한다.

## 3. 예외 목록

### 3.1 파일 위치

`.github/vulnerability-allowlist.yml`

### 3.2 항목 구조

각 예외 항목은 다음 네 필드를 모두 가져야 한다.

| 필드 | 형식 | 의미 |
|---|---|---|
| `id` | 문자열 | 식별자. python 은 CVE ID, npm 은 GHSA ID, trivy 은 CVE ID |
| `package` | 문자열 | 영향을 받는 패키지 이름 |
| `reason` | 문자열 | 왜 지금 막을 수 없는지 구체 사유 |
| `expires_on` | `YYYY-MM-DD` | 만료일. 만료 후 게이트가 다시 막는다 |

사유가 없거나 만료일이 없는 항목은 검증 단계에서 거부된다.

### 3.3 갱신 절차

1. 사유와 만료일을 정해 `.github/vulnerability-allowlist.yml` 의 적절한 섹션
   (`python`, `npm`, `trivy`) 에 항목을 추가한다.
2. 1인 작업 체계로 Pull Request를 생성하지 않으므로, .github/vulnerability-allowlist.yml 의 사유(reason)·만료일(expires_on) 필드와 작업 브랜치 커밋 메시지에 "왜 지금 막을 수 없는가"와 "언제까지인가"를 명시한다.
3. 만료일 직전에 다시 평가해 상류 픽스 적용, 의존성 업그레이드, 또는 예외
   연장을 결정한다. 만료 연장만으로 같은 사유를 반복 등록하지 않는다.

### 3.4 만료 처리

만료일이 되면 해당 항목의 패키지/식별자가 다시 검출되면 CI 가 실패한다. 만료된
항목은 목록에서 자동 제거되지 않으므로, 평가 후 명시적으로 삭제하거나 갱신해야
한다.

## 4. ignore-unfixed 정책

Trivy 의 `ignore-unfixed: true` 옵션은 유지한다. 상류에 픽스가 없는 취약점까지
막으면 우리가 할 수 있는 일이 없다. 다만 다음을 만족해야 한다.

- `ignore-unfixed` 는 Trivy 단계에만 적용한다. pip-audit 이나 npm audit 에는
  동일한 옵션이 없으므로 차단하지 않는다.
- `ignore-unfixed` 로 통과된 항목은 CI 로그에 그대로 남아 추적 가능해야 한다.
- 향후 `ignore-unfixed` 자체를 제거할지 여부는 분기별로 재평가한다.

## 5. SBOM

SBOM 생성 단계는 변경하지 않는다. `anchore/sbom-action@3ad7283483fc7af8ff2b4ea19663c2d5ca935e26` (`v0.24.2`) 가
`refac-bid-box-sbom.spdx.json` 을 그대로 만들고, `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02` (`v4`) 로
업로드한다. SBOM 자체는 게이트와 무관한 감사 산출물이다.

## 6. 책임 및 1인 작업 운영

본 저장소는 1인 작업 체계([`AGENTS.md`](../../AGENTS.md) 6장)로 Pull Request 생성 및 타인 코드 리뷰 절차를 두지 않습니다. 대신 다음 원칙으로 보안 책임성과 추적성을 기계 강제합니다.

- 정책 변경: 1인 개발 담당자 직접 검토 및 결정.
- 예외 항목 추가/갱신: PR 리뷰 대신 `.github/vulnerability-allowlist.yml` 필수 필드(`id`, `package`, `reason`, `expires_on`) 및 작업 브랜치 커밋 메시지에 사유와 기한을 기록하여 추적성 확보 (`scripts/check_vulnerability_allowlist.py`로 기계 검증).
- 만료 항목 정리: 만료일 도래 전 또는 만료 즉시 점검하여 상류 픽스 적용 또는 제거.

## 7. 변경 이력

| 날짜 | 버전 | 변경 내용 |
|---|---|---|
| 2026-09-03 | 1.0.0 | 최초 도입. pip-audit/npm audit/Trivy 의 `|| true`/`exit-code 0` 제거 및 예외 목록 체계 신설 |
| 2026-09-04 | 1.1.0 | 스캐너 스텝 exit-code 0 허용 예외 명시 (후속 단독 게이트 및 fail-closed 조건부) 및 스캐너/판정자 분리 규정 반영 |
| 2026-09-04 | 1.2.0 | 판정 스크립트 입력 계약 검증 도입 (오류 객체, 빈 객체, 오타입 차단, Results 부재 vs 0건 구분, npm metadata 개수 검증, 미해소 전이 의존성 차단) |
| 2026-09-04 | 1.3.0 | Trivy `Results[].Error` 대상 오류 차단, npm `errors` 배열 차단, npm `metadata` 패키지 수 대비 파서 설명 가능성(explainability) 정합성 검증, Trivy Action 핀 실측 기준 명시 |
| 2026-09-05 | 1.3.1 | 1인 작업 체계(AGENTS.md 6장) 정합: PR 전제 절차 제거, 예외 추적을 allowlist 필수 필드 및 커밋 메시지 기록으로 일원화, 소유 주체 정정 (C-02) |
| 2026-09-05 | 1.4.0 | GitHub Actions 7종 40자 커밋 SHA 불변 고정, pip-audit 2.10.1 명시 고정, actionlint 컨테이너 다이제스트 고정 및 1인 작업 갱신 절차 추가 (S-02) |


## 8. 예외 목록 계약의 기계 강제

사유와 만료를 문서로만 요구하면 지켜지지 않습니다. [scripts/check_vulnerability_allowlist.py](../../scripts/check_vulnerability_allowlist.py)
가 CI 의 스캔 단계보다 먼저 돌아 다음을 거부합니다.

| 거부 조건 | 이유 |
| --- | --- |
| `id`, `package`, `reason`, `expires_on` 중 하나라도 비어 있음 | 사유 없는 예외는 영구 부채가 됩니다 |
| `expires_on` 이 `YYYY-MM-DD` 형식이 아님 | 만료 비교가 불가능합니다 |
| `expires_on` 이 오늘보다 이전 | 만료된 예외가 조용히 계속 억제되는 것을 막습니다 |

만료일 당일까지는 유효합니다. 경계에서 갑자기 CI 가 붉어지지 않게 하기 위함입니다.


## 9. 판정 스크립트 입력 계약 (Fail-Closed)

스캐너 결과를 allowlist 와 대조하는 판정 스크립트([scripts/filter_npm_audit.py](../../scripts/filter_npm_audit.py), [scripts/filter_trivy_results.py](../../scripts/filter_trivy_results.py))는 단순 JSON 구문 해석에 그치지 않고, 엄격한 **입력 계약(Input Contract)**을 검증합니다.

### 9.1 '취약점 0건'과 '결과 없음/스캐너 실패'의 구분

스캐너가 정상 동작하여 보안 취약점이 0건으로 확인된 상태와, 스캐너가 네트워크 오류·레지스트리 장애·설정 오류 등으로 결과를 전혀 생성하지 못했거나 일부 타깃 스캔에 실패한 상태를 동일하게 "취약점 없음(통과)"으로 처리하면 치명적인 보안 게이트 무력화가 발생합니다.
따라서 판정 스크립트는 스캐너가 산출하지 못한 빈 결과나 오류 객체, 또는 개별 타깃 분석 실패를 '취약점 0건'으로 오인하지 않고 즉시 종료 코드 1로 차단(Fail-Closed)합니다. 트레이스백으로 중단되는 대신 stderr 에 원인 진단 메시지를 남깁니다.

### 9.2 도구별 거부 조건

| 도구 | 판정 스크립트 | 거부 조건 (Exit Code 1) | 이유 |
|---|---|---|---|
| npm audit | [scripts/filter_npm_audit.py](../../scripts/filter_npm_audit.py) | - 입력 부재, 빈 문자열, JSON 파싱 실패<br>- 최상위 구조가 객체(dict)가 아님 (list 등)<br>- 최상위 `error` 객체 또는 `errors` 배열 존재 (스캐너/레지스트리 장애 보고)<br>- `auditReportVersion` 필드 누락<br>- `vulnerabilities` 또는 `metadata.vulnerabilities` 부재/오타입<br>- `metadata`의 HIGH+CRITICAL 패키지 수와 `vulnerabilities` 매핑 불일치<br>- 파싱 결과가 `metadata` 카운트를 설명하지 못함 (누락 또는 0건 모순)<br>- 문자열 `via`의 원인 패키지가 미해소 | 스캐너 레지스트리 장애나 스키마 불일치로 인한 조용한 통과 방지, 전이 의존성 누락 방지 |
| Trivy | [scripts/filter_trivy_results.py](../../scripts/filter_trivy_results.py) | - 결과 파일 부재, 빈 파일, JSON 파싱 실패<br>- 최상위 구조가 객체(dict)가 아님 (list 등)<br>- 최상위 `Error` 키 존재 (스캐너 장애 보고)<br>- 개별 `Results[].Error` 키 존재 (타깃 단위 스캔 실패 보고)<br>- `SchemaVersion` 누락 또는 미지원 버전 (2 외)<br>- `Results` 키 자체가 누락됨<br>- `Results` 내 `Vulnerabilities` 가 리스트가 아님 | 스캐너 비정상 중단/타깃 실패와 정상 0건(`Results: []`)을 엄격히 구분하고 오타입 트레이스백 방지 |

### 9.3 스키마 버전 및 실측 기준

- **Trivy 스키마 고정**: 저장소 워크플로에 핀된 `aquasecurity/trivy-action@v0.36.0` 이 실제로 산출하는 스키마 버전은 `SchemaVersion: 2` 입니다. 각 `Results` 항목의 키는 `Class`, `Packages`, `Target`, `Type` 등으로 구성됩니다. 미지 스키마에 대해서는 임의 버전을 통과시키지 않고 fail-closed(차단)를 유지하며, 향후 상류 액션 업그레이드 시 실측 검증을 거쳐 지원 범위를 확장합니다.
- **npm audit 설명 가능성 (Explainability)**: npm audit v2의 `metadata.vulnerabilities` 수치는 개별 advisory 수가 아닌 **취약 패키지 수** 단위입니다. 단일 패키지에 복수의 advisory 가 존재하거나 전이 의존성 링크(`via: ["cause-pkg"]`)가 존재하는 경우에도, 파서는 모든 대상 패키지가 유효한 advisory 또는 해소된 전이 체인으로 완전히 설명되는지 교차 검증하여 거짓 차단(False Positive)과 누락(False Negative)을 동시에 방지합니다.

## 10. 워크플로 액션 및 도구 불변 참조 고정 (S-02)

이동 가능한 Git 태그(예: `v5`, `v4`)나 도구의 암묵적 최신 버전(`latest`) 참조는 가리키는 대상이 상류 저장소에서 임의로 변경될 수 있어, 공급망 게이트가 예기치 않은 코드를 실행하게 만들 위험이 있습니다. 이에 따라 모든 GitHub Actions와 핵심 스캐너/린터 도구는 불변 참조(40자 커밋 SHA, 명시적 버전, 컨테이너 이미지 다이제스트)로 고정합니다.

### 10.1 GitHub Actions 커밋 SHA 고정 목록

모든 워크플로(`.github/workflows/ci.yml`, `.github/workflows/release.yml`)의 액션은 반드시 40자 전체 커밋 SHA로 고정하며, 가독성을 위해 주석으로 원래 태그를 명시합니다 (형식: `<action>@<40자 SHA> # <태그>`).

| 액션 | 태그 | 고정 커밋 SHA | 유형 |
|---|---|---|---|
| `actions/checkout` | `v5` | `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09` | direct commit |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` | direct commit |
| `actions/setup-node` | `v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` | direct commit |
| `actions/upload-artifact` | `v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` | direct commit |
| `astral-sh/setup-uv` | `v3` | `caf0cab7a618c569241d31dcd442f54681755d39` | target commit (annotated tag 해소) |
| `aquasecurity/trivy-action` | `v0.36.0` | `ed142fd0673e97e23eac54620cfb913e5ce36c25` | target commit (annotated tag 해소) |
| `anchore/sbom-action` | `v0.24.2` | `3ad7283483fc7af8ff2b4ea19663c2d5ca935e26` | target commit (annotated tag 해소) |

### 10.2 도구 및 컨테이너 불변 참조

1. **pip-audit 고정**:
   - 워크플로 내에서 `uvx --from pip-audit`로 최신 버전을 동적 수신하던 방식을 `uvx --from 'pip-audit==2.10.1' pip-audit`로 고정하여 매 실행마다 동일한 스캐너 버전을 보장합니다.
2. **rhysd/actionlint 도커 이미지 다이제스트 고정**:
   - 로컬 및 CI 환경의 shellcheck 연계 검증에 사용되는 actionlint 도커 이미지는 태그(`latest`) 대신 sha256 불변 다이제스트로 고정하여 사용 가능합니다:
   - 다이제스트 참조: `rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`
   - 실행 명령 예시: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`

### 10.3 불변 참조 갱신 절차 (1인 작업 체계)

본 저장소는 1인 작업 체계([`AGENTS.md`](../../AGENTS.md) 6장)로 Pull Request 승인 절차를 전제하지 않습니다. 1인 개발 담당자가 의존 액션이나 도구 버전을 갱신할 때는 다음 기계적 검증 절차를 필수로 수행해야 합니다.

1. **커밋 SHA 실측 및 annotated tag 해소**:
   - GitHub API를 통해 해당 태그의 실제 커밋 SHA를 추출합니다.
   - `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`
   - 반환된 객체 타입이 `tag`(annotated tag)인 경우, 반드시 `gh api repos/<owner>/<repo>/git/tags/<tag_sha>`를 1회 더 호출하여 대상 `commit` SHA를 얻어야 합니다. (태그 객체 SHA를 액션 uses에 기재하면 액션 런타임이 커밋을 찾지 못해 CI가 즉시 실패합니다).
2. **워크플로 구문 린트 및 shellcheck 검증**:
   - `uv run actionlint` 실행으로 워크플로 구문 오류가 없음을 확인 (종료 코드 0).
   - `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`를 실행하여 shellcheck 연계 린트 통과 확인 (종료 코드 0).
3. **보안 게이트 강도 유지 확인**:
   - 버전 갱신 과정에서 기존 차단 임계(CRITICAL, HIGH), fail-closed 입력 계약, continue-on-error 부재 원칙이 축소되지 않았는지 확인합니다.
4. **추적성 커밋 기록**:
   - 작업 브랜치 커밋 메시지에 갱신 대상 액션/도구, 이전/이후 SHA 또는 버전, 실측 검증 명령 수행 결과를 명시합니다.
