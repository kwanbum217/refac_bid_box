# 수요기관 계약 법령 미상 범주 조사

> 작성일: 2026-10-03
> 대상: 2025-01-01 이후 공고일 기준 `Servc` 용역 공고
> 판정 기준: `raw_data.dminsttCd`로 `g2b_demand_institutions`를 연결하고 `classify_contract_regime`의 기존 규칙을 적용

## 요약

읽기 전용 DB 조회 결과 대상 공고는 373,825건이었고, 현재 분포는 LOCAL 177,050건(47.36%), NATIONAL 85,216건(22.80%), 미상 111,559건(29.84%)입니다. 기존 미상 판정에 대한 법령 검토로 특정 기관 범주 전체를 올릴 수 있는 새 규칙은 확인하지 못했습니다. 따라서 코드는 변경하지 않았으며 적용 전후 분포는 동일하고 기존 LOCAL/NATIONAL 판정 변경도 0건입니다.

기관 데이터의 소관구분·대분류·중분류만으로는 설립 법인, 계약 주체, 개별 법률의 적용 여부를 모두 식별하지 못합니다. 추정 규칙 대신 해당 범주는 미상으로 유지합니다.

## 재현 가능한 DB 질의

아래 질의는 미상 공고를 소관구분·대분류·중분류 조합 및 기관 행 미수집으로 분해하고 건수 상위 40개를 출력합니다. 동일 질의는 운영 DB를 변경하지 않습니다.

```sql
WITH bids AS (
    SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.dminsttCd')) AS dminstt_cd,
           COUNT(*) AS n
    FROM bid_announcements
    WHERE bid_ntce_dt >= '2025-01-01' AND category = 'Servc'
    GROUP BY 1
)
SELECT CASE WHEN di.dminstt_cd IS NULL THEN '미수집'
            ELSE COALESCE(NULLIF(TRIM(di.jrsdctn_div_nm), ''), '(소관구분 없음)') END AS jrsdctn_div_nm,
       CASE WHEN di.dminstt_cd IS NULL THEN '(기관 행 없음)'
            ELSE COALESCE(NULLIF(TRIM(di.instt_ty_lrgclsfc_nm), ''), '(대분류 없음)') END AS instt_ty_lrgclsfc_nm,
       CASE WHEN di.dminstt_cd IS NULL THEN '(기관 행 없음)'
            ELSE COALESCE(NULLIF(TRIM(di.instt_ty_midclsfc_nm), ''), '(중분류 없음)') END AS instt_ty_midclsfc_nm,
       SUM(b.n) AS announcement_count
FROM bids b
LEFT JOIN g2b_demand_institutions di ON di.dminstt_cd = b.dminstt_cd
WHERE di.dminstt_cd IS NULL
   OR ((TRIM(di.instt_ty_lrgclsfc_nm) <> '교육행정조직'
        OR TRIM(di.instt_ty_midclsfc_nm) NOT IN ('시, 도교육청', '지역교육청', '시, 도교육청 직속기관')
        OR di.instt_ty_midclsfc_nm IS NULL)
       AND COALESCE(TRIM(di.jrsdctn_div_nm), '') NOT IN ('지방자치단체', '지방공기업')
       AND (TRIM(di.instt_ty_lrgclsfc_nm) NOT IN ('초등학교', '중학교', '고등학교', '특수학교', '유치원')
            OR TRIM(di.instt_ty_smlclsfc_nm) <> '공립'
            OR di.instt_ty_smlclsfc_nm IS NULL)
       AND COALESCE(TRIM(di.jrsdctn_div_nm), '') NOT IN ('국가기관', '공기업', '준정부기관', '정부투자기관'))
GROUP BY 1, 2, 3
ORDER BY announcement_count DESC
LIMIT 40
```

재실행 명령은 다음과 같습니다.

```sh
uv run python scripts/db_readonly_query.py --sql "<위 SQL>" --limit 40 --format json
```

## 미상 공고 수 상위 범주

