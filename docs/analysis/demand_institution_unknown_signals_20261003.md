# 수요기관 원천 필드 및 상위기관 단서 조사

> 작성일: 2026-10-03
> 대상: 2025-01-01 이후 공고일 기준 `Servc` 용역 공고 중 `classify_contract_regime` 결과가 미상(None)인 수요기관
> 기준 문서: `docs/analysis/demand_institution_regime_unknown_20261003.md`

## 요약

`raw_json`에는 사업자등록번호(`bizno`), 법인등록번호(`corprtRgstNo`), 기관 코드·명, 소관·유형, 상위기관, 주소·연락처·홈페이지 등 기관 대조와 분류에 쓸 필드가 있습니다. 상위 15개 미상 범주에서 사업자번호는 대체로 공고 기준 100%에 가깝게 채워져 있어 외부 공시와 기관 단위 대조를 시도할 수 있습니다. 다만 사업자번호와 법인번호가 법률상 계약 주체나 지방계약법 적용 여부를 직접 증명하지는 않습니다.

현재 미상 111,559건 가운데 상위기관이 기존 판정 규칙상 LOCAL인 연결은 26,038건, NATIONAL인 연결은 13,728건입니다. 따라서 상위기관 판정을 승계하는 접근의 조사 후보 상한은 두 값의 합인 39,766건입니다. 이 수는 법적으로 축소 가능한 건수가 아니며, 안전하게 판정할 수 있는 축소 건수는 법령·기관별 근거 확인 전까지 0건입니다.

## 재현 방법과 범위

모든 DB 수치는 아래 공통 대상을 사용합니다. 공고의 `raw_data.dminsttCd`로 `g2b_demand_institutions.dminstt_cd`를 연결하고 기존 `classify_contract_regime` 조건을 SQL로 옮겨 None만 셉니다. 재실행은 각 SQL을 `uv run python scripts/db_readonly_query.py --sql "<SQL>" --limit 200 --format json`에 넣습니다. 질의는 읽기 전용입니다.

공통 대상 CTE:

```sql
WITH bids AS (
    SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.dminsttCd')) AS dminstt_cd,
           COUNT(*) AS n
    FROM bid_announcements
    WHERE bid_ntce_dt >= '2025-01-01' AND category = 'Servc'
    GROUP BY 1
), unknowns AS (
    SELECT b.dminstt_cd, b.n, di.*
    FROM bids b
    LEFT JOIN g2b_demand_institutions di ON di.dminstt_cd = b.dminstt_cd
    WHERE CASE
      WHEN di.dminstt_cd IS NULL THEN 1
      WHEN TRIM(di.instt_ty_lrgclsfc_nm) = '교육행정조직'
       AND TRIM(di.instt_ty_midclsfc_nm) IN ('시, 도교육청','지역교육청','시, 도교육청 직속기관') THEN 0
      WHEN TRIM(di.jrsdctn_div_nm) IN ('지방자치단체','지방공기업') THEN 0
      WHEN TRIM(di.instt_ty_lrgclsfc_nm) IN ('초등학교','중학교','고등학교','특수학교','유치원')
       AND TRIM(di.instt_ty_smlclsfc_nm) = '공립' THEN 0
      WHEN TRIM(di.jrsdctn_div_nm) IN ('국가기관','공기업','준정부기관','정부투자기관') THEN 0
      ELSE 1 END = 1
)
```

`unknowns` CTE 뒤에 아래 집계를 붙여 재현합니다. 분류값 공백은 `NULLIF(TRIM(...), '')`로 `(없음)`에 합칩니다.

```sql
SELECT COALESCE(NULLIF(TRIM(jrsdctn_div_nm), ''), '(소관구분 없음)') AS juris,
       COALESCE(NULLIF(TRIM(instt_ty_lrgclsfc_nm), ''), '(대분류 없음)') AS large,
       COALESCE(NULLIF(TRIM(instt_ty_midclsfc_nm), ''), '(중분류 없음)') AS middle,
       SUM(n) AS bid_n,
       COUNT(DISTINCT dminstt_cd) AS institution_n
FROM unknowns
GROUP BY 1, 2, 3
ORDER BY bid_n DESC
LIMIT 15
```

