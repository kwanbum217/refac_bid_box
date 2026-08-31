# 인수인계: 2026-09-01 세션 종료 (Wave J 마감·I-F 병합)

> **작성일**: 2026-09-01
> **Run**: `run_f5b20eafcaff`
> **기준 HEAD**: `c00c789` (`main`, 로컬. `origin/main` 보다 35커밋 앞)
> **이전 인수인계**: [`handoff_20260901_wave_j.md`](handoff_20260901_wave_j.md),
> [`handoff_20260831_wave_i_prep.md`](handoff_20260831_wave_i_prep.md)
> **이 문서가 우선하는 범위**: 아래 4장의 다음 착수 순서. Wave J 문서 4장은
> I-F 를 아직 미병합으로 적고 있으므로 쓰지 마십시오.

---

## 1. 세션이 끝낸 것

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| J1 리뷰어 JSON 복구 | `main` 병합 | `3ca22ce`. 첫 완전 JSON `raw_decode`, 파싱 실패 1회 재시도, `.raw` 보존. Level 1 pass, 테스트 2,928건 재실행 일치 |
| J2 CURRENT_STATE·ngram 런북 | `main` 병합 | `8f20d7e`. I-F 를 MATCH AGAINST 로 적은 오기는 `7f70ce5` 에서 정정 |
| 완료 세션 미회수 재발 방지 | `main` 병합 | `b889ee6`. `scripts/orca_settled_session_audit.py`, `dispatch` 거부, watch `[차단:회수 대기]` |
| I-F 계약 강제 | `main` 병합 | `8b9e5e9` (재기반 커밋 `dd1df7a`). 대상 테스트 261건, 규칙 16/16. MATCH AGAINST 가 아님 |
| Wave J 워커 창·워크트리 | 회수 완료 | J1·J2·J4 브랜치 삭제. 완료 세션 잔류 검사 통과 |
| 운영 FULLTEXT / 플래그 | **미착수** | 사용자 승인 전 보류. 런북만 있음 |

활성 워커 0, git worktree 는 주 저장소만 있습니다.

---

## 2. 다음 코디네이터가 먼저 할 일

1. `docs/context/CURRENT_STATE.md` 를 읽고 이 문서를 잔여 작업 정본으로 쓴다.
2. `python3 scripts/orca_settled_session_audit.py` 로 잔류 세션이 없는지 확인한다. 종료 코드 1 이면 다음 Dispatch 전에 회수한다.
3. 로컬 `main` 이 원격보다 35커밋 앞이다. 푸시는 사용자 확인 후.

**Grok 가 이 세션의 코디네이터였다.** 기본 코디네이터는 Codex `gpt-5.6-terra` / `medium` 이다. 바꾸면 `MODEL_CHANGE_NOTICE` 를 남긴다.

---

## 3. 바로 이어서 (승인 없이 가능)

### 3.1 I-H 경계값 픽스처 — 다음 착수 지점

| 항목 | 값 |
| --- | --- |
| 브랜치 | `kwanbum217/orca-i-h` |
| 커밋 | `d8aa9a9` `test: add 7 ngram edge assertions and correct fail-closed safety` |
| 내용 | `edge_04`·`05`·`07`·`09`·`10`·`11`·`12` 의 `is_safe_for_ngram` 을 `true` 에서 `false` 로 좁힘. ID 집합 동등성 테스트 |
| 파일 | `tests/fixtures/ngram_edge_keywords.json`, `tests/test_ngram_prefilter_equivalence.py`, `docs/analysis/task_1a222b4caaa8.md`, `docs/analysis/task_i_h_ngram_edge_assertions.md` |
| 이미 확인 | J4 읽기 전용 대조에서 7항목 모두 main `true` / I-H `false` |
| 금지 | 운영 FULLTEXT 생성, 플래그 ON, `src/rag/structured_data.py` 변경, Alembic |

절차:

