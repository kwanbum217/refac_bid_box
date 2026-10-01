# 미확정 7건 B·k·T 확정 근거 조사

> **작성일**: 2026-10-01
> **작성자**: Orca investigator (`task_3e7c6581a354`)
> **정본 Capsule**: `.orca/capsules/task_3e7c6581a354/capsule.yaml`
> **대상**: `SERVC_QUAL_POST_20260526_ATTACH_01·03·04·05·12·13·14` 7건의 가격배점한도(B)·평점계수(k)·통과점수(T)
> **원칙**: 코드는 수정하지 않았다. 문서에서 확인되지 않은 값은 만들지 않고 확인 불가로 적는다. 확정값에는 문서 경로와 행 번호를 붙인다.
> **결론**: 7건 중 4건(ATTACH_01·03·04·05)은 별표 귀속이 확정되고 B·k·T는 구간 조건부로 확정 가능하다. 3건(ATTACH_12·13·14)은 별표 귀속 자체가 없어 전부 확정 불가다.

---

## 1. 조사 대상 7건의 현재 상태

`src/app/services/evaluation_rules.py`의 배점표 판정표(`_SCORE_TABLE_DECLARATIONS`) 기준이다.

| # | rule_id | 용도 | 현재 선언 | 사유 상수 |
| --- | --- | --- | --- | --- |
| 1 | SERVC_QUAL_POST_20260526_ATTACH_01 | 시설분야용역 | 전부 None | `_SCORE_REASON_DOC_CONFLICT` (`src/app/services/evaluation_rules.py:159`) |
| 2 | SERVC_QUAL_POST_20260526_ATTACH_03 | 여객 육상운송 | 전부 None | `_SCORE_REASON_DOC_CONFLICT` (`src/app/services/evaluation_rules.py:166`) |
| 3 | SERVC_QUAL_POST_20260526_ATTACH_04 | SW 중소기업자간 경쟁제품 대상 | 전부 None | `_SCORE_REASON_DOC_CONFLICT` (`src/app/services/evaluation_rules.py:167`) |
| 4 | SERVC_QUAL_POST_20260526_ATTACH_05 | SW 중소기업자간 경쟁제품 비대상 | T=85만 선언, B·k는 None | `src/app/services/evaluation_rules.py:168-172` |
| 5 | SERVC_QUAL_POST_20260526_ATTACH_12 | 추정가격 2억원 미만 | 전부 None | `_SCORE_REASON_UNMAPPED_BAND` (`src/app/services/evaluation_rules.py:210`) |
| 6 | SERVC_QUAL_POST_20260526_ATTACH_13 | 추정가격 5억원 미만 2억원 이상 | 전부 None | `_SCORE_REASON_UNMAPPED_BAND` (`src/app/services/evaluation_rules.py:211`) |
| 7 | SERVC_QUAL_POST_20260526_ATTACH_14 | 추정가격 30억원 미만 15억원 이상 | 전부 None | `_SCORE_REASON_UNMAPPED_BAND` (`src/app/services/evaluation_rules.py:212`) |

개정 전 세대(`PRE_20250901`)의 ATTACH_01·03·04도 같은 사유로 전부 None이다(`src/app/services/evaluation_rules.py:79,86,87`). ATTACH_05는 개정 전후 모두 T=85만 선언이다(`src/app/services/evaluation_rules.py:88-93`).

---

## 2. 미확정 7건 판정표

표의 B·k·T는 제2026-260호(시행 2026-05-26) 세대 값이다. PRE 세대 값은 3장을 참조한다.

