# 인수인계: 20260906 Wave U·V 세션 종료

> **작성일**: 2026-09-06
> **Run**: `run_38ef63cba230`(Wave U), `run_e61d4eaa452e`(Wave V)
> **기준 커밋**: `1e1b01d` -> `8022a43` (원격 `main` 반영 완료, 커밋 24개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260905_report_remediation_close.md`](handoff_20260905_report_remediation_close.md)

---

## 1. 한 줄 요약

**어제 남긴 첫 확인 항목이던 CI 실패를 닫았고**, R-05 를 시정했으며, 이번 세션이
스스로 잡아낸 조율 도구 결함 세 건까지 함께 닫았습니다. 빌더는 전부 Muse Spark
1.3, 리뷰어는 전부 Gemini 였고 그 실적을 근거로 Muse 를 라우터에 승격했습니다.

---

## 2. CI 확인 결과 (선행 인수인계의 첫 항목)

`1e1b01d` 의 Run `33973156303` 은 **실패였습니다.** 열 개 작업 중 아홉 개가
통과하고 `Test (windows-latest, py3.11)` 하나만 실패했습니다. 앞선 두 실패
(`33972858106`, `33971468611`)는 `lint-and-validate` 였고 이미 닫혀 있었습니다.

원인을 코드 근거로 특정했습니다. `src/app/core/cache.py` 의
`CONNECT_TIMEOUT_SECONDS` 가 2 이고, `src/rag/structured_data.py` 의 `_top_rows`
가 single-flight 잠금 안에서 `cache.set` 을 호출합니다. Redis 가 없는 CI 에서 그
호출이 최대 2초를 쓰는데 테스트의 `t1.join(timeout=2)` 예산이 정확히 같은
값이었습니다. 재연결 백오프 5초가 만료된 회차에서만 터지므로 간헐적으로
보였습니다.

**세션 종료 시점 CI 는 두 번 연속 10개 작업 전량 통과입니다**
(`34006441984`, `34007760587`).

---

## 3. 병합한 것

| 건 | 내용 | 빌더 커밋 | 리뷰 |
| --- | --- | --- | --- |
| U1 | CI 타이밍 의존 테스트 결정화 | `6b7cabe` | flash-high `pass` |
| U2 | R-05 KB 모집단 불일치 시정 | `5d93ec6` | flash-high `pass` |
| U3 | Z2 후속 정리 (`tables` 인자, 런북 예시) | `b89b02e` | flash-medium `pass` |
| V1 | `worker_done` 전송 신원 자동 해소 | `e536058` | flash-high `pass` |
| V2 | 스냅샷 매니페스트 부재 fail-closed | `23123b5` | flash-high `pass` |
| V3 | Level 1 게이트 7 (gitignore 커밋 검사) | `ca1c757` | flash-high `pass` |
| 라우터 | Muse Spark 1.3 고난도 워커 승격 | `50190c1` | 코디네이터 직접 |

`main` 최종 검증은 pytest **3,727 passed / 32 skipped**,
`validate_agent_rules` 20/20, ruff 통과, mypy 93개 파일 0건입니다.

### 3.1 R-05 는 후보 1 로 구현했습니다

조사 문서의 후보 1(저장소별 도메인 정합 기대 집합 분리)을 채택했습니다.
`verify_reconciliation` 이 세 대조를 각각 수행하고 하나라도 누락이 있으면
fail-closed 로 실패합니다.

| 대조 | 좌변 | 우변 |
| --- | --- | --- |
| 1 | DB 공고(`BidAnnouncement`) | ChromaDB `bidding_kb` |
| 2 | DB 공고 | Meilisearch `dataset="announcement"` |
| 3 | DB 낙찰(`BidResult`) | Meilisearch `dataset="result"` |

후보 2 는 낙찰 없는 공고의 색인 누락을 못 잡고, 후보 3 은 G1 에 위배되어
채택하지 않았습니다.

---

## 4. Muse Spark 1.3 승격 (WORKER_MODEL_NOTICE)

`builder` 와 `investigator` 의 **high 위험도 두 조합만** `TIER_POLICY` 선두를
`opencode/muse-spark-1.3-contributor-free` 로 바꿨습니다. 기존
`gemini-3.8-flash-high` 는 fallback 으로 남습니다. 나머지 13개 역할·위험도
조합은 변경 전후가 동일함을 실측으로 확인했습니다.

**승격 근거는 외부 벤치마크가 아니라 이 세션에 병합된 실과제 6건입니다.**
전부 Level 1 게이트와 독립 리뷰를 통과했고, U1 은 CI 전량 통과로 목표 달성까지
확인됐습니다. 다만 **표본은 하루치이므로 스택 간 순위를 말할 수는 없습니다.**
자동 배정을 high 두 조합으로만 좁힌 이유가 그것입니다.

### 4.1 추론 등급은 설정하지 않습니다 (capability_unknown 확정)

세 경로가 모두 막혀 있음을 실측했습니다. **다시 조사하지 마십시오.**

| 경로 | 결과 |
| --- | --- |
| `worker-start --agent opencode --model ... --effort ...` | `Agent opencode does not support launch-time model selection` 로 거부 |
| 워커가 뜨는 TUI (`opencode <project>`) | `--variant` 플래그 자체가 없음 |
| `opencode run --variant` | `high`, `max`, 존재하지 않는 `zzzznotavariant` 가 **전부 종료 코드 0** |

세 번째가 결정적입니다. 아무 값이나 통과하므로 등급을 매핑하면 실제로는 아무
일도 하지 않는 설정이 됩니다. **난이도는 effort 가 아니라 Capsule 사양 밀도로
조절하십시오.**

### 4.2 reviewer 와 benchmarker 는 명시 지정 전용입니다

`suitable_for` 에는 넣었으나 `TIER_POLICY` 에는 넣지 않았습니다. 병합 판정과
수치 해석은 임계 경로이고, 무료 티어 스택을 그 경로에 자동으로 올리지 않는다는
기존 규칙을 유지했습니다.

### 4.3 열린 설계 논점 하나

`classify_risk` 는 DB 스키마 변경과 마이그레이션 같은 **위험한** 목적도, 다중
파일 리팩터링 같은 **복잡한** 목적도 똑같이 `high` 로 분류합니다. 따라서
`(builder, high)` 를 Muse 로 열면 DB 마이그레이션 구현도 무료 티어 워커로
자동 배정됩니다. 병합 판정은 Level 3 에서 코디네이터가 하므로 최종 결정권은
넘어가지 않지만, **위험도와 복잡도를 분리하는 축을 라우터에 둘지는 아직
정해지지 않았습니다.** 필요해지면 그때 결정하십시오.

---

## 5. 기동 절차 (반드시 이 순서)

### 5.1 Muse(OpenCode) 빌더

`--model`/`--effort` 를 `worker-start` 에 넘길 수 없으므로 터미널 경로만 씁니다.

```bash
orca terminal create --worktree "id:<워크트리ID>" --title "OC | <섹션>" \
  --command 'opencode --model opencode/muse-spark-1.3-contributor-free'
python3 scripts/orca_taskctl.py dispatch --intent <intent> --run-id <run> \
  --task-id <task> --capsule <capsule> --terminal <핸들> --agent opencode \
  --repo <워크트리경로> --allow-unverified-delivery
```

### 5.2 Gemini 리뷰어

**런처를 먼저 띄운 다음 dispatch 하십시오.** 순서를 반대로 하면 preamble 만
쓰이고 30초 뒤 `런처 기동 확인 시한 초과` 로 실패합니다. 이번 세션에 한 번
겪었습니다.

```bash
T=$(orca terminal create --worktree "id:<워크트리ID>" --title "RV | <섹션>" --json | ...)
orca terminal send --terminal $T --text "python3 scripts/orca_agy_launch.py --model gemini-3.8-flash-high" --enter
python3 scripts/orca_taskctl.py dispatch ... --terminal $T --launcher --model gemini-3.8-flash-high --agent antigravity
```

---

## 6. 이번 세션이 스스로 잡아낸 도구 결함 (전부 시정 완료)

기계 게이트가 아니라 **실제 운용 중에** 드러난 것들입니다.

| 결함 | 증상 | 시정 |
| --- | --- | --- |
| `orca_worker_done_guard.py --send` 가 `--from`/`--dispatch-id` 를 안 붙임 | Orca 가 `Rejected worker_done` 으로 거부. 워커 두 대가 전송 완료로 착각하고 유휴 상태로 남음 | `ORCA_TERMINAL_HANDLE` 에서 해소하고, 못 구하면 전송하지 않고 실패 (V1) |
| 게이트가 gitignore 강제 커밋을 못 잡음 | 리뷰어 두 대가 `.orca/capsules/**/review_done.json` 을 커밋. 코디네이터가 손으로 브랜치를 되돌림 | 게이트 7 신설. `git check-ignore` 근거 판정 (V3) |
| 매니페스트 없는 스냅샷이 목록에서 사라지고 보존 검증도 생략 | 손상 보존본이 조용히 `retain_count` 를 채움 | 목록에 무효로 노출, 보존 검증에서 fail-closed (V2) |

---

## 7. 이번 세션이 확인한 것

### 7.1 게이트 실패가 곧 결함은 아닙니다

Level 1 게이트 6 이 세 번 실패했는데 **셋 다 산출물 결함이 아니었습니다.**

| 사례 | 실제 원인 |
| --- | --- |
| U1 `exit code 4` | 워커가 `command` 필드에 `(5 consecutive runs)` 를 붙여 실행 불가 문자열이 됨 |
| U1 `passed 보고=60, 실제=30` | 정정한 `result` 문자열에 숫자가 두 번 들어가 파서가 합산 |
| V2 `범위 초과` | **코디네이터 Capsule 결함.** 앞 회차 커밋을 유지하라 지시하고 그 산출물 경로를 쓰기 범위에 넣지 않음 |

**보고의 `command` 필드에는 실행 가능한 문자열만 넣게 하십시오.** 회차 수 같은
부연은 `result` 에 적되 숫자를 중복시키지 마십시오. 이번 세션부터 Capsule
`ground_truth` 에 이 조항을 넣었고 이후 재발하지 않았습니다.

### 7.2 재작업을 같은 브랜치에 쌓으면 게이트가 구조적으로 어긋납니다

선행 인수인계 6.5 절이 지적한 문제가 그대로 재현됐습니다. V2 재작업을 같은
브랜치에 쌓자 앞 회차 산출물이 새 Capsule 범위 밖으로 잡혔습니다. **같은
브랜치에 쌓으려면 앞 회차의 산출물 경로를 새 Capsule 의 `allowed_write_files`
에 반드시 함께 넣으십시오.**

### 7.3 메일함을 비우지 않으면 워커가 죽습니다

V2 워커가 범위 확대를 `ask` 로 물었는데 코디네이터가 그 Run 의 배달을 비우지
않아 **600초 시간 초과로 차단됐습니다.** 워커 판단은 옳았고 코디네이터 과실
입니다. 스킬 3.4 절의 배달 소진은 선택이 아니라 감독 절차의 일부입니다.

### 7.4 병합 훅은 대상 커밋별 전량 테스트 증거를 요구합니다

`git merge` 전에 **병합 대상 커밋에서** `python3 scripts/premerge_full_suite_gate.py --record`
를 돌려야 합니다. 워크트리에서 기록하면 주 저장소 훅이 즉시 공유합니다. 브랜치
마다 한 번씩 필요하므로 병합 전 소요를 계산에 넣으십시오(회당 약 2분).

---

## 8. 남은 항목

선행 인수인계 4장의 7개 중 R-05 가 닫혀 **6개가 남습니다.** 조건은 그대로입니다.

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| R-02 | 정기 백업의 운영 컨테이너 배선 | "백업을 어디서 실행할 것인가" 운영 결정 |
| R-07 | RPO/RTO 미정 | 복구 목표를 사람이 정해야 한다 |
| R-10 | 관측성 backend, SLO, 알람 미정 | 수집기와 보존 기간 결정 |
| R-12 | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 경로가 열려 있다 |
| R-13 | RAG cold SQL 재측정 | 측정 중 저장소 동결 필요 |
| R-14 | Servc 결측 하한율 구간 품질, drift baseline | 승인된 baseline 의 출처와 버전 확정 |

**여섯 개 모두 사람의 결정이나 장비가 선행합니다.** 코드로 진행할 수 있는
항목은 이 세션에서 소진했습니다.

### 8.1 후속 정리 과제 잔여

| 출처 | 내용 | 상태 |
| --- | --- | --- |
| Z1 리뷰 | 매니페스트 없는 보존본 검증 생략 | **닫힘 (V2)** |
| Z1 리뷰 | 경보가 prune 보다 앞서는 실행 순서 | 열림 |
| Z1 리뷰 | 임계값 비교 테스트 부재 | 열림 |
| Z2 리뷰 | `evaluate_row_counts` 미사용 `tables` 인자, 런북 예시 | **닫힘 (U3)** |
| 코디네이터 | `backup_snapshots.py` 분리 검토 | 열림. V2 에서 줄 수 상한 안에 들어와 급하지 않음 |
| 코디네이터 | 원 X4 `worker_done.json` 부재로 `docs/analysis/task_7f0659b4d4fc.md` 가 미보고 | 열림 |

---

## 9. 환경 조치

**로컬 `claude` CLI 를 복구했습니다.** `/opt/homebrew/bin/claude` 심볼릭 링크는
있는데 네이티브 바이너리가 없어 `claude native binary not installed` 로
`orca_taskctl.py` 의 정본 스킬 영수증 검사와 `orca_worker_watch.py` 가 오류를
뱉었습니다. 사용자 승인 후 postinstall 을 실행해 2.1.263 정상 동작을
확인했습니다.

```bash
node /opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/install.cjs
```

같은 증상이 다시 보이면 이 한 줄이 답입니다. 그 사이에는
`--skip-skill-receipt` 로 우회할 수 있으나 습관화하지 마십시오.

---

## 10. 정리 상태

**모든 자원을 회수했습니다.** 워커 6대와 리뷰어 4대 전원을 `worker_done` 또는
게이트 확인 직후 `worker-release` 하고 터미널을 닫았습니다. `worker-release` 는
터미널 부착 Dispatch 라 전부 `retained`/`no_owned_resource` 로 돌아왔고
`orca terminal close --terminal` 로 창 단위 종료했습니다(`--tab` 미사용).

워크트리 6개(`orca-u1-singleflight`, `orca-u2-r05`, `orca-u3-z2`, `orca-v1`,
`orca-v2`, `orca-v3`)를 모두 제거했고, 브랜치는 전부 `git branch -d` 로
삭제했습니다. `-D` 강제는 쓰지 않았습니다. `orca_settled_session_audit.py` 는
잔류 없음이며 `git worktree list` 는 주 저장소 한 줄입니다.

세션이 띄운 배경 프로세스(`orca_auto_approve.py` 10개, 상시 감시기, CI 감시기,
게이트 감시기)를 종료했습니다. **Docker 는 이 세션에서 띄우지 않았고 세션
내내 내려가 있었습니다.**

### 10.1 하나 남은 기록

`task_29305aa797b8`(V2 재작업)의 Task 행은 `dispatched` 로 남아 있습니다.
워커가 `worker_done.json` 은 썼으나 수명주기 메시지를 보내지 못했고, 그 Dispatch
(`ctx_5e9cc0f4fb44`)는 이미 `failed` 로 정착돼 동시 쓰기 상한을 점유하지
않습니다. **산출물은 게이트 7/7 통과와 독립 리뷰 `pass` 로 검증하고
병합했습니다.** 기록과 실물이 어긋난 지점이니 다음 사람이 오해하지 않도록
적어 둡니다.
