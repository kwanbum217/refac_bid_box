# Orca 제어 평면 도구(scripts/) Fail-Open 패턴 전수 조사 보고서

> **작성일**: 2026-08-18
> **작성자**: Dispatched Worker (Task ID: `task_da40f3ac1c6d` / Run: `run_5a0930ee8cf2`)
> **조사 대상**: `scripts/` 전체 (Orca 제어 평면 자동화 도구 및 검증/감사 스크립트)
> **조사 목적**: 실패, 미검증, 절단, 부분, 미도달, 알 수 없음 등 중간 상태가 SUCCESS(통과/정상)로 승격되는 fail-open 결함 후보 식별

---

## 1. 개요 및 요약

2026-08-18 외부 지적 사항(중간 상태의 SUCCESS 승격 기전)과 관련하여 `scripts/` 디렉터리 내 전체 스크립트(Orca 제어 평면 9종 및 검증/감사 스크립트 83종, 총 92개 파일)를 대상으로 fail-open 패턴 전수 조사를 실시하였습니다.

조사 결과, 실효 검증이 생략되거나 비정상 상태가 `PASS`(종료 코드 0 또는 위반 0건)로 보고될 수 있는 결함 후보 총 6건을 식별하였습니다. 코드는 수정하지 않고 사양 및 acceptance 기준에 따라 정밀 분석 결과만을 본 문서에 기록합니다.

---

## 2. 결함 후보 목록 요약

| ID | 파일:줄번호 | 심각도 분류 | 핵심 기전 | 잘못 보고되는 상태 |
| --- | --- | --- | --- | --- |
| F1 | `scripts/orca_contract.py:228-230` | **판정 오염** | `allowed`가 빈 리스트(`[]`)일 때 `scope_excess`가 `[]` 반환 | 읽기 전용 워커의 무단 파일 수정이 Gate 2 및 요약 검증에서 정상(PASS)으로 통과 |
| F2 | `scripts/orca_taskctl.py:1005-1018` | **판정 오염 / 실행 은폐** | `finalize_task`에서 `orca_level1_gate.py` 호출 시 `--tests` 및 `--strict` 누락 | 테스트가 전혀 실행되지 않고(skipped) Level 1 게이트 전체가 통과(exit code 0)로 판정 |
| F3 | `scripts/orca_taskctl.py:1004` | **실행 은폐** | 지정된 `--worktree` 경로가 존재하지 않을 때 `repo`로 조용히 폴백 | 워커 워크트리 부재 오류가 은폐되고 메인 저장소 검증 결과로 통과 판정 |
| F4 | `scripts/summarize_worker_done.py:175` | **판정 오염** | `commit_count == 0` 검사가 `len(changed_files) > 0`일 때만 발동 | 코드 변경 작업(builder)에서 커밋과 파일 변경이 0건이어도 위반 0건/PASS 처리 |
| F5 | `scripts/compare_host_container_db.py:159-163` | **데이터 무손실 직결** | 호스트-컨테이너 간 DB 행 수/스키마 차이가 있어도 항상 `return 0` | DB 불일치/데이터 유실 상태가 파이프라인에서 정상(exit code 0)으로 승격 |
| F6 | `scripts/orca_taskctl.py:741-749` | **실행 은폐** | `_launch_succeeded`에서 `JSONDecodeError` 발생 시 `return True` | CLI가 비정상 에러 텍스트나 트레이스백을 출력해도 기동 성공으로 간주 |

---

## 3. 결함 후보 상세 분석