| rule_id | 별표 귀속 후보 | 확정 가능 여부 | B | k | T |
| --- | --- | --- | --- | --- | --- |
| ATTACH_01 시설분야 | 별표 2 (확정) | 조건부 확정 가능 | 60(5억원 이상)/70(5억원 미만). `docs/analysis/servc_post_rules_audit_20260929.md:103`는 수식만 적고 배점한도는 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`의 별표 1~7·9 공통 규칙을 따른다 | 5 단일. `docs/analysis/servc_post_rules_audit_20260929.md:103` | 85. `docs/analysis/servc_post_rules_audit_20260929.md:131` |
| ATTACH_03 여객 | 별표 5 (확정) | 조건부 확정 가능 | 60/70 (위와 같은 근거 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`) | 4 단일. `docs/analysis/servc_post_rules_audit_20260929.md:107` | 88. `docs/analysis/servc_post_rules_audit_20260929.md:131`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176` |
| ATTACH_04 SW 대상 | 별표 3의2 (확정) | 조건부 확정 가능 | 60/70 (같은 근거 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`) | 4 단일. `docs/analysis/servc_post_rules_audit_20260929.md:105` | 88. `docs/analysis/servc_post_rules_audit_20260929.md:131`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176` |
| ATTACH_05 SW 비대상 | 별표 3 (확정) | T 확정, B·k 조건부 확정 가능 | 60/70 (같은 근거 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`) | 2(고시금액 이상)/4(고시금액 미만). `docs/analysis/servc_post_rules_audit_20260929.md:104` | 85 확정. `src/app/services/evaluation_rules.py:168-172`에 이미 선언됨. 근거 `docs/analysis/servc_post_rules_audit_20260929.md:131` |
| ATTACH_12 2억원 미만 | 없음 (별표 외 일반 띠) | 확정 불가. 원문 별표 1~9에 같은 이름이 없어 귀속 자체가 미확인이다 (`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312`) | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 |
| ATTACH_13 5억 미만 2억 이상 | 없음 (별표 외 일반 띠) | 확정 불가. 위와 같은 사유 (`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312`) | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 |
| ATTACH_14 30억 미만 15억 이상 | 없음 (별표 외 일반 띠) | 확정 불가. 위와 같은 사유 (`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312`) | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 | 확정 불가. 같은 사유 |

별표 귀속 확정 근거는 ATTACH_01·03·04·05에 대해 개정 전 대응표(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:265-269`)와 개정 후 정합성 판정표(`docs/analysis/servc_post_rules_audit_20260929.md:183-187`)가 일치한다. 일반 띠 3종은 두 문서 모두 별표 귀속 미확인으로 적는다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:276-278,655`, `docs/analysis/servc_post_rules_audit_20260929.md:194-196`).

---

## 3. 왜 ATTACH_01·03·04가 미확인인가: 세대 혼동이지 문서 충돌이 아니다

현 코드의 미확인 사유는 다음과 같다(`src/app/services/evaluation_rules.py:63-66`).

```text
미확인: 문서 간 기준비율·계수 불일치(시설분야 91 대 93, 여객·SW(대상) 계수 4)로 확정하지 않습니다
```

조사 결과 이 사유 문구는 정확하지 않다. 불일치가 아니라 세대별 정상 개정 차이이며, 세대를 분리하면 값이 확정된다.

### 3.1 시설분야 기준비율 91 대 93

