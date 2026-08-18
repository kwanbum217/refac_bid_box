# src/app/services 및 src/app/api fail-open 패턴 전수 조사 보고서 (task_s1)

> **조사일시**: 2026-08-18
> **과업 ID**: task_s1 (Dispatch: task_72337aabd6a0 / Context: ctx_66975dd1b48a)
> **조사 대상**: `src/app/services` (26개 모듈 + `tools/` 7개 모듈), `src/app/api` (`ui.py` + `v1/` 8개 모듈) 총 42개 파일
> **원칙**: 코드를 수정하지 않고 조사 및 분석 결과만 보고 (이모지 미사용)

---

## 1. 조사 개요

2026-08-18 중간 상태(실패, 미검증, 절단, 부분, 미도달, 알 수 없음)가 `SUCCESS` 또는 정상 응답으로 부당하게 승격되는 fail-open 패턴을 `src/app/services`와 `src/app/api` 전역에서 전수 조사하였습니다.

이미 해결된 사실(`api_collector._run_ranges` 구간 실패 격리, `automation_orchestrator` run_mode 불일치 재사용 방지, `automation_tokens` 만료 검증 등)은 제외하고, 신규 결함 후보를 식별하였습니다.

---

## 2. 결함 후보 요약

| 번호 | 대상 위치 (file:line) | 삼키는 기전 | 결과 상태 | 심각도 |
| --- | --- | --- | --- | --- |
| 1 | `src/app/services/automation_orchestrator.py:263-268` | 실행 액션/파이프라인 미존재 시 `STATUS_SUCCESS` 승격 | `STATUS_SUCCESS` (완료) | 판정 오염 |
| 2 | `src/app/services/tools/bid_prediction_tool.py:290`<br>`src/app/api/v1/chatbot_format.py:68-140` | 비예가/모델 후보 전량 실패 건의 `status: success` 포장 및 0원/0% 표 렌더링 | `status: "success"` / 투찰가 0원 정상 표 | 판정 오염 |
| 3 | `src/app/services/collector_service.py:329-339` | 수집 후 집계 재구축/캐시 예열 예외 발생 시에도 전체 수집 상태 `success` 반환 | `metrics["status"] = "success"` | 경미 |
| 4 | `src/app/services/tools/automation_status_tool.py:189-194` | 활성 작업 상태 동기화 중 예외 발생 시 삼키고 `found: True` 반환 | `found: True` (정상 조회) | 경미 |

---

## 3. 후보별 상세 분석 및 오탐 반증

### 후보 1: 자동화 실행 시작 시 비파이프라인/미정의 액션의 `STATUS_SUCCESS` 승격
- **위치**: `src/app/services/automation_orchestrator.py:263-268`
- **삼키는 기전**:
  `start_automation_request` 진입 시 `request_obj`의 계획에 `action`도 없고 `pipeline_step`도 없으면(`if not action and not pipeline_step:`), 에러(`STATUS_FAILED`)나 거부 처리를 하지 않고 `request_obj.status = STATUS_SUCCESS`로 설정하며 `result_summary = "실행 파이프라인이 필요하지 않은 요청입니다."`를 남기고 즉시 종결합니다.
- **잘못 보고되는 상태**:
  요청된 액션 키가 카탈로그에 없거나 파이프라인 구성이 누락되어 실제 백그라운드 작업이 전혀 실행되지 않았음에도, 요청 레코드 상태가 `STATUS_SUCCESS`(완료)로 기록되고 호출자에게 작업 완료로 보고됩니다.
- **오탐 가능성 반증 결과**:
  파이프라인이 필요 없는 단순 조회형 액션을 위한 의도적 분기일 가능성을 검토했으나, 비파이프라인 요청은 챗봇 도구(내부 tool) 경로에서 즉시 처리되며 `AutomationRequest` 엔티티 자체가 비동기 파이프라인 실행용이므로, 실행 대상 부재를 `SUCCESS`로 종결하는 것은 명백한 fail-open 상태 승격입니다.
- **심각도**: `판정 오염`

---

### 후보 2: 투찰가 예측 도구의 비예가/추론 실패 건 `status: success` 반환 및 0원 표 출력
- **위치**:
  - `src/app/services/tools/bid_prediction_tool.py:290`
  - `src/app/api/v1/chatbot_format.py:68-140`
- **삼키는 기전**:
  `_predict_bid`에서 비예가 공고(`PriceDecisionMethod.NON_PREARNG`)이거나 모델 후보 전량 실패 시 `skipped: True`, `optimal_price: 0`, `prediction_rate: 0`, `skip_reason`을 반환합니다. 그러나 이를 호출하는 `execute` 함수는 개별 항목의 `skipped` 여부와 무관하게 전체 도구 결과를 `"status": "success"`로 반환합니다.
  이에 따라 챗봇 포맷터 `_build_direct_tool_answer`는 `prediction.get("status") != "success"`만 검사하고 `skipped` 플래그를 확인하지 않은 채, "추천 투찰가: 0원", "예상 낙찰률: 0.0%"로 구성된 정상 마크다운 표를 사용자에게 렌더링합니다.