| 순위 | 소관구분 | 대분류 | 중분류 | 공고 수 |
| ---: | --- | --- | --- | ---: |
| 1 | 기타기관 | 없음 | 없음 | 19,373 |
| 2 | 교육기관 | 고등교육기관 | 4년제 정규대학 | 8,174 |
| 3 | 기타기관 | 산하기관 | 기타 | 7,252 |
| 4 | 기타공공기관 | 산하기관 | 정부출연기관 | 7,031 |
| 5 | 기타기관 | 산하기관 | 정부출연기관 | 6,448 |
| 6 | 기타공공기관 | 산하기관 | 기타 | 5,802 |
| 7 | 기타기관 | 정부투자기관및기타 | 기타 | 5,591 |
| 8 | 기타공공기관 | 없음 | 없음 | 3,939 |
| 9 | 기타기관 | 고등학교 | 일반계 고등학교 | 3,482 |
| 10 | 기타공공기관 | 산하기관 | 정부보조기관 | 3,161 |
| 11 | 기타기관 | 고등교육기관 | 4년제 정규대학 | 2,963 |
| 12 | 지자체 출자출연기관 | 없음 | 없음 | 2,434 |
| 13 | 지자체 출자출연기관 | 산하기관 | 정부출연기관 | 2,223 |
| 14 | 교육기관 | 초등학교 | 초등학교(본교) | 2,128 |
| 15 | 미수집 | 기관 행 없음 | 기관 행 없음 | 2,043 |
| 16 | 기타기관 | 산하기관 | 없음 | 1,943 |
| 17 | 기타공공기관 | 정부투자기관및기타 | 기타 | 1,781 |
| 18 | 지자체 출자출연기관 | 산하기관 | 기타 | 1,779 |
| 19 | 기타기관 | 중학교 | 중학교(본교) | 1,495 |
| 20 | 교육기관 | 고등교육기관 | 전문대학 | 1,409 |

`없음`은 해당 분류 컬럼이 NULL 또는 공백인 경우입니다. 미수집 2,043건은 수요기관 코드로 연결되는 기관 기준정보 행이 없습니다. 상위 범주는 합쳐서 미상 전체 111,559건을 설명하지 않으며, 나머지 범주는 위 재현 질의의 나머지 결과 행에서 확인할 수 있습니다.

## 범주별 법령 검토 및 판정