### 3.1 [F1] 읽기 전용 워커의 파일 수정이 허용 범위 내로 판정되는 결함 (판정 오염)
- **파일:줄번호**: [`scripts/orca_contract.py:228-230`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/orca_contract.py#L228-L230)
- **삼키는 기전**:
  ```python
  def scope_excess(paths: list[str], allowed: list[str]) -> list[str]:
      if not allowed:
          return []
      return [p for p in paths if not matches_any(p, allowed)]
  ```
  `scope_excess`는 `allowed` 리스트가 비어 있으면(판정 근거 부재로 가정하여) 초과 파일이 없는 것으로 보고 `[]`를 반환합니다.
- **잘못 보고되는 상태**:
  Capsule v2 규약에서 읽기 전용 워커(reviewer, investigator 등)는 `allowed_write_files: []`로 지정됩니다. 만약 해당 워커가 임의로 파일을 수정하여 `changed_files = ["src/ml/features.py"]`가 발생해도, `scope_excess(changed_files, [])`가 `[]`를 반환하므로:
  - `orca_level1_gate.py:186-207` (Gate 2 범위 검증)에서 `excess`가 0건으로 계산되어 `status="pass"`를 반환합니다.
  - `summarize_worker_done.py:192-195`에서 범위 초과 위반이 추가되지 않습니다.
- **오탐 가능성 자체 반증**:
  Capsule에서 `allowed_write_files`가 누락된 경우를 위한 방어일 수 있으나, deny-by-default 보안 모델에서 빈 쓰기 허용 목록은 '모든 쓰기 금지'를 의미해야 하므로 빈 목록을 '모든 쓰기 허용'으로 처리하는 것은 명백한 fail-open 결함입니다.

---

### 3.2 [F2] finalize 시 테스트가 생략된 채 게이트 통과로 승격되는 결함 (판정 오염 / 실행 은폐)
- **파일:줄번호**: [`scripts/orca_taskctl.py:1005-1018`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/orca_taskctl.py#L1005-L1018)
- **삼키는 기전**:
  `finalize_task`가 `orca_level1_gate.py`를 실행할 때 `--capsule`, `--repo`, `--base`, `--branch`, `--json`만 전달하고, Capsule 내의 `verification_commands`를 파싱하여 `--tests` 인자로 전달하지 않으며 `--strict` 플래그도 설정하지 않습니다.
  `orca_level1_gate.py` 내부에서는 `--tests`가 없으므로 Gate 3(테스트)를 `status="skipped"`로 설정하고, `--strict`가 아니므로 `failed_count == 0`에 따라 최종 판정을 `verdict="pass"`, `exit_code=0`으로 산출합니다 (`orca_level1_gate.py:633-634`).
- **잘못 보고되는 상태**:
  코디네이터의 단일 게이트 검증(`finalize`) 과정에서 테스트가 단 1건도 실행되지 않았음에도 Level 1 게이트가 완전 통과(`exit_code: 0`, `verdict: "pass"`)로 보고됩니다.
- **오탐 가능성 자체 반증**:
  워커가 `worker_done` 보고서에 자체 테스트 결과를 적었더라도 이는 비신뢰 입력(Level 0)이며, 독립 기계 검증(Level 1)의 핵심인 실제 테스트 실행이 생략된 채 통과로 처리되므로 결함이 맞습니다.

---

### 3.3 [F3] 지정된 worktree 부재 시 메인 저장소로 자동 폴백하여 검증을 왜곡하는 결함 (실행 은폐)
- **파일:줄번호**: [`scripts/orca_taskctl.py:1004`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/orca_taskctl.py#L1004)
- **삼키는 기전**:
  ```python
  target_repo = worktree_path if (worktree_path and worktree_path.exists()) else repo
  ```
  `finalize` 호출 시 인자로 전달된 `--worktree <path>` 경로가 오타, 삭제, 권한 등으로 존재하지 않을 때, 에러(종료 코드 2)를 발생시키지 않고 조용히 코디네이터의 기본 `repo` 디렉터리로 폴백합니다.
- **잘못 보고되는 상태**:
  워커의 변경 사항이 담긴 작업 트리가 유실되었거나 경로가 잘못되었음에도 메인 저장소의 깨끗한 상태를 대상으로 린터/규칙/게이트를 실행하여 통과(`PASS`)를 산출합니다.
- **오탐 가능성 자체 반증**:
  `--worktree` 인자가 아예 생략된 경우 `repo`를 사용하는 것은 정상이나, 명시적으로 지정된 경로가 존재하지 않는데도 조용히 폴백하는 것은 유실된 작업 대상을 은폐하고 잘못된 검증 결과를 낳습니다.

---

### 3.4 [F4] 코드 변경 작업에서 커밋/변경 파일 0건이 성공으로 승격되는 결함 (판정 오염)
- **파일:줄번호**: [`scripts/summarize_worker_done.py:175`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/summarize_worker_done.py#L175)
- **삼키는 기전**:
  ```python
  if status == "succeeded" and commit_count == 0 and len(changed_files) > 0:
      violations.append(...)
  ```
  규약 3.3 위반 검사 조건식에 `len(changed_files) > 0`이 AND 조건으로 결합되어 있어, 워커가 커밋도 하지 않고 변경 파일도 없는(`commit_count == 0`, `changed_files == []`) 상태에서 `status: "succeeded"`를 보고하면 조건문이 발동하지 않습니다.
- **잘못 보고되는 상태**:
  빌더(builder) 역할의 워커가 실제 코드를 변경/커밋하지 않고 허위 완료 보고서를 작성해도 `violations: []` 및 `exit_code: 0`으로 정상 요약됩니다.
- **오탐 가능성 자체 반증**:
  조사(investigator) 역할의 경우 변경 파일이 없을 수 있으나, 본 도구는 Capsule의 `role`을 대조하지 않으므로 빌더 역할의 미수행 완료 보고가 아무런 제재 없이 통과되는 fail-open 상태가 됩니다.

---

### 3.5 [F5] 호스트-컨테이너 간 DB 불일치 시 종료 코드 0 반환 (데이터 무손실 직결)
- **파일:줄번호**: [`scripts/compare_host_container_db.py:159-163`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/compare_host_container_db.py#L159-L163)
- **삼키는 기전**:
  ```python
  if diff.empty and mismatch.empty:
      print("두 DB 가 동일합니다. 호스트 DATABASE_URL 을 3306 으로 옮겨도 손실이 없습니다.")
  else:
      print("차이가 있습니다. 전환 전에 위 항목을 해소해야 합니다 (G1).")
  return 0
  ```
  두 DB 간의 행 수 차이(`diff`)나 컬럼 스키마 차이(`mismatch`)가 발견되어도 경고 문구만 출력하고 항상 `return 0`으로 종료합니다.
- **잘못 보고되는 상태**:
  자동화 파이프라인이나 CI/사전 점검 스크립트에서 본 도구를 실행할 경우, DB 데이터 누락이나 스키마 불일치가 존재해도 무조건 성공(`exit code 0`)으로 간주됩니다.
- **오탐 가능성 자체 반증**:
  스크립트 설명에 '읽기 전용'으로 명시되어 있으나, 불일치 검증 도구로서 차이 발생 시 비정상 종료 코드(예: 1)를 반환하지 않으면 기계 검증 자동화에서 G1 데이터 무손실 위반을 놓치게 됩니다.

---

### 3.6 [F6] CLI 비정상 텍스트 출력을 기동 성공으로 오인하는 결함 (실행 은폐)
- **파일:줄번호**: [`scripts/orca_taskctl.py:741-749`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/scripts/orca_taskctl.py#L741-L749)
- **삼키는 기전**:
  ```python
  def _launch_succeeded(stdout: str) -> bool:
      if not stdout or not stdout.strip():
          return True
      try:
          payload = json.loads(stdout)
      except (json.JSONDecodeError, ValueError):
          return True
      return not (isinstance(payload, dict) and payload.get("ok") is False)
  ```
  `_launch_succeeded` 함수는 `stdout`을 JSON으로 파싱하려 시도하고, 파싱 실패(`JSONDecodeError`) 시 `return True`를 반환합니다.
- **잘못 보고되는 상태**:
  Orca CLI 명령이 `--json` 플래그로 호출되었음에도 비정상적인 평문 오류 메시지나 트레이스백을 출력하고 종료 코드 0으로 끝났을 때, 이를 기동 성공으로 판단하여 후속 파이프라인이 진행됩니다.
- **오탐 가능성 자체 반증**:
  JSON이 아닌 일반 터미널 출력을 지원하기 위한 처리일 수 있으나, JSON 출력을 명시적으로 요구하는 자동화 제어 경로에서는 비-JSON 출력을 파싱 실패 오류로 다루어야 안전합니다.

---

## 4. 오탐 점검 및 정상 동작 확인 항목

조사 과정에서 fail-open 의심을 받았으나 정상 설계로 확인된 항목들입니다.

1. **제너레이터 함수 호출 (`scripts/orca_coordinator_usage.py:iter_usage_records`)**:
   - 호출 시점에 즉시 I/O가 일어나지 않으나, `collect_usage` 내의 `for record, is_malformed in iter_usage_records(...)` 루프에서 온전히 소비되므로 리소스 누수나 미실행 결함이 아님을 확인했습니다.
2. **리뷰어 빈 diff 처리 (`scripts/orca_run_reviewer.py:435`)**:
   - `--paths` 필터 결과 diff가 비어 있는 경우 `종료 코드 2`로 즉시 거부하며, 모델 호출을 건너뛰도록 fail-closed 방어가 적용되어 있습니다.
3. **규칙 검증기 source_commit 오차 (`scripts/validate_agent_rules.py:575`)**:
   - 커밋 지연이 허용치를 초과하거나 확인 불가일 때 FAIL 대신 WARN으로 보고되나, 이는 정본 신선도 검사의 의도된 설계이며 `ok=True`이지만 화면에 명시적 경고 태그(`[WARN]`)를 남기도록 되어 있습니다.

---

## 5. 결론 및 향후 조치 제안

전수 조사를 통해 발견된 6건의 fail-open 결함 후보 중, 특히 **F1(`scope_excess` 빈 허용 목록 허용)** 과 **F2(`finalize` 시 Level 1 테스트 생략 및 PASS 판정)** 는 제어 평면의 신뢰성과 직결되는 주요 판정 오염 기전입니다.

본 작업(task_s3)은 사양에 따라 코드 수정을 수행하지 않았으며, 코디네이터가 후속 버그 수정 Task를 발행하여 해당 취약점을 안전하게 차단(fail-closed)할 것을 권장합니다.
