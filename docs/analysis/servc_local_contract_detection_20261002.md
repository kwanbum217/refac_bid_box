# 용역 지방계약 판별 원천 조사

> 작성일: 2026-10-02
> 범위: Servc 공고, `bid_ntce_dt >= 2025-01-01`
> 판정 상태: 원천 법령/예비가격 범위율 키는 확인되지 않음. 기관 유형은 간접 신호만 확인됨.

## 1. 요약

**확인 사실.** 조사 대상은 372,766건이며 현재 `_is_local_contract`는 `raw_data.cntrctCnclsMthdNm`과 정규 컬럼 `cntrct_mthd_nm`에서 “지방” 포함 여부만 검사합니다. 코디네이터가 운영 전체 용역 2,126,568건에서 해당 계약방법 4종에 “지방” 포함이 0건임을 이미 실측했으므로, 이 함수는 현행 자료에서 항상 `False`입니다. 판정 함수의 위치와 호출은 `src/app/api/v1/evaluations.py`의 `_is_local_contract` 및 `_scenario_prices`입니다.

**확인 사실.** 113종 키 감사와 2025년 이후 키 이름·채움률 집계에서 법령 구분 또는 예비가격 범위율을 직접 나타내는 키는 확인되지 않았습니다. `presmptPrce`는 372,766건(100%), `totPrdprcNum`·`drwtPrdprcNum`은 각각 369,702건(99.18%), 두 필드 동시 존재도 369,702건입니다. `prearngPrceDcsnMthdNm`은 372,765건에서 “복수예가” 208,057건, “비예가” 111,478건, “단일예가” 53,139건이며, ±2%/±3% 수치를 뜻하지 않습니다.

**판정 제안.** 명시 범위율이 있는 경우에만 그 값을 우선 사용하고, 현재 확인한 키 목록에서는 그러한 원천이 없습니다. 기관 코드도 지방계약법 적용 여부를 직접 구분하지 않으므로 지금 자료만으로 `LOCAL`을 확정할 안정적 규칙은 없습니다. 판별 불가 값은 `None`으로 남기고 가격 시나리오도 국가 기본값으로 묵시 대체하지 않도록 후속 구현/제품 정책에서 결정해야 합니다. 지방자치단체·교육기관·지방공기업 이름을 곧바로 `LOCAL`로 승격하는 규칙은 이번 근거만으로 승인할 수 없습니다.

## 2. 조사 범위와 라벨 한계

DB 읽기는 `uv run python scripts/db_readonly_query.py --sql ...`만 사용했습니다. 해당 스크립트는 읽기 전용 트랜잭션으로 연결합니다. 조사 기준일의 데이터 스냅샷이나 외부 기관 코드표는 반입하지 않았습니다.

기관명 라벨은 `dminstt_nm` 문자열에 아래 단어가 포함되는지 SQL 정규식으로 기계 분류했습니다.

| 라벨 | 이름 정규식 | 해석과 한계 |
|---|---|---|
| 자치단체청 | `시청|군청|구청|도청|특별자치도` | 자치단체 발주기관의 부분 집합. 본청 외 사업소·직속기관을 놓칠 수 있고 명칭만으로 법 적용을 증명하지 않음 |
| 교육기관 | `교육청|교육지원청` | 교육행정기관 후보. 학교·교육 관련 공공기관은 빠질 수 있음 |
| 공기업·공단 | `공사|공단` | 국가·지방 공기업이 섞이고 이름에 문자열이 들어가는 비기관도 가능. 지방계약 적용 정답 라벨이 아님 |
| 국가기관 지방청 | `지방청|지청` | “지방”이 기관명에 들어가도 지방계약 적용을 뜻하지 않는 반례군 |

이 라벨은 코드 접두사 분포를 비교하기 위한 프록시일 뿐 정답 법령 라벨이 아닙니다. 따라서 아래 정밀도·재현율은 **문자열 라벨을 재현하는 정도**이며, 지방계약법의 실제 정확도를 뜻하지 않습니다.

## 3. 원천 키와 예비가격 정보

기존 12개 연도 113종 키 감사(`docs/design/servc_raw_data_key_audit_20260809.md`)를 기준으로, 이름에서 `Rng`, `Rate`, `Lmt`, `Law`, `Rgl`, 기관 코드·명, 예비가격을 연상시키는 키를 용역 최근 구간에서 재검색했습니다. 최근 구간에는 113종 전체 키를 대상으로 해당 패턴 키의 존재 여부와 채움 수를 세었습니다.

