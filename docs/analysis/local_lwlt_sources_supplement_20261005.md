# LOCAL 규칙 낙찰하한율 원문 근거 보강 조사 (인천·제주·강원·경북·경남·경기 보험·서울)

> **작성일**: 2026-10-05
> **작업**: Orca `task_8f7988ff9b58` (run `run_c6cbadfe4a2b`), 브랜치 `kwanbum217/z2-local-lwlt-src`
> **범위**: 별표 원문에 낙찰하한율이 인쇄되지 않아 값을 고치지 못한 7개 대상, 규칙 14개
> **대상 규칙**: 인천 2, 제주 2, 강원 2, 경북 4, 경남 1, 경기 보험 1, 서울 2
> **정본 사양**: `.orca/capsules/task_z2_local_lwlt_sources/capsule.yaml`
> **관련 코드**: `src/app/services/evaluation_rules.py` (`_local_rule`, `_LOCAL_LWLT_BY_SERVICE`)
> **관련 문서**: `docs/analysis/local_lwlt_audit_20261005.md`, `docs/analysis/servc_formula_collection_local_20261004.md`
> **결론**: 7개 대상 14개 규칙 모두 시·도 자치법규 원문 어디에도 낙찰하한율이 인쇄되지 않아 **미확인**입니다. 코드 값은 무변경(서비스 유형별 기본값 유지)합니다.

---

## 1. 요약

| 항목 | 수 | 내용 |
| --- | ---: | --- |
| 조사 대상 규칙 | 14 | 인천·제주·강원 각 2, 경북 4, 경남 1, 경기 보험 1, 서울 2 |
| 확인(원문 행 인용) | 0 | 시·도 별표·본문·부칙 어디에도 낙찰하한율 표기 없음 |
| 공고 실측(공고번호 3건 이상) | 0 | 이 워크트리에 해당 시·도 나라장터 공고 첨부 없음 |
| 미확인 | 14 | 원문 미인쇄. 값을 추정·역산하지 않고 무변경 |
| 코드 반영 시 바꿀 값 | 0 | 전부 무변경 |

핵심 결과:

1. 인천·제주·강원·경북·경남의 별표는 입찰가격 평점산식만 인쇄하고 낙찰하한율 열이 없습니다. 본문·부칙에도 낙찰하한율 문구가 없고, 제10~13조의 준용 조항으로 중앙 예규에 위임합니다.
2. 서울은 별표 1~5(보험용역 포함) 모두 낙찰하한율 표기가 없습니다. 추출본 전체에서 "하한" 문자열이 0건입니다.
3. 경기 보험 별표 1-5 는 같은 경기 별표 1-2·1-3·1-4·1-6 과 달리 낙찰하한율 열을 인쇄하지 않습니다. 다른 경기 별표는 좌표 추출본에서 "낙찰하한율" 열이 실제로 읽히므로, 1-5 의 부재는 추출 누락이 아니라 원문 부재입니다.
4. 경기 보험의 코드 값 47.995 는 경기 원문 근거가 아니라 `_LOCAL_LWLT_BY_SERVICE["INSURANCE"]` 기본값입니다. 같은 값은 조달청 보험용역 규칙(`SERVC_QUAL_POST_20260526_ATTACH_02`, `evaluation_rules.py:764`)의 실측 정본에서도 쓰입니다.
5. 낙찰하한율이 실제로 인쇄되는 중앙 문서는 행안부 예규 「지방자치단체 입찰시 낙찰자 결정기준」 제2장의2 기술·학술연구 용역 별표이며, "입찰가격 평점산식 (79.995/85.495/86.745/87.745%)" 형태로 괄호에 인쇄합니다(`data/sources/qualification/files/mois/fbe9a0b783c6_mois373_body.txt:7481,7895,8100,8308,8500,8660,8826`). 다만 사용자 결정 D8 에 따라 이 값을 시·도 규칙 값으로 대체하지 않습니다.
6. `ground_truth` 가 근거로 든 `docs/analysis/pps_lwlt_basis_20261005.md`(조달청 「분야별 낙찰하한율 안내」)는 이 워크트리에 없습니다. 조달청 고시 첨부 원문을 확보하지 못해 인용할 수 없습니다.

