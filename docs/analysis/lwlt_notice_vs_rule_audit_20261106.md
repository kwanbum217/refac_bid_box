# 공고 낙찰하한율 대 적용 규칙 하한율 전수 대조

> **작성일**: 2026-11-06
> **대상**: 최근 12개월(2025-11-06 ~ 2026-11-05) Servc 대표 공고 192,191건 중 적격심사 규칙이 적용된 21,546건
> **비교 축**: `bid_announcements.raw_data.sucsfbidLwltRate`(공고값) 대 `src/app/services/evaluation_rules*.py` 의 적용 규칙 하한율(규칙값)
> **판정**: 규칙 적용 건의 11.95%(1,184건)가 공고값과 규칙값이 다릅니다. 다만 현행 코드는 공고값을 우선하므로 이 불일치는 계산 오류가 아니라 **규칙 ID 선택·폴백·규칙 값의 정합성 진단값**입니다.
> **코드 수정**: 없음. 수정 제안만 5절에 두었습니다.
> **재현**: 부록 A 의 스크립트, 부록 B 의 실행 명령

---

## 1. 요약

최근 12개월 Servc 대표 공고 192,191건 가운데 적격심사 규칙이 적용된 21,546건을 전수로 대조했습니다. 공고값과 규칙값을 모두 알 수 있는 9,904건 중 8,720건(88.05%)이 소수 3자리까지 일치했고, 1,184건(11.95%)이 달랐습니다. 공고 하한율이 없어 비교할 수 없는 건은 0건이었습니다.

| 항목 | 건수 | 비고 |
| --- | --- | --- |
| Servc 대표 공고 | 192,191 | 공고번호·업무구분별 최신 차수만 |
| 규칙 적용 성공 | 21,546 | 차단·미적용 제외 |
| 값 비교 가능 | 9,904 | 공고값과 규칙값이 모두 있는 건 |
| 일치(소수 3자리) | 8,720 | 비교 가능의 88.05% |
| 불일치 | 1,184 | 비교 가능의 11.95% |
| 공고 하한율 없음 | 0 | 공고값이 없거나 0 이하 |
| 규칙값 없음(비교 제외) | 11,642 | 기술용역 11,626건, 기관 규칙 16건 |

**해석의 전제**: 현행 코드는 공고의 `sucsfbidLwltRate` 가 있으면 규칙값보다 우선합니다([`src/app/services/evaluation_rules.py:3698`](/src/app/services/evaluation_rules.py:3698)). 이번 창에서는 규칙이 적용된 21,546건 모두 공고 하한율이 있어 `rate_source=ANNOUNCEMENT` 가 100%였습니다. 따라서 아래 불일치는 **점수 계산 자체의 오류가 아니며**, 규칙 ID 선택, 폴백 경로, 규칙 기본값, 경고 문구의 정합성을 드러내는 진단값입니다. 공고 하한율이 결측인 공고가 생기면 그때는 규칙값이 실제 계산에 쓰입니다.

### 1.1 적용 범위별 분포

| 적용 범위 | 규칙 적용 | 비교 가능 | 불일치 | 불일치율 |
| --- | --- | --- | --- | --- |
| 시·도 규칙(REGION) | 1,855 | 1,855 | 772 | 41.62% |
| 조달청 기본(ALL) | 19,609 | 7,983 | 399 | 5.00% |
| 기관 규칙(INSTITUTION) | 82 | 66 | 13 | 19.70% |

불일치는 시·도 규칙(REGION)에서 41.62%로 가장 높고, 조달청 기본(ALL)은 5.00%, 기관 규칙은 19.70%입니다. 전체 불일치 1,184건 중 772건(65.2%)이 시·도 규칙에서 나옵니다.

---

## 2. 유형별 분포

### 2.1 다섯 유형

공고값과 규칙값의 차이를 소수 3자리로 맞춘 뒤 다음 다섯 유형으로 나눴습니다. 분모는 값 비교가 가능한 9,904건입니다.

| 유형 | 건수 | 비교 가능 대비 | 판정 기준 |
| --- | --- | --- | --- |
| 일치 | 8,720 | 88.05% | 차이 0 (소수 3자리) |
| 공고 +2%p | 7 | 0.07% | 차이 +2.000 |
| 공고 낮음 | 589 | 5.95% | 차이 < 0 |
| 공고 하한율 없음 | 0 | 0.00% | 공고값 없음 또는 0 이하 |
| 그 밖 | 588 | 5.94% | 차이 > 0, +2.000 아님 |
| 합계 | 9,904 | 100.00% | - |

`공고 +2%p` 는 차이가 정확히 +2.000인 경우만 셉니다. 2026-05-26 낙찰하한율 일괄 인상의 흔적을 보기 위한 유형이지만, 실제로는 7건뿐입니다. `그 밖` 588건에는 +2.5, +3.5, +5.0, +7.5, +6.25 등이 섞여 있어, 2.3절에서 차이값을 다시 나눴습니다.

### 2.2 2026-05-26 전후 분리

| 구간 | 비교 가능 | 일치 | 공고 +2%p | 공고 낮음 | 공고 하한율 없음 | 그 밖 | 불일치 | 불일치율 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-26 이전 | 7,015 | 6,151 | 0 | 445 | 0 | 419 | 864 | 12.32% |
| 2026-05-26 이후 | 2,889 | 2,569 | 7 | 144 | 0 | 169 | 320 | 11.08% |

체제 경계 전후의 불일치율은 12.32%와 11.08%로 비슷합니다. 2026-05-26 일괄 인상은 `공고 +2%p` 7건에만 직접 나타났고, 반대 방향인 `-2.000`(공고가 2%p 낮음)은 48건입니다. 즉 체제 차이는 전체 불일치의 주 원인이 아니며, 방향도 한쪽으로 정렬되지 않습니다.

### 2.3 차이값 분포

| 공고값 - 규칙값(%p) | 건수 |
| --- | --- |
| 2.500 | 228 |
| -3.750 | 178 |
| 3.500 | 123 |
| -1.000 | 99 |
| -0.250 | 71 |
| -39.750 | 64 |
| 5.000 | 49 |
| -2.000 | 48 |
| 7.500 | 37 |
| -7.250 | 37 |
| 6.250 | 30 |
| -38.750 | 26 |
| 0.250 | 22 |
| 3.750 | 21 |

양수 상위는 +2.500(228건), +3.500(123건), +5.000(49건), +7.500(37건)이고, 음수 상위는 -3.750(178건), -1.000(99건), -0.250(71건), -39.750(64건)입니다. -39.750·-38.750·-37.500 은 대부분 보험용역 공고에 시·도 GENERAL 별표가 적용된 경우입니다(4.2절). -3.750 은 수리·점검·임대차·소프트웨어의 고시금액 이상 구간에서 반복됩니다(4.4절).

### 2.4 공고값 집중

같은 공고값이 반복되는지 보면 규칙 선택 문제와 규칙 값 문제를 가를 수 있습니다.

| 공고값(%) | 불일치 건수 |
| --- | --- |
| 87.995 | 242 |
| 87.745 | 222 |
| 80.495 | 221 |
| 86.745 | 161 |
| 47.995 | 111 |
| 85.495 | 94 |
| 84.245 | 36 |
| 82.995 | 35 |
| 82.495 | 14 |
| 89.995 | 11 |
| 86.245 | 9 |
| 88.000 | 6 |

47.995 가 111건으로 정확히 보험용역 폴백 111건과 일치합니다. 87.995(242건), 87.745(222건), 80.495(221건), 86.745(161건)은 여러 규칙에 걸쳐 나타나므로, 값만으로는 어느 규칙이 맞는지 확정할 수 없습니다.

### 2.5 적용 규칙별 상위 10

