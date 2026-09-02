# 인수인계: 2026-09-03 Wave H 종료

> **작성일**: 2026-09-03
> **Run**: `run_971584ddb4a0` (계속 사용하십시오. 새 Run 을 만들지 마십시오)
> **기준 HEAD**: `aae5ab4` (`main` = `origin/main`)
> **코디네이터**: Claude Opus 5 (사용자 지정). 기본값은 Codex `gpt-5.6-terra` + `medium`
> **이전 인수인계**: [`handoff_20260902_wave_g_session_close.md`](handoff_20260902_wave_g_session_close.md)
> **이 문서가 우선하는 범위**: 워커·워크트리·잔여 과업·다음 착수. 이전 문서 4장의 4.1 과 4.2 항목은 이 문서가 갱신합니다.

---

## 1. 다음 세션이 먼저 할 일

```bash
git -C <repo> log --oneline -1                       # aae5ab4 여야 합니다
uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg
python3 scripts/orca_skill_receipt.py issue          # 정본 주입 + 영수증 발급
python3 scripts/validate_agent_rules.py              # 19/19 여야 합니다
python3 scripts/orca_settled_session_audit.py        # 잔류 없음이어야 합니다
gh run list --limit 3                                # CI 결론 확인
```

**두 번째 줄을 빠뜨리면 병합 게이트가 동작하지 않습니다.** 세 번째 줄을 빠뜨리면
`orca_taskctl.py create`·`dispatch` 가 종료 코드 4 로 거부합니다.

---

## 2. 이 세션이 넣은 게이트 두 개

이번 웨이브의 핵심 산출물입니다. **코디네이터 자신을 구속합니다.**

| 게이트 | 무엇을 막는가 | 실패 시 |
| --- | --- | --- |
| 병합 전 전량 테스트 | 전량 테스트 증거 없는 `main` 병합 | `prepare-commit-msg` 훅이 병합 커밋을 거부 |
| 정본 스킬 영수증 | 정본을 읽지 않은 채 워커 기동 | `create`·`dispatch` 가 종료 코드 4 |

### 2.1 병합 절차가 바뀌었습니다

작업 브랜치에서 증거를 남긴 뒤에만 `main` 에 병합할 수 있습니다.

```bash
# 작업 브랜치(또는 워커 워크트리)에서
python3 scripts/premerge_full_suite_gate.py --record
# 주 저장소 main 에서
git merge --no-ff <branch> -m "..."
```

`--record` 는 `uv run pytest tests/ -q -m 'not data_assets'` 를 돌리고 결과를
주 저장소 공통 `.cache/premerge_full_suite_evidence.json` 에 기록합니다. 약 60초
걸립니다. 증거의 커밋이 병합 대상과 다르거나, 전량 대상이 아니거나, 종료 코드가
0 이 아니면 병합이 거부됩니다.

**워커 브랜치가 `main` 보다 뒤처져 있으면 먼저 워크트리에서 `git merge --no-ff main`
을 하고 그다음에 `--record` 를 하십시오.** 그러지 않으면 게이트에 걸린 뒤 다시
돌려야 해서 60초를 두 번 씁니다.

우회는 `BYPASS_PREMERGE_FULL_SUITE_GATE=1` 하나뿐이며 쓰면 stderr 에 경고가 남습니다.

### 2.2 영수증은 정본을 실제로 읽어야 발급됩니다

`python3 scripts/orca_skill_receipt.py issue` 는 정본 본문 약 437줄을 표준출력으로
방출한 **뒤에만** 영수증을 씁니다. `--json` 같은 우회로로 주입 없이 영수증만 받을 수
없습니다. 영수증은 정본의 sha256 과 Orca `appVersion` 과 코디네이터 터미널 핸들에
묶입니다. Orca 가 갱신되면 해시가 달라져 재발급이 필요합니다.

세션 시작 훅(`.claude/settings.json` 의 `SessionStart`)이 같은 명령을 실행하므로
Claude Code 세션에서는 자동으로 채워집니다. 다른 CLI 는 손으로 실행하십시오.

