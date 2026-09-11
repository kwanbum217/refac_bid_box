# SLO 알람 Alertmanager Slack 수신기 배선 및 운영 절차

> **작성일**: 2026-09-11
> **상태**: 확정 (운영 배선 완료)
> **정본 파일**: [`docker/alertmanager.yml`](../../docker/alertmanager.yml), [`docker-compose.prod.yml`](../../docker-compose.prod.yml), [`scripts/render_alertmanager_secret.py`](../../scripts/render_alertmanager_secret.py)
> **참조 문서**: [`docs/ops/slo_alerts_20260911.md`](slo_alerts_20260911.md), [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 개요 및 배선 구조

본 문서는 Prometheus SLO 알람 규칙에서 발화된 알람 중 `severity: critical` 알람을 Slack 수신기로 안전하게 전달하기 위한 Alertmanager 배선 구조와 운영 절차를 정의합니다.

Alertmanager 는 설정 파일 내에서 환경변수 치환(`${VAR}`)을 지원하지 않으므로, 비밀값(Slack Incoming Webhook URL)을 설정 파일에 직접 작성하지 않고 파일 참조(`api_url_file`)를 통해 외부에서 주입합니다.

```mermaid
flowchart TD
    subgraph Prometheus
        PR[SLO 알람 평가<br/>interval: 15s]
    end

    subgraph Alertmanager
        R{Route 판별}
        LH[local-hold 수신기<br/>외부 발신 없음 / 침묵]
        SS[slack-slo 수신기<br/>api_url_file 참조]
    end

    subgraph Host / Docker
        ENV[.env<br/>ALERTMANAGER_SLACK_WEBHOOK_URL] -->|scripts/render_alertmanager_secret.py| SEC[docker/secrets/alertmanager_slack_url<br/>권한 0600 / gitignore]
        SEC -->|읽기 전용 볼륨 마운트| AM_SEC[/etc/alertmanager/secrets/slack_url]
    end

    PR -->|알람 전송| R
    R -->|기본 라우트 또는 warning| LH
    R -->|severity = critical| SS
    AM_SEC -.->|웹훅 URL 주입| SS
    SS -->|HTTP POST| SLACK[Slack 채널<br/>#alerts-slo]
```

---

## 2. 비밀값 주입 및 파일 관리 원칙

| 구분 | 정책 | 상세 설명 |
| --- | --- | --- |
| **저장 위치** | `docker/secrets/alertmanager_slack_url` | `.gitignore` 에 등록되어 Git 저장소에 절대 커밋되지 않습니다. |
| **파일 권한** | `0600` (소유자 읽기/쓰기 전용) | 컨테이너 호스트 사용자 외의 읽기 접근을 차단합니다. |
| **컨테이너 마운트** | `/etc/alertmanager/secrets/slack_url:ro` | `docker-compose.prod.yml` 에서 읽기 전용(`:ro`)으로 마운트됩니다. |
| **Alertmanager 설정** | `api_url_file` 사용 | `docker/alertmanager.yml` 에 실제 웹훅 URL 문자열을 절대 기록하지 않습니다. |
| **로그 및 출력 격리** | 비밀값 노출 금지 | 렌더링 스크립트와 빌드 로그 어디에도 실제 URL 을 출력하지 않습니다. |

---

## 3. 비밀 파일 생성 및 운영 절차

### 3.1 비밀 파일 생성 방법

1. `.env` 파일에 발급된 Slack Incoming Webhook URL 을 설정합니다:
   ```bash
   ALERTMANAGER_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
   ```
2. 비밀 파일 생성 스크립트 또는 Makefile 타깃을 실행합니다:
   ```bash
   make render-alertmanager-secret
   # 또는
   python3 scripts/render_alertmanager_secret.py
   ```
3. 생성 결과 확인:
   - `docker/secrets/alertmanager_slack_url` 파일이 생성되고 권한이 `0600` 으로 설정됩니다.
   - 스크립트는 성공 메시지만 출력하며 실제 웹훅 URL 값은 표준출력에 찍지 않습니다.

---

## 4. 비밀값이 없을 때의 동작 및 안전 Fallback 경로

### 4.1 개발 환경 (Local Development)
- 로컬 개발 환경(`docker-compose.yml`)에서는 관측성 스택(`OTEL_ENABLED=false`) 및 Alertmanager 컨테이너가 기본 구동되지 않으므로 비밀 파일이 없는 것이 정상 상태입니다.

### 4.2 운영 Compose 환경에서 비밀값이 없는 경우의 안전 경로
- **스크립트 동작**: `.env` 에 `ALERTMANAGER_SLACK_WEBHOOK_URL` 이 없거나 비어 있으면 `scripts/render_alertmanager_secret.py` 는 비밀 파일을 생성하지 않고 안전하게 종료합니다.
- **도커 바인드 마운트 함정 방어**:
  - 호스트에 `docker/secrets/alertmanager_slack_url` 파일이 존재하지 않는 상태에서 Docker Compose 가 기동되면, 도커 데몬이 해당 경로에 **디렉터리**를 자동 생성하여 마운트합니다.
  - 이로 인해 Alertmanager 가 디렉터리를 파일로 읽으려다 `read: is a directory` 오류로 비정상 종료(CrashLoopBackOff)할 수 있습니다.
  - `scripts/render_alertmanager_secret.py` 는 대상 경로가 디렉터리로 잘못 생성된 경우 이를 자동 감지하고 정리(rmdir)하는 방어 로직을 포함합니다.
- **local-hold 폴백 절차**:
  - 비밀값이 없는 환경에서 Alertmanager 를 안전하게 기동하려면, Alertmanager 컨테이너가 정상 구동되어 관측성 스택 전체가 유지되도록 로컬 더미 엔드포인트를 지정합니다:
    ```bash
    mkdir -p docker/secrets
    echo "http://localhost:9093/local-hold" > docker/secrets/alertmanager_slack_url
    chmod 600 docker/secrets/alertmanager_slack_url
    ```
  - 이 경우 Alertmanager 는 정상 기동하며, 외부 Slack 전송 없이 내부 `local-hold` 및 Grafana 대시보드로만 알람을 관측할 수 있습니다.

---

## 5. Critical 알람만 Slack 으로 라우팅하는 이유

`docker/alertmanager.yml` 은 기본 수신기(`default receiver`)로 `local-hold` 를 유지하고, `severity: critical` 인 알람만 `slack-slo` 수신기로 분기합니다.

| 심각도 (`severity`) | 대상 알람 | 수신기 | 전달 채널 | 라우팅 사유 |
| --- | --- | --- | --- | --- |
| **critical** | `PredictHttpP95High`<br/>`PredictHttpErrorRateHigh`<br/>`OtelCollectorDown` | `slack-slo` | Slack 채널 | 서비스 가용성 및 핵심 SLO(100ms, 5xx) 위반이 발생하여 온콜 담당자의 즉각적인 개입이 필요함. |
| **warning** | `ChatStreamHttpP95High` | `local-hold` | Grafana 대시보드 | 스트리밍 챗봇의 경우 LLM 응답 특성상 변동이 존재하므로 채널 알람 피로(Alert Fatigue)를 방지하고 대시보드 모니터링으로 유지. |

또한 `inhibit_rules` 에 따라 동일한 SLO 라벨에 대해 `critical` 알람이 발화 중인 경우 연관된 `warning` 알람은 자동으로 억제됩니다.

---

## 6. Slack 메시지 구성 및 템플릿

Slack 으로 발송되는 알람 메시지에는 다음 필수 정보가 포함됩니다:
- **알람 이름** (`.Labels.alertname`)
- **SLO 라벨** (`.Labels.slo`)
- **심각도** (`.Labels.severity`)
- **발화 시각** (`.StartsAt`)
- **요약 및 상세 설명** (`.Annotations.summary`, `.Annotations.description`)
- **Grafana 대시보드 링크**: 애노테이션(`dashboard_url`)으로 설정 가능하며, 기본값은 내부 대시보드 주소(`http://localhost:3000/d/bidbox-slo-alerts`)를 참조합니다.

---

## 7. Slack 채널 변경 방법

1. **Incoming Webhook 앱 설정**: Slack 앱 설정 페이지에서 Webhook 이 바인딩된 기본 채널을 직접 변경할 수 있습니다 (가장 권장).
2. **Alertmanager 설정 재정의**: 특정 채널로 재정의가 필요한 경우 `docker/alertmanager.yml` 의 `slack_configs` 블록에 `channel` 속성을 명시합니다:
   ```yaml
   receivers:
     - name: slack-slo
       slack_configs:
         - api_url_file: /etc/alertmanager/secrets/slack_url
           channel: '#새로운-알람-채널'
           send_resolved: true
   ```
3. 설정 변경 후 Alertmanager 에 `SIGHUP` 신호를 전송하거나 컨테이너를 재로드합니다:
   ```bash
   curl -X POST http://localhost:9093/-/reload
   ```
