# 인수인계: 2026-08-28 외부 감사 지적 대응 (Orca Run run_41f6ac9d7450)

> **작성일**: 2026-08-28
> **Run**: `run_41f6ac9d7450`
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity `gemini-3.7-flash-high` 4대, Kimi `or-free/nemotron-ultra` 1대
> **결과**: Task 5건 전부 병합 완료. 전량 테스트 2388 passed, `validate_agent_rules.py` 12/12 PASS

---

## 1. 처리한 Task

| Task | 내용 | 브랜치 | 게이트 | 상태 |
| --- | --- | --- | --- | --- |
| `task_7ff9116d6561` | P0 권한 자동승인 argv 화이트리스트 정책 | `t1-auto-approve` | Level 1 PASS, 테스트 113건 | 병합 완료 |
| `task_792ae782ed49` | P1 fixture Chroma fail-closed 전환 | `t2-fixture-failclosed` | Level 1 PASS, 테스트 16건 | 병합 완료 |
| `task_072fc411a3dc` | P1 백필 하류 동기화 및 정합성 게이트 | `t3-backfill-downstream` | Level 1 PASS, 테스트 9건 | 병합 완료 |
| `task_0c19e7f85c83` | 조사: 정확 제목 lexical 독립 채널 | `t4-lexical-survey` | Level 1 PASS | 병합 완료 |
| `task_28394bf3d41f` | 조사: `ORCA_WORKER_DONE_V2` 게이트 현황 | `t5-workerdone-survey` | 사실 대조 검증 | 병합 완료 |

워크트리 5개, 브랜치 8개 모두 반납 및 삭제했습니다. 워커 터미널 5개 전부 닫았습니다.
남은 워크트리는 주 저장소 하나입니다.

---

## 2. 코드 변경 요약

### 2.1 P0 `scripts/orca_auto_approve.py`

`SAFE_PREFIXES` 접두사 매칭을 폐기하고 `classify_command(cmd) -> (verdict, reason)` 순수 함수로 분리했습니다.

