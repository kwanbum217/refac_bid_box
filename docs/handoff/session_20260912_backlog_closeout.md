# 세션 인수인계: 2026-09-12 정합성 보고서 잔여 과업 종결

> **작성일**: 2026-09-12
> **작성자**: Claude Opus 5 (코디네이터)
> **기준 커밋**: `84b8a0d6`
> **이어받은 문서**: [`docs/handoff/session_20260912_wave_y_close.md`](session_20260912_wave_y_close.md)

---

## 1. 한 줄 요약

2026-09-11 정합성 분석 보고서의 **모든 항목이 종결**됐습니다. 8장 권고 14개는 Wave W/X/Y 로,
권고 목록 밖 2건(6.6 스킬 3중 미러링, 6.7 개발 compose 관측성)과 세션 중 발견한 자동 승인기
탐지 결함은 이 세션에서 처리했습니다. `main` 은 `84b8a0d6` 이며 원격까지 반영했습니다.

---

## 2. 이 세션의 병합 내역

| 커밋 | 내용 | 전량 테스트 |
| --- | --- | --- |
| `10ab9eb3` | npm `--prefix`/`run` 자동 승인 확장 | 4,616건 |
| `f82f0c61` | 운영 도구 3종 개별 커버리지 게이트 (Wave Y2) | 4,605건 |
| `1c990c28` | 커버리지 재현 테스트의 환경 의존 제거 | 4,619건 |
| `6e7bc2e3` | Wave Y 마무리 인수인계 문서 | 4,619건 |
| `afb444ec` | 챗봇 템플릿 인라인 JS 분리 (Wave Y3, 권고 12) | 4,624건 + E2E |
| `8f74dfec` | 승인 대화창 확인 문구 목록화 | 4,620건 |
| `4dc30734` | 스킬 미러 복제 도구 (6.6) | 4,628건 |
| `84b8a0d6` | 개발 관측성 프로파일 (6.7) | 4,637건 |

---

## 3. 6.6 스킬 3중 미러링

**선택한 방식은 생성 스크립트 + 기존 게이트이며, 중복 자체는 의도적으로 유지했습니다.**

| 항목 | 내용 |
| --- | --- |
| `scripts/sync_skill_mirrors.py` | 정본 `.agents/skills` → `.claude/skills`, `.opencode/skills` 복제 |
| `--check` | 복제하지 않고 어긋남만 보고. 어긋나면 종료 코드 1, 정본 부재는 2 |
| `make sync-skills` | 같은 동작. 쓰기 동작이라 `check-all` 에는 넣지 않았습니다 |
| `tests/test_sync_skill_mirrors.py` | 8건. 내용 상이·누락·잔여 감지, `--check` 무변경, 빈 디렉터리 정리 |

**심볼릭 링크로 통합하지 않은 이유는 G2 입니다.** Windows 의 Git 은 `core.symlinks` 와
권한이 갖춰지지 않으면 링크를 텍스트 파일로 체크아웃하므로 각 CLI 의 스킬 탐색이 오류 없이
조용히 깨집니다. 저장소에 추적되는 심볼릭 링크는 현재 0건이며 그 방침을 유지했습니다.
따라서 **추적 파일 36개와 408K 중복은 그대로입니다.** 목표는 중복 제거가 아니라 스킬 하나를
고칠 때 세 곳을 손으로 맞추는 작업의 제거였습니다. 디스크·파일 수 감축이 필요해지면 남은
선택지는 링크 통합(Windows 실기 검증 후)이나 CLI 설정으로 정본을 직접 가리키는 방식입니다.

`validate_agent_rules.py` 검사 5 는 종전대로 미러 동일성을 커밋 시점에 강제하며, 실패
메시지가 이제 복제 명령을 가리킵니다. pre-commit 에 별도 `--check` 훅은 넣지 않았습니다.
같은 어긋남을 이미 검사 5 가 막으므로 중복입니다.

---

## 4. 6.7 개발 compose 관측성

`otel-collector`, `tempo`, `prometheus`, `grafana` 를 `profiles: ["observability"]` 로
추가했습니다. 저장소가 이미 `frontend` 에 `profiles: ["legacy"]` 를 쓰고 있어 같은 관례입니다.

```bash
make observability-up      # docker compose --profile observability up -d
make observability-down
```

| 구분 | 서비스 |
| --- | --- |
| 기본 `docker compose up` | `app`, `worker`, `db`, `redis`, `meilisearch` (5개, 변화 없음) |
| `--profile observability` | 위 5개 + `otel-collector`, `tempo`, `prometheus`, `grafana` |

호스트 포트는 4317·4318(OTLP), 9090(Prometheus), 3000(Grafana)입니다. 앱에서 추적을 내보내려면
`.env` 에 `OTEL_ENABLED=true`, `OTEL_EXPORTER_TYPE=otlp`,
`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces` 를 두십시오. 엔드포인트를
`localhost` 로 두면 앱 컨테이너 자신을 가리켜 아무것도 도착하지 않습니다.

