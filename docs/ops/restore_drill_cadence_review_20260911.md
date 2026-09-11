# 분기 복구 드릴 정례화 독립 검토 (2026-09-11)

> 작성일: 2026-09-11
> 대상: 브랜치 `kwanbum217/orca-bf1`, 커밋 `201136d` (BF1 task_1c555d0116a2)
> 역할: 독립 리뷰어 (task_9adec02a8071)
> 판정: pass
> 전제: 읽기 전용 검토다. 테스트를 재실행하지 않았고, 드릴·백업·복원 실행, DB 변경, Docker 조작을 하지 않았다. 허용 파일과 `git diff HEAD~1 HEAD` 만 대조했다.

---

## 1. 결론

되돌릴 수 없는 복원이 무인 실행 경로에 들어가지 않는다. `drill`·`restore` 문자열은 주석·독스트링·문서의 사람 절차에만 있고, 점검기와 야간 경로의 실행 호출은 존재하지 않는다. 드릴 미실행·실패만 존재·시각 판독 불능은 모두 정상이 아닌 판정 불가(`UNDECIDABLE`)로 fail-closed되며, 시각 판독은 내용 기반 우선순위만 쓰고 파일명·mtime 추측이 없다. 옛 보고서 호환과 야간 실패 격리도 확인됐다.

차단 결함은 없다. `review_done.json`의 verdict는 `pass`다.

---

## 2. 되돌릴 수 없는 복원의 실행 경로 추적

추적 범위는 `src/app/services/restore_drill_freshness.py` 전체와 `src/tasks/scheduled_tasks.py`의 이번 커밋 추가분이다.

| 경로 | 실행 여부 | 근거 |
| --- | --- | --- |
| 점검기 임포트 | 없음 | `json`·`logging`·`datetime`·`Path`만 임포트하고 (`src/app/services/restore_drill_freshness.py:14-18`), `backup_recovery`를 임포트하지 않는다 |
| 야간 래퍼 임포트 | 점검만 | `_check_restore_drill_freshness`는 `check_restore_drill_freshness`만 임포트한다 (`src/tasks/scheduled_tasks.py:469`). `run_restore_drill`·`restore_mysql_database`·`execute_restore` 호출이 없다 |
| 조건부 실행 | 없음 | `OVERDUE`·`UNDECIDABLE` 분기에서 하는 일은 `logger.warning`과 결과 반환뿐이다 (`:474-483`). 임계를 넘겨도 SQL·DB 생성·덤프 임포트를 추가로 내지 않는다 |
| 문서·주석 언급 | 사람 절차뿐 | 등장은 읽기 전용 선언과 수동 승인 주석뿐이다 (점검기 `:6-10`, 야간 래퍼 `:462-468`, 규약 문서 4장). 코드가 그 문장을 실행하지 않는다 |
| 백업 경로 | 해당 없음 | `backup_schedule_task`의 `execute_backup(execute=True)`은 백업이며, 이번 검토의 금지 대상인 drill·restore가 아니다. 야간 래퍼의 지연 임포트(`:94-105`)도 backup·prune만 끌어온다 |

---

## 3. 미실행 상태를 정상으로 오판하지 않는지 (fail-closed)

`evaluate_drill_freshness`는 `latest_drill_at`이 `None`이면 세 갈래 모두 `UNDECIDABLE`로 돌린다 (`src/app/services/restore_drill_freshness.py:113-136`).

| 경우 | 분류 | 근거 |
| --- | --- | --- |
| 보고서 디렉터리 빔 | `UNDECIDABLE` | `find_latest_successful_drill`이 디렉터리 부재·비디렉터리·빈 목록에서 `(None, None, 0, 0)`을 돌린다 (`:192-196`). 사유는 보고서 부재 문구다 |
| 실패한 드릴만 존재 | `UNDECIDABLE` | `success is not True`는 건너뛰므로 (`:214`) 성공 후보가 0이면 성공 부재 사유로 판정 불가다 |
| 성공 보고서 있으나 시각 판독 불능 | `UNDECIDABLE` | 시각 없는 성공 보고서는 후보로 세되(`successful_candidates` 증가) 최신 시각을 갱신하지 않고 (`:217-220`), 사유는 유효 시각 판독 불능 문구다 |
| 정상 오판 경로 | 없음 | `None` 분기에 `OK` 반환이 없고, `is_overdue`는 `False`, `is_undecidable`은 `True`, 종료 코드는 2다 |

어느 경우도 `OK`로 분류되지 않으므로, 드릴을 한 번도 안 한 상태가 정상으로 보이는 일은 없다.

---

## 4. 시각 판독 우선순위와 mtime 미의존

`extract_report_timestamp`의 순서는 고정이다 (`src/app/services/restore_drill_freshness.py:65-93`).

1. 1순위: 최상위 `started_at` (`:76-79`)
2. 2순위: 구 보고서 하위 호환 `g1_verification.file.report.generated_at` (`:82-91`, `isinstance` 가드로 예외 없음)
3. 그 밖 추측 없음: 둘 다 없으면 `None`을 돌린다

