# task_74712e3bf4ad 작업 보고서: 학습 없는 drift baseline 생성 진입점

> **작성일**: 2026-09-06
> **Task**: task_74712e3bf4ad
> **산출물**: `scripts/generate_drift_baseline.py`, `tests/test_generate_drift_baseline.py`,
> `docs/ops/psi_drift_monitoring.md` 8절

## 1. 구현 내용

`scripts/generate_drift_baseline.py` 를 신설했습니다. 지정한 데이터 구간으로 drift baseline 을
만드는 정식 진입점이며 학습을 돌리지 않습니다.

- 분포 계산은 `save_baseline_distributions(df_feat, feature_columns, target_dir, model_name, model_version)`
  를 그대로 재사용합니다. 분포 로직을 새로 구현하지 않았습니다.
- 특징 생성은 `src/ml/features.py` 단일 공급원만 사용합니다. 학습 경로와 같은 순서로 기관 이력과
  재발주 이력을 붙인 뒤 `build_feature_frame` 으로 산출하고 저장된 범주 수준으로 dtype 을 복원합니다.
- `build_training_dataset` 호출에 `persist=False` 를 명시해 운영 학습 데이터셋 parquet 캐시를
  덮어쓰지 않습니다.
- 기본 동작은 dry-run 이며 `--write` 명시 플래그가 있을 때만 기록합니다.
- `--baseline-version` 은 필수 인자이며 학습 버전이 아니라 baseline 식별자임을 도움말과 문서에 적었습니다.
- `--start-at` 없이 `--write` 를 쓰면 종료 코드 2로 거부합니다.
- `REGIME_SHIFT_DATE` 를 하드코딩하지 않고 `--start-at` 으로 받되 도움말에 참고 기준으로 안내합니다.
- 표본이 집단별 최소 기준(100건)에 못 미치면 `--write` 여도 기록하지 않고 종료 코드 1로 끝냅니다
  (전체 표본과 `lwlt_rate_missing` 하위 집단 각각에 적용, fail-closed).
- `ModelTrainer._update_baseline_atomically` 를 재사용해 교체하므로 학습 경로와 같은 원자성 보장
  (임시 디렉터리와 백업을 거친 교체, 중간 실패 시 기존 baseline 복원)을 얻습니다.
  구조적으로 재사용이 가능했으므로 스크립트 안에 별도 절차를 두지 않았습니다.

## 2. 테스트

`tests/test_generate_drift_baseline.py` 4건은 실제 MySQL 에 접속하지 않습니다. 세션과 데이터 조회를
대역으로 대체했습니다.

- dry-run 이 어떤 파일도 쓰지 않는다 (및 `persist=False` 전달 확인).
- `--start-at` 없이 `--write` 를 거부한다.
- 표본 부족 시 기록하지 않고 실패로 끝난다.
- 교체 중간 실패(`shutil.move` 1회 강제 실패)에서 기존 baseline 이 보존되고 staging 잔재가 남지 않는다.

## 3. 검증 결과

- `uv run pytest tests/test_generate_drift_baseline.py -q`: 4 passed.
- `uv run pytest tests/ -q -m 'not data_assets'`: 3734 passed, 32 skipped, 3 deselected, 1 failed
  (`tests/e2e/test_ssr_auth.py::test_ssr_auth_signup_flow`, 본 변경과 무관한 e2e이며 단독 재실행 시 통과).
- `uv run mypy src`: no issues found in 93 source files.
- `python3 scripts/validate_agent_rules.py --quiet`: 20/20 통과.

## 4. 남은 사항

- `--write` 실제 실행은 하지 않았습니다. `ml_registry` 아래에 파일을 만들지 않았으며 실제 baseline
  생성은 코디네이터가 검토 후 직접 수행합니다.
- `src/` 아래 기존 코드는 수정하지 않았습니다.
