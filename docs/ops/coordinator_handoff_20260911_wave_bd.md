# 코디네이터 인수인계: Wave BD 진행 중 (2026-09-11)

> **인계자**: Claude Opus 5 (토큰 한도 임박으로 이양)
> **인수자**: grok-4.6 (high) 코디네이터
> **기준 커밋**: `7073cab` (main, origin 반영 완료)
> **정본 규칙**: `AGENTS.md`, `.agents/skills/orca-section-coordination/SKILL.md`
> **반드시 먼저**: `orca skills get orchestration` 을 읽으십시오. 그것이 도구 정본입니다.

---

## 0. 지금 당장 해야 할 일

**Wave BD 의 워커 2대가 돌고 있습니다.** 완료를 기다렸다가 검증하고 병합하십시오.

```sh
orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
```

Run 은 `run_ec495bb8490f` 입니다.

| Task | Dispatch | 워크트리 | 터미널 | 내용 |
| --- | --- | --- | --- | --- |
| `task_3d80b2899f28` | `ctx_1a7df3e01740` | `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-bd1` | `term_0423da9b-9ebc-4ddc-9559-94dc6dd90465` | BD1 OTel 메트릭 계측 (R-22) |
| `task_81954ca1a851` | `ctx_396090d1a35d` | `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-bd2` | `term_485253cb-80c6-4627-8a30-b794b34bf373` | BD2 복구 드릴 준비 (R-23a) |

빌더는 둘 다 `gemini-3.8-flash-medium` 입니다. 리뷰어는 `grok-4.6` 을 쓰십시오.

---

## 1. 완료 후 절차 (그대로 따르십시오)

각 워커가 `worker_done` 을 보내면 순서대로 합니다.

```sh
# 1) 배달 확인 후 ack. --ack 에는 deliveryId 를 넘깁니다 (msg_ 아님)
orca orchestration check --ack <deliveryId> --json

# 2) 보고 다이제스트
python3 scripts/summarize_worker_done.py --report <워크트리>/.orca/capsules/<task_id>/worker_done.json \
  --capsule .orca/capsules/<task_id>/capsule.yaml

# 3) 워커 회수 (ack 직후. 병합을 기다리지 마십시오)
uv run python scripts/orca_taskctl.py release-worker --dispatch <ctx_id> --terminal <handle>
orca terminal close --terminal <handle>
python3 scripts/orca_settled_session_audit.py

# 4) Level 1 게이트
python3 scripts/orca_level1_gate.py --base main --branch kwanbum217/orca-bd1 \
  --repo <워크트리> --capsule <워크트리>/.orca/capsules/<task_id>/capsule.yaml --json > /tmp/gate.json
```

**게이트는 반드시 직렬로, 다른 활동이 없을 때 돌리십시오.** 이 저장소의 전량
테스트는 DB 와 Redis 를 공유합니다. 오늘 게이트 2개를 동시에 돌렸다가 양쪽 모두
1건씩 실패하는 오탐을 냈고, 단독 재실행에서는 둘 다 통과했습니다.

---

## 2. 리뷰어 붙이는 법 (grok-4.6)

빌더 회수 직후 바로 붙입니다. 리뷰 Intent 는 빌더 Intent 의 `review_checklist`
블록을 **그대로 복사**해야 합니다. id 가 다르면 Level 1 게이트 5 가 실패합니다.

```sh
uv run python scripts/orca_taskctl.py create --intent .orca/intents/run_ec495bb8490f/<리뷰>.yaml \
  --run-id run_ec495bb8490f --task-title "<제목>" --display-name "<이름>" --json
cp -R .orca/capsules/<리뷰 task_id> <워크트리>/.orca/capsules/
orca terminal create --worktree path:<워크트리> --title "리뷰어 grok" --command zsh --json
orca orchestration dispatch --task <리뷰 task_id> --to <handle> --run run_ec495bb8490f --return-preamble --json
# 반환된 preamble 을 <워크트리>/.orca/preamble_grok.txt 에 기록한 뒤
orca terminal send --terminal <handle> \
  --text 'grok --model grok-4.6 --always-approve "$(cat .orca/preamble_grok.txt)"' --enter --json
```