---

## 2. 규칙별 하한율 근거 표

판정: 확인 = 원문 행 인용, 공고 실측 = 공고번호 3건 이상, 미확인 = 원문 미인쇄.

| rule_id | 현재 코드 하한율 | 찾은 하한율과 구간 | 근거 EXT 파일:행 | 판정 |
| --- | ---: | --- | --- | --- |
| `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/inan/f036c240a76f_tbl1_008.txt:55-70,300-333,545-579,779-797` (산식만) | 미확인 |
| `SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/inan/f036c240a76f_tbl1_008.txt:70-89` (단순노무 산식만) | 미확인 |
| `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt:212-229,437-455,663-681,870-889` | 미확인 |
| `SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt:225-226,451-452,677-678,885-886` | 미확인 |
| `SERVC_LOCAL_GANGWON_20230611_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt:51-58,117-124,329-337,395-402,607-615,673-681,880-888,933-940` | 미확인 |
| `SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt:117-124,395-402,673-681,933-940` | 미확인 |
| `SERVC_LOCAL_GB_20260108_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gb/1074fb94b60c_gb_byp001.tbl.txt:10,13` | 미확인 |
| `SERVC_LOCAL_GB_20260108_ATTACH_02` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gb/7a34be72d0d8_gb_byp002.tbl.txt:10,13` | 미확인 |
| `SERVC_LOCAL_GB_20260108_ATTACH_03` | 84.245 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gb/5c654914711a_gb_byp003.tbl.txt:9,12` | 미확인 |
| `SERVC_LOCAL_GB_20260108_ATTACH_04` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gb/86e6964e38bf_gb_byp004.tbl.txt:9,12` | 미확인 |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gn/5d8b1c6b8c83_gn_general.hwp.tbl.txt:6,17,56,67,106,117,154,165` | 미확인 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_5` | 47.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt:676-728` (산식만) | 미확인 |
| `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/seoul/c3c437588e9f_seoul_general_2024_08_12.tbl.txt:147,376-384,492,719-727,835,1062-1070,1166,1315-1323` | 미확인 |
| `SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR` | 87.995 (기본값) | 없음(전 구간) | `data/sources/qualification/files/seoul/c3c437588e9f_seoul_general_2024_08_12.tbl.txt:378,721,1064,1317` | 미확인 |

현재 코드 하한율은 모두 규칙 `lwlt_rate` 미지정 시 `_local_rule` 이 채우는 `_LOCAL_LWLT_BY_SERVICE[service_type]` 기본값입니다(`src/app/services/evaluation_rules.py:1633-1647,1771`). 공고에 `sucsfbidLwltRate` 가 있으면 공고값이 우선하는 경로는 그대로 유지됩니다.

---

## 3. 원문 미인쇄 근거 (지역별)

### 3.1 인천광역시 (예규 제488호, 시행 2025-12-24)

별표 1 표의 열 구성은 `구분 | 심사분야 | 심사항목 | 배점한도 | 비고` 이며 낙찰하한율 열이 없습니다. 네 구간 입찰가격 항목(`data/sources/qualification/files/inan/f036c240a76f_tbl1_008.txt:55-70,300-333,545-579,779-797`)은 산식과 투찰률 단서(100분의 98·90.5·89.25·88.25)만 인쇄합니다. 본문 `data/sources/qualification/files/inan/4e46dc57c1b0_elis_inan_008.txt` 전체에 "낙찰하한율"·"하한" 문자열이 0건이고, 제10조 준용(`:171`)이 중앙 예규로 위임합니다. 구버전 별표 `data/sources/qualification/files/inan/140e479e98d1_tbl1_table.txt` 도 하한율 열이 없습니다.

