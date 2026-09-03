# 작업 분석 보고서: PSI 평가 윈도우 쿼리 반영 및 비파괴 모니터링 구축

> **Task ID**: `task_7aecb23da179`
> **Run ID**: `run_971584ddb4a0`
> **작성일**: 2026-09-03
> **작성자**: Orca Worker (Builder)
> **상태**: 완료 (Completed)

---

## 1. 작업 개요 및 배경

### 1.1 배경
2026-09-03 외부 감사에서 P1 결함으로 지적된 사항을 조치했습니다:
1. `drift_monitor_task`에서 `evaluation_window_days=7` 인자가 로그와 결과 JSON에만 기록되고, 실제 데이터 조회 함수인 `build_training_dataset`에는 날짜 조건이 없어 매일 전체 DB 이력을 풀 스캔하는 결함.
2. 장기 전체 이력을 읽음으로써 최근의 데이터 분포 변화가 희석되어 드리프트 탐지 신뢰도가 저하되는 문제.
3. 모니터링 관측 경로가 실행될 때마다 `data/feature_store/dataset_{category}.parquet` 학습용 캐시를 덮어써서 관측이 운영 학습 데이터를 변경시키는 결함.

### 1.2 목표
- `build_training_dataset`에 `start_at`, `end_at`, `persist` 키워드 인자를 추가하고 개찰일(`BidResult.rl_openg_dt`) 기준 `[start_at, end_at)` 반열림 구간 필터링 적용.
- `persist=False` 지원으로 모니터링 경로에서 Parquet 파일 덮어쓰기 방지.
- `drift_monitor_task`에서 `evaluation_window_days`를 기반으로 `[now - N days, now)` 구간을 계산해 전달.
- 표본 부족(0건 또는 100건 미만) 시 조용히 통과하지 않고 `INSUFFICIENT_DATA` 상태를 명시적으로 기록.
- 기존 학습 경로와의 100% 하위 호환성 유지.

---

## 2. 변경 내역

### 2.1 `src/ml/dataset.py`
- `build_training_dataset` 시그니처에 `start_at: datetime | str | None = None`, `end_at: datetime | str | None = None`, `persist: bool = True` 추가.
- `start_at` 지정 시 `BidResult.rl_openg_dt >= start_at` (시작점 포함) where 절 적용.
- `end_at` 지정 시 `BidResult.rl_openg_dt < end_at` (종료점 제외) where 절 적용.
- `persist=False` 인 경우 디렉터리 생성 및 `df.to_parquet(...)` 호출을 건너뛰고 정제된 `DataFrame`만 반환하도록 변경.

### 2.2 `src/tasks/scheduled_tasks.py`
- `drift_monitor_task`에서 `now = utcnow()`, `start_at = now - timedelta(days=evaluation_window_days)`, `end_at = now` 계산.
- `build_training_dataset(db, category_code=category, start_at=start_at, end_at=end_at, persist=False)` 호출로 윈도우 구간 및 비파괴 플래그 적용.
- `df_raw.empty` 분기에서 `evaluation_window_days` 및 윈도우 구간 정보를 `metrics_summary`에 포함하여 `INSUFFICIENT_DATA`로 기록.

### 2.3 `tests/test_drift_monitor_window.py`
- 기본 인자 및 `persist=True` 시 Parquet 파일 생성 검증.
- `persist=False` 시 Parquet 파일 미생성 및 메모리 프레임 반환 검증.
- `[start_at, end_at)` 반열림 구간 경계값(시작점 포함, 끝점 제외, 윈도우 밖 제외) 검증.
- `require_announcement=False` 경로에서의 윈도우 필터 적용 검증.
- `drift_monitor_task`의 7일 윈도우 계산 및 `persist=False` 전달 검증.
- 윈도우 내 데이터 부재(0건) 시 `INSUFFICIENT_DATA` 기록 검증.

### 2.4 `docs/ops/psi_drift_monitoring.md`
- 평가 윈도우 계약, 비파괴 모니터링 원칙, 반열림 구간 사양, 결측 집단 평가 규칙을 문서화.

---

## 3. 검증 결과

### 3.1 신규 및 관련 테스트
```
tests/test_drift_monitor_window.py (6 passed)
tests/test_psi_drift_wiring.py (9 passed)
tests/test_drift_subgroup.py (8 passed)
tests/test_scheduled_tasks.py (14 passed)
합계: 37 passed in 4.43s
```

### 3.2 전체 회귀 테스트
- 명령: `uv run pytest tests/ -q -m 'not data_assets'`
- 결과: 통과 (3287 passed, 35 skipped, 3 deselected in 129.5s)
- 참고: 격리 워크트리 환경상 `data_assets` 마커 제외 시 전체 테스트 무결성 확인.

### 3.3 에이전트 규칙 검증
- 명령: `python3 scripts/validate_agent_rules.py --quiet`
- 결과: 통과 (19/19 건 통과)

---

## 4. 리뷰 체크리스트 확인

| 항목 ID | 점검 질문 | 확인 결과 | 근거 |
| --- | --- | --- | --- |
| `window_not_applied` | 날짜 인자가 쿼리에 실제로 적용되지 않고 메타데이터에만 남는가? | No (결함 없음) | `src/ml/dataset.py`에서 `BidResult.rl_openg_dt >= start_at` 및 `< end_at` where 절 적용 확인 |
| `parquet_still_written` | 모니터링 경로에서 여전히 Parquet을 쓰는가? | No (결함 없음) | `drift_monitor_task`가 `persist=False`로 호출하며 `to_parquet` 미호출 확인 |
| `training_path_changed` | 기본값에서 학습 경로 동작이 달라졌는가? | No (결함 없음) | 기본값 `start_at=None`, `end_at=None`, `persist=True`로 기존 동작 100% 보존 |
| `boundary_unspecified` | 구간 경계 포함 여부가 테스트로 고정되지 않았는가? | No (결함 없음) | `test_build_training_dataset_half_open_window_filtering`으로 시작점 포함/끝점 제외 고정 |
| `silent_insufficient` | 표본 부족을 조용히 통과시키는가? | No (결함 없음) | 0건 및 100건 미만 표본에서 `INSUFFICIENT_DATA` 명시적 반환 및 기록 확인 |
| `monitoring_touched` | `src/ml/monitoring.py`를 수정했는가? | No (결함 없음) | `src/ml/monitoring.py` 미수정 (읽기만 수행) |
| `scope_creep` | 허용 범위 밖 파일을 수정했는가? | No (결함 없음) | 허용된 5개 파일 범위 내에서만 작성/수정 완료 |
