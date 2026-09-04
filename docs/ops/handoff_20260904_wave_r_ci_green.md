# 인수인계: wave_r CI 초록화와 공급망 게이트 구조 시정

> **작성일**: 2026-09-04
> **Run**: `run_93509f926948`
> **기준 커밋**: `41db0b0` -> `0729aa6` (원격 반영 완료)
> **코디네이터**: Claude Opus 5
> **워커**: 빌더 2대 Antigravity `gemini-3.8-flash-high`, 리뷰어 2대 Antigravity `gemini-3.1-pro-high`, r3 는 코디네이터 직접 수행
> **선행 문서**: [`handoff_20260904_wave_q_ci_recovery.md`](handoff_20260904_wave_q_ci_recovery.md)

---

## 1. 한 줄 요약

CI 를 막고 있던 P0 3건(mypy 24건, Trivy HIGH 2건, Trivy allowlist 구조 결함)을 닫고,
외부 감사가 지적한 공급망 SSoT 모순을 해소했습니다. 그 과정에서 **CI 만 실패하고
로컬은 통과하던 네 번째 원인**을 새로 찾아 함께 고쳤습니다.

---

## 2. 병합된 작업

| Task | 내용 | 병합 커밋 |
| --- | --- | --- |
| (코디네이터) | r3 런타임 빌드 도구 제거, Trivy HIGH 2건 해소 | `1abf9d8` |
| `task_304f542fefbd` | r1 mypy 24건 실제 수정 | `d67a227` |
| `task_ee9b51352b45` | r1 독립 리뷰 (fail 판정, 2건 수용) | (위에 포함) |
| `task_69142134cabc` | r2 공급망 게이트 구조 시정과 SSoT 갱신 | `0729aa6` |
| `task_dd67c3654752` | r2 독립 리뷰 (fail 판정, 1건 수용) | (위에 포함) |
| (코디네이터) | r5 폴백 파서 결함 수정과 정리 | 본 문서와 같은 커밋 |

---

## 3. 외부 감사 지적에 대한 판정

2026-09-04 GPT 분석 보고서의 지적을 코드로 직접 확인한 결과입니다.

| 지적 | 판정 | 근거 |
| --- | --- | --- |
| Trivy `exit-code: 1` 때문에 allowlist 가 구조적으로 동작 불가 | **사실. 수정함** | 스캐너 스텝이 failure 면 후속 필터가 exit 0 을 내도 job conclusion 은 failure |
| 실패 빌드의 SBOM 이 생성되지 않음 | **사실. 수정함** | 두 스텝에 조건이 없어 앞 스텝 실패가 곧 skip |
| npm allowlist 가 패키지 전체를 허용 | **사실. 수정함** | 판정이 `{e['package']}` 만 비교하고 advisory ID 를 무시 |
| `current_state_facts.yaml` 이 실제 CI 정책과 모순 | **사실. 수정함** | 원장은 "보고 전용", `ci.yml` 은 "모두 차단 모드" |
| mypy 24건이 전부 실제 AttributeError 위험 | **과장** | 실제 결함은 1건이었고 나머지는 타입 표현 문제 |
| `Result.rowcount` 는 타입 표현 문제 | **사실** | UPDATE 는 CursorResult 를 돌려주므로 런타임 정상 |
| `chatbot.py:438` 인자 순서가 의심된다 | **아님** | `_run_chat` 은 원래부터 두 호출 규약을 가진 함수이며 호출부는 규약과 일치 |

감사가 놓친 것도 있습니다. **`observability.py` 의 `trace.reset_span` 은 존재하지
않는 API 였고 `except Exception` 이 그 실패를 매번 삼키고 있었습니다.** 짝이 되는
`arq_on_job_start` 도 컨텍스트 매니저를 토큰처럼 저장하고 있었습니다. arq 작업 간
컨텍스트가 누수되던 실제 결함입니다.

---

## 4. r3 — 런타임 빌드 도구 제거 (코디네이터 직접 수행)

인수인계가 권장한 C 안을 채택했습니다. 상세는
[`runtime_build_tool_removal_20260904.md`](runtime_build_tool_removal_20260904.md).

| 대상 | CRITICAL/HIGH |
| --- | --- |
| `main`(`41db0b0`) baseline | 4건 (CVE 2건 × 위치 2곳) |
| 수정본 | **0건** |

