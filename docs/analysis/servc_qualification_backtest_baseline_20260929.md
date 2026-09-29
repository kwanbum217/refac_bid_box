# 일반용역 적격심사 정량평가 기준 백테스트 (현행 규칙, 2026-05-26 이후)

> **작성일**: 2026-09-29
> **수정일**: 2026-09-29
> **작성자**: Orca builder (task_5f9d38232d98)
> **기준 커밋**: `ec4d196e` (`kwanbum217/orca-g3`)
> **기준 시각**: 2026-09-29 19:30 KST
> **대상**: `category='Servc'`, `raw_data.sucsfbidMthdNm LIKE '적격심사제%'`, `bid_ntce_dt >= '2026-05-26'`
> **결론**: 계산 입력값과 평점 산식을 코드 근거로 확정했다. 현행 규칙 기준으로 낙찰률이 실효 하한율 이상인 비율은 99.92%(2,659/2,661)이고, 별표 기본 하한율과 공고 하한율의 일치율은 95.34%(942/988, 일반용역 규칙)이다. 이 값이 개정 전 규칙 구현 뒤 백테스트의 비교 기준이다. 절대 최저 투찰금액 대조는 개찰 시 확정되는 예정가격이 DB에 없어 실행할 수 없으며, 점수 계층(역산 최저 통과 투찰률)은 배점표 B·k·T가 DB 원천에 없어 미실행이다.

> **표기 구분**: 이 보고서에서 **실측**은 8장 재현 명령으로 그대로 다시 계산되는 값이고, **추정**은 그렇지 않은 값이다. 다른 표기가 없으면 실측이다.

---

## 1. 요약과 판단

| 항목 | 값 | 성격 |
| --- | ---: | --- |
| 적격심사 공고 (`bid_ntce_dt >= 2026-05-26`) | 7,968행 / 6,643건 | 실측 |
| 규칙 판별 차단 | 2,284행 (28.66%) | 실측 |
| 정량평가 가능 (차단 아님 + 예정가격 기준액 > 0) | 5,682행 / 4,724건 | 실측 |
| 낙찰결과 매칭 | 2,661행 / 2,661건 | 실측 |
| 낙찰률 >= 실효 하한율 | 2,659 / 2,661 (99.92%) | 실측 |
| 별표 기본 하한율 == 공고 하한율 (일반용역 규칙) | 942 / 988 (95.34%) | 실측 |
| 낙찰률 - 하한율 프리미엄 중앙값 | +0.1170%p | 실측 |
| 2025 적격심사 하한율 보유율 | 37,134 / 37,205 (99.81%) | 실측 |
| 2025 적격심사 예정가격 보유율 | 0 / 37,205 (0%) | 실측 |

핵심 판단입니다.

- **계산은 두 계층으로 나뉘고, DB만으로 검증 가능한 것은 하한율 계층뿐입니다.** 규칙 판별과 낙찰하한율은 `evaluation_rules.py`가, 점수와 역산은 `evaluation_scoring.py`가 계산합니다. 그런데 가격배점한도 `B`, 평점계수 `k`, 통과점수 `T` 는 규칙 레지스트리에도 DB에도 없고 사용자가 공고문 배점표를 읽어 입력하는 값입니다. 따라서 현행 규칙의 "계산 결과" 중 DB만으로 재현되는 것은 하한율과 그 기반 최저 투찰률이며, 점수 기반 역산 투찰률은 배점표 확보 전에는 백테스트할 수 없습니다.
- **절대 금액 대조는 예정가격 미수집으로 불가합니다.** `bid_announcements`/`bid_results` 에는 기초금액(`raw_data.asignBdgtAmt`, `base_amount`)과 추정가격(`raw_data.presmptPrce`, `presmpt_prce`)만 있고, 개찰 시 확정되는 예정가격 컬럼이 없습니다. 반면 실제 낙찰률 `sucsf_bid_rate` 는 예정가격 기준으로 계산되어 있습니다(역산 분모가 기초금액과 중앙 +0.23% 차이, ±1% 이내 73.1%). 그래서 기준 백테스트의 주 지표는 **비율 공간의 `낙찰률 >= 하한율`** 이며, 이는 곧 "실제 낙찰자 투찰률이 예정가격 * 하한율 이상"과 동치입니다.
- **낙찰률 >= 하한율 99.92%는 법적 하한의 실효성을 보여줄 뿐, 규칙 레지스트리의 정확도를 보여주는 값이 아닙니다.** 실효 하한율은 공고의 `sucsfbidLwltRate` 가 최우선이고 이 표본에서 `rate_source` 가 전건 `ANNOUNCEMENT` 라, 별표 기본값이 쓰이지 않았습니다. 규칙 레지스트리 정확도를 가르는 지표는 **별표 기본 하한율과 공고 하한율의 일치율(95.34%)** 이고, 불일치 46건은 개정 전 규칙 구현 시 규칙표 검토 대상입니다.

---

## 2. 계산 입력값 목록과 출처

### 2.1 분석 API 진입점

`POST /api/v1/evaluations/analyze` (`src/app/api/v1/evaluations.py:769`) 가 `_analyze_bid` (`src/app/api/v1/evaluations.py:704`) 를 거쳐 규칙 판별과 점수 계산을 도메인 모듈에 위임합니다.

### 2.2 입력값과 출처

계산 함수별 입력값, 그 출처, 코드 근거입니다.

