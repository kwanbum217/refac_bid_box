# 코디네이터 인수인계 — Opus 5 에서 Grok 4.6 으로

> **작성일**: 2026-09-02
> **인계 HEAD**: `46a5ebd`
> **인계 사유**: Opus 5 의 5시간 토큰 사용량 95% 도달
> **Orca Run**: `run_971584ddb4a0` (계속 사용하십시오. 새 Run 을 만들지 마십시오)

---

## 1. 지금 당장 확인할 것

부트스트랩에서 아래를 **직접 실행해** 확인하십시오. 이 문서의 값도 작성 시점 기준이며 정본이 아닙니다.

```bash
git rev-parse --short HEAD && git branch --show-current
git status --short
git worktree list
python3 scripts/orca_taskctl.py status --run-id run_971584ddb4a0
python3 scripts/orca_worker_watch.py
python3 scripts/orca_settled_session_audit.py
gh run list --limit 1 --json headSha,status,conclusion
```

작성 시점 상태입니다.

| 항목 | 값 |
| --- | --- |
| HEAD | `46a5ebd` (= `origin/main`) |
| 전량 테스트 | 3,206 통과 / 0 실패 (CI 모사 환경) |
| 커버리지 | 85.86% (하한 80) |
| `make check-all` | 통과 |
| CI | `46a5ebd` 미실행. 직전 `03f11c6` 는 실행 중이었음 |

---

## 2. 활성 워커 — 인계 시점 진행 중

| 워크트리 | Task | 빌더 | 상태 |
| --- | --- | --- | --- |
| `g1-heartbeat` | `task_4962455374cc` | `gpt-5.6-luna` | Capsule 경합으로 Task 가 `failed` 종결됨. Capsule 재배치 후 터미널로 재지시했으나 커밋 없음. **재기동 판단 필요** |
| `g2-mysqlconc` | `task_bedb4b8bf44b` | `or-free/minimax-m3` | `dispatched`. 정상 진행 중 |
| `g4-image` | `task_c8e14bf8d6cd` | `gpt-5.6-luna` | **병합 완료**. 워크트리 회수만 남음 |

### 즉시 할 일

1. `g4-image` 워크트리와 브랜치를 회수하십시오. `git log --oneline main..kwanbum217/g4-image` 가 0 인 것을 먼저 확인하십시오.
2. `g1-heartbeat` 를 재기동할지 판단하십시오. Capsule 은 이미 배치돼 있습니다.
3. `g2-mysqlconc` 완료를 기다렸다가 검증하십시오.

---

## 2.5 인계되는 배경 작업과 감시기

### 상시 감시기

인계 시점에 `scripts/orca_worker_watch.py --watch` 를 하나 기동해 두었습니다. 워커별 커밋 수, 미커밋 수, 터미널 차단 신호를 감시합니다. 로그는 아래에 쌓입니다.

```
/var/folders/p1/7s1dlwjx1mq6727k1ry667nm0000gn/T/orca_worker_watch/
```

죽었으면 다시 띄우십시오. **종료 코드 1 은 사람 개입이 필요한 차단이 있다는 뜻이며, 그때는 조치 전에 다음 Task 를 Dispatch 하지 마십시오.**

```bash
python3 scripts/orca_worker_watch.py            # 1회 요약
nohup python3 scripts/orca_worker_watch.py --watch >/dev/null 2>&1 &
```

### 승인 감시기

살아 있는 워커 터미널마다 `scripts/orca_auto_approve.py` 가 하나씩 붙습니다. 인계 시점에는 `g2-mysqlconc` 워커용 하나만 남아 있습니다.

**닫힌 터미널의 감시기가 고아로 남습니다.** 인계 직전에 16개를 정리했습니다. 주기적으로 확인하십시오.

```bash
LIVE=$(orca terminal list 2>&1 | grep -oE "term_[a-f0-9-]+" | tr '\n' ' ')
ps aux | grep "[o]rca_auto_approve" | while read -r _ pid _; do
  t=$(ps -o command= -p $pid | grep -oE "term_[a-f0-9-]+")
  case "$LIVE" in *"$t"*) ;; *) echo "고아 $pid"; kill $pid;; esac
done
```

### 대기 중인 CI 두 건

인계 시점에 아직 결과가 안 나온 run 이 둘 있습니다. **반드시 확인하십시오.**

