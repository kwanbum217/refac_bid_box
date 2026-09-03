# Task 38b3bb325d8e 분석 보고서

> **목적**: 공급망 스캔(pip-audit, npm audit, Trivy)을 보고 전용에서 차단 모드로
> 전환하고, 예외 목록 체계를 도입한다.
> **작성일**: 2026-09-03
> **소유**: 플랫폼 팀

## 1. 문제 정의

기존 `.github/workflows/ci.yml` 의 `supply-chain` 잡은 세 스캔을 모두 돌리고는
있지만, 어떤 결과가 나와도 CI 가 붉어지지 않았다. 구체적으로는 다음과 같다.

- `pip-audit` 의 실행 줄 끝에 `|| true` 가 붙어 실패가 사라짐.
- `npm audit --audit-level=high || true` 가 동일한 패턴.
- Trivy 는 `exit-code: '0'` 으로 설정되어 CRITICAL/HIGH 검출도 통과시킴.

스캔 도구 자체는 동작하지만 출력이 CI 게이트와 연결되지 않아, 취약점이 그대로
병합되고 있었다. 2026-09-03 외부 감사가 이를 P2 로 지적했고, 본 Task 가 그
해결을 담당한다.

## 2. 변경 요약

| 파일 | 변경 |
|---|---|
| `.github/workflows/ci.yml` | `pip-audit`/`npm audit` 의 `|| true` 제거, Trivy 의 `exit-code` 를 `1` 로 변경, 세 스캔이 `.github/vulnerability-allowlist.yml` 의 사유+만료가 박힌 예외 항목만 통과시키도록 통합 |
| `.github/vulnerability-allowlist.yml` (신규) | 차단 모드를 켤 때 필요한 최소 예외를 사유/만료와 함께 등록 |
| `docs/ops/supply_chain_policy.md` (신규) | 차단 임계, 예외 목록 운영 규칙, `ignore-unfixed` 정책, 책임과 변경 이력 |

세 변경 모두 `Capsule` 의 `allowed_write_files` 범위 안에 있다. 그 외 파일은
수정하지 않았다.

## 3. 차단 임계와 예외 항목의 근거

### 3.1 임계: CRITICAL 과 HIGH 만 즉시 차단

`Capsule` 의 확정 계약에 따라 CRITICAL 과 HIGH 만 즉시 차단한다. MEDIUM 이하와
상류 미패치 항목은 지금 막지 않는다. 한 번에 너무 많이 막으면 팀이 게이트를
끄게 되기 때문이다.

### 3.2 예외 항목

본 Task 가 끝나는 시점에 게이트를 켜면 즉시 CI 가 붉어진다. 따라서 현재
검출된 항목 중 차단할 수 없는 것을 사유와 만료와 함께 등록한다.

| 출처 | 식별자 | 패키지 | 만료 | 사유 핵심 |
|---|---|---|---|---|
| pip-audit | CVE-2026-45830 | chromadb 0.6.3 | 2026-12-31 | chromadb 1.x 메이저 업그레이드로 해결, G1 데이터 무손실 위해 별도 Phase 분리 |
| pip-audit | CVE-2026-45831 | chromadb 0.6.3 | 2026-12-31 | chromadb 1.x 메이저 업그레이드로 해결 |
| pip-audit | CVE-2026-45833 | chromadb 0.6.3 | 2026-12-31 | chromadb 1.x 메이저 업그레이드로 해결 |
| npm audit | GHSA-2v37-7h3g-55p8 | nanoid | 2026-10-31 | Vite 의 전이 의존성이라 직접 픽스 불가, vite 6.x 업그레이드 시 해결 |

Trivy 의 예외는 현재 검출을 실측할 수 없는 환경(로컬 docker 데몬 down) 이라
`trivy: []` 로 비워 두되, `python` 과 `npm` 처럼 빈 배열도 허용되는 형태로
유지한다. 향후 Trivy 결과에 사유가 정당한 예외가 생기면 동일한 형식으로
추가한다.

## 4. 실측 결과

### 4.1 pip-audit

명령: `uvx --from pip-audit pip-audit -r /tmp/requirements.txt --strict`
요약: `Found 3 known vulnerabilities in 1 package`. 종료 코드 1.