| 키 | 채움 행 / 전체 372,766 | 관측 값 | 의미 판정 |
|---|---:|---|---|
| `presmptPrce` | 372,766 (100%) | 금액 | 추정가격. 예비가격 변동률이 아님 |
| `prearngPrceDcsnMthdNm` | 372,765 (100%) | 복수예가 208,057; 비예가 111,478; 단일예가 53,139; 빈 문자열 91; JSON null 1 | 예가 결정 방법. 범위 폭(±2/±3%) 아님 |
| `totPrdprcNum` | 369,702 (99.18%) | 정수 매개변수 | 복수예비가격 총수 |
| `drwtPrdprcNum` | 369,702 (99.18%) | 정수 매개변수 | 추첨 예비가격 수 |
| `cntrctCnclsMthdNm` | 372,766 (100%, 기존 코디네이터 실측) | 제한경쟁·수의계약·일반경쟁·지명경쟁 | “지방” 문자열 0건. 법령 구분이 아님 |
| `sucsfbidLwltRate` | 368,003 (98.72%) | 상위 값은 88, 87.745, 90 등 | 낙찰하한율. 예비가격 범위율과 다른 값 |
| `rgnLmtBidLocplcJdgmBssCd/Nm` | 각 365,345 (98.01%) | `N` 80,141; `Y` 2,541; 본사/참여지사 소재지 80,141; 본사 소재지 2,541 | 지역제한 입찰 판단. 법령·가격 범위가 아님 |
| `dminsttCd`, `ntceInsttCd` | 각 372,766 (100%) | 코드 | 기관 식별자. 두 코드 값이 다른 행 35,080 (9.41%) |
| `dminsttNm`, `ntceInsttNm` | 각 372,766 (100%) | 기관명 | 각각 수요기관·공고기관. 적용법 필드는 아님 |

키 이름 패턴 검색에서 직접 `Rng`/`Law`/`Rgl`을 담은 법령·범위율 키는 나오지 않았습니다. `Rate` 이름으로 잡힌 `sucsfbidLwltRate`는 낙찰하한율이므로 의미를 혼동하면 안 됩니다. 이 결과는 DB에 값이 없다는 증거이지, 나라장터 API 명세 전체에 그러한 항목이 없다는 증명은 아닙니다.

복수예가 두 필드가 모두 존재하는 건수는 369,702건(전체 99.18%)입니다. 다만 두 값은 추첨 방식 매개변수일 뿐 ±범위를 정하지 않습니다. 이를 토대로 범위율을 복원할 수 없습니다.

## 4. 기관 코드 형식과 접두사 교차

| 관측 항목 | 값 |
|---|---:|
| `dminsttCd` 채움 | 372,766 / 372,766 (100%) |
| `ntceInsttCd` 채움 | 372,766 / 372,766 (100%) |
| `dminsttCd` 길이 | 7자리만 관측 |
| 고유 `dminsttCd` | 15,002 |
| 고유 `ntceInsttCd` | 14,655 |
| `dminsttCd = ntceInsttCd` | 337,686 (90.59%) |
| 코드 불일치 | 35,080 (9.41%) |

코드 첫 글자와 기관명 라벨 교차 결과는 다음과 같습니다. 각 행의 분모는 해당 첫 글자 코드의 공고 수이며 라벨 집계는 독립적으로 중복될 수 있습니다.

| 첫 글자 | 공고 수 | 고유 코드 수 | 자치단체청 라벨 | 교육기관 라벨 | 공기업·공단 라벨 | 국가기관 지방청 라벨 |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 46,501 | 854 | 140 | 0 | 0 | 163 |
| 3 | 22,356 | 235 | 0 | 0 | 0 | 0 |
| 4 | 33,838 | 339 | 14,157 | 0 | 0 | 0 |
| 5 | 39,572 | 381 | 0 | 0 | 0 | 0 |
| 6 | 29,479 | 570 | 4,697 | 0 | 0 | 0 |
| 7 | 47,194 | 4,940 | 2,383 | 35,246 | 0 | 0 |
| 8 | 15,115 | 1,957 | 3,334 | 15,111 | 0 | 0 |
| 9 | 7,476 | 807 | 613 | 6,342 | 0 | 0 |
| A | 4 | 1 | 0 | 0 | 0 | 0 |
| B | 53,994 | 743 | 571 | 0 | 17,994 | 0 |
| C | 2,253 | 149 | 0 | 0 | 0 | 0 |
| D | 13,904 | 226 | 13 | 0 | 13,690 | 0 |
| P | 1 | 1 | 0 | 0 | 0 | 0 |
| Z | 61,079 | 3,799 | 890 | 15 | 10,523 | 0 |