**`alertmanager` 는 개발에서 제외했습니다.** `docker/alertmanager.yml:25` 가
`api_url_file: /etc/alertmanager/secrets/slack_url` 을 요구하는 운영 호출 경로이며 로컬에는
호출할 대상이 없습니다. 대신 `alerting` 블록을 남기면 Prometheus 가 없는 호스트를 계속 조회해
오류 로그를 쌓으므로, 그 블록만 없는 `docker/prometheus.dev.yml` 을 따로 두었습니다. 두 설정의
스크랩 대상과 규칙 파일 동일성은 `tests/test_observability_dev_stack.py` 가 검사합니다. 같은
테스트가 **기본 기동 서비스 집합이 늘어나는 것도 막습니다.**

### 4.1 미검증 항목

**실제 컨테이너 기동은 확인하지 못했습니다.** 작업 시점에 이 장비의 Docker 데몬이 내려가
있었습니다(`Cannot connect to the Docker daemon`). `docker compose config -q` 는 프로파일
포함·미포함 모두 통과했으나, 이미지 4개 내려받기와 포트 4개 점유가 따르는 동작이라 데몬을
임의로 띄우지 않았습니다. **다음 세션에서 Docker 를 켠 뒤 `make observability-up` 을 한 번
돌려 컨테이너 상태와 Grafana 의 Prometheus·Tempo 데이터소스 연결을 확인하십시오.**

---

## 5. 자동 승인기 탐지 결함 (세션 중 발견)

전임 인수인계 5.2·5.3 절은 감시기가 "화면 끝부분만 검사해서" 놓친다고 적었으나 **원인이
달랐습니다.** `pending_command()` 가 확인 문구로 `"Do you want to proceed?"` 만 인정했고
현재 Antigravity 빌드는 `"Run this command?"` 를 씁니다. 그래서 판정기가 `approve` 로 판단하는
읽기 전용 조사 명령까지 대화창이 탐지되지 않아 워커가 멈췄고, 감시기 로그는 빈 파일로 남았습니다.

`CONFIRM_PHRASES` 목록으로 바꾸고 매칭된 문구로 본문 끝 경계를 자르게 했으며,
`orca_worker_watch.py` 의 차단 신호 표에도 같은 문구를 추가했습니다. **승인 규칙
(`classify_command`)은 바꾸지 않았습니다.** 무엇을 승인할지는 그대로이고 대화창을 알아보는
부분만 고쳤습니다.

**진단 교훈**: 감시기 로그가 **빈 파일**이면 "승인할 것이 없었다" 가 아니라 "대화창을 탐지하지
못했다" 일 수 있습니다. 워커가 멈춰 있는데 로그가 비어 있으면 탐지 실패를 먼저 의심하십시오.

이 수정은 단위 테스트로만 검증했습니다. **실제 Antigravity 워커에서 자동 승인이 되는지는
다음 워커 기동 때 확인해야 합니다.** 감시기 로그에 승인 기록이 남는지 보면 됩니다.

---

## 6. Wave Y3 에서 워커 산출물을 반려한 근거

빌더 보고를 그대로 받지 않고 코디네이터가 실측해 네 건을 잡았습니다. 다음 세션도 같은 방식을
유지하십시오.

| 항목 | 보고 | 실측 |
| --- | --- | --- |
| eslint 배선 | "0에러 통과" | `-f json` 결과가 **빈 배열**. 검사된 파일이 0개 |
| lint 범위 | 명시 없음 | 8개 → 7개로 축소. 설정 파일 2개 누락 |
| `make quality` | 통과 | **배경 실행**으로 결과를 읽지 않음 (Capsule 위반) |
| 커밋 | 완료 | `ignores` 변경이 **미커밋** 상태로 `worker_done` 전송 |

**판정 기준을 하나 남깁니다.** 린터 배선이 실제로 동작하는지는 "오류 0건" 으로 판단할 수
없습니다. `-f json` 결과 배열에 그 파일 항목이 있는지로만 판단하십시오. 검사되지 않은 파일은
항목 자체가 없습니다.

---

## 7. 다음 착수 순서

| 순서 | 작업 | 비고 |
| :---: | --- | --- |
| 1 | 관측성 스택 실기동 확인 | 4.1. Docker 켠 뒤 `make observability-up` |
| 2 | 자동 승인 실동작 확인 | 5장. 다음 Antigravity 워커 기동 시 감시기 로그 확인 |
| 3 | Windows 실기 검증 | G2 컷오버의 유일한 잔여 조건. 장비 부재로 보류 |

`kwanbum217/orca-r15-verify` 브랜치는 다른 세션 소유라 이 세션에서 건드리지 않았습니다.

---

## 8. 자원 정리 상태

| 대상 | 상태 |
| --- | --- |
| 워크트리 | 주 저장소만 남김. Wave Y·작업용 워크트리 5개 제거 |
| 브랜치 | `main` 과 다른 세션 소유 `kwanbum217/orca-r15-verify` 뿐 |
| Orca Run `run_ad5f13923f5a` | Task 7건 전부 `completed`. 잔류 세션 없음 |
| 워커 터미널 | 5대 전부 `worker-release` 후 종료 |
| 원격 | `origin/main` = `84b8a0d6`, 미푸시 0 |

**워크트리 기본 터미널은 닫아도 재생성됩니다.** 이번 세션에서 핸들이 바뀌어 되살아나는 것을
확인했습니다. 워커 세션 회수와 다른 창이며, 없애는 방법은 그 워크트리를 제거하는 것뿐입니다.
회수 감사 도구가 잡지 못하므로 `orca terminal list` 로 직접 확인하십시오.
