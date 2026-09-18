# 협상에 의한 계약 가격점수 산식 확정 타당성 분석 보고서

> **작성일**: 2026-09-18
> **문서 상태**: 완료 (정본)
> **태스크 ID**: `task_9c0e566c8dc4` (`task_at1_negotiation_price_score`)
> **관련 사양**: `.orca/task_at1_negotiation_price_score/capsule.yaml`
> **단일 판정**: **공고서 원문 필요**

---

## 1. 개요 및 목적

본 보고서는 `docs/context/CURRENT_STATE.md`의 active 사실인 `negotiation_contract_support`("가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했다")의 미확정부를 해소하기 위한 선행 기술 조사입니다.

본 조사는 협상에 의한 계약(`NEGOTIATION_CONTRACT`)의 가격점수 산식을 현재의 코드베이스와 데이터베이스 적재 컬럼만으로 확정할 수 있는지를 실측 검증하고, 가격점수 계산에 필요한 입력값 목록과 DB 충족 현황을 대조하여 단일 판정을 도출하는 것을 목적으로 합니다.

본 과업은 산식 계산 로직을 구현하지 않으며, 현재 구현 범위 정리, 필요 입력값 명세, DB 실측 대조, 최종 판정 및 근거 수립까지만 다룹니다.

---

## 2. 현재 구현된 협상계약 지원 범위

현재 시스템은 협상에 의한 계약 공고를 감지하여 적격심사 별표 계산을 안전하게 차단하고, 공고 메타데이터에 실린 평가비율 및 과거 낙찰률 통계를 제공하는 계층까지 구현 및 병합되어 있습니다.

### 2.1 evaluation_rules.py 내 구현 상수 및 함수

`src/app/services/evaluation_rules.py`는 도메인 순수 함수로 협상계약 식별 및 비율 파싱을 담당합니다.

| 구분 | 심볼명 | 역할 및 정의 |
| --- | --- | --- |
| 차단 코드 상수 | `BLOCK_CODE_NEGOTIATION_CONTRACT` | `"NEGOTIATION_CONTRACT"`: 협상계약 공고 감지 시 적격심사 점수 계산 차단 코드 |
| 낙찰방법 코드 대응 | `METHOD_FAMILY_BY_CODE["낙030005"]` | `"협상에의한계약"`: 조달청 낙찰방법코드 `낙030005`를 협상계약 계열로 매핑 |
| 출처 상수 | `METHOD_SOURCE_CODE` / `METHOD_SOURCE_ANNOUNCEMENT` | `"CODE"` / `"ANNOUNCEMENT"`: 낙찰방법명 출처가 원문인지 코드 매핑인지 구분 |
| 자리표시자 상수 | `METHOD_NAME_PLACEHOLDER` | `"공고서참조"`: 원문 낙찰방법명이 자리표시자일 때 코드 매핑 경로로 전환 |
| 변종 식별 상수 | `NEGOTIATION_VARIANT_STANDARD` | `"STANDARD"`: 표준 협상에 의한 낙찰자 결정 |
| 변종 식별 상수 | `NEGOTIATION_VARIANT_SW` | `"SW"`: 소프트웨어 사업 협상 |
| 변종 식별 상수 | `NEGOTIATION_VARIANT_ENGINEERING` | `"ENGINEERING"`: 일반 엔지니어링 협상 |
| 변종 식별 상수 | `NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING` | `"CONSTRUCTION_ENGINEERING"`: 건설 엔지니어링 협상 |
| 변종 매핑 튜플 | `_NEGOTIATION_VARIANTS` | 문자열 패턴(`"건설엔지니어링"`, `"엔지니어링"`, `"SW사업"`, `"협상에 의한 낙찰자 결정"`)과 변종 상수의 매핑 목록 |
| 낙찰방법명 해석 함수 | `resolve_method_name` | 원문이 `"공고서참조"`이거나 결측일 때 `sucsfbidMthdCd`(`"낙030005"`)를 기반으로 `"협상에의한계약"` 계열명을 부여 |
| 규칙 판별 함수 | `resolve_evaluation_rule` / `_resolve_by_method_name` | 공고의 `sucsfbidMthdNm`에 `"협상에의한계약"`이 포함된 경우 변종 식별 및 `techAbltEvlRt`, `bidPrceEvlRt`를 추출하여 `RuleResolutionResult(is_blocked=True, block_reason_code=BLOCK_CODE_NEGOTIATION_CONTRACT, ...)` 반환 |
| 원본 추출 함수 | `resolve_evaluation_rule_from_raw_data` | `raw_data` 딕셔너리에서 `techAbltEvlRt`, `bidPrceEvlRt`, `sucsfbidMthdCd` 등을 추출하여 `resolve_evaluation_rule` 호출 |

