---
name: web-platform-launch
description: 에이전트가 Docker 서버를 띄우고 웹 브라우저로 화면을 확인할 때 호출됩니다.
---

# web-platform-launch 스킬 지침

설치와 데이터 확보를 마친 저장소에서 에이전트가 Docker 스택을 띄우고 브라우저로 화면을 확인할 때 쓰는 반복 실행 절차입니다. Windows PowerShell 을 1순위로 적고 macOS·Linux bash 를 함께 둡니다. 처음 설치, `.env` 작성, 데이터 복원은 다루지 않으며 그 상태면 `.agents/skills/windows-onboarding/SKILL.md` 2·3·4장을 먼저 따릅니다. 모든 명령은 저장소 루트에서 실행합니다.

## 0. 안전 규칙

| 규칙 | 내용 |
| --- | --- |
| 데이터 보호 | `docker compose down -v` 를 쓰지 않습니다. 볼륨 삭제, DB 초기화, 데이터 삭제도 하지 않습니다. |
| 비밀값 | `.env` 값을 출력하거나 커밋하지 않습니다. 누락 오류가 나면 값은 사용자에게 받습니다. |
| 범위 | 저장소 밖 전역 설정, 방화벽, Docker Desktop 재설치를 임의로 바꾸지 않습니다. |
| 처음 설치 | Docker Desktop 이나 `.env` 가 없으면 멈추고 `windows-onboarding` 2·3장을 안내합니다. |
| 확인 우선 | 결과를 확인한 뒤 다음으로 넘어가고, 실패하면 5장 로그를 먼저 봅니다. |

## 1. Docker Desktop 확인과 기동

Docker Desktop 이 실행 중이고 Linux 컨테이너 모드인지 확인합니다.

```powershell
docker version
docker compose version
```

하나라도 실패하면 앱을 실행하고 `docker info` 가 성공할 때까지 기다립니다. 상한은 3분이며, 넘으면 기동을 멈추고 `windows-onboarding` 6장을 봅니다.

```powershell
docker desktop start
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5
}
docker version
```

`docker desktop start` 가 없는 버전은 `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"` 로 앱을 띄운 뒤 같은 대기 루프를 씁니다. macOS·Linux 는 엔진이 떠 있는지만 확인합니다.

```bash
docker info >/dev/null 2>&1 && echo "Docker 준비 완료" || echo "Docker 엔진을 실행하십시오"
```

## 2. 서버 기동

```powershell
docker compose up -d
docker compose ps
```

- 최초 기동이거나 `pyproject.toml`, `uv.lock`, `Dockerfile` 이 바뀌었으면 `docker compose up -d --build` 를 씁니다.
- `git pull`·병합 뒤에는 uvicorn 이 `--reload` 없이 돌아 라우트가 그대로이므로 `docker compose restart app worker` 로 재시작합니다. 템플릿만 바뀌었으면 즉시 반영됩니다.
- `make` 가 있으면 `make up` 이 같은 동작이지만 Windows 기본 설치가 아니므로 위 명령을 씁니다. macOS·Linux 도 `docker compose` 명령과 옵션이 같습니다.

## 3. 준비 대기

`/api/v1/health/ready` 가 `ready` 또는 `degraded` 를 돌려주면 화면을 열 수 있습니다. 상한은 5분입니다.

```powershell
$deadline = (Get-Date).AddMinutes(5)
while ((Get-Date) -lt $deadline) {
    try {
        $h = Invoke-RestMethod http://localhost:8000/api/v1/health/ready -TimeoutSec 3
        if ($h.status -in @("ready", "degraded")) { $h.status; break }
    } catch { }
    Start-Sleep -Seconds 5
}
docker compose ps
```

```bash
for i in $(seq 1 60); do
  body=$(curl -s http://localhost:8000/api/v1/health/ready || true)
  printf '%s' "$body" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"(ready|degraded)"' && { printf '%s\n' "$body"; break; }
  sleep 5
done
docker compose ps
```

