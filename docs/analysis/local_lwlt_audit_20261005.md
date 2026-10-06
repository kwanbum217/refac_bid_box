# LOCAL 규칙 별표 원문 낙찰하한율 전수 대조

> **작성일**: 2026-10-05
> **작업**: Orca `task_2e903a11a248` (run `run_c6cbadfe4a2b`), 브랜치 `kwanbum217/x1-local-lwlt`
> **범위**: 기존 LOCAL 규칙 36개(인천·제주·강원·세종·경북·울산·충북·전남광주·경남·대구·경기)의 별표 원문 낙찰하한율 전수 대조, 정정 20개, 무변경 16개
> **근거 원문**: 프로젝트 루트 `EXT/` (지역별 수집분)와 `EXT/supplement/daegu`
> **정본 사양**: `.orca/capsules/task_2e903a11a248/capsule.yaml`
> **관련 코드**: `src/app/services/evaluation_rules.py`, `src/app/services/evaluation_flat_zones.py`

---

## 1. 요약

| 항목 | 수 | 내용 |
| --- | ---: | --- |
| 대조 대상 규칙 | 36 | 기존 LOCAL 규칙 11개 지역 |
| 정정 | 20 | 대표값 정정 9개, 구간별 하한율 반영 11개(그중 7개는 10억/30억 구간 분할 동반) |
| 일치(무변경) | 4 | 세종 소프트웨어·육상운송 별표 3·5 (80.495/84.995) |
| 원문 미기재(무변경) | 12 | 인천·제주·강원 규칙 6개, 경북 규칙 4개, 경남 규칙 1개, 경기 보험 별표 1-5 |
| 신규 11개 규칙 | - | 2단계 추가 5곳(서울·부산·대전·충남·전북)은 이 워크트리 원문이 없어 하한율 값 무변경. 전북 source 행 범위만 보정 |

핵심 결과:

1. 원문이 구간마다 다른 낙찰하한율을 인쇄한 규칙 11개에 `PriceBand.lwlt_rate` 를 채웠습니다. 이 가운데 울산·충북·전남광주 7개 규칙은 기존 구간에 10억·30억 경계가 없어 구간을 나눴습니다.
2. 원문이 전 구간 단일 하한율을 인쇄한 규칙 9개의 규칙 대표값(`lwlt_rate`)을 원문값으로 고쳤습니다. 세종 시설·폐기물·생활폐기물(87.745%)이 포함됩니다.
3. 공고 하한율이 있으면 공고값이 우선하므로 이번 정정은 공고 하한율이 없는 경우에만 결과를 바꿉니다.
4. 분할한 구간의 평탄 값은 분할 전과 같게 유지했습니다(`evaluation_flat_zones.py` 에 새 상한 키만 추가, 기존 키 값 변경 없음).
5. 기존 시험 `tests/test_local_regime_rules_wave2.py` 의 고정 다이제스트는 정정 16개 규칙 때문에 값이 바뀌어 새 스냅샷으로 갱신했습니다(해시 값만 변경, 8장).

---

## 2. 지역별 대조표

판정: 정정(대표값) = 규칙 `lwlt_rate` 정정, 정정(구간) = 구간별 하한율 추가, 구간 분할 = 10억/30억 경계 추가 동반, 일치 = 원문과 코드 값 동일, 원문 미기재 = 원문이 하한율을 인쇄하지 않아 무변경.

