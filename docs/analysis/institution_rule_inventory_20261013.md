# 기관별 적격심사 산식 인벤토리와 공고기관·수요기관 판정 설계

> **작성일**: 2026-10-13
> **작업**: Orca Task `task_00564acc363a` (builder, R1 단계). 코드는 바꾸지 않으며 R2 가 이 명세로 구현한다.
> **정본 사양**: `.orca/capsules/task_00564acc363a/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **기준 커밋**: `main` `96cf5e6e`, 작업 브랜치 `kwanbum217/r1-institution-rule-inventory`
> **산출물**: 본 문서와 [institution_rules_20261013.yaml](../../data/reference/institution_rules_20261013.yaml)
> **범위**: `institution_scope=INSTITUTION`(중앙부처·공기업·공단·준정부기관). 시·도 및 행정안전부 예규(`institution_scope=REGION`, `LOCAL_RULES`)는 이미 코드에 등록되어 있어 제외한다.
> **판정 규칙**: 수집 세션 3절의 10개 규칙을 그대로 따른다. 계수 생략 시 평탄 대입이 인쇄 점수와 맞을 때만 k=1, 대입값이 인쇄 점수와 0.01점이라도 다르면 미확정이다.

---

## 1. 목적과 결론

- 목적: `src/app/services/evaluation_rules.py` 의 기관 규칙(`institution_scope=RULE_SCOPE_INSTITUTION`)이 현재 0개인 공백을 채우기 위한 1단계로, 수집·확인된 기관 산식을 기계 판독 가능한 명세 [institution_rules_20261013.yaml](../../data/reference/institution_rules_20261013.yaml) 로 확정한다.
- 결론: 기관 18곳, 구간(band) 189개를 명세화했다. 상태는 확인 10곳, 부분 5곳, 미확인 3곳이며 기관 규칙에 넣을 수 있는 값(확인·부분)은 전부 B·k·기준비율·통과점수·역산 하한율과 문서:행 근거를 가진다.
- R2 는 확인 구간을 그대로 옮기고, 부분 기관의 미확정 행은 `k=None` 과 사유를 남기며, 미확인 3곳은 규칙을 만들지 않는다.

---

## 2. 역산 하한율 정의

명세의 `lwlt_rate` 는 공고의 정책 낙찰하한율이 아니라, "가격점수 + 비가격 만점 = 통과점수" 가 되는 최저 투찰률을 식으로 역산한 값이다.

| 항목 | 정의 |
| --- | --- |
| 총점 구조 | 가격 배점한도 B + 비가격 만점 (100 − B) = 100 |
| 경계 조건 | `B − k × (base_ratio − rate) = pass_score − (100 − B)` → `rate = base_ratio − (100 − pass_score) / k` |
| 표기 관행 | 계산값을 소수 둘째 자리까지 버린 뒤 0.005 를 뺀다. 예: `88 − (100 − 85) / 0.375 = 48.000` → `47.995` |
| 검증 | `base 88, k 2, T 95` → `85.500` → `85.495` (부산·경기 문서의 인쇄 하한율 85.495% 와 일치), `base 90, k 1, T 90` → `80.000` → `79.995` (부산 10억~30억 단순노무 외 77.995% 와 부합하는 경계역) |
| 적용 불가 | `k` 가 미확정이거나(규칙 5·7) 원문에 상한 규정이 없는 구간은 `lwlt_rate: null` 이다. |

`rate` 는 `base_ratio` 위쪽(평탄)에서도 정의되지만, 하한율은 항상 `base_ratio` 아래에서 성립한다.

---

## 3. 기관별 요약 표

`구간 수` 는 명세 YAML 의 band 개수, `역산 하한율` 은 그 기관 bands 의 `lwlt_rate` 최소~최대(값이 있는 행만)다. `근거` 는 대표 정본 분석 문서다.

| 기관 | 상태 | 구간 수 | 역산 하한율(%) | 근거 |
| --- | :---: | ---: | --- | --- |
| 국토교통부 | 확인 | 5 | 80.495~87.745 | [servc_formula_collection_central_20261004.md](servc_formula_collection_central_20261004.md:66) |
| 국가유산청 | 확인 | 5 | 79.995~87.745 | [servc_formula_collection_central_20261004.md](servc_formula_collection_central_20261004.md:115) |
| 환경부(기후에너지환경부) | 확인 | 4 | 80.495~87.745 | [servc_formula_collection_central_20261004.md](servc_formula_collection_central_20261004.md:160) |
| 방위사업청 | 부분 | 5 | 85.495~87.745 | [servc_formula_collection_central_20261004.md](servc_formula_collection_central_20261004.md:199) |
| 한국토지주택공사(LH) | 미확인 | 0 | - | [servc_formula_recover_a_20261005.md](servc_formula_recover_a_20261005.md:6) |
| 한국철도공사(승강기 한정) | 부분 | 4 | 81.995~89.745 | [servc_formula_recover_b_20261005.md](servc_formula_recover_b_20261005.md:5) |
| 한국농어촌공사 | 확인 | 20 | 47.995~89.995 | [servc_formula_userfiles_agency_20261004.md](servc_formula_userfiles_agency_20261004.md:4) |
| 한국도로공사 | 부분 | 10 | 79.995~87.745 | [20260930_servc_formula_recalc_kwater_koex.md](20260930_servc_formula_recalc_kwater_koex.md:4) |
| 한국가스공사 | 확인 | 5 | 79.995~89.995 | [servc_formula_kogas_qualification_20261004.md](servc_formula_kogas_qualification_20261004.md:4) |
| 한국전력기술 | 부분 | 16 | 80.495~87.995 | [servc_formula_collection_energy_20261004.md](servc_formula_collection_energy_20261004.md:3) |
| 한국수자원공사 | 부분 | 11 | 79.995~87.995 | [servc_formula_userfiles_existing_20261004.md](servc_formula_userfiles_existing_20261004.md:8) |
| 한국수력원자력 | 확인 | 26 | 82.495~89.995 | [servc_formula_userfiles_agency_20261004.md](servc_formula_userfiles_agency_20261004.md:6) |
| 한국지역난방공사 | 확인 | 22 | 47.995~87.995 | [servc_formula_userfiles_agency_20261004.md](servc_formula_userfiles_agency_20261004.md:5) |
| 한국석유공사 | 확인 | 16 | 80.495~87.995 | [servc_formula_recover_a_20261005.md](servc_formula_recover_a_20261005.md:5) |
| 한전 전력연구원 | 미확인 | 0 | - | [servc_formula_recover_b_20261005.md](servc_formula_recover_b_20261005.md:6) |
| 한전KPS | 미확인 | 0 | - | [servc_formula_recover_a_20261005.md](servc_formula_recover_a_20261005.md:7) |
| 인천국제공항공사 | 확인 | 18 | 47.995~87.995 | [servc_formula_recover_a_20261005.md](servc_formula_recover_a_20261005.md:4) |
| 인천공항시설관리(주) | 확인 | 22 | 47.995~87.995 | [servc_formula_userfiles_agency_20261004.md](servc_formula_userfiles_agency_20261004.md:9) |

- 상태별: 확인 10, 부분 5, 미확인 3.
- 보험용역(별표 6)의 0.375 계수 구간이 47.995 로 가장 낮고, 시설분야 B−15 구조 구간이 87.995~89.995 로 가장 높다.
- 한국수자원공사·한국도로공사·방위사업청의 미확정 행은 `k=None` 이며 사유를 명세 `note` 와 band `status` 에 남겼다.

---

## 4. 명세 YAML 스키마

[institution_rules_20261013.yaml](../../data/reference/institution_rules_20261013.yaml) 의 구조다.

| 키 | 뜻 |
| --- | --- |
| `schema` | `INSTITUTION_RULE_INVENTORY_V1` |
| `conventions` | 점수식·하한율식·구간 경계 규약·고시금액 토큰·통화 단위 |
| `region_rules_out_of_scope` | 이 명세에서 제외한 REGION(시·도·행안부) 기관 목록과 그 근거 문서 |
| `institutions[].institution_name` | 정식 명칭 |
| `institutions[].name_aliases` | 공고에 나오는 표기 변형 |
| `institutions[].institution_code` | 나라장터 기관 코드. 문서에서 확인한 경우만 값, 없으면 `null` |
| `institutions[].status` | `confirmed` / `partial` / `unresolved` |
| `institutions[].scope` | `INSTITUTION` (REGION 기관은 제외 목록에만 둔다) |
| `institutions[].standard` | 기준 문서명·번호·시행일 |
| `institutions[].service_types` | 일반·기술·단순노무 등 적용 범위 |
| `institutions[].non_qual_methods` | 종심제처럼 적격 B−k 가 아닌 낙찰 방식과 적용 조건 |
| `institutions[].bands[]` | 추정가격 구간별 B·k·기준비율·통과점수·역산 하한율·근거 |

band 필드:

| 필드 | 뜻 |
| --- | --- |
| `band` | 별표·구간 라벨 |
| `service_type` | 이 구간의 용역 유형 |
| `lower` / `upper` | 추정가격 경계(원). `lower` 이상, `upper` 미만. `null` 은 개방. 문자열 `고시금액` 은 연도별 고시금액 토큰 |
| `B` | 입찰가격 배점한도. 배열이면 추정가격이 아니라 용역 유형(계량화 정도)으로 갈리는 경우(한국가스공사) |
| `k` | 평점계수. `null` 이면 원문에 근거가 없어 미확정 |
| `base_ratio` | 기준비율(%). 한국수자원공사 별표 6 과 환경부·한전기술 일부는 91·92·93 |
| `pass_score` | 종합평점 통과점수 |
| `lwlt_rate` | 역산 하한율(%). `k` 미확정 구간은 `null` |
| `price_cap_rate` / `flat_score` | 원문 평탄 상한 비율과 그때의 인쇄 점수(원문 미인쇄면 `null`) |
| `status` | 이 band 의 확정도 |
| `source` | 문서:행 근거 |

---

## 5. 공고기관·수요기관 판정 설계

### 5.1 raw_data 필드

`raw_data`(나라장터 OpenAPI 응답 JSON)에는 공고기관과 수요기관이 따로 들어 있다. 현행 `resolve_evaluation_rule_from_raw_data` 는 수요기관(`dminsttNm`·`dminsttCd`)만 읽는다(`src/app/services/evaluation_rules.py:3921`).

| 구분 | raw_data 키 | DB 컬럼 | 뜻 |
| --- | --- | --- | --- |
| 공고기관 | `ntceInsttNm` / `ntceInsttCd` | `ntce_instt_nm` | 공고를 올린 기관(대행이면 조달청) |
| 수요기관 | `dminsttNm` / `dminsttCd` | `dminstt_nm` | 실제 용역을 발주·사용하는 기관 |

DB 컬럼 존재 확인은 아래 질의로 했다(읽기 전용, 단일 SELECT). 읽기 전용 스크립트 사용은 Capsule 이 허용한 경로다.

```
uv run python scripts/db_readonly_query.py --sql "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='procurement' AND TABLE_NAME='bid_announcements' AND COLUMN_NAME LIKE '%ntce%'"
uv run python scripts/db_readonly_query.py --sql "SELECT bid_ntce_no, ntce_instt_nm, dminstt_nm FROM procurement.bid_announcements WHERE bid_ntce_no IN ('R25BK01097015','R26BK01716376','R25BK01060561','R26BK01398051','R25BK01157938') LIMIT 10"
```

### 5.2 대행 여부 실측 (2026-10-13)

| 공고번호 | 공고기관(ntce_instt_nm) | 수요기관(dminstt_nm) | 실제 적용 기준 | 판정 |
| --- | --- | --- | --- | --- |
| R25BK01060561 | 인천국제공항공사 | 인천국제공항공사 | 자체 일반용역 적격심사 세부기준 | 자체 집행 |
| R26BK01716376 | 한국석유공사 | 한국석유공사 | 자체 용역 적격심사 세부기준 | 자체 집행 |
| R25BK01157938 | 대구광역시 | 대구광역시 | 자체 일반용역 적격심사 세부기준 별표 | 자체 집행 |
| R25BK01097015 | 조달청 서울지방조달청 | 한국토지주택공사 경기남부지역본부 | 조달청 일반용역 적격심사 세부기준 | 조달청 대행 |
| R26BK01398051 | 조달청 서울지방조달청 | 방위사업청 | 환경부 건설폐기물 기준(개별 기준) | 조달청 대행 |

- 자체 기준을 인용한 공고는 모두 공고기관 = 수요기관 = 그 기관이었다.
- 조달청이 공고기관인 대행 공고는 조달청 또는 별도 발주기준을 인용했고, 수요기관 자체 기준을 인용한 사례는 확인되지 않았다.

### 5.3 판정 규칙 (제안)

1. **기관 규칙의 축은 수요기관(`dminsttNm`·`dminsttCd`)으로 한다.**
   - 근거: 각 기관 세부기준 제1조가 적용 대상을 "그 기관이 집행하는 용역" 으로 규정한다(예: 한국석유공사 제1조, 인천국제공항공사 제1조). 현행 코드의 `institution_code`/`institution_name` 축도 수요기관(`dminsttCd`/`dminsttNm`)이다.
2. **공고기관이 조달청·지방조달청 계열이면 수요기관 자체 규칙을 배제하고 조달청(또는 해당 발주) 기준을 적용한다.**
   - 근거: 위 5.2 실측에서 대행 공고 2건 모두 조달청·환경부 기준을 인용했다.
   - 단, 이 배제를 기관 규정으로 확정하는 조문은 찾지 못했다. 따라서 **R2 잠정 기본안**으로 두고, 확정 전에는 플래그로 켜고 끌 수 있게 한다.
3. **판단 근거 부재 항목**: "공고기관이 조달청 대행일 때 수요기관 자체 규칙을 항상 배제한다" 는 규정 조문은 확인되지 않았다. 이 항목은 **사용자 결정 필요**다. 잠정 기본안(규칙 2)을 채택하되, 사용자가 "수요기관 우선" 을 택하면 플래그만 끄면 되도록 설계한다.

### 5.4 R2 코드 변경 지점

- `resolve_evaluation_rule_from_raw_data` 에서 `ntceInsttCd`·`ntceInsttNm` 를 읽어 `resolve_evaluation_rule` 로 넘긴다.
- `resolve_evaluation_rule` 에 `announcement_institution_code/name`(공고기관) 인자를 추가하고, 조달청 대행 판정 플래그를 둔다.
- 기관 규칙 매칭은 기존 `_axis_matches`(`evaluation_rules.py:3282`)의 `RULE_SCOPE_INSTITUTION` 분기를 재사용한다.

---

## 6. 기관 규칙과 LOCAL·조달청 규칙의 우선순위

현행 `resolve_evaluation_rule` 의 선택 순서는 `INSTITUTION > REGION > ALL` 이고, `contract_regime == "LOCAL"` 이면 조달청 규칙을 배제하고 `LOCAL_RULES`(REGION)만 본다(`evaluation_rules.py:3496-3531`, `:3569`). 이 순서를 유지하되 기관 규칙을 명시적으로 1순위에 둔다.

| 순위 | 규칙 | 적용 조건 |
| ---: | --- | --- |
| 1 | 기관(INSTITUTION) | 수요기관이 규칙을 가진 기관이고, 조달청 대행이 아님(5.3) |
| 2 | 시·도(REGION, `LOCAL_RULES`) | `contract_regime == "LOCAL"` 이고 수요기관 시·도 규칙이 있음 |
| 3 | 조달청(ALL) | 위 어느 것도 없고 낙찰방법명이 조달청 별표와 매칭됨 |

- 충돌 규칙: `contract_regime == "LOCAL"`(계약방법에 "지방" 표기)이면 시·도 규칙을 우선하고 기관 규칙은 배제한다. 공기업·공단 용역은 지방계약 대상이 아니다.
- 충돌 규칙: 같은 `RULE_SCOPE_INSTITUTION` 단계에 둘 이상이 매칭되면 현행대로 `RULE_SCOPE_AMBIGUOUS` 로 차단한다(`evaluation_rules.py:3571`).
- 별표·시행일 대조(`RULE_NOT_FOUND`·`RULE_REGIME_MISMATCH`)는 기관 규칙에도 동일하게 적용한다.

---

## 7. R2 구현 계획

### 7.1 규칙 ID 명명

기존 명명(`SERVC_LOCAL_<SIDO>_<YYYYMMDD>_<VARIANT>`, `SERVC_QUAL_POST` 등)을 따라 기관 규칙은 다음 형식으로 둔다.

```
SERVC_INST_<INST_KEY>_<YYYYMMDD>_<SERVICE_KEY>
```

| 기관 | 제안 rule_id 접두 |
| --- | --- |
| 국토교통부 | `SERVC_INST_MOLIT_20180104_GENERAL`, `..._SUPERVISION` |
| 국가유산청 | `SERVC_INST_KHS_20240517_BURIAL` |
| 환경부 | `SERVC_INST_ME_20251111_TECH` |
| 방위사업청 | `SERVC_INST_DAPA_20260921_*` |
| 한국철도공사 | `SERVC_INST_KORAIL_20260914_ELEVATOR` |
| 한국농어촌공사 | `SERVC_INST_KRC_20260624_*` |
| 한국도로공사 | `SERVC_INST_KOEX_20221001_*` |
| 한국가스공사 | `SERVC_INST_KOGAS_20260709_*`, `..._FACILITY` |
| 한국전력기술 | `SERVC_INST_KEPCOEC_20250820_*` |
| 한국수자원공사 | `SERVC_INST_KWATER_20260630_*` |
| 한국수력원자력 | `SERVC_INST_KHNP_20260619_*` |
| 한국지역난방공사 | `SERVC_INST_KDHC_20260101_*` |
| 한국석유공사 | `SERVC_INST_KNOC_20190930_*` |
| 인천국제공항공사 | `SERVC_INST_IIAC_20250101_*` |
| 인천공항시설관리(주) | `SERVC_INST_IIAFM_20250901_*` |

### 7.2 값 매핑

- band 의 `lower`/`upper` 를 `PriceBand.upper_bound` 로 옮긴다(`upper` 미만 규약이 현행 `PriceBand` 와 일치).
- `B`→`max_price_score`, `k`→`multiplier`, `base_ratio`→`base_rate`(0~1 스케일로 변환), `pass_score`→`ThresholdBand.pass_threshold`.
- `lwlt_rate` 는 `PriceBand.lwlt_rate` 로 넣는다(구간별 하한율). 공고 하한율이 있으면 언제나 공고값이 우선한다는 현행 규칙을 유지한다.
- `k=None` 구간은 규칙에 넣지 않거나 `None` 과 사유를 남긴다. 추측하지 않는다.
- 가스공사처럼 `B` 가 배열인 규칙은 `max_price_score` 단일 필드로 표현할 수 없으므로, R2 는 별도 표현(용역 유형 축)을 설계하거나 해당 구간을 보류한다. 이 항목은 R2 설계 결정 사항이다.

### 7.3 시험 목록

| # | 시험 | 유형 |
| ---: | --- | --- |
| 1 | `institution_rules_20261013.yaml` 가 파싱되고 기관 18·band 189 가 로드된다 | 단위 |
| 2 | 확인·부분 기관의 모든 band 가 `B`·`base_ratio`·`pass_score`·`source` 를 가진다 | 단위(스키마) |
| 3 | `lwlt_rate` 가 `base_ratio − (100 − pass_score)/k` 의 .995 표기와 일치한다 | 단위(계산) |
| 4 | 기관 코드 일치 / 공백 제거 이름 일치로 기관 규칙이 선택된다 | 단위(매칭) |
| 5 | 조달청 대행 공고에서 기관 규칙이 배제되고 조달청 기준이 선택된다(플래그 on) | 단위(판정) |
| 6 | 수요기관이 조달청 대행 플래그 off 이면 기관 규칙이 선택된다 | 단위(판정) |
| 7 | `INSTITUTION > REGION > ALL` 우선순위가 지켜지고, LOCAL 계약은 기관 규칙을 배제한다 | 단위(우선순위) |
| 8 | `k=None` 구간은 선택되어도 하한율을 만들지 않고 사유를 남긴다 | 단위(회귀) |
| 9 | **mock 없는 API 끝단 최저투찰금액 대조**: 실제 공고 3건(인천국제공항공사 `R25BK01060561`, 한국석유공사 `R26BK01716376`, 대구광역시 `R25BK01157938`)을 대상으로 실제 API(모의 객체 없음)를 호출해 응답의 최저투찰금액·역산 하한율을 명세의 `lwlt_rate × 예정가격` 과 대조한다 | E2E(실제 API) |
| 10 | 시행일 대조: 기관 규칙 시행일보다 앞선 공고는 `RULE_REGIME_MISMATCH` 로 차단된다 | 단위(회귀) |

시험 9 는 `tests/` 의 기존 API 끝단 시험 패턴을 따르며, DB·API 가 꺼져 있으면 skip 하지 않고 사유를 남긴다(정본 게이트 원칙).

### 7.4 R2 완료 조건

- 확인 기관 10곳의 band 가 규칙으로 등록되고 시험 1~10 이 통과한다.
- 부분 기관 5곳의 확정 band 만 등록하고, 미확정 행은 `None` 과 사유를 남긴다.
- 미확인 기관 3곳(LH·한전 전력연구원·한전KPS)은 규칙을 만들지 않고 `RULE_NOT_FOUND` 경로를 유지한다.

---

## 8. 미확정·미확인·잔여 리스크

| 항목 | 내용 |
| --- | --- |
| 방위사업청 10억원 이상 | 계수 생략 + 평탄 문장 부재로 k 미확정(규칙 5). 나머지 3구간은 검산 일치 |
| 한국도로공사 | 현행 2022-10-01 판 원문 미확보. 별표 1-1·별표 2 미확정. 등급 부분 유지 |
| 한국전력기술 | 별표 1-1·1-5 k 미확정. 여러 별표 평탄 점수 미인쇄 |
| 한국수자원공사 | 별표 5·6·7의2·7의3·8 은 대입값이 0.010~0.025점 달라 미확정. 별표 7의1 k 미확정 |
| 한국철도공사 | 전사 일반용역은 조달청 준용이라 기관 규칙 대상이 아니다(승강기 점검보수 한정만 자체) |
| 미확인 3곳 | LH·한전 전력연구원·한전KPS 는 접속 실패·보안모듈·스크립트 렌더링으로 원문 미확보(규칙 9: 부재로 단정하지 않음) |
| 구조 미결 | 한국가스공사의 용역 유형별 B(30/50/70)는 현행 `PriceBand` 단일 `max_price_score` 로 표현되지 않는다. R2 설계 결정 필요 |
| 판정 미결 | 조달청 대행 시 수요기관 자체 규칙 배제 여부는 규정 조문 근거가 없어 **사용자 결정 필요**(5.3) |

---

## 9. 검증

| 항목 | 값 |
| --- | --- |
| 검증 명령 | `python3 scripts/validate_agent_rules.py --quiet` |
| 검증 명령 | `uv run pytest tests/test_validate_doc_links.py -q` |
| YAML 파싱 | `python3 -c "import yaml; yaml.safe_load(open('data/reference/institution_rules_20261013.yaml'))"` |
| 코드 변경 | 없음. `src/app/services/evaluation_rules.py`, 테스트, DB 스키마, Meilisearch 색인, Docker 관련 파일 미변경 |
| 변경 파일 | `docs/analysis/institution_rule_inventory_20261013.md`, `data/reference/institution_rules_20261013.yaml` (문서·명세 2개) |
| 작업 브랜치 | `kwanbum217/r1-institution-rule-inventory` (`main` 직접 커밋 없음) |

---

## 10. 참고

- [institution_rules_20261013.yaml](../../data/reference/institution_rules_20261013.yaml) — 기계 판독 명세
- [servc_formula_collection_central_20261004.md](servc_formula_collection_central_20261004.md) — 중앙부처·공단 9곳
- [servc_formula_collection_energy_20261004.md](servc_formula_collection_energy_20261004.md) — 에너지·공항 8곳
- [servc_formula_collection_local_20261004.md](servc_formula_collection_local_20261004.md) — 지자체 12곳(REGION)
- [servc_formula_kogas_qualification_20261004.md](servc_formula_kogas_qualification_20261004.md) — 한국가스공사
- [servc_formula_userfiles_agency_20261004.md](servc_formula_userfiles_agency_20261004.md) — 사용자 제공 공공기관 6건
- [servc_formula_userfiles_existing_20261004.md](servc_formula_userfiles_existing_20261004.md) — 사용자 제공 기관 5건
- [servc_formula_userfiles_local_20261004.md](servc_formula_userfiles_local_20261004.md) — 사용자 제공 지자체 11건(REGION)
- [servc_formula_recover_a_20261005.md](servc_formula_recover_a_20261005.md) — 인천국제공항·한국석유공사 등
- [servc_formula_recover_b_20261005.md](servc_formula_recover_b_20261005.md) — 한국도로공사·한국철도공사 등
- [servc_formula_recover_c_20261005.md](servc_formula_recover_c_20261005.md) — 서울·부산 등 5곳(REGION)
- [servc_formula_resolve_daegu_dapa_gg_20261005.md](servc_formula_resolve_daegu_dapa_gg_20261005.md) — 대구·방위사업청·경기도 재판정
- [20260930_servc_formula_recalc_kwater_koex.md](20260930_servc_formula_recalc_kwater_koex.md) — 수자원공사·도로공사 재계산
- [20260930_servc_formula_recalc_ince_molit.md](20260930_servc_formula_recalc_ince_molit.md) — 인천국제공항·국토교통부
- [institution_formula_unresolved_20261012.md](institution_formula_unresolved_20261012.md) — 미확정 9행 재조사
- [institution_formula_g2b_attachment_sweep_20261012.md](institution_formula_g2b_attachment_sweep_20261012.md) — 나라장터 첨부 조사
- `src/app/services/evaluation_rules.py` — 규칙 레지스트리(이번 작업에서 미변경)