| 계산 함수 | 입력값 | 출처 | 코드 근거 |
| --- | --- | --- | --- |
| `calculate_price_score` | `bid_price` | 운영: 사용자 입력 `candidate_bid_amount` / 백테스트: 결과 `sucsf_bid_amt` | `src/app/api/v1/evaluations.py:223`, `:298` |
| | `pred_price` | `BidAnnouncement.prediction_reference_amount` | `src/app/api/v1/evaluations.py:202`, `src/app/models/bids.py:408` |
| | `base_rate` | 규칙 필드 `EvaluationRule.base_rate` (기본 `0.90`) | `src/app/services/evaluation_rules.py:35` |
| | `max_price_score` (B) | 사용자 입력 `QualificationInput.max_price_score` | `src/app/schemas/evaluations.py:94`, `src/app/api/v1/evaluations.py:176` |
| | `multiplier` (k) | 사용자 입력 `QualificationInput.multiplier` | `src/app/schemas/evaluations.py:99`, `src/app/api/v1/evaluations.py:178` |
| `calculate_min_bid_amount` | `pred_price` | 위와 같음 | `src/app/services/evaluation_scoring.py:151` |
| | `lwlt_rate` | 실효 하한율 (공고 `sucsfbidLwltRate` 우선, 결측 시 별표 기본값) | `src/app/services/evaluation_rules.py:700`, `:720` |
| | `a_value` | 용역은 항상 `None` (A값 산식은 공사 전용) | `src/app/services/evaluation_scoring.py:151`, `src/app/api/v1/evaluations.py:440` |
| `invert_lowest_bid_rate` | `pass_threshold` (T) | 사용자 입력 `QualificationInput.pass_threshold` | `src/app/schemas/evaluations.py:104`, `src/app/api/v1/evaluations.py:179` |
| | `non_price_score` (Q) | 사용자 입력 4항목 합 (실적+경영+근로조건+신인도) | `src/app/api/v1/evaluations.py:272`, `:583` |
| | 나머지 | 위와 같음 | `src/app/services/evaluation_scoring.py:198` |
| `evaluate_qualification` | `has_disqualification` | 사용자 입력 `QualificationInput.disqualification` | `src/app/schemas/evaluations.py:78` |
| | 나머지 | 위 값 + 계산된 `price_score` | `src/app/services/evaluation_scoring.py:324` |
| `generate_pred_price_scenarios` | `base_amount` | 예정가격 기준액 (위 `prediction_reference_amount`) | `src/app/api/v1/evaluations.py:246` |
| | `tot_prdprc_num` / `drwt_prdprc_num` | 공고 `raw_data.totPrdprcNum` / `drwtPrdprcNum` | `src/app/api/v1/evaluations.py:252` |
| | `range_rate` | 공고 명시값, 없으면 국가 ±2% / 지방 ±3% | `src/app/services/evaluation_scoring.py:273`, `:298` |
| `resolve_price_compensation` | `reference_pred_price` / `scenarios` | 예정가격 기준액 / 3 시나리오 | `src/app/services/evaluation_scoring.py:661`, `src/app/api/v1/evaluations.py:608` |

### 2.3 예정가격 기준액의 결정 사슬

`prediction_reference_amount` 는 다음 순서로 확정됩니다.

| 단계 | 규칙 | 코드 근거 |
| --- | --- | --- |
| 1 | `raw_data.asignBdgtAmt`, 없으면 `raw_data.bdgtAmt` | `src/app/models/bids.py:46`, `:119` |
| 2 | 1이 없고 `raw_data` 가 `None` 이면 `base_amount` 컬럼 | `src/app/models/bids.py:391` |
| 3 | 1·2가 모두 없으면 `presmpt_prce` 컬럼 | `src/app/models/bids.py:408` |

용역 표본에서 `raw_data` 는 항상 채워져 있고 `bdgtAmt` 는 0건이므로, 실질 기준액은 **`raw_data.asignBdgtAmt`**(없으면 `presmpt_prce`)입니다.

### 2.4 규칙 판별 입력값

`resolve_evaluation_rule_from_raw_data` (`src/app/services/evaluation_rules.py:741`) 가 읽는 `raw_data` 필드입니다.

| 필드 | 용도 | 근거 |
| --- | --- | --- |
| `sucsfbidMthdNm` | 별표 식별 문자열 매칭, 수기심사·협상·계열 차단 | `:741`, `:366`, `:585`, `:650` |
| `sucsfbidMthdCd` | 원문이 `공고서참조` 일 때 계열명 대체 | `:414`, `:120` |
| `prearngPrceDcsnMthdNm` | `비예가` 차단 | `:556` |
| `srvceDivNm` | `기술용역` 여부 (공고 하한율 경로) | `:650` |
| `sucsfbidLwltRate` | 실효 하한율 1순위 | `:700` |
| `techAbltEvlRt`, `bidPrceEvlRt` | 협상에의한계약 평가비율 | `:600` |
| `bidNtceDt` | 별표 시행일 대조 (`RULE_REGIME_MISMATCH`) | `:479`, `:519` |

`is_qualification_analyzable` (`src/app/services/bid_queries.py:419`) 은 "규칙 판별이 차단되지 않음 AND `prediction_reference_amount > 0`" 두 조건만 봅니다. 정량평가 가능 여부의 정본입니다.

---

