# 낙찰방법명과 실제 서비스 불일치 13건 코드 경로 추적

> **작성일**: 2026-11-07
> **대상**: [`lwlt_notice_vs_rule_audit_20261106.md`](./lwlt_notice_vs_rule_audit_20261106.md) 4.7절의 9건(화물 표기·여객 실제 6건, 대구 단순노무 3건)과 `docs/analysis/local_general_fallback_source_check_20261107.md` 3.7절의 대구 역방향 4건. 합계 13행이며 가운데 3건은 두 목록에 겹칩니다.
> **질문**: 각 건에서 규칙 선택이 어떤 입력 필드(낙찰방법명, 조달분류 `pubPrcrmnt*`, 공고명)를 근거로 이뤄졌는가. 교차 확인을 넣으면 최근 12개월 31,325건 가운데 몇 건의 판정이 바뀌는가.
> **판정**: 13행 전부의 원인 코드 줄을 확인했습니다. 화물 6건은 조달청 경로가 낙찰방법명 문자열만 보고 화물 별표를 고른 결과이고, 대구 3건은 `UNRESOLVED` 분기에서 GENERAL 후보가 없어 SIMPLE_LABOR 를 자동 확정한 결과입니다. 역방향 4건 가운데 1건은 현재 코드에서 첨부 갈래가 먼저 적용되어 SIMPLE_LABOR 경로를 타지 않습니다.
> **코드 수정**: 없음. 수정 방안의 영향 건수만 3절에 두었습니다.
> **재현**: 3절과 부록 A. DB 는 `scripts/report_rule_coverage.py` 의 READ ONLY 수집 경로만 사용했습니다.

---

## 1. 요약

규칙 선택 입력은 경로마다 다릅니다. 조달청 경로는 **낙찰방법명 하나**로 별표를 고르고, 시·도 경로는 **낙찰방법명 → 조달분류(폐기물·소프트웨어 두 표기만) → 미판정** 순으로 세부유형을 정합니다. 공고명은 세부유형을 확정하는 입력이 아니며, 추천 경고와 중소기업 경쟁제품 대상 판정, 건설폐기물 제외 조건에만 쓰입니다.

- **화물 표기 6건**: `match_rule_by_mthd_nm` 이 낙찰방법명의 `화물 육상운송용역...` 패턴을 그대로 맞춰 `SERVC_QUAL_POST_20260526_ATTACH_11`(FREIGHT, 82.495)을 골랐습니다. 조달분류 `도로여객운송서비스`와 공고명 `통학버스 임차`는 이 경로에서 읽지 않습니다.
- **대구 단순노무 3건**: `resolve_local_service_type` 이 `GENERAL`/`UNRESOLVED` 를 돌려주고, 대구에는 GENERAL 별표가 없어 `_select_local_rule` 의 `simple` 목록만 남습니다. 감사 문서가 지목한 `GENERAL + SIMPLE_LABOR` 차단 분기는 두 후보가 모두 있을 때만 작동하므로, SIMPLE_LABOR 단독 후보는 차단 없이 적용됩니다.
- **대구 역방향 4건**: 3건은 위 3건과 같은 건입니다. 나머지 1건(`R26BK01444191`)은 현재 코드에서 첨부 갈래 `MOIS_ACADEMIC` 이 먼저 적용되어 행안부 학술연구용역 규칙(80.495)으로 풀리며 SIMPLE_LABOR 를 쓰지 않습니다.

### 1.1 공고별 추적표 (13행)