| HEAD | 내용 |
| --- | --- |
| `46a5ebd` | 이미지 강화와 codex 런처 |
| `1263629` | 인계 문서 |

`gh run view --log-failed` 는 run 이 완료돼야 동작합니다. Windows job 이 느려 대기가 깁니다.

```bash
gh run list --limit 3 --json headSha,status,conclusion
RID=$(gh run list --limit 3 --json databaseId,headSha --jq '.[] | select(.headSha|startswith("1263629")) | .databaseId')
gh run view $RID --json jobs --jq '.jobs[] | "\(.conclusion // .status)  \(.name)"'
```

### 정리된 임시 자원

인계 전에 제거했습니다. 다시 만들 필요는 없습니다.

- `py311repo` 워크트리 (py3.11 플레이키 재현용)
- `ci-mysql-repro` 컨테이너 (MySQL 오류 코드 실측용)
- `refac-bid-box:g4-verify` 이미지 (이미지 강화 검증용)
- 고아 승인 감시기 16개

**Docker 데몬은 켜 둔 상태입니다.** 이미지 빌드 검증과 MySQL 통합 테스트 재현에 필요합니다.

---

## 3. Orca Task 상태가 실제와 다릅니다

`taskctl status` 에 `[ready]` 로 남은 Task 다섯 개는 **이미 병합 완료된 것**입니다.

```
task_817dbd6a2a28  자동화 RBAC        병합됨
task_15b11c894c87  승격 게이트         병합됨
task_06a97b69bd4f  PSI 설계 조사       병합됨
task_1a63a0432aea  운영 compose        병합됨
task_085277f3ab30  G1 행 수 대조       병합됨
```

원인은 Antigravity, kimi, opencode 워커가 `worker-start` 를 쓸 수 없어 `dispatch --to --return-preamble` 비감독 경로로 띄웠기 때문입니다. 그 경로는 Orca 수명주기를 갱신하지 않습니다.

**Task 상태를 진행 판단 근거로 쓰지 마십시오.** git 커밋과 `main` 병합 여부가 정본입니다.

---

## 4. 이 세션에서 배운 함정

### 4.1 Codex Capsule 배치 경합 (해결됨)

`worker-start` 는 워크트리 생성과 워커 기동을 한 번에 합니다. 기동 뒤에 Capsule 을 복사하면 워커가 그 사이에 정본을 못 찾습니다. **이 하나로 워커 네 대가 계약 없이 작업했거나 멈췄습니다.**

반드시 이 런처를 쓰십시오.

```bash
uv run python scripts/orca_codex_launch.py --task <task_id> --name <워크트리명>
```

### 4.2 병합 전 검증은 세 가지를 모두 돌려야 합니다

하나라도 빠뜨리면 CI 에서 터집니다. 실제로 이 세션에서 세 번 겪었습니다.

```bash
make check-all                      # mypy 와 actionlint 가 여기 있습니다
uv run pytest -q -m "not data_assets" --cov=src --cov-fail-under=80 -p no:cacheprovider
python3 scripts/validate_agent_rules.py --quiet
```

**CI 환경을 모사해야 합니다.** 로컬에 Ollama 나 Redis 가 떠 있으면 결과가 달라집니다.

```bash
mv .env .env.bak
SECRET_KEY="test-only-secret-key-at-least-32-characters" MEILI_MASTER_KEY=y SKIP_MODEL_LOAD=true \
OLLAMA_BASE_URL="http://127.0.0.1:19999" REDIS_URL="redis://127.0.0.1:6399/0" \
uv run pytest -q -m "not data_assets" -p no:cacheprovider
mv .env.bak .env
```

`0295e3e` 에서 readiness 가 warmup 과 LLM 을 보게 되면서 CI 의 Test job 다섯 개가 실패했는데, 로컬에 Ollama 가 떠 있어 코디네이터와 워커와 게이트와 리뷰어가 **전부** 놓쳤습니다.

### 4.3 푸시 전에 `source_commit` 을 갱신하십시오

`c5c35f3` 에서 이 누락 하나로 CI job 여섯 개가 실패했습니다. `docs/context/CURRENT_STATE.md` 의 `source_commit` 이 HEAD 보다 5커밋 이상 뒤처지면 규칙 검증이 실패합니다.

### 4.4 워커가 쓴 값은 실측으로 확인하십시오

