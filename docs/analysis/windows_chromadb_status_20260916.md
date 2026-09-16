# Windows 실기 경로 및 ChromaDB CVE 현황 보고서 (2026-09-16)

> **작성일**: 2026-09-16
> **작성자**: Orca Builder (Worker)
> **작업 ID**: `task_eecaaada87af`
> **소속 Run**: `run_4ed3b9b08099`
> **기준 상태**: G2 보류 (Windows Docker Desktop 실기 미검증), ChromaDB 0.6.3 유지 (상류 미수정, 2026-12-31 재확인 유지)

---

## 1. 요약 및 핵심 결론

본 보고서는 ChromaDB 상류 취약점(CVE/GHSA 4건)의 수정 패치 존재 여부 실측 결과와 Windows Docker Desktop 실기 검증 경로 현황을 기록한 정본 분석 문서입니다.

1. **ChromaDB CVE 상류 수정 버전 부재**:
   - 2026-09-16 18:48 KST 기준 GitHub Advisory API 및 OSV API 실측 결과, 4개 권고(GHSA-2wm9-hf6c-p5cr, GHSA-xph7-9rjv-w5fr, GHSA-36p7-vc44-83pf, GHSA-f4j7-r4q5-qw2c) 모두 `first_patched_version`이 존재하지 않습니다 (`null`).
   - PyPI 최신 배포 버전은 여전히 `1.5.9`이며, 해당 버전까지 취약 범위에 완전히 포함됩니다.
   - 따라서 **ChromaDB 1.x 업그레이드를 제안하지 않으며**, 기존 확정 정책인 **'상류 미수정, 2026-12-31 재확인 유지'**를 그대로 유지합니다.

2. **Windows 실기 경로 부재 및 G2 게이트 현황**:
   - 코디네이터 실측 확인(2026-09-16 18:33 KST) 결과, Orca 원격 환경(`orca environment list`)은 0건(빈 배열)이며 현재 가용한 Windows 원격 워커 경로는 존재하지 않습니다.
   - 워커는 계약에 따라 불필요한 `orca` CLI 명령을 실행하지 않았습니다.
   - G2 크로스 플랫폼 게이트는 **'보류 (Windows Docker Desktop 실기 미검증)'**를 유지하며, CI Windows job은 정규 통과 상태(Run 33947859707 기준)를 유지합니다.

3. **자산 및 스택 불변 준수**:
   - 운영 및 워크트리의 `chroma_db/` 디렉터리는 열람하거나 수정하지 않았습니다.
   - `pyproject.toml`, `.github/vulnerability-allowlist.yml`, `uv.lock` 및 소스 코드는 일체 변경하지 않았습니다.

---

## 2. ChromaDB CVE 상류 패치 실측 결과

### 2.1 실측 환경 및 질의 정보
- **실측 일시**: 2026-09-16 18:48:06 KST
- **조회 엔드포인트**:
  - GitHub Advisory API: `https://api.github.com/advisories/{GHSA_ID}`
  - OSV API: `https://api.osv.dev/v1/vulns/{GHSA_ID}`
  - PyPI JSON API: `https://pypi.org/pypi/chromadb/json` (최신 릴리스 `1.5.9` 확인)

### 2.2 권고별 상세 현황

| 권고 식별자 | CVE 식별자 | 심각도 | 취약 버전 범위 | 최초 수정 버전 (`first_patched_version`) | 최종 갱신 일시 | 권고 URL |
| --- | --- | --- | --- | --- | --- | --- |
| [GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | CVE-2026-45830 | High | `>= 0.4.17, <= 1.5.9` | **없음 (null)** | 2026-08-24T19:57:43Z | https://github.com/advisories/GHSA-2wm9-hf6c-p5cr |
| [GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | CVE-2026-45831 | High | `>= 0.5.0, <= 1.5.9` | **없음 (null)** | 2026-08-24T20:00:43Z | https://github.com/advisories/GHSA-xph7-9rjv-w5fr |
| [GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf) | CVE-2026-45833 | Critical | `>= 0.4.17, <= 1.5.9` | **없음 (null)** | 2026-08-24T20:03:34Z | https://github.com/advisories/GHSA-36p7-vc44-83pf |
| [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | CVE-2026-45829 | Critical | `>= 1.0.0, <= 1.5.9` | **없음 (null)** | 2026-05-29T19:15:04Z | https://github.com/advisories/GHSA-f4j7-r4q5-qw2c |

### 2.3 기술 분석 및 판단
1. **취약점 유입 및 노출 경로**:
   - 상기 4건의 취약점은 모두 독립 Chroma HTTP 서버(`/api/v2`)의 인증, 테넌트 권한 검증 및 `trust_remote_code` 실행 경로에서 발생합니다.
   - 본 `refac_bid_box` 저장소는 애플리케이션 프로세스 내 임베디드 `PersistentClient`만을 사용하며, Docker Compose 및 프로덕션 코드 어디에도 독립 Chroma 서버, `HttpClient`, `trust_remote_code` 설정이 존재하지 않습니다.
   - 따라서 실제 운영 환경에서 해당 취약점에 대한 공격 표면은 노출되지 않습니다.
2. **업그레이드 불가 사유**:
   - 0.6.3에서 1.x(1.5.9)로 업그레이드할 경우 기존 3건의 CVE가 해소되지 않을 뿐만 아니라, 1.x 전용인 `CVE-2026-45829`가 추가로 유입됩니다.
   - 상류 패치가 출시되지 않았으므로 업그레이드를 재제안하지 않습니다.
3. **정책 결정**:
   - `.github/vulnerability-allowlist.yml`의 기존 한시 예외(사유: "상류 미수정, 서버 경로 미노출")를 유지합니다.
   - 예외 만료일인 **2026-12-31**을 상류 수정 버전 재확인 시점으로 유지합니다.

---

## 3. Windows 실기 환경 및 G2 게이트 현황

### 3.1 원격 환경 및 실기 장비 조사
- **원격 환경 점검**: 코디네이터가 2026-09-16 18:33 KST에 `orca environment list`를 확인하였으며, 등록된 환경은 0건(빈 배열)으로 확인되었습니다.
- **원격 워커 경로**: Windows 원격 실행 환경이 부재하므로 워커 레벨에서 Windows 원격 조사를 수행할 수 없습니다. 계약에 따라 임의의 `orca` CLI 탐색 명령은 실행하지 않았습니다.
- **로컬 실기 장비**: 현재 물리적 Windows Docker Desktop 실기 장비가 확보되지 않은 상태입니다.

### 3.2 게이트 및 CI 판정
- **G2 크로스 플랫폼 게이트**: **보류 (Windows Docker Desktop 실기 미검증)** 상태를 확정 유지합니다.
- **CI Windows Job**: GitHub Actions Windows 잡은 Run 33947859707 (fa1202f) 기준 `continue-on-error` 없이 정규 게이트를 통과하고 있으며, 회귀 없이 정상 통과 상태를 유지하고 있습니다.

---

## 4. 규약 준수 및 검증 결과

1. **자산 보존**:
   - `chroma_db/` 디렉터리를 일체 열거나 변경하지 않았습니다.
   - `pyproject.toml`, `.github/vulnerability-allowlist.yml`을 일체 변경하지 않았습니다.
2. **규칙 검증**:
   - `python3 scripts/validate_agent_rules.py --quiet` 검증을 수행하여 21개 전 검사 항목 통과를 확인하였습니다.