| 규칙 ID | 범위 | 시·도 / 세부유형 | 불일치 | 비교 가능 | 대표 차이(%p) | 대표 공고값 |
| --- | --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4` | REGION | 전라남도 / LAND_TRANSPORT | 137 | 138 | 2.500 (137) | 87.995 (137) |
| `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03` | REGION | 충청남도 / WASTE | 98 | 99 | 3.500 (57) | 87.745 (57) |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4` | REGION | 전라남도 / WASTE | 92 | 159 | -1.000 (69) | 86.745 (69) |
| `SERVC_QUAL_PRE_20250901_ATTACH_15` | ALL | - / REPAIR_INSPECTION | 79 | 283 | -3.750 (76) | 80.495 (76) |
| `SERVC_LOCAL_GN_20230105_ATTACH_01` | REGION | 경상남도 / GENERAL | 59 | 237 | -39.750 (16) | 47.995 (29) |
| `SERVC_LOCAL_GB_20260108_ATTACH_03` | REGION | 경상북도 / WASTE | 57 | 57 | 3.500 (22) | 87.745 (22) |
| `SERVC_QUAL_PRE_20250901_ATTACH_16` | ALL | - / LEASE | 56 | 184 | -3.750 (47) | 80.495 (47) |
| `SERVC_QUAL_PRE_20250901_ATTACH_03` | ALL | - / PASSENGER_TRANSPORT | 50 | 1,102 | -0.250 (33) | 87.745 (33) |
| `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03` | REGION | 충청남도 / WASTE | 49 | 49 | 3.500 (25) | 87.745 (25) |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | REGION | 전남광주통합특별시 / WASTE | 40 | 72 | -1.000 (28) | 86.745 (28) |

### 2.6 시·도별 상위 10

| 시·도 | 불일치 |
| --- | --- |
| 전남광주통합특별시 | 157 |
| 전라남도 | 154 |
| 충청남도 | 148 |
| 경상북도 | 72 |
| 경기도 | 64 |
| 경상남도 | 59 |
| 서울특별시 | 43 |
| 강원특별자치도 | 26 |
| 인천광역시 | 20 |
| 전북특별자치도 | 17 |

전남광주통합특별시(157건)와 전라남도(154건)는 2026-07-16 통합 전후의 명칭 차이일 뿐 실질적으로 같은 권역입니다. 두 값을 합치면 311건으로, 충청남도(148건)보다 많습니다.

---

## 3. 대표 사례

### 3.1 유형별 3건

| 유형 | 공고번호 | 공고일 | 시·도 | 공고값 | 규칙값 | 규칙 ID |
| --- | --- | --- | --- | --- | --- | --- |
| 일치 | `R25BK01002047` | 2025-12-07 | 전남광주통합특별시 | 86.745 | 86.745 | `SERVC_QUAL_MOE_CDW_ATTACH_03` |
| 일치 | `R25BK01120099` | 2025-11-06 | - | 87.995 | 87.995 | `SERVC_QUAL_PRE_20250901_ATTACH_03` |
| 일치 | `R25BK01120111` | 2025-11-10 | - | 87.995 | 87.995 | `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| 공고 +2%p | `R26BK01730527` | 2026-09-22 | - | 82.495 | 80.495 | `SERVC_INST_KDHC_20260101_WASTE` |
| 공고 +2%p | `R26BK01745985` | 2026-09-28 | - | 82.495 | 80.495 | `SERVC_INST_KDHC_20260101_WASTE` |
| 공고 +2%p | `R26BK01761398` | 2026-10-07 | - | 82.495 | 80.495 | `SERVC_INST_KDHC_20260101_LEASE` |
| 공고 낮음 | `R25BK01112297` | 2025-11-10 | - | 87.745 | 87.995 | `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| 공고 낮음 | `R25BK01118012` | 2025-11-12 | - | 80.495 | 84.245 | `SERVC_QUAL_PRE_20250901_ATTACH_16` |
| 공고 낮음 | `R25BK01140714` | 2025-11-10 | - | 80.495 | 84.245 | `SERVC_QUAL_PRE_20250901_ATTACH_16` |
| 공고 하한율 없음 | - | - | - | - | - | 해당 없음 |
| 그 밖 | `R25BK01132770` | 2025-11-06 | 강원특별자치도 | 87.995 | 85.495 | `SERVC_LOCAL_GANGWON_20230611_ATTACH_01` |
| 그 밖 | `R25BK01135808` | 2025-11-06 | 서울특별시 | 87.995 | 87.745 | `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` |
| 그 밖 | `R25BK01136538` | 2025-11-19 | 경기도 | 84.245 | 80.495 | `SERVC_QUAL_PRE_20250901_ATTACH_09` |

### 3.2 기제를 보여주는 사례

| 사례 | 공고번호 | 낙찰방법명 | 공고값 → 규칙값 | 판독 |
| --- | --- | --- | --- | --- |
| 보험용역 폴백 | `R25BK01147624` | 적격심사제-보험용역 적격심사 추정가격 5억원이상 | 47.995 → 85.495 | 시·도 규칙에 보험 세부유형이 없어 GENERAL 별표로 폴백했습니다. 공고값 47.995는 조달청 보험용역 규칙값과 일치합니다. |
| 전남 여객 육상운송 | `R25BK01179833` | 적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만 | 87.995 → 85.495 | 구판 규칙은 원문 미인쇄 값을 역산해 85.495로 등록했지만, 공고 137건이 모두 87.995입니다. |
| 수리·점검 고시금액 이상 | `R25BK01168447` | 적격심사제-수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상 | 80.495 → 84.245 | 규칙은 단일 대표값 84.245만 갖고, 고시금액 이상 구간의 80.495를 표현하지 못합니다. |
| 화물 표기와 여객 실제 | `R26BK01759197` | 적격심사제-화물 육상운송용역 적격심사 추정가격 5억원이상 | 89.995 → 82.495 | 조달분류는 `도로여객운송서비스`, 공고명은 통학버스 임차입니다. 낙찰방법명의 '화물' 표기를 그대로 따라 FREIGHT 규칙이 적용됐습니다. |
| 기관 규칙 구간 선택 | `R26BK01764484` | 적격심사제-학술연구용역 적격심사 추정가격 5억원 미만 고시금액 이상 | 82.495 → 86.245 | 규칙의 두 구간(82.495/86.245) 중 추정가격으로 86.245를 골랐으나, 공고는 다른 구간 값 82.495입니다. |

---

## 4. 규칙 오적용으로 의심되는 군

### 4.1 판정 기준

다음 두 신호를 함께 봤습니다.

1. **규칙 안에서 체계적**: 같은 규칙에서 같은 차이 또는 같은 공고값이 반복되고, 불일치가 비교 가능 건의 일정 비율 이상입니다. 자동 기준은 `불일치 3건 이상 + 지배 차이 80% 이상`입니다.
2. **기제가 설명됨**: 낙찰방법명, 조달분류, 공고명, 규칙의 세부유형·구간 선언을 대조해 "왜 이 규칙이 선택됐는지"를 확인했습니다.

이 기준으로 자동 통과한 군은 17개 규칙입니다. 다만 자동 기준은 한 규칙 안의 차이가 여러 값으로 흩어진 경우(예: 지역 폐기물)를 놓치므로, 4.2절과 4.3절에서 공고값 분포를 함께 보고 수동으로 보강했습니다. 4.2~4.4절의 공고값·차이 분포는 상위 값만 표시하므로, 표의 합계가 불일치 건수와 다를 수 있습니다.

### 4.2 시·도 GENERAL 폴백 (208건, 역방향 4건 포함)

시·도 규칙에 요청한 세부유형이 없으면 코드는 **조용히 같은 시·도의 GENERAL 별표로 폴백**합니다([`src/app/services/evaluation_rules.py:2368-2373`](/src/app/services/evaluation_rules.py:2368)). 표의 합계는 204건이며, 방향이 반대인 `SIMPLE_LABOR <- GENERAL` 4건을 더하면 208건입니다. 전체 불일치의 17.6%(208/1,184)를 차지합니다.