`9e48194` 에서 워커가 MySQL 오류 코드를 추정값 `1140` 으로 넣어 CI 가 실패했습니다. 실제는 `OperationalError` `1055` 입니다. **skip 되는 테스트는 값이 틀려도 드러나지 않습니다.**

로컬에서 MySQL 통합 테스트를 실제로 돌리는 방법입니다.

```bash
docker run -d --name ci-mysql -e MYSQL_ROOT_PASSWORD=testpassword \
  -e MYSQL_DATABASE=test_procurement_ngram -p 3399:3306 mysql:8.0
docker exec -i ci-mysql mysql -uroot -ptestpassword test_procurement_ngram < tests/fixtures/ngram_mysql_init.sql
MYSQL_TEST_URL="mysql+pymysql://root:testpassword@127.0.0.1:3399/test_procurement_ngram" \
  uv run pytest -m mysql_integration -q
```

### 4.5 벽시계 단언은 대비를 20배 이상 두십시오

`7d18005` 에서 readiness 타임아웃 테스트가 `0.1초 대 0.08초` 대비 때문에 CI 러너에서만 실패했습니다. 커버리지 계측이 오버헤드를 키운 것이 계기입니다.

### 4.6 kimi 프로필마다 등록 모델이 다릅니다

`or-free/minimax-m3` 는 `~/.kimi-openrouter-free` 에 있고 런처 기본 프로필에는 없습니다. `--home /Users/kwanbum/.kimi-openrouter-free` 를 붙이십시오.

---

## 5. 워커 풀 현황

| 풀 | 상태 |
| --- | --- |
| `gpt-5.6-luna` (codex) | **주력.** `worker-start` 감독 경로. 진행이 Orca 에 정상 기록됨 |
| Gemini (Antigravity) | 잔량 35%. **리뷰어에만 `medium` 등급으로** 쓰십시오 |
| qwen 계열 (Alibaba) | **2026-09-06 08:13 UTC 까지 할당량 소진.** deepseek, glm, qwen-max 포함 전부 |
| opencode | **배정 보류.** 한 과제에 9~14분. E3 에서 컨텍스트 15% 를 쓰고 산출물 0 |
| kimi `or-free/minimax-m3` | 쓰기 과제 1회 통과(F3). 풀에는 `investigator` 만 열려 있으나 명시 지정으로 builder 배정 가능 |
| kimi `or-free/nemotron-ultra` | 사용 가능. 가시성이 낮아 산출물 기준 점검 필요 |

`gpt-5.6-lunar` 는 존재하지 않는 모델입니다. `gpt-5.6-luna` 입니다.

### effort 판단

현재 `medium` 입니다. 이 세션에서 luna 실패 7건 중 **4건이 코디네이터의 Capsule 배치 실수**였고 그 원인은 제거됐습니다. 남은 모델 책임 2건은 커밋 없이 `worker_done` 전송과 적용 범위 협소입니다.

**Capsule 경합이 사라진 상태에서 3~4건을 관찰한 뒤 반려가 반복되면 그때 `high` 로 올리십시오.** 지금 올리면 원인 규명 없이 비용만 커집니다.

---

## 6. 보고서 진척 (2026-09-02 보완점 분석 기준)

### 해소 완료

| 항목 | 병합 |
| --- | --- |
| 2.1 대화 상태 IDOR + 익명 세션 키 | `0438db5`, `5a0ffb0` |
| 2.2 자동화 RBAC + 확인 토큰 | `b08e58f` |
| 2.3 승격 게이트 + served-version | `98f8291`, Wave E |
| 3.1 G1 스키마 서명 + 행 수 대조 | `94b7a6a`, Wave F |
| 3.2 백업 도구 + 정기 스케줄 | `8dcf80f`, Wave E |
| 3.3 재학습 category 필수화 | `cf5558e` |
| 3.4 Session rollback | Wave A |
| 3.5 인증 강화 + CSRF | Wave A, Wave F |
| 3.7 운영 compose + 이미지 강화 | `45f6621`, `7a8c7b9` |
| 3.8 RAG single-flight + readiness | Wave A |
| 3.9 PSI 연결 + 집단 분리 | Wave C, Wave D |
| 3.10 Servc 정책 + 서빙 + UI | `d4fe987`, Wave D |
| 4.1 CURRENT_STATE 모순 정정 | Wave P0 |
| 4.2 커버리지 게이트 + MySQL 통합 | Wave C, Wave F |
| 4.3 공급망 (SBOM, 스캔, digest) | Wave D |
| 4.4 버전 정본 단일화 | Wave D |

