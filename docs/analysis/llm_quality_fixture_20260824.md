# LLM 품질 평가 Fixture v1 설계 보고서 (2026-08-24)

> **작성일**: 2026-08-24
> **작성자**: Orca Worker (Gemini 3.7 Flash)
> **대상 작업**: `task_cd8421ddd466`
> **평가 데이터셋**: [`data/eval/llm_quality_fixture_v1.json`](../../data/eval/llm_quality_fixture_v1.json)
> **검증 도구**: [`scripts/validate_llm_quality_fixture.py`](../../scripts/validate_llm_quality_fixture.py)

---

## 0. 요약

본 문서는 `gemma4:e4b` 와 `gemma4:e2b` 간 LLM 승격 판정을 정량적·객관적으로 수행하기 위한 기계 판독 가능(machine-readable) 품질 평가 fixture v1의 설계 근거, 문항 구성, 채점 루브릭 및 측정 절차를 정의합니다.

| 항목 | 수치 / 내용 | 비고 |
| --- | ---: | --- |
| 총 문항 수 | **19문항** | 전체 fixture 세트 |
| 컨텍스트 충족 문항 (`context_sufficient: true`) | **16문항** | 요구 기준(15문항) 초과 충족 |
| 거절 기대 문항 (`refusal_expected: true`) | **3문항** | 가상·미래·범위외 질의 환각 검증 |
| 채점 가능 명제/수치 (`expected_facts`) | **31개** | 검증 기준 및 허용오차 명시 |
| 자기모순 금지 규칙 (`must_not_claim`) | **전 문항 적용** | 데이터 부재 주장 후 비교 수행 방지 |
| 스키마 검증기 의존성 | **표준 라이브러리 전용** | `scripts/validate_llm_quality_fixture.py:1` |

---

## 1. Fixture 설계 배경 및 원칙

