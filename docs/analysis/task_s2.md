# src/tasks, src/ml, src/rag 모듈 Fail-Open 패턴 전수 조사 보고서

> **작성일**: 2026-08-18
> **태스크**: task_s2 (run_5a0930ee8cf2)
> **조사 범위**: `src/tasks/`, `src/ml/`, `src/rag/` 전체 모듈
> **목적**: 실패, 미검증, 절단, 부분, 미도달, 알 수 없음 등의 중간 상태가 SUCCESS 또는 정상으로 승격되는 Fail-Open 패턴 전수 조사 및 결함 후보 도출 (코드 수정 없음)

---

## 1. 개요 및 조사 결과 요약

`src/tasks`, `src/ml`, `src/rag` 디렉터리 내의 모든 소스 코드를 대상으로 예외 처리, 기본값 반환, 반환 타입 불일치, 상태 승격 로직을 전수 조사하였습니다.

조사 결과 총 **6건의 결함 후보**를 식별하였으며, 사전에 확인된 학습 승격 게이트의 fail-closed 방어 동작 1건에 대해 오탐 검증을 완료하였습니다.

### 결함 후보 심각도 분류 요약

| 심각도 | 건수 | 대상 모듈 및 주요 내용 |
| --- | --- | --- |
| **데이터 무손실 직결** | 0건 | DB 원본 데이터 손실이나 스키마 훼손에 직결되는 fail-open 없음 |
| **판정 오염** | 2건 | `src/ml/monitoring.py` (표본 부재 시 PSI 0.0 반환 -> STABLE 승격), `src/tasks/automation_tasks.py` (테이블 누락 등 inspect 경고 발생 시에도 SUCCESS 승격) |
| **실행 은폐** | 2건 | `src/tasks/automation_tasks.py` (추론 검증 건너뜀 시 SUCCESS 승격), `src/tasks/scheduled_tasks.py` (기관 이력/스냅샷 집계 실패 시 스케줄 SUCCESS 유지) |
| **경미** | 2건 | `src/rag/vector_store.py` (ChromaDB 검색 실패 시 빈 목록 반환 -> 200 OK 응답), `src/rag/structured_data.py` (날짜 파싱 실패 시 조건 누락 -> 전체 기간 조회) |

---

## 2. 결함 후보 상세 분석

### 후보 1: PSI 모니터링 표본 부재 시 STABLE 승격

