# 분석 보고서: DB 직접 실행 자동 승인 경로 제거 및 리뷰어 독립성 Fail-Closed 강화

> **Task ID**: `task_1803e9c04566`
> **작성일**: 2026-09-01
> **작성자**: Orca Worker (`term_a1bc689e-a3f3-4108-aa6b-296fffb2a017`)

---

## 1. 개요 및 배경

2026-09-01 외부 보안 및 정합성 감사에서 확인된 두 가지 취약점을 원천 차단하고 보강하였습니다.

1. **취약점 1 (약한 DB 판정 자동 승인)**:
   - `scripts/orca_auto_approve.py`의 `classify_docker_execution`에서 `mysql -e`로 전달된 SQL 접두사(`SELECT`, `WITH` 등)만을 단순 검사하여 `approve`를 내리는 경로가 존재했습니다.
   - 이로 인해 `WITH x AS (SELECT 1) UPDATE ...`와 같은 쓰기 우회 또는 `SELECT ... INTO OUTFILE`과 같은 파일 쓰기/탈출 시도가 자동 승인될 수 있는 취약점이 있었습니다.
2. **취약점 2 (리뷰어 독립성 미보장 시 침묵 진행)**:
   - `scripts/orca_model_router.py`에서 빌더 Provider를 판정하지 못했을 때(`unknown` 또는 미지정), 고위험 및 쓰기 권한이 있는 Task임에도 불구하고 경고만 남긴 채 임의의 모델로 리뷰어를 배정하는 문제가 있었습니다.
   - 이로 인해 빌더와 리뷰어가 동일한 모델 계열로 배정되어 상호 독립적 검증 원칙이 훼손될 위험이 있었습니다.

---

## 2. 주요 변경 내역

### 2.1 DB 직접 실행 자동 승인 경로 제거 (`scripts/orca_auto_approve.py`)
- `classify_docker_execution`에서 `docker` 및 `docker compose`를 통한 직접 SQL 실행 자동 승인(`approve`) 로직을 완전히 제거하였습니다.
- 모든 직접 `docker` 실행은 `"hold"`로 판정되며, 보류 사유에 공식 안전 경로인 `scripts/db_readonly_query.py`를 사용하도록 명확히 안내합니다:
  - 안내 문구: `"docker 직접 실행은 보류 대상 (DB 조회가 필요하면 uv run python scripts/db_readonly_query.py 를 사용하십시오)"`
- 약한 접두사 검사용 상수 `READ_ONLY_SQL_PREFIXES`를 제거하였습니다.

### 2.2 조사 워커를 위한 안전한 단일 대체 경로
- 조사 및 분석 작업에서 DB 조회가 필요한 워커는 `uv run python scripts/db_readonly_query.py --sql "<질의>"` 단일 경로를 사용합니다.
- `scripts/db_readonly_query.py`는 이미 `UV_RUN_ALLOWED_SCRIPTS`에 등록되어 터미널 자동 승인이 보장되며, 내부적으로 다음 4중 안전장치를 강제합니다:
  1. 다중 문장 세미콜론 분할 검사
  2. SQL 토큰화, 주석 및 문자열 리터럴 정규화
  3. `INTO OUTFILE`, `DUMPFILE`, `FOR UPDATE` 등 쓰기/탈출 키워드 원천 차단
  4. MySQL 세션 수준 `SET SESSION TRANSACTION READ ONLY` 강제

### 2.3 리뷰어 독립성 Fail-Closed 강제 (`scripts/orca_model_router.py`)
- `select_model` 및 `route()`에 `builder_provider` 판정 로직을 보강하였습니다.
- 빌더 Provider를 알 수 없는 경우(`builder_provider="unknown"` 또는 미지정):
  - **Fail-Closed**: 위험도가 `medium` 이상이거나 쓰기 범위(`has_write_scope=True`)가 있는 경우, 독립성을 검증할 수 없으므로 `ModelRoutingError`를 발생시켜 실행을 즉시 차단합니다.
  - **Low 위험 읽기 전용 허용**: 위험도가 `low`이고 읽기 전용(`has_write_scope=False`)인 경우에만 종전과 같이 경고(`inventory_notes` / `warnings`)를 기록하고 진행을 허용합니다.

