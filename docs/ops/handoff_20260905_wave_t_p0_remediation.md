# 인수인계: Wave T 진단 보고서 P0 시정과 금액 집계 전환

> **작성일**: 2026-09-05
> **Run**: `run_88eed8b64095` (Wave T)
> **기준 커밋**: `dc09a51` -> `9d7fdce` (원격 `main` 반영 완료)
> **미병합 후보**: `a4bbd75` (`kwanbum217/wave-t-t10-ci`)
> **인수 대상**: 다음 코디네이터
> **이전 코디네이터**: Claude Opus 5 -> Codex (사용자 요청으로 현 지점에서 인계)
> **선행 문서**: [`handoff_20260904_wave_r_ci_green.md`](handoff_20260904_wave_r_ci_green.md)

---

## 1. 한 줄 요약

2026-09-04 외부 진단 보고서의 P0 항목을 순서대로 닫았습니다. 공급망 게이트의 실제
구멍, 마이그레이션 G1 증거, Orca 통제면 3대 결함, 금액 집계 전환까지 병합했습니다.
운영 요약 통제 재집계도 원본 행 수 불변으로 완료했습니다. 마지막 `main` CI에서 발견된
`actionlint` SC2034 수정은 별도 브랜치에 커밋했으며 **독립 리뷰·병합·원격 CI 확인이
남았습니다.**

---

## 2. 병합 완료 (전부 원격 반영)

| 순서 | 작업 | 병합 커밋 |
| --- | --- | --- |
| 1 | S-01 공급망 입력 계약 fail-closed (재작업 1회) | `611ab5a` |
| 2 | D-01 마이그레이션 G1 증거 복구 | `53407a7` |
| 3·4 | O-01·O-02·O-03 Orca 통제면 (재작업 1회) | `41131cf` |
| 5 | A안 금액 집계 `base_amount` 컬럼 전환 | `e66e3ae` |
| 6 | `source_commit` 검사 범위 한정 | `26906b1` |
| 추가 | provider 미상 판정 정규화 + 컬럼 전환 실측 | `9d7fdce` |

**`main` 상태**: 전량 테스트 3,637 passed / 23 skipped / 실패 0, mypy 0건,
`validate_agent_rules` 20/20, ruff 통과. `main`, `origin/main`, 현재 `wave_t/handoff`
HEAD는 모두 `9d7fdce`입니다.

**마지막 원격 CI Run `33887683825`는 failure입니다.** Windows·Ubuntu·macOS·MySQL·
Playwright·공급망 보안 작업은 모두 성공했고, `lint-and-validate`의 actionlint만
`.github/workflows/ci.yml:62`의 미사용 `NPM_EXIT` 대입(SC2034)으로 실패했습니다.
수정 후보는 3장에 정리했습니다.

---

## 3. 즉시 해야 할 일 — CI 수정 후보 검토와 병합

사용자가 현재 워커까지만 끝내고 인계하라고 지시하여 새 리뷰 Task는 시작하지 않았습니다.