### 2.2 연계 계층 현황

1. **API 계층 (`src/app/api/v1/evaluations.py`)**:
   - `_analyze_bid`: 규칙 판별 결과 `rule_result.is_blocked`이고 `negotiation_variant`가 존재하면, `src/app/services/negotiation_stats.py`의 `get_negotiation_stats(db, rule_result.negotiation_variant)`를 호출하여 과거 유효 낙찰률 분포(`NegotiationRateDistribution`: 건수, 평균, 중앙값, 최솟값, 최댓값)를 응답에 포함합니다.
   - 응답 상태는 `blocked`이며, `blocked_reason`에 `"NEGOTIATION_CONTRACT: 협상에의한계약 공고입니다. 적격심사 점수 산식은 적용하지 않으며 공고의 기술능력·입찰가격 평가비율만 제공합니다."` 메시지를 전달합니다.
2. **화면 템플릿 계층 (`src/app/templates/bids/detail.html`)**:
   - `setEvaluationScopeBadge(data)`: `data.negotiation_variant != null`인 경우 배지 문구를 `'협상에의한계약 평가비율 제공'`으로 렌더링합니다.
   - `renderNegotiation(data)`: 일반 적격심사 점수 계산 영역을 숨기고, 기술능력 평가비율(`negotiation-tech-rate`), 입찰가격 평가비율(`negotiation-price-rate`), 변종(`negotiation-variant`), 낙찰률 참고 분포를 표시합니다.

---

## 3. 가격점수 산출에 필요한 입력값 목록 및 DB 적재 현황

### 3.1 협상에 의한 계약 가격점수 산식 표준 체계

공공조달에서 협상에 의한 계약의 입찰가격 평점산식은 적격심사와 근본적으로 다른 **상대평가(경쟁 입찰자 투찰가 종속)** 구조를 갖습니다.

대표적으로 기획재정부 계약예규 「협상에 의한 계약체결기준」 제7조 및 [별표] '입찰가격 평점산식'은 다음과 같습니다:

1. **입찰가격을 추정가격(또는 예정가격)의 100분의 80 이상으로 입찰한 자**:
   $$\text{평점} = \text{입찰가격평가배점한도}(B) \times \left( \frac{\text{최저입찰가격}}{\text{당해입찰가격}} \right)$$
2. **입찰가격을 추정가격(또는 예정가격)의 100분의 80 미만으로 입찰한 자**:
   $$\text{평점} = \left[ \text{입찰가격평가배점한도}(B) \times \left( \frac{\text{최저입찰가격}}{\text{기준가격} \times 0.80} \right) \right] + \left[ a \times \left( \frac{\text{기준가격} \times 0.80 - \text{당해입찰가격}}{\text{기준가격} \times 0.80 - \text{기준가격} \times 0.60} \right) \right]$$
   *(단, 최저입찰가격이 추정가격의 100분의 60 미만일 때는 100분의 60으로 간주)*

또한 발주기관 및 사업 성격에 따라 다음 변형이 존재합니다:
- **지방자치단체 (행정안전부 예규)**: 분기 기준율이 80% 외에 용역 유형별로 70%가 적용되는 경우가 다수 존재하며, 가산 계수($a$) 및 최저하한 인정선(70% 또는 60%)이 상이합니다.
- **공기업 및 준정부기관**: 자체 회계규정에 따라 독자적인 평점 산식 및 계수를 정의합니다.
- **기준가격 정의**: 비예가 공고의 경우 국가계약법은 '추정가격(부가세 제외)', 지방계약법은 '추정가격에 부가세를 포함한 금액(사업예산)'을 기준으로 삼습니다.

