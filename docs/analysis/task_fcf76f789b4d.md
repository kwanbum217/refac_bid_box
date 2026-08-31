# 워커 모델 정책 drift 및 CURRENT_STATE 모순 자동 검증 분석 보고서

> **작성일**: 2026-08-31
> **Task ID**: `task_fcf76f789b4d`
> **관련 파일**: [`../../scripts/validate_agent_rules.py`](../../scripts/validate_agent_rules.py), [`../../tests/test_validate_agent_rules.py`](../../tests/test_validate_agent_rules.py), [`../ops/orca_worker_model_pool.md`](../ops/orca_worker_model_pool.md), [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`../../AGENTS.md`](../../AGENTS.md)

---

## 1. 개요 및 배경

2026-08-31 외부 감사에서 [`AGENTS.md`](../../AGENTS.md), [`docs/ops/orca_worker_model_pool.md`](../ops/orca_worker_model_pool.md), [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py)의 모델 배정 정책이 세 갈래로 갈라졌던 사실이 확인되었습니다. 당시 CI의 규칙 검증기는 이 drift를 감지하지 못하고 통과 상태였습니다.

아울러 [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)에서도 동일 결함(q21 등)이 한쪽에서는 해소로, 다른 쪽에서는 수정 미적용으로 동시에 기술되는 내부 서술 모순이 발생한 바 있습니다. 이 문서는 코디네이터가 세션 시작 시 가장 먼저 읽는 운영 상태 정본이므로, 내부 모순 발생 시 후속 에이전트에게 상반된 지시를 전달하게 됩니다.

본 작업에서는 이러한 정책 drift와 정본 서술 모순을 사전 차단하기 위해 `scripts/validate_agent_rules.py`에 3종의 자동 검증기를 추가하고 단위 테스트로 고정했습니다.

---

## 2. 신규 검증기 구현 상세

### 2.1 워커 모델 배정표 정합성 검사 (`check_worker_model_pool_drift`)

- **검증 대상**: [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py)의 `TIER_POLICY` 실행 정본과 [`docs/ops/orca_worker_model_pool.md`](../ops/orca_worker_model_pool.md) 1장 표.
- **검증 규칙**:
  1. 마크다운 표 파싱: `| 역할 (role) | 위험도 (risk) | 1순위 (Primary) | 2순위 (Fallback) |` 형식의 표를 기계적으로 추출.
  2. 표 부재/파싱 실패 시 Fail-Closed: 표를 찾지 못하거나 형식이 깨진 경우 통과가 아닌 실패(`FAIL`)로 처리하여 표 삭제를 통한 검사 무력화 방지.
  3. 역할(role) x 위험도(risk) 조합별 Primary 및 Fallback 일치 검증:
     - 값 불일치(`mismatches`)
     - 코드에만 존재하는 조합(`code_only`)
     - 문서에만 존재하는 조합(`doc_only`)
  4. 불일치 발생 시 상세 내역(조합 키 및 상이한 값)을 detail에 명확히 기록.

### 2.2 AGENTS.md 워커 모델 배정표 부재 검사 (`check_agents_model_table_absence`)

- **검증 대상**: [`AGENTS.md`](../../AGENTS.md) 본문.
- **검증 규칙**:
  - `AGENTS.md`는 단일 진실 원천으로서 모델 배정에 대해 `scripts/orca_model_router.py`의 `TIER_POLICY` 포인터만 유지해야 함.
  - `MODEL_POOL`에 등록된 워커 모델 풀 키(`gemini-flash-high`, `qwen-plus` 등) 및 모델 ID(`gemini-3.7-flash-high`, `qwen3.7-plus` 등) 문자열이 `AGENTS.md` 본문에 직접 나타나면 구체 배정표의 재발생(drift)으로 간주하여 실패(`FAIL`) 처리.
  - 코디네이터 전용 모델(`gpt-5.6-terra` 등)은 제외하여 정당한 코디네이터 기본값 서술을 허용.

### 2.3 CURRENT_STATE 6.1 Unknowns 상태 모순 검사 (`check_current_state_unknowns_contradictions`)

- **검증 대상**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)의 `### 6.1 알려진 미해결 사항 (Unknowns)` 절.
- **탐지 범위 (기계로 확실히 잡는 범위)**:
  1. 단일 항목 내부 상태 모순: 항목 표제/괄호 내에 해소 표지(`해소`, `완료`, `종결`, `해결` 등)와 미해결 표지(`미해결`, `미적용`, `수정 미적용`, `미수행`, `미검증` 등)가 공존하는 경우.
  2. 복수 항목 간 동일 사안 상반 상태 기술: 정규화된 동일 표제 또는 공유 식별자(`q21` 등)를 갖는 항목들이 각각 상반된 상태(해소 vs 미해결)로 기술된 경우.
- **탐지 제외 및 한계 (못 잡는 범위)**:
  1. 6.1절 외 타 섹션(예: 2장 성능 정본, 4장 과업 우선순위)과의 문맥적 불일치.
  2. 완전히 상이한 자연어 문장으로 서술된 의미적 모순.
  3. 부분 해결 분기 서술 (예: 플랫폼별 상이한 상태 서술).
  4. 수치 지표의 논리적 모순이나 날짜 선후 관계 불일치.

---

## 3. 검증 결과 및 테스트 추가

`tests/test_validate_agent_rules.py`에 다음 8종 이상의 시나리오 테스트를 추가하였습니다:

1. 문서 표가 `TIER_POLICY`와 일치 시 통과 (`test_check_worker_model_pool_drift_match_passes`)
2. Primary 불일치 시 실패 및 상세 조합 출력 (`test_check_worker_model_pool_drift_primary_mismatch_fails`)
3. Fallback 불일치 시 실패 (`test_check_worker_model_pool_drift_fallback_mismatch_fails`)
4. 코드에만 있는 조합 존재 시 실패 (`test_check_worker_model_pool_drift_code_only_combination_fails`)
5. 문서에만 있는 조합 존재 시 실패 (`test_check_worker_model_pool_drift_doc_only_combination_fails`)
6. 표 파일 누락 및 파싱 불가 시 통과가 아닌 실패 (`test_check_worker_model_pool_drift_missing_file_or_unparseable_fails`)
7. `AGENTS.md`에 워커 모델 ID/풀 키 발견 시 실패 (`test_check_agents_model_table_absence`)
8. `CURRENT_STATE.md` 6.1절 단일 항목 및 복수 항목 간 모순 검출 (`test_check_current_state_unknowns_contradictions`)
9. 실제 저장소 실물 파일 기준 15개 전체 규칙 검증 통과 (`test_real_repo_validation_passes`)

모든 테스트는 `tmp_path` 기반의 격리된 임시 구조에서 수행되며 실제 저장소 파일을 수정하지 않습니다.
