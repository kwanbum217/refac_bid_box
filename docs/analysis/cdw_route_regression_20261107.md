# 건설폐기물 고시 경로 라우팅 회귀 (2026-11-07)

> **작성일**: 2026-11-07
> **작업**: Orca Task `task_417e06f69f79` (builder, `run_d3fa8d51ba74`)
> **정본 사양**: `.orca/capsules/task_417e06f69f79/capsule.yaml`
> **사용자 결정**: D01~D06 ([decision_backlog_20261107.md](decision_backlog_20261107.md) 2.1절)
> **근거 문서**: [entity_cdw_route_cause_20261106.md](entity_cdw_route_cause_20261106.md)
> **측정 창**: 2025-11-07 ~ 2026-11-07, 업무구분 `Servc`, 낙찰방법 코드 `낙030001`, 공고번호·업무구분별 최신 차수
> **측정 방법**: `scripts/report_rule_coverage.py` 의 `collect_records` 와 같은 SQL·필터를 읽기 전용 세션에서 재생하고, `resolve_evaluation_rule_from_raw_data` 를 같은 인자로 호출했습니다. 저장소 파일은 고치지 않았고 DB 쓰기도 하지 않았습니다.

---

## 1. 요약

| 항목 | 값 |
| --- | ---: |
| 측정 창 공고 수 | 31,325 |
| entity 문서 2절 51건 중 고시 규칙 판정 | **51 / 51** |
| 51건 공고 하한율 = 적용 고시 규칙 하한율 | **51 / 51** |
| 판정이 바뀐 공고 | 1,169 |
| 대상 집합 밖에서 바뀐 공고 | **0** |
| 새로 고시 규칙으로 간 공고 | 1,169 |
| 바뀐 공고 중 공고 하한율 = 새 고시 규칙 하한율 | **1,169 / 1,169 (100.0%)** |
| 적용 → 차단으로 바뀐 공고 | 0 |
| 차단 → 적용으로 바뀐 공고 | 1 |
| 고시 규칙 적용 공고(전체 창) | 1,610 → 2,779 |

- 판정 변경은 전부 `SERVC_QUAL_MOE_CDW_ATTACH_02~04B` 로 이동한 경우입니다. 대상 집합 밖 변경은 0건입니다.
- 대상 집합은 "조달분류(`pubPrcrmntClsfcNm` 등)가 `건설폐기물처리서비스` 이거나 공고명(`bidNtceNm`)에 `건설폐기물` 이 있는 `Servc` 공고"로 정의했고, 측정 창에서 3,218건입니다.
- 51건은 모두 공고 하한율이 새로 적용된 고시 호의 하한율과 정확히 같습니다.

---

## 2. 적용한 결정

| 결정 | 적용 내용 | 코드 위치 |
| --- | --- | --- |
| D01 | 51건을 환경부고시 「건설폐기물처리용역 적격업체 평가기준」 경로로 옮김 | `src/app/services/evaluation_rules_local.py` A 계열 6개 규칙 |
| D02 | 원문 제외 조항을 확인하지 못한 5개 시·도(서울·부산·제주·경남·충남)에 `cdw_exclusion` 선언 | 같은 파일. 서울·부산·제주·경남 `GENERAL`, 충남 `WASTE` 구판·현행 |
| D03 | `WASTE` 규칙을 새로 만들지 않고 기존 `GENERAL` 규칙에 선언. 충남은 이미 있는 `WASTE` 별표에 선언 | 같은 파일 |
| D04 | 공고명 `건설폐기물` 문자열과 조달분류 `건설폐기물처리서비스` 를 병행(OR) | `src/app/services/evaluation_rules.py:2080-2082`, `2360-2388` |
| D05 | 라우팅 순서(조달청 → 기관 → 시·도 → 환경부고시 대체) 변경 없음 | `resolve_evaluation_rule` 분기 순서 그대로 |
| D06 | 조달분류만 `건설폐기물처리서비스` 이고 공고명에 `폐기물` 이 없어도 같은 신호로 고시 경로 진입 | D04 의 OR 신호 |

### 2.1 `cdw_exclusion` 선언값

| 값 | 의미 | 선언 규칙 |
| --- | --- | --- |
| `named` | 원문에 건설폐기물 제외 문구가 있고, 공고명 또는 조달분류의 건설폐기물 신호를 확인 | 인천 2, 강원, 세종, 경북 2, 충북, 경기, 대전 2, 전북 |
| `named_except_haul` | `named` 신호에 더해 공고명에 `처리` 가 있을 때만 제외 | 울산 |
| `band` | 낙찰방법명 일치만으로 제외 | 대구 2 |
| `notice_cited` | 원문 제외 문구는 없으나 공고문이 고시를 인용. 신호 판정은 `named` 와 같고 선언 근거만 다름 | 서울, 부산, 제주, 경남, 충남 구판·현행 |

