# RULE_NOT_FOUND 32건 해소 판정 회귀 (2026-11-06)

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_98340cd68f69` (builder, `run_8734173629f4`). 규칙·시험·회귀 문서만 고친다.
> **정본 사양**: `.orca/capsules/task_98340cd68f69/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/rnf32-fix`
> **선행 근거**: [rule_not_found_32_source_20261106.md](./rule_not_found_32_source_20261106.md) 2.2~2.4, 3.1~3.3, 4.1
> **측정 창**: 2025-11-06 ~ 2026-11-06, 업무구분 `Servc`, 낙찰방법 코드 `낙030001`, 공고번호·업무구분별 최신 차수

---

## 1. 결론

| 항목 | 값 |
| --- | ---: |
| 비교 대상 | 31,348건 |
| 수정 전 RULE_NOT_FOUND (고정 입력 재생) | 42건 |
| 수정 후 RULE_NOT_FOUND (같은 고정 입력) | 10건 |
| 판정이 바뀐 공고 | **32건** |
| 32건 목록 밖에서 바뀐 공고 | **0건** |
| 판정 오류(ERROR) | 0건 |

- 바뀐 32건은 전부 선행 조사 문서 3절의 목록과 일치합니다. 기타용역 17건, SW 비대상 11건, 여객 4건입니다.
- 수정 전 46건에서 42건으로 줄어든 4건은 이번 규칙 변경과 무관합니다. 고정 입력을 뜨기 전에 공유 DB의 첨부 판별 조회 값이 갱신되어 지역 학술연구 4건이 수정 전 코드에서도 함께 풀렸습니다. 두 코드에 같은 입력을 넣었으므로 변경 32건에는 포함되지 않습니다.

---

## 2. 측정 방법

| 단계 | 방법 |
| --- | --- |
| 수집 | `scripts/report_rule_coverage.py` 의 `collect_records(months=12, category="Servc", method_code="낙030001")` 를 메모리에서 실행했습니다. 원장 파일은 쓰지 않았습니다 |
| 입력 고정 | `resolve_evaluation_rule_from_raw_data` 에 전달되는 인자(raw_data 핵심 키, 기관·지역·계약 regime, 추정가격, 교육기관 여부, 첨부 판별 갈래)를 31,348건 분량으로 한 번만 캡처했습니다 |
| 수정 전 재생 | 작업 트리를 `HEAD` 상태로 되돌려 같은 고정 입력을 재생했습니다 |
| 수정 후 재생 | 이번 변경을 적용한 상태에서 같은 고정 입력을 재생했습니다 |
| 비교 키 | `bid_ntce_no`, `bid_ntce_ord` 별 `rule_id`, `block_reason_code`, `is_blocked`, `effective_lwlt_rate`, `rate_source` |
| DB | 읽기 전용 SELECT 만 썼고 `raw_data LIKE` 는 쓰지 않았습니다 |

- 고정 입력 재생을 쓴 이유는 같은 날 공유 DB의 첨부 판별 값이 바뀌어 수정 전후 스냅샷의 입력이 달라졌기 때문입니다. 두 코드에 동일한 입력을 넣어 규칙 변경 효과만 분리했습니다.

---

## 3. 변경된 공고 32건

`적용 띠` 는 수정 후 규칙에서 추정가격으로 고른 구간입니다. `B / k / T` 는 배점한도·평점계수·통과점수입니다. `하한율` 은 서비스가 실제로 적용한 값이며, 공고가 인쇄한 하한율이 있으면 그 값이 규칙 구간값보다 우선합니다.

| # | 공고번호 | 수요기관 | 기관 코드 | 묶음 | 적용 규칙 | B | k | T | 하한율 |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 | R25BK01216649 | 한국지역난방공사 김해사업소 | D325107 | 기타용역 | `SERVC_INST_KDHC_20230719_OTHER` | 80 | 5 | 85 | 84.995 |
| 2 | R25BK01226057 | 한국지역난방공사 동탄지사 | D325152 | 기타용역 | `SERVC_INST_KDHC_20230719_OTHER` | 80 | 5 | 85 | 84.995 |
| 3 | R25BK01245404 | 한국지역난방공사 광교지사 | D325116 | 기타용역 | `SERVC_INST_KDHC_20230719_OTHER` | 80 | 5 | 85 | 84.995 |
| 4 | R26BK01413737 | 한국지역난방공사 대구지사 | D325102 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 80 | 5 | 85 | 84.995 |
| 5 | R26BK01592477 | 한국지역난방공사 대구지사 | D325102 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 6 | R26BK01595814 | 한국지역난방공사 판교지사 | D325114 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 7 | R26BK01600695 | 한국지역난방공사 광교지사 | D325116 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 8 | R26BK01604818 | 한국지역난방공사 강남지사 | D325150 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 80 | 5 | 85 | 84.995 |
| 9 | R26BK01604853 | 한국지역난방공사 강남지사 | D325150 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 80 | 5 | 85 | 84.995 |
| 10 | R26BK01607454 | 한국지역난방공사 세종지사 | D325104 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 11 | R26BK01608131 | 한국지역난방공사 화성지사 | D325156 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 12 | R26BK01611934 | 한국지역난방공사 삼송지사 | D325115 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 13 | R26BK01616444 | 한국지역난방공사 동탄지사 | D325152 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 14 | R26BK01628909 | 한국지역난방공사 서울중앙지사 | D325109 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 15 | R26BK01632830 | 한국지역난방공사 서울중앙지사 | D325109 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 80.495 |
| 16 | R26BK01635339 | 한국지역난방공사 평택지사 | D325160 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 80 | 5 | 85 | 87.745 |
| 17 | R26BK01708025 | 한국지역난방공사 수원사업소 | D325112 | 기타용역 | `SERVC_INST_KDHC_20260101_OTHER` | 50 | 2 | 85 | 82.495 |
| 18 | R26BK01562185 | 군인공제회C_C | Z006079 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 19 | R26BK01596009 | 인천대학교 | 7007971 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 20 | R26BK01610632 | 인천대학교 | 7007971 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 21 | R26BK01629794 | (주)강원랜드 | Z003620 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 22 | R26BK01646244 | 군인공제회C_C | Z006079 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 23 | R26BK01628548 | 과학기술정보통신부 우정사업본부 우정정보관리원 | 1723325 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 60 | 2 | 85 | 82.495 |
| 24 | R26BK01752464 | 대구경북과학기술원 | Z010258 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 25 | R26BK01787939 | 한국산업은행 | B190030 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 60 | 2 | 85 | 82.495 |
| 26 | R26BK01792902 | 한국과학기술정보연구원 | Z004831 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 70 | 2 | 85 | 82.495 |
| 27 | R26BK01795531 | 한국산업은행 | B190030 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 60 | 2 | 85 | 82.495 |
| 28 | R26BK01807230 | 해양경찰청 제주지방해양경찰청 | 1532019 | SW 비대상 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 60 | 2 | 85 | 82.495 |
| 29 | R26BK01751239 | 기후에너지환경부 국립환경과학원 | 1482021 | 여객 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH` | 60 | 4 | 88 | 89.995 |
| 30 | R26BK01805851 | 국토교통부 서울지방항공청 | 1613320 | 여객 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH` | 60 | 4 | 88 | 89.995 |
| 31 | R26BK01810776 | 한전KDN(주) | Z004651 | 여객 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH` | 60 | 4 | 88 | 89.995 |
| 32 | R26BK01813822 | 해양수산부 | 1192000 | 여객 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH` | 60 | 4 | 88 | 89.995 |

---

## 4. 규칙 등록 내용

| 묶음 | 규칙 | 조치 | 값 |
| --- | --- | --- | --- |
| 기타용역 14건(2026-01-01 이후) | `SERVC_INST_KDHC_20260101_OTHER` | 기관 축에 지사·사업소 정확 코드 12개 추가 | 기존 값 유지(B 80/50, k 5/2, 88:100, T 85, 하한 84.995/80.495) |
| 기타용역 3건(2025-12) | `SERVC_INST_KDHC_20230719_OTHER` | 직전판 신규 등록 | B 80/50, k 5/2, 88:100, T 85, 하한 84.995/80.495, 시행 2023-07-19, 폐지 2026-01-01 |
| SW 비대상 고시금액 이상 11건 | `SERVC_QUAL_POST_20260526_ATTACH_21` | 별도 보조 규칙 신규 등록 | B 70(5억원 미만)/60(5억원 이상), k 2, 90:100, T 85, 하한 82.495 |
| 여객 5억원 이상 4건 | `SERVC_QUAL_POST_20260727_ATTACH_03_HIGH` | 390판 전용 보조 규칙 신규 등록 | B 60, k 4, 93:100, T 88, 하한 89.995 |

### 4.1 기관 축

- `INSTITUTION_RULE_EXACT_CODES`([evaluation_rules_institution.py:101](../../src/app/services/evaluation_rules_institution.py:101))에 한국지역난방공사 기타용역 두 규칙의 정확 코드 목록을 두었습니다.
- 목록은 2026-11-06 읽기 전용 DB 조회로 확인한 지사·사업소 코드 12개입니다: `D325102`, `D325104`, `D325107`, `D325109`, `D325112`, `D325114`, `D325115`, `D325116`, `D325150`, `D325152`, `D325156`, `D325160`.
- 접두·대역이 아니라 정확 목록이므로 `D3251xx` 라도 목록 밖 코드에는 적용되지 않습니다. 다른 기관 코드에도 적용되지 않습니다. 회귀 시험 `test_kdhc_rule_does_not_apply_to_unlisted_institution_code` 가 이를 확인합니다.

### 4.2 표준 벌과 분리한 이유

- `SW_NON_SME_NOTICE_ABOVE_RULES`([evaluation_rules.py:1101](../../src/app/services/evaluation_rules.py:1101))와 `PASSENGER_NOTICE_ABOVE_RULES`([evaluation_rules.py:1164](../../src/app/services/evaluation_rules.py:1164))는 표준 별표 20종 벌(`POST_20260526_RULES`, `POST_20260727_RULES`)에 넣지 않고 규칙 배분([evaluation_rules.py:3038](../../src/app/services/evaluation_rules.py:3038))에서만 합칩니다.
- 기존 규칙의 값·적용 조건·선언 순서를 바꾸지 않고, 같은 별표의 다른 띠만 추가하기 위한 분리입니다. 정량 배점표도 `_SUPPLEMENTARY_QUANT_SCORE_TABLES`([evaluation_rules.py:4510](../../src/app/services/evaluation_rules.py:4510))에서 원문 별표 3·5 표를 그대로 씁니다.
- 직전판 기관 규칙도 `PREDECESSOR_INSTITUTION_RULES`([evaluation_rules_institution.py:3473](../../src/app/services/evaluation_rules_institution.py:3473))로 분리해 기관 규칙 선택에서만 합칩니다. 기관 정량 배점표가 직전판에 대해 등록되어 있지 않아 `quant_table=False`(직접 입력)를 유지합니다.

---

## 5. 주의 사항

1. **`R26BK01708025`**: 규칙 구간값은 별표 9 원문 계산값 80.495% 이고, 서비스의 실제 적용 하한율은 공고가 인쇄한 82.495% 입니다. 공고 하한율 우선 정책에 따른 결과이며 규칙 값 자체는 별표 원문을 따릅니다.
2. **`R26BK01635339`**: 공고 `sucsfbidLwltRate` 가 87.745% 라 실제 적용 하한율이 규칙 구간값 84.995% 와 다릅니다. 규칙 판정은 현행 기타용역 규칙으로 정상 해소됐습니다.
3. **`R26BK01813822`**: 공고문이 제2025-257호를 인용하지만 인쇄값 89.995%·88점은 제2026-390호와 같습니다. 390판 보조 규칙으로 판정했습니다.
4. **260판 여객**: 5억원 이상 패턴은 390판 전용 보조 규칙에만 있습니다. 2026-05-26~2026-07-26 공고는 종전처럼 RULE_NOT_FOUND 로 남습니다.
5. **기존 규칙 무변경**: `POST_20260526_RULES` 20종, `POST_20260727_RULES` 20종, `INSTITUTION_RULES`, `QUANT_SCORE_TABLES` 의 값·순서·키를 바꾸지 않았습니다. 신규 시험은 기존 시험 단언을 수정하지 않고 추가만 했습니다.

---

## 6. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_rule_not_found_32_fix.py -q` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'evaluation_rules or institution'` | 717 passed, 6 skipped |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10,388 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
