# 인수인계: Wave I 선행 3건 워커 기동과 런처 승인 결함 시정 (2026-08-31)

> **작성일**: 2026-08-31
> **Run**: `run_428567a2da1f`
> **다음 코디네이터**: Codex `gpt-5.6-terra` effort `medium` (Claude 5시간 한도 92% 소진으로 이양)
> **이전 인수인계**: [`handoff_20260831_wave_gh.md`](handoff_20260831_wave_gh.md)
> **기준 커밋**: `4cb6514`

---

## 0. 21:35 KST 종료 갱신 (Codex 코디네이터)

이 절이 아래 인계 시점 기록보다 우선합니다. `main` 기준 커밋은 `d466ec6`이며 규칙
검증은 16/16 통과 상태입니다.

| 작업 | 최종 상태 | 다음 조치 |
| --- | --- | --- |
| I-A | 검증·병합·회수 완료 | 없음 |
| I-B | 검증·병합·회수 완료 | 없음 |
| I-C | Qwen 리뷰 `citations_wrong`으로 반려, 브랜치 `kwanbum217/orca-i-c`의 `9210641` 보존 | 필요할 때 새 Task로 재작업 |
| I-D | `agy --mode accept-edits` 선점 기동 검증·병합·회수 완료 | 없음 |
| I-E | `CURRENT_STATE` 갱신 병합 완료 | Run Task 상태 정리 필요 |
| I-G | 격리 MySQL 8 ngram CI, Qwen 독립 리뷰·전체 2,924 테스트 통과 후 병합·회수 완료 | 원격 CI 확인 |
| I-F | 브랜치 `kwanbum217/orca-i-f`, 커밋 `f9184f5`; 대상 261건·전체 2,946건·규칙 16/16·Ruff 통과. Qwen 내용 판정은 결함 0건이나 50,000자 diff 절단으로 finalize가 fail-closed 거부 | `finalize --max-diff-chars 120000 --reviewer-model qwen3.7-plus`로 재검증 후에만 병합 |
| I-H | 브랜치 `kwanbum217/orca-i-h`, 커밋 `d8aa9a9`; `worker_done` 수신, 단위 18건·규칙 16/16 보고. 독립 리뷰 미실행 | I-F와 동시에 리뷰하지 말고 Qwen finalize 후 병합 판단 |

I-F 재검증 경로는 다음과 같습니다.

```bash
python3 scripts/orca_taskctl.py finalize \
  --report /Users/kwanbum/orca/workspaces/refac_bid_box/orca-i-f/.orca/capsules/task_22541627a79a/worker_done.json \
  --capsule /Users/kwanbum/orca/workspaces/refac_bid_box/orca-i-f/.orca/capsules/task_i_f_contract_enforcement/capsule.yaml \
  --repo /Users/kwanbum/orca/workspaces/refac_bid_box/orca-i-f \
  --base main --branch kwanbum217/orca-i-f --reviewer \
  --reviewer-model qwen3.7-plus --max-diff-chars 120000
```

I-H는 I-G 병합 뒤의 `main`에 rebase한 후 보고 커밋을 갱신하고 finalize하는 편이 안전합니다.
두 워커 모두 종료 시점에는 커밋 1개, 미커밋 0개였습니다. 운영 FULLTEXT 인덱스와
기능 플래그 활성화는 계속 사용자 승인 전 보류입니다. Docker 컨테이너는 종료 점검 시
실행 중인 것이 없었습니다.

GPT 감사 항목은 전부 완료된 상태가 아닙니다. 이번 회차는 모델 정책 문서 정합성,
CURRENT_STATE 모순, 분석 수치 자동 검산, 승인 선점, 격리 MySQL CI를 닫거나 보강했습니다.
I-F 계약 강제는 재검증 대기이며, ngram 기능의 운영 활성화·운영 인덱스·canonical 재측정과
Windows Docker Desktop 실기는 남아 있습니다.

