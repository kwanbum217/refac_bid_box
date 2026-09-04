# 인수인계: wave_q CI 복구와 집계 버전 도입

> **작성일**: 2026-09-04
> **Run**: `run_c1a0996c60ef`
> **기준 커밋**: `a44edca` -> `f17847b` (원격 반영 완료)
> **코디네이터**: Claude Opus 5, 워커 3대: Antigravity Gemini 3.8 Flash

---

## 1. 한 줄 요약

main CI 가 4회 연속 실패하던 원인 두 가지를 제거하고, 금액 집계가 알고리즘 변경을
감지하지 못하던 구조 결함에 버전 필드를 도입했습니다. **CI 는 아직 초록이 아닙니다.**
남은 실패 2건은 이번 작업이 만든 것이 아니며 사용자 결정이 필요합니다.

---

## 2. 병합된 작업

| Task | 내용 | 병합 커밋 |
| --- | --- | --- |
| `task_0dfc2f73ee31` | CI 스케줄 테스트 복구, catch-up 쿨다운 키 분리 | `ccad3c3` |
| `task_ba5614889a6f` | `aggregation_version` 도입, stale 요약 무효화 | `2682b09` |
| (코디네이터) | CURRENT_STATE `source_commit` 갱신 | `b45d2df` |
| `task_bfbd6d51107a` | 공급망 보안 검증 job 복구 (재작업) | `f17847b` |

`task_a48917d63a07` 은 반려됐고 그 이력은 `.orca/capsules/task_a48917d63a07/rejection.json`
에 있습니다.

### 2.1 q1 — CI 스케줄 테스트와 쿨다운 키

Redis 가 없는 CI 에서 `test_task_offload_scheduled.py` 2건이 실패했습니다. 원인은
claim 획득이 fail-closed 되어 `status='failed'` 를 반환하는데 테스트가 `'success'`
를 기대한 것입니다. **기대값을 뒤집지 않고** `FakeRedisConnection` 대역으로 claim
을 획득하게 해 오프로드 검사를 살렸고, Redis 부재 시 fail-closed 동작을 고정하는
테스트 2건을 새로 추가했습니다.

키 분리도 함께 했습니다. `CATCHUP_LAST_ATTEMPT_KEY` 가 `SCHEDULE_COLLECTION_CLAIM_KEY`
와 같은 값이라 문서가 약속한 6시간 쿨다운이 성공 경로에서 성립하지 않았습니다.
성공 시 claim 을 즉시 release 하기 때문입니다. 이제 `bidbox:schedule:collection_claim`
(동시 실행 방지 lease)과 `bidbox:schedule:catchup_cooldown`(재시작 폭주 방지)이
분리되었고, 후자는 `finally` 에서 성공 실패와 무관하게 기록됩니다.

### 2.2 q2 — 집계 알고리즘 버전

`get_bid_dataset_summary` 의 재집계 조건이 `source_latest_collected_at` 비교뿐이라,
데이터가 아니라 **집계 알고리즘이 바뀌었을 때** 옛 요약이 계속 유효한 것으로
쓰였습니다. 2026-09-04 의 음수 총액이 그대로 남아 있던 이유입니다.

`bid_dataset_summaries.aggregation_version` 을 추가하고(`server_default="1"`),
announcement 기대 버전을 2로 올려 기존 행이 자동으로 stale 판정을 받게 했습니다.
`_dashboard_stats_cache_key` 와 `_compare_stats_cache_key` 에도 버전을 포함해
캐시가 옛 값을 계속 주는 경로를 막았습니다.

마이그레이션 `e7f8a9b0c1d2` 는 **작성만 했고 운영 DB 에 적용하지 않았습니다.**

### 2.3 q3 — 공급망 보안 검증 job

CI 실패의 실제 원인은 `IGNORE_ARGS` 를 만드는 인라인 `python3 -c "import yaml"` 의
`ModuleNotFoundError: No module named 'yaml'` 이었습니다. 러너 시스템 python3 에
PyYAML 이 없어 스크립트가 죽고 스텝이 exit 1 로 끝났으며, `pip-audit` 은 실행되지도
않았습니다. 이어지던 "Trivy failed but result file not found" 는 2차 증상입니다.

`python3 -c` 를 `uv run python -c` 로 세 곳 교체했습니다. PyYAML 은 전이 의존성으로
uv 환경에 있습니다(6.0.3). npm audit 필터는 `working-directory: frontend` 라
allowlist 를 `../` 로 참조하게 고쳤습니다.

---

## 3. 반려 이력 — 워커 오진단과 그 후일담

1차 시도(`task_a48917d63a07`)를 세 가지 사유로 반려했습니다.

| 반려 사유 | 그 후 확인된 사실 |
| --- | --- |
| 원인을 `pip-audit` 으로 오진단 | 정당한 반려. 실제 원인은 PyYAML 부재였고 수정 후 그 스텝이 통과했습니다 |
| `--strict` 를 "존재하지 않는 플래그" 라며 제거 | 정당한 반려. `-S, --strict` 는 실재합니다 |
| 실행되지 않은 Trivy 의 CVE 2건을 allowlist 에 추가 | **절차상 정당했으나 그 CVE 들은 실재했습니다.** 5장 참조 |

세 번째는 기록해 둘 가치가 있습니다. 반려 시점에 Trivy 는 앞 스텝 실패로 실행조차
되지 않았으므로 그 결과를 근거로 쓸 수 없었습니다. 수정 후 Trivy 가 처음으로 실제
실행되자 **정확히 그 2건**을 검출했습니다. 워커의 결론은 맞았지만 근거는 없었습니다.

---

## 4. 현재 상태