1. `orca worktree create --name orca-ih --base-branch kwanbum217/orca-i-h --setup skip`
2. 현재 `main` 위로 rebase. I-F 병합 이후 `main` 이 많이 앞섰다.
3. `uv run pytest tests/test_ngram_prefilter_equivalence.py -q` 와 `python3 scripts/validate_agent_rules.py --quiet`
4. 독립 리뷰어는 빌더와 다른 계열. 리뷰어를 동시에 두 개 띄우지 말 것
5. 통과하면 `main` 에서 `git merge --no-ff`. `origin/main` 미푸시는 터미널 회수 사유가 아님
6. `worker_done` ack 직후 `worker-release` 와 `terminal close --terminal` (`--tab` 금지)

### 3.2 선택 — J3 리뷰 문서만 이식

브랜치 `kwanbum217/orca-j3` 에 커밋 `4621631` (`docs/analysis/task_j3_if_review.md`) 이 남아 있다. I-F 코드는 이미 `main` 에 있으므로 **코드 커밋 `f9184f5` 를 다시 병합하지 마십시오.** 리뷰 문서만 cherry-pick 할지 판단한다. 필요 없으면 브랜치를 유지하고 `-D` 하지 않는다.

### 3.3 건드리지 말 것

| 브랜치 | 이유 |
| --- | --- |
| `kwanbum217/orca-i-c` (`9210641`) | I-C 반려 보존본. citations_wrong |
| `kwanbum217/orca-i-f` (`f9184f5`) | 재기반본 `dd1df7a` 가 `main` 에 들어갔다. 구 SHA 는 이력이 다를 수 있어 `-D` 금지. `git log --oneline main..<branch>` 를 읽고 `-d` 가 거부하면 둔다 |

---

## 4. 사용자 승인이 있어야 하는 일

순서 고정. 런북 정본은 [`ngram_fulltext_cutover_runbook.md`](ngram_fulltext_cutover_runbook.md).

1. 운영 MySQL ngram FULLTEXT 생성 (`bid_announcements` 약 27GB 재구축, 쓰기 차단). Alembic 자동 마이그레이션 금지
2. 경계값 7클래스 **실측** (픽스처 병합만으로는 실측이 아님)
3. `NGRAM_PREFILTER_ENABLED=true`
4. cold SQL 정본 재측정 (fixture v2 32문항 x 3회, `scripts/measure_coldsql_attribution.py`)
5. 그다음에야 G3 컷오버 판정

Windows Docker Desktop 실기는 장비 부재로 계속 보류.

---

## 5. 이 세션에서 드러난 반복 금지

| 금지 | 올바른 동작 |
| --- | --- |
| I-F 를 MATCH AGAINST 구현으로 적기 | I-F 는 scope guard·worker_done guard. ngram 코드는 Wave H2 로 `main` 에 있고 기본값 OFF |
| `completed` 워커 창을 병합·푸시까지 남기기 | `worker_done` ack 가 회수 시점. `python3 scripts/orca_settled_session_audit.py` |
| `origin/main` 미반영을 회수 보류 사유로 쓰기 | 터미널 회수와 원격 푸시는 별개 |
| 리뷰어 동시 2개 | 2026-08-31 실증. 한 번에 하나 |
| 운영 FULLTEXT / 플래그를 승인 없이 실행 | 런북 0장 체크리스트 |

상세 근거는 [`orca_do_not_repeat.md`](orca_do_not_repeat.md) 25장.

---

## 6. 세션 종료 점검표

| 항목 | 값 |
| --- | --- |
| 주 저장소 | `main` `c00c789` |
| 원격 | `origin/main` 대비 ahead 35. 미푸시 |
| 활성 워커 / 잔류 세션 | 0 / 없음 |
| 워크트리 | 주 저장소만 |
| Docker FULLTEXT | 미생성 |
| 다음 착수 | 3.1 I-H |
| 회수 여부 | Wave J 워커 창·J1·J2·J4 워크트리 **회수했다.** J3 브랜치는 미병합이라 **남겼다** |