- 셸 메타문자(`| < > ; ` & \n $(`)를 `shlex.split()` **이전**에 검사하여 hold
- `git` 은 서브커맨드 단위 판정. `status`/`diff`/`log`/`show`/`rev-parse` 와 읽기 전용 `branch`/`worktree list` 만 승인
- `git clean`/`reset`/`checkout`/`restore`/`branch -D`/`commit`/`merge`/`push`, `python -c`, `npm`, `mv`/`cp`/`mkdir`, `find -delete`/`-exec`, `docker` 는 hold
- 기존 `DANGEROUS` 정규식은 화이트리스트 통과 이후 2차 방어선으로 유지
- 마지막 `return` 이 fail-closed 보류

### 2.2 P1 `scripts/build_generalization_fixture.py`

`ChromaLoadError` 를 신설하여 조회 실패와 유효 근거 0건을 분리했습니다.

- 파일 부재, sqlite 연결 실패, 쿼리 실패 세 경로 모두 예외 발생 (종전에는 전부 `set()` 반환)
- 후보 필터를 `if chroma_ann_ids and ...` 에서 `if chroma_ann_ids is not None and ...` 로 교체
- 검증 우회는 기본값 `False` 인 `skip_chroma_filter` 명시 인자로만 가능

### 2.3 P1 `scripts/run_data_reconciliation.py` (신규) 와 `scripts/backfill_from_g2b.py`

- 단계 순서: 파생 집계 -> ChromaDB KB 색인 -> Meilisearch 색인 -> 정합성 검사
- 어느 단계든 예외 발생 시 뒤 단계를 실행하지 않고 종료 코드 1 (fail-closed)
- 정합성 차집합이 0 이 아니면 `RuntimeError` 를 올려 종료 코드 1
- 구간 지정(`--since` 또는 `--since-hours`) 없이는 전체 재색인을 거부
- `backfill_from_g2b.py --sync-downstream` 이 위 오케스트레이션을 이어서 호출하고 종료 코드를 전파. 옵션 미지정 시 종전 동작과 안내문 유지

---

## 3. 감사 지적의 정정

### 3.1 지적 10번(`ORCA_WORKER_DONE_V2` 가 문서 규칙일 뿐)은 **부분 타당**입니다

`scripts/orca_taskctl.py:1421` `finalize_task()` 가 `summarize_worker_done.py`(:1467)와
`orca_level1_gate.py`(:1537)를 이미 순차 호출합니다. 게이트는 구현되어 있습니다.

실제 문제는 둘입니다.

1. 자동 호출이 아니라 코디네이터의 수동 실행에 묶여 있습니다.
2. 보고 내용의 진실성(커밋 SHA 위조, 조작된 verification 등)을 검증하지 않습니다.

상세는 [`docs/analysis/worker_done_v2_gate_survey_20260828.md`](../analysis/worker_done_v2_gate_survey_20260828.md).

### 3.2 지적 5번(제목 정규화 충돌)은 **타당**하며 4쌍의 충돌 입력이 유도됐습니다

`2026년 도로포장공사(1차)` 와 `2026년 도로포장공사 1차` 가 동일 키가 됩니다.
동점 해소 근거가 없어 `exact_matches` 리스트의 원래 순서(벡터 거리 순)를 그대로 씁니다.

`MeiliSearchClient.search`(`src/app/services/search_index.py:106-219`)의 인덱스
`searchableAttributes` 첫 항목이 `bid_ntce_nm` 이므로 lexical 독립 채널의 재사용
후보로 확인됐습니다. 상세는
[`docs/analysis/exact_title_lexical_channel_survey_20260828.md`](../analysis/exact_title_lexical_channel_survey_20260828.md).

---

## 4. 이번 Run 에서 재현된 계약 위반 (다음 세션이 먼저 볼 것)

**워커 5대 중 T1, T5 가 `worker_done.json` 보고 파일을 쓰지 않았습니다.**
`summarize_worker_done.py` 가 "보고 파일 없음" 으로 끝나는데도 **Level 1 게이트는
PASS 했습니다.** 게이트 5(리뷰 보고)가 `--review-report` 미지정으로 `N/A` 처리되기
때문입니다.

즉 3.1 의 "게이트가 자동이 아니다" 는 문제가 이 Run 에서 실측으로 확인됐습니다.
산출물은 코디네이터가 직접 대조 검증하여 수용했습니다.

---

## 5. 워커 감시 실적과 도구 사각지대

### 5.1 감시가 잡아 해제한 차단 5건

| 차단 | 탐지 경로 | 해제 |
| --- | --- | --- |
| Antigravity 3대 인증 정체 (`not signed in`) | `orca_worker_watch.py` 종료 코드 1 | 런처 대기 + `agy -i` 프롬프트 인자 주입 경로로 전환 |
| 파일 편집 승인 대화창 3대 | 터미널 직접 판독 | `terminal send --text $'\x1b[Z'` (shift+tab) |
| CLI 만족도 설문 T2/T3 | 감시 루프 종료 코드 1 | `terminal send --text '0'` |
| opencode 문장 반복 정체 (T4) | 터미널 직접 판독 | Gemini 3.7 Flash 로 교체 재배정 |
| 네트워크 오류 + 설문 (T4 재배정 후) | 감시 루프 종료 코드 1 | 설문 skip 후 **작업 재개 지시 재전송** |

### 5.2 도구가 놓치는 것 (미해결, 다음 세션 후보)

1. **`orca_auto_approve.py` 는 Antigravity 의 파일 편집 대화창을 탐지하지 못합니다.**
   `"Do you want to proceed?"` 와 `"Requesting permission for:"` 문자열만 찾으므로
   `Accept this file edit?` / `Allow creation of this file?` 는 잡히지 않습니다.
   `orca_worker_watch.py` 도 이 상태를 `[진행]` 으로 표시했습니다.
   예방책은 기동 직후 shift+tab 전송이며, 이번에 이를 빠뜨려 3대가 멈췄습니다.
2. **감시 신호와 실제 원인이 다를 수 있습니다.** T4 재배정 후 도구는 "CLI 설문" 만
   보고했으나 실제 정체 원인은 네트워크 오류로 인한 턴 종료였습니다. 설문만
   넘겼다면 워커는 유휴로 남았을 것입니다. **도구 신호만 보고 조치하지 말고
   터미널을 함께 읽으십시오.**

### 5.3 Antigravity 기동은 런처 경로가 안정적입니다

`orca terminal create --command "agy --model <id>"` 로 띄운 3대가 전부 스플래시에서
멈췄습니다. 같은 시각 `agy --print "reply with OK only"` 는 종료 코드 0 으로 정상이었으므로
CLI 문제가 아니라 TUI 기동 문제입니다.

Kimi 와 동일하게 **워크트리의 `.orca/preamble.txt` 를 기다렸다가 `agy --model <id> -i "<preamble>"`
로 exec 하는 런처**를 터미널 명령으로 지정하면 안정적으로 떴습니다. 4대 모두 이 경로로 성공했습니다.

---

## 6. 다음 착수 (우선순위)

저장소가 동결 가능한 상태이므로 측정 계열을 먼저 닫는 것이 맞습니다.

| 순위 | 작업 | 비고 |
| --- | --- | --- |
| 1 | 현 HEAD 에서 blind fixture 최종 재측정 | 암묵 날짜 필터 수정, exact title rerank, 후보 30 확대 반영 후 evidence recall 미확정. e2b/e4b 비교보다 retrieval 24/24 여부가 먼저 |
| 2 | 후보 풀 30 확대 후 RAG 레이턴시 재측정 | `vector_ms` P50/P95, Query RAG P95, SSE first-token/total P95. 기존 G3 수치를 그대로 쓰면 안 됨 |
| 3 | Servc 3,589 OOS 현 Champion 고정 평가 | 재학습 게이트 3,098 을 491 초과. 재학습 전에 고정 평가부터 |
| 4 | `ORCA_WORKER_DONE_V2` 를 실행 게이트로 승격 | 4장 참조. 최소 변경 지점은 조사 보고서 6장 |
| 5 | 정확 제목 lexical 독립 채널 도입 | 조사 보고서 6장의 통합 지점 후보 참조. `candidate_pool=30` 을 장기 해법으로 두지 않음 |
| 6 | `orca_auto_approve.py` 에 파일 편집 대화창 탐지 추가 | 5.2 참조 |

**측정(1~3)은 저장소 동결이 전제입니다.** 측정 중 병합을 하지 마십시오.

---

## 7. 미푸시 상태

`main` 이 `origin/main` 대비 18 커밋 앞서 있습니다. 푸시는 담당자 확인 후 수행합니다.