## 3. 입찰가격 평점 산식과 매개변수

### 3.1 산식

| 계산 | 수식 | 코드 근거 |
| --- | --- | --- |
| 투찰률 확정 | `x = ROUND_HALF_UP(입찰금액 / 예정가격, 소수점 4자리)` | `src/app/services/evaluation_scoring.py:101` |
| 입찰가격 평점 | `P = B - k * abs(기준비율 - x) * 100` | `src/app/services/evaluation_scoring.py:117`, `:134`, `:136` |
| 최저 투찰금액 | `예정가격 * 하한율` (용역은 A값 미적용) | `src/app/services/evaluation_scoring.py:151` |
| 필요 가격점수 | `P_req = T - Q` | `src/app/services/evaluation_scoring.py:217` |
| 역산 최저 투찰률 | `기준비율 - (B - P_req) / (100 * k)` | `src/app/services/evaluation_scoring.py:239` |
| 실질 구속 하한 | `max(공고 하한율, 역산 최저 투찰률)` | `src/app/services/evaluation_scoring.py:243` |
| 종합점수 | `총점 = Q + P` | `src/app/services/evaluation_scoring.py:353` |
| 적격 판정 | `결격사유 없음 AND 입찰금액 <= 예정가격 AND 총점 >= T` | `src/app/services/evaluation_scoring.py:355` |

`base_rate` 는 `1` 초과면 백분율, 이하면 비율로 정규화됩니다 (`src/app/services/evaluation_scoring.py:134`). `x` 는 소수점 4자리 격자이며, 보완 금액 탐색도 이 격자를 씁니다 (`:500`).

### 3.2 매개변수 구분

| 구분 | 매개변수 | 값 · 출처 |
| --- | --- | --- |
| **공통 (별표 무관)** | 산식 형태, `x` 4자리 확정, A값 미적용, 적격 3조건 | 코드 상수 · 고정 |
| **규칙별 (레지스트리 선언)** | `base_rate` | 현행 14종 전부 `0.90` (`:40`) |
| | `lwlt_rate` | 별표별 상이 (예: 시설 89.995, 보험 47.995) |
| | `patterns`, `effective_date` | 별표 식별 문자열, 시행일 `2026-05-26` |
| **사용자 입력 (레지스트리 미등록)** | `B`, `k`, `T` | 공고문 배점표. DB 원천 없음 (`src/app/api/v1/evaluations.py:99`) |

### 3.3 개정 전 규칙 구현이 새로 요구하는 매개변수

현행 코드와 [`servc_pre20260526_rules_sourcing_20260929.md`](servc_pre20260526_rules_sourcing_20260929.md) 5장을 대조한 판정입니다.

| 매개변수 | 현행 | 개정 전 구현 시 | 판정 |
| --- | --- | --- | --- |
| `base_rate` | 단일 `0.90` | 시설분야 계열은 `0.91`, 그 외 `0.88` 가능성 | **별표군별 분리 필요.** 단일 필드로는 시설분야를 표현하지 못함 |
| `lwlt_rate` | 별표별 | 별표별 (동일 식별 문자열의 시행일 구간별 중복 선언) | 기존 필드 재사용. 시행일 라우팅으로 충돌 회피 |
| `effective_date` | `2026-05-26` | `2025-09-01`, `2026-03-01` 등 복수 구간 | 기존 필드 재사용. 구간 선택 로직 신규 |
| `patterns` | 14종 | 개정 전 전용 별표(수리점검·임대차·수요기관지정형 등) 추가 | 기존 필드 재사용 |
| `B`, `k`, `T` | 사용자 입력 | 동일 | **변경 없음.** 별표 원문에서 별도 확보 필요(DB 원천 없음) |

즉 개정 전 규칙 구현이 **새로 만드는 매개변수는 `base_rate` 의 별표군별 분리 하나**이고, 나머지 `B`·`k`·`T` 결측은 개정 전에도 그대로입니다. `PRE_20260526_RULES` 는 현재 빈 튜플입니다 (`src/app/services/evaluation_rules.py:293`).

---

## 4. 백테스트 정의 제안

### 4.1 비교 대상과 지표

**계층 A - 하한율 계층 (배점표 불필요, 즉시 실행 가능)**

| 지표 | 정의 | 비교 기준 |
| --- | --- | --- |
| A1 규칙 판별 커버리지 | `is_qualification_analyzable` 통과 비율, 차단 사유별 분포 | 개정 전: `RULE_NOT_FOUND`·`RULE_REGIME_MISMATCH` 가 0 에 수렴해야 함 |
| A2 하한율 일치율 | 별표 기본 `lwlt_rate` == 공고 `sucsfbidLwltRate` 비율 (일반용역 규칙 한정) | 개정 전: 동일 지표가 현행 이상이어야 함 |
| A3 하한 실효성 | 실제 낙찰률 `sucsf_bid_rate` >= 실효 하한율 비율 | 개정 전: 100% 에 가까워야 함 |
| A4 프리미엄 분포 | `낙찰률 - 하한율` 의 중앙·p10·p90·min·max | 개정 전: 중앙값이 현행(+0.117%p)과 유사해야 함 |

**계층 B - 점수 계층 (배점표 B·k·T 필요, 현재 미실행)**