| 패키지 | 버전 | 식별자 |
|---|---|---|
| chromadb | 0.6.3 | CVE-2026-45830 |
| chromadb | 0.6.3 | CVE-2026-45831 |
| chromadb | 0.6.3 | CVE-2026-45833 |

### 4.2 npm audit

명령: `cd frontend && npm audit --audit-level=high --json`
요약: high 1, critical 0. `vulnerabilities.nanoid.severity = high`.

| 패키지 | 등급 | 식별자 |
|---|---|---|
| nanoid | high | GHSA-2v37-7h3g-55p8 |

### 4.3 Trivy

로컬 docker 데몬이 내려가 있어 컨테이너 이미지를 빌드하거나 스캔할 수 없다.
**Trivy 의 현재 검출 수치는 실측하지 못했다. 추측 값을 보고에 적지 않는다.**

CI 환경(ubuntu-latest, docker 데몬 가용) 에서는 Trivy 가 동작하므로, 첫 실행
결과가 위 두 스캔과 다른 항목을 보여 주면 `Capsule` 의 `trivy` 섹션에 사유와
만료와 함께 항목을 추가한다.

## 5. 허용 범위 밖 변경 없음

`git diff --name-only main..HEAD` 로 확인한 변경 파일은 다음과 같다.

```
.github/workflows/ci.yml
.github/vulnerability-allowlist.yml
docs/ops/supply_chain_policy.md
docs/analysis/task_38b3bb325d8e.md
```

`Capsule` 의 `allowed_write_files` 와 정확히 일치한다. 그 외 워크플로/정책
문서/스크립트는 건드리지 않았다.

## 6. 검증 결과

### 6.1 `uv run actionlint`

```
EXIT_CODE=0
```

워크플로 YAML 의 문법/구조 오류가 없음을 확인.

### 6.2 `uv run pytest tests/ -q -m 'not data_assets'`

```
3366 passed, 40 skipped, 3 deselected in 122.67s (0:02:02)
EXIT_CODE=0
```

본 변경은 워크플로/문서만 건드리므로 테스트 영향이 없음을 확인. 격리 워크트리에
`data/model_files` 와 `chroma_db` 가 없어서 발생하는
`test_model_bin_files_exist`, `test_chroma_db_exists` 두 건은 데이터 자산
테스트이므로 `-m 'not data_assets'` 로 제외되어 본 검증 명령에 포함되지 않는다.
이는 본 Task 의 결함이 아니다.

### 6.3 `python3 scripts/validate_agent_rules.py --quiet`

```
검증 통과: 19/19 건.
EXIT_CODE=0
```

## 7. 잔여 위험과 후속 작업

- chromadb 0.6.3 의 CVE 세 건은 2026-12-31 만료. 만료 시점에 chromadb 1.x
  메이저 업그레이드와 벡터 DB 마이그레이션 작업이 선행되어야 한다.
- nanoid 의 GHSA 항목은 2026-10-31 만료. vite 6.x 업그레이드를 별도 PR로
  분리할 것.
- Trivy 의 첫 CI 결과를 확인한 후 `trivy` 섹션에 사유+만료 항목을 추가해야
  한다.
- 향후 `ignore-unfixed` 를 제거할지 여부는 분기별로 재평가한다. 현재는
  Trivy 단계에만 적용하고 그 판단 근거는 `supply_chain_policy.md` 4절에
  기록되어 있다.

## 8. Capsule review_checklist 대응

| 항목 | 결과 |
|---|---|
| `swallow_remains` | 통과. `\|\| true`, `continue-on-error`, `exit-code 0` 모두 제거 |
| `threshold_lowered` | 통과. severity/audit-level 모두 CRITICAL, HIGH 유지 |
| `exception_without_expiry` | 통과. 모든 항목이 `reason` 과 `expires_on` 보유 |
| `guessed_numbers` | 통과. Trivy 수치는 보고에 포함하지 않음 |
| `sbom_broken` | 통과. SBOM 단계 그대로 |
| `scope_creep` | 통과. 변경 파일 4건 모두 `allowed_write_files` 안 |
