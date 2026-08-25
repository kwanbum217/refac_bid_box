# LLM 품질 평가 Fixture v1/v2 설계 및 근거 검증 보고서 (2026-08-24/2026-08-25)

> **작성일**: 2026-08-24
> **수정일**: 2026-08-25 (v2: 원자 numeric 팩트 분해, 금지 진술 분리, refusal 채점, 모델 라벨 결박, provenance 강화)
> **작성자**: Orca Worker
> **대상 작업**: `task_cd8421ddd466` (v1), `task_65064c460d26` (v2)
> **평가 데이터셋**: [`data/eval/llm_quality_fixture_v1.json`](../../data/eval/llm_quality_fixture_v1.json)
> **검증 도구**: [`scripts/validate_llm_quality_fixture.py`](../../scripts/validate_llm_quality_fixture.py)
> **실측 하네스**: [`scripts/measure_llm_quality.py`](../../scripts/measure_llm_quality.py)

---

## 0. 요약 및 변경 이력

### 0.1 v1 요약 (2026-08-24)
본 문서는 `gemma4:e4b` 와 `gemma4:e2b` 간 LLM 승격 판정을 정량적·객관적으로 수행하기 위한 기계 판독 가능(machine-readable) 품질 평가 fixture v1의 설계 근거, ChromaDB 지식베이스 실재 근거 결박 내역, 채점 루브릭 및 측정 절차를 정의합니다.

| 항목 | 수치 / 내용 | 비고 |
| --- | ---: | --- |
| 총 문항 수 | **19문항** | 전체 fixture 세트 |
| 컨텍스트 충족 문항 (`context_sufficient: true`) | **16문항** | 요구 기준(15문항) 초과 충족 |
| 거절 기대 문항 (`refusal_expected: true`) | **3문항** | 가상·미래·범위외 질의 환각 검증 |
| 지식베이스 실재 근거 ID (`expected_evidence_ids`) | **17개 실재 ID** | ChromaDB `bidding_kb` 512,348건 DB 100% 일치 |
| 채점 가능 명제/수치 (`expected_facts`) | **45개** | 검증 기준 및 허용오차 명시 |
| 자기모순 금지 규칙 (`must_not_claim`) | **전 문항 적용** | 데이터 부재 주장 후 비교 수행 방지 |
| 스키마 검증기 의존성 | **표준 라이브러리 전용** | `scripts/validate_llm_quality_fixture.py:1` |

### 0.2 v1 코디네이터 1차 반려 사유 및 교정 조치
- **반려 사유**: 초기 커밋(`310d908`)에서 `expected_evidence_ids`에 법령/규정 임의 코드(예: `KB-LAW-KNTCE-001`)를 가상으로 기재하여, ChromaDB `bidding_kb` 실측 시 실재 근거가 0건으로 판정됨.
- **교정 조치**:
  1. ChromaDB `bidding_kb` 컬렉션(512,348건)의 실제 SQLite 및 메타데이터를 직접 조회하여 실제 문서 ID(`bid_10015927`, `bid_7952020`, `bid_5880526` 등)와 공고명, 수요기관, 낙찰업체, 낙찰금액, 낙찰률 원본 데이터를 추출했습니다.
  2. 16개 컨텍스트 충족 문항 전체를 추출된 실제 지식베이스 데이터로 1:1 재작성하고, 수치 팩트의 오차 허용치(±0.01%p)를 명시했습니다.
  3. `scripts/validate_llm_quality_fixture.py`에 ChromaDB SQLite 데이터베이스 연동 검증을 추가하여, `expected_evidence_ids`가 지식베이스에 실재하지 않을 경우 검증이 즉시 실패(exit code 1)하도록 강화했습니다.

### 0.3 v2 주요 변경 사항 (2026-08-25, `task_65064c460d26`)
2026-08-24 e4b/e2b 품질 비교 보고에서 드러난 채점 결함과 provenance 결함을 수정했습니다.