인수인계가 미검증으로 남긴 "editable 설치가 setuptools 를 요구할 수 있다" 는 위험은
실측으로 기각했습니다. 이미지 빌드, `import src.app.main`, 모델 5개 전량 로드가 모두
통과합니다.

**위임하지 않은 이유**를 남깁니다. `scripts/orca_auto_approve.py` 의
`classify_docker_execution` 이 docker 직접 실행을 항상 보류하므로 워커는 `docker build`
마다 사람 승인을 기다립니다. 담당자 부재 시간에는 진행이 불가능한 경로입니다.

---

## 5. 리뷰어가 실제로 잡은 것

두 리뷰어 모두 `fail` 을 냈고 지적 4건 중 3건을 수용했습니다.

| 지적 | 수용 | 조치 |
| --- | --- | --- |
| `context.detach` 예외 시 `span.end()` 미실행으로 span 누수 | 수용 | detach 를 try 로 감싸고 span 종료를 finally 로 옮김. 실패 케이스 테스트 추가 |
| `isinstance(result, CursorResult)` 가 조기 반환을 조용히 건너뜀 | 수용 | `cast` 로 교체해 런타임 동작 보존 |
| allowlist `id` 형식 미검증으로 `UNKNOWN` 합성 식별자 등록 우회 가능 | 수용 | CVE/GHSA/PYSEC 형식만 허용하도록 검증 추가 |
| `_run_chat` 첫 분기 payload 판정 변경 | **미수용** | 갈리는 입력은 Session 분기에 int payload 가 오는 경우뿐이고 그 호출 경로가 없으며 새 동작이 더 안전 |

세 번째는 **리뷰어가 없었으면 그대로 병합됐을 실제 우회 경로**입니다. 판정 스크립트가
정체 불명 취약점에 붙이는 합성 식별자를 그대로 예외 목록에 넣을 수 있었습니다.

---

## 6. 새로 찾은 CI 전용 실패 원인

`lint-and-validate` 가 mypy 를 통과한 뒤에도 계속 실패했습니다. 원인은
**`scripts/validate_agent_rules.py` 의 PyYAML 폴백 파서가 최상위 `version` 키를
버리는 것**이었습니다.

```
ci.yml:140   python3 scripts/validate_agent_rules.py --quiet   # 시스템 python3
```

CI 와 pre-commit 은 시스템 `python3` 로 검증기를 돌리고 거기에는 PyYAML 이 없어
폴백 파서가 쓰입니다. 그 파서는 `{"facts": [...]}` 만 돌려주므로
`facts.get("version") != "2.0"` 판정이 폴백 경로에서 **항상** 실패했습니다.
로컬은 PyYAML 이 있어 통과했으므로 로컬 검증으로는 절대 드러나지 않았습니다.

폴백 파서가 최상위 스칼라를 함께 돌려주게 고쳤고, **PyYAML 없는 경로를 강제로 타는
회귀 테스트 2건**을 추가했습니다. 이 테스트가 없으면 같은 격차가 다시 벌어집니다.

---

## 7. 현재 상태

| 항목 | 값 |
| --- | --- |
| main | `0729aa6` 이후 본 커밋 (원격 반영) |
| mypy | 0건 (CI 스텝 통과 확인) |
| actionlint (shellcheck 포함) | 0 issues (docker `rhysd/actionlint` 실측) |
| Trivy CRITICAL/HIGH | 0건 (로컬 컨테이너 실측) |
| actionlint | 0 errors |
| `validate_agent_rules` | 20/20 (PyYAML 유무 양쪽) |
| 로컬 전량 테스트 | 3506 passed / 40 skipped / 실패 0 |
| Orca 워크트리·터미널 | 전부 회수. 잔류 없음 |

---

## 8. 미해결 — 사용자 결정이 필요합니다

담당자 부재 시간에 되돌리기 어려운 조작은 하지 않았습니다.

### 8.1 P0: 마이그레이션 적용과 통제된 재집계

`e7f8a9b0c1d2` 는 여전히 운영 DB 에 **미적용**입니다.
`bid_dataset_summaries` 의 announcement 행은 여전히 `-6,063,896,128,872,295,352` 입니다.

순서를 지켜야 합니다. 재집계가 477초이고 HTTP 요청 경로에서 실행될 수 있습니다.