### 2.1 세종특별자치시 (예규 제32호, 시행 2025-12-01)

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_02` | 별표 2 시설 | 전 구간 87.745% (`data/sources/qualification/files/sejong/1f7ff1eafc15_byp2_2025.txt:31`) | 87.995 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_04` | 별표 4 폐기물 | 전 구간 87.745% (`data/sources/qualification/files/sejong/f6909b0180a1_byp4_2025.txt:18`) | 84.245 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2` | 별표 4의2 생활폐기물 | 전 구간 87.745% (`data/sources/qualification/files/sejong/aff68bd433da_byp4_2_2025.txt:11`) | 84.245 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_03` | 별표 3 SW 비대상 | 80.495% (`data/sources/qualification/files/sejong/acbf29823fb4_byp3_sw_2025.txt:17`) | 80.495 | 80.495 | 일치 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME` | 별표 3 SW 대상 | 84.995% (`data/sources/qualification/files/sejong/acbf29823fb4_byp3_sw_2025.txt:25`) | 84.995 | 84.995 | 일치 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_05` | 별표 5 육상운송 비대상 | 80.495% (`data/sources/qualification/files/sejong/53fc5b005509_byp5_2025.txt:20`) | 80.495 | 80.495 | 일치 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME` | 별표 5 육상운송 대상 | 84.995% (`data/sources/qualification/files/sejong/53fc5b005509_byp5_2025.txt:28`) | 84.995 | 84.995 | 일치 |

### 2.2 울산광역시 (공고 제2022-1100호, 시행 2022-08-10)

원문 근거: `data/sources/qualification/files/ulsan/0e673b450ec3_ulsan_general_20220810.tbl.txt:671-713` (별표 1 뒤 참고 "입찰가격 평점 산식", 일반용역·폐기물용역·단순노무·생활폐기물수집·운반대행용역 공통).

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | 별표 1 일반 | 2억 미만 87.745 (`:707`), 5억 미만 86.745 (`:695`), 10억 미만 85.495 (`:683`), 30억 미만 77.995·30억 이상 72.995 (`:671`) | 구간값 없음(대표값 87.995) | 구간값 5개, 30억 경계 분할 | 구간 분할 |
| `SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR` | 별표 1 단순노무 | 전 구간 87.745% (`:677,689,701,713`) | 87.995 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1` | 별표 1-1 생활폐기물 | 전 구간 87.745% (`:680,692,704`) | 84.245 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | 별표 2 폐기물 | 2억 미만 87.745 (`:710`), 5억 미만 86.745 (`:698`), 10억 미만 85.495 (`:686`), 30억 미만 77.995·30억 이상 72.995 (`:674`) | 구간값 없음(대표값 84.245) | 구간값 5개, 30억 경계 분할 | 구간 분할 |

### 2.3 충청북도 (공고 제2023-1428호, 시행 2023-10-20)

원문 근거: `data/sources/qualification/files/cb/0cfe5136bcc2_cb_cjuc.txt:1454-1659` (별표 1 "3. 입찰가격 평가").

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_CB_20231020_ATTACH_01` | 별표 1 일반 | 2억 미만 87.745 (`:1635-1637`), 5억 미만 86.745 (`:1595-1597`), 10억 미만 85.495 (`:1555-1557`), 30억 미만 77.995·30억 이상 72.995 (`:1515-1519`) | 구간값 없음(대표값 87.995) | 구간값 5개, 30억 경계 분할 | 구간 분할 |
| `SERVC_LOCAL_CB_20231020_SIMPLE_LABOR` | 별표 1 단순노무 | 전 구간 87.745% (`:1535-1537,1575-1577,1615-1617,1655-1657`) | 87.995 (기본값) | 87.745 | 정정(대표값) |

### 2.4 전남광주통합특별시 (예규 제3호, 시행 2026-07-16)

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_01` | 별표 1 시설 | 전 구간 87.745% (`data/sources/qualification/files/jn_gj/7890f3b13189_jngj_att001.hwp.tbl.txt:53,61,69`) | 87.995 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_02` | 별표 2 소프트웨어 | 2억 미만 87.745 (`att002:74`), 5억 미만 86.745 (`att002:66`), 5억 이상 85.495·10억 이상 82.995·30억 이상 80.495 (`att002:58`) | 구간값 없음(대표값 87.995) | 구간값 5개, 10억·30억 경계 분할 | 구간 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 별표 3 폐기물 | 2억 미만·5억 미만 87.745 (`att003:75,67`), 5억 이상 82.995·10억 이상 77.995·30억 이상 72.995 (`att003:59`) | 구간값 없음(대표값 84.245) | 구간값 5개, 10억·30억 경계 분할 | 구간 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_04` | 별표 4 생활폐기물 | 전 구간 87.745% (`att004:50,55,60`) | 84.245 (기본값) | 87.745 | 정정(대표값) |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_05` | 별표 5 육상운송 | 2억 미만·5억 미만·10억 미만 85.495 (`att005:70,62`), 10억 이상 82.995, 30억 이상 80.495 (`att005:54`) | 구간값 없음(대표값 84.245) | 구간값 5개, 10억·30억 경계 분할 | 구간 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_06` | 별표 6 어장정화·정비 | 2억 미만 87.745 (`att006:93`), 5억 미만 86.745 (`att006:65`), 10억 미만 85.495 (`att006:37`), 30억 미만 77.995·30억 이상 72.995 (`att006:9`) | 구간값 없음(대표값 87.995) | 구간값 5개, 30억 경계 분할 | 구간 분할 |

