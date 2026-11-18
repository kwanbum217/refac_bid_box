# 시·도 일반용역 적격심사 세부기준의 학술용역 적용범위 조사 (2026-11-18, B조)

> **작성일**: 2026-11-18
> **작업**: Orca Task `task_07eeae706958` (builder, Run `run_b68a3b16b660`)
> **정본 사양**: `.orca/capsules/task_academic_scope_survey_b_20261118/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **대상 시·도 코드**: 41 경기, 43 충북, 44 충남, 46 전남, 47 경북, 48 경남, 50 제주, 51 강원, 52 전북
> **비교 기준**: 대구광역시(27) `docs/analysis/daegu_academic_scope_20261118.md`,
> `docs/analysis/blocked_decision_daegu_20261118.md`
> **범위**: 조사 보고서 한 건. 소스 코드·규칙 데이터·시험·원장은 변경하지 않았다.
> **검증**: `python3 scripts/validate_agent_rules.py --quiet`

---

## 1. 결론표

정의 조항을 둔 8개 시·도(41·43·44·46·47·50·51·52)는 **모두 일반용역 정의가 학술용역(학술연구용역)을 적용 대상에서 제외**한다. 48 경상남도는 애초에 정의 조항이 없다. **학술연구 별표를 가진 지역은 9개 전부 없다.** 정의 조항만 보면 대구와 같은 구조다.

| 코드 | 시·도 | 기준 이름 · 판본(시행일) | 일반용역 정의가 학술 제외 | 학술 별표 | `evaluation_rules_local.py` 그 지역 규칙 | 대구와 같은 처리 대상 |
| ---: | --- | --- | --- | --- | --- | --- |
| 41 | 경기도 | 경기도 일반용역 적격심사 세부기준 지침, 예규 제751호 (2026-04-15). 저장소 규칙은 제748호(2025-08-08) 판 | 예 (간접: 행안부 예규 제9장 정의를 인용, 그 정의가 학술용역 제외) | 없음 | `GENERAL`·`SW`·`WASTE`·`LAND_TRANSPORT`·`INSURANCE`. `ACADEMIC` 없음 | 아니오. 상수에 41을 더해도 바뀌는 판정 0건 |
| 43 | 충청북도 | 충청북도 일반용역 적격심사 세부기준, 공고 제2020-1559호 (2020-12-18) | 예 (명시) | 없음 | `GENERAL`·`SIMPLE_LABOR`. `ACADEMIC` 없음 | 아니오. 1건이 바뀌나 역방향(행안부 띠 → 시·도 일반 별표) |
| 44 | 충청남도 | 충청남도 일반용역 적격심사 세부기준, 공고 제2026-1235호 (행안부 협의 2026-06-16, 저장소 규칙 시행일 2026-07-13) | 예 (명시) | 없음 | `FACILITY`·`SW`·`SW_SME`·`WASTE`·`LAND_TRANSPORT`·`FISHERY_CLEANUP`. **`GENERAL` 없음**, `ACADEMIC` 없음 | 아니오. 상수에 44를 더해도 0건. **차단 갈래가 `LOCAL_RULE_NOT_FOUND` 라 대구와 다른 게이트** |
| 46 | 전남 | 전남광주통합특별시 일반용역 적격심사 세부지침, 예규 제3호 (2026-07-16). 2026-07-16 이전은 전라남도 예규 제1075호(2023-03-02) | 예 (명시) | 없음 | `FACILITY`·`WASTE`·`LAND_TRANSPORT`. **`GENERAL` 없음**, `ACADEMIC` 없음 | 아니오. 상수에 46을 더해도 0건. 44와 같은 게이트 |
| 47 | 경상북도 | 경상북도 일반용역 등 적격심사 세부기준, 예규 제1571호 (2026-01-08) | 예 (명시) | 없음 | `GENERAL`·`SIMPLE_LABOR`·`SW`·`WASTE`. `ACADEMIC` 없음 | 아니오. 9건이 바뀌나 5건은 역방향 |
| 48 | 경상남도 | 경상남도 일반용역 등 적격심사 세부기준, 공고 제2023-23호 (파일명 표기 시행 2023-01-30, 저장소 규칙 시행일 2023-01-05) | **정의 조항 없음**(제2조는 평가기준). 별표 1 = 일반용역 단일 기준 | 없음 | `GENERAL`. `ACADEMIC` 없음 | 판정 불가. 상수에 48을 더해도 0건 |
| 50 | 제주특별자치도 | 제주특별자치도 일반용역 적격심사 세부기준, 예규 제82호 (2024-01-01) | 예 (명시) | 없음 | `GENERAL`·`SIMPLE_LABOR`. `ACADEMIC` 없음 | 아니오. 3건 중 2건은 역방향 |
| 51 | 강원특별자치도 | 강원특별자치도 일반용역 적격심사 세부기준, 예규 제832호 (2023-06-11) | 예 (명시) | 없음 | `GENERAL`·`SIMPLE_LABOR`·`WASTE`. `ACADEMIC` 없음 | 아니오. 7건 전부 역방향 |
| 52 | 전북특별자치도 | 전북특별자치도 일반용역 적격심사 세부기준, 부칙 제2024-10호 (2024-01-18) | 예 (명시) | 없음 | `GENERAL`·`SIMPLE_LABOR`·`WASTE`. `ACADEMIC` 없음 | 아니오. 6건 중 5건은 역방향 |

- **"학술 별표"** 는 같은 예규 안에 `학술연구용역`(또는 `학술용역`) 이름의 별표·별지를 두었는지를 뜻한다. 9개 지역 전부 별표 목록을 끝까지 확인했고 해당 별표가 없다.
- **"대구와 같은 처리 대상"** 은 `LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES`(`src/app/services/evaluation_rules.py:3334`)에 지역 코드를 더했을 때 판정이 실제로 달라지는지를 뜻한다. **대구처럼 이 상수로 풀리는 지역은 없다.** 8개 지역은 0건이거나 오히려 역방향으로 바뀌고, 역방향이 아닌 변경도 47 4건·50 1건·52 1건뿐이다(4.2절). 정의 조항이 같다는 사실과 코드 상수로 처리할 수 있다는 것은 별개다.
- `ACADEMIC` 서비스 유형 규칙은 `src/app/services/evaluation_rules_local.py` 전체에 **하나도 없다**. 학술연구 띠 값은 행안부 예규 별표(`MOIS_ACADEMIC_BAND_RULES`, `evaluation_rules.py:2347-2413`)에만 있다.

---

## 2. 시·도별 원문 인용

인용은 모두 저장소 보관 원문에서 그대로 옮겼다. 줄 번호는 해당 파일 기준이다.

### 2.1 41 경기도 — 행안부 예규 정의를 인용

**원문**: `data/sources/qualification/files/gg/be1882f40f86_gg_20260415.txt` (경기도 예규 제751호, 시행 2026-04-15), `:18`

```
제2조(정의) 이 지침에서 사용하는 “일반용역”의 뜻은 「지방자치단체 입찰 및 계약집행기준」 제9장 계약 일반조건에서 정하고 있는 용어의 정의에 따른다. <개정 2023.8.28.>
```

- 같은 조문이 예규 제748호 판 `data/sources/qualification/files/gg/407fa1d637b5_gg_g2b_20251210.txt:21-25` 에도 있다.
- 인용한 행안부 예규 정의 자체가 학술용역을 배제한다: `data/sources/qualification/files/mois_exec/d6daf6a85442_exec_standard_body.txt:7157` 및 `:7152`, `:7133`(판본별)
  `3) “일반용역”이란 “기술용역”과 “학술용역” 이외의 용역을 말한다.`
- 별표 목록(`be1882f40f86:84,196,308,420,532,598,710`)은 `별표 1-1`(단순노무)·`1-2`(소프트웨어)·`1-3`(폐기물)·`1-4`(육상운송)·`1-5`→`1-6`(이동)·`1-6`(기타 일반용역)·`별표 2` 다. 학술연구 별표는 없다.
- **판정**: 예 (간접). 학술 분야는 경기 지침의 일반용역이 아니다.

### 2.2 43 충청북도 — 명시적 제외

**원문**: `data/sources/qualification/files/cb/bee67e711e97_cb_flat.txt:6` (충청북도 공고 제2020-1559호, `[시행 2020.12.18.]` `:1`)

```
제2조(정의) ① “일반용역”이란「지방자치단체를 당사자로 하는 계약에 관한 법률」(이하 ‘지방계약법’이라 한다.)에 따른 용역 중 「지방자치단체 입찰 및 계약집행기준(행정안전부 예규)」의 용역계약 일반조건에서 정한 “기술용역”과 “학술용역” 이외의 용역을 말한다.
```

같은 조문이 `data/sources/qualification/files/cb/0cfe5136bcc2_cb_cjuc.txt:93-97`, `cb/cb8c86236f3b_cb.txt:31` 에도 있다.

- 별표는 `〈별표 1〉` 하나다(`bee67e711e97:66`, 제3조 제1항 `:8` `세부기준의 심사항목 및 배점기준은〈별표 1〉에 의한다`). 학술연구 별표는 없다.
- **판정**: 예.

### 2.3 44 충청남도 — 명시적 제외

**원문**: `data/sources/qualification/files/chungnam/d123ad901f6f_chungnam_2026_1235.txt:23-27` (충청남도 공고 제2026-1235호)

```
2. 적용대상 및 용어의 정의

