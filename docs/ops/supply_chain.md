# 공급망 검증

> 최종 갱신: 2026-09-05

## CI 검증 및 게이트 운영

`.github/workflows/ci.yml`의 `supply-chain` 잡은 잠금 파일을 기준으로 Python과 JavaScript 의존성 취약점을 조회하고, 애플리케이션 컨테이너의 운영체제·라이브러리 취약점을 Trivy로 검사합니다. Syft를 통해 SPDX JSON 형식의 SBOM을 만들고 GitHub Actions 아티팩트로 업로드합니다.

세 스캔(pip-audit, npm audit, Trivy)은 모두 정규 차단 게이트로 운영 중입니다([`docs/ops/supply_chain_policy.md`](supply_chain_policy.md) 참조). `continue-on-error`는 사용하지 않으며, 허용되지 않은 `CRITICAL` 및 `HIGH` 심각도 취약점 검출 시 즉시 CI가 차단(exit code 1)됩니다.

본 저장소는 1인 작업 체계([`AGENTS.md`](../../AGENTS.md) 6장)로 Pull Request를 생성하지 않고 작업 브랜치에서 직접 검증 후 `main`에 `git merge --no-ff`로 병합합니다. 따라서 취약점 예외 관리는 PR 리뷰를 거치지 않고, `.github/vulnerability-allowlist.yml`에 필수 필드(`id`, `package`, `reason`, `expires_on`)를 명시하고 커밋 메시지에 사유와 기한을 기록하여 추적성을 유지합니다. 사유가 없거나 기한이 만료된 예외는 CI 사전 검증 단계(`scripts/check_vulnerability_allowlist.py`)에서 즉시 차단됩니다.

## 이미지 digest 고정

태그 변동으로 빌드 결과가 달라지지 않도록 애플리케이션 및 Compose 이미지에 태그와 digest를 함께 기록합니다. digest는 2026-09-02에 다음 명령으로 Docker Registry의 `Docker-Content-Digest` 헤더를 조회했습니다.

```bash
for repo in library/python library/node library/mysql library/redis getmeili/meilisearch; do
  # 각 저장소에 대응하는 태그를 지정한 뒤 Registry manifest HEAD 요청을 실행합니다.
  curl -fsSI -H "Authorization: Bearer $token" \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "https://registry-1.docker.io/v2/${repo}/manifests/${tag}"
done
```

조회 결과는 다음과 같습니다.

| 이미지 | digest |
| --- | --- |
| `python:3.11-slim` | `sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0` |
| `node:20-alpine` | `sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293` |
| `mysql:8.0` | `sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b` |
| `redis:7-alpine` | `sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf` |
| `getmeili/meilisearch:v1.14` | `sha256:8cd411ba5d9ec2dfce02e241305208eebacce0fd74a72bece21cadd03dc566ce` |

Compose와 frontend 이미지의 digest 해석은 `docker manifest inspect`로 확인했으며, 애플리케이션 빌드는 별도 CI 단계에서 수행합니다.
