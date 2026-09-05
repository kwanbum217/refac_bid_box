# 모델 승격·롤백 서빙 경로 원자 전환 (R-06)

> **작성일**: 2026-09-05
> **Task**: `task_7f0659b4d4fc` / `task_x4_model_swap_atomic`
> **상태**: 구현 완료. `CURRENT_STATE` 의 `model_swap_gap` 갱신은 코디네이터 소유

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