---

## 1. 지금 돌고 있는 것 (인계 시점 활성)

워커 3대가 Dispatch 되어 작업 중입니다. **아직 아무도 커밋하지 않았습니다.**

| Task | 내용 | 모델 | 워크트리 / 브랜치 | 터미널 |
| --- | --- | --- | --- | --- |
| `task_92717a9a5e22` | I-A 리뷰어 diff 상한 기본값 정정 | `qwen3.7-plus` | `orca-i-a` / `kwanbum217/orca-i-a` | `term_1aa8d821-f58d-4962-8266-c6435a03b8ee` |
| `task_f494424ee328` | I-B 분석 문서 수치 자동 생성기 | `claude-sonnet-4-6` (Antigravity) | `orca-i-b` / `kwanbum217/orca-i-b` | `term_fd4ae30c-57f4-4039-81e9-a6f0fec65a51` |
| `task_50768bf0d9de` | I-C qwen 리뷰어 JSON 실패 조사 (읽기 전용) | kimi `or-free/minimax-m3` | `orca-i-c` / `kwanbum217/orca-i-c` | `term_e55d8693-4f99-45e1-9801-25ac6f1ba7aa` |

Intent 정본은 `.orca/intents/run_428567a2da1f/` 에 있습니다.

**감시 명령**:

```bash
python3 scripts/orca_worker_watch.py     # 종료 코드 1 이면 사람 개입 필요
```

`worker_done` 이 나오면 표준 경로로 검증하십시오.

```bash
python3 scripts/orca_taskctl.py finalize --task <task_id> --reviewer
```

---

## 2. 모델 배정 근거 (WORKER_MODEL_NOTICE)

Antigravity Gemini 5시간 잔량이 28% 뿐이라 `TIER_POLICY` 기본값(builder = `gemini-flash-medium`)을
벗어났습니다. 기본값 복귀 시점은 Gemini 할당량 리셋 후입니다.

| Task | 기본값 | 실제 | 사유 |
| --- | --- | --- | --- |
| I-A | `gemini-flash-medium` | `qwen3.7-plus` | Alibaba Token Plan 은 별도 예산 |
| I-B | `gemini-flash-medium` | `claude-sonnet-4-6` | Antigravity Claude 별도 한도, 판정 품질 필요 |
| I-C | `gemini-flash-low` | kimi `or-free/minimax-m3` | 읽기 전용 무료 풀. 동시 쓰기 상한 미포함 |

**리뷰어는 빌더와 계열이 달라야 합니다.** I-A 는 qwen 이 빌더이므로 리뷰어를 qwen 으로
두지 마십시오. I-B 는 claude 가 빌더이므로 리뷰어를 claude 로 두지 마십시오.
**리뷰어를 동시에 두 개 이상 띄우지 마십시오.**

`cursor` 는 이번에도 배제했습니다. 무료 등급에서 named model 이 차단됩니다.

---

## 3. 이번에 시정한 결함: 런처 승인 자동화가 항상 죽고 있었다

**병합 `4cb6514`.** Wave H3 로 승인 자동화를 세 런처에 이식했는데, agy 런처 경로가
실제로는 한 번도 동작하지 않았습니다.

```
common.run_permission_setup_child 는 acquire_fn 에 cli_type 과 launcher 를 항상 키워드로 넘김
  -> agy 런처가 acquire_fn 으로 건네는 자기 래퍼가 그 둘을 받지 않음
  -> TypeError 로 자식 즉시 사망
  -> 부모는 이미 exec 로 사라진 뒤라 실패가 어느 화면에도 남지 않음
  -> 워커는 신뢰 대화창에서 그대로 정지
```

`.orca/permission_setup.log` 에만 traceback 이 남습니다. **승인 문제를 만나면 그 로그를
먼저 보십시오.** 화면에는 아무 단서가 없습니다.