| 요청 세부유형 | 적용 경로 | 불일치 | 공고값 분포 | 대표 사례 |
| --- | --- | --- | --- | --- |
| 보험용역 | 시·도 GENERAL 폴백 | 111 | 47.995(111) | `R25BK01147624` 서울특별시 47.995→85.495 |
| 폐기물처리용역 | 시·도 GENERAL 폴백 | 43 | 85.495(19), 82.995(11), 80.495(4), 86.245(3), 84.245(2), 87.745(2) | `R25BK01157722` 경상남도 84.245→87.745 |
| 시설분야용역 | 시·도 GENERAL 폴백 | 24 | 87.995(18), 87.745(3), 89.995(3) | `R25BK01135808` 서울특별시 87.995→87.745 |
| 육상운송용역 | 시·도 GENERAL 폴백 | 11 | 87.995(6), 80.495(4), 84.245(1) | `R25BK01132770` 강원특별자치도 87.995→85.495 |
| 소프트웨어용역 | 시·도 GENERAL 폴백 | 9 | 87.995(7), 84.245(1), 80.495(1) | `R25BK01159442` 제주특별자치도 87.995→87.745 |
| 임대차 | 시·도 GENERAL 폴백 | 4 | 84.245(3), 86.245(1) | `R25BK01143172` 충청북도 84.245→87.745 |
| 수리·점검용역 | 시·도 GENERAL 폴백 | 1 | 88.000(1) | `R25BK01210931` 경기도 88.000→87.745 |
| 수요기관 지정형 | 시·도 GENERAL 폴백 | 1 | 80.495(1) | `R26BK01524274` 경기도 80.495→85.495 |

가장 명확한 것은 보험용역입니다. 요청 세부유형은 `INSURANCE` 인데 시·도 규칙에는 보험 별표가 없어 GENERAL 로 폴백했고, 111건 전부 공고값이 47.995입니다. 47.995는 조달청 보험용역 규칙(`SERVC_QUAL_PRE_20250901_ATTACH_02`, 현행 대응 규칙)의 값과 정확히 일치합니다. 적용된 시·도 GENERAL 의 구간값은 85.495~87.995이므로 차이가 -37.5~-39.75%p에 이릅니다.

폐기물 43건과 시설분야 24건도 같은 구조입니다. 공고값은 조달청 또는 인접 시·도의 해당 세부유형 값에 가깝고, 적용된 GENERAL 구간값은 다릅니다. 다만 이 폴백이 항상 틀렸다고 단정할 수는 없습니다. 시·도 예규가 해당 세부유형을 GENERAL 별표로 처리하도록 규정했을 가능성이 있어, 원문 확인 전에는 "규칙 선택이 공고 표기와 어긋난다"는 사실만 확정할 수 있습니다.

`SIMPLE_LABOR <- GENERAL` 4건은 방향이 반대입니다. 요청은 GENERAL 인데 SIMPLE_LABOR 가 적용됐습니다. 대구 3건은 공고값 80.495가 대구 폐기물 규칙값과 일치해, 낙찰방법명에 세부유형이 없는 공고를 단순노무로 확정한 경로를 의심하게 합니다.

### 4.3 시·도 세부유형 규칙의 값·구간 불일치 (503건)

시·도 규칙 자체의 하한율 또는 구간 경계가 공고 표기와 다른 군입니다. GENERAL 폴백과 달리, 요청 세부유형과 적용 규칙은 일치합니다.

| 규칙 ID | 대상 | 규칙 대표값 | 불일치 | 비교 가능 | 공고값 분포 | 차이 분포 |
| --- | --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03` | 충청남도 폐기물(2020 구판) | 84.245 | 98 | 99 | 87.745(57), 86.745(23), 85.495(14), 82.995(4) | 3.500(57), 6.250(20), 5.000(14), 2.500(7) |
| `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03` | 충청남도 폐기물(2026 현행) | 84.245 | 49 | 49 | 87.745(25), 86.745(10), 85.495(9), 82.995(3) | 3.500(25), 5.000(9), 6.250(9), 2.500(4) |
| `SERVC_LOCAL_GB_20260108_ATTACH_03` | 경상북도 폐기물(2026) | 84.245 | 57 | 57 | 87.745(22), 86.745(22), 85.495(11), 80.495(1) | 3.500(22), 2.500(22), 1.250(11), -3.750(1) |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4` | 전라남도 폐기물(2023 구판) | 87.745 | 92 | 159 | 86.745(69), 85.495(21), 84.245(2) | -1.000(69), 2.500(18), 7.500(3), -3.500(2) |
| `SERVC_LOCAL_JNGJ_20260716_ATTACH_03` | 전남광주 폐기물(2026) | 84.245 | 40 | 72 | 86.745(28), 85.495(10), 82.995(2) | -1.000(28), 2.500(10), 5.000(2) |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4` | 전라남도 육상운송(2023 구판) | 85.495 | 137 | 138 | 87.995(137) | 2.500(137) |
| `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5` | 광주광역시 육상운송(2022 구판) | 85.495 | 19 | 19 | 87.995(19) | 2.500(19) |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4` | 전라남도 시설분야(2023 구판) | 87.745 | 11 | 11 | 87.995(11) | 0.250(9), 0.500(2) |

- **전남·광주 육상운송(156건)**: 규칙은 원문에 인쇄되지 않은 값을 평점산식과 통과점수로 역산해 85.495로 등록했습니다([`src/app/services/evaluation_rules_local.py:274-284`](/src/app/services/evaluation_rules_local.py:274)). 그런데 전남 137/138건, 광주 19/19건의 공고값이 모두 87.995입니다. 같은 파일의 기본값 `_LOCAL_LWLT_BY_SERVICE["LAND_TRANSPORT"] = "87.995"`([`src/app/services/evaluation_rules_local.py:390`](/src/app/services/evaluation_rules_local.py:390))와도 어긋납니다. 역산 가정(통과점수·평점계수·기준비율)을 재검토할 근거가 강합니다.
- **충남 폐기물(147건)**: 2020 구판 98/99건, 2026 현행 49/49건이 불일치입니다. 규칙은 고시금액/5억 경계의 3구간(84.245/80.495)을 선언하지만, 공고의 낙찰방법명은 2억/5억/15억/30억 경계를 쓰고 공고값은 87.745/86.745/85.495/82.995로 갈립니다. 구간 경계 자체가 다릅니다.
- **경북 폐기물(57건)**: 57/57건 불일치. 공고값은 2억 미만 86.745, 2~5억 87.745, 5~15억 85.495로 구간별로 다르지만, 규칙은 5억 미만 70·k20, 5억 이상 50·k4의 두 구간만 선언합니다.
- **전남 폐기물(92건)·전남광주 폐기물(40건)**: 공고의 `5억원 미만 2억원 이상` 구간에서 공고값 86.745가 69건·28건 반복됩니다. 규칙은 같은 구간을 87.745로 선언해 -1.000이 체계적으로 납니다.
- **전남 시설분야(11건)**: 공고값 87.995, 규칙값 87.745로 +0.250입니다. 차이는 작지만 11/11건 전부 같은 방향입니다.

이 군은 "규칙이 오적용됐다"기보다 **규칙에 등록한 값 또는 구간 경계가 공고 표기와 다르다**는 신호입니다. 원문 대조로 어느 쪽이 맞는지 확정해야 합니다.

### 4.4 조달청 단일 대표값·구간 누락 (212건)

| 규칙 ID | 대상 | 규칙 대표값 | 공고값 분포 | 불일치 | 비교 가능 | 차이 분포 |
| --- | --- | --- | --- | --- | --- | --- |
| `SERVC_QUAL_PRE_20250901_ATTACH_15` | 수리·점검(개정 전) | 84.245 | 80.495(76), 87.995(2), 87.745(1) | 79 | 283 | -3.750(76), 3.750(2), 3.500(1) |
| `SERVC_QUAL_PRE_20250901_ATTACH_16` | 임대차(개정 전) | 84.245 | 80.495(47), 87.745(5), 87.995(2) | 56 | 184 | -3.750(47), 3.500(5), 3.750(2) |
| `SERVC_QUAL_PRE_20250901_ATTACH_05` | 소프트웨어 비대상(개정 전) | 84.245 | 80.495(21), 87.995(1) | 22 | 100 | -3.750(21), 3.750(1) |
| `SERVC_QUAL_PRE_20250901_ATTACH_17` | 수요기관 지정형(개정 전) | 84.245 | 80.495(17), 87.995(9), 100.000(2) | 31 | 113 | -3.750(17), 3.750(9), 15.755(2) |
| `SERVC_QUAL_POST_20260526_ATTACH_17` | 임대차(현행, 고시금액 미만) | 86.245 | 87.745(10), 84.245(2) | 12 | 135 | 1.500(10), -2.000(2) |
| `SERVC_QUAL_POST_20260526_ATTACH_15` | 수리·점검(현행, 고시금액 미만) | 86.245 | 84.245(5) | 5 | 109 | -2.000(5) |
| `SERVC_QUAL_POST_20260526_ATTACH_08` | 폐기물(현행, 고시금액 미만) | 86.245 | 84.245(3), 87.745(3), 86.745(1) | 7 | 125 | -2.000(3), 1.500(3), 0.500(1) |