가. "일반용역"이라 함은「지방자치단체 입찰 및 계약집행기준」제9장
계약 일반 조건 제1절 2-다에서 정한 기술용역과 학술용역을 제외한
나머지 용역을 총칭한다.
```

- 별표 목록(`d123ad901f6f:169-193`): `[별표 1]` 시설분야, `[별표 2]`·`[별표 2의 1]` 정보통신, `[별표 3]` 폐기물, `[별표 4]` 육상운송, `[별표 5]` 해양환경·어장관리. 학술연구 별표는 없다.
- 여기서 **기타 일반용역 별표가 없다.** 시설분야·정보통신·폐기물·육상운송·해양환경 다섯 갈래뿐이다.
- `evaluation_rules_local.py` 도 같은 구조다. 충남 규칙은 `FACILITY`·`SW`·`SW_SME`·`WASTE`·`LAND_TRANSPORT`·`FISHERY_CLEANUP` 만 있고 `GENERAL` 규칙이 없다(`:2107-2292`).
- **판정**: 예.

### 2.4 46 전남 — 명시적 제외

**원문**: `data/sources/qualification/files/jn_gj/0cb48ef87686_elis_jngj_bonmun.txt:298-301` (전남광주통합특별시 예규, `[시행 2026.07.16]` `:266`)

```
제2조(정의)
이 지침에서 사용하는 용어의 뜻은 다음과 같다.
1. “일반용역”이란 「
지방자치단체 입찰 및 계약집행기준
」에서 규정한 기술용역과 학술용역을 제외한 나머지 모든 종류의 용역(시설분야용역, 소프트웨어용역, 폐기물처리용역, 생활폐기물 수집·운반 대행용역, 육상운송용역, 어장정화·정비용역)을 총칭한다.
```

같은 조문이 제정안 `data/sources/qualification/files/jn_gj/c5f948f52dce_jngj_jeongan.txt:18-19` 에도 있다.

- 별표 목록(`0cb48ef87686:37-44`): `(별표 1)` 시설분야, `(별표 2)` 소프트웨어, `(별표 3)` 폐기물, `(별표 4)` 생활폐기물, `(별표 5)` 육상운송, `(별표 6)` 어장정화·정비, `(별표 7)` 신인도. 학술연구 별표는 없다.
- 여기도 **기타 일반용역 별표가 없다.** 그리고 `evaluation_rules_local.py` 의 전남 계열 규칙은 `FACILITY`·`WASTE`·`LAND_TRANSPORT` 만이다(`:1170-1325`). `GENERAL` 규칙이 없다.
- **판정**: 예.

### 2.5 47 경상북도 — 명시적 제외

**원문**: `data/sources/qualification/files/gb/ab55faa1b1a3_gb_body.txt:86` (예규 제1571호, `[시행 2026.01.08]` `:79-80`)

```
2. “일반용역”이란 행정안전부 예규「 지방자치단체 입찰 및 계약 집행기준 」에서 규정한 기술용역과 학술용역 이외의 용역을 말한다. <개정 2026. 1. 8.>
```

같은 조문이 `data/sources/qualification/files/gb/17af2d266b97_elis_gb_body.txt:553` 에도 있다.

- 별표 목록(`ab55faa1b1a3:169-176`): `[별표 1]` 단순노무, `[별표 2]` 소프트웨어, `[별표 3]` 폐기물, `[별표 4]` 기타 일반용역, `[별표 5]` 신용평가, `[별표 6]` 신인도, `[별표 7]` 지역업체 참여도, `[별표 8]` 제출서류목록표. 학술연구 별표는 없다.
- **판정**: 예.

### 2.6 48 경상남도 — 정의 조항이 없다

**원문**: `data/sources/qualification/files/gn/b0f2b47dd5ae_gn_flat.txt:5-8` (경상남도 공고 제2023-23호)

```
제1조 (목적) 이 기준은「지방자치단체를 당사자로 하는 계약에 관한 법률 시행령」제42조 제4항에 따라 경상남도(경상남도 및 시․군 포함)에서 집행하는 일반용역 등(정보통신용역을 포함한다) 계약에 적용할 적격심사 세부기준(이하 “세부기준”이라 한다)을 정함을 목적으로 한다.
제2조 (평가기준) ① 용역별 적격심사 항목 및 배점기준은 다음과 같다
1. 일반용역 : 경상남도 일반용역 적격심사 세부기준 [별표 1]
2. 정보통신용역 : 경상남도 정보통신용역 적격심사 세부기준 [별표 3]
```

- 제2조가 정의가 아니라 평가기준이다. 제1조~제7조 어디에도 **일반용역 정의 조항이 없다**(`grep -o '제[0-9]*조'` 결과 제1·2·3·4·5·6·7조뿐).
- 별표 목록(`b0f2b47dd5ae:37,780`): `[별표 1]` 일반용역 적격심사, `[별표 2]` 평가방법. `:782` 에 `<별표1 적용>` 이 있다. 학술연구 별표는 없다.
- **판정**: 원문에 정의 조항 없음 → **판정 불가**. `별표 1` 이 일반용역 단일 기준이므로 학술연구 전용 별표 부재만은 확인된다.
- 남은 불확실성은 4.1절에 적었다. `63107ac1756e_…(23.1.30.시행).hwp` 는 `extract_document_text` 가 `지원하지 않는 첨부 형식` 을 돌려주어 열지 못했다.

### 2.7 50 제주특별자치도 — 명시적 제외

**원문**: `data/sources/qualification/files/jeju/79a8f851701b_elis_jeju_main.txt:110` (예규 제82호, `[시행 2024.01.01]` `:105`)

```
제2조(정의) 이 세부기준에서 사용하는 용어의 정의는 다음 각 호와 같으며, 각 호 이외의 용어는 관련 법령의 정의에 따른다. 1. “일반용역”이란 기술용역, 학술연구용역을 제외한 용역을 총칭한다.
```

- 바로 다음 호가 학술연구용역을 정의하지만 `:112`, 이는 **제외 대상의 뜻풀이**이지 적용 대상이 아니다.
- 별표 목록(`79a8f851701b:47-49`): `[별표 1]` 일반용역 적격심사 심사항목 및 배점기준, `[별표 2]` 신인도 평가방법, `[별표 3]` 용역 분야별 평가방법. 학술연구 별표는 없다.
- **판정**: 예.

### 2.8 51 강원특별자치도 — 명시적 제외

**원문**: `data/sources/qualification/files/gwd/0ab5d0ce1041_elis_gwd_main.txt:254` (예규 제832호, `[시행 2023.06.11]` `:251`)

```
제2조(정의) 이 기준에서 사용하는 용어의 뜻은 다음과 같다. 1. “일반용역”이란 「 지방자치단체를 당사자로 하는 계약에 관한 법률」 (이하 “지방계약법”이라 한다)에 따른 용역 중 「 지방자치단체 입찰 및 계약 집행기준 」(행정안전부 예규)의 용역계약 일반조건에서 정한“기술용역”과 “학술용역”이외의 용역을 총칭한다.
```

- 별표 목록(`0ab5d0ce1041:38-43`): `[별표1]` 일반용역, `[별표2]` 폐기물, `[별표3]` 생활폐기물, `[별표4]` 신인도·지역업체, `[별표5]` 근로조건, `[별표6]` 용역 분야별 평가방법. 학술연구 별표는 없다.
- **판정**: 예.

### 2.9 52 전북특별자치도 — 명시적 제외

**원문**: `data/sources/qualification/files/jeonbuk/2d58643f0a49_jb_general_2024_10.hwp5txt.txt:35` (부칙 제2024-10호, 시행 2024-01-18 `:87-88`)

```
제2조 (정의)  ①“일반용역”이란 「지방자치단체를 당사자로 하는 계약에 관한 법률」에 따른 용역 중 「지방자치단체 입찰 및 계약 집행기준」 제14장 용역계약 일반조건에서 정한 기술용역, 학술연구용역을 제외한 용역을 총칭한다.
```

같은 조문이 `data/sources/qualification/files/jeonbuk/5110c07087d6_jb_general_2024_10.tbl.txt:8` 에도 있다.

- 별표 목록(`2d58643f0a49:89,254,290,328`): `[별표 1]` 일반용역·단순노무, `[별표 2]`, `[별표 3]` 폐기물, `[별표 4]` 평가방법. 학술연구 별표는 없다.
- **판정**: 예.

---

## 3. 대상 시·도의 현재 차단 학술 공고 건수

### 3.1 조회 조건

- 기간 **최근 24개월**: `2024-11-18` 이상 `2026-11-18` 미만(조회 시 창 끝은 `2026-11-19 00:00`).
- 업무구분 `Servc`, 같은 공고번호의 **최신 차수만**, 최신 차수가 취소공고인 번호는 제외.
- **"학술 공고"** 는 조달분류 네 필드(`pubPrcrmntLrg/Mid/Sml/DtlsClsfcNm`) 중 하나라도 `학술연구` 를 담은 공고다(`_is_academic_band_classification`, `evaluation_rules.py:2554-2562`). 실측상 24개월 `Servc` 학술 표기는 중분류 `학술연구서비스` 하나뿐이었다.
- **"차단"** 은 판정 함수(`resolve_evaluation_rule_from_raw_data`)의 `is_blocked` 다. 지역은 `institution_sido`(수요기관 `toplvl_instt_nm` 기준)로, 계약 법령은 `classify_contract_regime` 이 `LOCAL` 인 공고만 셌다.
- **적격심사 표기 한정**: 낙찰방법명에 `적격심사` 가 있는 공고만 셌다. 시·도 일반용역 적격심사 세부기준은 적격심사 공고에만 적용되므로, `소액수의견적`(44 175건·46 129건)·`협상에의한계약`(44 287건·46 107건) 은 이 조사의 모집단이 아니다. 이들을 넣으면 4,924건이 되지만 3.2절 수치와 비교 대상이 아니다.

### 3.2 지역별 건수 (적격심사 표기 · LOCAL · 최근 24개월 · 최신 차수)

| 코드 | 시·도 | 학술+적격심사 모집단 | 차단 계 | `LOCAL_RULE_NOT_FOUND` | `RULE_REGIME_MISMATCH` | `MANUAL_EVALUATION` | 띠 표기(`2억미만 1억이상`) 차단 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 41 | 경기도 | 52 | 31 | 0 | 20 | 11 | 14 |
| 43 | 충청북도 | 8 | 3 | 0 | 0 | 3 | 0 |
| 44 | 충청남도 | 39 | 30 | **24** | 2 | 4 | 24 |
| 46 | 전남 | 14 | 8 | **4** | 3 | 1 | 6 |
| 47 | 경상북도 | 21 | 14 | 0 | 4 | 10 | 0 |
| 48 | 경상남도 | 30 | 5 | 0 | 0 | 5 | 0 |
| 50 | 제주특별자치도 | 6 | 1 | 0 | 1 | 0 | 0 |
| 51 | 강원특별자치도 | 13 | 1 | 0 | 0 | 1 | 0 |
| 52 | 전북특별자치도 | 17 | 5 | 0 | 1 | 4 | 0 |
| | **합계** | **200** | **98** | **28** | **31** | **39** | **44** |

- 모집단 200건 중 계산까지 간 102건은 시·도 자체 별표(41 `ATTACH_1_6` 15, 48 `ATTACH_01` 23, 52 `ATTACH_01` 6 등) 또는 행안부 학술 띠(`SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E`/`OVER_2E`/`1E_2E`)로 풀렸다.
- **대구와 같은 차단 갈래는 `LOCAL_RULE_NOT_FOUND` 28건**(44 24건, 46 4건)이다. 두 지역만 값이 0이 아니다.
- `MANUAL_EVALUATION`(39건)은 낙찰방법명이 `적격심사제-관리규정외 수기심사(총점입력)` 인 공고로, 시·도 별표가 아니라 원장에서 `manual_input` 범주다. 이 과업의 대상이 아니다.
- `RULE_REGIME_MISMATCH`(31건)은 규칙은 잡혔으나 공고일이 규칙 시행 구간 밖인 경우다. 예: 50 제주 `R25BK00601128`(2025-05-28, `적격심사제-추정가격 1억미만`, `학술연구용역 적격심사 세부기준` 명시).

### 3.3 44·46 `LOCAL_RULE_NOT_FOUND` 28건의 정체 (실측)

28건 전부 다음 세 조건을 동시에 만족한다.

1. 낙찰방법명이 **띠 표기** `적격심사제-추정가격 2억미만 1억이상`(또는 `… - 지역업체참여`) → `_is_band_only_method` 가 `True`.
2. 조달분류가 `학술연구서비스` → `select_mois_academic_band_rule` 이 `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` 를 **돌려준다**(28/28).
3. 그 지역에 `GENERAL`·`ACADEMIC` 규칙이 없다 → `_select_local_rule` 이 `LOCAL_RULE_NOT_FOUND` 로 끝난다.

공고일은 44 중 16건이 2025-07-01 이후, 8건이 그 이전이고 46 4건은 모두 이후다. 행안부 띠 규칙 시행일(`2025-07-01`) 이전 8건은 설령 구제 게이트가 열려도 시행일 대조에서 다시 막힌다.

### 3.4 질의 부록

**(가) 지역별 모집단(공고 수) 재현 질의.** 최신 차수만 남긴 결과 241건이다. 이 241건은 3.2절 모집단 200건에 **최신 차수가 취소공고라 판정에서 빠지는 41건**을 더한 값이다(41 경기 10, 43 충북 3, 44 충남 8, 46 전남 4, 47 경북 2, 48 경남 3, 50 제주 1, 51 강원 3, 52 전북 7; 200 + 41 = 241).

```sql
SELECT LEFT(i.rgn_cd, 2) AS sido, COUNT(*) AS cnt
FROM bid_announcements a
JOIN g2b_demand_institutions i
  ON i.dminstt_cd = JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.dminsttCd'))