```
1. DB 백업/체크포인트
2. alembic upgrade head
3. 스키마 확인
4. 통제된 시점에 announcement 요약 재집계 (요청 경로 아님)
5. 값 검증
6. app/worker 교체
7. smoke/E2E
```

**코드 배포 후 마이그레이션 순서로 하면 안 됩니다.** production compose 에 마이그레이션
전용 서비스가 없어 새 ORM 이 없는 컬럼을 요구할 수 있습니다.

### 8.2 다음 Wave 후보 (결정 불필요, 착수 가능)

| 우선순위 | 작업 | 근거 |
| --- | --- | --- |
| P1 | `get_bid_dataset_summary` 의 인라인 재집계 제거 (ARQ enqueue + snapshot 응답) | 첫 요청이 477초를 잡고 동시 요청이 각자 재집계 시작 |
| P1 | 금액 도메인 정책 모듈 분리와 Decimal 완전 통일 | `_coerce_amount` 에 `int(float(...))` 잔존, 정책이 `dashboard.py` 에 묶임 |
| P1 | `base_amount` 범위 검증과 DECIMAL 검토 | saturation 2건은 이미 발생한 실제 손실 |
| P1 | MySQL 금액 통합 테스트 | 운영 방언 회귀 미차단 |
| P1 | startup catch-up 을 ARQ enqueue 로 | `max_jobs` 밖에서 `asyncio.create_task` 실행 |
| P1 | collection completeness ledger | 현재 freshness 만 보고 중간 구멍을 못 봄 |
| P2 | `agency_top10` 31.97초 사전집계 | 운영 레이턴시 |
| P2 | KB reconciliation 103건 기준 재정의 | 구조적 false-positive |

`docs/context/CURRENT_STATE.md` 의 Windows 실기, RPO/RTO, 관측성 backend 는 그대로
열려 있습니다.

---

## 9. 이번 세션이 남기는 운영 교훈

| 교훈 | 근거 |
| --- | --- |
| **로컬 통과는 CI 통과의 근거가 아니다.** 검증기가 인터프리터에 따라 다른 경로를 타면 로컬은 영구히 초록일 수 있다 | 6장. PyYAML 유무로 갈렸고 회귀 테스트가 없었다 |
| **`uv run actionlint` 은 로컬에서 shellcheck 를 실행하지 않는다.** CI 러너에는 shellcheck 가 있어 워크플로 셸 스크립트 지적이 CI 에서만 난다 | `ci.yml:37` 의 SC2086 이 로컬 0 errors 인데 CI 에서 실패. 재현 명령은 `docker run --rm -v $PWD:/repo -w /repo rhysd/actionlint:latest` |
| **런처는 워크트리의 `preamble.txt` 를 재사용한다.** 같은 워크트리에 다음 워커를 띄우기 전에 지워야 한다 | 리뷰어가 빌더의 지시를 다시 집어 같은 작업을 시작했다 |
| Antigravity Claude 계열은 실행 오류로 죽을 수 있다. 다른 계열 리뷰어가 필요하면 `gemini-3.1-pro-high` 가 대안이다 | `claude-sonnet-4-6` 이 Error ID 를 내고 종료 |
| docker 를 쓰는 작업은 위임 대상이 아니다. 자동 승인이 docker 를 항상 보류한다 | 4장 |
| 리뷰어를 건너뛰면 우회 경로가 병합된다 | 5장 세 번째 항목 |

---

## 10. 정리 상태

Orca 워커 터미널 4대(빌더 2, 리뷰어 2), 워크트리 2개, 작업 브랜치 3개를 **모두
회수했습니다.** `orca_settled_session_audit.py` 는 "완료 세션 잔류 없음" 입니다.

리뷰어 워커가 `.orca/capsules/*/review_done.json` 을 강제로 커밋해 gitignore 대상
파일이 `main` 에 들어갔던 것을 추적에서 해제했습니다.

Docker Desktop 은 r3 검증을 위해 이 세션에서 기동했으며 **내리지 않았습니다.**
`refac-bid-box:r3` 와 `refac-bid-box:r3-baseline` 이미지도 남아 있습니다. 필요 없으면
`docker rmi refac-bid-box:r3 refac-bid-box:r3-baseline` 로 정리하십시오.