- 개정 전 수리·점검(79/283), 임대차(56/184), 소프트웨어 비대상(22/100), 수요기관 지정형(31/113)의 주된 패턴이 **84.245 → 80.495(-3.750)** 입니다. 낙찰방법명이 `고시금액 이상`을 명시한 건에서 집중됩니다. 네 규칙 모두 `price_bands` 없이 단일 `lwlt_rate` 만 선언해, 고시금액 미만/이상 구간을 표현하지 못합니다. 수요기관 지정형은 87.995(9건)·100.000(2건)도 섞여 있어 지배 패턴의 비중이 17/31입니다.
- 현행 임대차(12/135)는 반대로 **86.245 → 87.745(+1.500)** 입니다. `고시금액 미만` 구간의 실제 값이 87.745일 가능성을 보여줍니다.
- 현행 수리·점검(5/109)은 86.245 → 84.245(-2.000), 현행 폐기물(7/125)은 86.245 → 84.245/87.745로 갈립니다. 현행 규칙도 구간별 값을 완전히 담지 못한 사례가 있습니다.

이 군은 규칙 ID 선택이 아니라 **규칙 스키마의 구간 표현 부족**이 원인입니다. 공고값이 우선되므로 현재 계산은 맞지만, 규칙 기본값과 경고는 틀린 값을 말하게 됩니다.

### 4.5 2026-05-26 체제 차이 (65건)

| 구간 | 규칙 ID | 공고값 → 규칙값 | 건수 | 판독 |
| --- | --- | --- | --- | --- |
| 2026-05-26 이후 | `SERVC_QUAL_POST_20260526_ATTACH_01` | 87.995/87.745 → 89.995 | 23/379 | 공고일이 인상 시행일 이후인데 공고문은 개정 전 값을 씁니다. |
| 2026-07-27 이후 | `SERVC_QUAL_POST_20260727_ATTACH_03` | 87.995 → 89.995 | 7/73 | 여객 육상운송도 같은 방향입니다. |
| 2026-05-26 이전 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | 87.745 → 87.995 | 35/1,277 | 차이 -0.250. 체제 차이라기보다 표기 관행 차이입니다. |

체제 경계 전후 불일치율이 12.32%와 11.08%로 비슷하고, `+2.000` 7건 대 `-2.000` 48건으로 방향이 섞여 있어, **2%p 일괄 인상만으로 전체 불일치를 설명할 수 없습니다**. 인상 시행일 이후에도 개정 전 값을 쓰는 공고가 일부 있다는 사실은 확인됩니다.

### 4.6 기관 규칙 (13건)

- **한국지역난방공사 폐기물(6건)**: 규칙 84.245, 공고값 82.495가 5건입니다. 규칙의 두 구간(80.495/84.245) 사이 값이라 구간 선택 또는 기관 규칙 값 중 하나가 어긋납니다.
- **한국농어촌공사 학술연구(4건)**: 규칙의 두 구간(82.495/86.245) 중 추정가격으로 86.245를 골랐지만, 공고값은 82.495입니다. 4건 모두 공고값이 규칙의 다른 구간값과 정확히 일치해, 추정가격 구간 판정 자체를 확인할 필요가 있습니다.
- 나머지 3건(KDHC 임대차·SW, KRC 임대차)도 공고값이 82.495로 같습니다. 기관 규칙의 구간값과 공고값이 어긋나는 같은 패턴이 기관별로 반복됩니다.

### 4.7 낙찰방법명과 실제 서비스 불일치 (9건)

- **화물 표기 → 여객 실제(6건)**: `SERVC_QUAL_POST_20260526_ATTACH_11`(화물)이 적용됐지만, 조달분류는 `도로여객운송서비스`, 공고명은 통학버스 임차입니다. 공고값 89.995는 여객 현행 규칙값과 일치합니다. 낙찰방법명의 '화물' 표기를 그대로 신뢰한 결과입니다.
- **대구 단순노무(3건)**: 낙찰방법명에 세부유형이 없는데 SIMPLE_LABOR 규칙이 적용됐고, 공고값 80.495는 대구 폐기물 규칙값과 일치합니다. 세부유형 미판정 시 GENERAL 과 SIMPLE_LABOR 를 모두 후보로 두고 차단하는 경로([`src/app/services/evaluation_rules.py:2330-2355`](/src/app/services/evaluation_rules.py:2330))를 우회한 사례로 보입니다.

### 4.8 표기·반올림 차이 (약 100건)

-0.250(71건), +0.250(22건), +0.005(7건), -0.040(1건), +0.255(1건) 등은 규칙 구조가 아니라 소수 표기 관행에서 생길 수 있는 차이입니다. 예를 들어 87.995와 87.745의 0.25%p 차이는 `.995`와 `.745` 표기 규칙이 섞인 결과일 수 있습니다. 우선순위는 낮지만, 같은 규칙에서 반복되는 0.25 차이는 원문 표기 확인 대상입니다. 나머지 약 70건은 규칙별 1~2건의 소규모 군으로, 4.2~4.7절 어디에도 속하지 않는 잔여입니다.

### 4.9 자동 기준 통과 군

| 규칙 ID | 범위 / 시·도 / 세부유형 | 규칙 대표값 | 지배 공고값(차이) | 불일치 | 비교 가능 | 지배 비중 |
| --- | --- | --- | --- | --- | --- | --- |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4` | REGION / 전라남도 / LAND_TRANSPORT | 85.495 | 87.995 (차이 2.500) | 137 | 138 | 100.0% |
| `SERVC_QUAL_PRE_20250901_ATTACH_15` | ALL / - / REPAIR_INSPECTION | 84.245 | 80.495 (차이 -3.750) | 79 | 283 | 96.2% |
| `SERVC_QUAL_PRE_20250901_ATTACH_16` | ALL / - / LEASE | 84.245 | 80.495 (차이 -3.750) | 56 | 184 | 83.9% |
| `SERVC_QUAL_PRE_20250901_ATTACH_01` | ALL / - / FACILITY | 87.995 | 87.745 (차이 -0.250) | 35 | 1,277 | 100.0% |
| `SERVC_QUAL_POST_20260526_ATTACH_01` | ALL / - / FACILITY | 89.995 | 87.995 (차이 -2.000) | 23 | 379 | 82.6% |
| `SERVC_QUAL_PRE_20250901_ATTACH_05` | ALL / - / SW_NON_SME | 84.245 | 80.495 (차이 -3.750) | 22 | 100 | 95.5% |
| `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5` | REGION / 광주광역시 / LAND_TRANSPORT | 85.495 | 87.995 (차이 2.500) | 19 | 19 | 100.0% |
| `SERVC_QUAL_POST_20260526_ATTACH_17` | ALL / - / LEASE | 86.245 | 87.745 (차이 1.500) | 12 | 135 | 83.3% |
| `SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4` | REGION / 전라남도 / FACILITY | 87.745 | 87.995 (차이 0.250) | 11 | 11 | 81.8% |
| `SERVC_QUAL_POST_20260727_ATTACH_03` | ALL / - / PASSENGER_TRANSPORT | 89.995 | 87.995 (차이 -2.000) | 7 | 73 | 100.0% |
| `SERVC_INST_KDHC_20260101_WASTE` | INSTITUTION / - / WASTE | 84.245 | 82.495 (차이 2.000) | 6 | 9 | 83.3% |
| `SERVC_QUAL_POST_20260526_ATTACH_11` | ALL / - / FREIGHT | 82.495 | 89.995 (차이 7.500) | 6 | 39 | 100.0% |
| `SERVC_QUAL_MOE_CDW_ATTACH_04` | ALL / - / WASTE_MOE | 87.745 | 86.245 (차이 -1.500) | 5 | 961 | 80.0% |
| `SERVC_QUAL_POST_20260526_ATTACH_15` | ALL / - / REPAIR_INSPECTION | 86.245 | 84.245 (차이 -2.000) | 5 | 109 | 100.0% |
| `SERVC_INST_KRC_20260624_ACADEMIC` | INSTITUTION / - / ACADEMIC | 86.245 | 82.495 (차이 -3.750) | 4 | 4 | 100.0% |
| `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | REGION / 대구광역시 / SIMPLE_LABOR | 87.745 | 80.495 (차이 -7.250) | 3 | 3 | 100.0% |
| `SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E` | ALL / - / ACADEMIC | 80.495 | 82.995 (차이 2.500) | 3 | 37 | 100.0% |