- 91은 개정 전(제2025-257호) 별표 2 값이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:163`).
- 93은 개정 후(제2026-260호) 별표 2 값이다(`docs/analysis/servc_post_rules_audit_20260929.md:103`).
- 개정 전후 변화표가 91에서 93으로의 +2 상향을 명시한다(`docs/analysis/servc_post_rules_audit_20260929.md:119`).
- 따라서 POST_20260526_ATTACH_01에는 93·k5·예외상한 96%를, PRE_20250901_ATTACH_01에는 91·k5·예외상한 94%를 각각 적으면 된다. 하나의 rule_id에 두 세대 값을 함께 적을 수 없어 미확인으로 둔 것이 현재 상태이며, 세대 분리 선언이면 확정 가능하다.
- 코드의 `base_rate`는 이미 세대 분리되어 있다. POST ATTACH_01은 0.93(`src/app/services/evaluation_rules.py:255`), PRE ATTACH_01은 0.91(`src/app/services/evaluation_rules.py:533`)이다. 남은 것은 B·k·T 선언뿐이다.

### 3.2 여객·SW(대상) 계수 4

- 여객 계수 4는 개정 전 별표 5 값이고(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:167`), 개정 후 별표 5 값도 4로 동일하다(`docs/analysis/servc_post_rules_audit_20260929.md:107`).
- SW(대상) 계수 4는 개정 전 별표 3의2 값이고(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:165`), 개정 후 별표 3의2 값도 4로 동일하다(`docs/analysis/servc_post_rules_audit_20260929.md:105`).
- 개정 전후 변화표는 두 별표 모두 "변동 없음"으로 적는다(`docs/analysis/servc_post_rules_audit_20260929.md:121,123`).
- 즉 여객·SW(대상)의 계수 4에는 문서 간 불일치가 존재하지 않는다. 사유 문구의 "여객·SW(대상) 계수 4"는 불일치 사례가 아니며, POST_20260526_ATTACH_03·04에 k=4 단일(`docs/analysis/servc_post_rules_audit_20260929.md:105,107`), T=88(`docs/analysis/servc_post_rules_audit_20260929.md:131`)을 적는 데 장애가 없다.
- 코드의 `base_rate`도 이미 0.91로 분리되어 있다. POST ATTACH_03·04는 0.91(`src/app/services/evaluation_rules.py:287,303`), PRE ATTACH_03·04도 0.91(`src/app/services/evaluation_rules.py:563,579`)이다.

### 3.3 정정: "91에서 93으로 상향"은 두 개의 다른 사건이다

- 시설분야 91에서 93으로의 상향은 제2026-260호(시행 2026-05-26)에서 일어났고 원문 확정이다(`docs/analysis/servc_post_rules_audit_20260929.md:119`).
- 여객·SW(대상) 91에서 93으로의 상향은 제2026-390호(시행 2026-07-27) 추정이며 별표 확정 원문은 미확보 상태다(`docs/analysis/servc_post_rules_audit_20260929.md:137-138,263`). 낙찰하한율 87.995에서 89.995로의 이동과 함께 보도와 실측 간접 증거에만 의존한다(`docs/analysis/servc_post_rules_audit_20260929.md:169,205-208`).
- 두 사건을 "390호에서 91이 93이 되었다" 하나로 묶으면 시설분야 값의 근거 판정이 틀린다. 세대별 정리표는 4장을 참조한다.

---

## 4. 개정 3세대 간 기준비율·k 변화표

### 4.1 별표별 기준비율 변화 (k 체계는 전 세대 동일)

| 별표 | 제2025-257호·제2026-15호 (개정 전) | 제2026-260호 (개정 후) | 제2026-390호 (후속, 추정) |
| --- | ---: | ---: | --- |
| 1 학술연구 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:162` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:102` | 변동 없음(조문 확인). `docs/analysis/servc_post_rules_audit_20260929.md:209-210` |
| 2 시설분야 | 91, k 5 단일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:163` | 93, k 5 단일. `docs/analysis/servc_post_rules_audit_20260929.md:103` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 3 SW 비대상 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:164` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:104` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 3의2 SW 대상 | 91, k 4 단일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:165` | 91, k 4 단일. `docs/analysis/servc_post_rules_audit_20260929.md:105` | 93, k 4 단일 (추정, 원문 미확보). `docs/analysis/servc_post_rules_audit_20260929.md:205-208` |
| 4 폐기물처리 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:166` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:106` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 5 여객 | 91, k 4 단일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:167` | 91, k 4 단일. `docs/analysis/servc_post_rules_audit_20260929.md:107` | 93, k 4 단일 (추정, 원문 미확보). `docs/analysis/servc_post_rules_audit_20260929.md:205-208` |
| 5의2 화물 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:168` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:108` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 6 보험 | 88, k 0.375 단일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:169` | 88, k 0.375 단일. `docs/analysis/servc_post_rules_audit_20260929.md:109` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 7 수리·점검 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:170` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:110` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 8 임대차 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:171` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:111` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |
| 9 수요기관 지정형 | 88, k 2/4. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:172` | 90, k 2/4. `docs/analysis/servc_post_rules_audit_20260929.md:112` | 변동 없음. `docs/analysis/servc_post_rules_audit_20260929.md:209` |

개정 전후 변화 요약은 감사 보고서의 변화표와 같다(`docs/analysis/servc_post_rules_audit_20260929.md:116-128`). 핵심은 계수 k의 체계 자체는 세대를 가로질러 변하지 않았다는 점이다. 바뀐 것은 기준비율뿐이며, SW(대상)·여객·보험은 260호에서 기준비율도 바뀌지 않았다(`docs/analysis/servc_post_rules_audit_20260929.md:130`).

### 4.2 B 규칙 (전 세대 공통)

- 별표 1~7·9는 60(추정가격 5억원 이상)/70(5억원 미만)이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`).
- 별표 8 임대차는 단일 70이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:120-126,174`).
- 별표 9 수요기관 지정형은 60 이상 70 이하에서 수요기관이 정한다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:127-138`).
- 공고 첨부 별표 9 실측도 B 60/70을 확인한다(`docs/analysis/20260930_score_params_acquisition.md:126-128`).

### 4.3 T 규칙 (전 세대 공통)

- 기본 85점이며 소프트웨어용역의 중소기업자간 경쟁제품과 여객 육상운송용역은 88점이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176`, `docs/analysis/servc_post_rules_audit_20260929.md:136,146-148`).
- 390호도 통과점수 변동이 없다(`docs/analysis/servc_post_rules_audit_20260929.md:210`).