| 미상 범주 | 법령·조문과 검토 결과 | 결론 및 반례 |
| --- | --- | --- |
| 지자체 출자출연기관 | [지방자치단체 출자·출연 기관의 운영에 관한 법률 제17조제3항~제5항](https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1032108809)은 기관의 계약 방식을 직접 정합니다. 다만 같은 법 제2조제2항은 지방공기업, 공공기관운영법상 지정 공공기관 등 적용 제외를 두고, 제2조제3항은 지분 50% 미만 출자기관에 제17조 등을 적용하지 않습니다. | `jrsdctn_div_nm` 하나로는 법 제2조의 적용·제외 여부를 식별할 수 없어 None. 같은 소관값의 일부는 법 제2조제2항 또는 제3항에 따라 제17조 적용 대상이 아닙니다. 개별 설립·지분 근거 확인 없이 LOCAL로 올릴 수 없습니다. |
| 기타공공기관, 정부출연기관·정부보조기관 | [공공기관의 운영에 관한 법률 제39조](https://www.law.go.kr/lsLawLinkInfo.do?lsJoLnkSeq=1032878665)는 계약 관련 제재를 공기업·준정부기관에 규정하지만 기타공공기관 일반의 계약 법령을 확정하지 않습니다. 기타공공기관에는 개별 설립법과 자체 규정이 다를 수 있습니다. | None. 같은 `기타공공기관` 표지 안에서 개별 설립법·계약규정 차이를 대분류·중분류가 나타내지 않습니다. 공기업·준정부기관으로 이미 분류된 기관과 기타공공기관도 같은 범주로 취급할 수 없습니다. |
| 기타기관·산하기관·정부출연기관 또는 기타 | 설립 근거에 따라 지방자치단체 출연기관, 국가·지방 공공기관의 자회사, 민간 법인 등이 섞일 수 있습니다. [지방출자출연법 제2조·제17조](https://www.law.go.kr/lsInfoP.do?lsiSeq=288619)는 모든 산하기관이나 정부출연기관을 일괄 포괄하지 않습니다. | None. 같은 분류 조합에서 출연·투자기관 자회사 및 법 적용대상이 아닌 기관이 반례가 됩니다. 기관명이나 분류 소분류로 추정하지 않습니다. |
| 교육기관·고등교육기관(대학·전문대학) | [고등교육법](https://www.law.go.kr/법령/고등교육법)은 대학 종류와 설립주체를 구별하지만, 이 기관유형 조합만으로 계약 주체와 적용 계약법을 확정하지 못합니다. 공립·사립 법인 대학, 국립대학법인 등 서로 다른 설립 형태가 포함될 수 있습니다. | None. 사립대학과 국립대학법인은 지방계약 주체라고 볼 수 없고, 기관 분류에는 법인격·재원·개별 계약 규정이 없습니다. |
| 교육기관·초등학교/중학교/고등학교 | [초·중등교육법 제3조](https://law.go.kr/LSW/lsInfoP.do?ancYnChk=0&chrClsCd=010202&efYd=20250621&lsiSeq=267355&urlMode=lsInfoP)는 국립·공립·사립 학교를 설립주체에 따라 나눕니다. 그러나 실측 분류 소분류에는 사립 가톨릭관동대학교가 `국립`, 공립 서울정목초등학교가 `국립`으로 기록되는 오염이 이미 확인되었습니다. | None. 공립·국립·사립을 실제 설립주체의 대용값인 소분류만으로 판정하면 오분류합니다. 공립 초·중·고·특수학교·유치원의 확정 기존 규칙 외에는 확대하지 않습니다. |
| 기타기관·기타공공기관의 대분류/중분류 없음 | 기관 행은 있지만 현재 메타데이터에 법령 적용 주체를 식별할 수 있는 분류값이 없습니다. | None. 누락 필드만으로는 적용 법령이나 계약 주체를 확인할 수 없습니다. |
| 미수집 | `dminsttCd`와 일치하는 `g2b_demand_institutions` 행이 없습니다. | None. 계약 주체의 법령 근거를 확인할 기관 기준정보 자체가 없습니다. |

위 표의 사례는 범주 단위로 판정할 수 없는 반례를 제시합니다. 개별 기관에 대한 법령 적용을 판별하려면 설립 법령, 법인격, 출자·출연 비율, 기관 지정 여부 등 별도 근거가 필요하며 현재 판별 함수 입력만으로 그 사실을 복원할 수 없습니다.

## 적용 전후 분포와 변경 확인

아래 값은 동일 조건(`bid_ntce_dt >= '2025-01-01'`, `category = 'Servc'`)으로 다시 계산했습니다. 코드 규칙을 추가하지 않았으므로 전후 수치가 같습니다.

| 구분 | LOCAL | NATIONAL | None | 합계 |
| --- | ---: | ---: | ---: | ---: |
| 적용 전 | 177,050 (47.36%) | 85,216 (22.80%) | 111,559 (29.84%) | 373,825 |
| 적용 후 | 177,050 (47.36%) | 85,216 (22.80%) | 111,559 (29.84%) | 373,825 |

아래 집계는 위와 같은 날짜·용역 조건에서 수요기관 코드별 공고 수를 만든 뒤 기존 분류 규칙을 적용합니다. 신규 규칙이 없으므로 이 값이 적용 전후에 공통으로 재현됩니다.

```sql
WITH bids AS (
    SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.dminsttCd')) AS dminstt_cd,
           COUNT(*) AS n
    FROM bid_announcements
    WHERE bid_ntce_dt >= '2025-01-01' AND category = 'Servc'
    GROUP BY 1
), regimes AS (
    SELECT b.n,
           CASE
             WHEN di.dminstt_cd IS NULL THEN NULL
             WHEN TRIM(di.instt_ty_lrgclsfc_nm) = '교육행정조직'
              AND TRIM(di.instt_ty_midclsfc_nm) IN ('시, 도교육청', '지역교육청', '시, 도교육청 직속기관') THEN 'LOCAL'
             WHEN TRIM(di.jrsdctn_div_nm) IN ('지방자치단체', '지방공기업') THEN 'LOCAL'
             WHEN TRIM(di.instt_ty_lrgclsfc_nm) IN ('초등학교', '중학교', '고등학교', '특수학교', '유치원')
              AND TRIM(di.instt_ty_smlclsfc_nm) = '공립' THEN 'LOCAL'
             WHEN TRIM(di.jrsdctn_div_nm) IN ('국가기관', '공기업', '준정부기관', '정부투자기관') THEN 'NATIONAL'
             ELSE NULL
           END AS regime
    FROM bids b
    LEFT JOIN g2b_demand_institutions di ON di.dminstt_cd = b.dminstt_cd
)
SELECT COALESCE(regime, 'None') AS regime,
       SUM(n) AS announcement_count,
       ROUND(SUM(n) * 100.0 / (SELECT SUM(n) FROM bids), 2) AS pct
FROM regimes
GROUP BY regime
ORDER BY regime
```

재실행 명령은 다음과 같습니다.

```sh
uv run python scripts/db_readonly_query.py --sql "<위 SQL>" --limit 10 --format json
```

추가 규칙이 없어 기존 결과를 바꿀 실행 분기도 없습니다. 판정 변경 수는 LOCAL→NATIONAL, LOCAL→None, NATIONAL→LOCAL, NATIONAL→None 합계 0건입니다. 상위 미상 범주에 법령 표지가 일부 있더라도 적용 제외와 예외를 분류 필드로 판별할 수 없으므로 정확성 기준을 우선해 미상 비율을 그대로 둡니다.

## 출처

- [지방자치단체 출자·출연 기관의 운영에 관한 법률 제2조·제17조](https://www.law.go.kr/lsInfoP.do?lsiSeq=288619)
- [공공기관의 운영에 관한 법률 제39조](https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1032878665)
- [고등교육법](https://www.law.go.kr/법령/고등교육법)
- [초·중등교육법 제3조](https://law.go.kr/LSW/lsInfoP.do?ancYnChk=0&chrClsCd=010202&efYd=20250621&lsiSeq=267355&urlMode=lsInfoP)