| 지표 | 정의 | 전제 |
| --- | --- | --- |
| B1 역산 최저 통과 투찰률 정합 | `invert_lowest_bid_rate` 결과(실질 구속 하한) <= 실제 낙찰률 비율 | 별표별 `B`·`k`·`T` |
| B2 도달 가능성 | `P_req <= B` 로 통과 가능한 표본 비율 | 별표별 `B`·`k`·`T` |
| B3 보완 금액 타당성 | `resolve_price_compensation` 상태(`compensate`/`impossible`)별 실제 낙찰률 분포 | 별표별 `B`·`k`·`T` |

계층 B는 `B`·`k`·`T` 를 별표 원문에서 확보하기 전에는 실행하지 않습니다(반쪽 구현 금지, 설계서 4.6·6장).

### 4.2 표본 선정 규칙

| 항목 | 규칙 | 근거 |
| --- | --- | --- |
| 분류 | `category='Servc'` | `is_qualification_analyzable` |
| 낙찰방법 | `raw_data.sucsfbidMthdNm LIKE '적격심사제%'` | 설계서 2장 |
| 제도 시점 | `bid_ntce_dt >= 규칙 effective_date` | `src/app/services/evaluation_rules.py:519` |
| 계산 가능 | 규칙 판별 차단 아님 AND `prediction_reference_amount > 0` | `src/app/services/bid_queries.py:419` |
| 결과 매칭 | `(bid_ntce_no, category, normalize_ord(ord))` 키 일치 | [`result_coverage.py:90`](../../src/app/services/result_coverage.py) |
| 집계 단위 | 행(차수) 기준. 공고번호 중복 허용 | - |
| 제외 | 오프라인 개찰·취소공고 제외는 별도 보고 (본 보고서 미적용) | - |

차수 정규화는 `'000'->'000'`, `'0'->'000'`, `'1'->'001'`, `'02'->'002'` 입니다. 공고는 3자리, 결과는 2자리로 내려오므로 정규화 없이 이으면 대부분 어긋납니다 (`src/app/models/bids.py:108`).

---

## 5. 현행 규칙 기준 실측 (2026-05-26 이후)

### 5.1 모집단과 규칙 판별

| 항목 | 행 | 공고 수 | 비율(행) |
| --- | ---: | ---: | ---: |
| 적격심사 공고 전체 | 7,968 | 6,643 | 100% |
| - 일반용역 | 3,690 | 3,172 | 46.3% |
| - 기술용역 | 4,278 | 3,471 | 53.7% |

차단 사유별 분포입니다.

| 차단 코드 | 행 | 일반용역 | 기술용역 | 비율(전체 행) |
| --- | ---: | ---: | ---: | ---: |
| `MANUAL_EVALUATION` (관리규정외 수기심사) | 1,597 | 1,218 | 379 | 20.04% |
| `RULE_NOT_FOUND` (별표 매칭 실패) | 608 | 608 | 0 | 7.63% |
| `NON_PRED_PRICE` (비예가) | 79 | 11 | 68 | 0.99% |
| 합계 | 2,284 | 1,837 | 447 | 28.66% |
| 정량평가 가능 | 5,682 | 1,851 | 3,831 | 71.31% |

- `RULE_REGIME_MISMATCH` 는 0건입니다. 모집단이 별표 시행일 이후이므로 정상입니다.
- 정량평가 가능은 공고 수 기준 4,724건입니다. `prediction_reference_amount <= 0` 으로 추가 탈락한 행은 2건입니다.
- `RULE_NOT_FOUND` 608행은 전부 일반용역입니다. 개정 전 전용 별표 누락과 같은 성격의 공백이 현행 별표에도 남아 있음을 시사합니다.

### 5.2 결과 매칭

| 항목 | 행 | 공고 수 |
| --- | ---: | ---: |
| 정량평가 가능 | 5,682 | 4,724 |
| 결과 매칭 | 2,661 | 2,661 |
| 매칭률 | 46.83% | 56.33% |

- 미매칭 3,021행 중 개찰일이 지난 행 2,757, 개찰 예정(`openg_dt > 2026-10-01`) 264입니다. 개찰이 끝났는데도 결과가 붙지 않은 2,757행은 결과 수집 지연·오프라인 개찰·차수 불일치가 섞인 것으로 보이며, 본 보고서는 원인을 분해하지 않았습니다(9장).
- 매칭된 2,661행은 공고 수와 같습니다(중복 차수 없음).

### 5.3 규칙(별표)별 지표

프리미엄은 `낙찰률 - 실효 하한율`(단위 %p)입니다. "하한율 일치"는 별표 기본값과 공고 하한율이 같은 건수이며, 기술용역은 별표 기본값이 `0` 이라 해당 없음입니다.