### 3.2 제주특별자치도 (예규 제82호, 시행 2024-01-01)

`data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt:212-229` 등 4개 구간 입찰가격 항목이 평점산식·투찰률 단서·최저평점만 인쇄합니다. 본문 `data/sources/qualification/files/jeju/79a8f851701b_elis_jeju_main.txt` 에 "하한" 문자열이 0건이고, 제7조 준용(`:140`)이 회계예규로 위임합니다.

### 3.3 강원특별자치도 (예규 제832호, 시행 2023-06-11)

`data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt` 의 일반·폐기물·생활폐기물 별표 모두 입찰가격 산식만 인쇄합니다. 본문 `data/sources/qualification/files/gwd/0ab5d0ce1041_elis_gwd_main.txt` 에 "하한" 문자열이 0건이고, 제11조 준용(`:306`)이 중앙 예규로 위임합니다.

### 3.4 경상북도 (예규 제1571호, 시행 2026-01-08)

별표 1~4 는 `EXT/gb/gb_byp001~004.tbl.txt` 이며, 모두 "Ⅳ(Ⅲ). 입찰가격 | ※입찰가격 평점산식 참조" 행과 산식만 있습니다. 별표 1·2(`data/sources/qualification/files/gb/1074fb94b60c_gb_byp001.tbl.txt`, `data/sources/qualification/files/gb/7a34be72d0d8_gb_byp002.tbl.txt`)는 입찰가격 행과 산식이 `:10`,`:13` 이고, 별표 3·4(`data/sources/qualification/files/gb/5c654914711a_gb_byp003.tbl.txt`, `data/sources/qualification/files/gb/86e6964e38bf_gb_byp004.tbl.txt`)는 `:9`,`:12` 입니다. 단서는 투찰률 88.25%·89.25%·91% 로, 낙찰하한율이 아닙니다. 본문 `data/sources/qualification/files/gb/17af2d266b97_elis_gb_body.txt` 에 "하한" 문자열이 0건이고, 제13조 준용(`:622`)이 중앙 예규로 위임합니다.

### 3.5 경상남도 (공고 제2023-23호, 시행 2023-01-05)

`data/sources/qualification/files/gn/5d8b1c6b8c83_gn_general.hwp.tbl.txt` 의 4개 구간 입찰가격 행(`:6,56,106,154`)이 "※ 입찰가격 평점산식 참조" 이고, 산식·최저평점(`:17,67,117,165`)만 인쇄합니다. 파일 전체에 "낙찰하한율"·"하한" 문자열이 0건입니다.

### 3.6 경기도 보험 (예규 제748호, 시행 2025-08-08)

`data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt:676-728` 의 별표 1-5 보험용역은 배점한도(`:684-685`)와 산식 `평점 = 배점한도 − 0.375 × |(88/100 − 입찰가격/예정가격)×100|`(`data/sources/qualification/files/gg/ef0df12af478_gg_g2b_20251210_dec.txt:722-726`, 계수 `0.375` 는 `:724`)만 인쇄하고 낙찰하한율 열이 없습니다. 같은 파일의 별표 1-4·1-6 은 "낙찰하한율" 열이 좌표 추출본에 실제로 읽히고(`:630`,`:793`), 별표 1-1 은 `data/sources/qualification/files/gg/53a88f2293de_gg_748_biapyo_table.txt:10-14` 에서 낙찰하한율 87.995% 열이 읽힙니다. 따라서 별표 1-5 의 부재는 추출 누락이 아니라 원문 부재입니다.

### 3.7 서울특별시 (시행 2024-08-12)

`data/sources/qualification/files/seoul/c3c437588e9f_seoul_general_2024_08_12.tbl.txt` 전체에서 "낙찰하한율"·"하한" 문자열이 0건입니다. 일반 별표 1~4 와 보험용역 별표(`:1325`~) 모두 입찰가격 평점산식(`:378`,`:721`,`:1064`,`:1317`,`:1445-1447`)만 인쇄합니다.