이 집계는 기존 미상 분해 문서에 보고된 상위 범주 건수와 일치합니다. 대분류·중분류 값이 NULL인 기관도 미상에 포함되며, 기관 행이 없는 공고는 `(소관구분 없음)/(대분류 없음)/(중분류 없음)`으로 묶입니다.

## `raw_json` 원천 필드

다음은 `SELECT raw_json FROM g2b_demand_institutions WHERE raw_json IS NOT NULL LIMIT 1` 질의에서 확인한 한 원천 응답의 키 목록입니다. 이는 응답에 나타난 키 목록이며 스키마상 모든 레코드에서 키가 항상 존재한다는 뜻은 아닙니다.

| 용도 | 키 |
| --- | --- |
| 기관 식별 | `dminsttCd`, `dminsttNm`, `dminsttEngNm`, `dminsttAbrvtNm` |
| 사업자·법인 식별 | `bizno`, `corprtRgstNo` |
| 소관·유형 | `jrsdctnDivNm`, `insttTyCdLrgclsfcNm`, `insttTyCdMidclsfcNm`, `insttTyCdSmlclsfcNm` |
| 상위기관 | `toplvlInsttCd`, `toplvlInsttNm` |
| 소재지·연락 | `rgnCd`, `rgnNm`, `zip`, `adrs`, `dtlAdrs`, `telNo`, `faxNo`, `ofclFaxNo`, `hmpgAdrs` |
| 업종 | `bizcndtnNm`, `indstrytyNm` |
| 상태·기간 | `dltYn`, `vldPrdBgnDt`, `vldPrdEndDt`, `rgstDt`, `chgDt` |

## 미상 상위 범주별 식별 필드 채움 현황

아래 수치는 공고 건수 가중치 기준입니다. 같은 기관에 연결된 공고는 각각 한 건으로 셌습니다. SQL은 공통 `unknowns` CTE 다음에 붙이며, 각 필드의 값이 NULL이 아니고 빈 문자열도 아닌 공고 수를 냅니다.

```sql
SELECT COALESCE(NULLIF(TRIM(jrsdctn_div_nm), ''), '(소관구분 없음)') AS juris,
       COALESCE(NULLIF(TRIM(instt_ty_lrgclsfc_nm), ''), '(대분류 없음)') AS large,
       COALESCE(NULLIF(TRIM(instt_ty_midclsfc_nm), ''), '(중분류 없음)') AS middle,
       SUM(n) AS bid_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.bizno') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.bizno')) <> '')) AS bizno_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.corprtRgstNo') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.corprtRgstNo')) <> '')) AS corp_reg_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.toplvlInsttCd') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.toplvlInsttCd')) <> '')) AS parent_code_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.dminsttEngNm') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.dminsttEngNm')) <> '')) AS eng_name_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.adrs') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.adrs')) <> '')) AS address_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.telNo') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.telNo')) <> '')) AS phone_n,
       SUM(n * (JSON_EXTRACT(raw_json,'$.hmpgAdrs') IS NOT NULL AND JSON_UNQUOTE(JSON_EXTRACT(raw_json,'$.hmpgAdrs')) <> '')) AS homepage_n
FROM unknowns
GROUP BY 1, 2, 3
ORDER BY bid_n DESC
LIMIT 15
```

`parent_code_n`은 원천 JSON 코드 존재 여부이며, 아래 상위기관 판정 질의의 `toplvl_instt_cd` DB 컬럼 존재 여부와 같습니다. `비율 = 각 *_n / bid_n`입니다. 다음 추가 집계는 앞서 설명한 공통 `unknowns` CTE의 전체 미상 111,559건을 대상으로 원천 응답에서 확인한 각 키의 비어 있지 않은 값 비율을 계산합니다.

