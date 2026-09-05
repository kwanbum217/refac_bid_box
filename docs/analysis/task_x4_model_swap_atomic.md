# 모델 승격·롤백 서빙 경로 원자 전환 (R-06)

> **작성일**: 2026-09-05
> **Task**: `task_7f0659b4d4fc` / `task_x4_model_swap_atomic` (구현), `task_7227826cd798` (재검증)
> **상태**: 구현은 선행 커밋 `902a046`. 본 문서는 그 구현을 이 Task 가 직접 재검증한 기록이다. `CURRENT_STATE` 의 `model_swap_gap` 갱신은 코디네이터 소유

---

## 1. 문제

기존 승격은 서빙 디렉터리를 백업 자리로 `shutil.move` 한 뒤, staging 을 서빙 이름으로 다시 `shutil.move` 했습니다. 롤백도 target → holding, backup → target, holding → backup 의 같은 순서입니다. 두 이동 사이에 `data/model_files/<model_name>` 이 존재하지 않습니다. 그 순간에 예측 요청이 모델 파일을 찾지 못할 수 있습니다.

## 2. 비교와 선택

| 방식 | 서빙 이름 유지 | Windows | Docker 바인드 마운트 | 채택 |
| --- | --- | --- | --- | --- |
| 디렉터리 두 번 `move` (기존) | 아니오. 두 rename 사이 부재 | 동작하나 부재 구간 동일 | 동일 | 기각 |
| 버전 디렉터리 + 심볼릭 링크 `os.replace` | 링크 이름은 유지 | 개발자 모드/관리자 권한 없이는 생성 실패. 디렉터리 junction 은 `os.replace` 가 파일과 같지 않음 | virtiofs/osxfs/WSL 바인드에서 링크 교체가 호스트와 다르게 실패하거나 따라가지 않을 수 있음 | 기각 |
| 비어 있지 않은 디렉터리 위 `os.replace` | 시도만 가능 | dest 가 비어 있지 않으면 실패 | POSIX 도 dest 비어 있지 않으면 실패 | 기각 |
| 같은 볼륨 파일 단위 `os.replace` + 서빙 디렉터리 유지 | 디렉터리 inode/이름을 지우지 않음 | 파일 `ReplaceFile`/`os.replace` 는 같은 볼륨에서 원자적 | staging 을 서빙 루트 안에 만들어 같은 마운트에서 rename | 채택 |

심볼릭 링크를 고르지 않은 이유: 이 저장소의 G2 목표는 macOS 한 점의 성공이 아니라 Windows 와 Docker 바인드 마운트에서 같은 계약입니다. 링크 생성 권한과 바인드 마운트 링크 의미는 그 계약을 깨뜨립니다.

`ModelRegistry` 는 `MODEL_FILES_DIR` 아래 실디렉터리를 모델 ID 로 훑고 `model_dir/metadata.json` 을 읽습니다. 서빙 경로를 링크나 버전 하위 디렉터리로 바꾸면 레지스트리 수정이 필요합니다. 이 Task 범위는 파일 전환의 원자성이라 레지스트리 레이아웃은 유지합니다.

## 3. 구현

승격:

1. staging 에서 복사·검증을 끝낸다. 실패 시 서빙 트리는 손대지 않는다.
2. 기존 서빙 트리가 있으면 백업 자리로 **복사**한다. 서빙 디렉터리는 이동하지 않는다.
3. staging 파일을 서빙 디렉터리 안으로 `os.replace` 한다. 새 트리에 없는 잔여 파일만 지운다.
4. 3이 실패하면 백업 복사본을 같은 방식으로 서빙 경로에 다시 설치한다.

롤백:

1. 현재 서빙 트리를 holding 으로 복사한다.
2. 백업 트리를 staging 복사한 뒤 서빙 디렉터리에 파일 단위로 설치한다. 백업 원본은 설치 성공 전까지 유지한다.
3. 실패 시 holding 으로 복구한다.
4. 성공 시 이전 서빙본(holding)을 백업 자리로 옮긴다.

첫 승격처럼 서빙 경로가 아직 없으면 디렉터리 rename 한 번으로 만듭니다. 부재 구간은 “있던 이름을 지운 뒤”에만 생깁니다.

메모리에 올라간 `ModelRegistry` wrapper 교체는 이 Task 밖입니다. 디스크 전환 후에도 이미 로드된 모델은 그대로입니다.

## 4. 검증