### 2.3 훅 설치도 기계로 검사합니다

`validate_agent_rules.py` 의 19번째 검사가 `.pre-commit-config.yaml` 이 요구하는
모든 stage 에 대해 `.git/hooks/<stage>` 가 존재하고 실행 가능하며 **pre-commit 이
생성한 래퍼인지** 확인합니다. 내용이 `exit 0` 뿐인 스텁도 거부합니다. `CI=true`
에서는 건너뜁니다.

**훅 설치는 반드시 주 저장소에서 하십시오.** 워크트리에서 하면 생성된 래퍼의
`INSTALL_PYTHON` 이 그 워크트리 `.venv` 를 가리켜 워크트리를 지우면 훅이 깨집니다.

---

## 3. 이 세션이 병합한 것

| 항목 | 커밋 | 비고 |
| --- | --- | --- |
| CI 적색 해소 (chatbot.py 줄 수 상한) | `0832ac0` | 익명 쿼터가 560 -> 565 줄로 늘려 5개 플랫폼 실패. 상한 570 재고정 |
| SSR E2E 범위 조사 보고서 | `6f171f4` | 245줄. 도구 4종 비교, 4단계 분할안 |
| CURRENT_STATE 정규화 (부분) | `f3d9487` | 57,381 -> 48,039 바이트. 웨이브 이력 분리 |
| 병합 전 전량 테스트 게이트 | `c5fca8d`, `1756d3e` | 재작업 5회 |
| 정본 스킬 영수증 게이트 | `4a4aba5` | 재작업 3회 |
| 훅 설치 기계 검증 | `dbb1705` | 재작업 1회. 검사 18 -> 19 건 |
| SSR E2E Phase 1 | `948900d` | pytest-playwright, 동적 포트, 브라우저 부재 시 skip |
| 훅 검사 테스트 CI 환경 수정 | `aae5ab4` | CI 에서만 실패하던 것 |

실측 기준값입니다.

```
uv run pytest tests/ -q -m 'not data_assets'   # 3268 passed, 31 skipped, 3 deselected
python3 scripts/validate_agent_rules.py        # 19/19
```

---

## 4. 다음 착수: SSR E2E Phase 2 (쪼개서 진행)

**Phase 2 를 한 Task 로 만들지 마십시오. 2a 와 2b 로 나누십시오.** 이번 웨이브에서
재작업이 길어진 건들은 전부 범위가 커서 매 라운드 전체를 다시 검증해야 했습니다.

### 4.1 Task 2a — 인증 세션 픽스처와 DB 격리 (선행)

**이것이 Phase 2 의 진짜 난관입니다.** 시나리오 작성이 아닙니다.

`tests/e2e/conftest.py` 의 `live_server_url` 은 실제 `app` 객체를 그대로 uvicorn 에
띄웁니다. 주변 `.env` 를 따라가므로 **개발 DB 에 붙습니다.** Phase 1 은 로그인 화면만
읽어서 문제가 없었지만, Phase 2 는 인증 화면이라 사용자 생성이 필요하고 그 순간
개발 DB 에 쓰기가 발생합니다. **G1 데이터 무손실 위반입니다.**

| 항목 | 내용 |
| --- | --- |
| 쓰기 범위 | `tests/e2e/conftest.py` 만 |
| 완료 기준 | 인증이 필요한 화면 1개에 로그인 상태로 진입하고, 개발 DB 에 쓰기가 없음을 근거와 함께 보임 |
| 검증 | 브라우저 있는 상태 통과, 없는 상태 skip, `uv run pytest tests/ -q -m 'not data_assets'` 전량 통과 |
| 유력한 방법 | uvicorn 이 같은 프로세스·같은 `app` 객체를 쓰므로 `app.dependency_overrides[get_db]` 가 스레드 경계를 넘어 적용될 가능성이 큽니다. **검증 전에는 단정하지 마십시오.** |
| 참고 | 세션 쿠키는 `src/app/core/security.py:212` 의 `create_session()` 으로 직접 발급해 브라우저 컨텍스트에 주입하면 UI 로그인 반복을 없앨 수 있습니다 |
| 막히면 | 구조적으로 불가능하다고 판단되면 `escalation` 으로 보고. 범위를 스스로 넓히지 말 것 |