### 2.5 경기도 (예규 제748호, 시행 2025-08-08)

원문 근거: `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt` (별표 1-2~1-6). 별표 1-1(단순노무)은 종전 판단대로 규칙을 만들지 않았습니다.

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_2` | 별표 1-2 소프트웨어 | 2억 미만 87.745 (`:452`), 5억 미만 86.745 (`:443`), 10억 미만 85.495 (`:432`), 10억 이상 77.995 (`:419`) | 구간값 없음(대표값 87.995) | 구간값 4개 | 정정(구간) |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_3` | 별표 1-3 폐기물 | 2억 미만 87.745 (`:569`), 5억 미만 86.745 (`:563`), 10억 미만 85.495 (`:550`), 10억 이상 77.995 (`:537`) | 구간값 없음(대표값 84.245) | 구간값 4개 | 정정(구간) |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_4` | 별표 1-4 육상운송 | 2억 미만·5억 미만 87.745 (`:669,660`), 10억 미만 86.745 (`:649`), 10억 이상 85.495 (`:641`) | 구간값 없음(대표값 87.995) | 구간값 4개 | 정정(구간) |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_5` | 별표 1-5 보험 | 인쇄 없음(입찰가격 평점 산식만, `:723-726`) | 47.995 | 47.995 | 원문 미기재 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | 별표 1-6 기타 일반 | 2억 미만 87.745 (`:835`), 5억 미만 86.745 (`:825`), 10억 미만 85.495 (`:815`), 10억 이상 77.995 (`:805`) | 구간값 없음(대표값 87.995) | 구간값 4개 | 정정(구간) |

### 2.6 대구광역시 (예규 제238호, 시행 2026-05-11)

| 규칙 ID | 별표·용역 | 원문 구간별 하한율 (EXT 파일:행) | 종전 코드 | 정정 코드 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | 별표 1 단순노무 | 최저 낙찰하한율 87.745% 이상 (`data/sources/qualification/files/daegu/036ab03c59cf_tbl1_daegu.txt:150`), 공고문 낙찰하한율 87.745% (`data/sources/qualification/files/supplement/6face695bdca_R25BK01157938_f1.txt:47`) | 87.995 (기본값) | 87.745 | 정정(대표값) |

### 2.7 원문 미기재 지역 (무변경)

| 규칙 ID | 원문 확인 파일 | 종전·현재 코드 | 판정 |
| --- | --- | --- | --- |
| `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | `data/sources/qualification/files/inan/140e479e98d1_tbl1_table.txt` (별표 1 입찰가격 배점한도만) | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR` | `data/sources/qualification/files/inan/140e479e98d1_tbl1_table.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | `data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR` | `data/sources/qualification/files/jeju/9dd3512e42de_tbl1_jeju.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_GANGWON_20230611_ATTACH_01` | `data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR` | `data/sources/qualification/files/gwd/6db5320aba06_tbl1_gwd.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_GB_20260108_ATTACH_01`~`04` | `EXT/gb/gb_byp001~004.tbl.txt` | 87.995/87.995/84.245/87.995 | 원문 미기재 |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | `data/sources/qualification/files/gn/5d8b1c6b8c83_gn_general.hwp.tbl.txt` | 87.995 | 원문 미기재 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_5` | `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt:723-726` | 47.995 | 원문 미기재 |

인천·제주·강원·경북·경남은 수집 추출물 어디에도 낙찰하한율 표기가 없어 추정·역산하지 않고 값을 바꾸지 않았습니다. 경기 보험 별표 1-5 는 낙찰하한율 열 없이 입찰가격 평점 산식(계수 0.375)만 인쇄되어 있습니다.

---

## 3. 정정 상세

### 3.1 규칙 대표값 정정 9개