```sql
, fieldkeys AS (
    SELECT 'dminsttCd' AS k UNION ALL SELECT 'dminsttNm' UNION ALL SELECT 'dminsttEngNm'
    UNION ALL SELECT 'dminsttAbrvtNm' UNION ALL SELECT 'bizno' UNION ALL SELECT 'corprtRgstNo'
    UNION ALL SELECT 'jrsdctnDivNm' UNION ALL SELECT 'insttTyCdLrgclsfcNm'
    UNION ALL SELECT 'insttTyCdMidclsfcNm' UNION ALL SELECT 'insttTyCdSmlclsfcNm'
    UNION ALL SELECT 'toplvlInsttCd' UNION ALL SELECT 'toplvlInsttNm' UNION ALL SELECT 'rgnCd'
    UNION ALL SELECT 'rgnNm' UNION ALL SELECT 'zip' UNION ALL SELECT 'adrs' UNION ALL SELECT 'dtlAdrs'
    UNION ALL SELECT 'telNo' UNION ALL SELECT 'faxNo' UNION ALL SELECT 'ofclFaxNo'
    UNION ALL SELECT 'hmpgAdrs' UNION ALL SELECT 'bizcndtnNm' UNION ALL SELECT 'indstrytyNm'
    UNION ALL SELECT 'dltYn' UNION ALL SELECT 'vldPrdBgnDt' UNION ALL SELECT 'vldPrdEndDt'
    UNION ALL SELECT 'rgstDt' UNION ALL SELECT 'chgDt'
)
SELECT k, SUM(n) AS total_bid_n,
       SUM(n * (JSON_EXTRACT(raw_json, CONCAT('$.', k)) IS NOT NULL
                AND JSON_UNQUOTE(JSON_EXTRACT(raw_json, CONCAT('$.', k))) <> '')) AS filled_bid_n
FROM unknowns CROSS JOIN fieldkeys
GROUP BY k ORDER BY k
```

| 원천 키 | 채움 비율 | 원천 키 | 채움 비율 |
| --- | ---: | --- | ---: |
| `adrs` | 98.2% | `bizcndtnNm` | 60.7% |
| `bizno` | 97.6% | `chgDt` | 97.8% |
| `corprtRgstNo` | 37.6% | `dltYn` | 98.2% |
| `dminsttAbrvtNm` | 70.2% | `dminsttCd` | 98.2% |
| `dminsttEngNm` | 97.5% | `dminsttNm` | 98.2% |
| `dtlAdrs` | 98.2% | `faxNo` | 97.6% |
| `hmpgAdrs` | 53.6% | `indstrytyNm` | 60.0% |
| `insttTyCdLrgclsfcNm` | 74.8% | `insttTyCdMidclsfcNm` | 71.8% |
| `insttTyCdSmlclsfcNm` | 24.9% | `jrsdctnDivNm` | 98.2% |
| `ofclFaxNo` | 86.0% | `rgnCd` | 97.6% |
| `rgnNm` | 97.6% | `rgstDt` | 98.2% |
| `telNo` | 97.6% | `toplvlInsttCd` | 98.2% |
| `toplvlInsttNm` | 93.6% | `vldPrdBgnDt` | 10.4% |
| `vldPrdEndDt` | 10.4% | `zip` | 97.6% |