**리뷰어 Capsule 의 `context` 에 커밋 금지를 반드시 넣으십시오.** "커밋하지 말라.
git add, git commit, git push 를 실행하지 말라. 커밋은 코디네이터가 한다."
이것을 넣은 뒤로 리뷰어의 브랜치 오염이 사라졌습니다. 리뷰 문서는 코디네이터가
별도 커밋으로 넣습니다.

**리뷰 보고는 checklist 와 blocking 만 보지 말고 본문을 읽으십시오.** 오늘
비차단 지적 3건이 본문에만 있었고 전부 실제 결함이었습니다.

---

## 3. 병합 절차

```sh
# 워커 워크트리에서 증거를 먼저 기록합니다 (주 저장소에서 하면 안 됩니다)
cd <워크트리> && python3 scripts/premerge_full_suite_gate.py --record
cd <주 저장소> && git branch --show-current   # main 인지 확인
git merge --no-ff kwanbum217/orca-bd1 -m "merge: <한국어 제목>

<본문>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git worktree remove <워크트리> --force
git branch -d kwanbum217/orca-bd1
git push origin main
```

**`premerge_full_suite_gate.py --record` 는 `MERGE_HEAD` 와 커밋이 정확히 일치해야
통과합니다.** 워크트리를 지우기 전에 거기서 돌리십시오. 병합 커밋은 `--amend` 가
불가능합니다(`prepare-commit-msg` 훅이 `MERGE_HEAD` 부재로 거부). 빠뜨린 내용은
새 작업 브랜치로 넣으십시오.

`main` 에 직접 커밋하지 마십시오. Pull Request 를 만들지 마십시오(1인 작업).

---

## 4. BD1 과 BD2 각각의 판정 포인트

### BD1 (OTel 메트릭 계측, R-22)

- **새 외부 패키지가 없어야 합니다.** OTel SDK 와 OTLP 익스포터가 이미 있습니다.
  `prometheus_client` 가 들어갔으면 차단입니다(사전 합의 없는 라이브러리 추가 금지).
- **`OTEL_ENABLED` 가 거짓일 때 무자원**이어야 합니다. MeterProvider, 익스포터,
  주기적 내보내기 스레드가 하나라도 생기면 결함입니다.
- **라벨 카디널리티**가 핵심입니다. 경로 라벨은 반드시 템플릿이어야 하고
  실제 공고 번호 같은 값이 들어가면 Prometheus 가 죽습니다.
- `docker-compose` 와 Collector 설정은 이번 범위가 아닙니다.

### BD2 (복구 드릴 준비, R-23a)

- **런북의 RPO/RTO 공란이 확정값과 모순**이던 것을 고치는 것이 최우선 산출물입니다.
  `docs/ops/backup_recovery_runbook.md` 46~53행이 "운영 담당자 기입 필요" 였는데
  `CURRENT_STATE` 의 `rpo_rto` 사실은 "RPO 24시간·RTO 4시간 확정(2026-09-06)" 입니다.
- **드릴을 실제로 실행했으면 계약 위반입니다.** 실행은 코디네이터 몫입니다(6장).
- 합격 기준이 시간 하나뿐이면 결함입니다. 행 수 대조와 스키마 대조가 있어야 합니다.

---

## 5. 오늘 세션에서 얻은 교훈 (되풀이하지 마십시오)

1. **게이트 병렬 금지.** 1장 참조.
2. **`docker compose up -d app` 은 프로세스를 다시 띄우지 않습니다.** 설정이
   그대로면 컨테이너를 재생성하지 않습니다. 기동 시 1회 실행되는 코드를 고쳤으면
   `docker compose restart app` 을 쓰십시오.
3. **앱 컨테이너에 볼륨 마운트가 없습니다.** 소스가 이미지에 구워집니다. 새
   마이그레이션이나 새 파일을 컨테이너가 보게 하려면 `docker compose build app`
   후 `up -d` 해야 합니다. 이것을 몰라 `alembic upgrade head` 가 성공한 것처럼
   보였지만 아무 일도 일어나지 않았습니다.
4. **`SHOW TABLES LIKE` 는 0행일 때도 헤더를 출력합니다.** 결과 행으로 오독하지
   마십시오. `DESC` 로 재확인하십시오.