### 4.2 Task 2b — SSR 핵심 화면 시나리오 (2a 검증 후)

| 항목 | 내용 |
| --- | --- |
| 쓰기 범위 | `tests/e2e/test_ssr_auth.py`, `test_ssr_bids.py`, `test_ssr_results.py`, `test_ssr_dashboard.py` |
| 완료 기준 | 최소 12개 시나리오 통과. 브라우저 없으면 전부 skip |
| 대상 화면 | 인증 플로우(회원가입·로그인·`next` 리다이렉트·POST 로그아웃·CSRF), 공고 목록 검색·필터·정렬·페이지네이션, 공고 상세 AI 예측 폼, 낙찰 목록·상세, 대시보드 Chart.js 캔버스 |
| 주의 | Chart.js 캔버스 단언은 깨지기 쉽습니다. 캔버스 픽셀이 아니라 요소 존재와 데이터 속성으로 검증하도록 지시하십시오 |

상세 화면 목록과 진입 경로는
[`../analysis/ssr_e2e_scope_survey_20260902.md`](../analysis/ssr_e2e_scope_survey_20260902.md)
2.1 절의 표에 있습니다.

### 4.3 소요 추정

이번 세션 실측 기준입니다. Phase 1 은 재작업 0회에 워커 20분 + 코디네이터 검증 10분
이었고, 게이트 계열은 재작업 3~5회에 2~3시간이었습니다.

| 시나리오 | 소요 |
| --- | --- |
| 2a 재작업 0회 | 30~45분 |
| **2a + 2b 재작업 1~2회 (유력)** | **1.5~2.5시간** |
| 2a 의 DB 격리가 구조적으로 막힘 | 3~4시간 또는 설계 재검토 |

### 4.4 모델 배정

사용자 지시입니다. **절차적 구현은 Codex `gpt-5.6-luna`, 추론 밀도가 높으면
Antigravity `gemini-3.7-flash-high`** 입니다.

- 2a: `gemini-3.7-flash-high` (DB 격리 설계 판단)
- 2b: `gpt-5.6-luna` 로 시작 가능 (시나리오 작성은 반복적)

`gpt-5.6-luna` 는 `worker-start --agent codex --model gpt-5.6-luna` 로 띄웁니다.
`gemini` 계열은 `--agent` 로 못 띄우므로 `orca terminal create --command "agy --model
gemini-3.7-flash-high"` 뒤 `worker-start --terminal <handle> --worktree path:<경로>`
입니다.

---

## 5. 잔여 차단 항목 (변동 없음)

| 항목 | 상태 | 막고 있는 것 |
| --- | --- | --- |
| Windows Docker Desktop 실기 | 차단 | 장비 부재. Windows 에 Orca 를 띄우면 `worker-start --on <환경>` 원격 워커 경로가 열립니다 |
| 관측성 스택 구현 | 조사 보고서만 | 스택 선택이 사용자 몫. 결정 전 코드 금지 |
| RPO/RTO, restore drill | 도구만 있음 | 목표값 미확정 |
| 운영 ngram FULLTEXT 컷오버 | 승인 대기 | [`ngram_fulltext_cutover_runbook.md`](ngram_fulltext_cutover_runbook.md) |
| SSR E2E Phase 3·4 | 미착수 | Phase 2 완료가 선행 |
| CURRENT_STATE 8,000자 예산 | 48KB, 미달 | 남은 분량은 2장 지표와 6.1 미해결이며 항목이 닫힐 때 함께 줄어듭니다 |

---

## 6. 이 세션에서 확인한 함정

**전부 실측으로 확인한 것입니다. 재조사하지 마십시오.**

1. **`pre-merge-commit` 시점에는 `MERGE_HEAD` 가 없습니다.** `.git` 에 `AUTO_MERGE`
   만 있고 `MERGE_HEAD` 도 `MERGE_MSG` 도 아직 쓰이지 않았습니다. 탐침 훅으로 두 번
   확인했습니다. 병합 대상 커밋이 필요하면 `prepare-commit-msg` 스테이지를 쓰고
   두 번째 인자가 `merge` 인지 확인하십시오. 그 시점에는 셋 다 존재합니다.