---

## 5. 사용자 결정 항목

### 5.1 결정이 필요한 항목

| 항목 | 선택지 | 권고 | 근거 |
| --- | --- | --- | --- |
| 시·도 세부유형 폴백 | (A) 현행 GENERAL 폴백 유지, (B) 폴백 시 경고만 강화, (C) 폴백 대신 차단, (D) 조달청 동일 세부유형으로 폴백 | (B) 또는 (D) | 보험용역 111건이 47.995 대 85.495~87.995로 -37.5~-39.75%p 벌어집니다. 최소한 현재 경고가 사용자에게 보이는지 확인하고, 조달청 동일 세부유형 규칙이 있으면 그쪽으로 폴백하는 편이 공고 표기와 맞습니다. |
| 공고값 우선 원칙 | (A) 현행 유지, (B) 불일치 시 차단, (C) 불일치 경고를 별도 지표로 집계 | (A) 유지 + (C) | 이번 창에서는 공고값이 100% 존재해 규칙값이 계산에 쓰이지 않았습니다. 공고값 우선은 실제 입찰 조건을 따르는 동작이므로 유지하되, 불일치율을 운영 지표로 올려 규칙 드리프트를 감시하는 편이 낫습니다. |
| 시·도 육상운송 역산값 | (A) 85.495 유지, (B) 87.995로 정정, (C) 원문 재수집 후 결정 | (C) | 전남 137/138, 광주 19/19가 87.995입니다. 규칙 주석도 "원문 미인쇄, 역산"이라고 밝히므로, 원문 재확인 없이 값을 바꾸지 않는 편이 안전합니다. |
| 시·도 폐기물 구간 경계 | (A) 현행 고시금액/5억 유지, (B) 공고의 2억/5억/15억/30억 경계로 재모델링, (C) 원문 재확인 | (C) → 필요 시 (B) | 충남 147건, 경북 57건, 전남 132건이 구간 경계 차이를 보입니다. 규칙 스키마(`PriceBand`)로 표현 가능한지 먼저 확인해야 합니다. |
| 조달청 개정 전 단일 대표값 | (A) 84.245 유지, (B) 고시금액 미만/이상 구간 추가, (C) 원문 재확인 | (C) → (B) | 수리·점검 79, 임대차 56, SW 22, 수요기관지정 31이 같은 84.245→80.495 패턴입니다. 네 규칙이 같은 원인을 공유하므로 한 번의 원문 확인으로 일괄 판단할 수 있습니다. |
| 낙찰방법명 신뢰도 | (A) 현행처럼 낙찰방법명만 사용, (B) 조달분류·공고명과 교차 확인, (C) 불일치 시 차단 | (B) | 화물/여객 6건, 대구 단순노무 3건에서 낙찰방법명과 실제 서비스가 어긋났습니다. |
| 2026-05-26 체제 처리 | (A) 현행(공고일로 규칙 선택, 공고값 우선) 유지, (B) 공고값이 개정 전 값이면 경고 | (A) + (B) | 인상 시행일 이후 23+7건이 개정 전 값을 씁니다. 계산은 공고값을 따르므로 유지하되, 경고로 노출할 수 있습니다. |

### 5.2 코드 수정 제안 (이번 Task 에서 적용하지 않음)

1. **폴백 정책 명시**: `_select_local_rule` 의 GENERAL 폴백을 그대로 두더라도, 폴백 발생 시 `warnings` 에 "요청 세부유형 X 가 없어 GENERAL 을 적용했다"는 사실과 적용 규칙 ID를 남기고, 가능하면 조달청 동일 세부유형 규칙을 먼저 찾도록 순서를 바꿉니다. 현재는 경고 문구만 있고 사용자 화면 노출 여부가 확인되지 않습니다.
2. **구간 표현 보강**: 개정 전 수리·점검·임대차·SW·수요기관지정 규칙에 `price_bands` 를 추가해 고시금액 미만/이상 값을 분리합니다. 시·도 폐기물 규칙은 공고 낙찰방법명의 2억/5억/15억/30억 경계와 규칙 `PriceBand` 경계를 대조해 필요한 구간을 추가합니다.
3. **규칙 선택 교차 확인**: 시·도 규칙 선택 시 낙찰방법명과 조달분류(`pubPrcrmnt*`)가 충돌하면 차단하거나 경고합니다. 화물/여객, 대구 단순노무 사례가 대상입니다.
4. **불일치 모니터링**: `sucsfbidLwltRate` 와 규칙값의 불일치를 규칙 ID별로 집계하는 읽기 전용 지표를 추가합니다. 이번 부록 스크립트를 그대로 정기 실행할 수 있습니다.
5. **테스트 고정**: 4.2~4.9절의 대표 공고번호를 회귀 테스트 픽스처로 고정해, 규칙 값이나 폴백 정책을 바꿀 때 불일치 건수가 의도대로 움직이는지 확인합니다.

### 5.3 이번 조사에서 하지 않은 것

- 코드, 규칙 값, DB, 마이그레이션을 수정하지 않았습니다.
- 공고 원문(별표 PDF/HWP)을 다시 수집하거나 대조하지 않았습니다. 4절의 "규칙 값이 틀렸다"는 판정은 공고값과의 체계적 차이에 근거한 가설이며, 원문 확인 전에는 확정이 아닙니다.
- `data/reference/rule_coverage_ledger.yaml` 을 갱신하지 않았습니다. 이 문서는 별도 조사 기록입니다.

---

## 부록 A. 집계 스크립트 전문

저장소 루트에서 아래 스크립트를 저장해 실행했습니다. `scripts/report_rule_coverage.py` 의 SQL·판정 함수를 그대로 재사용하되, 공고번호·공고일·추정가격을 함께 남겨 대조에 씁니다. DB 는 READ ONLY 트랜잭션에서 SELECT 만 하며 `LIKE` 를 쓰지 않습니다.