---

## 4. 경기 보험 47.995 의 출처 추적

| 단계 | 내용 | 근거 |
| --- | --- | --- |
| 경기 별표 1-5 | 낙찰하한율 열 없음, 산식(k=0.375)만 | `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt:676-728`, `data/sources/qualification/files/gg/ef0df12af478_gg_g2b_20251210_dec.txt:724` |
| 코드 규칙 | `SERVC_LOCAL_GG_20250808_ATTACH_1_5` 는 `lwlt_rate` 미지정 | `evaluation_rules.py:2363-2375` |
| 기본값 주입 | `_LOCAL_LWLT_BY_SERVICE["INSURANCE"] = "47.995"` | `evaluation_rules.py:1635,1771` |
| 동일 값 | 조달청 보험용역 실측 정본 규칙도 47.995 | `evaluation_rules.py:764` |

즉 47.995 는 경기 원문 근거가 아니라 보험 서비스 유형의 조달청 관행 기본값입니다. 경기 원문에서 확인(원문 행 인용)할 수 있는 낙찰하한율은 존재하지 않습니다.

---

## 5. 낙찰하한율이 실제로 인쇄되는 위치 (중앙 문서)

| 문서 | 인쇄 형태 | 근거 EXT 파일:행 | 사용 제한 |
| --- | --- | --- | --- |
| 행안부 「지방자치단체 입찰시 낙찰자 결정기준」 제2장의2 기술·학술연구 용역 적격심사 별표 | `입찰가격 평점산식 (79.995%)`, `(85.495%)`, `(86.745%)`, `(87.745%)` | `data/sources/qualification/files/mois/fbe9a0b783c6_mois373_body.txt:7481,7895,8100,8308,8500,8660,8826` | D8: 시·도 규칙 값으로 그대로 사용 금지 |
| 조달청 고시 첨부 「분야별 낙찰하한율 안내」 | 미확보 | `docs/analysis/pps_lwlt_basis_20261005.md` (부재) | 인용 불가 |

시·도 별표가 준용하는 문서는 위 중앙 예규이고, 시·도 자체 별표는 B·k·기준비율 88·평탄점수·최저평점만 인쇄합니다. 낙찰하한율의 실무 입력은 나라장터 공고문의 `sucsfbidLwltRate` 항목(공고값 우선)입니다.

---

## 6. 코드 반영 시 바꿀 값 표

