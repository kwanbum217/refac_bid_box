# 알람 라우팅 및 Alertmanager 운영 명세

> **작성일**: 2026-09-15
> **상태**: 운영 계약 정본
> **관련 파일**: [`docker/alertmanager.yml`](../../docker/alertmanager.yml), [`docker-compose.prod.yml`](../../docker-compose.prod.yml)

---

## 1. 목적

본 문서는 refac_bid_box 프로젝트의 Alertmanager 경보 라우팅 정책 및 Slack 수신기 연동, 비밀값 파일 준비 절차를 정의합니다. 심각도(severity)에 따라 알람 수신 채널을 분리하여 중요한 장애 알람이 묻히지 않도록 통제합니다.

---

## 2. 수신기(Receivers) 구성

Alertmanager는 알람의 라벨에 따라 다음과 같이 세 가지 수신기로 분기합니다.

| 수신기 명칭 | 대상 심각도 | 반복 간격 (`repeat_interval`) | 설명 |
| --- | --- | --- | --- |
| `local-hold` | (기본값) | 4h | 외부 발송 없이 Alertmanager 내부에만 보류하는 기본 수신기 |
| `slack-slo` | `severity = critical` | 4h | 핵심 SLO 위반 및 주요 장애 발생 시 Slack 채널로 즉시 발송 |
| `slack-warning` | `severity = warning` | 12h | 경고 수준 알람을 분리된 Slack 채널로 전송하여 채널 피로도 제어 |

### 2.1 라우팅 및 억제 정책

- **기본 수신기**: `local-hold`를 기본값으로 유지하여 명시적인 라우팅 규칙에 매칭되지 않은 알람이 외부로 무분별하게 전송되는 것을 방지합니다.
- **그룹핑**: `alertname`, `slo` 라벨을 기준으로 알람을 묶어 발송합니다 (`group_wait: 30s`, `group_interval: 5m`).
- **억제 규칙 (Inhibit Rules)**: 동일한 `slo` 라벨을 가진 알람에 대해 `critical` 심각도 알람이 발화 중이면 중복되는 `warning` 알람 발송을 억제합니다.

---

## 3. 비밀 파일 준비 절차

Alertmanager는 설정 파일 내 환경변수 직접 치환을 지원하지 않으므로, `api_url_file` 지시자를 통해 컨테이너 내부로 읽기 전용 마운트된 비밀 파일을 참조합니다.

### 3.1 파일 경로 명세

| 수신기 | 호스트 비밀 파일 경로 | 컨테이너 마운트 경로 | 용도 |
| --- | --- | --- | --- |
| `slack-slo` | `./docker/secrets/alertmanager_slack_url` | `/etc/alertmanager/secrets/slack_url:ro` | Critical 알람용 Slack Incoming Webhook URL |
| `slack-warning` | `./docker/secrets/alertmanager_slack_warning_url` | `/etc/alertmanager/secrets/slack_warning_url:ro` | Warning 알람용 Slack Incoming Webhook URL |

> **보안 주의사항**:
> - 웹훅 URL의 실제 값은 어떠한 경우에도 코드나 문서에 기록하지 않습니다.
> - `./docker/secrets/` 경로는 `.gitignore`에 등록되어 Git 추적에서 제외됩니다.

### 3.2 비밀 파일 생성 단계

운영 배포 시 다음 절차에 따라 비밀 파일을 준비합니다.

1. **디렉터리 준비**:
   호스트의 프로젝트 루트에서 `docker/secrets/` 디렉터리가 존재하는지 확인하고, 없으면 생성합니다.
   ```sh
   mkdir -p docker/secrets
   ```

2. **비밀값 파일 작성**:
   배포 환경의 시크릿 관리 도구(예: CI/CD Secret, 오케스트레이터 시크릿 주입) 또는 `.env` 렌더링 스크립트를 통해 파일 내용을 생성합니다.
   - 단일 URL 문자열만 개행 없이 파일에 기록합니다.
   - 예시:
     ```sh
     # CI/CD 파이프라인 또는 배포 스크립트 예시
     echo -n "${PROD_SLACK_SLO_WEBHOOK_URL}" > docker/secrets/alertmanager_slack_url
     echo -n "${PROD_SLACK_WARNING_WEBHOOK_URL}" > docker/secrets/alertmanager_slack_warning_url
     ```

3. **권한 설정**:
   비밀 파일의 무단 접근을 방지하기 위해 파일 권한을 `0600`(소유자 읽기/쓰기 전용)으로 제한합니다.
   ```sh
   chmod 600 docker/secrets/alertmanager_slack_url
   chmod 600 docker/secrets/alertmanager_slack_warning_url
   ```

4. **도커 볼륨 마운트 확인**:
   `docker-compose.prod.yml`의 `alertmanager` 서비스에 두 비밀 파일이 `:ro` 모드로 마운트되어 있는지 확인합니다.

---

## 4. Compose 서비스 명세

`docker-compose.prod.yml`의 `alertmanager` 서비스 볼륨 마운트 구성은 다음과 같습니다.

```yaml
  alertmanager:
    image: prom/alertmanager:v0.28.1@sha256:27c475db5fb156cab31d5c18a4251ac7ed567746a2483ff264516437a39b15ba
    volumes:
      - ./docker/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - ./docker/secrets/alertmanager_slack_url:/etc/alertmanager/secrets/slack_url:ro
      - ./docker/secrets/alertmanager_slack_warning_url:/etc/alertmanager/secrets/slack_warning_url:ro
      - alertmanager_data:/alertmanager
```