`notice_cited` 규칙 6개는 다음과 같습니다. 각 선언에는 entity 문서 절과 대표 공고번호 주석을 달았습니다.

| 규칙 | 시·도 | service_type | 대표 공고 |
| --- | --- | --- | --- |
| `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | 서울특별시 | `GENERAL` | `R26BK01268796` 외 30건 |
| `SERVC_LOCAL_BUSAN_20250626_ATTACH_01` | 부산광역시 | `GENERAL` | `R26BK01390456` 외 4건 |
| `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | 제주특별자치도 | `GENERAL` | `R26BK01387878` 외 1건 |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | 경상남도 | `GENERAL` | `R26BK01537443` 외 1건 |
| `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03` | 충청남도 | `WASTE` (구판) | `R25BK01255404` 외 3건 |
| `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03` | 충청남도 | `WASTE` (현행) | 위와 같은 별표의 현행판 |

---

## 3. entity 문서 2절 51건 확인

`O` 는 공고 `sucsfbidLwltRate` 가 적용된 고시 규칙의 하한율과 같은 경우입니다.

| # | 공고번호 | 차수 | 시·도 | 공고 하한율 | 적용 규칙 | 일치 |
| ---: | --- | :---: | --- | ---: | --- | :---: |
| 1 | `R25BK01230693` | 000 | 경기도 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 2 | `R25BK01255404` | 000 | 충청남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 3 | `R26BK01268796` | 000 | 서울특별시 | 85.495 | `SERVC_QUAL_MOE_CDW_ATTACH_02` | O |
| 4 | `R26BK01372506` | 000 | 충청남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 5 | `R26BK01378581` | 000 | 서울특별시 | 85.495 | `SERVC_QUAL_MOE_CDW_ATTACH_02` | O |
| 6 | `R26BK01382344` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 7 | `R26BK01382612` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 8 | `R26BK01382838` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 9 | `R26BK01387878` | 000 | 제주특별자치도 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 10 | `R26BK01390456` | 000 | 부산광역시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 11 | `R26BK01392592` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 12 | `R26BK01411789` | 000 | 울산광역시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 13 | `R26BK01435218` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 14 | `R26BK01449261` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 15 | `R26BK01459107` | 001 | 서울특별시 | 77.995 | `SERVC_QUAL_MOE_CDW_ATTACH_04B` | O |
| 16 | `R26BK01462942` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 17 | `R26BK01481923` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 18 | `R26BK01483433` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 19 | `R26BK01484068` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 20 | `R26BK01492038` | 000 | 충청남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 21 | `R26BK01488978` | 000 | 경기도 | 82.995 | `SERVC_QUAL_MOE_CDW_ATTACH_04A` | O |
| 22 | `R26BK01509769` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 23 | `R26BK01519384` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 24 | `R26BK01520658` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 25 | `R26BK01522871` | 000 | 부산광역시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 26 | `R26BK01522932` | 002 | 부산광역시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 27 | `R26BK01522970` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 28 | `R26BK01526326` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 29 | `R26BK01530000` | 000 | 충청남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 30 | `R26BK01537443` | 000 | 경상남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 31 | `R26BK01558250` | 000 | 경기도 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 32 | `R26BK01561178` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 33 | `R26BK01570494` | 000 | 울산광역시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 34 | `R26BK01570886` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 35 | `R26BK01579244` | 001 | 부산광역시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 36 | `R26BK01579697` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 37 | `R26BK01600619` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 38 | `R26BK01617264` | 000 | 부산광역시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 39 | `R26BK01622238` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 40 | `R26BK01622362` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 41 | `R26BK01633504` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 42 | `R26BK01639721` | 000 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 43 | `R26BK01648659` | 001 | 서울특별시 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 44 | `R26BK01662864` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 45 | `R26BK01717987` | 000 | 강원특별자치도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 46 | `R26BK01719314` | 000 | 서울특별시 | 82.995 | `SERVC_QUAL_MOE_CDW_ATTACH_04A` | O |
| 47 | `R26BK01718223` | 002 | 경상남도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 48 | `R26BK01763245` | 000 | 경기도 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |
| 49 | `R26BK01787532` | 000 | 제주특별자치도 | 87.745 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | O |
| 50 | `R26BK01795375` | 000 | 서울특별시 | 85.495 | `SERVC_QUAL_MOE_CDW_ATTACH_02` | O |
| 51 | `R26BK01813785` | 000 | 서울특별시 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` | O |

적용 규칙 분포는 제4호 29건, 제3호 16건, 제2호 3건, 제1호(30억 미만) 2건, 제1호(100억 미만) 1건입니다.

---

## 4. 기존 시험 단언 변경

이번 결정으로 의도적으로 바뀐 기존 단언과 입력입니다. 삭제한 단언은 없습니다.

| 파일 | 항목 | 이전 | 이후 | 이유 |
| --- | --- | --- | --- | --- |
| `tests/test_evaluation_rules_split_invariance.py` | `EXPECTED_FINGERPRINTS["LOCAL_RULES"]` | `48d29a0c7a15e957` | `dc1347bfca63de90` | A 계열 6개 규칙에 `cdw_exclusion="notice_cited"` 를 추가해 `repr` 이 바뀜. 나머지 8개 지문, `EXPECTED_NAMES`, `list_all_rules` 지문은 불변 |
| `tests/test_cdw_exclusion_regions.py` | `test_outside_region_unchanged` 입력·단언 | 서울(11) `건설폐기물 처리용역` → MOE 아님 | 전남광주(12) `건설폐기물 처리용역` → `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 서울은 D02 의 `notice_cited` 선언 대상이 됨. 선언 밖 지역 불변 검증을 아직 선언이 없는 전남광주로 옮김 |
| `tests/test_daejeon_predecessor.py` | `_raw` 기본 `pubPrcrmntClsfcNm` | `건설폐기물처리서비스` | `소프트웨어개발서비스` | D04 의 OR 신호로 건설폐기물 분류 공고가 고시 경로로 가므로, 구판·현행 시행일 선택을 보는 이 파일의 입력에서 건설폐기물 신호를 분리. 6개 단언은 그대로 |