### 3.2 필요 입력값 및 DB/수집 대조 검증

`scripts/db_readonly_query.py`를 통해 실제 적재된 데이터베이스(`procurement`) 및 테이블(`bid_announcements`, `bid_results`)을 질의 검증한 결과입니다.

| 번호 | 필요 입력값 | 산식 내 역할 | DB 컬럼 및 raw_data 경로 | DB 질의 실측 결과 | 충족 판정 |
| --- | --- | --- | --- | --- | --- |
| 1 | **적용 평점산식 규정 및 분기선** | 기재부(80%) vs 행안부(70%/80%) vs 기관 자체산식, 가산계수 $a$ 결정 | `bid_announcements.raw_data.sucsfbidMthdAppStd` 등 | `category='Servc' AND sucsfbidMthdCd='낙030005'` 질의 시 `sucsfbidMthdAppStd` 값은 100% 공백(`""`) 또는 `None` | **결측 (부재)** |
| 2 | **입찰가격평가 배점한도 ($B$)** | 가격점수 최대 배점 (통상 10점~20점) | `bid_announcements.raw_data.bidPrceEvlRt` | 최근 표본(`id >= 10200000`) 2,038건 전량 적재 확인 (20: 894건, 10: 1055건 등 비율값) | **부분 충족** (비율만 제공, 절대만점표 부재) |
| 3 | **기술능력평가 평가비율** | 기술평가 배점 비율 (통상 80%~90%) | `bid_announcements.raw_data.techAbltEvlRt` | 최근 표본 2,038건 전량 적재 확인 (80: 894건, 90: 1055건 등) | **충족** |
| 4 | **기준가격 (예가/추정가격/예산)** | 산식의 분모 및 80% 분기점 기준액 | `bid_announcements.base_amount`, `presmpt_prce`, `raw_data.asignBdgtAmt` | 최근 협상공고 2,038건 중 비예가 1,788건(87.7%), 복수예가 130건(6.4%), 단일예가 120건(5.9%). 비예가 시 사업예산/추정가격 필드 존재 | **충족** |
| 5 | **당해 입찰자의 입찰가격** | 피평가자의 투찰 금액 | 시뮬레이션 사용자 입력 | 분석 API 호출 시 사용자가 제출하는 파라미터 | **사용자 입력** |
| 6 | **최저입찰가격 (유효 투찰 최저가)** | **가격평가 분자 파라미터 (필수)** | `bid_announcements`, `bid_results` 전 테이블 | - `bid_announcements`: 공고 시점이므로 미래 사건으로 미발생<br>- `bid_results`: 낙찰자(`bidwinnr_nm`)의 낙찰금액(`sucsf_bid_amt`)만 존재. 타 입찰자 투찰 목록 테이블 전무 | **원천 부재** |
| 7 | **A값 (국민연금 등 비입찰비용)** | 순수 입찰가격 산출용 공제액 | `bid_announcements.raw_data` A값 키 | 협상 공고에서는 원칙적으로 A값 자동 반영 산식을 적용하지 않으며, 필드 값 대부분 결측 | **공고서 확인 필요** |

### 3.3 핵심 결측 요인 분석

1. **최저입찰가격의 구조적 부재**:
   - 적격심사는 '예정가격 대비 투찰률'이라는 절대평가 산식이므로 공고 시점에도 예정가격 시나리오를 세워 점수를 확정할 수 있습니다.
   - 반면 협상계약은 `(최저입찰가격 / 당해입찰가격)` 구조입니다. 공고 시점에는 경쟁자들이 얼마를 쓸지 알 수 없으므로 실제 최저입찰가격을 확정할 수 없습니다.
   - 사후 분석(낙찰 결과) 관점에서도 `bid_results`에는 최종 계약 체결 금액인 `sucsf_bid_amt`만 있을 뿐, 개찰 당시 참여자들의 투찰 내역(순위별 입찰가격)이 전혀 적재되지 않습니다.