| 규칙 ID | 종전 | 정정 | 근거 |
| --- | ---: | ---: | --- |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_02` | 87.995 | 87.745 | `data/sources/qualification/files/sejong/1f7ff1eafc15_byp2_2025.txt:31` |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_04` | 84.245 | 87.745 | `data/sources/qualification/files/sejong/f6909b0180a1_byp4_2025.txt:18` |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2` | 84.245 | 87.745 | `data/sources/qualification/files/sejong/aff68bd433da_byp4_2_2025.txt:11` |
| `SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR` | 87.995 | 87.745 | `data/sources/qualification/files/ulsan/0e673b450ec3_ulsan_general_20220810.tbl.txt:677,689,701,713` |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1` | 84.245 | 87.745 | `data/sources/qualification/files/ulsan/0e673b450ec3_ulsan_general_20220810.tbl.txt:680,692,704` |
| `SERVC_LOCAL_CB_20231020_SIMPLE_LABOR` | 87.995 | 87.745 | `data/sources/qualification/files/cb/0cfe5136bcc2_cb_cjuc.txt:1535-1537,1575-1577,1615-1617,1655-1657` |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_01` | 87.995 | 87.745 | `data/sources/qualification/files/jn_gj/7890f3b13189_jngj_att001.hwp.tbl.txt:53,61,69` |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_04` | 84.245 | 87.745 | `data/sources/qualification/files/jn_gj/75912ab66990_jngj_att004.hwp.tbl.txt:50,55,60` |
| `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | 87.995 | 87.745 | `data/sources/qualification/files/daegu/036ab03c59cf_tbl1_daegu.txt:150`, `data/sources/qualification/files/supplement/6face695bdca_R25BK01157938_f1.txt:47` |

### 3.2 구간별 하한율 반영 11개

구간값을 넣은 규칙은 구간 하한율이 서로 다르면 추정가격으로 구간을 고르고, 추정가격이 없으면 `LWLT_RATE_UNRESOLVED` 로 막습니다. 규칙 대표값은 분할 전 값을 유지해 대표값 경로 자체는 바뀌지 않게 했습니다.

| 규칙 ID | 구간값(2억 미만 → 마지막) | 비고 |
| --- | --- | --- |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | 87.745 / 86.745 / 85.495 / 77.995 / 72.995 | 30억 경계 분할 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | 87.745 / 86.745 / 85.495 / 77.995 / 72.995 | 30억 경계 분할 |
| `SERVC_LOCAL_CB_20231020_ATTACH_01` | 87.745 / 86.745 / 85.495 / 77.995 / 72.995 | 30억 경계 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_02` | 87.745 / 86.745 / 85.495 / 82.995 / 80.495 | 10억·30억 경계 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 87.745 / 87.745 / 82.995 / 77.995 / 72.995 | 10억·30억 경계 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_05` | 85.495 / 85.495 / 85.495 / 82.995 / 80.495 | 10억·30억 경계 분할 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_06` | 87.745 / 86.745 / 85.495 / 77.995 / 72.995 | 30억 경계 분할 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_2` | 87.745 / 86.745 / 85.495 / 77.995 | 기존 4구간 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_3` | 87.745 / 86.745 / 85.495 / 77.995 | 기존 4구간 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_4` | 87.745 / 87.745 / 86.745 / 85.495 | 기존 4구간 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | 87.745 / 86.745 / 85.495 / 77.995 | 기존 4구간 |

### 3.3 규칙 source 보강

정정한 규칙의 `source` 에 EXT 원문 파일과 행을 추가했습니다(값이 의심스러우면 원문 행을 직접 대조할 수 있게 함).

| 규칙 묶음 | source 에 추가한 EXT 근거 |
| --- | --- |
| 세종 시설·폐기물·생활폐기물 | `data/sources/qualification/files/sejong/1f7ff1eafc15_byp2_2025.txt:31`, `byp4_2025.txt:18`, `byp4_2_2025.txt:11` |
| 울산 4개 | `data/sources/qualification/files/ulsan/0e673b450ec3_ulsan_general_20220810.tbl.txt:671-713` |
| 충북 2개 | `data/sources/qualification/files/cb/0cfe5136bcc2_cb_cjuc.txt:1454-1659` |
| 전남광주 6개 | `EXT/jn_gj/jngj_att001~006.hwp.tbl.txt` 해당 행 |
| 경기 4개 | `data/sources/qualification/files/gg/c231f0609a39_gg_g2b_20251210_coord.txt` 별표별 구간 |
| 대구 1개 | `data/sources/qualification/files/daegu/036ab03c59cf_tbl1_daegu.txt:150`, `data/sources/qualification/files/supplement/6face695bdca_R25BK01157938_f1.txt:47` |

### 3.4 전북특별자치도 source 행 범위 보정

`_SRC_JEONBUK` 의 괄호 밖 범위(`35-37,44-49,127-145,357-366,583-592,792-799`)는 기존 시험 `tests/test_local_band_lwlt.py` 가 토큰으로 고정 검사하므로 유지하고, 괄호 안에 실제 하한율 숫자 행을 덧붙였습니다.

| 하한율 | 실제 숫자 행 (리뷰어 확인) | 종전 인용 |
| --- | --- | --- |
| 77.995 | `:141` | 괄호 안 138-145 만 기재 |
| 87.745(단순노무) | `:143` | 동일 |
| 72.995 | `:145` | 동일 |
| 85.495 | `:369` | 357-366 이 3행 짧음 |
| 86.745 | `:595` | 583-592 가 3행 짧음 |
| 87.745(2억 미만) | `:802` | 792-799 가 3행 짧음 |

값 자체는 바꾸지 않았고 문자열만 보정했습니다.

---

## 4. 구간 분할에 따른 평탄 데이터 보강

구간을 나눈 7개 규칙은 새 상한(10억·30억)에 분할 전 구간과 같은 `FlatZone` 값을 유지해야 점수가 달라지지 않습니다. `src/app/services/evaluation_flat_zones.py` 에 아래 키만 추가했습니다(기존 키 값 변경·삭제 없음).

| 규칙 ID | 추가한 상한 키 | 적용 값(분할 전 구간과 동일) |
| --- | --- | --- |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | 3000000000 | 0.98 → 20 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | 3000000000 | 0.98 → 20 |
| `SERVC_LOCAL_CB_20231020_ATTACH_01` | 3000000000 | 0.98 → 20 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_02` | 1000000000, 3000000000 | 0.905 → 45 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 1000000000, 3000000000 | 0.93 → 25 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_05` | 1000000000, 3000000000 | 0.905 → 55 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_06` | 3000000000 | 0.98 → 20 |