`tests/test_cdw_route_20261107.py` 를 새로 추가했습니다. (a) 조달분류만 건설폐기물인 공고, (b) 공고명만 건설폐기물인 공고, (c) 생활폐기물 등 일반 폐기물 불변, (d) `notice_cited` GENERAL 폴백 시·도의 건설폐기물만 고시, (e) 원문 `named`·`named_except_haul` 선언 불변, `notice_cited` 와 `named` 의 분리, 미선언 시·도의 라우팅 순서 유지를 단언합니다.

---

## 5. 전수 판정 회귀

### 5.1 방법

`collect_records(months=12, category="Servc", method_code="낙030001", today=date(2026, 11, 7))` 와 같은 SQL(`ANNOUNCEMENT_SQL`)·최신 차수 규칙·낙찰방법 코드 필터를 읽기 전용 세션에서 재생했습니다. 각 공고에 `resolve_evaluation_rule_from_raw_data` 를 `_to_record` 와 같은 인자로 호출해 변경 전·후 판정을 `bid_ntce_no-bid_ntce_ord` 키로 비교했습니다.

- 변경 전: 기준 커밋의 코드
- 변경 후: 이 Task 의 코드
- 판정 변경 정의: `(rule_id, is_blocked, block_reason_code)` 중 하나라도 달라진 경우

### 5.2 결과

| 항목 | 값 |
| --- | ---: |
| 비교 공고 | 31,325 |
| 판정 변경 | 1,169 |
| 대상 집합 밖 변경 | **0** |
| 새 고시 규칙(`SERVC_QUAL_MOE_CDW_*`) | 1,169 |
| 공고 하한율 = 새 규칙 하한율 | 1,169 / 1,169 (100.0%) |
| 적용 → 차단 | 0 |
| 차단 → 적용 | 1 |
| `effective_lwlt_rate` 변경 | 1 |

변경 전 규칙별 이동 건수입니다.