| 항목 | 위치 |
| --- | --- |
| 교체 중 서빙 경로 존재 | `tests/test_promotion_gate.py::test_promote_keeps_serving_path_present_during_swap` |
| 승격 중간 실패 후 유효 트리 | `tests/test_promotion_gate.py::test_promote_injected_replace_failure_leaves_valid_serving` |
| 롤백 중 서빙 경로 존재 | `tests/test_promotion_cli.py::test_rollback_keeps_serving_path_present_during_swap` |
| 롤백 중간 실패 후 유효 트리 | `tests/test_promotion_cli.py::test_rollback_injected_replace_failure_leaves_valid_serving` |
| 롤백 후 이전 버전 복원 | 기존 `test_promote_then_rollback_restores_previous_version` |

가중치 파일은 서빙 디렉터리를 삭제하거나 덮어쓰기 전에 백업/holding 으로 복사합니다. `data/model_files/*/model.bin` 실서빙 가중치는 이 워크트리에서 로드하지 않았고, 검증은 `tmp_path` 격리 fixture 만 사용했습니다.

---

## 5. task_7227826cd798 재검증 (2026-09-05)

이 절은 선행 Task `task_7f0659b4d4fc` 의 구현 커밋을 **다시 읽고 명령을 직접 재실행한** 기록이다. 이 Dispatch(`ctx_79ed841296df`)는 그 커밋의 저자가 아니며, 과거 `worker_done` 을 소급 작성하지 않는다. 코드는 수정하지 않았다.

### 5.1 선행 구현과 이번 문서 커밋의 구분

| 구분 | 값 |
| --- | --- |
| 선행 구현 커밋 | `902a04660b6825c3778e11a8bd37c3ada1431518` |
| 선행 커밋 메시지 | `fix: 승격과 롤백에서 서빙 경로 부재 구간을 없앤다` |
| 선행 커밋 파일 | `src/ml/promotion.py`, `tests/test_promotion_gate.py`, `tests/test_promotion_cli.py`, `docs/analysis/task_x4_model_swap_atomic.md`, `docs/analysis/task_7f0659b4d4fc.md` |
| 이번 Task 쓰기 범위 | `docs/analysis/task_x4_model_swap_atomic.md` 만 |
| 이번 Task 가 한 일 | 구현 재독, 검증 재실행, 이 절 추가 후 커밋, `ORCA_WORKER_DONE_V2` 보고 |

브랜치 `kwanbum217/wave-x-x4-swap` 의 `main...HEAD` 에는 선행 구현 파일이 남아 있다. 이번 보고의 `changed_files` 는 이 Task 가 실제로 고친 문서만 적는다. 코디네이터가 게이트 6 를 `main` 기준으로 돌리면 선행 파일이 보고 누락으로 잡힐 수 있다. 그때 기준 커밋은 `902a046` 이거나, 선행 구현과 이 재검증을 한 묶음으로 보아야 한다.

### 5.2 코드 재확인 (수정 없음)

`src/ml/promotion.py` 에서 `shutil.move` 호출은 주석에만 남고, 실행 경로는 아래다.

| 경로 | 동작 | 서빙 이름 |
| --- | --- | --- |
| 첫 승격 (`target` 없음) | `os.replace(staging, target)` 한 번 | 없던 이름을 만든다. 부재 구간은 없다 |
| 이후 승격 | `_snapshot_directory(target, backup)` 후 `_install_staging_into_serving` | `target` 디렉터리를 지우지 않는다 |
| 롤백 | holding 복사, 백업을 staging 복사, 서빙에 파일 단위 설치, 실패 시 holding 복구 | 동일 |
| 실패 복구 | `_restore_serving_from(backup 또는 holding, target)` | 서빙 이름을 유지한 채 되돌린다 |

staging 은 `tempfile.mkdtemp(dir=str(serving_dir), ...)` 로 서빙 루트 안에 만든다. 같은 마운트에서 `os.replace` 하므로 Docker 바인드 마운트에서도 디렉터리 단위 교체 실패를 피하려는 선택이다. 심볼릭 링크는 쓰지 않는다. 2절 근거와 코드가 같다.

`ModelRegistry.discover_models` 는 `MODEL_FILES_DIR` 아래 실디렉터리의 `metadata.json` 을 읽고 wrapper 를 메모리에 올린다. `promote`/`rollback` 은 레지스트리 재로드를 호출하지 않는다. 디스크 전환 원자성이 이 Task 범위이고, 이미 로드된 wrapper 교체는 범위 밖이라 코드를 바꾸지 않았다.

### 5.3 이 Dispatch 가 직접 실행한 검증

실행 시각은 2026-09-05, 작업 디렉터리는 이 워크트리 루트다.