JOIN (SELECT bid_ntce_no, MAX(CAST(bid_ntce_ord AS UNSIGNED)) AS mo
      FROM bid_announcements
      WHERE category = 'Servc'
        AND bid_ntce_dt >= '2024-11-18' AND bid_ntce_dt < '2026-11-19'
      GROUP BY bid_ntce_no) m
  ON m.bid_ntce_no = a.bid_ntce_no
 AND CAST(a.bid_ntce_ord AS UNSIGNED) = m.mo
WHERE a.category = 'Servc'
  AND a.bid_ntce_dt >= '2024-11-18' AND a.bid_ntce_dt < '2026-11-19'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.pubPrcrmntMidClsfcNm')) = '학술연구서비스'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.sucsfbidMthdNm')) LIKE '적격심사%'
  AND i.jrsdctn_div_nm IN ('지방자치단체', '지방공기업')
  AND LEFT(i.rgn_cd, 2) IN ('41','43','44','46','47','48','50','51','52')
GROUP BY LEFT(i.rgn_cd, 2)
ORDER BY sido;
```

결과(최신 차수 적용, 취소공고 포함): 41 62, 43 11, 44 47, 46 18, 47 23, 48 33, 50 7, 51 16, 52 24. 합계 241.

**(나) 띠 표기 `2억미만 1억이상` 학술 공고(판정 전 모집단).** 3.2절 "띠 표기 차단" 열과 다른 값이다. 이 열은 **차단된 것만** 세었고 이 질의는 차단 여부를 모른다.

```sql
SELECT LEFT(i.rgn_cd, 2) AS sido, COUNT(DISTINCT a.bid_ntce_no) AS cnt
FROM bid_announcements a
JOIN g2b_demand_institutions i
  ON i.dminstt_cd = JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.dminsttCd'))
