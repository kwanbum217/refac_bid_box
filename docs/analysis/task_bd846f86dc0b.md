# 스냅샷 매니페스트 부재 구간 해소 분석 (task_bd846f86dc0b)

> **작성일**: 2026-09-06
> **대상**: `scripts/backup_snapshots.py`, `tests/test_backup_recovery.py`
> **과제**: 매니페스트 없는 스냅샷이 목록에서 사라지고 보존 검증도 건너뛰는 두 경로를 닫고, 심볼릭 링크 문구와 동작의 불일치를 바로잡는다.

---

## 1. 확인된 결함 세 가지

| 번호 | 위치 | 결함 |
| --- | --- | --- |
| 1 | `list_snapshots` 수집 분기 | `manifest_file.exists()` 가 참일 때만 목록에 추가하여 매니페스트 없는 디렉터리가 통째로 감춰진다 |
| 2 | `prune_snapshots` 보존 검증 분기 (`validate_retained`) | 매니페스트 존재 시에만 `verify_snapshot` 을 호출하여 매니페스트 없는 보존본이 검증 없이 `retain_count` 를 채운다 |
| 3 | `prune_snapshots` 삭제 대상 심볼릭 링크 분기 | 문구는 "삭제 대상에서 제외됩니다" 라고 말하지만 `errors` 에 적재해 전체 정리를 중단(fail-closed)하므로 문구와 동작이 어긋난다 |

---

## 2. 변경 내용

### 2.1 목록 노출 (`list_snapshots`)

- 매니페스트 없는 하위 디렉터리도 목록에 포함하되 `valid=False`, `created_at`/`head_commit` 은 `"unknown"`, 사유는 `error` 키(`매니페스트 파일 없음`)로 구분해 표시한다.
- 유효 판정을 무효로 바꾸지 않았다. 매니페스트가 있는 항목의 판정 로직은 그대로이다.

### 2.2 보존 검증 (`prune_snapshots`, `validate_retained`)

- 보존 대상(`keep`)은 매니페스트 유무와 관계없이 항상 `verify_snapshot` 으로 검증한다. `verify_snapshot` 은 매니페스트 부재 시 `(False, ["매니페스트 파일 없음: ..."], {})` 을 반환하므로, 매니페스트 없는 보존본은 `보존 대상 스냅샷 무결성 손상 ({이름}): 매니페스트 파일 없음 ...` 오류와 함께 fail-closed 로 아무것도 삭제하지 않는다.
- 매니페스트가 있는 보존본의 기존 검증은 그대로 유지하였다. 별도 분기를 두지 않고 단일 호출로 합쳐 특수 경로를 없앴다.

### 2.3 심볼릭 링크 문구와 동작 일치

- **정본 결정: 중단(fail-closed)을 유지하고 문구를 동작에 맞췄다.**
- 메시지를 `심볼릭 링크는 안전을 위해 삭제 대상에서 제외됩니다` 에서 `심볼릭 링크 감지로 정리를 중단합니다` 로 바꾸었다.
- 판단 근거: 캡슐 계약상 안전 쪽 기본값은 중단이며, 제외 후 계속 삭제로 바꾸면 삭제 허용이 넓어져 "삭제 조건을 넓히는 변경은 금지" 조항에 저촉된다. 제외-계속이 안전하다는 근거도 Task 범위에서 확보할 수 없으므로, 동작(중단)을 정본으로 삼고 문구를 고치는 쪽이 유일하게 안전한 선택이다.
- 기존 안전장치(`retain_count` 최소 1, 분할 정합성, 경로 이탈 방지, 삭제 후 잔여 개수 확인)는 그대로이며 삭제 조건을 넓히지 않았다.
- 파일 분리 리팩터링은 하지 않았다.

---

## 3. 추가된 테스트 (`tests/test_backup_recovery.py`, `tmp_path` 사용)

1. `test_list_snapshots_includes_manifestless_as_invalid`: 매니페스트 없는 디렉터리가 목록에 무효 상태(`valid is False`, `unknown` 표기)로 드러남을 확인한다.
2. `test_prune_retained_manifestless_fails_closed`: 매니페스트 없는 보존 대상이 있으면 `deleted is False`, `매니페스트 없음` 오류 기록, 양쪽 디렉터리 보존을 확인한다.
3. `test_prune_symlink_stale_aborts_with_matching_message`: 삭제 대상 심볼릭 링크가 있으면 전체 중단(`deleted is False`), 메시지에 `중단` 포함·`제외` 미포함, 심볼릭 링크 잔존을 확인한다.

---

## 4. 검증 결과

- `tests/test_backup_recovery.py` 단독: 20건 전부 통과 (기존 17건 + 신규 3건).
- 3종 백업 테스트 묶음(`test_backup_recovery.py`, `test_backup_schedule.py`, `test_backup_fail_closed.py`): 48건 통과, 2건 실패.
  - 실패 2건은 모두 `tests/test_backup_schedule.py` 의 `test_retention_prune_deletes_excess_snapshots_when_delete_is_true` 와 `test_backup_task_executes_retention_deletion` 이다.
  - 원인: 두 테스트가 매니페스트 없는 빈 디렉터리를 만들고 삭제를 기대하는데, 새 계약(매니페스트 없는 보존본은 fail-closed)이 정확히 그 삭제를 막는다. 구현이 계약대로 동작한 결과이며, 테스트 쪽 설정이 옛 동작을 전제로 한 레거시 결함이다.
  - 해당 파일은 본 Task 의 `allowed_write_files` 범위 밖이라 수정하지 않았다. 코디네이터에게 `ask` 로 진행 방침을 질의하였으나 600초 시간 초과로 응답이 없었고, `check` 에서도 수신 메시지가 없었다.
- 남은 검증(`tests/` 전량 `-m 'not data_assets'`, `validate_agent_rules.py --quiet`)은 커밋 후 worker_done.json 기록 시점에 실행하였다.

---

## 5. 남은 일

- `tests/test_backup_schedule.py` 의 위 2건에 정상 매니페스트를 갖추도록 테스트 설정을 고치는 작업이 필요하다. 범위 밖 파일이므로 코디네이터 결정(범위 확대 허용 또는 별도 Task 배정)이 필요하다.
- 프로덕션 동작에는 영향이 없다. 실제 백업이 만드는 스냅샷에는 항상 매니페스트가 있으므로 새 fail-closed 분기는 비정상 보존본이 있을 때만 발동한다.
