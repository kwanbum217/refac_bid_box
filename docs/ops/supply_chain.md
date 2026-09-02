# 공급망 검증

> 최종 갱신: 2026-09-02

## CI 검증

`.github/workflows/ci.yml`의 `supply-chain` 잡은 잠금 파일을 기준으로 Python과 JavaScript 의존성 취약점을 조회하고, 애플리케이션 컨테이너의 운영체제·라이브러리 취약점을 Trivy로 검사합니다. Syft를 통해 SPDX JSON 형식의 SBOM을 만들고 GitHub Actions 아티팩트로 업로드합니다.

현재 저장소의 기존 취약점 현황을 먼저 관찰하기 위해 세 검사는 보고 전용입니다. `continue-on-error`는 사용하지 않으며, pip-audit와 npm audit의 결과는 로그에 남기고 Trivy는 `CRITICAL,HIGH` 심각도 범위를 명시하되 exit code를 0으로 설정합니다.

다음 조건을 충족하면 게이트로 승격합니다.

1. 의존성 스캔에서 기존 예외 목록을 검토하고 HIGH 이상 취약점이 0건입니다.
2. Trivy의 CRITICAL,HIGH 결과가 0건이며, 수정 가능한 취약점의 예외 사유와 만료일이 기록돼 있습니다.
3. SBOM 생성과 아티팩트 업로드가 매 빌드에서 성공합니다.

게이트 승격 시 Python과 npm 스캔의 `|| true`를 제거하고 Trivy의 `exit-code`를 `1`로 변경합니다. 수정 불가능한 취약점은 `ignore-unfixed` 정책을 재검토한 뒤 별도 승인된 예외로 관리합니다.

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
