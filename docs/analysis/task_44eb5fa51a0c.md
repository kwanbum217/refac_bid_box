# LLM 품질 측정 하네스 검색 실패(Retrieval Miss) 분리 및 요약 블록 구축 분석 보고서

> **문서 식별자**: `docs/analysis/task_44eb5fa51a0c.md`
> **작업 일시**: 2026-08-30
> **작업 ID**: `task_44eb5fa51a0c`
> **관련 사양**: `.orca/capsules/task_44eb5fa51a0c/capsule.yaml`
> **대상 파일**: `scripts/measure_llm_quality.py`, `tests/test_measure_llm_quality.py`

---

## 1. 개요 및 배경

2026-08-30 RAG v2 32문항 정본 실측(`docs/analysis/blind_fixture_v2_canonical_20260830.md`)에서 신규 정본(`6210ee1`)의 Citation 지표가 100.0%(70/70)에서 97.2%(70/72)로, 과잉응답이 1건에서 3건으로 악화된 것처럼 집계되는 현상이 관측되었습니다.

원인을 정밀 조사한 결과, 이는 모델의 품질 저하가 아닌 **측정 하네스 채점 규약의 구조적 결함**이었습니다.
- **문항 q21 상황**: "2026년 조림지 풀베기사업 2차(동부지구)" 질의에 대해 지식 베이스 검색이 기대 근거(`bid_10169448`)를 검색하지 못함(`evidence_recall=0.0`).
- **과거 동작**: 모델이 영암지구라는 다른 공고의 정보를 근거 표기까지 붙여 사실처럼 허위 답변(환각)을 생성하였으나, 하네스는 이를 정상 답변 및 인용 통과로 오판함.
- **개선 동작**: 새 모델은 동부지구 정보가 검색 컨텍스트에 없음을 인지하고 정직하게 거부함.
- **채점 결함**: fixture의 `context_sufficient=true` 선언만 기계적으로 대조하여 검색 실패로 인한 실제 컨텍스트 부재 상태에서의 정직한 거부를 "과잉거절/과잉응답"으로, 거부 답변의 인용 부재를 "Citation 누락"으로 벌하는 역전 현상이 발생함.

본 과업에서는 검색 실패 상황을 명시적으로 식별하는 `retrieval_miss` 필드를 도입하고, 검색 실패를 제외한 합리적 집계와 제외 전 원시값을 동시에 투명하게 산출물 최상위 `summary` 블록에 기록하도록 하네스를 개선하였습니다.

---

## 2. 주요 변경 사항

### 2.1 결과 항목 단위 검색 실패(`retrieval_miss`) 식별
- `scripts/measure_llm_quality.py`의 `score_item` 함수에 `retrieval_miss` 불리언 필드를 추가하였습니다.
- 기대 근거(`expected_evidence_ids`)가 지정되어 있는데 `evidence_recall == 0.0`(적중 근거 수 0건)인 경우 `retrieval_miss = True`로 판정합니다.
- 기대 근거가 없거나(`expected_evidence_ids` 비어 있음) 일부라도 적중한 경우(`evidence_recall > 0`)는 `retrieval_miss = False`입니다.

### 2.2 순수 집계 함수 `compute_summary` 및 헬퍼 구현
측정 실행 없이도 과거 산출물이나 임의의 결과 배열에서 동일한 기준으로 요약을 도출할 수 있도록 순수 함수 `compute_summary(results)`를 분리 구현하였습니다.
- `is_retrieval_miss(record)`: 신규 `retrieval_miss` 필드가 없는 레거시 산출물 레코드에 대해서도 fallback 계산을 수행하여 호환성을 보장합니다.
- `_percentile(values, p)`: 외부 의존성 없이 선형 보간 방식으로 P50, P95 레이턴시를 계산합니다.

### 2.3 산출물 최상위 `summary` 블록 사양
산출물 최상위에 `summary` 블록을 구성하여 지표 해석의 주관성을 원천 차단하였습니다.