| 변경 전 규칙 | 건수 |
| --- | ---: |
| `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | 326 |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | 188 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_3` | 158 |
| `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03` | 98 |
| `SERVC_LOCAL_CB_20231020_ATTACH_01` | 77 |
| `SERVC_LOCAL_GB_20260108_ATTACH_03` | 55 |
| `SERVC_LOCAL_GANGWON_20230611_ATTACH_01` | 51 |
| `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03` | 49 |
| `SERVC_LOCAL_BUSAN_20250626_ATTACH_01` | 38 |
| `SERVC_LOCAL_JEONBUK_20240118_ATTACH_01` | 34 |
| `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | 30 |
| `SERVC_LOCAL_GB_20241212_ATTACH_05` | 26 |
| `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | 12 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | 9 |
| `SERVC_LOCAL_INCHEON_20241204_ATTACH_01` | 8 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_04` | 5 |
| `SERVC_LOCAL_DAEJEON_20260101_ATTACH_01` | 3 |
| `SERVC_LOCAL_DAEJEON_20240120_ATTACH_01` | 1 |
| 차단(`LOCAL_SERVICE_TYPE_UNRESOLVED`) | 1 |
| **합계** | **1,169** |

이동 후 규칙 분포는 제4호 657건, 제3호 350건, 제2호 128건, 제1호(30억 미만) 29건, 제1호(100억 미만) 5건입니다. 시·도별로는 서울 327, 경남 188, 경기 158, 충남 147, 경북 81, 충북 77, 강원 51, 부산 38, 전북 34, 제주 30, 인천 20, 울산 9, 세종 5, 대전 4건입니다.

### 5.3 신호별 분해

| 확인된 신호 | 건수 |
| --- | ---: |
| 조달분류만 `건설폐기물처리서비스` | 755 |
| 공고명과 조달분류 모두 | 413 |
| 공고명만 `건설폐기물` | 1 |

- 공고명만 걸린 1건은 `R26BK01795300`(서울특별시)으로, 변경 전 `LOCAL_SERVICE_TYPE_UNRESOLVED` 차단이었습니다. 공고명에 `건설폐기물` 이 있어 고시 제2호로 풀리고, 공고 하한율 85.495 와 규칙 하한율이 일치합니다.
- 조달분류 신호만으로 이동한 755건은 공고명 표기가 `가연성폐기물`, `폐아스콘`, `건설오니`, `매립폐기물` 등으로 흔들린 공고입니다.

### 5.4 D06: 조달분류만 건설폐기물인 공고

공고명에 `폐기물` 이 없고 조달분류만 `건설폐기물처리서비스` 이면서 낙찰방법명이 고시 띠 표기 6종에 맞는 공고는 76건입니다.

| 구분 | 건수 |
| --- | ---: |
| 띠 표기 + 조달분류만 건설폐기물(공고명에 `폐기물` 없음) | 76 |
| 변경 전부터 고시 규칙 | 19 |
| 이번에 고시 규칙으로 이동 | 47 |
| 시·도 규칙 유지 | 10 |

- 유지 10건은 모두 전남광주통합특별시의 `SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4`(8건)와 `SERVC_LOCAL_JNGJ_20260716_ATTACH_03`(2건)입니다. 두 규칙에는 `cdw_exclusion` 선언이 없고, 이 Task 의 선언 대상은 A 계열 5개 시·도(서울·부산·제주·경남·충남)입니다. 전남광주 선언은 원문 근거 확보가 필요한 별도 결정입니다.
- 유지 10건의 공고번호는 `R25BK01252783`, `R26BK01380666`, `R26BK01430856`, `R26BK01431133`, `R26BK01558610`, `R26BK01558639`, `R26BK01558656`, `R26BK01558672`, `R26BK01675184`, `R26BK01737531` 입니다.
- 같은 조달분류 신호를 가진 공고는 전체 109건이고, 이 중 33건은 낙찰방법명이 고시 띠 표기가 아니어서 고시 규칙 선택 대상이 아닙니다.

### 5.5 하한율이 바뀐 1건

`R26BK01795300`(서울특별시, `장지공영차고지 건설폐기물(파쇄) 처리용역`)은 변경 전 세부유형 미판정으로 차단되어 `effective_lwlt_rate` 가 없었고, 변경 후 고시 제2호 85.495 가 됩니다. 공고 하한율도 85.495 입니다.

---

## 6. 검증 명령

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_cdw_route_20261107.py tests/test_evaluation_rules_split_invariance.py tests/test_evaluation_rules_local.py -q` | 29 passed |
| `uv run pytest tests/test_cdw_exclusion_regions.py tests/test_daejeon_predecessor.py -q` | 추가 확인, 통과 |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10,550 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 7. 한계

- entity 문서 4절의 2안 영향 1,170건과 이번 실측 1,169건은 측정 창과 기준 커밋이 달라 직접 비교하지 않습니다. entity 문서는 2025-11-06 ~ 2026-11-06 창의 31,428건, 이번 회귀는 2025-11-07 ~ 2026-11-07 창의 31,325건입니다.
- 전남광주 10건은 D06 의 신호에는 걸리지만 해당 시·도 규칙에 제외 선언이 없어 시·도 규칙으로 남습니다. A 계열 5개 시·도 밖이라 이 Task 에서 선언하지 않았습니다.
- 회귀 수집은 저장소 밖 임시 스크립트로 실행했고, 결과 수치만 이 문서에 남깁니다. 재현에는 같은 창·필터·읽기 전용 세션이 필요합니다.
- 공고 하한율 일치율은 `sucsfbidLwltRate` 가 있는 공고만 대상으로 했습니다. 이번 변경 1,169건은 모두 값이 있었습니다.