`scripts/orca_agy_launch.py:75` 의 래퍼가 두 키워드를 받아 전달하도록 고치고, 자식 모드가
공통 호출 규약으로 불려도 죽지 않는지 고정하는 회귀 테스트를 추가했습니다.

**kimi 와 qwen 런처는 영향이 없었습니다.** 두 런처는 `acquire_fn` 을 넘기지 않아 공통
기본값을 쓰므로 시그니처가 맞았습니다.

---

## 4. 함께 확인한 기동 함정 두 가지

### 4.1 kimi 모델 별칭은 프로필마다 다릅니다

`or-free/minimax-m3` 로 띄우려다 실패했습니다. 런처 기본 프로필
`~/.kimi-openrouter-bakeoff` 에는 `laguna-s`, `laguna-xs`, `nemotron-ultra`,
`north-mini` 만 있고 `minimax-m3` 는 `~/.kimi-code` 프로필에 있습니다.

```bash
uv run python scripts/orca_kimi_launch.py --model or-free/minimax-m3 --home $HOME/.kimi-code
```

23장의 모델 검증이 기동 전에 잡아냈습니다. 검증이 없었다면 워커가 뜬 채로 아무 일도
하지 않았을 것입니다.

### 4.2 qwen 과 kimi 는 `shift+tab` 대상이 아닙니다

`prepare-worker` 는 두 CLI 에서 모드 전환을 fail-closed 로 건너뜁니다. 정상입니다.
qwen 은 Auto mode 로 기동하며 `shift+tab` 은 오히려 그 모드를 벗어나는 순환 키입니다.
셸 명령 승인은 감시기가 처리하므로 감시기 부착 여부만 확인하십시오.

Antigravity 는 화면이 스피너면 모드가 `unknown` 으로 읽혀 전환을 건너뜁니다.
**시도 상한 3회를 넘겨 실패로 나와도 워커가 실제로는 파일을 만들고 있을 수 있습니다.**
2026-08-31 에 I-B 가 그랬습니다. 상태만 보지 말고 화면을 읽으십시오.

---

## 5. 남은 잔여 (미착수)

| 순서 | 작업 | 근거 |
| --- | --- | --- |
| 1 | 워커 3대 `worker_done` 검증 후 병합, 워크트리·브랜치 반납 | 1장 |
| 2 | **Wave I 운영 FULLTEXT 인덱스** — 사용자가 이번 세션에서 **보류** 결정 | 이전 인수인계 3.1 |
| 3 | 경계값 7 클래스 실측 (Wave I 선행 조건) | 이전 인수인계 3.2 |
| 4 | Windows Docker Desktop 실기 | 장비 부재로 보류 |
| 마지막 | G3 cutover 최종 판정 | 콜드 SQL 이 닫힌 뒤 |

**Wave I 는 사용자 승인 없이 시작하지 마십시오.** 이번 세션에서 명시적으로 보류를
선택했습니다. 수 GB 테이블의 최초 FULLTEXT 생성은 테이블 재구축과 쓰기 차단을
유발할 수 있고, 컨테이너가 가동 중입니다.

---

## 6. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| main HEAD | `4cb6514` |
| 규칙 검증 | 15/15 통과 |
| 워크트리 | **4개** (주 저장소 + `orca-i-a`, `orca-i-b`, `orca-i-c`) |
| 작업 브랜치 | `kwanbum217/orca-i-a`, `-i-b`, `-i-c` (미병합, 작업 중) |
| 활성 워커 | **3대** (쓰기 2, 읽기 전용 1) |
| 승인 감시기 | 3개 터미널 전부 부착됨 |
| Docker | 가동 중. 내릴 때 Redis 는 `SHUTDOWN NOSAVE` |

**`fix/launcher-acquire-permissions-signature` 브랜치는 병합 완료입니다.** 삭제해도
됩니다. 나머지 세 브랜치는 활성 워커가 소유하고 있으니 건드리지 마십시오.