2. **평점산식 본문의 API 미제공**:
   - 나라장터 OpenAPI 공고 목록 및 상세 서비스는 `techAbltEvlRt`(80), `bidPrceEvlRt`(20) 같은 정량 비율만 제공할 뿐, 구체적인 계산 산식(예: 80% 미만 시 감점 폭, 소수점 처리 방식, 최저가격 인정 하한선)을 제공하는 필드가 없습니다.
   - 실측 질의 결과 `raw_data.sucsfbidMthdAppStd`(낙찰방법적용기준) 컬럼은 용역 협상공고 625,410건 전량에서 공백(`""`)으로 비어 있습니다.

---

## 4. 단일 판정 및 근거

### 4.1 단일 판정

**`공고서 원문 필요`**

### 4.2 판정 근거

1. **산식 세부 파라미터 및 적용 규정의 공고서 원문 독점성**:
   - 협상에 의한 계약에서 가격점수 평점산식의 분기점(80% vs 70%), 가산 계수, 소수점 처리 기준, 최저입찰가격 하한 보정 기준(60% 또는 70% 등)은 공고 데이터베이스나 API 응답 스키마 어디에도 구조화된 데이터로 적재되어 있지 않습니다.
   - 해당 기준은 오직 첨부서류인 **입찰공고문 본문 및 제안요청서(RFP) 첨부파일(HWP/PDF)**의 평가기준 별표에만 기재되어 있습니다.
2. **과거 공고의 낙찰방법 원문 자리표시자 한계**:
   - 2024년 이전 용역 공고의 경우 `sucsfbidMthdNm`이 100% `"공고서참조"`로 적재되어 있어, 공고 메타데이터만으로는 세부 변종조차 특정할 수 없고 코드 매핑(`낙030005`)에 의존해야 합니다. 공고서 원문 확인 없이는 적용 산식을 규명할 수 없습니다.
3. **기준가격 산출 방식의 기관별 상이성**:
   - 협상 공고의 87.7%가 "비예가" 공고입니다. 비예가 시 기준가격을 '추정가격(부가세 제외)'으로 볼 것인지, '배정예산(부가세 포함)'으로 볼 것인지는 발주기관 규정(국가계약법 vs 지방계약법 vs 공기업 자체지침)과 공고서 본문의 명시 조항에 따라 결정되므로 공고서 원문 해석이 선행되어야 합니다.
4. **'추가 수집 필요'가 아닌 이유**:
   - 조달청 나라장터 공공데이터포털 OpenAPI(입찰공고정보서비스) 스키마 자체에 협상계약 가격점수 평점산식을 내려주는 메타데이터 필드가 존재하지 않습니다.
   - 즉, 기존 수집 파이프라인에서 누락된 필드가 있는 것이 아니라, API가 산식 텍스트를 제공하지 않는 구조적 한계이므로 API 수집 대상 확대로는 해결할 수 없고 **공고문/제안요청서 첨부파일 원문 텍스트 추출**이 필수적입니다.

---

## 5. 결론 및 향후 과제

1. **현행 유지**:
   - 현행 시스템의 `NEGOTIATION_CONTRACT` 차단 및 평가비율(`techAbltEvlRt`, `bidPrceEvlRt`)·변종별 낙찰률 분포(`get_negotiation_stats`) 제공 상태는 현재 적재된 데이터로 제공 가능한 최선의 범위이며 타당합니다.
2. **후속 기능 확장을 위한 요건**:
   - 협상계약 가격점수 계산기를 도입하려면 다음 두 가지 중 하나의 아키텍처가 전제되어야 합니다:
     - **방안 A (공고문 배점표 사용자 입력 방식)**: 적격심사의 `ScoreTable`처럼, 사용자가 공고문 제안요청서의 가격산식 유형(80% 분기선, 최저가 인정 하한선 등)과 가상 경쟁 최저입찰가격을 직접 입력하도록 하는 방식.
     - **방안 B (공고서 원문 파싱 MLOps/LLM 연계)**: `stdNtceDocUrl` 및 `ntceSpecDocUrl`의 HWP/PDF 문서를 수집·파싱하여 제안서 배점표 및 가격점수 산식을 추출하는 문서 파이프라인 구축.
3. **코드 변경 여부**:
   - 본 조사는 선행 타당성 조사로, 가격점수 계산 로직을 구현하지 않았으며 `src/` 경로의 코드 변경은 0건입니다.