- **파일 및 라인**: [`src/ml/monitoring.py:28-29`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/ml/monitoring.py#L28-L29), [`src/ml/monitoring.py:58-66`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/ml/monitoring.py#L58-L66)
- **삼키는 기전**: `calculate_psi(expected, actual)` 함수에서 `len(expected) == 0 or len(actual) == 0`인 경우 드리프트를 계산할 수 없음에도 예외 발생이나 측정 불가 상태를 반환하지 않고 `0.0`을 반환합니다.
- **그 결과 잘못 보고되는 상태**: `check_feature_drift`에서 `psi = 0.0`으로 수신되어 `drift_detected: False`, `action: "STABLE"`(정상 안정)으로 판정됩니다. 즉, 데이터 누락/표본 부재(미검증/계산 불가) 상태가 "정상 안정" 상태로 승격(Fail-open)됩니다.
- **오탐 반증**: 표본이 0건인 것은 안정 상태가 아니라 모니터링 불능(UNAVAILABLE/UNKNOWN) 상태이므로, 0.0을 반환하여 STABLE 판정을 내리는 것은 명백한 fail-open 결함입니다.
- **심각도**: **판정 오염**

---

### 후보 2: 자동화 태스크 추론 검증 스텝 건너뜀 시 STATUS_SUCCESS 승격

- **파일 및 라인**: [`src/tasks/automation_tasks.py:198-203`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/automation_tasks.py#L198-L203), [`src/tasks/automation_tasks.py:427-433`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/automation_tasks.py#L427-L433)
- **삼키는 기전**: `_step_predict`는 가용 모델이 없거나 공고 표본이 없을 때 `("검증 가능한 모델 또는 공고가 없어 예측 검증을 건너뜁니다.", {"pass_all": False, "model_count": len(available)})` 튜플(2개 요소)을 반환합니다. 파이프라인 디스패치 루프(`run_automation_pipeline`)는 2개 요소 튜플 처리 시 `metrics.get("status")`가 없으면 기본값인 `STATUS_SUCCESS`를 부여합니다.
- **그 결과 잘못 보고되는 상태**: 등록된 모델이 0개이거나 공고가 없어 추론 검증을 전혀 수행하지 못하고 건너뛰었음(`pass_all: False`)에도 불구하고, 해당 스텝 및 파이프라인 전체가 `STATUS_SUCCESS`로 완료됩니다.
- **오탐 반증**: `_step_predict` 반환 딕셔너리에 명시적인 `"status": "failed"` 또는 `"skipped"`가 누락되어 디스패처가 강제로 `STATUS_SUCCESS`로 판정하므로, 모델 부재 및 검증 누락이 성공으로 위장되는 실행 은폐 결함입니다.
- **심각도**: **실행 은폐**

---

### 후보 3: 데이터 무결성/ChromaDB 점검 경고 발생 시 STATUS_SUCCESS 승격

- **파일 및 라인**: [`src/tasks/automation_tasks.py:338-351`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/automation_tasks.py#L338-L351), [`src/tasks/automation_tasks.py:427-433`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/automation_tasks.py#L427-L433)
- **삼키는 기전**: `_step_inspect`는 DB 필수 테이블 누락(`missing_tables`), ChromaDB 임베딩 0건(`vector_count == 0`), 48시간 초과 수집 지연 등 치명적 문제를 `warnings`에 누적하지만, 반환값은 2개 요소 튜플 `(summary, metrics)`이며 `metrics`에는 `"status"` 키가 없습니다.
- **그 결과 잘못 보고되는 상태**: DB 필수 테이블이 누락되거나 ChromaDB 벡터 데이터가 통째로 비어 있는 치명적 장애 상태에서도 `metrics.get("status")`가 없기 때문에 스텝 상태가 `STATUS_SUCCESS`로 처리되어 전체 파이프라인이 성공으로 기록됩니다.
- **오탐 반증**: 필수 테이블 누락이나 벡터DB 비어있음과 같은 중대 시스템 불능 상태가 감지되었음에도 `STATUS_SUCCESS`로 보고되는 것은 인프라 점검 목적에 반하는 fail-open입니다.
- **심각도**: **판정 오염**

---

### 후보 4: 정기 스케줄 후속 집계(기관 이력/스냅샷) 실패 시 success 상태 유지

- **파일 및 라인**: [`src/tasks/scheduled_tasks.py:148-174`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/scheduled_tasks.py#L148-L174), [`src/tasks/scheduled_tasks.py:96-101`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/scheduled_tasks.py#L96-L101)
- **삼키는 기전**: `nightly_schedule_task` 및 `development_data_refresh_task`에서 `_rebuild_ranking_snapshots()`와 `_rebuild_institution_stats()`를 비동기 실행할 때, 내부에서 발생하는 모든 예외를 잡아서 `{"status": "failed", "error": str(exc)}` 딕셔너리로 변환하고 상위 스케줄의 `outcome["status"]`는 변경하지 않습니다.
- **그 결과 잘못 보고되는 상태**: 기관 이력 집계가 실패하여 추론 경로의 기관 낙찰률 통계가 최신화되지 못해 train/serve skew가 발생할 위험이 있음에도 불구하고, 스케줄 태스크의 최종 상태는 파이프라인 성공에 따라 `status: "success"`로 반환됩니다.
- **오탐 반증**: 주석에 "실패해도 야간 스케줄 전체를 실패로 만들지 않는다"는 완화 설계 의도가 있으나, 기관 통계 실패는 추론과 학습의 정합성에 직결되므로 스케줄 최종 상태에 부분 실패(`partial_failure`)나 경고 플래그 없이 완전 `success`로 끝나는 것은 장애 은폐 성격이 있습니다.
- **심각도**: **실행 은폐**

---

### 후보 5: ChromaDB 벡터 검색 실패 시 챗봇 정상 응답(200 OK) 승격

- **파일 및 라인**: [`src/rag/vector_store.py:43-49`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/rag/vector_store.py#L43-L49), [`src/rag/engine.py:309-314`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/rag/engine.py#L309-L314)
- **삼키는 기전**: `retrieve_semantic_context`에서 ChromaDB 조회 중 예외 발생 시 에러 로그만 남기고 `[]` (빈 문서 목록)을 반환합니다.
- **그 결과 잘못 보고되는 상태**: ChromaDB 장애나 임베딩 조회 실패가 발생해도 상위 RAG 엔진은 이를 "일치하는 지식 문서가 0건인 정상 상황"으로 해석하여 Fallback 답변을 생성하고, 최종 챗봇 API는 200 OK 정상 상태로 응답합니다.
- **오탐 반증**: 챗봇 UI의 가용성을 유지하기 위한 정상적인 Graceful Degradation(오류 문구가 LLM에 주입되는 왜곡 방지) 설계이나, RAG 인프라 장애가 단순 검색 결과 0건으로 승격되어 운영 가시성이 저하되는 fail-open 특성을 갖습니다.
- **심각도**: **경미**

---

### 후보 6: RAG 정형 데이터 질의 시 잘못된 날짜 파싱 조건 누락

- **파일 및 라인**: [`src/rag/structured_data.py:55-59`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/rag/structured_data.py#L55-L59), [`src/rag/structured_data.py:63-71`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/rag/structured_data.py#L63-L71)
- **삼키는 기전**: `_parse_date` 함수에서 날짜 문자열 형식이 올바르지 않아 `ValueError`가 발생하면 `None`을 반환하며, `_resolve_window`는 `date_from, date_to`를 `None`으로 설정합니다.
- **그 결과 잘못 보고되는 상태**: 사용자가 잘못된 형식의 날짜 필터를 전달했을 때 파싱 오류를 알리지 않고 날짜 필터 조건이 완전히 제거된 "전체 기간 데이터"가 정상 질의 결과로 반환됩니다.
- **오탐 반증**: 잘못된 질의 매개변수를 오류로 처리하지 않고 전체 기간으로 범위를 자동 확장하여 응답하므로, 사용자가 의도하지 않은 방대한 통계가 정상 데이터로 반환될 수 있습니다.
- **심각도**: **경미**

---

## 3. 오탐 검증 결과 (정상 Fail-Closed 확인 항목)

### 승격 게이트(Promotion Gate)의 서빙 지표 부재 처리

- **확인 대상**: [`src/ml/promotion.py:185-230`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/ml/promotion.py#L185-L230), [`src/tasks/retrain_task.py:178-191`](file:///Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/src/tasks/retrain_task.py#L178-L191)
- **검증 내용**: 서빙 모델의 `metadata.json` 또는 사이드카 파일이 없거나 깨져서 지표를 읽을 수 없을 때 `load_serving_metrics`는 `({}, {})`를 반환합니다.
- **판정 결과**: `retrain_task.py`의 `run_retrain_pipeline_task`에서 `champion_metrics`가 비어있는 경우 `recommendation: "REJECT_CHALLENGER"`로 승격을 기각하도록 명시적으로 분기 처리되어 있습니다.
- **결론**: 지표 계산 실패나 비교 불가 상황에서 승격이 자동으로 통과되는 fail-open이 존재하지 않으며, 안전하게 fail-closed로 동작함을 확인하였습니다.