교육기관 이름 라벨 56,714건 중 코드를 7·8·9로 시작하는 공고는 56,699건으로 라벨 재현율 99.97%, 해당 세 접두 전체 69,785건 중 교육기관 라벨은 56,699건으로 문자열 라벨 정밀도 81.24%입니다. 이는 교육기관 코드 군집 후보로는 유용하지만, 교육기관 모두가 같은 계약법을 적용하는지 확인하지 못했으며 법령 판정 성능으로 해석하면 안 됩니다.

자치단체청 라벨은 코드 첫 글자 4에만 모이지 않습니다(첫 글자 4, 6, 7, 8, 9, B, Z에서 관측). 첫 글자 4만 쓰면 자치단체청 라벨 재현율은 14,157/26,798=52.83%, 정밀도는 14,157/33,838=41.84%입니다. 여러 접두를 조합하면 회수율은 오르지만 교육기관·공기업·기타 기관과 혼합됩니다. 따라서 코드 길이 7자리라는 사실과 접두 분포만으로 지방자치단체·지방교육청·지방공기업을 안정적으로 구별할 규칙을 세울 수 없습니다.

기관명 프록시 행 수는 자치단체청 26,798, 교육기관 56,714, 공기업·공단 42,207, 국가기관 지방청 163입니다. 자치단체청/교육기관을 합한 엄격한 후보군은 77,184건(20.70%)이고, 공사·공단까지 더한 넓은 후보군은 119,200건(31.97%)입니다. 넓은 후보군에서 복수예가 두 필드가 모두 있는 건수는 118,753건입니다. 이 수치는 지방계약으로 확인된 건수가 아니라 기관명 규칙의 잠재 영향 상한에 가까운 분석 후보량입니다. 정밀도/재현율을 실제 적용 법령 기준으로 산출할 골드 라벨이 없어 법령 기준 수치는 미상입니다.

## 5. 후보 규칙 우선순위와 오판 위험

| 우선순위 | 후보 원천 | 현재 판단 | 오판 위험 및 미상 처리 |
|---:|---|---|---|
| 1 | 공고에 명시된 범위율 또는 적용 법령 키 | 이 113종 키 및 최근 용역 값에서는 미발견. 값이 확인되면 직접 범위율이 최우선이며, 법령명보다 계산 범위 자체를 우선 반영 | 문자열 단위를 퍼센트/비율로 오해할 수 있으므로 `0.03`과 `3`의 정규화, 허용 범위, ±표기 파싱을 검증해야 함. 키 결측·이상치는 `None` |
| 2 | `dminsttCd`/`ntceInsttCd` 코드 분류 | 7자리 고정, 접두와 이름 유형 사이 군집은 있으나 코드표 없이 법령 규칙으로 확정 불가 | 발주기관과 수요기관 코드가 9.41% 다름. 지방 소속 국가기관(지방청), 지방공기업 등 오판. 외부 공식 코드표와 법령 적용범위 확인 전 `None` |
| 3 | 기관명 패턴 | 명확한 시·군·구·도청/교육청 명칭은 사람이 검토할 후보로 쓰되 자동 `LOCAL` 근거로는 부족. 공사·공단 패턴은 특히 범위가 넓음 | 국가기관 지방청은 이름에 “지방”이 있어도 지방계약을 의미하지 않음. 공기업의 설립·발주 주체에 따라 법 적용이 다를 수 있음. 혼합/불명 기관은 `None` |

현재 시나리오 함수의 `range_rate`가 제공되면 기본 `is_local_contract`보다 우선하며, 값이 없으면 `is_local_contract=True`일 때 ±3%, 아니면 ±2%를 고릅니다. 따라서 판별 불가 `None`을 `False`로 강제 변환하면 다시 국가 ±2%가 묵시 적용될 수 있습니다. 계산 API는 미상 상태를 표현하거나 사용자 확인을 요구하는 정책이 필요합니다.

## 6. 잠정 영향 건수

| 범위 정의 | 후보 공고 수 | 전체 중 비율 | 복수예가 두 필드 모두 존재 |
|---|---:|---:|---:|
| 자치단체청 + 교육기관 이름 라벨 | 77,184 (20.70%) | 20.70% | 76,988 |
| 위 범위 + 공사·공단 이름 라벨 | 119,200 (31.97%) | 31.97% | 118,753 |
| 법령 적용이 실측으로 확정된 지방계약 | 0건 확인 가능 | 산출 불가 | 산출 불가 |