`docker compose ps` 에 `app`, `worker`, `db`, `redis`, `meilisearch` 가 보여야 합니다. `degraded` 는 모델 가중치나 ChromaDB 자산이 없는 격리 워크트리에서 정상이므로 화면 확인을 계속합니다.

## 4. 브라우저 열기

| OS | 명령 |
| --- | --- |
| Windows | `Start-Process http://localhost:8000` |
| macOS | `open http://localhost:8000` |
| Linux | `xdg-open http://localhost:8000` |

```powershell
Start-Process http://localhost:8000
```

| 화면 | 주소 |
| --- | --- |
| 웹 화면 | `http://localhost:8000` |
| 공고 목록 | `http://localhost:8000/bids/` |
| API 문서 | `http://localhost:8000/docs` |
| 준비 상태 | `http://localhost:8000/api/v1/health/ready` |
| 생존 확인 | `http://localhost:8000/api/v1/health/live` |

## 5. 상태·로그

```powershell
docker compose ps
docker compose logs --tail 100 app
docker compose logs -f app
```

`logs -f` 는 `Ctrl+C` 로 빠져나오며, 그래도 컨테이너는 계속 돕니다. 기동 오류는 `app` 로그 마지막 100줄에서 먼저 찾습니다. 세 명령은 macOS·Linux 에서도 같습니다.

## 6. 선택 기능

- 챗봇 확인에는 호스트 Ollama 가 필요합니다(`ollama list`). 주소는 `host.docker.internal:11434` 입니다.
- 관측성 스택은 `docker compose --profile observability up -d` 로 띄우며 기본 기동에서 제외됩니다. Grafana 는 `http://localhost:3000` 입니다.

## 7. 종료

| 목적 | 명령 | 데이터 |
| --- | --- | --- |
| 잠시 멈춤 | `docker compose stop` | 볼륨과 DB 데이터 유지 |
| 컨테이너 제거 | `docker compose down` | 볼륨 유지 |
| 재기동 | `docker compose up -d` | 유지된 상태로 기동 |

`docker compose down` 뒤에도 `mysql_data` 볼륨은 남으므로 다음 기동에 데이터가 그대로입니다. 볼륨을 지우는 옵션은 0장에 따라 쓰지 않습니다.

## 8. 문제 해결

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| 포트 점유 | `netstat -ano` 로 `8000`, `3306`, `6379`, `7700` 확인 | 점유 프로세스를 종료한 뒤 2장을 다시 실행합니다. |
| 기동 지연 | `docker compose ps` 의 `starting`·`unhealthy` | 첫 빌드와 DB 초기화는 오래 걸립니다. 3장 대기를 계속합니다. |
| 준비 상태 `503` | 응답 `checks` 의 실패 항목 | `docker compose logs --tail 100 app` 로 원인을 봅니다. |
| `/bids/` 가 `503` | `app`, `meilisearch` 상태 | 색인이 비었을 수 있습니다. 재색인은 `windows-onboarding` 4장 A 6단계를 따릅니다. |
| 로그인 불가 | `docker compose logs --tail 100 app` | 인증 오류 원인을 확인합니다. 계정 준비는 범위 밖입니다. |

증상이 이어지면 `windows-onboarding` 6장 문제 해결 표를 봅니다.

## 9. 에이전트 지침

1. 명령마다 종료 코드와 출력을 확인하고 성공·실패를 사용자에게 한 줄로 보고합니다.
2. 브라우저를 열 수 없는 환경(원격 셸, 헤드리스)이면 열지 않고 4장 주소 표만 안내합니다.
3. 실패하면 추측으로 명령을 바꾸지 않고 `docker compose logs --tail 100 app` 를 먼저 읽습니다. 데이터를 지우는 명령은 사용자가 요청해도 실행하지 않고 0장을 근거로 거절합니다.
4. 확인이 끝나면 계속 띄울지 사용자에게 묻고, 종료 요청에는 7장 `docker compose stop` 을 씁니다.

## 10. 팀원용 프롬프트

