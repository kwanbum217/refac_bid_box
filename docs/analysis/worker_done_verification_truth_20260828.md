# ORCA_WORKER_DONE_V2 Verification 진실성 검증 및 재실행 비용 설계 보고서

> **작성일**: 2026-08-28
> **Task ID**: task_1049283686bf
> **Run ID**: run_43d9937ac156
> **작업자**: builder (Gemini 3.7 Flash)
> **대상**: worker_done verification 배열 진실성 대조 및 비용 최적화 게이트 구현

---

## 1. 배경 및 목적

2026-08-28 1차 게이트 승격 작업(`docs/analysis/worker_done_v2_gate_promotion_20260828.md`)을 통해 commit SHA 실존성, 브랜치 실존성, changed_files diff 일치 검증이 Level 1 실행 게이트로 승격되었습니다.

그러나 조사 보고서의 잔여 과제인 `verification` 배열의 진실성 검증이 남아 있어, 워커가 테스트를 돌리지 않고 허위 통과를 기재하더라도 기계적으로 검출하지 못하는 위험이 존재했습니다.

본 작업은 다음을 달성하기 위해 구현되었습니다:
1. `verification` 배열의 구조 및 필수 필드(`command`, `result`) 형식을 엄격 검증하여 위반 시 verdict 를 `blocked` 로 즉시 격하.
2. 검증 비용과 환경 의존성을 고려하여 재실행 대상을 화이트리스트로 선별하고, 실제 실행 결과와 보고된 결과의 일치 여부를 대조.
3. 화이트리스트 외 명령은 조용히 통과시키지 않고 `unverified` 로 명시하여 요약 및 게이트 출력에 투명하게 보존.
4. 재실행 타임아웃 및 실행 불능은 fail-closed 원칙으로 엄격 차단.

---

## 2. 재실행 대상(화이트리스트) 및 미검증(Unverified) 비용 판단 기준

모든 검증 명령을 게이트에서 재실행하면 게이트 실행 비용과 지연 시간이 기하급수적으로 증가하며 외부 환경(도커 데몬, 브라우저, 외부 서비스) 의존성 문제가 발생합니다. 따라서 비용과 위험도를 정량적으로 분석하여 다음과 같이 분리했습니다.

| 분류 | 대상 명령 | 재실행 여부 | 비용 및 근거 |
| --- | --- | :---: | --- |
| **화이트리스트** | `pytest` 계열 (`uv run pytest ...`, `python -m pytest ...`) | **재실행 및 대조** | - 실행 시간 수 초 이내 (단위/통합 테스트)<br>- 파일시스템 외 외부 자원 의존성 없음<br>- 허위 보고(조작) 위험이 가장 높은 핵심 영역 |
| **화이트리스트** | `validate_agent_rules.py` | **재실행 및 대조** | - 실행 시간 1초 미만<br>- 12개 규칙 검증으로 정합성 보장 비용 대비 효과 극대화 |
| **미검증 (Unverified)** | `npm test`, `npm run build` | **미재실행 (`unverified` 명시)** | - Node 환경, 번들링 시간 소요 (수십 초~수 분)<br>- Gate 3 / CI 파이프라인에서 별도 검증 수행 |
| **미검증 (Unverified)** | `docker build`, `compose` | **미재실행 (`unverified` 명시)** | - Docker 데몬 필수 (플랫폼별 소켓 의존성)<br>- 빌드 캐시 및 레이어 용량/시간 비용 과다 |
| **미검증 (Unverified)** | 임의 셸 스크립트, `curl` 등 | **미재실행 (`unverified` 명시)** | - 임의 부수효과(side-effect) 방지 및 보안 격리 |

---

## 3. 세부 구현 내역

### 3.1 `scripts/orca_contract.py`
- `is_whitelisted_verification_command(command)`: `pytest` 계열 및 `validate_agent_rules.py` 명령을 정확히 파싱하여 실행 인자 목록(`argv`) 추출.
- `verify_verification_truth(repo, verification, timeout)`:
  - 각 항목의 형식 검증 (dict 여부, 비어있지 않은 `command` 및 `result` 문자열).
  - 화이트리스트 명령은 지정된 저장소에서 subprocess 로 격리 실행.
  - 실행 실패(exit code != 0)인데 성공을 보고했거나, 실행 성공인데 실패를 보고한 경우 불일치(`fail`)로 판정.
  - 화이트리스트 외 명령은 `status="unverified"` 로 기록.
  - 타임아웃 및 실행 오류는 fail-closed(`fail`) 처리.

### 3.2 `scripts/summarize_worker_done.py`
- `check_field_types`: `verification` 내 개별 항목의 `command`/`result` 문자열 형식을 정적으로 검증하여 누락 시 `violations` 추가 및 verdict 격하(`blocked`).
- `summarize_worker_report`: `repo_path` 전달 시 `verify_verification_truth` 를 연계 실행하고 `unverified_commands` 및 상세 검증 결과를 요약 다이제스트에 반영.

### 3.3 `scripts/orca_level1_gate.py`
- `run_gate6_worker_done`: `summarize_worker_report` 를 통해 `verification` 진실성 검증 결과를 Level 1 Gate 6 에 통합. 진실성 위반 발생 시 게이트 FAIL 판정.

---

## 4. 회귀 테스트 및 검증 결과

`tests/test_orca_verification_truth.py` 에 다음 5대 시나리오를 구성하여 검증을 완수했습니다:
1. **(a) 형식 위반 verification 격하**: 빈 command, 빈 result, 객체형이 아닌 원소 등이 포함된 경우 verdict 가 `blocked` 로 격하되고 게이트 FAIL.
2. **(b) 조작된 result 차단**: 실패하는 테스트(`assert False`)를 `1 passed` 로 허위 기재한 경우 실제 재실행 불일치로 게이트 FAIL.
3. **(c) 화이트리스트 밖 명령 unverified 명시**: `npm test`, `docker build` 등이 `unverified` 로 정확히 표기되고 요약 다이제스트 및 게이트에 보존.
4. **(d) 정상 보고 통과**: 정상적인 pytest 및 규칙 검증 통과 보고서가 모든 게이트를 PASS.
5. **(e) 재실행 실패/타임아웃 fail-closed**: 존재하지 않는 테스트 경로 실행 및 타임아웃 발생 시 즉시 FAIL 처리.

### 검증 명령 결과
- `uv run pytest tests/test_orca_verification_truth.py tests/test_orca_worker_done_gate.py tests/test_orca_level1_gate.py -q`: 43개 테스트 전량 통과.
- `python3 scripts/validate_agent_rules.py --quiet`: 12/12 통과.
- `uv run ruff check scripts/ tests/test_orca_verification_truth.py`: 위반 0건 통과.