마지막 행이 중요한 한계입니다. 현재 데이터는 실제 지방계약으로 확인된 양성 건을 제공하지 않으므로, 위 후보 수를 “지방계약 건수”나 정밀한 예측 영향으로 보고하면 안 됩니다. 확정 영향 건수는 외부 공식 기관 코드/법령 적용 표 또는 공고 원문 증거를 확보한 뒤 계산해야 합니다.

## 7. 구현 제안 및 사용자 결정 사항

병렬 빌더가 `services`에 `contract_regime` 추출 함수 하나를 두는 설계를 전제로, API의 `_scenario_prices`에서 별도 `_is_local_contract` 대신 그 추출 결과를 사용하도록 연결하는 방안을 제안합니다. 추출기는 원천 직접값이 확인되면 `LOCAL`/`NATIONAL`과 정규화 범위율을 함께 반환하고, 식별 근거가 없으면 `None`을 반환해야 합니다. 다만 현재 조사로는 직접 원천 키가 없으므로 이 단계에서는 코드/기관명 휴리스틱을 운영 판정으로 승격하지 않는 것이 근거에 맞습니다.

회귀 시험은 최소한 다음 반례를 고정해야 합니다.

- 계약방법 네 값(제한경쟁·수의계약·일반경쟁·지명경쟁)에 “지방”이 없어도 기관 기반 계약 레짐이 판정되어야 하는 지방자치단체 공고.
- 이름에 “지방청/지청”이 포함된 국가기관 발주 공고가 이름만으로 `LOCAL` 처리되지 않는 경우.
- 지방교육청과 학교/교육지원기관의 판정 정책을 분리하는 경우.
- `공사`/`공단` 이름을 가진 국가 공기업과 지방 공기업을 구별하지 못하면 `None`을 반환하는 경우.
- `dminsttCd != ntceInsttCd`일 때 어느 주체를 기준으로 하는지 정책에 따른 일관된 판정.
- 직접 범위율 값 `3`, `0.03`, `2`, `0.02`, 공백·잘못된 값이 적절히 정규화/거부되는 경우.
- 총수·추첨수 결측은 범위 판정과 독립적으로 처리되고, 범위 미상은 국가 ±2%로 조용히 오인되지 않는 경우.

**사용자가 결정해야 하는 항목:** 법령 판정 미상일 때 계산 중단/선택 요청/임시 국가 기본값 중 어떤 제품 정책을 채택할지, 교육기관을 지방계약 범위에 포함할지, 지방공기업을 발주 주체별로 분류할지, 공고기관 코드와 수요기관 코드 중 어느 것을 기준으로 삼을지입니다. 외부 공식 기관 코드표·법령 적용 정보를 도입할 수 있는지 확인이 선행되어야 합니다.

## 부록 A. 재현 명령과 SQL

모든 DB 수치는 프로젝트 루트에서 아래 실행기로 계산합니다. 이 스크립트는 MySQL 직접 클라이언트 접속 대신 읽기 전용 트랜잭션을 사용합니다.

```sh
uv run python scripts/db_readonly_query.py --sql "<아래 SQL>" --format json
```

### A.1 기준 공고 수

```sql
SELECT COUNT(*) AS n, MIN(bid_ntce_dt) AS min_dt, MAX(bid_ntce_dt) AS max_dt
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2025-01-01'
```

### A.2 키 이름별 채움 수

```sql
SELECT j.k AS raw_key, COUNT(*) AS rows_present
FROM bid_announcements b
JOIN JSON_TABLE(JSON_KEYS(b.raw_data), '$[*]' COLUMNS(k VARCHAR(128) PATH '$')) j
WHERE b.category='Servc' AND b.bid_ntce_dt >= '2025-01-01'
  AND JSON_TYPE(b.raw_data)='OBJECT'
  AND j.k REGEXP 'Rng|Rate|Lmt|Law|Rgl|Instt|Org|Dminstt|NtceInstt|Prdprc|Presmpt'
GROUP BY j.k ORDER BY rows_present DESC
```

### A.3 복수예가 관련 키와 명시적 금액 키 채움 수

