# Orca 통제면 3대 진실성 결함 해결 분석 보고서 (신규 D, E, F)

> **작성일**: 2026-09-05
> **Task ID**: task_490d6d4f7d1f
> **관련 문서**: docs/ops/orca_control_plane_tools.md, docs/ops/agent_worker_launch_reference.md

---

## 1. 개요 및 배경

2026-09-05 세션 및 이전 독립 리뷰(O-05, O-06)에서 드러난 Orca 제어 평면의 세 가지 진실성 결함을 해소하였습니다:
1. **신규 D (rework Capsule 경로와 Task spec 및 워크트리 불일치)**:
   - 코디네이터 확인 및 코드 조사 결과, 주 저장소 로컬에서는 `cmd_rework` 가 spec 잠정 경로(3682~3695행)와 새 Task ID 경로(3744~3745행) 양쪽 모두에 디렉터리를 만들고 파일을 작성합니다.
   - 그러나 **워커가 실제로 동작하는 격리 워크트리에는 이 파일들이 전혀 배치되지 않았습니다**.
   - 그 결과 워커는 격리 워크트리에서 spec 이 지시한 파일을 열지 못하고, 이름이 비슷한 이전 리뷰 캡슐을 열어 종료된 Task 로 worker_done 을 보내는 사고가 발생했습니다.
2. **신규 E (dispatch 의 --deps 자동 연결 문서-구현 불일치)**: cmd_dispatch 의 도움말과 문서에는 의존성 자동 연결이 주장되었으나 실제 구현은 create / rework 경로에만 존재하고 dispatch 에서는 방치된 허구 인자였습니다.
3. **신규 F (비감독 Dispatch receipt 기록 fail-open 결함)**: 비감독 Dispatch(--terminal) 영수증 기록 실패 시 경고만 내고 기동을 강행하여, 영수증 부재로 인해 완료 세션 잔류 감사(orca_settled_session_audit.py)가 터미널 점유를 검출하지 못하고 회수 누락이 조용히 지나갔습니다.

---

## 2. 결함별 실측 조사 및 해결 방안

| 결함 | 실측 조사 결과 및 원인 | 해결 방안 |
| --- | --- | --- |
| **신규 D** | 1. 주 저장소 로컬에는 두 사본이 모두 기록되나 `final_capsule_text` 의 `allowed_read_files` 에 spec 잠정 경로가 누락될 수 있음<br>2. `cmd_rework` 에 워크트리 배치 로직이 전혀 없어 워커 워크트리에는 Capsule 파일이 부재함<br>3. `dispatch` 가 워크트리 내 Capsule 실존을 확인하지 않아 빈 워크트리로 기동됨 | 1. `rework` 시 두 사본 내용의 100% 일치를 강제하고 `allowed_read_files` 에 두 경로를 모두 등록<br>2. `rework --worktree <path>` 옵션을 신설하여 워크트리에도 동시 자동 배치 지원<br>3. `dispatch` 시 워크트리 내 Capsule 자동 배치를 시도하고, 파일 부재 시 종료 코드 2 로 fail-closed 거부 |
| **신규 E** | Task DAG 의존성은 task-create 시점에만 연결 가능함에도 dispatch 파서와 문서에 --deps 자동 연결이 남아 있어 역할 혼선 유발 | 1. dispatch 서브커맨드에서 불필요한 --deps 인자 및 도움말 제거<br>2. 의존성 연결 책임은 create 및 rework 에만 있음을 문서에 명확히 일원화 |
| **신규 F** | 워커 기동 후 사후에 영수증을 기록하고, 예외 발생 시 경고만 출력하여 영수증 없이 워커가 기동됨 | 1. 비감독 기동 직전 preflight 단계에서 영수증 기록을 먼저 수행<br>2. 기록 실패 시 워커를 기동하지 않고 종료 코드 2 로 fail-closed 중단<br>3. --skip-dispatch-receipt 명시 플래그로만 의도적 우회 허용<br>4. 기동 실패 시 사전 작성된 임시 영수증 자동 삭제 정리 |

---

## 3. 코드 변경 상세

### 3.1 scripts/orca_taskctl.py
- **cmd_rework**:
  - actual_capsule_path 와 new_capsule_path 양쪽에 동일한 final_capsule_text 저장.
  - allowed_read_files 에 spec 경로와 실제 경로 모두 등록하여 워커가 어느 경로로 읽어도 계약 준수.
  - --worktree 인자 지원: 지정된 워크트리 내에도 사본 자동 배치.
  - 결과 페이로드 및 출력에 spec_capsule, worktree_capsules 추가.
- **cmd_dispatch**:
  - --capsule 경로가 실제 파일인지(is_file()) 검증하고 부재 시 종료 코드 2 반환.
  - 워크트리 경로 확정 시 워크트리 내 Capsule 자동 배치 및 실존 확인, 부재 시 종료 코드 2 거부.
  - 비감독 기동 직전 영수증 사전 기록 및 실패 시 종료 코드 2 거부 (우회: --skip-dispatch-receipt).
  - 기동 성공 시 영수증 최종 갱신, 기동 실패 시 임시 영수증 삭제.
- **파서 (_build_parser)**:
  - dsp 파서에서 --deps 제거, --skip-dispatch-receipt 추가.
  - rwk 파서에 --worktree 추가.

### 3.2 scripts/orca_settled_session_audit.py
- load_unsupervised_receipts: 영수증 내 original_task_id 필드도 매핑 지원하여 rework 태스크 역추적 보장.

### 3.3 문서 (docs/ops/orca_control_plane_tools.md, docs/ops/agent_worker_launch_reference.md)
- rework 명령어 표 및 --worktree 인자 문서화.
- dispatch 인자에서 --deps 제거 및 의존성 책임 일원화 서술.
- 비감독 Dispatch 영수증 fail-closed 정책 및 --skip-dispatch-receipt 우회 플래그 문서화.
- 워크트리 내 Capsule 실존 검증 및 자동 배치 절차 명시.

---

## 4. 검증 결과

| 검증 항목 | 대상 파일 / 명령 | 결과 | 비고 |
| --- | --- | :---: | --- |
| 단위 및 회귀 테스트 | uv run pytest tests/test_orca_taskctl.py tests/test_orca_settled_session_audit.py -q | 237 passed | 신규 회귀 테스트 4건 포함 전량 통과 |
| 정적 타입 검사 | uv run mypy src | 0건 (Success) | 93개 소스 파일 오류 없음 |
| 다중 에이전트 규칙 검증 | python3 scripts/validate_agent_rules.py --quiet | 20/20 통과 | pre-commit 규칙 및 단일 진실 원천 준수 |
| 전체 테스트 스위트 | uv run pytest tests/ -q -m 'not data_assets' | 3639 passed | 전량 통과 (기존 기능 무손실) |

---

## 5. 결론 및 기대 효과

1. **워크트리 사양 배치 자동화**: rework 이후 Task spec 이 가리키는 경로에 파일이 실제로 존재할 뿐만 아니라 워크트리에도 자동 배치되므로, 워커가 없는 파일을 열고 다른 캡슐로 넘어가는 사고가 원천 차단됩니다.
2. **제어 평면 정직성 확보**: dispatch 의 허구 옵션 --deps 를 제거하여 도구 도움말과 문서, 실제 구현이 완벽하게 일치합니다.
3. **완료 세션 누락 없는 회수**: 비감독 Dispatch 영수증이 fail-closed 로 강제되어, 영수증 없는 워커 세션이 생성되지 않으므로 잔류 세션 감사가 항상 정상 작동합니다.