| 규칙 ID | 표본 | 하한율 일치/불일치 | 낙찰률>=하한율 | 프리미엄 중앙 | p10 | p90 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `..._ATTACH_01` 시설분야 | 156 | 145 / 11 | 156 / 0 | +0.0200 | 0.0000 | 0.6910 | 0.0000 | 9.2950 |
| `..._ATTACH_02` 보험 | 74 | 74 / 0 | 74 / 0 | +1.8740 | 0.0440 | 45.6320 | 0.0020 | 49.2830 |
| `..._ATTACH_03` 여객 | 40 | 25 / 15 | 40 / 0 | +0.4190 | 0.0520 | 7.8750 | 0.0240 | 11.8090 |
| `..._ATTACH_04` SW(대상) | 22 | 16 / 6 | 22 / 0 | +1.0170 | 0.0120 | 8.9140 | 0.0060 | 10.8880 |
| `..._ATTACH_05` SW(비대상) | 3 | 2 / 1 | 3 / 0 | +0.1220 | 0.0480 | 2.0110 | 0.0480 | 2.0110 |
| `..._ATTACH_06` 학술연구(고시미만) | 40 | 33 / 7 | 38 / 2 | +0.3340 | 0.0120 | 8.4520 | -1.9970 | 14.7920 |
| `..._ATTACH_07` 학술연구(고시이상) | 8 | 7 / 1 | 8 / 0 | +0.2500 | 0.0070 | 2.6520 | 0.0010 | 16.6060 |
| `..._ATTACH_08` 폐기물(고시미만) | 57 | 55 / 2 | 57 / 0 | +0.1370 | 0.0140 | 0.6080 | 0.0010 | 12.0480 |
| `..._ATTACH_09` 폐기물(고시이상) | 8 | 7 / 1 | 8 / 0 | +0.2510 | 0.0820 | 0.4180 | 0.0130 | 0.8010 |
| `..._ATTACH_10` 화물(고시미만) | 11 | 10 / 1 | 11 / 0 | +0.2790 | 0.0200 | 1.2340 | 0.0080 | 3.2800 |
| `..._ATTACH_11` 화물(고시이상) | 16 | 16 / 0 | 16 / 0 | +0.2230 | 0.0290 | 2.4330 | 0.0030 | 12.6130 |
| `..._ATTACH_12` 2억 미만 | 350 | 350 / 0 | 350 / 0 | +0.0500 | 0.0090 | 0.2750 | 0.0000 | 1.4220 |
| `..._ATTACH_13` 5억미만 2억이상 | 194 | 193 / 1 | 194 / 0 | +0.0550 | 0.0090 | 0.2880 | 0.0000 | 11.2570 |
| `..._ATTACH_14` 30억미만 15억이상 | 9 | 9 / 0 | 9 / 0 | +0.0430 | 0.0010 | 0.2030 | 0.0010 | 0.5110 |
| `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` 기술용역 | 1,673 | 해당 없음 | 1,673 / 0 | +0.1790 | 0.0080 | 1.2060 | 0.0000 | 12.2920 |
| **전체** | **2,661** | **942 / 46** | **2,659 / 2** | **+0.1170** | **0.0070** | **1.1940** | **-1.9970** | **49.2830** |

재현: R1.

### 5.4 판독

- **낙찰률 >= 하한율 99.92%.** 실패 2건은 모두 `ATTACH_06` 학술연구(고시미만)이며 낙찰률 84.248%, 84.281% 로 실효 하한율 86.245% 를 밑돕니다. 하한율 미달 낙찰로는 이례적이므로 오수집 또는 재입찰 결과 혼입 가능성을 개별 확인해야 합니다.
- **프리미엄 중앙값 +0.1170%p** 는 설계서 4.7절의 복수예가 중앙 프리미엄 0.161%p 와 같은 자릿수입니다. 낙찰률이 하한율에 거의 붙어 있다는 기존 실측과 일치합니다.
- **하한율 불일치 46건**은 특정 공고일(경계일)에 몰리지 않고 2026-05-28~2026-09-16 에 분포합니다. 차이(공고값 - 별표 기본값)는 `-2.000` 20건, `+2.000` 19건, `+1.500` 3건, `-0.250` 2건, `+5.250` 1건, `+1.000` 1건으로, **±2.000%p 가 39건(84.8%)** 입니다. 재현: R1 출력에 `ann - rule_lwlt` 를 집계. 실효 하한율은 공고값을 쓰므로 지표에는 영향이 없지만, 별표 기본값의 정확도 또는 별표 오매칭 신호이므로 개정 전 구현 시 같은 검사를 붙여야 합니다.
- **`rate_source` 는 전건 `ANNOUNCEMENT`** 입니다. 별표 기본값 fallback 경로(`RULE_DEFAULT`)는 이 표본에서 한 번도 쓰이지 않아, 현행 데이터만으로는 별표 기본 하한율의 타당성을 지표로 검증할 수 없습니다.

### 5.5 예정가격 미수집의 영향 (추정 금지 근거)

기초금액을 예정가격 대용으로 쓰면 결과가 왜곡됩니다. 참고로 `기초금액 * 하한율 <= 낙찰금액` 을 계산하면 2,655건 중 1,377건(51.9%)만 성립합니다. 이는 규칙 오류가 아니라 **분모가 예정가격이 아니라 기초금액이기 때문**입니다. 실제 낙찰률의 역산 분모는 기초금액과 중앙 +0.23%(절대값 1% 이내 73.1%) 차이가 나는 예정가격입니다. 따라서 계층 A의 지표는 비율 공간으로만 정의하며, 절대 금액 대조는 예정가격이 수집되기 전까지 보류합니다. 재현: R4.

---

## 6. 2025년 필드 보유율과 개정 전 백테스트 가능 범위

모집단: `category='Servc'`, `bid_ntce_dt` 2025-01-01~2025-12-31, `raw_data.sucsfbidMthdNm LIKE '적격심사제%'`.