사람이 에이전트에게 붙여 넣는 문구입니다. 스킬 경로를 직접 적어 두어 스킬을 자동으로 찾지 못하는 에이전트(Grok 등)도 같은 절차를 따릅니다.

### 10.1 매일 쓰는 프롬프트 (pull, 서버 기동, 브라우저 확인)

```text
이 저장소의 AGENTS.md 를 먼저 읽고, 그다음 .agents/skills/web-platform-launch/SKILL.md 를 끝까지 읽은 뒤 그 절차대로 진행해 줘.

1. git status 로 내 작업 트리에 커밋하지 않은 변경이 있는지 먼저 확인해. 변경이 있으면 pull 하지 말고 목록만 보여 주고 멈춰.
2. 변경이 없으면 main 브랜치에서 git pull 로 최신 커밋을 받아. 받은 커밋 목록(git log --oneline)을 보여 줘.
3. 받은 변경에 pyproject.toml, uv.lock, Dockerfile, docker-compose.yml 이 있으면 docker compose up -d --build 로 이미지를 다시 만들어. 없으면 docker compose up -d 로 띄우고, 이미 떠 있었다면 docker compose restart app worker 로 새 코드를 반영해.
4. 스킬의 준비 대기 절차대로 /api/v1/health/ready 가 ready 또는 degraded 가 될 때까지 기다린 다음, 브라우저로 http://localhost:8000 을 열어 줘.
5. 마지막에 docker compose ps 결과와 접속 주소를 표로 정리해 줘.

지켜야 할 것: docker compose down -v 나 볼륨 삭제는 절대 하지 말 것, .env 값을 화면에 출력하지 말 것, 명령이 실패하면 추측으로 다시 시도하지 말고 docker compose logs --tail 100 app 을 먼저 보고 원인을 알려 줄 것.
```

### 10.2 상황별 짧은 프롬프트

| 상황 | 프롬프트 |
| --- | --- |
| 처음 클론한 노트북 | `.agents/skills/windows-onboarding/SKILL.md 를 읽고 그 절차대로 설치 점검부터 웹 접속까지 진행해 줘. 설치가 필요하면 winget 명령 목록을 먼저 보여 주고 내 승인을 받아.` |
| 서버만 띄우기 | `.agents/skills/web-platform-launch/SKILL.md 를 읽고 서버를 띄운 뒤 브라우저로 http://localhost:8000 을 열어 줘.` |
| 상태와 로그 확인 | `.agents/skills/web-platform-launch/SKILL.md 의 상태·로그 절차대로 지금 서버 상태와 최근 app 로그를 보여 줘.` |
| 작업 끝내고 종료 | `.agents/skills/web-platform-launch/SKILL.md 의 종료 절차대로 docker compose stop 으로 서버를 내려 줘. 데이터는 지우지 마.` |
| 기능 점검까지 | `.agents/skills/platform-health-checklist/SKILL.md 를 읽고 기능 점검 항목을 확인해서 결과를 표로 정리해 줘.` |

### 10.3 알아 둘 점

| 항목 | 내용 |
| --- | --- |
| 짧은 호출 | Claude Code·OpenCode 는 스킬을 자동 인식하므로 "web-platform-launch 스킬로 서버 띄워 줘" 로도 됩니다. 경로를 적으면 어느 에이전트에서나 결과가 같습니다. |
| 메인 "집계 중" | 기동 직후 메인 화면 건수가 "집계 중" 으로 보일 수 있습니다. worker 예열이 30초 안팎에 채우므로 새로고침하면 됩니다. 오류가 아닙니다. |
| 챗봇 | AI 어드바이저는 호스트에 Ollama 가 실행 중이어야 동작합니다(6장). 나머지 화면은 Ollama 없이 볼 수 있습니다. |
| 커밋까지 맡길 때 | "main 에 직접 커밋하지 말고 작업 브랜치에서 해" 를 함께 적습니다. `AGENTS.md` 6장이 main 직접 커밋을 금지합니다. |
