# 인수인계: 2026-09-03 Wave I~P 종료 및 실환경 결함 발굴

> **작성일**: 2026-09-03
> **Run**: `run_971584ddb4a0` (계속 사용하십시오. 새 Run 을 만들지 마십시오)
> **기준 HEAD**: `41c46df` (`main`)
> **코디네이터**: Claude Opus 5
> **이전 인수인계**: [`handoff_20260903_wave_h_close.md`](handoff_20260903_wave_h_close.md)

---

## 1. 다음 세션이 먼저 할 일

```bash
git -C <repo> log --oneline -1                       # 41c46df 여야 합니다
git branch --list "fix/*"                            # 미병합 4개가 보여야 합니다
uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg
python3 scripts/orca_skill_receipt.py issue
python3 scripts/validate_agent_rules.py              # 20/20 여야 합니다
docker compose ps                                    # 스택 가동 여부 확인
```

**이번 세션에서 검사가 19 에서 20 건으로 늘었습니다.** 19/20 이 나오면 `source_commit`
갱신이 필요한 것입니다.

---

## 2. 최우선 과업: 미병합 브랜치 5개

**전부 커밋과 검증을 마쳤고 병합만 남았습니다.** 순서를 지키십시오.

| 순서 | 브랜치 | 내용 | 상태 |
| ---: | --- | --- | --- |
| 1 | `fix/test-rate-limit-isolation` | 테스트 격리 (**나머지의 선행조건**) | 전량 테스트 38% 까지 **실패 0건** 확인 후 중단 |
| 2 | `fix/runtime-libgomp` | 모델 5개 로드 복구 | 실측 검증 완료 |
| 3 | `fix/chatbot-feature-parity` | 챗봇 train/serve skew 제거 | 실측 검증 완료 |
| 4 | `fix/home-swipe-on-desktop` | 홈 화면 3건 | 브라우저 실측 완료 |
| 5 | `kwanbum217/orca-p1` | 수집 catch-up | **Level 1 전 항목 통과** |

**1번이 먼저여야 합니다.** 그것 없이는 Redis 가 뜬 상태에서 어느 브랜치도 전량
테스트를 통과하지 못합니다. 로그인 관련 16건이 429 로 막힙니다.

각 브랜치마다 `git merge --no-ff main` -> `premerge_full_suite_gate.py --record`
-> `git merge --no-ff <branch>` 순서입니다. 게이트가 증거의 커밋 해시를 병합 대상과
대조하므로 건너뛸 수 없습니다.

`source_commit` 은 중간과 마지막에 각각 한 번씩 갱신하십시오. 5커밋 이상 뒤처지면
규칙 검증이 실패해 다음 병합이 막힙니다.

---

## 3. 이번 세션이 병합한 것

| 웨이브 | 내용 | 비고 |
| --- | --- | --- |
| I | G1 fail-closed, 승격 증거 결속, 운영 Compose egress | P0 3건 |
| J | 자동화 토큰 단일소비, PSI 윈도우, E2E DB 격리 | P1 3건 |
| K | Session 스레드 소유권, E2E Phase 2b, taskctl 런처 | 3건 |
| L | E2E Phase 3, 대형 모듈 분할, 경고 예산 | 3건 |
| M | E2E Phase 4, backup 분할, **Gemini 3.8 채택** | 3건 |
| N | 백업 fail-closed, 공급망 차단, 릴리스 자동화 | 3건 |
| O | OTel 계측, 복원 리허설 도구, CURRENT_STATE 정규화 | 3건 |
| P | 수집 catch-up | 미병합 |

GPT 감사 보고서(`refac_bid_box_보완점_재검토_20260903.md`)의 12개 항목 중
**착수 가능했던 것을 전부 처리**했습니다.

---

## 4. 실환경에서만 드러난 결함 8건

**이번 세션의 가장 큰 성과입니다.** Docker 스택을 실제로 띄우자 코드 검토로는
나오지 않던 결함이 연속으로 드러났습니다.

| # | 결함 | 왜 안 잡혔나 | 상태 |
| ---: | --- | --- | --- |
| 1 | `python3 scripts/backup_recovery.py` 가 `ModuleNotFoundError` | 테스트가 import 만 검증 | 병합됨 |
| 2 | `host=localhost` 라 포트 무시하고 유닉스 소켓 접속 | 컨테이너 DB 로 백업을 안 돌려 봄 | 병합됨 |
| 3 | 호스트 mysqldump 26.7 에 `mysql_native_password` 없음 | 호스트에서 백업을 안 해 봄 | 병합됨 |
| 4 | 운영 이미지가 3일 낡아 worker 기동 실패 | CI 는 항상 새로 빌드 | 재빌드로 해소 |
| 5 | **LightGBM 모델 4개 로드 실패** (`libgomp.so.1` 없음) | 호스트엔 Homebrew libomp 이 있음 | **미병합 2번** |
| 6 | **챗봇 특징 28개 누락** (train/serve skew) | 두 경로를 비교한 적 없음 | **미병합 3번** |
| 7 | **rate limit 테스트 오염** | Redis 없이 돌면 통과 | **미병합 1번** |
| 8 | 수집이 3주간 미실행 | 워커가 02:00 에 안 떠 있었음 | **미병합 5번** |