---

## 3. 검증 결과

### 3.1 단위 및 회귀 테스트
1. **`tests/test_orca_auto_approve.py`**:
   - `TestDockerReadOnlySql` 갱신:
     - `test_select_is_held_and_instructs_readonly_query`: `SELECT` 질의의 docker 직접 실행 보류 및 안내 문구 검증 (Pass)
     - `test_multiple_read_only_statements_are_held`: 복수 읽기 질의 보류 검증 (Pass)
     - `test_with_update_is_held`: `WITH ... UPDATE` 쓰기 우회 시도 보류 검증 (Pass)
     - `test_select_into_outfile_is_held`: `SELECT ... INTO OUTFILE` 파일 쓰기 시도 보류 검증 (Pass)
     - DDL, 대화형 세션, 셸 경유 실행 보류 검증 (Pass)
   - 결과: 230건 전량 통과.

2. **`tests/test_orca_model_router.py`**:
   - `TestProviderIndependence` 테스트 스위트 보강:
     - `test_select_model_reviewer_unknown_builder_provider_fails_closed_on_high_risk`: high 위험도 fail-closed 검증 (Pass)
     - `test_select_model_reviewer_unknown_builder_provider_fails_closed_on_medium_risk`: medium 위험도 fail-closed 검증 (Pass)
     - `test_select_model_reviewer_unknown_builder_provider_fails_closed_on_write_scope`: 쓰기 범위 보유 시 fail-closed 검증 (Pass)
     - `test_select_model_reviewer_unknown_builder_provider_allowed_on_low_risk_readonly`: low 위험 읽기 전용 허용 및 경고 기록 검증 (Pass)
     - `test_route_reviewer_unknown_builder_provider_fails_closed_on_high_medium_or_write`: route() fail-closed 검증 (Pass)
     - `test_route_reviewer_unknown_builder_provider_allowed_on_low_risk_readonly`: route() low 위험 허용 검증 (Pass)
     - `test_tier_policy_values_unmodified`: TIER_POLICY 불변성 검증 (Pass)
   - 결과: 139건 전량 통과.

3. **`tests/test_orca_run_reviewer.py`**:
   - `test_build_model_command_supported_independent_reviewer_models`: 지원 리뷰어 모델 CLI 빌드 검증 추가 (Pass)
   - 결과: 43건 전량 통과.

4. **`tests/test_orca_taskctl.py`**:
   - 결과: 187건 전량 통과.

### 3.2 전체 테스트 및 에이전트 규칙 검증
- `python3 scripts/validate_agent_rules.py --quiet`: 통과 (16/16 건 통과).
- `uv run pytest tests/ -q -m 'not data_assets'`: 통과 (3011 passed, 15 skipped, 3 deselected).

---

## 4. 변경 파일 목록

| 파일 경로 | 변경 내용 요약 |
|---|---|
| `scripts/orca_auto_approve.py` | `classify_docker_execution`의 읽기 전용 자동 승인 제거, 전량 보류 및 `db_readonly_query.py` 안내 |
| `scripts/orca_model_router.py` | 리뷰어 빌더 Provider 미상 시 위험도/쓰기 범위에 따른 fail-closed 및 low 읽기 전용 허용 분기 구현 |
| `tests/test_orca_auto_approve.py` | docker 실행 보류 및 `WITH ... UPDATE`, `SELECT ... INTO OUTFILE` 보류 단언 테스트 갱신 |
| `tests/test_orca_model_router.py` | 빌더 Provider 미상 fail-closed 및 low 읽기 전용 허용 회귀 테스트 추가 |
| `tests/test_orca_run_reviewer.py` | 독립 리뷰어 모델 명령어 빌드 검증 테스트 추가 |
| `docs/analysis/task_u3_approval_and_reviewer.md` | 작업 분석 및 보안 검증 보고서 작성 |
| `docs/analysis/task_1803e9c04566.md` | 작업 ID 매핑 분석 보고서 작성 |