| 지표 그룹 | 필드명 | 계산 방식 및 사유 |
| --- | --- | --- |
| **요청 및 실패** | `total_requests`, `request_failures` | 전체 요청 수 및 네트워크/타임아웃 실패 건수 |
| **검색 실패 정보** | `retrieval_miss_count`, `retrieval_miss_ids` | 검색 실패 요청 수 및 대상 문항 ID 정렬 목록 |
| **Numeric 정확도** | `numeric_accuracy` (`passed`, `total`, `rate`) | **검색 실패 미제외**: 검색 실패 자체도 시스템 품질 지표이므로 가감 없이 반영 |
| **Evidence Recall** | `evidence_recall_mean` | **검색 실패 미제외**: 검색 실패 문항의 0.0 recall을 그대로 반영 |
| **Citation** | `citation` (`passed`, `total`, `rate`, `raw_passed`, `raw_total`, `raw_rate`) | **검색 실패 제외**: 검색 실패로 인한 거부 문항을 분모에서 제외하되, 제외 전 원시값을 함께 기록 |
| **Refusal 정확도** | `refusal_accuracy` (`passed`, `total`, `rate`, `raw_*`) | 거절 기대 문항의 정상 거절 여부 집계 |
| **과잉응답** | `over_response_count`, `raw_over_response_count` | **검색 실패 제외**: 검색 실패로 인한 정직한 거부를 과잉응답/과잉거절에서 제외하고, 원시값과 보정값을 병기 |
| **금지 표현 위반** | `forbidden_literal_violations_count` | 영문 코드 등 문자열 리터럴 매칭 위반 건수만 집계 (`semantic_forbidden_claims`는 자동 채점되지 않으므로 제외) |
| **레이턴시** | `latency_ms` (`p50`, `p95`, `max`) | 전체 성공 요청의 P50, P95, Max 레이턴시(ms) |

---

## 3. 검증 결과

### 3.1 회귀 및 단위 테스트 검증
`tests/test_measure_llm_quality.py`에 다음 단위 및 시나리오 테스트를 추가하였습니다:
1. `test_retrieval_miss_*`: 기대 근거 존재 및 적중 여부에 따른 `retrieval_miss` 판정 (True/False).
2. `test_is_retrieval_miss_helper`: 신규 및 레거시 레코드 판정.
3. `test_summary_numeric_and_recall_not_excluded`: numeric과 recall 집계에서 검색 실패 미제외 확인.
4. `test_summary_citation_excludes_retrieval_miss_and_keeps_raw`: citation 보정값 및 원시값 분리 집계 확인.
5. `test_summary_over_response_excludes_retrieval_miss_refusal_and_keeps_raw`: 정직한 거부의 과잉응답 제외 및 원시값 보존 확인.
6. `test_summary_semantic_claims_not_counted_as_violations`: 의미적 금지 주장이 위반 건수에 합산되지 않음 확인.
7. `test_summary_q21_case_validation`: q21 실측 시나리오(검색 실패 + 거부 + 인용 부재)에서 과잉응답 0건, Citation 100.0%(70/70) 판정 및 원시값(과잉응답 3건, 70/73) 보존 확인.

### 3.2 테스트 실행 결과
- `uv run pytest tests/test_measure_llm_quality.py -q`: **82 passed**
- `uv run pytest tests/ -q -m 'not data_assets'`: **2,672 passed, 6 skipped, 3 deselected** (전량 통과)
- `uv run ruff check src/ scripts/ tests/`: **All checks passed!**
- `python3 scripts/validate_agent_rules.py --quiet`: **12/12 건 통과**

---

## 4. 불변식 및 계약 준수 점검

1. **데이터 무손실(G1)**: `data/benchmarks`의 기존 산출물 수정 없음.
2. **Train/Serve 단일화**: `src/ml/features.py` 수정 없음.
3. **정본 판정 및 종료 코드**: `evaluate_canonical` 및 `exit_code` 로직 변경 없음.
4. **기존 필드 보존**: 기존 결과 항목 필드 이름 및 의미 100% 보존.
5. **이모지 금지**: 코드 주석, 커밋 메시지, 문서 전 영역 이모지 0건 준수.