| 필드 | 2025 (행/비율) | 2026-01-01~05-25 (행/비율) | 원천 |
| --- | ---: | ---: | --- |
| 적격심사 공고 전체 | 37,205 / 30,814건 | 17,151 / 14,405건 | - |
| 하한율 (`sucsfbidLwltRate`, >0) | 37,134 (99.81%) | 17,151 (100%) | `raw_data` |
| 하한율 <= 0 | 71 (0.19%) | 0 | 수기심사 계열 |
| 기초금액 (`asignBdgtAmt` 존재) | 37,205 (100%) | 17,151 (100%) | `raw_data` |
| 기초금액 (`base_amount` 컬럼 > 0) | 37,200 (99.99%) | 17,150 (99.99%) | 컬럼 |
| 추정가격 (`presmptPrce` 존재) | 37,205 (100%) | 17,151 (100%) | `raw_data` |
| 추정가격 (`presmpt_prce` 컬럼 > 0) | 37,197 (99.98%) | 17,146 (99.97%) | 컬럼 |
| **예정가격** | **0 (0%)** | **0 (0%)** | 수집 안 됨 |

결과 매칭 범위입니다.

| 구간 | 적격심사 행 | 결과 매칭 행 | 매칭률 |
| --- | ---: | ---: | ---: |
| 2025 전체 | 37,205 | 21,165 | 56.89% |
| 2025 비수기심사 | 27,379 | 15,224 | 55.60% |

재현: R2, R3.

판단입니다.

- **개정 전 백테스트도 현행과 같은 제약을 받습니다.** 하한율(99.81%)·기초금액(100%)·추정가격(100%)은 충분히 보유되지만 **예정가격이 0%** 이므로, 절대 최저 투찰금액 대조는 개정 전에도 불가합니다. 비율 공간의 A2·A3 지표는 2025년에도 그대로 적용할 수 있습니다.
- **매칭 표본이 15,224행(비수기심사)** 으로 현행(2,661행)보다 5.7배 큽니다. 개정 전 규칙의 A2·A3 지표는 현행보다 훨씬 좁은 신뢰구간으로 측정됩니다.
- 하한율 보유율 100% 덕분에 개정 전 별표 기본 하한율을 행별 공고값과 전량 대조할 수 있습니다. 이것이 개정 전 백테스트의 가장 강한 축입니다.

---

## 7. 개정 전 규칙 구현 Task 테스트 설계 권고

### 7.1 단위 테스트

| 대상 | 케이스 | 기대 |
| --- | --- | --- |
| `resolve_evaluation_rule` | 공고일 2026-05-25 / 2026-05-26 경계 | PRE / POST 별표 선택 |
| `resolve_evaluation_rule` | PRE 공고가 `RULE_REGIME_MISMATCH` 없이 통과 | 차단 0 |
| `resolve_evaluation_rule` | `base_rate` 가 시설분야 계열에서 `0.91`, 그 외 `0.88` | 별표군별 값 |
| `match_rule_by_mthd_nm` | 개정 전 전용 이름(수리점검·임대차·수요기관지정형 등) | PRE 규칙 매칭 |
| 하한율 우선순위 | 공고값 존재/결측/불일치 3분기 | 공고값 우선, 결측만 기본값 |
| `calculate_price_score` | `x == 기준비율`, `x == 하한율` | `P == B`, 경계 점수 |
| `invert_lowest_bid_rate` | `P_req > B` | `can_pass=False` |
| `calculate_min_bid_amount` | A값 전달 시 | 용역 경로에서 A값 무시(항상 `예정가격 * 하한율`) |

픽스처는 공고번호·차수를 고정한 골든 샘플(예: 2025년 `ATTACH_12` 계열 1건, 기술용역 1건)로 두어 재현성을 보장합니다.

### 7.2 백테스트 테스트

| 항목 | 내용 |
| --- | --- |
| 대상 구간 | 2025 전체(비수기심사 27,379행), 2026-01-01~05-25(12,931행 추정) |
| 지표 | 4.1의 A1~A4 |
| 비교 기준 | 이 보고서의 현행 값: A2 95.34%, A3 99.92%, A4 중앙 +0.117%p |
| 합격 조건(제안) | A1 의 `RULE_NOT_FOUND`·`RULE_REGIME_MISMATCH` 가 1% 미만, A2 가 현행 이상, A3 가 99.9% 이상 |
| 매칭 | 4.2 표본 규칙 그대로. `normalize_ord` 필수 |
| 계층 B | 배점표 B·k·T 확보 전 실행 금지. 확보 시 B1~B3 추가 |

### 7.3 회귀 방지

현행 지표(A2·A3·A4)를 테스트 상수로 고정해 개정 전 규칙 추가가 현행 계산을 바꾸지 않았음을 확인합니다. `PRE_20260526_RULES` 를 채운 뒤에도 POST 공고 표본의 지표가 동일해야 합니다.

---

## 8. 재현 명령

모든 DB 조회는 읽기 전용입니다. 계산 스크립트는 현재 작업 디렉터리(워크트리)에서 `uv run python -` 히어독으로 실행하며, 세션은 쓰기를 하지 않습니다. 조회일 2026-09-29.

### R0. 규칙 검사

```sh
python3 scripts/validate_agent_rules.py --quiet
```

### R1. 모집단·차단·매칭·규칙별 지표 (5장)