**공통 교훈**: 지금까지의 전량 테스트는 전부 **의존 서비스가 없는 조건**에서 돌았습니다.
7번이 그 증거입니다. Redis 가 fail-open 이라 없으면 카운트를 안 해 통과하고, 실제로
띄우자 16건이 한꺼번에 터졌습니다. **운영에는 항상 Redis 가 있으므로 그동안의
"3400 passed" 는 실제 조건을 반영하지 못했습니다.**

---

## 5. 결정이 필요한 것

### 5.1 병합 게이트와 실환경의 충돌

스택이 뜬 상태에서 전량 테스트가 **20~36분** 걸립니다(E2E 가 초반 2~3분 점유).
스택이 없으면 90초입니다. 병합할 브랜치가 5개라 회당 20분이면 100분입니다.

선택지 셋입니다. **실측값을 보고 정하십시오.**

| 방안 | 장점 | 단점 |
| --- | --- | --- |
| 스택 내리고 병합 | 회당 90초 | 검증 조건이 실제와 다름 (지금까지의 문제) |
| E2E 를 게이트에서 분리 | 일관된 시간. CI 에 이미 독립 Job 있음 | 로컬에서 E2E 회귀를 늦게 발견 |
| 그대로 진행 | 실제 조건 검증 | 100분 소요 |

### 5.2 미결정 항목

| 항목 | 막고 있는 것 |
| --- | --- |
| RPO/RTO 목표값 | 사용자 결정. **도구는 준비 완료** |
| 백업 암호화·오프사이트 | 보관 위치 결정 |
| 관측성 백엔드 + SLO·알람 | 스택 결정 (계측은 배선 완료, 기본 꺼짐) |
| Windows Docker Desktop | 장비 부재 |

---

## 6. 실복원 훈련 미완료

사용자 지시로 시작했으나 **개발 작업을 위해 중단**했습니다.

- 백업 도구 결함 3건을 고쳐 **이제 실행 가능한 상태**입니다
- DB 실측: **32.8GB** 중 `bid_announcements` 가 30.8GB
- 백업 진행률 실측: 19분에 1.3GB (압축), 78MB/분
- **추정 백업 소요 45~75분**, RTO 는 그보다 큼 (복원이 덤프보다 느림)
- 미완성 스냅샷 4개는 정리했습니다

**RPO 1시간 / RTO 1시간은 현재 구조로 달성 불가**임이 이 실측으로 드러났습니다.
논리 덤프 방식으로는 어렵고, 물리 백업이나 증분 또는 큰 테이블 분리가 필요합니다.

재개하려면 개발을 하지 않는 시간대(야간)를 권합니다. Docker 를 배타 점유합니다.

---

## 7. 이번 세션에서 확인한 함정

**전부 실측입니다. 재조사하지 마십시오.**

1. **`taskctl dispatch --terminal` 은 `--worktree` 를 무시합니다.** 내부적으로
   `dispatch --inject` 라 워크트리를 만들지도 옮기지도 않습니다. 워커가 주 저장소에서
   브랜치를 만들었습니다. **터미널은 만들 때부터 목표 워크트리에 만드십시오.**

2. **agy TUI 를 직접 띄우면 `Checking for updates` 에서 멈춥니다.** 인증 문제가
   아닙니다(`agy --print` 는 즉시 응답). 정본은 `orca_agy_launch.py` + preamble 주입이며,
   Wave M 부터 `taskctl dispatch --launcher` 로 자동화됐습니다.

3. **`or-free/minimax-m3` 는 `~/.kimi-openrouter-free` 프로필에만 있습니다.**
   런처 기본 프로필에는 없어 `--home` 지정이 필요합니다.

4. **전량 테스트를 두 개 동시에 돌리지 마십시오.** 같은 Redis 를 공유해 서로의
   rate limit 키를 지우고 CPU 도 나눠 씁니다. 21분을 쓰고 결과도 못 썼습니다.

5. **워커의 통과 수치를 믿지 마십시오.** 이번에도 계약 위반이 워커마다 하나씩
   나왔고 전부 코디네이터 diff 검토에서 발견됐습니다. 특히 무료 풀(cursor)이
   이동 중 docstring 한 단어를 바꿔 의미가 틀어졌습니다.

6. **상시 감시기는 `run_in_background` 로 띄우십시오.** `taskctl dispatch` 가
   기동하는 것은 분리 프로세스라 종료 코드가 코디네이터에게 도달하지 않습니다.
   이번 세션에서 세 번 놓쳤고 사용자가 먼저 지적했습니다.

7. **`check` 소진만으로는 메시지를 다 보지 못합니다.** `question` 과 `worker_done` 이
   `inbox` 에는 있는데 `check` 에는 안 나온 사례가 두 번입니다. **`check` 뒤에
   `inbox` 를 교차 확인하십시오.**

---

## 8. 정리 상태

- 활성 워커: **없음** (p1 회수 완료)
- git worktree: 주 저장소 + `orca-p1` (5번 병합 후 제거)
- 완료 세션 잔류: 없음
- Docker: **가동 중** (db, redis, meilisearch, app, worker)
- 실행 중이던 전량 테스트: 38% 까지 실패 0건 확인 후 중단 (프로세스 정리 완료)
- **앞서 429 로 실패하던 `test_login_fails_with_unknown_user` 가 PASSED 로 확인됐습니다.**
  격리 픽스처가 실제로 듣는다는 증거입니다. 다만 전량 완주 증거는 아직 없으므로
  1번 병합 전에 `premerge_full_suite_gate.py --record` 를 완주시켜야 합니다.