WHERE a.category = 'Servc'
  AND a.bid_ntce_dt >= '2024-11-18' AND a.bid_ntce_dt < '2026-11-19'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.pubPrcrmntMidClsfcNm')) = '학술연구서비스'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.sucsfbidMthdNm')) LIKE '적격심사제-추정가격 2억미만 1억이상%'
  AND i.jrsdctn_div_nm IN ('지방자치단체', '지방공기업')
  AND LEFT(i.rgn_cd, 2) IN ('41','43','44','46','47','48','50','51','52')
GROUP BY LEFT(i.rgn_cd, 2)
ORDER BY sido;
```

결과: 41 28, 43 3, 44 28, 46 13, 47 2, 48 13, 50 3, 51 4, 52 7.

**(다) 차단 건수 재현.** 차단 여부는 순수 판정 함수 결과이므로 SQL 로 직접 셀 수 없다. 아래 스크립트가 (가)의 모집단을 판정 함수에 통과시켜 3.2절 값을 낸다.

```python
from datetime import datetime
from sqlalchemy import text
from scripts import report_rule_coverage as coverage
from src.app.core.db import engine
from src.app.services.demand_institutions import (
    classify_contract_regime, institution_sido,
)

KEYS = ("pubPrcrmntLrgClsfcNm", "pubPrcrmntMidClsfcNm",
        "pubPrcrmntSmlClsfcNm", "pubPrcrmntDtlsClsfcNm")