| 결함 영역 | v1 문제점 | v2 해결 |
| --- | --- | --- |
| **복합 numeric 팩트** | 한 `expected_facts` 원소가 낙찰금액과 낙찰률 두 수치를 동시에 요구 (`expected_value`는 금액 하나만). 하나가 없어도 `numeric_all_found`가 true가 될 수 있음. | 모든 numeric 팩트를 **원자 단위로 분해**. 낙찰금액(`unit: 원, tolerance: 1`)과 낙찰률(`unit: %, tolerance: 0.01`)을 별도 `expected_facts` 원소로 분리. 총 45개 → **61개** expected_facts로 증가. |
| **금지 진술 채점** | `must_not_claim`에 규칙 설명문(예: "Servc 등 내부 영문 코드를 사용자 답변에 노출")이 포함되어 문자열 포함 검사 시 오탐 발생. | `forbidden_literals`(정확한 리터럴 매칭: Servc, Thng, Cnstwk, Frgcpt)와 `semantic_forbidden_claims`(자기모순 등 의미 기반 판정 필요 항목)로 **분리**. 전자는 대소문자 무시 자동 검사 + 매칭 근거 기록, 후자는 수동 판정 대상으로 별도 집계. |
| **refusal 채점 미구현** | `refusal_expected` 필드만 결과 JSON에 복사하고 실제 채점하지 않음. | `is_refusal()` 함수로 거절 판정 로직 구현. `expected_refusal`, `actual_refusal`, `refusal_correct`를 결과에 기록. 거절해야 하는데 답했거나 답해야 하는데 거절한 경우 실패로 집계. |
| **모델 라벨 결박 부재** | `--model-label`은 기록용. 시작/종료 `OLLAMA_MODEL`이 서로 같은지만 확인(`serving_model_consistent`). 라벨과 실제 모델이 다른지 검사 안 함. | **`--expected-model` 필수 인자 추가**. 시작/종료 `OLLAMA_MODEL`이 모두 `--expected-model` 값과 **정확히 일치**해야 통과. 불일치 시 0이 아닌 종료 코드(5)로 종료하고 정식 근거 저장 거부(fail-closed). |
| **base_url 포트 검증 없음** | `--base-url`이 실제 앱 컨테이너 발행 포트를 가리키는지 검증하지 않음. | `scripts/benchmark_provenance.py`의 `_parse_published_host_ports` 재사용하여 **포트 결박 검증**. 불일치 시 측정 중단(exit code 2). |
| **Provenance 미흡** | Git SHA, dirty 상태, 시작/종료 source identity, 런타임 OLLAMA_MODEL 미기록. | `benchmark_provenance.py`의 `get_git_status`, `verify_provenance_consistency` 재사용. **Git SHA, dirty 여부, source_identity_start/end, serving_model_start/end, base_url 검증 결과**를 `provenance` 객체에 기록. dirty 시 정식 근거 저장 거부(exit code 3). provenance 일관성 위반 시 exit code 4. |

---

## 1. Fixture 설계 배경 및 원칙