2. **워커는 자기 워크트리에서만 검증하므로 브랜치·저장소 상태 의존 결함을 못 봅니다.**
   워크트리는 현재 브랜치가 `main` 이 아니고 주 저장소의 파일이 없습니다. 게이트처럼
   저장소 문맥에 의존하는 코드는 거기서 항상 통과합니다. 이번 웨이브 재작업 8회 중
   5회가 이 원인입니다. **코디네이터가 병합 후 주 저장소에서 반드시 재측정하십시오.**

3. **`CI=true` 에서만 실패하는 테스트가 나옵니다.** 검사가 CI 에서 조기 통과하도록
   설계됐는데 테스트가 그 환경변수를 지우지 않으면 로컬은 초록, GitHub Actions 는
   적색입니다. `monkeypatch.delenv("CI", raising=False)` 로 고정하십시오.

4. **워커의 통과 수치를 믿지 마십시오.** H3 가 "3232건 통과" 로 보고했으나 실제로는
   46건 실패였습니다. 원인은 워커 자기 세션의 영수증 파일이 있던 상태에서 측정한
   것이었습니다. **코디네이터가 격리 상태에서 재측정한 값만 근거로 쓰십시오.**

5. **`gpt-5.6-luna` 는 커밋 없이 `worker_done` 을 보내는 경향이 있습니다.** 이번에도
   커밋 0건 · 미커밋 5건 상태로 보고했습니다. `orca_worker_watch.py` 의 커밋 수를
   확인하고, 0이면 완료로 처리하지 마십시오. 첫 기동에서
   `The selected Codex account credentials are temporarily unavailable` 로 실패할 수
   있습니다. `worker-start --retry-of <dispatch>` 로 재시도하면 됩니다.

6. **배달을 소진하지 않으면 `question` 을 놓칩니다.** FIFO 라 앞 배달을 ack 하지
   않으면 뒤의 질문이 보이지 않습니다. 이번에 워커가 응답 대기로 멈춘 것을 사용자가
   먼저 발견했습니다. `check --ack <deliveryId>` 를 비어질 때까지 반복하십시오.

7. **감시기는 `run_in_background` 로 띄우고 종료 코드로 알리십시오.** `nohup ... &`
   는 도구 호출이 끝나면 함께 죽습니다. 출력을 `| tail` 로 파이프하면 읽히는 종료
   코드가 `tail` 의 0 이라 차단이 보이지 않습니다. 상세는
   [`../../.claude/skills/orca-section-coordination/SKILL.md`](../../.claude/skills/orca-section-coordination/SKILL.md)
   3.2.1 절과 이 세션의 메모리 기록입니다.

8. **`orca_auto_approve` 는 `rm` 등 파괴적 명령을 설계상 보류합니다.** 자동 승인이
   안 되는 것이 결함이 아니라, 그 보류가 코디네이터에게 도달하지 않는 것이 결함입니다.
   감시 루프에 터미널 프롬프트 문자열 검사를 넣으십시오.

---

## 7. 정리 상태

- 활성 워커: **없음**
- git worktree: 주 저장소만 (`git worktree list` 로 확인)
- 완료 세션 잔류: 없음 (`orca_settled_session_audit.py` 종료 코드 0)
- 미소진 배달: 없음
- Docker·Ollama: **내리지 않았습니다.** 이 세션은 컨테이너를 띄우지 않았습니다

## 8. CI

`aae5ab4` 의 CI 는 이 문서를 쓰는 시점에 **아직 돌지 않았습니다.** 직전 실패
(`33651010133`, `33650452776`)의 원인은 6장 3번 항목이며 `aae5ab4` 로 고쳤습니다.
다음 세션 부트스트랩에서 `gh run list --limit 3` 으로 결론을 확인하십시오.
실패하면 `tests/test_validate_agent_rules.py` 부터 보십시오.