### 1.1 배경
이전 모델 비교([`docs/analysis/llm_model_comparison_e4b_e2b_20260824.md:1`](llm_model_comparison_e4b_e2b_20260824.md#L1))에서 `gemma4:e2b`는 `llm_ms` P50 -54.1%의 압도적 속도 우세를 보였으나, 품질 표본이 5문항에 불과했고 그중 4문항이 컨텍스트 부족 상태였습니다. 또한 기존의 "사실 오류 0건" 평가는 실제 Ground Truth(참조 정답) 대조 없이 지면만 대조한 한정 판정이었으며, 4번 문항에서 관측된 **"데이터가 없다고 말한 뒤 곧바로 비교를 수행하는 자기모순"**과 같은 논리 결함을 포착하지 못했습니다.

### 1.2 핵심 설계 원칙
1. **실제 KB 및 DB 근거 결박**: 모든 컨텍스트 충족 문항은 ChromaDB `bidding_kb` 및 MySQL 정형 통계에 실제 존재하는 근거 ID(`expected_evidence_ids`)와 1:1로 결박합니다.
2. **채점 가능성 (Gradeable Facts)**: 모호한 서술형 평가를 배제하고, 객관적으로 검증 가능한 명제(`proposition`), 법정 수치(`numeric`), 분류명(`category`), 계산 수식(`formula`) 단위로 분해하여 오차 허용치(`numeric_tolerance`)를 함께 부여합니다.
3. **금지 진술 및 자기모순 차단 (`must_not_claim`)**: 각 문항별로 사실 왜곡, 도메인 내부 코드 노출(`Servc`, `Thng` 등), 데이터 부재를 선언한 뒤 비교를 전개하는 자기모순을 명시적으로 금지합니다.
4. **의도적 거절 문항 분리**: 컨텍스트가 존재하지 않는 가상/미래/도메인 외 질의(3문항)를 명시적으로 분리하여 환각(Hallucination) 억제 능력을 측정합니다.

---

## 2. 문항별 출처 및 근거 체계

| 문항 ID | 도메인 분류 | 질문 요약 | 근거 식별자 (`expected_evidence_ids`) | 주요 검증 팩트 및 허용오차 |
| :--- | :--- | :--- | :--- | :--- |
| `q01` | 적격심사 | 적격심사 기본 심사 항목 및 낙찰자 결정 구조 | `KB-LAW-KNTCE-001`, `KB-EVAL-QUAL-001` | 가격+수행능력 종합평점, 최저가순 순차심사 |
| `q02` | 정형 통계 | 2025년 물품 낙찰 평균 낙찰률 | `DB-SQL-RESULT-STAT-2025-THNG`, `DB-AGG-BIDRESULT-RATE-001` | `91.1075%` (허용오차 ±0.01%p) |
| `q03` | 입찰보증금 | 입찰보증금 법정 원칙 및 완화 비율 | `KB-LAW-KNTCE-ENFORCE-37`, `KB-RULE-BID-DEPOSIT-01` | 원칙 5%(100분의 5), 완화 2.5%(100분의 2.5) |
| `q04` | 수요기관 비교 | 수요기관별 낙찰 금액 상위 기관 비교 | `DB-SQL-RESULT-TOP-INST-001`, `DB-AGG-DMINSTT-AMT-RANK` | 순위 통계 일관성, **자기모순 금지** |
| `q05` | 계약보증금 | 계약보증금 기본 법정 비율 및 감경 기준 | `KB-LAW-KNTCE-ACT-12`, `KB-RULE-CONTRACT-DEPOSIT-01` | 원칙 10%(100분의 10), 특례 5% |
| `q06` | 예정가격 | 복수예비가격 추첨 및 예정가격 결정 원칙 | `KB-PROC-PRED-PRICE-001`, `KB-RULE-MULTI-PREPRICE-15-4` | 15개 작성, 4개 최다추첨 산술평균 |
| `q07` | 분류 체계 | BIDBOX 4대 입찰 분야 및 표기 규칙 | `KB-DOMAIN-CAT-001`, `SRC-MODELS-BIDS-CATEGORY-LABELS` | 물품, 공사, 용역, 외자 (용역 코드 사용자명 준수) |
| `q08` | 지체상금 | 물품/공사/용역 1일당 법정 지체상금율 | `KB-LAW-KNTCE-ENFORCE-74`, `KB-RULE-DELAY-PENALTY-01` | 물품 0.075%, 공사 0.05%, 용역 0.125% |
| `q09` | 투찰 공식 | 투찰률(낙찰률) 및 사정율 계산 공식 | `KB-FORMULA-BID-RATE-001`, `KB-FORMULA-ASSESS-RATE-001` | (투찰가/예가)*100, (예가/기초가)*100 |
| `q10` | 적격심사 하한 | 조달청 물품 적격심사 구간별 낙찰하한율 | `KB-DAPS-THNG-QUAL-RATE-001`, `KB-QUAL-LOWER-LIMIT-TABLE` | 10억 이상 80.495%, 10억 미만 84.245% |
| `q11` | 공동도급 | 공동이행방식과 분담이행방식 차이 및 책임 | `KB-LAW-JOINT-CONTRACT-001`, `KB-RULE-JOINT-OPERATION-TYPE` | 출자비율 연대책임 vs 분담구간 개별책임 |
| `q12` | 하자보수 | 시설공사 하자보수보증금율 및 보증기간 | `KB-LAW-KNTCE-ENFORCE-62`, `KB-RULE-DEFECT-WARRANTY-01` | 2%~5% 법정 범위, 1년~10년 담보책임기간 |
| `q13` | 계약 방식 | 법정 주요 5대 계약 체결 방식 | `KB-LAW-KNTCE-ACT-07`, `KB-RULE-BID-METHODS-5` | 일반경쟁, 제한경쟁, 지명경쟁, 수의계약, 협상계약 |
| `q14` | 용역 하한 | 조달청 일반용역 적격심사 낙찰하한율 | `KB-DAPS-SERVC-QUAL-RATE-001`, `KB-QUAL-SERVC-LOWER-LIMIT` | 5억 이상 85.495%, 2억~5억 87.995% |
| `q15` | 순공사비 A값 | 공사 A값 개념 및 입찰가격 하한 산식 | `KB-RULE-A-VALUE-FORMULA-001`, `KB-PROC-CONST-AVALUE-01` | 사후정산비용, `[(예가-A)*하한율]+A` |
| `q16` | 부정당 제재 | 부정당업자 입찰참가자격 제한 기간 및 사유 | `KB-LAW-KNTCE-ACT-27`, `KB-RULE-SANCTION-PERIOD-01` | 최대 2년, 담합/사기/미이행 등 핵심 사유 |
| `q17` | [거절] 가상공고 | 2029년 화성 우주기지 건설공사 낙찰 결과 | - | DB/KB 부재 명시 및 환각 없이 거절 |
| `q18` | [거절] 미개찰정보 | 내일 개찰 예정 사업 사전 확정 예가 질의 | - | 미개찰/비공개 내부정보 제공 불가 거절 |
| `q19` | [거절] 도메인외 | 2030년 EU 고속철도 신호체계 입찰 통계 | - | 수집 범위 외 해외 데이터 부재 명시 거절 |

---

## 3. 품질 측정 및 승격 판정 절차 초안

향후 모델 측정 Task 수행 시 준수해야 하는 공식 절차 규약입니다.

### 3.1 측정 환경 및 파라미터 고정 규약
1. **모델당 문항별 3회 반복 측정**: 생성 변동성(variance)과 모델 간 고유 품질 차이를 분리하기 위해 각 문항에 대해 **최소 3회 독립 실행**하여 최빈/최악/평균 점수를 집계합니다.
2. **동일 Temperature 엄격 고정**: 모든 모델(`gemma4:e4b`, `gemma4:e2b`)에 대해 운영 기본값인 `temperature = 0.1` (또는 지정된 단일 하이퍼파라미터)을 동일하게 강제합니다.
3. **호스트 부하 규약 결박**: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)에 따라 측정 중 호스트 부하 median <= 30%, max <= 45% 조건을 충족해야 유효 측정으로 인정합니다.

### 3.2 채점 기준 및 합격선 (Grading Protocol)
- **정확도 (Accuracy, 10점 만점)**:
  - `expected_facts` 내 모든 명제 및 수치가 허용오차 내에 부합하는 경우 10점.
  - `must_not_claim` 위반(자기모순, 사실 왜곡, 허위 수치 제시) 발생 시 해당 문항 **0점 처리**.
- **인용 충실도 (Citation & Guard, 가점/감점)**:
  - `citation_required: true` 문항에서 본문 내 `Source [1]`, `[2]` 등 적절한 근거 출처 표기 여부 검증.
- **승격 판정 조건**:
  1. 16개 컨텍스트 충족 문항의 평균 정확도 점수가 기준선(e4b) 대비 동등 이상 (회귀 없음).
  2. 3개 거절 기대 문항에 대해 환각 발생 0건 (100% 정상 거절).
  3. 자기모순(`must_not_claim`) 발생 0건.

---

## 4. 검증 결과

- 검증 스크립트: `scripts/validate_llm_quality_fixture.py`
- 단위 테스트: `tests/test_validate_llm_quality_fixture.py`
- 스키마 검증 결과: 19/19 문항 검증 통과 (16 컨텍스트 충족, 3 거절 기대, 중복 0건, 필수 필드 누락 0건)
