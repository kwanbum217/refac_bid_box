# TLS ingress 작업 분석

## 결정

- 운영 Compose에 Caddy 공식 이미지를 `proxy` 서비스로 추가했습니다.
- 앱의 호스트 포트 게시를 제거하고 Caddy의 443만 게시했습니다.
- 인증서 디렉터리와 Caddy 내부 인증서 경로는 환경변수로 주입하며, 실제 인증서와 개인키는 저장소에 포함하지 않습니다.
- 운영 환경의 실제 프록시 IP 또는 CIDR을 알 수 없으므로 `TRUSTED_PROXY_IPS`는 필수 환경변수로 두고 문서에서 운영자가 지정하도록 했습니다.

## 검증

`docker compose -f docker-compose.prod.yml config -q`를 필수 환경변수 주입 후 실행합니다. 개발용 `docker-compose.yml`과 Python 의존성은 변경하지 않습니다.