분할 전후 B·k·기준비율·평탄·통과점수는 같고, 달라진 것은 구간별 낙찰하한율뿐입니다. 경계값(정확히 10억·30억)은 이상 쪽 구간에 속합니다.

---

## 5. 기존 시험 다이제스트 갱신

`tests/test_local_regime_rules_wave2.py` 의 `test_existing_36_local_rules_unchanged` 는 기존 36개 규칙의 동작 필드(`lwlt_rate`·`price_bands`·`threshold_bands` 등) 스냅샷 SHA-256 을 고정 대조합니다. 이번 정정으로 해시가 바뀌어 값만 새 스냅샷으로 갱신했습니다(시험 로직·다른 기대값 무변경).

- 종전: `25955ed3e54284d5fc7afd11621f7a0d8a4ec03ebfc6e0b52935d80ae6d32540`
- 갱신: `37bea272e20575bcc93fa5b82c15d3894b8bb93d705f79244c34382a8c75653a`

해시가 바뀐 원인 규칙 16개:

| # | 규칙 ID | 바뀐 필드 |
| ---: | --- | --- |
| 1 | `SERVC_LOCAL_SEJONG_20251201_ATTACH_02` | `lwlt_rate` |
| 2 | `SERVC_LOCAL_SEJONG_20251201_ATTACH_04` | `lwlt_rate` |
| 3 | `SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2` | `lwlt_rate` |
| 4 | `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | `price_bands`(10억/30억 분할) |
| 5 | `SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR` | `lwlt_rate` |
| 6 | `SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1` | `lwlt_rate` |
| 7 | `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | `price_bands`(10억/30억 분할) |
| 8 | `SERVC_LOCAL_CB_20231020_ATTACH_01` | `price_bands`(10억/30억 분할) |
| 9 | `SERVC_LOCAL_CB_20231020_SIMPLE_LABOR` | `lwlt_rate` |
| 10 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_01` | `lwlt_rate` |
| 11 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_02` | `price_bands`(10억/30억 분할) |
| 12 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | `price_bands`(10억/30억 분할) |
| 13 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_04` | `lwlt_rate` |
| 14 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_05` | `price_bands`(10억/30억 분할) |
| 15 | `SERVC_LOCAL_JNGJ_20260716_ATTACH_06` | `price_bands`(10억/30억 분할) |
| 16 | `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | `lwlt_rate` |

경기 4개 규칙은 `PriceBand.lwlt_rate` 만 바뀌어 다이제스트에 잡히지 않습니다(서명 대상 필드 아님). 이 4개를 포함한 정정 20개는 새 시험 `tests/test_local_lwlt_audit.py` 가 구간값·원문 근거·API 끝단으로 직접 검증합니다.

---

## 6. 끝단 검증 (mock 없이 TestClient)

정정 20개 규칙마다 공고 하한율이 없는 공고를 만들어 평가 API `POST /api/v1/evaluations/analyze` 로 effective 하한율과 최저투찰금액(1원 단위)을 확인했습니다. 최저투찰금액은 예정가격 x 하한율입니다.

| 규칙 ID | 추정가격 | 기대 하한율 | 기대 최저투찰금액 |
| --- | ---: | ---: | ---: |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_02` | 800,000,000 | 87.745 | 701,960,000 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_04` | 800,000,000 | 87.745 | 701,960,000 |
| `SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2` | 800,000,000 | 87.745 | 701,960,000 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | 2,000,000,000 | 77.995 | 1,559,900,000 |
| `SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR` | 300,000,000 | 87.745 | 263,235,000 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1` | 2,000,000,000 | 87.745 | 1,754,900,000 |
| `SERVC_LOCAL_ULSAN_20220810_ATTACH_02` | 4,000,000,000 | 72.995 | 2,919,800,000 |
| `SERVC_LOCAL_CB_20231020_ATTACH_01` | 4,000,000,000 | 72.995 | 2,919,800,000 |
| `SERVC_LOCAL_CB_20231020_SIMPLE_LABOR` | 300,000,000 | 87.745 | 263,235,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_01` | 1,500,000,000 | 87.745 | 1,316,175,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_02` | 700,000,000 | 85.495 | 598,465,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 2,000,000,000 | 77.995 | 1,559,900,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_04` | 4,000,000,000 | 87.745 | 3,509,800,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_05` | 2,000,000,000 | 82.995 | 1,659,900,000 |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_06` | 4,000,000,000 | 72.995 | 2,919,800,000 |
| `SERVC_LOCAL_DAEGU_20260511_ATTACH_01` | 100,000,000 | 87.745 | 87,745,000 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_2` | 300,000,000 | 86.745 | 260,235,000 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_3` | 600,000,000 | 85.495 | 512,970,000 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_4` | 600,000,000 | 86.745 | 520,470,000 |
| `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | 700,000,000 | 85.495 | 598,465,000 |

비정정 규칙은 같은 조건에서 종전 값을 유지합니다(예: 인천 `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` 20억 → 87.995%, 1,759,900,000원). 공고 하한율이 있으면 여전히 공고값이 우선합니다.

---

## 7. 검증 실행

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/ -q -m 'not data_assets'` | 6432 passed, 40 skipped, 3 deselected |
| `uv run mypy src` | Success: no issues found in 119 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 21/21 건 |
| `uv run ruff check <변경 4개 파일>` | All checks passed |
| `uv run ruff format --check <변경 4개 파일>` | 4 files already formatted |