```python
"""공고 낙찰하한율(sucsfbidLwltRate)과 적용 규칙 하한율의 전수 대조.

scripts/report_rule_coverage.py 의 collect_records 와 같은 SQL·같은 판정 함수를
그대로 쓰되, 공고번호·공고일·추정가격을 함께 남겨 대조에 쓴다. DB 는 READ ONLY
트랜잭션에서 SELECT 만 한다.

사용법 (저장소 루트에서):
    uv run python audit_lwlt_notice_vs_rule.py --months 12 --category Servc
    uv run python audit_lwlt_notice_vs_rule.py --method-code 낙030001 --format json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path.cwd()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

import src.app.services.evaluation_rules as er  # noqa: E402
import src.app.services.evaluation_rules_institution as eri  # noqa: E402
import src.app.services.evaluation_rules_local as erl  # noqa: E402
from src.app.core.db import engine  # noqa: E402

RULE_SCOPE_ALL = "ALL"
RULE_SCOPE_INSTITUTION = "INSTITUTION"
RULE_SCOPE_REGION = "REGION"

TYPE_MATCH = "일치"
TYPE_NOTICE_PLUS_2P = "공고 +2%p"
TYPE_NOTICE_LOWER = "공고 낮음"
TYPE_NOTICE_MISSING = "공고 하한율 없음"
TYPE_OTHER = "그 밖"
TYPE_RULE_MISSING = "규칙값 없음"
TYPE_ORDER = (
    TYPE_MATCH,
    TYPE_NOTICE_PLUS_2P,
    TYPE_NOTICE_LOWER,
    TYPE_NOTICE_MISSING,
    TYPE_OTHER,
)

REGIME_BOUNDARY = date(2026, 5, 26)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def collect_rows(
    *,
    months: int,
    category: str,
    method_code: str,
    today: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """collect_records 와 같은 필터·중복 제거로 공고 행과 판정 레코드를 모은다."""
    rrc = _load_module("report_rule_coverage", PROJECT_ROOT / "scripts/report_rule_coverage.py")
    window_from = rrc._months_ago(today, months)
    window_end = today + timedelta(days=1)

    best_rows: list[Any] = []
    with engine.connect() as conn:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        institutions = rrc._load_institutions(conn)
        announcement_sql = rrc.ANNOUNCEMENT_SQL.replace(
            "SELECT bid_ntce_no,", "SELECT bid_ntce_dt, bid_ntce_no,", 1
        )
        result = conn.execution_options(stream_results=True).execute(
            text(announcement_sql),
            {
                "category": category,
                "window_from": datetime.combine(window_from, day_time.min),
                "window_end": datetime.combine(window_end, day_time.min),
            },
        )
        current_key: tuple[str, str] | None = None
        best_row: Any = None
        best_ord = -1
        scanned = 0
        for row in result:
            scanned += 1
            raw_data = rrc._as_dict(row.raw_data)
            if method_code and str(raw_data.get("sucsfbidMthdCd") or "").strip() != method_code:
                continue
            key = (row.bid_ntce_no, row.category)
            if key != current_key:
                if best_row is not None:
                    best_rows.append(best_row)
                current_key = key
                best_row = None
                best_ord = -1
            ord_key = rrc._ord_key(row.bid_ntce_ord)
            if best_row is None or ord_key > best_ord:
                best_row = row
                best_ord = ord_key
        if best_row is not None:
            best_rows.append(best_row)
        result.close()
        regimes = rrc.lookup_attachment_regimes(
            conn, (rrc.attachment_regime_key(row) for row in best_rows)
        )

    outcomes: list[dict[str, Any]] = []
    for row in best_rows:
        record = rrc._to_record(row, institutions, regimes.get(rrc.attachment_regime_key(row)))
        outcomes.append(
            {
                "row": {
                    "bid_ntce_no": row.bid_ntce_no,
                    "bid_ntce_ord": str(row.bid_ntce_ord),
                    "bid_ntce_dt": row.bid_ntce_dt,
                    "presmpt_prce": row.presmpt_prce,
                    "dminstt_nm": row.dminstt_nm,
                    "category": row.category,
                    "cntrct_mthd_nm": row.cntrct_mthd_nm,
                },
                "raw_data": rrc._as_dict(row.raw_data),
                "record": record,
                "institution": institutions.get(str(record.get("dminstt_cd") or "")),
            }
        )
    meta = {
        "scanned_rows": scanned,
        "representative_rows": len(best_rows),
        "window_from": window_from.isoformat(),
        "window_to": today.isoformat(),
    }
    return outcomes, meta


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        text_value = str(value).strip()
        if not text_value:
            return None
        return Decimal(text_value)
    except (ArithmeticError, TypeError, ValueError):
        return None


def _q3(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"))


def _rule_rates(rule: Any, estimated_price: Decimal | None) -> tuple[Decimal | None, str | None]:
    """규칙의 적용 하한율. 구간 인쇄값이 있으면 그 구간, 없으면 규칙 대표값."""
    band_rate, band_label, _reason = er._band_lwlt_rate(rule, estimated_price)
    if band_rate is not None:
        return band_rate, band_label
    return rule.lwlt_rate, None


def _scope_of(result: Any) -> str:
    rule = result.rule
    if rule is None:
        return "NONE"
    if rule.institution_scope == RULE_SCOPE_INSTITUTION:
        return RULE_SCOPE_INSTITUTION
    if rule.institution_scope == RULE_SCOPE_REGION:
        return RULE_SCOPE_REGION
    return RULE_SCOPE_ALL


def _classify(notice: Decimal | None, rule_rate: Decimal | None) -> str:
    if rule_rate is None:
        return TYPE_RULE_MISSING
    if notice is None or notice <= 0:
        return TYPE_NOTICE_MISSING
    diff = _q3(notice) - _q3(rule_rate)
    if diff == 0:
        return TYPE_MATCH
    if diff == Decimal("2.000"):
        return TYPE_NOTICE_PLUS_2P
    if diff < 0:
        return TYPE_NOTICE_LOWER
    return TYPE_OTHER


def _known_rule_rates() -> dict[Decimal, list[dict[str, Any]]]:
    """다른 규칙이 같은 하한율을 선언하는지 대조할 색인."""
    rules: list[Any] = []
    for name in (
        "POST_20260727_RULES",
        "POST_20260526_RULES",
        "PRE_20250901_RULES",
        "PRE_20230501_RULES",
        "MOE_CDW_RULES",
        "MOIS_ACADEMIC_BAND_RULES",
        "MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES",
        "MOIS_TECH_BAND_RULES",
    ):
        rules.extend(getattr(er, name, ()))
    rules.extend(erl.LOCAL_RULES)
    rules.extend(eri.INSTITUTION_RULES)

    index: dict[Decimal, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, Decimal]] = set()
    for rule in rules:
        rates = {rule.lwlt_rate}
        rates.update(band.lwlt_rate for band in (rule.price_bands or ()))
        for rate in rates:
            if rate is None:
                continue
            key = (rule.rule_id, rate)
            if key in seen:
                continue
            seen.add(key)
            index[rate].append(
                {
                    "rule_id": rule.rule_id,
                    "region_name": rule.region_name,
                    "service_type": rule.service_type,
                    "table_name": rule.table_name,
                    "scope": _scope_of(_FakeResult(rule)),
                }
            )
    return index


class _FakeResult:
    def __init__(self, rule: Any) -> None:
        self.rule = rule


def build_report(outcomes: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    known_rates = _known_rule_rates()
    counters: Counter = Counter()
    regime_counts: dict[str, Counter] = {"pre": Counter(), "post": Counter()}
    by_rule: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "compared": 0,
            "match": 0,
            "mismatch": 0,
            "diffs": Counter(),
            "notice_values": Counter(),
            "missing": 0,
            "rule_missing": 0,
            "rule_rate": None,
            "service_type": None,
            "table_name": None,
            "scope": None,
            "region_name": None,
            "effective_date": None,
            "own_band_match": 0,
            "same_region_hits": Counter(),
            "same_type_hits": Counter(),
            "price_bands": [],
            "method_names": Counter(),
            "institution_names": Counter(),
            "service_div": Counter(),
            "samples": [],
        }
    )
    by_sido_mismatch: Counter = Counter()
    by_rule_mismatch: Counter = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()
    rate_sources: Counter = Counter()
    mismatch_by_notice_value: Counter = Counter()
    mismatch_by_method_name: Counter = Counter()
    service_fallbacks: Counter = Counter()
    fallback_notice_values: dict[str, Counter] = defaultdict(Counter)
    fallback_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scope_counts: Counter = Counter()
    scope_comparable: Counter = Counter()
    candidates: list[dict[str, Any]] = []

    for item in outcomes:
        record = item["record"]
        result = record.get("result")
        if result is None:
            skipped[f"판정오류:{record.get('error_type')}"] += 1
            continue
        if result.is_blocked or result.rule is None:
            skipped[f"차단:{result.block_reason_code}"] += 1
            continue

        row = item["row"]
        raw_data = item["raw_data"]
        notice = _decimal(raw_data.get("sucsfbidLwltRate"))
        estimated = er._normalized_price(row["presmpt_prce"])
        rule_rate, band_label = _rule_rates(result.rule, estimated)
        rule = result.rule
        scope = _scope_of(result)

        from src.app.services.demand_institutions import institution_sido

        _sido_code, sido_name = institution_sido(item["institution"])
        notice_value = _q3(notice) if notice is not None and notice > 0 else None
        rule_value = _q3(rule_rate) if rule_rate is not None else None
        diff = (notice_value - rule_value) if (notice_value is not None and rule_value is not None) else None
        kind = _classify(notice, rule_rate)

        announcement_dt = row["bid_ntce_dt"]
        if isinstance(announcement_dt, datetime):
            announcement_day = announcement_dt.date()
        elif isinstance(announcement_dt, date):
            announcement_day = announcement_dt
        else:
            announcement_day = None
        regime = (
            "pre"
            if announcement_day is not None and announcement_day < REGIME_BOUNDARY
            else "post"
        )

        scope_counts[scope] += 1
        counters[kind] += 1
        value_comparable = rule_rate is not None and notice_value is not None
        if value_comparable:
            counters["비교가능"] += 1
            scope_comparable[scope] += 1
        regime_counts[regime][kind] += 1
        if value_comparable:
            regime_counts[regime]["비교가능"] += 1

        acc = by_rule[rule.rule_id]
        acc["rule_rate"] = str(rule.lwlt_rate) if rule.lwlt_rate is not None else None
        acc["service_type"] = rule.service_type
        acc["table_name"] = rule.table_name
        acc["scope"] = scope
        acc["region_name"] = rule.region_name
        acc["effective_date"] = rule.effective_date
        acc["price_bands"] = sorted(
            {
                str(_q3(band.lwlt_rate))
                for band in (rule.price_bands or ())
                if band.lwlt_rate is not None
            }
        )
        rate_sources[result.rate_source or "NONE"] += 1
        if rule_rate is not None:
            acc["compared"] += 1
        if kind == TYPE_MATCH:
            acc["match"] += 1
        elif kind == TYPE_NOTICE_MISSING:
            acc["missing"] += 1
        elif kind == TYPE_RULE_MISSING:
            acc["rule_missing"] += 1
        else:
            acc["mismatch"] += 1
            if diff is not None:
                acc["diffs"][str(diff)] += 1
            if notice_value is not None:
                acc["notice_values"][str(notice_value)] += 1
            by_rule_mismatch[rule.rule_id] += 1
            if sido_name:
                by_sido_mismatch[sido_name] += 1
            if notice_value is not None:
                mismatch_by_notice_value[str(notice_value)] += 1
            method_name = str(raw_data.get("sucsfbidMthdNm") or "(없음)")
            mismatch_by_method_name[method_name] += 1
            if scope == RULE_SCOPE_REGION:
                resolved_method_name, _src, _warn = er.resolve_method_name(
                    raw_data.get("sucsfbidMthdNm"), raw_data.get("sucsfbidMthdCd")
                )
                requested_service, _basis, _reason = er.resolve_local_service_type(
                    raw_data, resolved_method_name
                )
                if requested_service != rule.service_type:
                    fallback_key = f"{rule.service_type} <- {requested_service}"
                    service_fallbacks[fallback_key] += 1
                    if notice_value is not None:
                        fallback_notice_values[fallback_key][str(notice_value)] += 1
                    if len(fallback_examples[fallback_key]) < 2:
                        fallback_examples[fallback_key].append(
                            {
                                "bid_ntce_no": row["bid_ntce_no"],
                                "bid_ntce_dt": announcement_day.isoformat()
                                if announcement_day
                                else None,
                                "bid_ntce_nm": str(raw_data.get("bidNtceNm") or ""),
                                "method_name": method_name,
                                "dminstt_nm": row["dminstt_nm"],
                                "sido_name": sido_name,
                                "notice_value": str(notice_value),
                                "rule_value": str(rule_value) if rule_value is not None else None,
                                "rule_id": rule.rule_id,
                            }
                        )
            own_band_values = {
                _q3(band.lwlt_rate)
                for band in (rule.price_bands or ())
                if band.lwlt_rate is not None
            }
            if notice_value is not None and notice_value in own_band_values and notice_value != rule_value:
                acc["own_band_match"] += 1
            if notice_value is not None:
                for candidate in known_rates.get(notice_value, ()):
                    if candidate["rule_id"] == rule.rule_id:
                        continue
                    if rule.region_name and candidate["region_name"] == rule.region_name:
                        acc["same_region_hits"][candidate["rule_id"]] += 1
                    if candidate["service_type"] == rule.service_type:
                        acc["same_type_hits"][candidate["rule_id"]] += 1
            acc["method_names"][str(raw_data.get("sucsfbidMthdNm") or "(없음)")] += 1
            acc["institution_names"][str(row["dminstt_nm"] or "(없음)")] += 1
            acc["service_div"][str(raw_data.get("srvceDivNm") or "(없음)")] += 1
            if len(acc["samples"]) < 5:
                acc["samples"].append(
                    {
                        "bid_ntce_no": row["bid_ntce_no"],
                        "bid_ntce_ord": row["bid_ntce_ord"],
                        "bid_ntce_dt": announcement_day.isoformat() if announcement_day else None,
                        "bid_ntce_nm": str(raw_data.get("bidNtceNm") or ""),
                        "method_name": str(raw_data.get("sucsfbidMthdNm") or ""),
                        "procurement_class": " ".join(
                            str(raw_data.get(key) or "")
                            for key in (
                                "pubPrcrmntLrgClsfcNm",
                                "pubPrcrmntMidClsfcNm",
                                "pubPrcrmntClsfcNm",
                                "pubPrcrmntDtlClsfcNm",
                            )
                        ).strip(),
                        "dminstt_nm": row["dminstt_nm"],
                        "sido_name": sido_name,
                        "notice_value": str(notice_value) if notice_value is not None else None,
                        "rule_value": str(rule_value) if rule_value is not None else None,
                        "diff": str(diff) if diff is not None else None,
                    }
                )
            alternative_rules: list[dict[str, Any]] = []
            if notice_value is not None:
                alternative_rules = [
                    candidate
                    for candidate in known_rates.get(notice_value, ())
                    if candidate["rule_id"] != rule.rule_id
                ][:5]

        if kind in TYPE_ORDER and len(examples[kind]) < 3:
            examples[kind].append(
                {
                    "bid_ntce_no": row["bid_ntce_no"],
                    "bid_ntce_ord": row["bid_ntce_ord"],
                    "bid_ntce_dt": announcement_day.isoformat() if announcement_day else None,
                    "dminstt_nm": row["dminstt_nm"],
                    "sido_name": sido_name,
                    "notice_value": str(notice_value) if notice_value is not None else None,
                    "rule_value": str(rule_value) if rule_value is not None else None,
                    "diff": str(diff) if diff is not None else None,
                    "rule_id": rule.rule_id,
                    "band_label": band_label,
                    "alternative_rules": alternative_rules if kind != TYPE_MATCH else [],
                    "announcement_regime": regime,
                }
            )

        if kind in (TYPE_NOTICE_PLUS_2P, TYPE_NOTICE_LOWER, TYPE_OTHER):
            candidates.append(
                {
                    "rule_id": rule.rule_id,
                    "scope": scope,
                    "diff": str(diff) if diff is not None else None,
                    "notice_value": str(notice_value) if notice_value is not None else None,
                    "rule_value": str(rule_value) if rule_value is not None else None,
                    "sido_name": sido_name,
                    "regime": regime,
                    "alternative_rules": alternative_rules if notice_value is not None else [],
                }
            )

    total = sum(counters[t] for t in TYPE_ORDER) + counters[TYPE_RULE_MISSING]
    mismatch_total = counters[TYPE_NOTICE_PLUS_2P] + counters[TYPE_NOTICE_LOWER] + counters[TYPE_OTHER]
    comparable_total = counters["비교가능"]

    suspected: list[dict[str, Any]] = []
    for rule_id, acc in by_rule.items():
        if acc["mismatch"] < 2:
            continue
        compared = acc["compared"]
        if compared == 0:
            continue
        top_diff, top_diff_count = acc["diffs"].most_common(1)[0] if acc["diffs"] else ("", 0)
        top_notice, top_notice_count = (
            acc["notice_values"].most_common(1)[0] if acc["notice_values"] else ("", 0)
        )
        dominant_share = top_diff_count / acc["mismatch"] if acc["mismatch"] else 0.0
        alternative_rules = [
            candidate
            for candidate in known_rates.get(Decimal(top_notice), ())
            if candidate["rule_id"] != rule_id
        ][:6] if top_notice else []
        if acc["mismatch"] >= 3 and dominant_share >= 0.8:
            suspected.append(
                {
                    "rule_id": rule_id,
                    "scope": acc["scope"],
                    "service_type": acc["service_type"],
                    "table_name": acc["table_name"],
                    "region_name": acc["region_name"],
                    "effective_date": acc["effective_date"],
                    "rule_rate": acc["rule_rate"],
                    "compared": compared,
                    "match": acc["match"],
                    "mismatch": acc["mismatch"],
                    "mismatch_share": round(acc["mismatch"] / compared, 4),
                    "dominant_diff": top_diff,
                    "dominant_diff_count": top_diff_count,
                    "dominant_share": round(dominant_share, 4),
                    "dominant_notice_value": top_notice,
                    "dominant_notice_count": top_notice_count,
                    "alternative_rules": alternative_rules,
                    "own_band_match": acc["own_band_match"],
                    "own_band_match_share": round(acc["own_band_match"] / acc["mismatch"], 4),
                    "price_bands": acc["price_bands"],
                    "same_region_rule_hits": acc["same_region_hits"].most_common(5),
                    "same_service_type_rule_hits": acc["same_type_hits"].most_common(5),
                    "method_names": acc["method_names"].most_common(5),
                    "institution_names": acc["institution_names"].most_common(5),
                    "service_div": acc["service_div"].most_common(5),
                    "samples": acc["samples"][:3],
                }
            )
    suspected.sort(key=lambda item: (-item["mismatch"], item["rule_id"]))

    diffs = Counter(item["diff"] for item in candidates if item["diff"] is not None)
    pre_mismatch = sum(
        regime_counts["pre"][t]
        for t in (TYPE_NOTICE_PLUS_2P, TYPE_NOTICE_LOWER, TYPE_OTHER)
    )
    post_mismatch = sum(
        regime_counts["post"][t]
        for t in (TYPE_NOTICE_PLUS_2P, TYPE_NOTICE_LOWER, TYPE_OTHER)
    )

    return {
        "meta": meta,
        "totals": {
            "rule_applied": total,
            "comparable": comparable_total,
            "match": counters[TYPE_MATCH],
            "mismatch": mismatch_total,
            "notice_missing": counters[TYPE_NOTICE_MISSING],
            "rule_value_missing": counters[TYPE_RULE_MISSING],
            "rate_source": dict(rate_sources.most_common()),
            "match_share_of_comparable": round(counters[TYPE_MATCH] / comparable_total, 6)
            if comparable_total
            else 0.0,
            "mismatch_share_of_comparable": round(mismatch_total / comparable_total, 6)
            if comparable_total
            else 0.0,
            "pre_20260526_mismatch": pre_mismatch,
            "post_20260526_mismatch": post_mismatch,
        },
        "by_type": {kind: counters[kind] for kind in TYPE_ORDER},
        "by_regime": {
            regime: {kind: regime_counts[regime][kind] for kind in TYPE_ORDER}
            for regime in ("pre", "post")
        },
        "mismatch_by_scope": dict(
            Counter(item["scope"] for item in candidates).most_common()
        ),
        "by_scope": {
            scope: {
                "rule_applied": scope_counts[scope],
                "comparable": scope_comparable[scope],
                "mismatch": sum(1 for item in candidates if item["scope"] == scope),
            }
            for scope in ("REGION", "ALL", "INSTITUTION")
        },
        "mismatch_by_diff": dict(diffs.most_common(30)),
        "mismatch_by_notice_value": dict(mismatch_by_notice_value.most_common(30)),
        "mismatch_by_method_name": dict(mismatch_by_method_name.most_common(20)),
        "local_service_fallbacks": dict(service_fallbacks.most_common()),
        "local_service_fallback_notices": {
            key: dict(counter.most_common(6))
            for key, counter in fallback_notice_values.items()
        },
        "local_service_fallback_examples": dict(fallback_examples),
        "top_rules": by_rule_mismatch.most_common(10),
        "top_sido": by_sido_mismatch.most_common(10),
        "by_rule": {
            rule_id: {
                "compared": acc["compared"],
                "match": acc["match"],
                "mismatch": acc["mismatch"],
                "missing": acc["missing"],
                "rule_missing": acc["rule_missing"],
                "rule_rate": acc["rule_rate"],
                "scope": acc["scope"],
                "region_name": acc["region_name"],
                "service_type": acc["service_type"],
                "table_name": acc["table_name"],
                "effective_date": acc["effective_date"],
                "diffs": dict(acc["diffs"].most_common(8)),
                "notice_values": dict(acc["notice_values"].most_common(8)),
                "method_names": dict(acc["method_names"].most_common(5)),
                "institution_names": dict(acc["institution_names"].most_common(5)),
                "service_div": dict(acc["service_div"].most_common(5)),
                "samples": acc["samples"][:3],
            }
            for rule_id, acc in sorted(
                by_rule.items(), key=lambda kv: (-kv[1]["mismatch"], kv[0])
            )
            if acc["mismatch"] or acc["missing"] or acc["rule_missing"]
        },
        "examples": {kind: examples[kind] for kind in TYPE_ORDER},
        "suspected_misapplication": suspected,
        "skipped": dict(skipped.most_common()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공고 하한율 대 규칙 하한율 전수 대조")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--category", default="Servc")
    parser.add_argument("--method-code", default="")
    parser.add_argument("--today", default=None, help="기준일 YYYY-MM-DD (기본 오늘)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default=None, help="JSON 출력 경로")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    outcomes, meta = collect_rows(
        months=args.months,
        category=args.category,
        method_code=args.method_code,
        today=today,
    )
    report = build_report(outcomes, meta)
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    if args.format == "json":
        print(payload)
    else:
        print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
        print(json.dumps(report["by_type"], ensure_ascii=False, indent=2))
        print("top rules:", report["top_rules"])
        print("top sido:", report["top_sido"])
        print("suspected:", len(report["suspected_misapplication"]))
        print("skipped:", report["skipped"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 부록 B. 재현 명령과 한계

### B.1 실행 명령

```sh
# 저장소 루트에서
uv run python <스크립트 경로>/audit_lwlt_notice_vs_rule.py \
  --months 12 --category Servc --today 2026-11-06 \
  --format json --output /tmp/lwlt_audit.json