| 미상 소관 / 대분류 / 중분류 | 공고 수 | 사업자번호 | 법인번호 | 상위기관 코드 | 영문명 | 주소 | 전화 | 홈페이지 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 기타기관 / 없음 / 없음 | 19,373 | 96.6% | 33.9% | 99.9% | 96.6% | 100.0% | 96.5% | 47.1% |
| 교육기관 / 고등교육기관 / 4년제 정규대학 | 8,174 | 100.0% | 15.3% | 100.0% | 100.0% | 100.0% | 100.0% | 58.8% |
| 기타기관 / 산하기관 / 기타 | 7,252 | 100.0% | 51.4% | 100.0% | 100.0% | 100.0% | 100.0% | 56.0% |
| 기타공공기관 / 산하기관 / 정부출연기관 | 7,031 | 100.0% | 58.4% | 100.0% | 100.0% | 100.0% | 100.0% | 77.4% |
| 기타기관 / 산하기관 / 정부출연기관 | 6,448 | 100.0% | 31.7% | 100.0% | 100.0% | 100.0% | 100.0% | 78.0% |
| 기타공공기관 / 산하기관 / 기타 | 5,802 | 100.0% | 49.2% | 100.0% | 100.0% | 100.0% | 100.0% | 74.6% |
| 기타기관 / 정부투자기관및기타 / 기타 | 5,591 | 100.0% | 60.3% | 100.0% | 100.0% | 100.0% | 100.0% | 42.6% |
| 기타공공기관 / 없음 / 없음 | 3,939 | 100.0% | 27.6% | 100.0% | 100.0% | 100.0% | 100.0% | 69.7% |
| 기타기관 / 고등학교 / 일반계 고등학교 | 3,482 | 100.0% | 7.8% | 100.0% | 99.5% | 100.0% | 100.0% | 29.3% |
| 기타공공기관 / 산하기관 / 정부보조기관 | 3,161 | 100.0% | 69.5% | 100.0% | 100.0% | 100.0% | 100.0% | 73.3% |
| 기타기관 / 고등교육기관 / 4년제 정규대학 | 2,963 | 100.0% | 18.3% | 100.0% | 100.0% | 100.0% | 100.0% | 43.2% |
| 지자체 출자출연기관 / 없음 / 없음 | 2,434 | 100.0% | 58.4% | 100.0% | 100.0% | 100.0% | 100.0% | 55.5% |
| 지자체 출자출연기관 / 산하기관 / 정부출연기관 | 2,223 | 100.0% | 56.9% | 100.0% | 100.0% | 100.0% | 100.0% | 61.7% |
| 교육기관 / 초등학교 / 초등학교(본교) | 2,128 | 100.0% | 1.3% | 100.0% | 99.7% | 100.0% | 100.0% | 15.2% |
| 미수집 / 기관 행 없음 | 2,043 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

사업자번호가 높은 비율로 있어 지방공공기관 통합공시의 기관 식별정보, 공공기관 알리오의 기관 정보와 대조를 시도할 수 있습니다. 법인등록번호도 보조키가 될 수 있으나 값이 비어 있는 비율이 높습니다. 이번 조사에서는 외부 사이트를 조회하지 않았으며, 식별자 정규화·법인 단위 매핑·대조 정확도는 확인되지 않았습니다. 사업자번호의 주체가 수요기관 법인인지 개별 사업장인지, 공고 계약 당사자와 일치하는지도 대조 과정에서 검증해야 합니다.

## 상위기관 분류 신호

상위기관 코드로 동일 테이블을 다시 연결하고 기존 기관 판정 규칙을 적용했습니다. 다음 질의는 공통 `unknowns` CTE 뒤에 사용합니다.

```sql
SELECT CASE
         WHEN p.jrsdctn_div_nm IN ('지방자치단체','지방공기업')
           OR (TRIM(p.instt_ty_lrgclsfc_nm)='교육행정조직'
               AND TRIM(p.instt_ty_midclsfc_nm) IN ('시, 도교육청','지역교육청','시, 도교육청 직속기관')) THEN 'LOCAL'
         WHEN p.jrsdctn_div_nm IN ('국가기관','공기업','준정부기관','정부투자기관') THEN 'NATIONAL'
         ELSE '미판정' END AS parent_regime,
       SUM(u.n) AS bid_n,
       COUNT(DISTINCT u.dminstt_cd) AS institution_n
FROM unknowns u
LEFT JOIN g2b_demand_institutions p ON p.dminstt_cd = u.toplvl_instt_cd
GROUP BY 1
ORDER BY bid_n DESC
```

집계 결과는 상위기관 LOCAL 26,038건, NATIONAL 13,728건, 기존 규칙으로 미판정 71,793건입니다. 이 질의는 상위기관이 현재 기준으로 판정되는지를 잴 뿐, 그 결과를 자식 수요기관의 법령상 계약 주체에 승계해도 되는지를 증명하지 않습니다.

