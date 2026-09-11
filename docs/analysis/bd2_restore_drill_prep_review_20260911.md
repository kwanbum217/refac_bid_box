# BD2 분기 복구 드릴 준비 산출물 독립 검토

> **작성일**: 2026-09-11
> **상태**: 독립 리뷰 완료
> **대상 Task**: `task_81954ca1a851` (빌더), `task_618841d639f2` (리뷰어)
> **대상 커밋**: `35706c968d3097264af991ee1d5365ba49da3936`
> **판정**: pass

---

## 1. 검토 범위

브랜치 `kwanbum217/orca-bd2` HEAD `35706c96` 하나와 그 커밋이 바꾼 세 파일만 본다. 테스트·드릴·백업·복원·Docker 는 실행하지 않았다.

| 항목 | 값 |
| --- | --- |
| 커밋 | `35706c968d3097264af991ee1d5365ba49da3936` |
| 제목 | `docs: 분기 복구 드릴 실행 절차서 작성 및 런북 RPO/RTO 확정값 갱신` |
| 변경 파일 | `docs/ops/backup_recovery_runbook.md`, `docs/ops/restore_drill_procedure_20260911.md`(신설), `tests/test_restore_drill_docs.py`(신설) |
| 통계 | 3 files, +277 / -9 |
| 작업 트리 | 깨끗함 (`git status` 공란, 빌더 커밋 기준) |

---

## 2. 체크리스트 판정 요약

| id | 질문 | answer | 결함 |
| --- | --- | --- | --- |
| rpo_rto_filled | 런북 RPO/RTO 확정값·공란 해소 | yes | 아니오 |
| basis_and_date | 확정일·근거 | yes | 아니오 |
| procedure_completeness | 전제·명령·합격·실패·운영 DB 미영향 | yes | 아니오 |
| pass_criteria_beyond_time | 행 수·스키마 대조 | yes | 아니오 |
| drill_executed | 드릴·백업·복원 실제 실행 | no | 아니오 |
| tools_modified | `scripts/backup_recovery*.py` 수정 | no | 아니오 |
| out_of_scope_files | `src/` 또는 CURRENT_STATE 수정 | no | 아니오 |
| machine_checkable | 문서 표지 기계 고정 | yes | 아니오 |
| new_package_added | 새 외부 패키지 | no | 아니오 |
| test_quality | 빈/동어반복 테스트 또는 기존 테스트 수정 | no | 아니오 |
| scope_exceeded | 허용 세 파일 밖 수정 | no | 아니오 |
| worker_done_report_present | 빌더 `worker_done.json` 필수 필드 | yes | 아니오 |

차단 결함 0건. 실효 판정은 pass 다.

---

## 3. 최우선 판정

### 3.1 런북 RPO/RTO 공란 해소

표만이 아니라 산문도 읽었다. `docs/ops/backup_recovery_runbook.md` 46~66행과 253~256행이 대상이다.

확정값:

- RPO **24시간**, RTO **4시간**, 확정일 **2026-09-06**
- 근거: `docs/context/CURRENT_STATE.md` 의 `rpo_rto` 기계 사실, 일 1회 `backup_schedule_task`, 분기 복원 드릴

사라진 공란 표지(커밋 `35706c96` 본문 검색 0건):

- `기입 필요`
- `운영 담당자가 결정하여 기입`
- `인위적인 수치를 단정하지 않으며`
- `공란으로 둡니다`
- `목표값이 미확정`

4.4.2절의 옛 문장(목표값 미확정이므로 도구가 합격/불합격을 내지 않는다)은, 확정 SLA 와 `total_duration_seconds` 를 대조하고 최종 합격은 절차서 기준으로 코디네이터가 판정한다는 문장으로 바뀌었다. 도구를 수정하지 않은 범위와 맞다.

### 3.2 합격 기준이 시간만이 아닌가

절차서 4절 표는 RTO 시간 외에 행 수 대조와 스키마 대조를 합격 조건으로 둔다.

| 검증 | 절차서 근거 | 기계 산출물 |
| --- | --- | --- |
| 행 수 | `restore_drill_procedure_20260911.md:86` `verify_migration.py` `[5/5]` | `g1_verification.success`, 종료 코드 |
| 스키마 | 같은 파일 87행 `[4/5]` | 동일 |
| 실패 연결 | 5.1절 항목 4·8 | `g1_verification.success == false` 또는 `success != true` 또는 `echo $? != 0` |

`scripts/backup_recovery.py` 의 `run_drill_g1_verification`(216~260행)은 실제로 `scripts/verify_migration.py` 를 호출하고, G1 실패 시 `RuntimeError` 로 단계를 실패시킨다. `main()` 드릴 분기는 `return 0 if rep.get("success") else 1`(543행)이다. 산문 권고로 끝나지 않는다.

### 3.3 드릴 미실행

실행 흔적은 없다.

- 커밋 파일 목록에 리포트 JSON·격리 DB 덤프·`/tmp` 아티팩트 없음
- `data/backups/` 에 `restore_drill_report*.json` 없음, `snapshots/` 디렉터리 없음
- `/tmp/refac_bid_box_restore_drill` 없음
- 빌더 `worker_done.json` 검증 항목은 pytest 와 `validate_agent_rules` 뿐