```

`--today 2026-11-06` 은 조사 기준일입니다. 창은 2025-11-06 이상 2026-11-07 미만입니다.

### B.2 집계 조건

| 항목 | 값 |
| --- | --- |
| 업무구분 | `Servc` |
| 기간 | 2025-11-06 ~ 2026-11-05 (공고일 기준) |
| 대표 공고 | `(bid_ntce_no, category)` 별 최신 `bid_ntce_ord` |
| 낙찰방법 필터 | 없음(`--method-code ""`). 규칙 판정이 성공한 건만 집계 |
| 공고값 | `raw_data.sucsfbidLwltRate` 를 소수 3자리로 반올림 |
| 규칙값 | 규칙에 인쇄된 구간 하한율이 있으면 해당 구간, 없으면 규칙 대표값 |
| 비교 제외 | 규칙값이 `None` 인 기술용역·기관 규칙 11,642건 |
| DB 접근 | `SET SESSION TRANSACTION READ ONLY`, SELECT only, `LIKE` 없음 |

### B.3 한계

1. **규칙값의 의미**: 규칙에 구간 하한율이 인쇄돼 있으면 추정가격으로 고른 구간값을, 없으면 대표값을 썼습니다. 추정가격이 없어 구간을 고르지 못한 건은 규칙 대표값으로 대체했으므로, 구간형 규칙에서 불일치가 과대 계상될 수 있습니다.
2. **공고값 우선**: 현행 코드가 공고값을 우선하므로, 이 문서의 불일치는 점수 계산 오류와 같지 않습니다. 4절의 "오적용"은 규칙 선택·규칙 값의 정합성 문제를 가리킵니다.
3. **시·도 귀속**: `institution_sido` 는 수요기관 본청명 기준입니다. 2026-07-16 전남광주 통합 전후로 같은 기관이 `전라남도` 또는 `전남광주통합특별시` 로 나뉘어, 2.6절 상위 2개를 합쳐 읽어야 합니다.
4. **자동 기준의 한계**: 4.9절 자동 기준은 한 규칙 안의 지배 차이가 80% 이상인 경우만 잡습니다. 지역 폐기물처럼 차이가 여러 구간값으로 흩어진 군은 4.3절에서 수동으로 보강했습니다.
5. **원문 미대조**: 규칙 값과 공고값 중 어느 쪽이 법령·예규상 정본인지는 이 조사에서 확정하지 않았습니다.