파일명 날짜나 파일 mtime을 읽는 코드(`stat`·`st_mtime`·파일명 파싱)가 점검기와 야간 래퍼 어디에도 없다. `find_latest_successful_drill`은 glob으로 나열만 하고 (`:195`), 시각은 보고서 내용에서만 뽑는다. 실제 옛 보고서 `data/backups/restore_drill_report_20260911.json`에는 최상위 `started_at`이 없고 중첩 `generated_at`(`2026-09-11T07:04:08`)만 있어 후퇴 경로로 판정된다.

---

## 5. 보고서 타임스탬프 추가와 옛 형식 호환

`scripts/backup_recovery.py:285-304`의 `_drill_rep`은 `finished_at`을 한 번 만들고 `started_at`(드릴 시작)·`finished_at`·`total_duration_seconds`(둘의 차)를 함께 남긴다. 기존 최상위 키를 지우거나 바꾸지 않았고, 테스트가 `schema`부터 `success`까지 14개 키 보존과 `RESTORE_DRILL_REPORT_V2` 유지를 단언한다 (`tests/test_restore_drill_freshness.py:89-106`). 판독부는 옛 필드 부재를 예외 없이 `None`으로 처리하므로 옛 보고서도 깨지지 않는다.

---

## 6. 야간 배선, 로그 수준, 실패 격리

`nightly_schedule_task`와 `development_data_refresh_task`의 후속 단계에 같은 점검을 붙이고 결과를 `outcome["restore_drill_freshness"]`에 담는다 (`src/tasks/scheduled_tasks.py:288-289`, `:358`). 새 크론 등록이나 새 스케줄러 함수는 없고, `_check_restore_drill_freshness`는 장식자 없는 헬퍼다.

로그 수준은 분기되어 있다.

- 초과(`OVERDUE`): `logger.warning` (`:474-478`)
- 판정 불가(`UNDECIDABLE`): `logger.warning` (`:479-483`)
- 정상(`OK`): `logger.info` (`:485`)

실패 격리는 `_check_mysql_stats_freshness`와 같다. 본문을 try로 감싸고, 예외를 밖으로 올리지 않고 `{"status": "failed", "error": ...}`를 돌려주고 (`:487-489`), 파일 단위 읽기 실패도 건너뛴다 (`src/app/services/restore_drill_freshness.py:203-208`). 그래서 점검이 깨져도 수집·스냅샷 재집계를 포함한 야간 작업 전체가 중단되지 않는다.

---

## 7. 임계값 문서, 범위, 테스트, 빌더 보고

규약 문서 2장은 정례 90일(분기 기준)과 경고 80일(10일 전 선제 경고: 덤프 적재·G1 대조·디스크 확보·승인 준비)을 표와 사유로 적는다 (`docs/ops/restore_drill_cadence_20260911.md:19-35`). 코드 기본값과 일치한다.

`git diff HEAD~1 HEAD --name-only`는 다음 다섯뿐이다.

- `scripts/backup_recovery.py`
- `src/app/services/restore_drill_freshness.py` (신설)
- `src/tasks/scheduled_tasks.py`
- `tests/test_restore_drill_freshness.py` (신설)
- `docs/ops/restore_drill_cadence_20260911.md` (신설)

`CURRENT_STATE`·facts·`pyproject.toml` 변경, 마이그레이션, 새 외부 패키지가 없다. 신규 테스트 13개는 성공 선별·판정 불가 3종·구 보고서 후퇴·mtime 미의존·경계 판정·호출 부재·로그 분기·예외 격리·야간 outcome 배선을 고정하며, 빈 테스트가 없고 기존 테스트 파일을 수정하지 않았다.

`.orca/capsules/task_1c555d0116a2/worker_done.json`이 있다. `schema=ORCA_WORKER_DONE_V2`, `version=2.1.0`, `task_id=task_1c555d0116a2`, `branch=kwanbum217/orca-bf1`, `commit=201136d`, `changed_files` 다섯, `blocking_issues=[]`를 갖췄다. 이 검토는 그 검증 명령을 재실행하지 않았다.

---

## 8. 체크리스트 요약

| id | 답 | 결함 |
| --- | --- | --- |
| report_timestamps_added | yes | 아니오 |
| success_only_candidates | yes | 아니오 |
| undecidable_not_ok | no | 아니오 |
| legacy_fallback | yes | 아니오 |
| filename_or_mtime_guess | no | 아니오 |
| threshold_documented | yes | 아니오 |
| nightly_wired | yes | 아니오 |
| drill_invoked | no | 아니오 |
| failure_isolated | yes | 아니오 |
| current_state_touched | no | 아니오 |
| new_cron_or_package | no | 아니오 |
| test_quality | no | 아니오 |
| scope_exceeded | no | 아니오 |
| worker_done_report_present | yes | 아니오 |