```sh
uv run python - <<'PY'
import json
from collections import Counter, defaultdict
from decimal import Decimal
from sqlalchemy import text
from src.app.core.db import SessionLocal
from src.app.services.evaluation_rules import resolve_evaluation_rule_from_raw_data
from src.app.models.bids import extract_business_budget

def norm_ord(v):
    t = str(v or "").strip()
    return (t.lstrip("0") or "0").zfill(3)

def dec(v):
    try:
        return Decimal(str(v).strip())
    except Exception:
        return None

db = SessionLocal()
rows = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord, presmpt_prce,
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdCd')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidLwltRate')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.prearngPrceDcsnMthdNm')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.srvceDivNm')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.bidNtceDt')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.techAbltEvlRt')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.bidPrceEvlRt')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.asignBdgtAmt')),
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.bdgtAmt'))
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2026-05-26'
 AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) LIKE '적격심사제%'
""")).fetchall()

block = Counter(); recs = []
for (no, o, presmpt, mthd, mcd, lwlt, pre, sdiv, rn, tech, prc, asig, bdg) in rows:
    raw = {"prearngPrceDcsnMthdNm": pre, "sucsfbidMthdNm": mthd, "sucsfbidLwltRate": lwlt,
           "techAbltEvlRt": tech, "bidPrceEvlRt": prc, "srvceDivNm": sdiv,
           "sucsfbidMthdCd": mcd, "bidNtceDt": rn, "asignBdgtAmt": asig, "bdgtAmt": bdg}
    res = resolve_evaluation_rule_from_raw_data(category="Servc", raw_data=raw)
    if res.is_blocked:
        block[res.block_reason_code] += 1
        continue
    pred = extract_business_budget(raw)
    if pred is None:
        pred = presmpt
    if not pred or pred <= 0:
        continue
    recs.append(dict(no=no, ord=norm_ord(o), lwlt=Decimal(str(res.effective_lwlt_rate)),
                     rule_lwlt=Decimal(str(res.rule.lwlt_rate)), rid=res.rule.rule_id,
                     ann=dec(lwlt)))

rres = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord, sucsf_bid_amt, sucsf_bid_rate
FROM bid_results WHERE category='Servc' AND rl_openg_dt >= '2026-05-20'
""")).fetchall()
R = {(no, norm_ord(o)): (amt, dec(rate)) for no, o, amt, rate in rres}
matched = [r for r in recs if (r["no"], r["ord"]) in R]

print("적격심사 rows/notices:", len(rows), len({r[0] for r in rows}))
print("차단:", dict(block))
print("정량평가 가능 rows/notices:", len(recs), len({r["no"] for r in recs}))
print("결과 매칭 rows/notices:", len(matched), len({r["no"] for r in matched}))

G = defaultdict(lambda: dict(n=0, eq=0, ne=0, ok=0, fail=0, prem=[]))
for r in matched:
    amt, rt = R[(r["no"], r["ord"])]
    for k in (r["rid"], "__ALL__"):
        g = G[k]; g["n"] += 1
        if r["rule_lwlt"] > 0 and r["ann"] is not None:
            if r["ann"] == r["rule_lwlt"]: g["eq"] += 1
            else: g["ne"] += 1
        if rt is not None:
            if rt >= r["lwlt"]: g["ok"] += 1
            else: g["fail"] += 1
            g["prem"].append(rt - r["lwlt"])

def q(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]

for k in ["__ALL__"] + sorted(x for x in G if x != "__ALL__"):
    g = G[k]
    print(k, g["n"], "eq", g["eq"], "ne", g["ne"], "ok", g["ok"], "fail", g["fail"],
          "med", q(g["prem"], 0.5) if g["prem"] else None,
          "p10", q(g["prem"], 0.1) if g["prem"] else None,
          "p90", q(g["prem"], 0.9) if g["prem"] else None,
          "min", min(g["prem"]) if g["prem"] else None,
          "max", max(g["prem"]) if g["prem"] else None)
db.close()
PY
```

### R2. 2025·2026-01~05 필드 보유율 (6장)

```sh
uv run python scripts/db_readonly_query.py --sql "
SELECT COUNT(*) total, COUNT(DISTINCT bid_ntce_no) notices,
 SUM(CASE WHEN lw <> '' AND lw REGEXP '^[0-9.]+$' AND CAST(lw AS DECIMAL(10,3))>0 THEN 1 ELSE 0 END) lwlt_pos,
 SUM(CASE WHEN asig <> '' THEN 1 ELSE 0 END) has_asign,
 SUM(CASE WHEN bdgt <> '' THEN 1 ELSE 0 END) has_bdgt,
 SUM(CASE WHEN base_amount > 0 THEN 1 ELSE 0 END) has_base_col,
 SUM(CASE WHEN presmpt <> '' THEN 1 ELSE 0 END) has_presmpt_raw,
 SUM(CASE WHEN presmpt_prce > 0 THEN 1 ELSE 0 END) has_presmpt_col
FROM (
 SELECT bid_ntce_no, base_amount, presmpt_prce,
  JSON_UNQUOTE(JSON_EXTRACT(raw_data,'\$.sucsfbidLwltRate')) lw,
  JSON_UNQUOTE(JSON_EXTRACT(raw_data,'\$.asignBdgtAmt')) asig,
  JSON_UNQUOTE(JSON_EXTRACT(raw_data,'\$.bdgtAmt')) bdgt,
  JSON_UNQUOTE(JSON_EXTRACT(raw_data,'\$.presmptPrce')) presmpt
 FROM bid_announcements
 WHERE category='Servc' AND bid_ntce_dt>='2025-01-01' AND bid_ntce_dt<'2026-01-01'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'\$.sucsfbidMthdNm')) LIKE '적격심사제%'
) t"
```