계약 위반(실제 드릴 실행)은 없다.

### 3.4 기존 drill 도구 재사용

절차서 3.1절 인자 표는 `scripts/backup_recovery.py:491-496` 과 같다. `--snapshot-dir`(필수), `--target-dir`(필수), `--report-path`, `--db-name`, `--keep-artifacts`. 새 스크립트 없음. `scripts/` 는 이 커밋에서 0파일 변경.

실행 명령은 런북과 같이 `python3 scripts/backup_recovery.py` 다. 절차서 안에서 `uv run python` 과 `python3` 을 섞지 않는다.

예시 스냅샷 경로 `data/backups/snapshots/snapshot_20260902_153000` 는 이 커밋이 새로 지어낸 값이 아니다. 런북의 verify·restore·drill 예시와 같은 자리표시자다. 이 워크트리에 해당 디렉터리는 없다. 운영 시 실존 스냅샷으로 바꿔야 한다.

---

## 4. 절차서 완결성

| 요구 | 위치 | 판정 |
| --- | --- | --- |
| 실행 전 조건 | 2절. 스냅샷 `verify` `[PASS]`, 격리 `--target-dir`, 서비스 상태, 단독 실행, 디스크 | 충족 |
| 실제 명령 | 3.2·3.3절. 기존 `drill` 인자만 사용 | 충족 |
| 합격 기준 | 4절. 시간 + 행 수 + 스키마 + 가중치 + Chroma + 정리 + 종료 코드 | 충족 |
| 실패 판정·기록 | 5절. 종료 코드, `success`, `errors`, `g1_verification.success`, RTO 초과, `RESTORE_DRILL_REPORT_V2` | 충족 |
| 운영 DB 미영향 | 6절. `_restore_drill` 접미사, `drop_mysql_database`, `cleanup_drill_target_dir` 의 루트·cwd·프로젝트 루트 거부 | 충족 |

`cleanup_drill_target_dir`(`scripts/backup_recovery_core.py:319-329`)가 루트·cwd·프로젝트 루트 및 상하위 겹침을 거부한다는 성질을 절차서 2절과 6.2절이 사람에게 `--target-dir` 를 아무 데나 주지 말라고 적었다.

---

## 5. 테스트 품질

`tests/test_restore_drill_docs.py` 는 신설 6건이다. 기존 테스트 파일은 수정되지 않았다. `assert True` 나 빈 본문은 없다.

고정하는 표지:

- 런북: `24시간`, `4시간`, `2026-09-06`, `docs/context/CURRENT_STATE.md`, 공란 표지 5종 부재
- 절차서 CLI: `drill`, `--snapshot-dir`, `--target-dir`, `--report-path`, `--db-name`, `--keep-artifacts`
- 합격 기준: `total_duration_seconds`, `행 수`, `스키마`, `verify_migration.py`, `g1_verification`
- 격리: `restore_drill`, `drop_mysql_database`, `cleanup_drill_target_dir`
- 실패 기록: `RESTORE_DRILL_REPORT_V2`, `report-path`, `errors`

문자열 포함 검사다. Capsule 이 허용한 방식이다. `drill` 이나 `errors` 단독은 약하지만, 필수 인자·금지 표지·G1 필드와 묶여 있어 아무 문서나 통과하지는 않는다.

---

## 6. 빌더 보고

경로: `.orca/capsules/task_81954ca1a851/worker_done.json`

있는 필드: `schema`, `version`, `task_id`, `status`, `branch`, `commit`, `commit_count`, `commit_shas`, `changed_files`, `read_files`, `verification`, `verdict`, `blocking_issues`.

빌더 Capsule 이 Level 1 게이트 6 실패 조건으로 적은 `version`, `task_id`, `branch`, `commit_count`, `commit_shas`, `changed_files`, `blocking_issues` 는 모두 있다. 템플릿의 `dispatch_id` 는 없다. 빌더 `report_schema` 필수 목록에는 없어 차단하지 않는다.

---

## 7. 비차단 지적

1. 테스트는 절 단위가 아니라 문서 전체 부분 문자열을 본다. `행 수`/`스키마`가 합격 표 밖에도 있으면 통과한다. 같은 테스트가 `g1_verification` 과 `verify_migration.py` 를 같이 요구하므로 실효는 있다.
2. 예시 JSON 의 `created_at_to_drill_start_seconds: 763200.0`(약 8.85일)은 24시간 RPO 를 넘긴다. 스키마 예시이지 합격 예시로 읽히면 오해할 수 있다.
3. 드릴 CLI 는 RTO 4시간 초과를 종료 코드로 자동 실패시키지 않는다. 런북 4.4.2와 절차서 5.1이 `total_duration_seconds` 대조를 코디네이터 판정으로 명시한다. 도구 미수정 범위와 맞다.
4. 빌더가 보고한 전량 `4432 passed / 32 skipped` 는 이 리뷰가 재실행하지 않았다. Capsule 지시다.

---

## 8. 잔여

- 코디네이터 Level 1 전량 게이트 독립 재실행(공유 DB/Redis 점유 해소 후)
- 두 Task 병합 뒤 코디네이터 직렬 복원 드릴 실측. 그때 `--snapshot-dir` 는 실존 스냅샷으로 치환