| 미상 수요기관 범주 | 해당 미상 공고 | LOCAL 상위기관 공고 | NATIONAL 상위기관 공고 | 미상/미연결 상위기관 공고 |
| --- | ---: | ---: | ---: | ---: |
| 기타기관 / 분류 없음 | 19,373 | 3,447 | 1,219 | 14,707 |
| 교육기관 / 고등교육기관 / 4년제 정규대학 | 8,174 | 0 | 6,476 | 1,698 |
| 기타기관 / 산하기관 / 기타 | 7,252 | 939 | 378 | 5,935 |
| 기타공공기관 / 산하기관 / 정부출연기관 | 7,031 | 0 | 33 | 6,998 |
| 기타기관 / 산하기관 / 정부출연기관 | 6,448 | 364 | 436 | 5,648 |
| 기타공공기관 / 산하기관 / 기타 | 5,802 | 0 | 139 | 5,663 |
| 기타기관 / 정부투자기관및기타 / 기타 | 5,591 | 819 | 355 | 4,417 |
| 기타공공기관 / 분류 없음 | 3,939 | 25 | 7 | 3,907 |
| 기타기관 / 고등학교 / 일반계 고등학교 | 3,482 | 3,254 | 11 | 217 |
| 기타공공기관 / 산하기관 / 정부보조기관 | 3,161 | 0 | 1 | 3,160 |
| 기타기관 / 고등교육기관 / 4년제 정규대학 | 2,963 | 0 | 1,324 | 1,639 |
| 지자체 출자출연기관 / 분류 없음 | 2,434 | 2,249 | 21 | 164 |
| 지자체 출자출연기관 / 산하기관 / 정부출연기관 | 2,223 | 1,497 | 0 | 726 |
| 교육기관 / 초등학교 / 초등학교(본교) | 2,128 | 2,091 | 25 | 12 |

상위 15 범주별 수치도 공통 `unknowns` CTE를 사용합니다. 위 표의 `미상/미연결`은 `해당 미상 공고 - LOCAL 상위기관 공고 - NATIONAL 상위기관 공고`로 재현할 수 있습니다. 미수집 2,043건은 전부 상위기관 코드가 없습니다.

승계가 부정확할 수 있는 반례는 대학에서 특히 분명합니다. 미상 범주인 국립대학·국립대학법인·대학 부설기관은 상위기관이 교육부(NATIONAL)로 연결될 수 있지만, 교육부와 대학/법인의 계약 주체가 같다고 단정할 수 없습니다. 반대로 지방자치단체 산하 기관·출자출연기관은 상위기관이 LOCAL이어도 기관 자체가 지방출자출연법 제2조·제17조의 적용 대상인지, 지방공기업 또는 공공기관 지정 등 적용 제외인지 확인해야 합니다. 일반 산하기관 역시 모기관의 법령 지위만으로 자회사·별도 법인의 계약법을 확정할 수 없습니다.

따라서 상위기관 신호는 기관별 법적 지위 조사와 후보 정렬에는 유용하지만, 그 판정을 미상 수요기관에 그대로 물려주는 규칙은 만들 수 없습니다.

## 다음 세션 권고와 기대 상한

1. 사업자번호를 키로 지방공공기관 통합공시와 알리오 기관 목록을 기관 단위로 대조하고, 기관명·법인번호·수요기관 코드의 일치 및 법인 관계를 검증합니다. 외부 공시의 지방출자출연기관 여부나 공공기관 지정값은 후보 증거로 수집하되, 계약 주체·적용 조항과 적용 제외 조항을 별도 법령 근거로 확인해야 합니다.
2. 상위기관이 LOCAL인 26,038건과 NATIONAL인 13,728건, 합계 39,766건을 대조 우선 후보의 최대 규모로 둡니다. 이는 질의로 확인한 수요기관 미상 공고 중 기존 분류 가능한 상위기관에 연결된 수이며, 새 규칙이 실제로 안전하게 줄일 수 있는 건수의 추정치가 아닙니다. 단순 승계의 기대 효과는 부정확하므로, 법적 확인 전 적용 가능한 축소량은 0건으로 봅니다.
3. 특히 지방출자출연법 제2조의 적용대상·제외대상·출자비율 요건 및 제17조의 계약 방식, 공공기관의 운영에 관한 법률상 기관 지정, 학교·대학의 설립주체와 법인격, 자회사·부설기관의 독립 계약 주체 여부를 확인합니다. 공시자료상 기관 분류만으로 조문 적용을 결론내리지 않습니다.

이번 조사에서는 판별 코드와 운영 데이터를 변경하지 않았습니다.