### 1.1 배경
이전 모델 비교([`docs/analysis/llm_model_comparison_e4b_e2b_20260824.md:1`](llm_model_comparison_e4b_e2b_20260824.md#L1))에서 `gemma4:e2b`는 `llm_ms` P50 -54.1%의 압도적 속도 우세를 보였으나, 품질 표본이 5문항에 불과했고 그중 4문항이 컨텍스트 부족 상태였습니다. 또한 기존의 "사실 오류 0건" 평가는 실제 Ground Truth(참조 정답) 대조 없이 지면만 대조한 한정 판정이었으며, 4번 문항에서 관측된 **"데이터가 없다고 말한 뒤 곧바로 비교를 수행하는 자기모순"**과 같은 논리 결함을 포착하지 못했습니다.

### 1.2 핵심 설계 원칙
1. **실제 ChromaDB `bidding_kb` 실재 근거 결박**: 모든 컨텍스트 충족 문항은 ChromaDB `bidding_kb` 컬렉션의 실제 문서 ID(`bid_...`)와 1:1로 결박하여 검증기가 데이터베이스 수준에서 존재성을 보증합니다.
2. **채점 가능성 (Gradeable Facts)**: 모호한 서술형 평가를 배제하고, 객관적으로 검증 가능한 명제(`proposition`), 실제 낙찰 수치(`numeric`) 단위로 분해하여 오차 허용치(`numeric_tolerance`)를 함께 부여합니다. **v2에서 numeric 팩트는 원자 단위(하나의 expected_facts = 하나의 수치) 원칙을 강제합니다.**
3. **금지 진술 및 자기모순 차단**: 각 문항별로 사실 왜곡, 도메인 내부 코드 노출(`Servc`, `Thng`, `Cnstwk`, `Frgcpt` 등), 데이터 부재를 선언한 뒤 비교를 전개하는 자기모순을 명시적으로 금지합니다. **v2에서 리터럴 매칭(`forbidden_literals`)과 의미 판정(`semantic_forbidden_claims`)을 분리하여 오탐을 방지합니다.**
4. **의도적 거절 문항 분리**: 컨텍스트가 존재하지 않는 가상/미래/도메인 외 질의(3문항)를 명시적으로 분리하여 환각(Hallucination) 억제 능력을 측정합니다. **v2에서 `refusal_expected`를 실제 채점합니다.**

---

## 2. 문항별 출처 및 실재 근거 체계 (v2)

| 문항 ID | 분야 | 질문 요약 | 실재 근거 ID (`expected_evidence_ids`) | 주요 실측 팩트 (원자 단위) |
| :--- | :--- | :--- | :--- | :--- |
| `q01` | 용역 | 봉화 공설운동장 리모델링 감리 용역 | `bid_10015927` | 공고번호, 수요기관(봉화군 체육시설사업소), 낙찰업체(건축사사무소 가온), **낙찰금액 46,602,100원**, **낙찰률 88.5100%** |
| `q02` | 용역 | 안녕 자두야 포스트프로덕션 용역 | `bid_10015878` | 수요기관(주식회사 아툰즈), 낙찰업체(씨아이씨미디어), **낙찰금액 33,000,000원**, **낙찰률 100.0000%** |
| `q03` | 용역 | 대구불로초 급식시설 환경개선 재해예방 | `bid_10015925` | 수요기관(대구동부교육지원청), 낙찰업체(대경안전전통소), **낙찰금액 1,585,800원**, **낙찰률 90.1390%** |
| `q04` | 용역 | 양평군 통학버스 임차 동부권 vs 서부권 비교 | `bid_10015865`, `bid_10015863` | 동부권: 낙찰업체(자유고속관광), **낙찰금액 1,074,000원**, **낙찰률 90.1950%** / 서부권: 낙찰업체(뉴월드컵고속관광), **낙찰금액 941,800원**, **낙찰률 89.3550%** |
| `q05` | 용역 | 예일여중 인조잔디 철거운반 및 재활용처리 | `bid_10015923` | 공고번호, 낙찰업체(장월조경), **낙찰금액 59,716,640원**, **낙찰률 88.0510%** |
| `q06` | 용역 | 남정공공하수처리시설 건설사업관리용역 | `bid_10015920` | 수요기관(영덕군 물관리사업소), 낙찰업체(대흥토목이엔지), **낙찰금액 50,329,400원**, **낙찰률 88.2890%** |
| `q07` | 용역 | 인천공항 T2 주차타워 건립 타당성조사 | `bid_10015856` | 수요기관(인천국제공항공사), 낙찰업체(팀플렉사), **낙찰금액 31,460,000원**, **낙찰률 99.6120%** |
| `q08` | 공사 | 2026년 금정산성 남문계단 보수정비공사 | `bid_7952020` | 수요기관(부산 금정구), 낙찰업체(서오건설), **낙찰금액 57,953,680원**, **낙찰률 90.5170%** |
| `q09` | 공사 | 갈산고등학교 기숙사 수선 기계설비공사 | `bid_7952018` | 공고번호, 수요기관(홍성교육지원청), 낙찰업체(일진산업), **낙찰금액 127,963,740원**, **낙찰률 90.6140%** |
| `q10` | 공사 | 2026년 시공원 보수정비사업(봉제산) | `bid_7952016` | 수요기관(서울 강서구), 낙찰업체((주)목전엘앤디), **낙찰금액 151,886,530원**, **낙찰률 90.4670%** |
| `q11` | 공사 | 매곡면 옥전리 세천정비공사 | `bid_7952015` | 수요기관(충북 영동군), 낙찰업체((주)오대건설), **낙찰금액 34,437,020원**, **낙찰률 90.3320%** |
| `q12` | 공사 | 충북대병원 노후 실습공간 개선공사 | `bid_7952013` | 수요기관(충북대병원), 낙찰업체(명문전기), **낙찰금액 15,098,070원**, **낙찰률 90.0930%** |
| `q13` | 공사 | 양강면 두릉리 마을안길 사면보강 공사 | `bid_7952012` | 공고번호, 낙찰업체(효성건설), **낙찰금액 27,324,730원**, **낙찰률 90.3160%** |
| `q14` | 물품 | 2026년 김량장 브랜드 홍보물품 제작 | `bid_5880526` | 수요기관(경기 용인시), 낙찰업체(디혜 협동조합), **낙찰금액 26,400,000원**, **낙찰률 88.0000%** |
| `q15` | 물품 | 연세대 앵커사업 바이오헬스 장비 구매 | `bid_5880502` | 수요기관(연세대 미래캠퍼스), 낙찰업체(유비코리아), **낙찰금액 19,000,300원**, **낙찰률 95.0010%** |
| `q16` | 물품 | 굴포하수처리시설 슬러지수집기 PLC 구매 | `bid_5880499` | 수요기관(경기 부천시), 낙찰업체(주식회사 진성), **낙찰금액 44,108,495원**, **낙찰률 88.0710%** |
| `q17` | [거절] | 2029년 화성 우주기지 건설공사 낙찰 결과 | - | DB/KB 부재 명시 및 환각 없이 거절 |
| `q18` | [거절] | 내일 개찰 예정 사업 사전 확정 예가 질의 | - | 미개찰/비공개 내부정보 제공 불가 거절 |
| `q19` | [거절] | 2030년 EU 고속철도 신호체계 입찰 통계 | - | 수집 범위 외 해외 데이터 부재 명시 거절 |

> **v2 변경**: 각 문항의 `expected_facts`에서 numeric 타입이 낙찰금액/낙찰률로 분리되었습니다. `forbidden_literals`는 전 문항 공통으로 `["Servc", "Thng", "Cnstwk", "Frgcpt"]`를 포함하며, `semantic_forbidden_claims`는 문항별 특화 규칙(자기모순, 허위 기재 등)을 담습니다.

---

## 3. 품질 측정 및 승격 판정 절차 (v2 업데이트)

### 3.1 측정 환경 및 파라미터 고정 규약
1. **모델당 문항별 3회 반복 측정**: 생성 변동성(variance)과 모델 간 고유 품질 차이를 분리하기 위해 각 문항에 대해 **최소 3회 독립 실행**하여 최빈/최악/평균 점수를 집계합니다.
2. **동일 Temperature 엄격 고정**: 모든 모델(`gemma4:e4b`, `gemma4:e2b`)에 대해 운영 기본값인 `temperature = 0.1` (또는 지정된 단일 하이퍼파라미터)을 동일하게 강제합니다.
3. **호스트 부하 규약 결박**: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)에 따라 측정 중 호스트 부하 median <= 30%, max <= 45% 조건을 충족해야 유효 측정으로 인정합니다.
4. **`--expected-model` 필수 지정**: 측정 대상 모델명(예: `gemma4:e4b`)을 `--expected-model`로 전달해야 하며, 시작/종료 시점의 컨테이너 `OLLAMA_MODEL`이 이 값과 정확히 일치해야만 통과합니다.
5. **`--base-url` 포트 결박**: `--base-url`의 포트가 `--app-container`의 실제 발행 포트와 일치해야 측정 개시. 불일치 시 즉시 중단.

### 3.2 채점 기준 및 합격선 (Grading Protocol v2)
- **정확도 (Accuracy, 10점 만점)**:
  - 모든 `expected_facts`(proposition, **원자 numeric**)이 허용오차 내에 부합하는 경우 10점.
  - `forbidden_literal_violations` 발생 시(내부 코드 노출) 해당 문항 **0점 처리**.
  - `semantic_forbidden_claims`는 자동 판정하지 않고 수동 판정 대상으로 별도 집계.
- **거절 채점 (Refusal Grading)**:
  - `refusal_expected=true` 문항: 거절 응답 시 10점, 답변 시 0점.
  - `refusal_expected=false` 문항: 정상 답변 시 채점 진행, 거절 시 0점.
  - 결과 JSON에 `expected_refusal`, `actual_refusal`, `refusal_correct` 기록.
- **인용 충실도 (Citation & Guard, 가점/감점)**:
  - `citation_required: true` 문항에서 본문 내 `Source [1]`, `[2]` 등 적절한 근거 출처 표기 여부 검증.
- **승격 판정 조건**:
  1. 16개 컨텍스트 충족 문항의 평균 정확도 점수가 기준선(e4b) 대비 동등 이상 (회귀 없음).
  2. 3개 거절 기대 문항에 대해 환각 발생 0건 (100% 정상 거절, `refusal_correct=true`).
  3. `forbidden_literal_violations` 발생 0건.
  4. `--expected-model`과 실제 서빙 모델 일치 (`model_match_expected=true`).
  5. Provenance 일관성 검증 통과 (`verify_provenance_consistency`).
  6. 소스 트리 clean 상태 (`git_dirty=false`).

---

## 4. 스키마 변경 사항 (v1 → v2)

### 4.1 Fixture 스키마 변경
```json
// v1 (제거됨)
"must_not_claim": ["Servc 등 내부 영문 코드를 사용자 답변에 노출", "낙찰업체 허위 기재"]

// v2 (추가됨)
"forbidden_literals": ["Servc", "Thng", "Cnstwk", "Frgcpt"],
"semantic_forbidden_claims": ["낙찰업체 허위 기재"]
```

- `expected_facts`의 numeric 타입은 반드시 `expected_value`, `unit`, `tolerance`를 모두 갖춰야 함.
- 복합 팩트(낙찰금액과 낙찰률 동시 언급) 검출 시 검증 실패.
- `forbidden_literals`는 알려진 내부 코드 4종을 모두 포함해야 함.

### 4.2 측정 결과 스키마 변경 (LLM_QUALITY_MEASURE_V1 → V2)
```json
{
  "schema": "LLM_QUALITY_MEASURE_V2",
  "expected_model": "gemma4:e4b",
  "model_match_expected": true,
  "base_url_validated": true,
  "provenance": {
    "git_sha": "abc123",
    "git_dirty": false,
    "source_identity_start": {"git_sha": "...", "git_dirty": false},
    "source_identity_end": {"git_sha": "...", "git_dirty": false},
    "serving_model_start": "gemma4:e4b",
    "serving_model_end": "gemma4:e4b",
    "serving_model_consistent": true,
    "base_url": "http://localhost:8000",
    "app_container": "refac_bid_box-app-1",
    "timestamp_start_utc": "...",
    "timestamp_end_utc": "..."
  },
  "results": [{
    "forbidden_literal_violations": [{"literal": "Servc", "matched_text": "servc", "position": 10, "context": "..."}],
    "semantic_forbidden_claims": ["낙찰업체 허위 기재"],
    "refusal_expected": false,
    "actual_refusal": false,
    "refusal_correct": true,
    "numeric_facts": [{"statement": "...", "expected_value": "46602100", "unit": "원", "tolerance": 1, "found": true}, ...]
  }]
}
```

---

## 5. 검증 결과 (v2)

- 검증 스크립트: `scripts/validate_llm_quality_fixture.py` (v2 스키마 대응)
- 실측 하네스: `scripts/measure_llm_quality.py` (v2 채점 로직, provenance, 모델 결박)
- 단위 테스트: `tests/test_validate_llm_quality_fixture.py`, `tests/test_measure_llm_quality.py`
- **스키마 및 KB 실재 검증 결과**: 19/19 문항 검증 통과 (16 컨텍스트 충족, 3 거절 기대, ChromaDB 17/17 실재 근거 일치 확인)
- **단위 테스트 통과**: 45개 테스트 모두 통과 (검증기 13개, 실측 하네스 32개)
- **전체 테스트 스위트 통과**: `uv run pytest tests/ -q -m 'not data_assets'` → 2022 passed, 6 skipped
- **린트 통과**: `uv run ruff check scripts/ tests/` → All checks passed
- **에이전트 규칙 검증 통과**: `python3 scripts/validate_agent_rules.py --quiet` → 12/12 통과

---

## 6. 기존 측정 결과의 무효화 안내

**중요**: `data/benchmarks/llm_quality_e4b_20260824.json` 및 `data/benchmarks/llm_quality_e2b_20260824.json`은 v1 채점 기준으로 생성된 산출물입니다. v2에서는 다음 변경으로 인해 **기존 결과는 새 채점 기준에서 무효**입니다.

1. **Numeric 팩트 분해**: 기존 `numeric_all_found`는 복합 팩트 하나로 평가되어 낙찰률 누락을 감지 못함. v2는 원자 단위로 각각 채점하므로 기존 통과 건도 실패로 재분류될 수 있음.
2. **Forbidden literal 분리**: 기존 `must_not_claim` 문자열 포함 검사는 규칙 설명문으로 인한 오탐 가능성. v2는 리터럴만 자동 검사하므로 결과가 다를 수 있음.
3. **Refusal 채점**: 기존에는 `refusal_expected`만 기록하고 채점하지 않았음. v2는 실제 채점하므로 거절 문항 점수가 달라짐.
4. **모델 결박**: 기존은 `serving_model_consistent`만 확인. v2는 `--expected-model`과 실측 모델 일치 필수.
5. **Provenance**: 기존 결과에는 Git SHA, dirty 상태, source identity, 포트 결박 정보가 없음.

**재측정 필요**: 검색 recall 결함(8/16 문항 recall < 1.0) 해소 후 v2 하네스로 재측정해야 생성 품질 비교가 성립합니다. 재측정은 별도 Task로 수행 예정입니다.

---

## 7. 산출물 및 파일 변경 내역

| 파일 | 변경 유형 | 설명 |
| --- | --- | --- |
| `data/eval/llm_quality_fixture_v1.json` | **수정** | v2 스키마 적용: numeric 팩트 원자 분해(45→61개), forbidden_literals/semantic_forbidden_claims 분리, version 2.0.0 |
| `scripts/validate_llm_quality_fixture.py` | **수정** | v2 스키마 검증: 복합 numeric 팩트 검출, forbidden_literals 4종 필수 확인, semantic_forbidden_claims 검증, numeric 필수 필드 검증 추가 |
| `scripts/measure_llm_quality.py` | **수정** | v2 채점 로직: 원자 numeric 채점, forbidden_literal 대소문자 무시 검사+근거 기록, semantic 자동 판정 제외, refusal 채점(is_refusal), --expected-model 필수+검증, base_url 포트 결박, provenance 기록(benchmark_provenance 재사용), dirty/model mismatch 시 fail-closed |
| `tests/test_validate_llm_quality_fixture.py` | **수정** | 복합 numeric 팩트 검출 테스트, forbidden_literals 누락/불일치 검출 테스트, semantic_forbidden_claims 비어있음 검출 테스트, numeric 필수 필드 검증 테스트 추가 |
| `tests/test_measure_llm_quality.py` | **신규** | 단위 테스트 신규 작성: (a) 원자 numeric 누락 감지, (b) forbidden_literal 대소문자 무시 위반 감지, (c) semantic 규칙 자동 위반 오판 방지, (d) refusal 기대/실제 불일치 감지, (e) expected-model 불일치 시 비정상 종료 |

---