with engine.connect() as conn:
    conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
    institutions = coverage._load_institutions(conn)
    rows = list(conn.execution_options(stream_results=True).execute(
        text(coverage.ANNOUNCEMENT_SQL),
        {"category": "Servc", "window_from": datetime(2024, 11, 18),
         "window_end": datetime(2026, 11, 19)}))
latest, _cancelled = coverage.split_by_latest_order(rows)
tally = {}
for row in latest:
    raw = coverage._as_dict(row.raw_data)
    inst = institutions.get(str(raw.get("dminsttCd") or "").strip())
    if classify_contract_regime(inst) != "LOCAL":
        continue
    code, _name = institution_sido(inst)
    if code not in {"41", "43", "44", "46", "47", "48", "50", "51", "52"}:
        continue
    if not any("학술연구" in str(raw.get(k) or "") for k in KEYS):
        continue
    if "적격심사" not in str(raw.get("sucsfbidMthdNm") or ""):
        continue
    record = coverage._to_record(row, institutions)
    out = coverage.classify_result(record.get("result"), record.get("error_type"))
    if out.applied_scope == coverage.LEDGER_SCOPE_BLOCKED:
        tally[(code, out.block_code)] = tally.get((code, out.block_code), 0) + 1
for k in sorted(tally):
    print(k, tally[k])