### 4.4 B와 k의 구간 축이 다르다

- B는 추정가격 5억원 기준으로 갈린다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`). 코드도 "B는 추정가격 5억원 미만 70/이상 60으로 갈려 미확인"으로 적는다(`src/app/services/evaluation_rules.py:72`).
- k(2 대 4)는 고시금액 기준으로 갈린다(`src/app/services/evaluation_rules.py:73`). 고시금액은 2025~2026년 2.3억원이다(`docs/design/g2b_procurement_institution_analysis.md:100-105`).
- 두 축이 다르므로(`docs/analysis/20260930_score_params_acquisition.md:222`) 단일 B·k 선언이 불가능한 규칙이 생긴다. ATTACH_05(SW 비대상)와 별표 1·4·5의2·7·8·9 계열이 해당한다. 이 경우 단일값 확정 불가가 정상이며, 구간 조건부(B는 5억 축, k는 고시금액 축)로만 확정할 수 있다.

---

## 5. ATTACH_05가 부분 확정인 이유

ATTACH_05(SW 비대상, 별표 3)는 T=85만 선언되어 있다(`src/app/services/evaluation_rules.py:168-172`).

- T=85의 근거는 개정 후 통과점수 기록이다(`docs/analysis/servc_post_rules_audit_20260929.md:131`). SW 비대상은 88점 예외에 해당하지 않는다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176`).
- B는 5억원 축으로 갈려 단일 확정 불가이다(`src/app/services/evaluation_rules.py:72`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`).
- k는 고시금액 축으로 갈려(2 이상/4 미만, `docs/analysis/servc_post_rules_audit_20260929.md:104`) 단일 확정 불가이다(`src/app/services/evaluation_rules.py:73`).
- 따라서 ATTACH_05의 현재 선언(T만 확정)은 정확한 상태이며, B·k는 조건부(5억원 축·고시금액 축)로만 확정 가능하다. 값을 새로 만들 필요가 없다.

---

## 6. 일반 띠 3건이 확정 불가인 이유

- `추정가격 2억원 미만인 용역` 등 일반 띠 이름은 원문 별표 1~9에 존재하지 않는다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:29,280,301`).
- 실측으로 확인되는 것은 낙찰방법명 존재와 최빈 하한율뿐이다. 개정 전 구간 실측은 2억원 미만 87.745(표본 1,500), 5억원 미만 2억원 이상 86.745(793), 30억원 미만 15억원 이상 82.995(65)이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:276-278`). 개정 후 구간 실측은 설계서 2.1표와 같다(`docs/design/servc_qualification_evaluation_design_20260909.md:52-56`).
- 기준비율 0.88 추정은 별표 1 동일 수식군 가정일 뿐 원문 확인이 아니다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:280,486,499,512`).
- B·k·T의 저장소·DB 원천 없음은 설계서에 명문화되어 있다(`docs/design/servc_qualification_evaluation_design_20260909.md:212-236`). B·k·T는 OpenAPI 113개 필드에도 공고 상세 페이지에도 공고문 본문에도 없고 오직 첨부 별표 문서에만 있다(`docs/analysis/20260930_score_params_acquisition.md:19,51,70,106`). 일반 띠는 첨부 별표 자체가 특정되지 않으므로 추출 경로도 없다.
- 적격심사 공고 중 별표를 직접 첨부하는 비율은 Servc 실측 9/90이며 PDF 스캔본은 추출 불가다(`docs/analysis/20260930_score_params_acquisition.md:207-211,229-231`).
- 결론: ATTACH_12·13·14는 B·k·T 전부 확정 불가다. 일반 띠의 세분 구간(15억원 미만 5억원 이상 등)도 별표 귀속 미확인이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:303-312`).

---

## 7. 2023-05-01판 14건이 전부 미확인인 이유

- 제2023-53호 판의 별표 배점표(B·k·T)는 조사 범위 밖이다(`src/app/services/evaluation_rules.py:59-62`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:658`).
- 별표 1·11의 배점표가 제2025-257호와 다르지만 식별 문자열·하한율·기준비율은 같아 같은 별표 범위를 한 벌로 표현한다는 주석이 있다(`src/app/services/evaluation_rules.py:748-750`). 즉 하한율·식별 문자열은 옮겨 적었으나 배점표는 옮겨 적지 않은 상태다.
- 2025-01-01~2025-08-31 구간에 적용된 판의 시행일과 별표 구성은 2차 자료 수준이다(`docs/analysis/servc_pre20260526_rules_sourcing_20260929.md:418-419`).
- 개정 전 별표별 배점표 B·k·T는 공식 별표 원문(HWPX/HWP)에서 읽어야 하며 저장소·DB에 원천이 없다는 미확인 항목이 별도로 기록되어 있다(`docs/analysis/servc_pre20260526_rules_sourcing_20260929.md:300-308`).
- 결론: 2023판 14건은 원문 미확보 상태이므로 전부 확정 불가다. 2025-257호 값을 소급 적용하는 것은 금지된다.

