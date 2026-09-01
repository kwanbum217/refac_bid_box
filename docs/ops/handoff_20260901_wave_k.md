# 인수인계: 2026-09-01 Wave K (I-H·J3 병합, 테스트 회귀 시정, 감시 강제화)

> **작성일**: 2026-09-01
> **Run**: `run_6872c388bbf2`
> **기준 HEAD**: `1cdcb51` (`main`, 로컬)
> **이전 인수인계**: [`handoff_20260901_session_close.md`](handoff_20260901_session_close.md)
> **이 문서가 우선하는 범위**: 아래 4장의 다음 착수 순서. 이전 문서 3장(I-H·J3)은 닫혔습니다.

---

## 1. 세션이 끝낸 것

| Task | 항목 | 상태 | 근거 |
| --- | --- | --- | --- |
| K1 | I-H 경계값 7 클래스 픽스처 | `main` 병합 | `a0ec7e3`. 7 클래스 전부 `is_safe_for_ngram: false`. 대상 테스트 18 passed / 9 skipped |
| K2 | J3 독립 리뷰 문서 이식 | `main` 병합 | `32b2426`. 코드 커밋 `f9184f5` 미병합 유지 |
| K5 | CURRENT_STATE 신선도 갱신 | `main` 병합 | `21bc3b3` |
| K3 | dispatch 테스트 회귀 27건 시정 | `main` 병합 | `7dac20f`. 시정 후 2,961 passed |
| K4R | 워커 감시·승인 차단 방지 강제화 | `main` 병합 | `1cdcb51`. 시정 후 2,966 passed |

전 Task 가 Level 1 게이트 PASS, 독립 리뷰(`qwen3.7-plus`, 빌더 Gemini 계열과 분리) `pass` 를 통과했습니다.

활성 워커 0, 워크트리는 주 저장소만, 완료 세션 잔류 없음입니다. **회수했습니다.**

---

## 2. 이 세션이 드러낸 사실

### 2.1 직전 인수인계의 테스트 수치는 사실이 아니었습니다

`handoff_20260901_session_close.md` 는 J1 을 "테스트 2,928건 재실행 일치" 로 적었으나, Wave K 착수
시점의 `main` 에는 **실패 27건**이 있었습니다.

| 파일 | 실패 |
| --- | ---: |
| `tests/test_orca_taskctl.py` | 26 |
| `tests/test_measure_agent_bootstrap_cost.py` | 1 |

원인은 `b889ee6` 이 넣은 완료 세션 잔류 검사가 테스트 안에서 실제 Orca CLI 를 호출하고,
런타임이 `Run run_auto was not found` 를 돌려주자 fail-closed 로 거부한 것입니다. 병합 시점에
전체 테스트가 돌지 않아 회귀가 `main` 에 남았습니다.

**시정 방향**: 검사 자체는 운영에서 계속 거부해야 하므로 약화하지 않고, `check_settled_sessions()`
를 주입 가능한 함수로 분리해 테스트가 이를 대체하게 했습니다. 운영 fail-closed 는 별도 회귀
테스트로 고정했습니다.

### 2.2 워커 감시는 지침이 아니라 기계여야 합니다

코디네이터가 상시 감시(`orca_worker_watch.py --watch`)를 걸지 않고 수동 폴링만 하다가,
사용자가 워커 중단을 먼저 지적했습니다. 감시를 걸자 **즉시** 다음을 잡았습니다.

| 차단 | 해제 |
| --- | --- |
| Antigravity 폴더 신뢰 대화창 (2회) | `terminal send --enter --text ''` |
| `worker_done` 의 `reportPath` 누락 | 보고 경로를 지정해 재전송 |
| 셸 리다이렉션·heredoc 승인 대화창 (3회) | 승인 후 편집 도구 사용을 지시 |

**셸 리다이렉션(`>`)과 heredoc 은 자동 승인 화이트리스트 밖입니다.** 워커가 `git show ... > /tmp/...`
나 `cat << EOF > 파일` 을 쓰면 매번 사람 승인을 기다립니다. Capsule 이나 기동 지시에 파일 편집
도구를 쓰라고 적으면 `accept-edits` 에서 자동 승인되어 멈추지 않습니다.

**K4R 로 기계화한 것**은 두 가지입니다.

1. Dispatch 가 권한 자동 승인 감시기 부착에 실패하면 **기본값에서 거부**합니다. 우회는
   `--skip-auto-approve-check` 명시 지정으로만 가능하고 경고가 남습니다.
2. 워커 기동 성공 경로에서 **상시 감시기를 단일 인스턴스로 자동 기동**합니다. PID 레지스트리로
   중복을 막고 이미 떠 있으면 재사용합니다.