---

## 8. 무변경 보증

- 정정 대상이 아닌 16개 규칙은 `tests/test_local_lwlt_audit.py::test_uncorrected_rules_keep_behavior_fields` 가 동작 필드 스냅샷 다이제스트로 고정 검증합니다.
  - 다이제스트: `dd362b0e55c04c2f837a1b0c5194be4b9ae7c24641e9aa95c591612a36aadc6d`
- 조달청 규칙은 `test_national_rule_unaffected` 가 89.995% 유지와 구간값 없음을 확인합니다.
- 신규 11개 규칙(2단계 추가 5곳)은 값 무변경이며, 전북은 source 문자열만 보정했습니다.

---

## 9. 남은 리스크

| 항목 | 내용 |
| --- | --- |
| 인천·제주·강원·경북·경남 하한율 | 추출 원문에 낙찰하한율 표기가 없어 여전히 조달청 관행 기본값(87.995/84.245)을 씁니다. 원문 원본(HWP) 표 판독이 확보되면 재대조가 필요합니다. |
| 경기 보험 별표 1-5 | 원문이 하한율을 인쇄하지 않습니다. 보험용역 하한율 47.995% 의 원문 근거는 별도 확보 대상입니다. |
| 전북 원문 | 이 워크트리에 없어 재수집 문서의 행 번호로만 보정했습니다. 숫자 행 141/143/145/369/595/802 는 리뷰어 확인값입니다. |
| JNGJ 규칙 대표값 | 분할 규칙(02·03·05·06)과 시설·생활폐기물(01·04) 대표값은 구간값이 없을 때만 쓰이며, 분할 규칙은 추정가격 미상 시 `LWLT_RATE_UNRESOLVED` 로 막힙니다. |
| 평탄 점수 미인쇄 규칙 | 세종 SW·육상운송 등은 종전대로 산식 대입값을 쓰며 이번 변경 대상이 아닙니다. |