---

## 8. 한계와 다음 단계

1. 제2026-390호 별표 확정 원문(HWPX)은 미확보 상태다(`docs/analysis/servc_post_rules_audit_20260929.md:143,263`). 여객·SW(대상)의 91에서 93으로의 상향과 하한율 89.995는 보도 기반 추정치이므로 POST_20260727 2종(`src/app/services/evaluation_rules.py:484-504`)의 B·k·T 선언은 원문 확보 후에 한다.
2. B 단일값 선언은 ATTACH_01·03·04를 포함한 5억원 양구간 규칙에서 불가능하다. 선언 설계는 구간 조건부(60/70) 또는 구간 분리 규칙으로 해야 한다.
3. k 단일값 선언은 ATTACH_05를 포함한 고시금액 분리 규칙에서 불가능하다. 선언 설계는 고시금액 조건부(2/4)로 해야 한다.
4. 일반 띠 3건의 B·k·T 확정에는 공식 원문 확보가 아니라 별표 귀속 특정이 선행되어야 한다. 귀속이 특정되지 않으면 원문을 구해도 값을 매칭할 수 없다.
5. 이 조사는 문서만 남기고 소스 파일을 하나도 수정하지 않았다.

---

## 9. 재현 정보

- 판정표의 별표 귀속은 개정 전 대응표(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:263-278`)와 개정 후 판정표(`docs/analysis/servc_post_rules_audit_20260929.md:181-196`)의 교차로 재현한다.
- B·k·T 원문값은 개정 전 수식표(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:160-176`)와 개정 후 수식표(`docs/analysis/servc_post_rules_audit_20260929.md:100-131`)의 대조로 재현한다.
- 일반 띠 미확인은 8.2절(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:299-312`)과 한계표(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:653-660`)로 재현한다.
- 검증 명령: `python3 scripts/validate_agent_rules.py --quiet`
