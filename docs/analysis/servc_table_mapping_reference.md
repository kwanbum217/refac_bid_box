# 일반용역 적격심사 rule_id와 공식 별표 대응표

> **작성일**: 2026-10-01
> **작성자**: Orca investigator (`task_3e7c6581a354`)
> **정본 Capsule**: `.orca/capsules/task_3e7c6581a354/capsule.yaml`
> **목적**: `src/app/services/evaluation_rules.py`의 rule_id(ATTACH_01 등 14종)와 공식 별표 번호(1, 2, 3, 3의2, 4, 5, 5의2, 6, 7, 8, 9) 사이의 대응을 한 표로 고정한다.
> **대응 원칙**: 1 rule_id가 여러 별표에 걸치는 경우는 없다. 반대로 1개 별표가 고시금액 축으로 2개 rule_id로 쪼개지는 경우가 있다(별표 1·4·5의2). 코드는 수정하지 않았다.

---

## 1. POST_20260526 14종 대응표 (제2026-260호, 시행 2026-05-26)

| rule_id | 공식 별표 | B·k·T 선언 상태 | 비고 |
| --- | --- | --- | --- |
| SERVC_QUAL_POST_20260526_ATTACH_01 | 별표 2 시설분야 | 미확인 (조건부 확정 가능, 조사서 2장) | 5억원 미만·이상 양구간을 1개 rule에 포함. `src/app/services/evaluation_rules.py:241-257` |
| SERVC_QUAL_POST_20260526_ATTACH_02 | 별표 6 보험 | k=0.375·T=85 선언, B 미확인 | B는 5억원 축 분리 필요. `src/app/services/evaluation_rules.py:160-164` |
| SERVC_QUAL_POST_20260526_ATTACH_03 | 별표 5 여객 육상운송 | 미확인 (조건부 확정 가능, 조사서 2장) | patterns는 5억원 미만만 등록됨. 5억원 이상 낙찰방법명은 개정 후 코드에 없음(`docs/analysis/servc_pre20260526_rules_sourcing_20260929.md:214-217`). `src/app/services/evaluation_rules.py:275-289` |
| SERVC_QUAL_POST_20260526_ATTACH_04 | 별표 3의2 SW 중소기업자간 경쟁제품 대상 | 미확인 (조건부 확정 가능, 조사서 2장) | `src/app/services/evaluation_rules.py:290-306` |
| SERVC_QUAL_POST_20260526_ATTACH_05 | 별표 3 SW 중소기업자간 경쟁제품 비대상 | T=85 선언, B·k 조건부 확정 가능 (조사서 5장) | patterns는 고시금액 미만 중심. `src/app/services/evaluation_rules.py:307-323` |
| SERVC_QUAL_POST_20260526_ATTACH_06 | 별표 1 학술연구 (고시금액 미만) | B=70·k=4·T=85 선언 | 고시금액 2.3억원 미만이라 B 단일 확정. `src/app/services/evaluation_rules.py:324-338` |
| SERVC_QUAL_POST_20260526_ATTACH_07 | 별표 1 학술연구 (고시금액 이상) | k=2·T=85 선언, B 미확인 | 5억원 미만 고시 이상과 5억원 이상을 1개 rule에 포함. `src/app/services/evaluation_rules.py:339-357` |
| SERVC_QUAL_POST_20260526_ATTACH_08 | 별표 4 폐기물처리 (고시금액 미만) | B=70·k=4·T=85 선언 | `src/app/services/evaluation_rules.py:358-372` |
| SERVC_QUAL_POST_20260526_ATTACH_09 | 별표 4 폐기물처리 (고시금액 이상) | k=2·T=85 선언, B 미확인 | `src/app/services/evaluation_rules.py:373-391` |
| SERVC_QUAL_POST_20260526_ATTACH_10 | 별표 5의2 화물 육상운송 (고시금액 미만) | B=70·k=4·T=85 선언 | `src/app/services/evaluation_rules.py:392-406` |
| SERVC_QUAL_POST_20260526_ATTACH_11 | 별표 5의2 화물 육상운송 (고시금액 이상) | k=2·T=85 선언, B 미확인 | `src/app/services/evaluation_rules.py:407-425` |
| SERVC_QUAL_POST_20260526_ATTACH_12 | 없음 (별표 외 일반 띠) | 전부 미확인 (확정 불가, 조사서 6장) | `src/app/services/evaluation_rules.py:426-442` |
| SERVC_QUAL_POST_20260526_ATTACH_13 | 없음 (별표 외 일반 띠) | 전부 미확인 (확정 불가, 조사서 6장) | `src/app/services/evaluation_rules.py:443-459` |
| SERVC_QUAL_POST_20260526_ATTACH_14 | 없음 (별표 외 일반 띠) | 전부 미확인 (확정 불가, 조사서 6장) | `src/app/services/evaluation_rules.py:460-476` |