| 항목 | 값 |
| --- | --- |
| main | `f17847b` (원격 반영 완료) |
| 로컬 전량 테스트 | 3,502 passed / 22 skipped / 실패 0 |
| `validate_agent_rules` | 20/20 |
| `actionlint` | 0 errors |
| alembic head | `e7f8a9b0c1d2` (단일) |
| Orca 워크트리 | 전부 회수. 잔류 세션 없음 |

CI run `33849470707` 에서 **Python 의존성 스캔, JS 의존성 스캔, MySQL 통합,
Windows/py3.12 테스트가 모두 통과**했습니다. 이전 run 에서 실패하던 pytest 2건도
해소됐습니다.

---

## 5. 미해결 — 사용자 결정이 필요합니다

### 5.1 P0: Trivy 가 검출한 실제 취약점 2건

```
Trivy failed; CRITICAL/HIGH not in allowlist:
  - CVE-2026-23949 jaraco.context HIGH
  - CVE-2026-24049 wheel HIGH
```

수정 덕분에 Trivy 가 **처음으로 실제 실행**되었고, 컨테이너 이미지에서 두 건을
찾았습니다. 둘 다 `python:3.11-slim` 베이스 이미지에 번들된 패키지입니다
(`setuptools/_vendor` 의 jaraco.context, venv 기본 포함 wheel).

선택지는 둘입니다.

- **A. allowlist 등록**: 이제는 실행된 스캔 결과라는 근거가 있습니다. 사유와 만료일을
  적어 `.github/vulnerability-allowlist.yml` 의 `trivy:` 에 넣습니다. 런타임이 비-root
  이고 두 패키지를 직접 호출하는 경로가 없다는 것이 근거가 될 수 있으나, **그 주장은
  아직 검증되지 않았습니다.**
- **B. 베이스 이미지 갱신 또는 제거**: 근본 해결이지만 이미지 재빌드와 회귀 검증이
  따릅니다.

**게이트를 약화시키는 방식(continue-on-error, 심각도 축소)은 선택지가 아닙니다.**

### 5.2 P0: mypy 24건 (이번 작업과 무관)

`lint-and-validate` job 이 mypy 24 errors in 7 files 로 실패합니다. 로컬에서도
동일하게 재현됩니다.

```
src/tasks/scheduled_tasks.py, src/tasks/retrain_task.py, src/tasks/automation_tasks.py
src/app/services/automation_orchestrator.py, src/app/api/v1/chatbot.py
src/ml/model_registry.py 외
```

대부분 `Session | None` 을 좁히지 않고 쓰는 `union-attr` 입니다. **이번 wave_q 가
만든 것이 아닙니다.** 이전 실패 run(`33829413176`)에서도 같은 job 이 실패했고,
마지막 성공은 2026-09-02 의 `33653723011` 입니다. 그 사이 커밋에서 유입된 부채입니다.

### 5.3 P0: stale summary 재생성

`bid_dataset_summaries` 의 announcement 행은 **여전히
`-6,063,896,128,872,295,352`** 입니다. 버전 필드를 도입했으므로 마이그레이션을
적용하면 다음 조회에서 stale 판정을 받아 재집계가 일어납니다. 다만 그 재집계는
**477초** 걸리고 HTTP 요청 경로에서 실행될 수 있습니다.

순서를 지키십시오.

1. `alembic upgrade head` (운영 DB, 아직 미적용)
2. 재집계를 요청 경로가 아닌 통제된 시점에 수행
3. 그 전에 6.1 의 343건 분류를 끝내면 fast aggregation 으로 넘어갈 수 있습니다

### 5.4 이전 감사에서 이월된 항목

2026-09-04 외부 감사 보고서에서 코드로 확인된 미해결 항목입니다.

| 항목 | 상태 |
| --- | --- |
| catch-up 이 `BidAnnouncement.MAX(collected_at)` 만 봄 (completeness 아님) | 미해결 |
| startup catch-up 이 ARQ `max_jobs` 밖에서 `asyncio.create_task` 로 실행 | 미해결 |
| `base_amount` 가 여전히 `BigInteger` (saturation 2건 잔존) | 미해결 |
| HTTP 요청 경로에서 477초 full rebuild 가능 | 미해결 |
| `agency_top10` 31.97초 (raw JSON 집계) | 미해결 |
| 금액 정책이 `dashboard.py` 에 있고 음수 guard 없음 | 미해결 |
| KB reconciliation 103건 false-positive | 미해결 |
| MySQL 통합 테스트에 금액 케이스 없음 | 미해결 |

감사 보고서의 지적 중 "MySQL integration suite 가 없다" 와 "HEAD 에 연결된 CI run 이
없다" 두 건은 **사실과 달랐습니다.** 전자는 `tests/test_mysql_integration_queries.py`
와 전용 CI job 이 이미 있고 skip 시 실패하도록 강제돼 있습니다. 후자는 run 이
존재했고 실패 중이었습니다.

---

## 6. 다음 세션 착수 순서

1. 5.1 Trivy 2건 결정 (A 또는 B)
2. 5.2 mypy 24건 정리 — 별도 Task 로 분리 권장
3. 5.3 마이그레이션 적용과 통제된 재집계
4. 이후 5.4 의 구조 과제

1과 2를 끝내야 CI 가 초록이 됩니다. **그 전까지는 CI 상태를 게이트로 쓸 수 없습니다.**

---

## 7. 정리 상태

Orca 워커 터미널 3대와 워크트리 3개, 작업 브랜치 4개를 **모두 회수했습니다.**
`orca_settled_session_audit.py` 는 "완료 세션 잔류 없음" 입니다. Docker 스택과
백그라운드 감시 프로세스도 세션 종료와 함께 내렸습니다.