```

실행은 저장소 루트에서 `PYTHONPATH=. uv run python <파일>` 로 한다(`scripts` 가 패키지로 잡히도록). 출력이 3.2절과 정확히 일치한다.

- `scripts/db_readonly_query.py` 만 썼고 `docker exec`·`mysql` 직접 호출은 하지 않았다. 측정 스크립트와 원시 결과는 `mktemp -d` 임시 경로에만 두었고 커밋하지 않았다.
- 판정 스냅숏 교차 확인: `uv run python scripts/judge_snapshot_diff.py dump --months 24 --as-of 2026-11-18` → `공고 51387건`. 모집단 200건은 이 스냅숏의 부분집합이다.

---

## 4. 남은 불확실성

### 4.1 원문 확보 실패

| 항목 | 상태 |
| --- | --- |
| 48 경남 `63107ac1756e_…(23.1.30.시행).hwp` | `extract_document_text` → `지원하지 않는 첨부 형식`. 같은 기준의 평문 `b0f2b47dd5ae_gn_flat.txt`·`cea6c57cc30d_gn.txt` 에는 정의 조항이 없다. **정의 조항 부재인지 추출 실패인지 구분되지 않는다** |
| 43 충북 `1fa436898780_…(최종).hwp`, `bc661e78176a_cb_cjuc.hwp` | 같은 미지원 형식. 다만 같은 기준 평문 3종(`bee67e711e97_cb_flat.txt`, `0cfe5136bcc2_cb_cjuc.txt`, `cb8c86236f3b_cb.txt`)에서 제2조 정의를 확인해 판정에는 영향이 없다 |
| 44 충남 `11c48edac4f7_…(신구대비표).hwpx` | 미지원 형식. 별표 목록은 평문 `679905cdbce5_chungnam_tables.txt` 로 확보했다 |
| 44 충남 시행일 | 원문 본문에 시행일이 인쇄되지 않았다. `manifest.json` 의 `effective_date=2026-07-13` 과 `evaluation_rules_local.py` 의 `effective_date="2026-07-13"` 을 근거로 적었다. 원문 표지의 `행정안전부 협의(2026. 06. 16.)`(`d123ad901f6f:3`)와 다르다 |
| 48 경남 시행일 | 파일명은 `23.1.30.시행`, 저장소 규칙은 `effective_date="2023-01-05"`(`evaluation_rules_local.py:1770`). 원문 평문에 부칙 시행일 문장이 없어 어느 쪽이 정본인지 확정하지 못했다 |
| 47 경북 구판 | `2998afddfb78_경상북도 일반용역 등 적격심사 세부기준(예규 제1559호).pdf` 가 manifest 에 있으나 이번에 열지 않았다. 정의 조문은 제1571호 판에서 확인했고 제1568호 판(`_SRC_GB_20241212`)도 같은 취지다 |

### 4.2 "정의가 같다"와 "코드가 처리할 수 있다"는 별개다 (실측)

`LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES` 에 지역을 더해 판정이 바뀌는지 시뮬레이션했다(모듈 전역만 바꾸고 파일은 고치지 않음, `mktemp -d` 스크립트).

| 시뮬레이션 | 바뀐 공고 | 방향 |
| --- | ---: | --- |
| 지역을 하나씩만 추가 (`{27} ∪ {X}`) | 41·44·46·48 **0건**, 43 1건, 47 9건, 50 3건, 51 7건, 52 6건 | 0건이 아닌 26건 가운데 **20건이 역방향**: 행안부 학술 띠(`PPS_DEFAULT`)로 풀리던 공고가 시·도 일반 별표(`REGION`)로 되돌아간다(43 1, 47 5, 50 2, 51 7, 52 5). 47 4건·50 1건·52 1건만 `RULE_REGIME_MISMATCH` → `REGION` 으로 풀린다 |
| `{27, 44, 46}` 추가 | **0건** | 없음. 44·46은 이미 `LOCAL_RULE_NOT_FOUND` 로 끝나 상수가 개입할 여지가 없다 |

- 44·46이 대구와 다른 지점은 **일반 별표 유무가 아니라 차단 코드**다. 대구는 `ACADEMIC` 확정을 되돌린 뒤 `SIMPLE_LABOR` 단독 후보만 남아 `LOCAL_SERVICE_TYPE_UNRESOLVED`(`LOCAL_SIMPLE_LABOR_ONLY_REASON`)로 막히고, 그 사유가 행안부 구제에서 배제된다. 44·46은 되돌릴 `ACADEMIC` 자체가 서지 않는다(띠 표기라 `mois_academic_band=False`) → `GENERAL`/`UNRESOLVED` → 일반·단순노무 후보 모두 없음 → `LOCAL_RULE_NOT_FOUND`.
- 그런데 띠 표기 구제 분기(`evaluation_rules.py:4753-4754`)는 **`BLOCK_CODE_RULE_NOT_FOUND` 일 때만** `select_mois_academic_band_rule` 을 부른다. 44·46의 28건은 `LOCAL_RULE_NOT_FOUND` 라 구제되지 않는다. 실측으로 이 조건만 `LOCAL_RULE_NOT_FOUND` 까지 넓히면 44 16건·46 4건이 `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` 로 계산되고, 44 8건은 시행일 대조로 `RULE_REGIME_MISMATCH` 가 된다. 이는 코드 변경이라 이번 과업 범위 밖이며, 여기에는 조사 결과로만 적는다.
- 대구 상수(`LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES`)는 **대구형 차단(`LOCAL_SERVICE_TYPE_UNRESOLVED` + `LOCAL_SIMPLE_LABOR_ONLY_REASON`) 전용**으로 읽어야 한다. 정의 조항이 같은 다른 지역에 그대로 확장하면 위 표처럼 역방향 변경이 생긴다.

### 4.3 판정하지 않은 것

- 국가계약(`NATIONAL`) 공고는 시·도 규칙 대상이 아니므로 세지 않았다.
- `MANUAL_EVALUATION`·`NEGOTIATION_CONTRACT`·`NON_PRED_PRICE`·`NOT_QUALIFICATION_METHOD` 차단은 시·도 일반용역 별표 적용 이전 단계에서 갈리는 사유라 이 조사의 결론 대상이 아니다.
- 지방공기업(지방공사·공단)은 `classify_contract_regime` 이 `LOCAL` 을 돌려주는 경우만 포함했다. `SIDO_RULE_EXCLUDED_NAME_MARKERS`(`demand_institutions.py:241`)로 시·도 규칙에서 제외되는 기관은 `institution_sido` 가 `(None, None)` 이 되어 자연히 빠진다.
- 학술연구 별표가 **다른 문서**(예: 시·도 소관 부서의 별도 고시)에 있는지는 저장소 수집분 범위에서만 확인했다. 저장소에 없다는 사실이 그 시·도에 없다는 증거는 아니다(대구 조사 6.1절과 같은 한계).

---

## 5. 다음 과업 후보 (구현하지 않음)

1. **44 충남·46 전남 28건**: 띠 표기 구제 조건을 `LOCAL_RULE_NOT_FOUND` 까지 넓힐지 결정이 필요하다. 넓히면 20건이 계산되고 8건은 시행일 대조로 남는다(4.2절 실측). 다만 이 게이트는 D25(첨부 원문 판별 없이 띠 표기만으로 확정하지 않음)와 맞물려 있어, 단순 확대가 D25 의도를 훼손하지 않는지 먼저 따져야 한다.
2. **44·46 기타 일반용역 별표 부재**: 원문 별표 목록에 기타 일반용역 갈래가 없다. `GENERAL` 규칙을 새로 만들 근거가 원문에 없다는 뜻이므로, 행안부 [별표 4] 준용이 유일한 계산 경로다.
3. **48 경남 정의 조항**: 원문 HWP 추출 경로를 확보한 뒤 재확인해야 한다. 정의 조항이 실제로 없다면 그 지역은 시·도 예규가 일반용역 정의를 두지 않는 특이 사례다.