| 항목 | 값 |
| --- | --- |
| Orca Task | `task_baa2042ee744` (`completed`) |
| Dispatch | `ctx_f5cc47158514` |
| 브랜치 | `kwanbum217/wave-t-t10-ci` |
| 커밋 | `a4bbd75dae380a639e10a165d73e84d5a5c4ce81` |
| 변경 | `.github/workflows/ci.yml`에서 사용되지 않는 `NPM_EXIT=$?` 한 줄 삭제 |
| 워커 검증 | actionlint exit 0, 규칙 20/20, npm 필터 14 passed, `not data_assets` 전량 3,628 passed / 32 skipped / 3 deselected |
| 작업 트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/wave-t-t10-ci`, clean, 터미널 0개 |

다음 순서로 재개하십시오.

1. `a4bbd75`를 Gemini 계열이 아닌 독립 reviewer에게 읽기 전용으로 검토시킵니다. 빌더는
   Antigravity Gemini 계열이었습니다.
2. 코디네이터가 shellcheck 포함 actionlint를 실행합니다.

   ```bash
   docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest
   ```

3. 통과하면 `kwanbum217/wave-t-t10-ci`를 `wave_t/handoff`에 `--no-ff`로 병합합니다.
4. 이 인수인계 문서와 필요한 현재 상태 문서를 작업 브랜치에서 커밋한 뒤 전량 검증합니다.
5. `wave_t/handoff`를 `main`에 `--no-ff`로 병합·푸시하고 새 GitHub Actions Run이
   전부 성공하는지 확인합니다.
6. 병합 확인 뒤에만 T10 워크트리와 브랜치를 제거합니다.

`npm audit`의 종료코드를 직접 게이트로 쓰지 마십시오. 취약점 발견 시 npm 자체는 비정상
종료할 수 있으므로 현재처럼 stdout·stderr를 보존하고 `filter_npm_audit.py`를 항상 실행해
입력 계약과 allowlist를 fail-closed로 판정해야 합니다.

---

## 4. 완료된 통제 재집계

`e66e3ae` 가 announcement 기대 집계 버전을 **2 -> 3** 으로 올렸습니다. 운영 DB 의
요약 행은 버전 2였고 통제 재집계에서 버전 3으로 갱신했습니다.

조회 경로는 이미 비동기로 분리돼 있어 HTTP 요청이 전체 집계를 잡지 않습니다. 이번에는
ARQ 워커 의존 없이 코디네이터가 다음 명령을 정확히 한 번 실행했습니다.

```bash
docker compose ps db                 # healthy 확인 (현재 떠 있음)
uv run python scripts/db_readonly_query.py --sql "SELECT dataset, total_amount, aggregation_version FROM bid_dataset_summaries"
uv run python scripts/rebuild_dataset_summaries.py --only-stale
```

실측 결과는 다음과 같습니다.

| 항목 | 실행 전 | 실행 후 | 판정 |
| --- | ---: | ---: | --- |
| announcement `total_count` | 5,497,840 | 5,497,840 | 불변 |
| announcement `total_amount` | 2,125,507,790,559,697 | 2,125,507,790,559,590 | 정확히 107원 감소 |
| announcement `aggregation_version` | 2 | 3 | 정상 갱신 |
| result `total_count` | 3,427,814 | 3,427,814 | 불변 |
| result `total_amount` | 856,413,340,509,171 | 856,413,340,509,171 | 불변 |
| result `aggregation_version` | 1 | 1 | stale 아님, 건너뜀 |

전체 명령은 exit 0, wall time 37.07초였고 announcement 집계 자체는 36.8초였습니다.
이전 554초 대비 약 15배 단축됐습니다. 원천 테이블 행 수와 Git HEAD·작업 트리는 실행
전후 동일했습니다. Orca 기록은 `task_8f46dda67146`에 있습니다.

선행 Capsule의 확정 상한은 **최대 107원**, 즉 `107원 이하`입니다. 이전 문서의
`107원 미만` 표현은 실제 결과가 정확히 107원이므로 잘못된 경계 문구입니다. 다음
문서 정리 때 [`base_amount_column_mismatch_343_20260904.md`](../analysis/base_amount_column_mismatch_343_20260904.md)와
[`amount_column_aggregation_20260904.md`](amount_column_aggregation_20260904.md)의 같은 표현도
`107원 이하`로 통일하십시오.

---

## 5. 진단 보고서 항목별 처리 결과

### 5.1 닫힌 것

| ID | 처리 |
| --- | --- |
| S-01 | 입력 계약 검증 도입. 차단해야 하는 9가지 입력 전부 `rc=1`, 정상 0건과 전이 의존성은 `rc=0` |
| D-01 | `evidence.json` 단일 유효 JSON, 5개 파일 manifest 와 `shasum -c` 전량 OK, `dump.err` 분류, 백업을 저장소 밖 `~/refac_bid_box_backups/`(권한 700)로 이동 |
| D-02 | 조회 경로 동기 재집계 제거는 Wave S 에서 이미 완료 |
| D-03 | 343건 분류 완결, 컬럼 전환, Decimal 통일, BIGINT 가드 3개 컬럼 |
| O-01 | 역할별 고지문 분기. 리뷰어에게 커밋 의무·`ORCA_WORKER_DONE_V2`·guard 안내가 가지 않음 |
| O-02 | `normalize_provider_hint` 로 미상 판정 통일. 17가지 표기 회귀 테스트 |
| O-03 | preamble 시도 단위 고유 파일명, 소비 후 삭제, 후보 다중 시 거부 |
| C-01 부분 | `supply_chain_gate` 는 Wave R 에서 갱신 |

### 5.2 남은 것

| ID | 내용 | 비고 |
| --- | --- | --- |
| O-04 | 리뷰 Task 를 빌더 Task 에 `deps` 로 연결, `verdict=fail` 후속 시정 Task 를 DAG 에 남기기 | Wave T 에서도 미적용. 재작업은 `taskctl rework` 로 이력을 남겼으나 `deps` 는 여전히 빈 배열 |
| O-05 | 완료 보고 스키마가 template·Capsule·validator 세 곳에서 다름 | 미착수 |
| O-06 | 비감독 Dispatch 수명주기 receipt | 미착수 |
| T-01 | 실패한 Arq 작업의 최상위 span 도 항상 OK | 미착수. `trace_worker_task` 호출부 0곳 |
| C-01 잔여 | `confirmation_token_redis`, `row_reconciliation`, `promotion_status_check`, `ci_windows` 가 코드보다 뒤처짐 | `automation_tokens.py:60` 은 이미 `nx=True` 로 구현됨 |
| S-02 | Actions·도구 이미지·pip-audit 버전 불변 pin | 미착수 |
| D-04 | startup catch-up 이 ARQ `max_jobs` 밖에서 실행, completeness ledger 없음 | 미착수 |
| C-02 | 공급망 정책의 PR·플랫폼 팀 문구가 1인 작업 규칙과 충돌 | 미착수 |
| D-05 | KB reconciliation 103건 모집단 불일치 | 미착수 |
| G-01 | Windows Docker 실기, RPO/RTO, 관측성 backend, cold SQL 재측정 | 미착수 |

---

## 6. 알려진 잔여 결함

| 항목 | 상태 |
| --- | --- |
| `wait_for_preamble` 후보 다중 시 거부 | 닫힘. 단 `taskctl dispatch` 는 여전히 옛 이름으로 쓸 수 있으니 7.1절 참조 |
| `_coerce_amount` 가 전각 숫자를 받지 않음 | 리뷰어 제안. 결함 아님. 필요하면 별도 Task |
| `base_amount` 포화 2건 (`R25BK01131785`, `R25BK01210563`) | 컬럼 값이 `9223372036854775807`. 상한이 집계에서 배제하므로 화면 영향 없음. `NULL` 로 바로잡는 것은 DB 값 변경이라 사용자 승인 필요 |

---

## 7. 인수자가 반드시 알아야 할 함정

### 7.1 런처와 dispatch 의 preamble 계약 불일치

**t2 워커가 이 함정으로 기동조차 못 했고 사용자가 먼저 발견했습니다.**

`e1d5a8a` 이후 런처(`orca_agy_launch.py`)는 `preamble_<task>_<dispatch>_<nonce>.txt`
형식만 받고 옛 고정 `.orca/preamble.txt` 를 **거부합니다.** 그런데 그 시점의
`taskctl dispatch --launcher` 는 옛 이름으로 썼습니다. 지금은 `41131cf` 가 병합돼
양쪽이 새 형식으로 맞춰져 있으나, **워커를 띄운 뒤 반드시 터미널을 읽어 실제로
기동했는지 확인하십시오.**

`dispatch` 가 "런처가 preamble 을 성공적으로 이어받아 에이전트를 기동했습니다" 라고
**거짓 보고**했습니다. `verify_launcher_pickup` 의 결함이며 아직 고치지 않았습니다.
`orca_worker_watch.py` 도 그 상태를 `[진행]` 으로 표시했습니다. **두 도구 모두
믿을 수 없으므로 기동 직후 `orca terminal read` 를 거르지 마십시오.**

### 7.2 `source_commit` 은 병합 커밋 안에서 갱신합니다

`26906b1` 이후 작업 브랜치에서는 경고이고 기본 브랜치에서만 차단합니다. 별도 커밋으로
올리면 그 커밋이 거리를 다시 늘리므로 **병합 커밋에 함께 넣으십시오.** 이 세션에서
네 번 걸렸습니다.

### 7.3 리뷰어 모델

지정 리뷰어 `qwen3.7-plus` 는 **2026-09-06 08:13 UTC 까지 할당량 소진**입니다.
그동안 사용자 제안으로 `grok-4.6` (provider `grok`, `/opt/homebrew/bin/grok`) 을
독립 리뷰어로 썼고 세 번 모두 실제 결함을 찾았습니다. 기동은 문서화된 Kimi 경로와
같습니다.

```bash
orca terminal create --worktree path:<워크트리> --title "리뷰어" --command "zsh" --json
orca orchestration dispatch --task <task> --to <handle> --run <run> --return-preamble --json
# preamble 을 <워크트리>/.orca/preamble_grok.txt 에 쓴 뒤
orca terminal send --terminal <handle> --text 'grok --model grok-4.6 --always-approve "$(cat .orca/preamble_grok.txt)"' --enter
```

`--always-approve` 라 승인 대화창에 걸리지 않습니다. effort high 는 코디네이터
등급이라 워커에는 쓰지 않습니다. **`agent_worker_launch_reference.md` 에 grok 항목이
아직 없습니다. 추가하십시오.**

### 7.4 검증은 배경 병렬로 돌리십시오

Level 1 게이트와 전량 테스트가 각각 ~2분입니다. 워크트리가 서로 독립이라 병렬로
돌려도 충돌하지 않습니다. 사용자가 이 점을 지적했고 전환 후 실제로 시간이 반으로
줄었습니다. 순차로 돌리지 마십시오.

### 7.5 리뷰 지적 시정은 재작업 Task 로

정본 스킬은 "review-only `worker_done` 은 코디네이터 파일 편집을 승인하지 않는다.
검토 완료 후에는 수정을 dispatch 하거나 handoff 하라" 고 규정합니다. 이 세션 전반부에
제가 직접 고쳤고 후반부에는 `taskctl rework` 로 돌렸습니다. **후자가 정본입니다.**

단 한 번 예외를 두었습니다. provider 미상 판정은 같은 결함의 세 번째 라운드였고 근본
원인이 제 사양 문구였으므로, 네 번째 라운드를 만들지 않기 위해 구조 수정을 직접
했습니다. 그 판단 근거를 커밋 메시지에 남겼습니다.

---

## 8. 이번 세션이 확인한 것

**리뷰어를 붙인 것이 값을 했습니다.** t1·t2 모두 기계 게이트(테스트·mypy·ruff·
actionlint)를 전부 통과했는데 독립 리뷰가 각각 실제 보안 구멍을 찾았습니다. 특히 t1 의
Trivy `Results[].Error` 는 **코디네이터 Level 3 검토도 놓쳤습니다.** 최상위 오류만
확인했기 때문입니다.

**같은 결함이 형태만 바꿔 반복됩니다.** 공급망은 "최상위 오류 차단" 후 "대상 단위
오류" 가 남았고, provider 판정은 세 라운드에 걸쳐 `unknown` -> `+빈 문자열` ->
`+공백` -> `+대소문자` 로 새어 나왔습니다. **개별 표기를 덧붙이는 지시는 다음 표기를
막지 못합니다.** 사양에 구조를 적으십시오.

**테스트 통과가 정상 동작의 근거가 아닙니다.** t1 의 metadata 대조 테스트는 기대값을
파서 결과에 맞춰 적어 두어 실제 npm 출력과의 불일치를 숨기고 있었습니다.

---

## 9. 정리 상태

기존 Wave T 워커 자원은 회수됐습니다. T10 워커 터미널과 워크트리 생성 시 생긴 셸
터미널도 모두 닫아 T10 워크트리의 터미널은 0개입니다. `orca_settled_session_audit.py`는
"완료 세션 잔류 없음"입니다.

토큰 한도로 멈춘 이전 Claude 코디네이터 터미널도 닫았습니다. 현재 프로젝트 작업 트리에는
이 인수인계를 작성한 Codex 코디네이터 터미널만 남아 있습니다.

T10 워크트리와 브랜치는 커밋 `a4bbd75`가 아직 병합되지 않아 의도적으로 보존했습니다.
미병합 브랜치와 활성 Dispatch 트리를 제거하지 말라는 규칙에 따른 것입니다.

사용자 요청에 따라 `docker compose down`을 실행했습니다. 실행 중이던 compose `db`
컨테이너와 `refac_bid_box_default` 네트워크는 정상 제거됐고, 볼륨 삭제 옵션은 사용하지
않아 데이터는 보존했습니다. 다음 코디네이터는 shellcheck 포함 actionlint 검증 전에
Docker Desktop 상태를 확인하고 필요한 서비스만 다시 올리십시오. `refac-bid-box:r3`와
`:r3-baseline` 이미지는 삭제하지 않았습니다.

컴퓨터 종료 준비를 위해 별도로 떠 있던 Docker MCP 보조 컨테이너 4개(`mcp/filesystem`,
`harness/mcp-server`, `mcp/github`, `mcp/fetch`)도 삭제하지 않고 중지했습니다. 최종
`docker ps` 출력은 비어 있습니다.

배경 프로세스는 모두 종료됐습니다.