| 명령 | 종료 코드 | 결과 |
| --- | --- | --- |
| `uv run pytest tests/test_promotion_gate.py tests/test_promotion_cli.py -q` | 0 | `25 passed in 1.42s` |
| `uv run mypy src` | 0 | `Success: no issues found in 93 source files`. note 2건(`src/ml/predictor.py:72`, `src/ml/model_registry.py:336`, `annotation-unchecked`). 오류 0건 |
| `python3 scripts/validate_agent_rules.py --quiet` | 0 | `검증 통과: 20/20 건` |
| `uv run pytest tests/ -q` | 1 | `2 failed, 3667 passed, 41 skipped in 128.71s` |

전량 pytest 실패 2건은 격리 트리에 원본 자산이 없어서다. 통과로 숨기지 않는다.

| 노드 | 메시지 |
| --- | --- |
| `tests/test_data_preservation.py::test_model_bin_files_exist` | `모델 가중치 없음: v25/model.bin` |
| `tests/test_data_preservation.py::test_chroma_db_exists` | `chroma_db 디렉터리 없음` |

이 워크트리에서 `data/model_files/*/model.bin` 은 0개, `chroma_db/` 는 없다. 실서빙 가중치는 로드하지 않았고, 승격 검증은 `tmp_path` fixture 만 사용했다. 운영 데이터에 접근하지 않았다.

부재 구간 회귀 테스트 4개는 전량 통과에 포함된다.

| 테스트 | 확인 |
| --- | --- |
| `test_promote_keeps_serving_path_present_during_swap` | `_replace_path`/`rmtree`/`copytree` 전후에 `serving.exists()` 가 모두 참 |
| `test_promote_injected_replace_failure_leaves_valid_serving` | `model.bin` 첫 `os.replace` 실패 후 바이트와 `metadata.json` 이 직전 값 |
| `test_rollback_keeps_serving_path_present_during_swap` | 롤백 중에도 서빙 경로 존재 |
| `test_rollback_injected_replace_failure_leaves_valid_serving` | 롤백 실패 후 버전이 `v_20260802_000000_000` 으로 남음 |
| `test_promote_then_rollback_restores_previous_version` | 롤백 후 `v_20260801_000000_000` |

### 5.4 리뷰 체크리스트 (이 재검증 기준)

| id | 판정 | 근거 |
| --- | --- | --- |
| no_absent_window | 결함 아님 | 서빙 디렉터리를 옮기지 않는다. 존재 감시 테스트가 통과했다 |
| failure_leaves_valid | 결함 아님 | 주입 실패 후 원본 바이트 복원 테스트가 통과했다 |
| rollback_exact | 결함 아님 | 롤백 후 이전 버전 문자열이 복원된다 |
| cross_platform_designed | 결함 아님 | 심볼릭 링크를 기각하고 같은 볼륨 파일 `os.replace` 를 택한 근거가 2절과 코드 주석에 있다 |
| weights_not_destroyed | 결함 아님 | 서빙 트리를 지우기 전에 백업/holding 복사. 이 Task 는 가중치 파일을 건드리지 않았다 |
| current_state_untouched | 결함 아님 | `docs/context/CURRENT_STATE.md` 를 읽기만 했다 |
| test_expectations_honest | 결함 아님 | 이 Dispatch 는 테스트를 수정하지 않았다 |
| scope_excess | 결함 아님 | 허용 쓰기 파일만 수정했다 |

### 5.5 잔여 리스크

1. 파일 단위 `os.replace` 는 디렉터리 전체가 한 연산으로 바뀌지 않는다. 교체 중에 `model.bin` 과 `metadata.json` 이 서로 다른 버전을 가리킬 수 있다. R-06 의 대상은 서빙 **경로 부재**이며, 내용 혼재는 이 설계의 남은 창이다.
2. 디스크 전환 뒤 `ModelRegistry` 메모리 wrapper 는 그대로다. 연속 예측이 옛 객체를 쓸 수 있다. 범위 밖이라 에스컬레이션하지 않았다.
3. `CURRENT_STATE` 의 `model_swap_gap` 은 아직 active 이고, 문구는 심볼릭 링크 교체를 추진한다고 적혀 있다. 구현은 링크를 기각했다. 상태 원장 갱신은 코디네이터 소유다.
4. Capsule `verification_commands` 의 `uv run pytest tests/ -q` 는 이 격리 트리에서 종료 코드 1 이다. 게이트 3 이 그 명령을 그대로 재실행하면 실패한다. 원인은 이 Task 의 승격 코드가 아니라 원본 `model.bin`/`chroma_db` 부재다.