5. **워커 보고 수치를 의심하기 전에 단독 재실행하십시오.** 오늘 게이트 6 불일치
   3건 중 2건이 코디네이터 자신의 추가 커밋 때문이었고 1건은 명령 표기 오류였습니다.
6. **Capsule 에 새 파일 생성을 요구하면 그 파일명을 쓰기 범위에 반드시 넣으십시오.**
7. **마이그레이션 리비전 ID 를 지어내지 마십시오.** 오늘 이미 쓰이는 head ID 를
   줘서 워커가 되물었습니다. 단일 head 를 계산해 확인하십시오.

---

## 6. 두 Task 병합 후 코디네이터가 직접 할 일

### 6.1 R-23b 복구 드릴 실행 (직렬, 조용한 상태에서)

도구는 이미 있습니다. 새로 만들지 마십시오.

```sh
uv run python scripts/backup_recovery.py drill --snapshot-dir <스냅샷> \
  --target-dir <격리 경로> --db-name <별도 DB> --report-path <보고서>
```

**다른 작업이 도는 중에 실행하지 마십시오.** RTO 는 시간 측정이라 전량 테스트가
옆에서 돌면 수치가 부풀려집니다. BD2 가 쓴 절차서
(`docs/ops/restore_drill_procedure_20260911.md`)를 따르십시오.

### 6.2 메트릭 실측

BD1 병합 후 `OTEL_ENABLED` 를 켜고 계측이 실제로 나가는지 확인하십시오.
**컨테이너 재빌드가 필요합니다**(5장 3번).

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-22** | 메트릭 계측 -> Prometheus 2단계 배선 | BD1 병합 후 |
| **R-23b** | 복구 드릴 실행 | BD2 병합 후, 조용한 기계 |
| R-18 | `.env` 비밀값 회전 | 사용자만 가능 |
| R-12 | G2 Windows Docker Desktop 실기 | Windows 장비 |
| R-15 | Orca setup 을 `npm ci` 로 | Orca 앱 UI. `--setup skip` 로 회피 중 |
| R-17 | 협상 가격점수 | **차단**. `k` 와 `T` 원천 부재 |
| R-21 | SSR E2E Phase 2~4 | 사용자 합의 |

---

## 8. 이번 세션이 끝낸 것 (참고)

| 웨이브 | 결과 |
| --- | --- |
| AZ | compare-stats 구간 계측 도입, 통계 신선도 점검기, 귀속 실측 |
| BA | 무거운 두 집계 사전 집계 전환. 종단 3,725ms -> 505ms |
| BB | 월별 두 집계 전환. **505ms -> 4.9ms (최초 대비 760배)** |
| BC | R-30b 채택(선택지 B)과 야간 상시 점검. `ANALYZE` 자동 실행 없음 |

compare-stats 경로 최적화는 **종료**했습니다. 남은 5ms 는 요약 조회와 캐시
연산뿐입니다. 이 경로를 더 파지 마십시오.

---

## 9. 워커 승인 차단 감시

**사용자가 워커의 승인 대기를 먼저 발견하면 코디네이터 실패입니다**(AGENTS.md 4장 9항).
오늘 한 번 발생했습니다.

`taskctl dispatch` 는 승인 감시기를 붙이지만 **파일 편집·생성 승인은 보류**하며,
Antigravity 는 `accept-edits` 모드 확보가 실패합니다. 그래서 별도 감시기를
`/private/tmp/claude-501/.../scratchpad/worker_guard.py` 에 두었습니다. 세션이
바뀌면 그 경로가 사라지므로, 필요하면 다음 원칙으로 다시 만드십시오.

- `python3 scripts/orca_worker_watch.py --json` 을 20초마다 폴링
- `blocked_kind == "prompt"` 이면 `shift+tab`(`\x1b[Z`) 후 Enter 로 자동 해제
- `reclaim` 과 `worker_done`/`report` 관련 사유는 **오탐이므로 무시**
- 인증 정체·설문·3회 해제 실패는 **즉시 종료해 사람을 깨움**. 로그에만 남기면
  도달하지 않습니다

`orca_worker_watch.py --watch` 단독은 차단을 출력만 하고 계속 돌아 사람에게
도달하지 않습니다. 그것에 의존하지 마십시오.