| 연번 | 구분 | 공고번호 | 공고명 | 낙찰방법명 | 조달분류(`pubPrcrmnt*`) | 적용 규칙 ID | 공고값 | 규칙값 | 맞는 규칙 후보 | 원인 코드 줄 |
| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 화물 표기 | `R26BK01759197` | 2026학년도 부산글로벌빌리지 글로벌 부산 영리더 양성 프로젝트 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH`(여객 5억원이상, 89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 2 | 화물 표기 | `R26BK01759371` | 2026학년도 부산글로벌빌리지 BPS 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03`(여객 5억원미만, 89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 3 | 화물 표기 | `R26BK01773533` | 2026학년도 부산글로벌빌리지 글로벌 부산 영리더 양성 프로젝트 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH`(89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 4 | 화물 표기 | `R26BK01773629` | 2026학년도 부산글로벌빌리지 BPS 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03`(89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 5 | 화물 표기 | `R26BK01784347` | 2026학년도 부산글로벌빌리지 BPS 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03`(89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 6 | 화물 표기 | `R26BK01784422` | 2026학년도 부산글로벌빌리지 글로벌 부산 영리더 양성 프로젝트 통학버스 임차용역 입찰 공고 | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원이상 | 도로여객운송서비스 | `SERVC_QUAL_POST_20260526_ATTACH_11` | 89.995 | 82.495 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH`(89.995) | [evaluation_rules.py:3882](/src/app/services/evaluation_rules.py:3882), [evaluation_rules.py:3057-3059](/src/app/services/evaluation_rules.py:3057) |
| 7 | 대구 단순노무 | `R26BK01270603` | 대구광역시 중구 평생학습도시 조성을 위한 중장기 발전계획 연구용역 | 적격심사제-추정가격 1억미만 | 연구조사서비스 학술연구서비스 인력개발및교육연구조사서비스 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_04`(폐기물, 80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 8 | 대구 단순노무 | `R26BK01422491` | 2026년 대구광역시 지능형교통체계(ITS) 구축 사업관리 용역 | 적격심사제-추정가격 2억미만 1억이상 | 연구조사서비스 학술연구서비스 교통연구조사서비스 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_04`(80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 9 | 대구 단순노무 | `R26BK01724914` | 2026년 대구 북구 빈집정비계획 수립 용역 | 적격심사제-추정가격 1억미만 | 연구조사서비스 학술연구서비스 건설및지역개발연구조사서비스 | `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20260511_ATTACH_04`(80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 10 | 역방향(겹침 7) | `R26BK01270603` | 대구광역시 중구 평생학습도시 조성을 위한 중장기 발전계획 연구용역 | 적격심사제-추정가격 1억미만 | 연구조사서비스 학술연구서비스 인력개발및교육연구조사서비스 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_04`(80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 11 | 역방향(겹침 8) | `R26BK01422491` | 2026년 대구광역시 지능형교통체계(ITS) 구축 사업관리 용역 | 적격심사제-추정가격 2억미만 1억이상 | 연구조사서비스 학술연구서비스 교통연구조사서비스 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20220930_ATTACH_04`(80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 12 | 역방향(겹침 9) | `R26BK01724914` | 2026년 대구 북구 빈집정비계획 수립 용역 | 적격심사제-추정가격 1억미만 | 연구조사서비스 학술연구서비스 건설및지역개발연구조사서비스 | `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | 80.495 | 87.745 | `SERVC_LOCAL_DAEGU_20260511_ATTACH_04`(80.495) | [evaluation_rules.py:2103](/src/app/services/evaluation_rules.py:2103), [evaluation_rules.py:2418-2421](/src/app/services/evaluation_rules.py:2418) |
| 13 | 역방향(별건) | `R26BK01444191` | 새로공고(긴급) 2026년 대구광역시 지능형교통체계(ITS) 구축 사업관리 용역 | 적격심사제-추정가격 2억미만 1억이상 | 연구조사서비스 학술연구서비스 교통연구조사서비스 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | 80.495 | 80.495 | 같은 행안부 학술연구용역 규칙(80.495) | [evaluation_rules.py:3449-3470](/src/app/services/evaluation_rules.py:3449) |

- 1~6번은 `(주)부산글로벌빌리지`의 2개 사업(글로벌 영리더 3건, BPS 3건)을 재공고한 묶음입니다. 6건 모두 공고일이 2026-07-27 이후라 제2026-390호 벌이 적용되며, 이 벌에는 여객 5억원이상 보조 규칙과 89.995로 개정된 여객 5억원미만 규칙이 함께 있습니다.
- 7~9번은 서로 다른 3개 사업입니다. 10~12번은 7~9번과 같은 공고이며, 표에서는 겹친다는 사실을 드러내려고 다시 적었습니다. 13번은 8번(`R26BK01422491`)의 재공고입니다.
- 13번의 `적용 규칙 ID` 는 이 작업 트리에서 현재 코드로 다시 판정한 값입니다. `local_general_fallback_source_check_20261107.md` 3.7절은 이 건을 `SERVC_LOCAL_DAEGU_*_ATTACH_01`(87.745)로 적었지만, 재실행에서는 첨부 갈래가 `MOIS_ACADEMIC` 으로 잡혀 행안부 학술연구용역 규칙(80.495)이 먼저 적용됩니다. 원문 판정 라벨 (다)는 그대로 유효합니다.

---

## 2. 코드 경로

### 2.1 진입점과 입력 필드

[`resolve_evaluation_rule_from_raw_data`](/src/app/services/evaluation_rules.py:3937)는 `raw_data` 에서 낙찰방법명(`sucsfbidMthdNm`), 낙찰방법 코드(`sucsfbidMthdCd`), 공고 하한율(`sucsfbidLwltRate`), 공고일(`bidNtceDt`), 수요기관 코드·명, 공고기관 코드·명을 꺼내 [`resolve_evaluation_rule`](/src/app/services/evaluation_rules.py:3320)로 넘깁니다. 이 함수는 `raw_data` 전체를 그대로 전달하지만, 조달분류 `pubPrcrmnt*` 를 직접 꺼내 판정에 쓰는 곳은 시·도 경로의 두 표기뿐입니다.

[`resolve_method_name`](/src/app/services/evaluation_rules.py:3082)은 낙찰방법명이 비어 있거나 `공고서참조` 일 때만 낙찰방법 코드의 계열명으로 대체합니다. 그 밖에는 공고 원문 낙찰방법명이 그대로 판정 문자열이 됩니다.

조달청 경로는 [`_resolve_by_method_name`](/src/app/services/evaluation_rules.py:3717)의 [`:3882`](/src/app/services/evaluation_rules.py:3882)에서 [`match_rule_by_mthd_nm`](/src/app/services/evaluation_rules.py:3032)을 호출합니다. 이 함수는 정규화한 낙찰방법명 문자열 안에서 등록 패턴을 찾고, 패턴이 긴 규칙부터 먼저 반환합니다([`:3057-3059`](/src/app/services/evaluation_rules.py:3057)). **조달분류와 공고명은 인자로 받지도 않습니다.**

시·도 경로는 [`_select_local_rule`](/src/app/services/evaluation_rules.py:2272)이 맡습니다. 세부유형은 [`resolve_local_service_type`](/src/app/services/evaluation_rules.py:2084)이 정합니다.

1. 낙찰방법명에 `단순노무` 가 있으면 `SIMPLE_LABOR`([`:2093-2094`](/src/app/services/evaluation_rules.py:2093)).
2. 낙찰방법명의 표식(`폐기물`, `시설분야`, `보험`, `육상운송`, `여객`, `화물`, `소프트웨어`, `수리ㆍ점검`, `임대차`, `수요기관 지정형`, `학술연구`, `어장`)을 순서대로 찾습니다([`:2054-2069`](/src/app/services/evaluation_rules.py:2054), [`:2095-2097`](/src/app/services/evaluation_rules.py:2095)). `여객` 과 `화물` 은 둘 다 `LAND_TRANSPORT` 로 매핑되어 **시·도 경로에서도 두 표기를 구분하지 않습니다**([`:2060-2061`](/src/app/services/evaluation_rules.py:2060)).
3. 조달분류 네 필드를 이어 붙인 문자열에서 `폐기물` → `WASTE`, `소프트웨어` → `SW` 두 표기만 찾습니다([`:2070-2073`](/src/app/services/evaluation_rules.py:2070), [`:2099-2102`](/src/app/services/evaluation_rules.py:2099)).
4. 아무것도 걸리지 않으면 `("GENERAL", "UNRESOLVED", 사유)` 를 돌려줍니다([`:2103`](/src/app/services/evaluation_rules.py:2103)).

공고명은 [`_recommend_local_service_type`](/src/app/services/evaluation_rules.py:2106)에서 추천 경고 문자열을 만들 때만 읽습니다([`:2111-2124`](/src/app/services/evaluation_rules.py:2111)). 그 밖에 공고명이 판정에 관여하는 곳은 중소기업자간 경쟁제품 대상/비대상 판정([`:2429-2449`](/src/app/services/evaluation_rules.py:2429), [`_classify_sme_competition`](/src/app/services/evaluation_rules.py:2138))과 건설폐기물 제외 조건(`named`, `named_except_haul`)입니다([`:2357-2385`](/src/app/services/evaluation_rules.py:2357)).

### 2.2 화물 표기 6건: 낙찰방법명만 보고 화물 별표를 고른다

6건의 낙찰방법명은 모두 `적격심사제-화물 육상운송용역 적격심사 추정가격 ...` 입니다. [`_resolve_by_method_name`](/src/app/services/evaluation_rules.py:3717)은 [`:3882`](/src/app/services/evaluation_rules.py:3882)에서 낙찰방법명으로 별표를 찾고, [`match_rule_by_mthd_nm`](/src/app/services/evaluation_rules.py:3032)은 화물 패턴([`:940-947`](/src/app/services/evaluation_rules.py:940))을 여객 패턴보다 먼저 맞춥니다. 그 결과 `SERVC_QUAL_POST_20260526_ATTACH_11`(고시금액 이상, 82.495)이 확정됩니다.

조달분류 `도로여객운송서비스`는 이 경로에서 읽히지 않습니다. 조달분류가 쓰이는 시·도 경로도 `contract_regime == "LOCAL"` 일 때만 진입하는데([`:3502-3516`](/src/app/services/evaluation_rules.py:3502)), 6건의 계약 체제는 판정값이 `None`(미상)이라 이 분기에 들어가지 않습니다. 설령 시·도 경로로 갔다 해도 `화물` 표식이 `LAND_TRANSPORT` 로 먼저 걸려 여객을 되찾지 못합니다.

공고값 89.995는 규칙값 82.495보다 우선 적용됩니다([`_apply_rule_lwlt`](/src/app/services/evaluation_rules.py:2615), [`:2628-2636`](/src/app/services/evaluation_rules.py:2628)). 그래서 화면의 하한율은 89.995로 맞지만, 규칙 ID와 경고 문구는 화물 별표를 가리킨 채 남습니다. 6건의 경고에는 `공고 하한율(89.995%)이 별표 기본값(82.495%)과 일치하지 않아 공고 하한율을 우선 적용합니다.` 가 붙습니다.

### 2.3 대구 단순노무 3건: GENERAL 후보가 없을 때 SIMPLE_LABOR 를 자동 확정

3건의 낙찰방법명은 `적격심사제-추정가격 1억미만` 또는 `... 2억미만 1억이상` 으로, 세부유형 표기가 없습니다. 조달분류는 `연구조사서비스`·`학술연구서비스` 계열이라 `폐기물`·`소프트웨어` 표식에도 걸리지 않습니다. 따라서 [`resolve_local_service_type`](/src/app/services/evaluation_rules.py:2084)은 [`:2103`](/src/app/services/evaluation_rules.py:2103)에서 `("GENERAL", "UNRESOLVED", 사유)` 를 돌려줍니다.

[`_select_local_rule`](/src/app/services/evaluation_rules.py:2272)은 이 값을 받아 [`:2399`](/src/app/services/evaluation_rules.py:2399)의 미판정 분기로 들어갑니다. 대구광역시 시·도 규칙에는 GENERAL 별표가 없습니다. 등록된 대구 규칙은 단순노무 별표 1(2022 구판·2026 현행)과 폐기물 별표 4(2022 구판·2026 현행)뿐입니다([`evaluation_rules_local.py:1632-1693`](/src/app/services/evaluation_rules_local.py:1632), [`evaluation_rules_local.py:2158-2184`](/src/app/services/evaluation_rules_local.py:2158)). 따라서 `general` 목록은 비고 `simple` 목록만 남습니다.

- `general` 과 `simple` 이 **둘 다** 있으면 후보를 경고로 남기고 `LOCAL_SERVICE_TYPE_UNRESOLVED` 로 차단합니다([`:2402-2417`](/src/app/services/evaluation_rules.py:2402)).
- `general` 만 있으면 GENERAL 을 적용합니다([`:2418-2419`](/src/app/services/evaluation_rules.py:2418)).
- `simple` 만 있으면 **차단하지 않고** SIMPLE_LABOR 를 적용합니다([`:2420-2421`](/src/app/services/evaluation_rules.py:2420)).

대구 3건은 세 번째 분기입니다. 감사 문서의 표현대로 "차단 경로를 우회한" 것이 아니라, 차단 조건이 `general and simple` 일 때만 성립하도록 구현되어 있어 단독 SIMPLE_LABOR 후보가 자동 확정됩니다. 적용 뒤에는 `_apply_rule_lwlt` 가 공고값 80.495를 우선 적용하고, 규칙 대표값 87.745와 다르다는 경고만 남깁니다.

감사 문서 4.7절이 지목한 줄 `2330-2355` 는 병합 과정에서 밀렸습니다. 현재 대응 위치는 시·도 세부유형 미판정 분기 `2399-2425` 이며, 위 세 분기의 조건은 변하지 않았습니다.

공고값 80.495가 대구 폐기물 별표 4 값과 같은 것은 사실이지만, 조달분류가 연구조사서비스라 폐기물 표식에 걸리지 않습니다. 코드가 폐기물 별표를 고른 것이 아니라, 값이 우연히 같은 것입니다.

### 2.4 역방향 4건: 3건은 2.3절, 1건은 첨부 갈래가 먼저 가로챈다

10~12번은 7~9번과 같은 공고이므로 경로도 같습니다. 13번(`R26BK01444191`)만 다릅니다.

13번은 낙찰방법명이 `적격심사제-추정가격 2억미만 1억이상` 이고 첨부 판별 갈래가 `MOIS_ACADEMIC` 입니다. [`resolve_evaluation_rule`](/src/app/services/evaluation_rules.py:3320)은 시·도 분기([`:3502`](/src/app/services/evaluation_rules.py:3502))보다 먼저 첨부 갈래 분기([`:3449-3470`](/src/app/services/evaluation_rules.py:3449))를 봅니다. 조건은 네 가지입니다.

1. `attachment_regime` 이 `MOIS_ACADEMIC` 또는 `MOIS_TECH`.
2. 낙찰방법명에 `2억미만` 과 `1억이상` 이 모두 있음([`:1897`](/src/app/services/evaluation_rules.py:1897), [`:3451`](/src/app/services/evaluation_rules.py:3451)).
3. 국가계약(`NATIONAL`)이 아님. 대구광역시는 LOCAL 입니다.
4. 조달청 매칭 결과가 차단이고, 그 코드가 첨부 갈래 구제 대상임([`:3454`](/src/app/services/evaluation_rules.py:3454)).

네 조건이 맞아 행안부 예규 제2장의2 [별표 4] 학술연구용역 2억미만 1억이상 규칙(80.495)이 적용됩니다([`:1947-1964`](/src/app/services/evaluation_rules.py:1947)). 이 규칙의 값이 공고값 80.495와 같아 불일치가 사라집니다. 즉 13번은 현재 코드에서 SIMPLE_LABOR 자동 확정 사례가 아닙니다.

`local_general_fallback_source_check_20261107.md` 3.7절이 이 건을 `SERVC_LOCAL_DAEGU_*_ATTACH_01`(87.745)로 적은 것은 그 조사 시점의 첨부 갈래 판정 결과입니다. 같은 문서 부록 B도 "재실행 시 첨부 갈래 판정이 달라져 폴백 목록에 잡히지 않는다"고 밝히고 있어, 표의 4건과 현재 코드의 3건은 모순이 아니라 판정 시점 차이입니다.

---

## 3. 교차 확인 방안 비교

### 3.1 측정 조건

- 창: 2026-11-07 기준 최근 12개월(2025-11-07 이상 2026-11-08 미만), 업무구분 `Servc`, 낙찰방법 코드 `낙030001`.
- 대표 공고: `(bid_ntce_no, category)` 별 최신 `bid_ntce_ord`.
- 건수: **31,325건**. 이 가운데 규칙 적용 21,590건, 차단 9,735건. 공고값과 규칙 인쇄값을 비교할 수 있는 적용 건의 불일치는 1,142건입니다.
- 규칙값은 규칙에 인쇄된 구간 하한율이 있으면 그 값, 없으면 규칙 대표값입니다. 공고값 우선 적용 뒤의 `effective_lwlt_rate` 가 아니라 **규칙이 선언한 값**과 비교했습니다.
- 측정은 메모리에서만 했습니다. 코드, 규칙 값, DB, 마이그레이션을 바꾸지 않았습니다.

감사 문서의 21,546건·1,184건과 숫자가 조금 다른 것은 낙찰방법 코드 필터 유무와 기준일(2026-11-06 대 2026-11-07) 차이입니다.

### 3.2 방안별 영향

| 방안 | 내용 | 판정 변경 | 그중 공고값과 일치 | 그중 차단 | 그중 여전히 불일치 |
| --- | --- | ---: | ---: | ---: | ---: |
| (가) 조달분류로 화물/여객 교정 | 낙찰방법명에 `화물`, 조달분류에 `여객` 이 있으면 낙찰방법명을 여객으로 바꿔 재판정 | 13 | 6 | 5 | 2 |
| (가-반대) 여객/화물 역방향 교정 | 낙찰방법명에 `여객`, 조달분류에 `화물` 이면 화물로 바꿔 재판정 | 3 | 0 | 3 | 0 |
| (나) SIMPLE_LABOR 확정 경로 차단 | 시·도 세부유형 `UNRESOLVED` 이고 GENERAL 후보가 없으며 SIMPLE_LABOR 만 있으면 차단 | 3 | 0 | 3 | 0 |
| 합계 (가)+(나) | 위 두 방안을 함께 적용 | 16 | 6 | 8 | 2 |

### 3.3 (가) 조달분류로 화물/여객 교정

낙찰방법명에 `화물`, 조달분류에 `여객` 이 함께 나오는 공고는 31,325건 중 13건입니다. 13건 모두 규칙 ID가 바뀝니다.

- **6건이 공고값과 일치하게 됩니다**: 1~6번입니다. 여객 5억원이상 보조 규칙(`SERVC_QUAL_POST_20260727_ATTACH_03_HIGH`) 또는 여객 5억원미만 규칙(`SERVC_QUAL_POST_20260727_ATTACH_03`)의 인쇄값이 89.995라 공고값과 같습니다.
- **2건은 규칙이 바뀌어도 불일치가 남습니다**: `R26BK01270968`(공고값 80.495, 여객 규칙 87.995), `R26BK01323038`(공고값 87.745, 여객 규칙 87.995). 앞의 1건은 교정 전에 화물 규칙값 80.495와 공고값이 일치했는데, 교정 뒤에는 87.995와 어긋나 **새 불일치가 생깁니다**. 뒤의 1건은 교정 전에도 불일치였고 교정 뒤에도 남습니다.
- **5건은 차단됩니다**: `R26BK01344845`, `R26BK01348950`, `R26BK01365102`, `R26BK01367374`, `R26BK01372328`. 교정된 이름이 `여객 육상운송용역 적격심사 추정가격 고시금액미만` 인데, 여객 규칙에는 `고시금액미만` 패턴이 없습니다. 이 5건은 규칙 공백 때문에 차단으로 바뀝니다.

따라서 (가)의 순효과는 "13건 판정 변경, 6건 공고값 일치, 5건 신규 차단, 2건 잔여 불일치"입니다. 감사 문서 4.7절의 화물 6건만 놓고 보면 6건 모두 해소됩니다. 다만 교차 확인을 넣으면 감사 문서 4.7절이 지목하지 않은 7건도 함께 판정이 바뀌고, 그중 1건은 오히려 새 불일치가 생깁니다.

역방향(낙찰방법명 `여객`, 조달분류 `화물`)은 3건입니다. 3건 모두 교정된 화물 이름이 등록 패턴과 맞지 않아 차단됩니다. 이 방향은 감사 문서의 13건에 없던 부수 사례이며, 교차 확인을 넣을 때 함께 고려해야 할 영향입니다.

### 3.4 (나) SIMPLE_LABOR 확정 경로 차단

시·도 세부유형이 `UNRESOLVED` 이고 GENERAL 후보가 없으며 SIMPLE_LABOR 만 있어 자동 적용된 건은 3건입니다. 10~12번(7~9번)과 같습니다. 3건 모두 규칙 인쇄값 87.745와 공고값 80.495가 달랐으므로, 차단으로 바뀌면 잘못된 규칙값이 노출되지는 않습니다. 다만 차단된 공고는 사용자가 용역 세부유형을 선택하기 전까지 계산할 수 없습니다.

방안 (나)는 "공고값과 일치하게 되는 건수"가 0입니다. 차단은 규칙값을 만들지 않기 때문입니다. 대신 기준 불일치 3건이 계산 불가로 바뀝니다. 이 3건은 모두 공고값 80.495가 대구 폐기물 별표 4 값과 같아, 폐기물 별표를 의도한 공고였다면 사용자 선택으로 복구할 수 있습니다.

### 3.5 해석

- (가)는 **공고값 우선 원칙 때문에 현재 점수 계산을 바꾸지 않습니다**. 바뀌는 것은 적용 규칙 ID, 규칙 기본값, 경고 문구입니다. (나)는 규칙 선택 자체를 막으므로 점수를 산출할 수 있는지가 바뀝니다.
- (가)는 화물 6건을 정확히 해소하지만, 규칙 공백 5건을 새 차단으로 만듭니다. 차단을 늘리지 않으려면 여객 `고시금액미만` 규칙을 함께 등록해야 합니다.
- (나)는 대구 3건만 다룹니다. 역방향 4건 가운데 13번은 첨부 갈래가 먼저 적용되어 이 방안의 영향을 받지 않습니다.
- (가)와 (나)의 대상은 겹치지 않아 합계 16건입니다. 역방향 교정까지 넣으면 19건입니다.

---

## 4. 사용자 결정 항목

| 항목 | 선택지 | 이번 조사에서 확인한 사실 |
| --- | --- | --- |
| 화물/여객 충돌 시 우선순위 | (A) 현행처럼 낙찰방법명만 신뢰, (B) 조달분류와 교차 확인, (C) 불일치 시 차단 | (B)면 13건 판정 변경, 6건 공고값 일치, 5건 신규 차단, 2건 잔여 불일치. (C)면 13건 전부 차단 |
| 여객 `고시금액미만` 규칙 공백 | (A) 차단 유지, (B) 여객 규칙 추가, (C) 다른 구간 규칙으로 근사 | (가)를 넣으면 5건이 이 공백 때문에 차단됩니다. 조달청 여객 규칙에는 `5억원미만`과 `5억원이상`만 있습니다 |
| 시·도 `UNRESOLVED` + SIMPLE_LABOR 단독 | (A) 현행 자동 확정 유지, (B) 차단, (C) GENERAL 부재를 경고로 노출 | (B)면 대구 3건이 차단됩니다. 3건 모두 공고값 80.495가 폐기물 별표 값과 같습니다 |
| 역방향 교정 포함 여부 | (A) 화물→여객만, (B) 양방향 | 양방향이면 추가 3건이 차단됩니다. 이 3건은 감사 문서 13건에 없습니다 |
| 13번(`R26BK01444191`) 기준 상태 | (A) 현재 코드의 첨부 갈래 적용을 정본으로, (B) 이전 조사표의 SIMPLE_LABOR 적용을 정본으로 | 현재 코드는 행안부 학술연구용역 80.495를 적용해 공고값과 일치합니다. 이전 표는 87.745였습니다 |
| 교차 확인 범위 | (A) 조달청 경로만, (B) 시·도 경로까지 | 시·도 경로는 `화물`·`여객` 을 모두 `LAND_TRANSPORT` 로 매핑해 두 표기를 구분하지 않습니다([`:2060-2061`](/src/app/services/evaluation_rules.py:2060)) |

이 문서는 어느 선택지도 확정하지 않습니다. 기존 사용자 결정(조달청 대행 배제, 시행일 불일치 차단 유지, 전남만 조달청 준용, 산림청 미등록)은 뒤집지 않았습니다.

---

## 부록 A. 재현

### A.1 수집 경로

`scripts/report_rule_coverage.py` 의 `ANNOUNCEMENT_SQL`, `_load_institutions`, `lookup_attachment_regimes`, `_to_record` 를 그대로 재사용했습니다. `SET SESSION TRANSACTION READ ONLY` 세션에서 SELECT 만 실행했고, `raw_data LIKE` 전체 스캔과 컨테이너 런타임·DB 클라이언트 직접 호출은 쓰지 않았습니다.

```python
items = collect_rows(months=12, category="Servc", method_code="낙030001", today=date(2026, 11, 7))
# records 31325
# baseline: applied 21590, blocked 9735, notice vs declared mismatch 1142
```

### A.2 교차 확인 측정

```python
# (가) 낙찰방법명에 '화물', 조달분류에 '여객' 이면 낙찰방법명의 '화물' 을 '여객' 으로 바꿔
#     resolve_evaluation_rule_from_raw_data 를 다시 호출하고 규칙 ID·인쇄값을 비교했다.
# (나) 적용 규칙이 REGION/SIMPLE_LABOR 이고 resolve_local_service_type 이 UNRESOLVED 이면
#     _select_local_rule 의 simple 단독 적용 분기(2418-2421)를 탄 것으로 보고 차단으로 셌다.
```

측정 결과는 3.2절 표와 같습니다. 규칙 인쇄값은 `_band_lwlt_rate` 가 구간값을 돌려주면 그 값, 아니면 `rule.lwlt_rate` 를 썼습니다.

### A.3 대상 13행 확인

1~9번은 수집 결과에서 적용 규칙 ID 로 직접 골랐습니다. 6건은 `SERVC_QUAL_POST_20260526_ATTACH_11`, 3건은 `SERVC_LOCAL_DAEGU_*_ATTACH_01` 입니다. 10~12번은 7~9번과 같은 공고번호입니다. 13번은 `bid_announcements` 에서 공고번호로 직접 읽었습니다.

```sh
uv run python scripts/db_readonly_query.py --sql "SELECT bid_ntce_no, bid_ntce_ord, bid_ntce_dt, dminstt_nm, cntrct_mthd_nm, presmpt_prce, raw_data FROM bid_announcements WHERE bid_ntce_no = 'R26BK01444191'" --format json
```

---

## 부록 B. 한계

1. **원문 미대조**: 낙찰방법명과 조달분류 중 어느 쪽이 실제 서비스와 맞는지는 이번에도 공고 원문으로 확정하지 않았습니다. 이 문서는 코드가 어떤 필드를 읽었는지만 확정합니다.
2. **교차 확인 측정의 근사**: (가)는 낙찰방법명 문자열의 `화물` 을 `여객` 으로 치환해 재판정하는 방식입니다. 실제 구현에서 우선순위나 예외를 어떻게 두느냐에 따라 13건 밖의 판정이 달라질 수 있습니다.
3. **기준 상태 차이**: 13번은 `local_general_fallback_source_check_20261107.md` 의 표와 현재 코드의 첨부 갈래 판정이 다릅니다. 표의 4건과 현재 코드의 3건을 함께 적었습니다.
4. **출처 문서 위치**: `docs/analysis/local_general_fallback_source_check_20261107.md` 는 `main` 에는 있으나 이 작업 브랜치(`kwanbum217/method-name`)에는 병합되어 있지 않습니다. 이 문서는 커밋 `40b54666` 의 객체로 읽었습니다.
5. **공고값 우선**: 31,325건 모두 공고 하한율이 있어 실제 점수는 공고값으로 계산됩니다. 3절의 "공고값과 일치"는 규칙 ID 선택의 정합성 판정이며 점수 변화가 아닙니다.
6. **건수 차이**: 이 조사의 기준 불일치 1,142건은 감사 문서의 1,184건과 다릅니다. 낙찰방법 코드 필터, 기준일, 규칙 인쇄값 비교 방식 차이입니다.
