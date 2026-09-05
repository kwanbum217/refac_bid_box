# 정기 백업 보존 정책 및 디스크 상한 강제(R-08) 분석 보고서

> **작성일**: 2026-09-05
> **태스크 ID**: `task_c7da7b57943f` (R-08)
> **관련 문서**: [`docs/ops/backup_recovery_runbook.md`](../ops/backup_recovery_runbook.md), [`src/app/core/config.py`](../../src/app/core/config.py)

---

## 1. 배경 및 문제 정의

2026-09-05 외부 진단 보고서(R-08)에 따르면, 기존 정기 백업 스케줄(`src/tasks/scheduled_tasks.py:backup_schedule_task`)은 `prune_snapshots` 함수를 `delete=False`로 고정 호출하고 있었습니다.
이로 인해:
1. 보존 개수 설정값(`BACKUP_RETENTION_COUNT=7`)이 디스크상 실제 최대 스냅샷 개수를 강제하지 못하고 삭제 후보만 계산하여 출력했습니다.
2. 백업이 실행될 때마다 스냅샷이 누적되어 스토리지 용량이 고갈될 위험이 있었으며, 디스크 고갈 시 다음 백업이 실패하고 복구 수단을 상실할 우려가 있었습니다.
3. 스토리지 디스크 여유 공간 부족에 대한 경보 체계가 연결되어 있지 않았습니다.

---

## 2. 변경 설계 및 안전장치

### 2.1 자동 정리 실제 적용 및 설정 정합성
- `src/tasks/scheduled_tasks.py`의 `backup_schedule_task`에서 `prune_snapshots` 호출 시 `delete=True`를 명시하여, 정기 백업 완료 후 `BACKUP_RETENTION_COUNT`(기본 7개)를 초과하는 오래된 스냅샷이 실제로 삭제되도록 구현했습니다.
- `src/app/core/config.py`의 주석을 실제 동작과 일치하도록 갱신하였습니다.

### 2.2 다중 안전장치 (Fail-Closed Guard)
스냅샷 삭제는 비가역적 조작이므로 다음의 안전장치를 `scripts/backup_snapshots.py:prune_snapshots`에 구현했습니다:
1. **보존 개수 안전 하한**: `retain_count < 1`인 경우 `ValueError`를 발생시키며 최소 1개 이상의 보존을 강제합니다.
2. **보존 대상 수량 보장**: 삭제 전 남길 스냅샷(`keep`)과 삭제 대상(`stale`)의 분할을 검증하고, 삭제 후에도 잔여 스냅샷이 `min(len(candidates), retain_count)` 미만으로 떨어지는 경로가 없음을 보장합니다.
3. **보존 대상 무결성 검증**: 남겨둘 스냅샷에 매니페스트(`backup_manifest.json`)가 존재하는 경우 `verify_snapshot`을 통해 손상 여부를 검증합니다. 만약 보존 대상이 손상되어 있으면 유효 백업 상실을 막기 위해 **삭제 판정 실패로 처리하고 아무것도 삭제하지 않습니다(fail-closed)**.
4. **경로 격리 검증**: 삭제 대상이 스냅샷 디렉토리의 직계 하위인지 확인하며 심볼릭 링크나 상위 경로 탈출을 차단합니다.

### 2.3 디스크 여유 공간 경보
- `BACKUP_DISK_MIN_FREE_GB: float = 5.0` 설정을 `src/app/core/config.py`에 추가했습니다.
  - **기본값 근거**: DB 덤프 압축본(수백 MB), ChromaDB 및 ML 아카이브 등 단일 통합 백업 1회분 크기(약 1GB 내외)와 임시 압축 버퍼 및 OS 최소 안전 마진을 감안하여 5.0GB로 설정.
- `src/tasks/scheduled_tasks.py`에 `check_backup_disk_space` 헬퍼를 도입하여 백업 실행 전 스토리지 여유 공간을 측정하고, 임계값 미달 시 기존 `src/tasks/notifier.py:notify` 경로로 경보를 발송하도록 연결했습니다 (새로운 알림 체계 중복 생성 금지 원칙 준수).

---

## 3. 설정값이 강제하는 것과 강제하지 않는 것

| 설정 항목 | 강제하는 것 | 강제하지 않는 것 |
| --- | --- | --- |
| `BACKUP_RETENTION_COUNT` | `BACKUP_SCHEDULE_ENABLED=true` 정기 백업 시 디스크상 스냅샷 최대 N개 강제 (오래된 스냅샷 자동 삭제) | 수동 백업(`make backup`) 실행 시 자동 삭제하지 않음; 스케줄 비활성화(`BACKUP_SCHEDULE_ENABLED=false`) 시 삭제 미수행; 수동 `prune`은 `--delete` 플래그 없이는 삭제 미강제 |
| `BACKUP_DISK_MIN_FREE_GB` | 백업 전 여유 공간이 임계값 미만일 때 기존 notifier를 통한 경보 발송 강제 | 경보는 관측성 알림이며, 백업 실행을 강제 중단하지는 않음 |

---

## 4. 검증 결과

### 4.1 단위 및 회귀 테스트
`tests/test_backup_schedule.py`에 다음 5개 회귀 테스트를 추가하여 총 10개 테스트 전량 통과를 확인했습니다:
1. `test_retention_prune_deletes_excess_snapshots_when_delete_is_true`: 보존 개수 초과 시 오래된 스냅샷 실제 삭제 및 보존 수량 유지 확인.
2. `test_retention_fail_closed_on_corrupt_manifest`: 보존 대상 스냅샷 매니페스트 손상 시 아무것도 삭제하지 않는 fail-closed 동작 확인.
3. `test_retention_never_leaves_less_than_retain_count`: 후보 개수가 retain_count 이하일 때 0건 삭제 및 안전 보존 확인.
4. `test_backup_task_executes_retention_deletion`: 정기 백업 태스크 실행 시 보존 정책에 따른 초과 스냅샷 실제 삭제 통합 확인.
5. `test_backup_task_notifies_low_disk_space`: 디스크 여유 공간 부족 시 기존 notifier 경보 발송 확인.

실행 결과:
```
uv run pytest tests/test_backup_schedule.py -q
..........                                                               [100%]
10 passed in 0.50s
```

### 4.2 정적 분석 및 규칙 검증
- `uv run mypy src`: Success: no issues found in 93 source files
- `python3 scripts/validate_agent_rules.py --quiet`: 검증 통과: 20/20 건