| rule_id | 현재 | 바꿀 값 | 사유 |
| --- | ---: | ---: | --- |
| `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄, 대체 근거 없음 |
| `SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GANGWON_20230611_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GB_20260108_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GB_20260108_ATTACH_02` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GB_20260108_ATTACH_03` | 84.245 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GB_20260108_ATTACH_04` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_5` | 47.995 | 무변경 | 경기 원문 미인쇄, 기본값 유지 |
| `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | 87.995 | 무변경 | 원문 미인쇄 |
| `SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR` | 87.995 | 무변경 | 원문 미인쇄 |

추정·역산 금지 원칙에 따라 미확인 값은 대체하지 않습니다. 공고 하한율 우선 경로가 이미 있으므로 실제 입찰에서는 공고값이 적용됩니다.

---

## 7. 조사 경로별 결과

| 우선순위 | 경로 | 확인 대상 | 결과 |
| ---: | --- | --- | --- |
| 1 | EXT 원문 전체 재검색(별표·본문·부칙) | `data/sources/qualification/files/inan`,`jeju`,`gwd`,`gb`,`gn`,`seoul`,`gg` | 낙찰하한율 표기 0건. 별표는 산식만 인쇄 |
| 2 | 자치법규정보시스템(elis.go.kr) 원문 | 위 지역 본문 수집분(`elis_*_main/body.txt`) | 적격통과점수만 인쇄. "하한" 0건 |
| 3 | 나라장터 해당 시·도 일반용역 공고 첨부·공고문 하한율 항목 | 이 워크트리에 공고 첨부 없음 | 미수집 → 공고 실측 불가(공고번호 인용 금지) |
| 보조 | 조달청 「분야별 낙찰하한율 안내」 | `docs/analysis/pps_lwlt_basis_20261005.md` | 문서 부재로 인용 불가 |

---

## 8. 출처 표

| 구분 | 파일 | 용도 |
| --- | --- | --- |
| 인천 별표 | `data/sources/qualification/files/inan/f036c240a76f_tbl1_008.txt`, `data/sources/qualification/files/inan/140e479e98d1_tbl1_table.txt` | 별표 1 산식·열 구성 |
| 인천 본문 | `data/sources/qualification/files/inan/4e46dc57c1b0_elis_inan_008.txt` | 제10조 준용, 하한 문자열 부재 |
| 제주 별표 | `data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt` | 별표 1 산식 |
| 제주 본문 | `data/sources/qualification/files/jeju/79a8f851701b_elis_jeju_main.txt` | 제7조 준용 |
| 강원 별표 | `data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt` | 별표 1~3 산식 |
| 강원 본문 | `data/sources/qualification/files/gwd/0ab5d0ce1041_elis_gwd_main.txt` | 제11조 준용 |
| 경북 별표 | `EXT/gb/gb_byp001~004.tbl.txt` | 별표 1~4 산식 |
| 경북 본문 | `data/sources/qualification/files/gb/17af2d266b97_elis_gb_body.txt` | 제13조 준용 |
| 경남 별표 | `data/sources/qualification/files/gn/5d8b1c6b8c83_gn_general.hwp.tbl.txt` | 별표 1 산식 |
| 경기 별표 | `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt`, `data/sources/qualification/files/gg/53a88f2293de_gg_748_biapyo_table.txt` | 별표 1-5 부재, 다른 별표 하한율 열 존재 |
| 서울 별표 | `data/sources/qualification/files/seoul/c3c437588e9f_seoul_general_2024_08_12.tbl.txt` | 별표 1~5 산식, 하한 문자열 부재 |
| 중앙 예규 | `data/sources/qualification/files/mois/fbe9a0b783c6_mois373_body.txt` | 행안부 낙찰하한율 괄호 인쇄(참고, D8 제한) |
| 코드 | `src/app/services/evaluation_rules.py` | 규칙 정의·기본값 주입 |
| 선행 문서 | `docs/analysis/local_lwlt_audit_20261005.md`, `docs/analysis/servc_formula_collection_local_20261004.md` | 기존 판정·산식 수집 근거 |
| 부재 문서 | `docs/analysis/pps_lwlt_basis_20261005.md` | ground_truth 인용이나 이 워크트리에 없음 |

---

## 9. 남은 리스크

| 항목 | 내용 |
| --- | --- |
| 나라장터 공고 실측 미수행 | 공고 첨부를 확보하지 못해 공고번호 3건 이상 인용 조건을 충족하지 못했습니다. 공고 실측이 필요하면 시·도별 일반용역 공고 첨부를 `EXT/<지역>/` 에 수집해야 합니다. |
| 조달청 안내 문서 부재 | `docs/analysis/pps_lwlt_basis_20261005.md` 가 없어 「분야별 낙찰하한율 안내」 원문을 인용하지 못했습니다. |
| HWP 원본 미판독 | 별표 추출본에 하한율 열이 없으나, 별표 원본 HWP(`EXT/inan/att008/*.hwp` 등)를 열람하지는 않았습니다. 다만 경기 별표 1-5 처럼 산식만 있고 하한율 열이 없는 구조와 동일합니다. |
| 경기 보험 47.995 | 경기 원문 근거가 아니라 `INSURANCE` 기본값입니다. 경기 보험 별표의 낙찰하한율은 원문에 인쇄되지 않습니다. |