### 남은 것

| 항목 | 상태 |
| --- | --- |
| **3.6 Windows 실기** | **차단.** 장비 부재. 워커로 해결 불가 |
| 4.3 관측성 구현 | 조사 보고서만 있음. **스택 결정이 사용자 몫** |
| 3.8 Arq heartbeat | G1 진행 중 |
| 3.4 MySQL 동시성 테스트 | G2 진행 중 |
| 3.5 익명 API 쿼터 | Intent 준비됨 (`.orca/intents/wave_g/g3_anonymous_api_policy.yaml`) |
| 4.1 `CURRENT_STATE` 정규화 | **미착수.** 51KB 로 자체 규정 8,000자의 6배 |
| 3.2 RPO/RTO, restore drill | 도구만 있음. 값 미확정, 리허설 미수행 |
| 3.7 TLS ingress | 미착수 |
| 4.2 SSR 브라우저 E2E | 미착수 |

---

## 7. 4.1 은 코디네이터가 직접 하십시오

`docs/context/CURRENT_STATE.md` 정규화는 워커에 맡기지 마십시오. **코디네이터가 매 병합마다 그 파일을 갱신하므로 동시 편집이 충돌합니다.** 실제로 워커 하나가 그 파일을 건드려 커밋을 되돌린 적이 있습니다.

모든 웨이브가 끝난 뒤 직접 하십시오. 현재 구조는 1.5.1 부터 1.5.7 까지 웨이브별 절이 누적돼 있으니, 현재 상태만 남기고 나머지는 handoff 나 analysis 문서로 옮기면 됩니다.

---

## 8. 준비된 Intent

바로 쓸 수 있습니다. 전부 게이트 검증을 통과했습니다.

```
.orca/intents/wave_g/g1_worker_heartbeat.yaml       진행 중
.orca/intents/wave_g/g2_mysql_concurrency.yaml      진행 중
.orca/intents/wave_g/g3_anonymous_api_policy.yaml   대기
.orca/intents/wave_g/g4_image_hardening.yaml        완료
```

---

## 9. Capsule 작성에서 효과가 있었던 것

이 세션에서 반려 없이 한 번에 통과한 Task 는 공통점이 있었습니다.

1. **대상을 파일과 행 번호로 열거**했습니다. "SSR 폼에 검증을 걸라" 는 워커가 셋 중 하나만 잡았고, "378행 signup, 450행 login, 528행 logout" 이라고 적었으면 안 놓쳤을 것입니다.
2. **금지 항목에 이유를 붙였습니다.** "readiness 에 결합하지 말라" 보다 "워커가 죽어도 API 는 요청을 처리하므로 readiness 를 흔들면 컨테이너가 재시작 루프에 빠진다" 가 지켜졌습니다.
3. **범위 밖이지만 필요할 것을 미리 `escalate_when` 에 적었습니다.** 워커가 그 조건에 정확히 걸려 물어온 사례가 둘 있습니다.
4. **이미 확인한 사실에 "재조사 불필요" 를 붙였습니다.** 워커가 같은 조사를 반복하지 않습니다.
5. **리뷰 체크리스트에 이모지와 링크 항목을 넣었습니다.** 넣기 전에는 이모지 위반 두 건이 리뷰어를 통과했습니다.

---

## 10. 인계자가 남기는 판단

- **Task 상태보다 git 을 믿으십시오.** 비감독 경로 때문에 Orca 기록이 실제와 어긋납니다.
- **워커 보고 수치를 재실행으로 확인하십시오.** Level 1 게이트가 보고와 실측 불일치를 세 번 잡았습니다.
- **리뷰어도 틀립니다.** 이 세션 결함 중 상당수가 리뷰어 `pass` 이후 코디네이터 검토에서 나왔습니다. 반대로 리뷰어가 코디네이터의 Capsule 범위 누락을 잡은 적도 한 번 있습니다.
- **`gh run view --log-failed` 는 run 이 완료돼야 동작합니다.** Windows job 이 느려서 로그를 못 받는 경우가 잦습니다.