- **잘못 보고되는 상태**:
  비예가 제도로 투찰가 산출이 불가하거나 모델 서버/추론 전량 장애로 예측을 수행하지 못한 공고가 "예측 성공"으로 처리되어 사용자에게 "추천 투찰가 0원"이라는 잘못된 값이 정상 답변으로 표출됩니다.
- **오탐 가능성 반증 결과**:
  도구 레벨에서 예외를 던지지 않고 사전 정의된 스킵 구조체를 반환하는 완충 설계였으나, 포맷터가 `skipped`를 검사하지 않고 0원 표를 그대로 렌더링하므로 실제 사용자 관점에서 실패가 성공으로 은폐되는 실질적 fail-open 결함입니다.
- **심각도**: `판정 오염`

---

### 후보 3: 수집 적재 후 대시보드 집계/캐시 예열 예외 발생 시 전체 수집 상태 `success` 판정
- **위치**: `src/app/services/collector_service.py:329-339`
- **삼키는 기전**:
  `collect_bids`에서 입찰공고/낙찰결과 DB 적재가 완료된 후 대시보드 요약 집계(`rebuild_bid_dataset_summaries`)나 캐시 예열(`warm_dashboard_stats_cache`, `warm_home_page_cache`) 중 예외가 발생하면 `metrics["cache_warmed"] = False`를 설정합니다. 그러나 최종 `failed_count`와 `status` 계산에서는 카테고리 수집 에러만 반영하므로, 집계/캐시 예열이 전량 실패해도 `metrics["status"]`는 `"success"`로 반환됩니다.
- **잘못 보고되는 상태**:
  대시보드 요약 및 캐시 갱신에 실패했음에도 수집 서비스의 상위 반환 상태가 `success`로 표시됩니다.
- **오탐 가능성 반증 결과**:
  수집 서비스의 주 과업은 G2B 원본 데이터의 무손실 DB 적재(G1)이며, DB 적재는 완료되었고 `cache_warmed=False` 필드가 별도로 명시되므로 수집 전체를 `failed`로 뒤집지 않는 것은 분리 격리 설계로 볼 수 있어 영향이 제한적입니다.
- **심각도**: `경미`

---

### 후보 4: 자동화 상태 조회 도구의 동기화 예외 은폐
- **위치**: `src/app/services/tools/automation_status_tool.py:189-194`
- **삼키는 기전**:
  활성 상태 작업에 대해 `sync_automation_status`를 호출하다가 예외가 발생할 경우, 예외를 발생시키거나 실패 처리하지 않고 `request_obj.result_summary`에 `"상태 동기화 보류: {exc}"`만 기재한 뒤 `found: True` 및 정상 payload로 포장하여 반환합니다.
- **잘못 보고되는 상태**:
  최신 실행 상태 동기화가 실패했음에도 도구 호출 결과가 정상 조회(`found: True`)로 보고됩니다.
- **오탐 가능성 반증 결과**:
  챗봇 대화 중 일시적 동기화 지연으로 대화 전체가 500 에러로 중단되는 것을 방지하고 마지막으로 기록된 상태를 안내하는 graceful degradation 동작이며, 요약문에 보류 사유가 포함되므로 심각한 상태 왜곡은 아닙니다.
- **심각도**: `경미`

---

## 4. fail-closed 정상 검증 영역

전수 조사 결과 아래 핵심 모듈 및 엔드포인트는 fail-closed 정책을 올바르게 준수하고 있음을 확인하였습니다.

1. **계정 인증 (`src/app/api/v1/accounts.py`, `src/app/core/security.py`)**:
   - 세션 저장소(Redis) 장애 시 401(비로그인)이 아닌 HTTP 503(`SessionStoreUnavailable`)을 반환하여 잘못된 로그아웃 오판 방지.
2. **검색 인덱스 (`src/app/services/search_index.py`, `src/app/api/v1/bids.py`)**:
   - Meilisearch 장애 시 MySQL fallback 실패나 인덱스 불가 시 HTTP 503(`SearchBackendUnavailable`)으로 명확히 전파.
3. **헬스체크 (`src/app/api/v1/health.py`)**:
   - MySQL, Redis, ModelRegistry 등 핵심 의존성 하나라도 실패 시 HTTP 503 `not_ready` 반환.
4. **챗봇 스트리밍 (`src/app/api/v1/chatbot.py:527-530`)**:
   - SSE 스트리밍 중 예외 발생 시 `event: error`로 클라이언트에 실패 사실과 `trace_id`를 명시 전달.

---

## 5. 결론

전수 조사 결과, 데이터 무손실(G1)에 직결되는 치명적 결함은 없으나, **비예가/모델추론 실패 건이 투찰가 0원으로 정상 렌더링되는 문제(후보 2)** 및 **비파이프라인 요청의 STATUS_SUCCESS 종결(후보 1)** 2건의 `판정 오염` 후보가 식별되었습니다.
본 Task의 지침에 따라 코드는 수정하지 않았으며, 향후 후속 Task에서 해당 후보들의 수정을 권장합니다.