```sql
SELECT COUNT(*) AS total,
 SUM(JSON_EXTRACT(raw_data,'$.totPrdprcNum') IS NOT NULL) AS tot_present,
 SUM(JSON_EXTRACT(raw_data,'$.drwtPrdprcNum') IS NOT NULL) AS drwt_present,
 SUM(JSON_EXTRACT(raw_data,'$.totPrdprcNum') IS NOT NULL AND JSON_EXTRACT(raw_data,'$.drwtPrdprcNum') IS NOT NULL) AS both_present,
 SUM(JSON_EXTRACT(raw_data,'$.presmptPrce') IS NOT NULL) AS presmpt_present
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2025-01-01'
```

### A.4 예가 결정·지역제한·하한율 값 분포

```sql
SELECT j.k,
 COALESCE(JSON_UNQUOTE(JSON_EXTRACT(b.raw_data, CONCAT('$.',j.k))),'(NULL)') AS v,
 COUNT(*) AS n
FROM bid_announcements b
JOIN JSON_TABLE('["prearngPrceDcsnMthdNm","rgnLmtBidLocplcJdgmBssNm","rgnLmtBidLocplcJdgmBssCd","sucsfbidLwltRate"]',
 '$[*]' COLUMNS(k VARCHAR(128) PATH '$')) j
WHERE b.category='Servc' AND b.bid_ntce_dt >= '2025-01-01'
GROUP BY j.k,v ORDER BY j.k,n DESC
```

### A.5 기관 코드 길이·고유 수·접두 종류

```sql
SELECT LENGTH(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd')))) AS code_len,
 COUNT(*) AS announcements,
 COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))) AS codes,
 COUNT(DISTINCT LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),1)) AS p1,
 COUNT(DISTINCT LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),2)) AS p2,
 COUNT(DISTINCT LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),3)) AS p3,
 COUNT(DISTINCT LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),4)) AS p4
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2025-01-01'
 AND JSON_TYPE(raw_data)='OBJECT'
 AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd')) NOT IN ('','null')
GROUP BY code_len ORDER BY code_len
```

### A.6 첫 글자 접두와 기관명 라벨 교차

```sql
SELECT LEFT(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),1) AS p1,
 COUNT(*) AS n,
 COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))) AS codes,
 SUM(dminstt_nm REGEXP '시청|군청|구청|도청|특별자치도') AS local_gov,
 SUM(dminstt_nm REGEXP '교육청|교육지원청') AS education,
 SUM(dminstt_nm REGEXP '공사|공단') AS corp,
 SUM(dminstt_nm REGEXP '지방청|지청') AS national_local_office
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2025-01-01'
 AND JSON_TYPE(raw_data)='OBJECT'
 AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd')) NOT IN ('','null')
GROUP BY p1 ORDER BY p1
```

### A.7 기관 코드 일치 여부와 후보량

```sql
SELECT COUNT(*) AS total,
 SUM(NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))),'') IS NOT NULL) AS dmin_code_filled,
 SUM(NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.ntceInsttCd'))),'') IS NOT NULL) AS ntce_code_filled,
 SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))=JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.ntceInsttCd'))) AS codes_equal,
 SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))<>JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.ntceInsttCd'))) AS codes_differ,
 COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.ntceInsttCd'))) AS ntce_codes,
 COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd'))) AS dmin_codes,
 SUM(dminstt_nm REGEXP '시청|군청|구청|도청|특별자치도|교육청|교육지원청') AS gov_edu_names,
 SUM(dminstt_nm REGEXP '시청|군청|구청|도청|특별자치도|교육청|교육지원청|공사|공단') AS gov_edu_corp_names,
 SUM((dminstt_nm REGEXP '시청|군청|구청|도청|특별자치도|교육청|교육지원청')
   AND JSON_EXTRACT(raw_data,'$.totPrdprcNum') IS NOT NULL
   AND JSON_EXTRACT(raw_data,'$.drwtPrdprcNum') IS NOT NULL) AS gov_edu_with_prdprc,
 SUM((dminstt_nm REGEXP '시청|군청|구청|도청|특별자치도|교육청|교육지원청|공사|공단')
   AND JSON_EXTRACT(raw_data,'$.totPrdprcNum') IS NOT NULL
   AND JSON_EXTRACT(raw_data,'$.drwtPrdprcNum') IS NOT NULL) AS gov_edu_corp_with_prdprc
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2025-01-01'
```

전역 운영 건수 2,126,568 및 계약방법 “지방” 0건은 코디네이터가 2026-10-02 수행한 사전 운영 질의 결과이며, 이 문서 조사에서 재실행하지 않았습니다.
