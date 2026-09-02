# 운영 TLS ingress

운영 Compose는 Caddy가 TLS를 종료한 뒤 내부 네트워크의 `app:8000`으로 요청을 전달합니다. 호스트에는 Caddy의 HTTPS 포트 `443`만 게시되며, 앱의 `8000` 포트는 호스트에 게시하지 않습니다.

## 필수 환경변수

실제 인증서와 개인키는 저장소에 넣지 말고 호스트의 인증서 디렉터리에 준비하십시오. `.env` 또는 배포 환경의 비밀값 저장소에 다음 값을 지정해야 합니다.

```dotenv
TLS_DOMAIN=example.com
TLS_CERT_DIR=/absolute/path/to/certificates
TLS_CERT_FILE=/etc/caddy/certs/fullchain.pem
TLS_KEY_FILE=/etc/caddy/certs/privkey.pem
TRUSTED_PROXY_IPS=<실제 Caddy 프록시 IP 또는 해당 내부 네트워크 CIDR>
```

`TLS_CERT_DIR`은 `fullchain.pem`과 `privkey.pem`을 포함하는 호스트 디렉터리입니다. `TLS_CERT_FILE`과 `TLS_KEY_FILE`은 Caddy 컨테이너 내부 경로이며, 기본값은 위 예시와 같습니다. 인증서 발급 기관이나 실제 인증서 파일은 이 구성의 범위에 포함하지 않습니다.

`TRUSTED_PROXY_IPS`는 반드시 실제 운영 환경의 Caddy 컨테이너 IP 또는 내부 네트워크 CIDR로 설정하십시오. 비워 두거나 추측한 값을 사용하면 앱이 모든 요청을 하나의 프록시 IP로 인식해 로그인 시도 제한이 전체 사용자에게 적용될 수 있습니다.

## 기동 전 검증

환경변수를 주입한 운영 환경에서 다음 명령으로 Compose 구성을 검증합니다.

```bash
docker compose -f docker-compose.prod.yml config -q
```

검증이 통과하면 `proxy`가 443을 게시하고 `app`은 내부 네트워크에서만 접근됩니다. 인증서 파일과 개인키는 호스트 경로에서만 관리하며 Git에 추가하지 마십시오.