`2026-01-01`~`2026-05-25` 는 같은 질의의 날짜 조건만 바꿉니다.

### R3. 2025 결과 매칭 범위 (6장)

```sh
uv run python - <<'PY'
from sqlalchemy import text
from src.app.core.db import SessionLocal
def norm_ord(v):
    t = str(v or "").strip()
    return (t.lstrip("0") or "0").zfill(3)
db = SessionLocal()
ann = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord,
 JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm'))
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt>='2025-01-01' AND bid_ntce_dt<'2026-01-01'
 AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) LIKE '적격심사제%'""")).fetchall()
A = {(n, norm_ord(o)) for n, o, m in ann}
An = {(n, norm_ord(o)) for n, o, m in ann if m and '수기심사' not in m}
res = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord FROM bid_results
WHERE category='Servc' AND rl_openg_dt>='2024-12-01' AND rl_openg_dt<'2026-03-01'""")).fetchall()
RK = {(n, norm_ord(o)) for n, o in res}
print("2025 all", len(A), "matched", len(A & RK))
print("2025 nonmanual", len(An), "matched", len(An & RK))
db.close()
PY
```

### R4. 예정가격 미수집과 낙찰률 분모 (5.5절)

낙찰률의 역산 분모(`낙찰금액 / (낙찰률 / 100)`)를 기초금액(`asignBdgtAmt`)과 대조합니다. 중앙 -0.23%, 절대 1% 이내 73.1% 로 나오면 분모가 기초금액이 아니라 예정가격임을 뜻합니다.

```sh
uv run python - <<'PY'
from decimal import Decimal
from sqlalchemy import text
from src.app.core.db import SessionLocal
def norm_ord(v):
    t = str(v or "").strip()
    return (t.lstrip("0") or "0").zfill(3)
db = SessionLocal()
ann = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord, JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.asignBdgtAmt'))
FROM bid_announcements WHERE category='Servc' AND bid_ntce_dt >= '2026-05-26'
 AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) LIKE '적격심사제%'
""")).fetchall()
A = {(n, norm_ord(o)): a for n, o, a in ann}
res = db.execute(text("""
SELECT bid_ntce_no, bid_ntce_ord, sucsf_bid_amt, sucsf_bid_rate FROM bid_results
WHERE category='Servc' AND rl_openg_dt >= '2026-05-20'
 AND sucsf_bid_rate > 0 AND sucsf_bid_amt > 0
""")).fetchall()
d = []
for n, o, amt, rate in res:
    a = A.get((n, norm_ord(o)))
    if not a:
        continue
    implied = Decimal(str(amt)) / (Decimal(str(rate)) / Decimal("100"))
    base = Decimal(str(a))
    if base > 0:
        d.append((implied - base) / base * 100)
d.sort()
n = len(d)
print("pairs", n, "median%", d[n // 2], "within1%",
      sum(1 for x in d if abs(x) <= 1) / n)
db.close()
PY
```

5.5절의 `기초금액 * 하한율 <= 낙찰금액` 성립률(2,655건 중 1,377건)은 R1 의 각 행에 `calculate_min_bid_amount(pred, lwlt)` 를 적용해 같은 방식으로 재현합니다.

---

## 9. 미확인 사항과 한계

- **예정가격이 DB에 없습니다.** `bid_announcements`·`bid_results` 어느 쪽에도 개찰 확정 예정가격 컬럼이 없습니다. 5.5절은 기초금액을 분모로 쓸 때 생기는 왜곡을 보인 것이며, 예정가격 확보 경로는 이번 조사 범위 밖입니다.
- **점수 계층(계층 B)을 실행하지 못했습니다.** `B`·`k`·`T` 는 규칙 레지스트리·DB 어디에도 없어, 역산 최저 통과 투찰률과 보완 금액 타당성은 배점표 확보 전까지 검증 대상이 아닙니다.
- **하한율 불일치 46건의 원인을 분해하지 않았습니다.** 공고값 override 인지 별표 오매칭인지 미확정입니다. 개별 확인이 필요합니다.
- **미매칭 2,757행(개찰 경과)의 원인을 분해하지 않았습니다.** 결과 수집 지연·오프라인 개찰·차수 불일치가 섞여 있을 것으로 보나 건수 분해는 하지 않았습니다.
- **표본이 소표본인 별표가 있습니다.** `ATTACH_05` 3건, `ATTACH_09` 8건, `ATTACH_07` 8건, `ATTACH_14` 9건은 지표 해석에 주의해야 합니다. 표본이 작은 값은 그대로 적었습니다.
- **코디네이터 확인값(정량평가 가능 4,722건)과 2건 차이**가 있습니다. 재현 질의로 계산한 4,724건을 정본으로 삼았으며, 조회 시점 수집 차이로 보입니다.
- **오프라인 개찰·취소공고 제외를 적용하지 않았습니다.** `RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS`·`EXCLUDE_LATER_CANCELLED` 규칙은 기본값이 꺼짐이라 본 백테스트에도 적용하지 않았습니다.
- 코드·설정·DB를 바꾸지 않았습니다. 이 보고서만 추가했습니다.