### 2.3 같은 파일을 두 Task 에 배정하면 병합에서 충돌합니다

K3 와 K4 에 `tests/test_orca_taskctl.py` 를 모두 배정해, K3 병합 후 K4 rebase 가 4 블록에서
충돌했습니다. 두 워커가 같은 문제(테스트 격리)를 각자 다르게 풀었기 때문입니다. 코디네이터가
손으로 합치는 대신 `orca_taskctl.py rework` 로 재작업 Task 를 발급해 워커가 현재 `main` 위에
자기 변경만 재적용하게 했습니다(K4R).

**Task 사양을 쓸 때 쓰기 범위가 겹치는지 먼저 확인하십시오.** 겹치면 순차로 돌립니다.

---

## 3. 바로 이어서 (승인 없이 가능)

승인 없이 할 수 있는 잔여 작업은 **없습니다.** 이전 인수인계 3장의 I-H 와 J3 가 모두 닫혔습니다.

선택 사항으로 남은 것은 다음뿐입니다.

| 대상 | 판단 |
| --- | --- |
| `origin/main` 푸시 | 로컬이 원격보다 앞섭니다. 사용자 확인 후 |
| 스킬 미러 3곳 세 번째 경로 | `.opencode/skills/` 도 미러 대상입니다. Task 사양에 세 경로를 모두 적으십시오 |

---

## 4. 사용자 승인이 있어야 하는 일

순서 고정. 런북 정본은 [`ngram_fulltext_cutover_runbook.md`](ngram_fulltext_cutover_runbook.md).

1. 운영 MySQL ngram FULLTEXT 생성 (`bid_announcements` 약 27GB 재구축, 쓰기 차단). Alembic 자동 마이그레이션 금지
2. 경계값 7클래스 **실측**. 픽스처는 병합됐으나 값은 fail-closed 추정이며 실측이 아닙니다
3. `NGRAM_PREFILTER_ENABLED=true`
4. cold SQL 정본 재측정 (fixture v2 32문항 x 3회, `scripts/measure_coldsql_attribution.py`)
5. 그다음에야 G3 컷오버 판정

Windows Docker Desktop 실기는 장비 부재로 계속 보류입니다.

---

## 5. 건드리지 말 것

| 브랜치 | 이유 |
| --- | --- |
| `kwanbum217/orca-i-c` (`9210641`) | I-C 반려 보존본. `citations_wrong` |
| `kwanbum217/orca-i-f` (`f9184f5`) | 재기반본 `dd1df7a` 가 `main` 에 들어갔습니다. 구 SHA 이므로 `-D` 금지 |
| `kwanbum217/orca-i-h` (`d8aa9a9`) | 내용은 `a0ec7e3` 로 병합됐으나 SHA 가 달라 `-d` 가 거부합니다. 그대로 두십시오 |
| `kwanbum217/orca-j3` (`4621631`) | 문서만 이식했고 코드 커밋이 남아 미병합입니다 |
| `kwanbum217/orca-k4-sup` (`cb46fc0`) | K4 반려 보존본. K4R(`c0dbdf7`)이 대체했습니다 |

---

## 6. 이 세션에서 드러난 반복 금지

| 금지 | 올바른 동작 |
| --- | --- |
| 인수인계의 테스트 수치를 재실행 없이 믿기 | 착수 시 `uv run pytest tests/ -q` 로 기준선을 직접 잡습니다 |
| 워커 감시를 수동 폴링으로 대신하기 | 기동 직후 `orca_worker_watch.py --watch` 를 배경으로 겁니다. K4R 이후 Dispatch 가 자동 기동합니다 |
| 쓰기 범위가 겹치는 Task 를 병렬 Dispatch | 사양 작성 시 scope 교집합을 확인하고 겹치면 순차로 돌립니다 |
| 워커가 셸 리다이렉션·heredoc 으로 파일을 쓰게 두기 | 편집 도구를 쓰라고 지시합니다. 리다이렉션은 화이트리스트 밖입니다 |
| 스킬 미러를 두 곳만 고치기 | `.claude/`, `.agents/`, `.opencode/` 세 곳입니다 |

---

## 7. 세션 종료 점검표

| 항목 | 값 |
| --- | --- |
| 주 저장소 | `main` `1cdcb51` |
| 전체 테스트 | 2,966 passed (격리 트리 예외 2건 제외) |
| 규칙 검사 | 16/16 |
| 활성 워커 / 잔류 세션 | 0 / 없음 |
| 워크트리 | 주 저장소만 |
| Docker FULLTEXT | 미생성 |
| 다음 착수 | 4장 (사용자 승인 필요) |
| 회수 여부 | Wave K 워커 창·워크트리 **회수했다.** 미병합 보존 브랜치 5개는 **남겼다** |