별표 귀속 근거는 개정 전 대응표(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:263-278`)와 개정 후 판정표(`docs/analysis/servc_post_rules_audit_20260929.md:181-196`)의 일치이다.

---

## 2. PRE_20250901 14종 대응표 (제2025-257호·제2026-15호, 시행 2025-09-01)

POST와 같은 ATTACH 번호 체계를 쓰며 별표 귀속도 같다. 값이 아니라 세대만 다르다(조사서 4.1표).

| rule_id | 공식 별표 | POST와 다른 점 |
| --- | --- | --- |
| SERVC_QUAL_PRE_20250901_ATTACH_01 | 별표 2 시설분야 | 기준비율 91(k 5 단일). POST는 93. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:163` |
| SERVC_QUAL_PRE_20250901_ATTACH_02 | 별표 6 보험 | 기준비율·k·B·T 모두 POST와 동일 |
| SERVC_QUAL_PRE_20250901_ATTACH_03 | 별표 5 여객 | 기준비율 91(k 4 단일). POST와 동일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:167` |
| SERVC_QUAL_PRE_20250901_ATTACH_04 | 별표 3의2 SW 대상 | 기준비율 91(k 4 단일). POST와 동일. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:165` |
| SERVC_QUAL_PRE_20250901_ATTACH_05 | 별표 3 SW 비대상 | 기준비율 88(k 2/4). POST는 90. `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:164` |
| SERVC_QUAL_PRE_20250901_ATTACH_06 | 별표 1 학술연구 (고시금액 미만) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_07 | 별표 1 학술연구 (고시금액 이상) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_08 | 별표 4 폐기물 (고시금액 미만) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_09 | 별표 4 폐기물 (고시금액 이상) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_10 | 별표 5의2 화물 (고시금액 미만) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_11 | 별표 5의2 화물 (고시금액 이상) | 기준비율 88(k 2/4). POST는 90 |
| SERVC_QUAL_PRE_20250901_ATTACH_15 | 별표 7 수리·점검 | POST에 대응 rule 없음 (개정 전 전용). `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:291-297` |
| SERVC_QUAL_PRE_20250901_ATTACH_16 | 별표 8 임대차 | POST에 대응 rule 없음 (개정 전 전용). 같은 근거 |
| SERVC_QUAL_PRE_20250901_ATTACH_17 | 별표 9 수요기관 지정형 | POST에 대응 rule 없음 (개정 전 전용). 같은 근거 |

주의할 비대칭이다. PRE에는 별표 7·8·9 전용 rule(ATTACH_15·16·17)이 있고 일반 띠 rule(ATTACH_12·13·14)이 판정표에 없다. POST에는 일반 띠 rule(ATTACH_12·13·14)이 있고 별표 7·8·9 전용 rule이 없다. 판정표에 없는 rule_id는 판정 함수가 미확인 사유만 남긴다(`src/app/services/evaluation_rules.py:222-226`).

---

## 3. PRE_20230501 14종 대응표 (제2023-53호 추정, 시행 2023-05-01)

ATTACH 번호 체계는 PRE_20250901과 같다(01~11·15·16·17). 별표 귀속 후보도 같다. 다만 배점표(B·k·T)는 조사 범위 밖이라 14건 전부 미확인이다(`src/app/services/evaluation_rules.py:59-62`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:658`). 별표 1·11의 배점표가 제2025-257호와 다르다는 기록이 있어(`src/app/services/evaluation_rules.py:748-750`) 2025-257호 값을 소급 적용할 수 없다. 상세 사유는 조사서 7장이다.

---

## 4. POST_20260727 2종 대응표 (제2026-390호, 시행 2026-07-27)

| rule_id | 공식 별표 | 상태 |
| --- | --- | --- |
| SERVC_QUAL_POST_20260727_ATTACH_03 | 별표 5 여객 | 기준비율 91에서 93으로, 하한율 87.995에서 89.995로 상향 추정. 별표 확정 원문 미확보라 B·k·T 선언 불가. `docs/analysis/servc_post_rules_audit_20260929.md:205-208,263`. 코드 객체는 존재한다(`src/app/services/evaluation_rules.py:487-494`). 판정표에 선언이 없어 조회 시 미확인 사유가 남는다(`src/app/services/evaluation_rules.py:222-226`) |
| SERVC_QUAL_POST_20260727_ATTACH_04 | 별표 3의2 SW 대상 | 위와 같은 상태. 코드 객체는 존재한다(`src/app/services/evaluation_rules.py:495-502`) |

---

## 5. 별표별 B·k·T 빠른 참조 (제2026-260호 세대)

상세 근거는 조사서 4장이다.

| 별표 | 기준비율 | k | B | T |
| --- | ---: | --- | ---: | ---: |
| 1 학술연구 | 90 | 2(고시금액 이상)/4(미만) | 60/70 | 85 |
| 2 시설분야 | 93 | 5 단일 | 60/70 | 85 |
| 3 SW 비대상 | 90 | 2/4 | 60/70 | 85 |
| 3의2 SW 대상 | 91 | 4 단일 | 60/70 | 88 |
| 4 폐기물처리 | 90 | 2/4 | 60/70 | 85 |
| 5 여객 | 91 | 4 단일 | 60/70 | 88 |
| 5의2 화물 | 90 | 2/4 | 60/70 | 85 |
| 6 보험 | 88 | 0.375 단일 | 60/70 | 85 |
| 7 수리·점검 | 90 | 2/4 | 60/70 | 85 |
| 8 임대차 | 90 | 2/4 | 70 단일 | 85 |
| 9 수요기관 지정형 | 90 | 2/4 | 60 이상 70 이하 | 85 |

- 기준비율·k 근거: `docs/analysis/servc_post_rules_audit_20260929.md:100-112`
- B 근거: `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:174`, 별표 8·9 특칙은 같은 문서 `120-138`
- T 근거: `docs/analysis/servc_post_rules_audit_20260929.md:131`, `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176`
- 별표 9 실측 교차 확인: B 60/70, k 2/4, 기준비율 0.9(`docs/analysis/20260930_score_params_acquisition.md:126-139`), T 85(`docs/analysis/20260930_score_params_acquisition.md:143-148`)
- B의 60/70은 추정가격 5억원 축, k의 2/4는 고시금액 축(2025~2026년 2.3억원, `docs/design/g2b_procurement_institution_analysis.md:100-105`)이다. 두 축이 다르므로 단일값 선언이 불가능한 조합이 있다(조사서 4.4절).

---

## 6. 1:N 분기 목록

1개 별표가 2개 rule_id로 나뉘는 경우만 존재한다. 1개 rule_id가 2개 별표에 걸치는 경우는 없다.

| 별표 | rule_id 분기 | 분기 축 |
| --- | --- | --- |
| 별표 1 학술연구 | ATTACH_06 / ATTACH_07 | 고시금액 미만 / 이상 |
| 별표 4 폐기물처리 | ATTACH_08 / ATTACH_09 | 고시금액 미만 / 이상 |
| 별표 5의2 화물 | ATTACH_10 / ATTACH_11 | 고시금액 미만 / 이상 |

분기하지 않는 별표(별표 2·3·3의2·5·6)는 5억원 미만·이상을 1개 rule_id에 함께 담는다. 이 경우 B는 구간 조건부(60/70)로만 확정할 수 있다.
