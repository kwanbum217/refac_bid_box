# 한국공항공사 별표 3의 2 소프트웨어용역(중소기업자간 경쟁제품 대상) 기관 규칙 등록

> **작성일**: 2026-10-17
> **작업**: 한국공항공사 일반용역 적격심사세부기준(2026-08-14 시행) 별표 3의 2 기관 규칙 등록
> **정본 명세**: [`data/reference/institution_rules_20261013.yaml`](../../data/reference/institution_rules_20261013.yaml) 한국공항공사 항목
> **코드 정본**: [`src/app/services/evaluation_rules.py`](../../src/app/services/evaluation_rules.py) 의 `INSTITUTION_RULES`
> **선행 조사**: [`kac_unregistered_annex_20261017.md`](kac_unregistered_annex_20261017.md)

---

## 1. 요약

한국공항공사 일반용역 적격심사세부기준(최종 개정 2026-08-05 지침 제792호, 2026-08-14 이후
입찰공고분 적용)의 별표 3의 2 를 기관 규칙 `SERVC_INST_KAC_20260814_SOFTWARE_SME` 하나와 구간
2개로 등록했습니다. 선행 조사가 별표 3·3의 2 가운데 별표 3의 2(중소기업자간 경쟁제품 대상)만
공고 낙찰방법명의 대상 표기로 판별 가능하다고 확정한 데 따른 등록이며, 값은 새로 추정하지
않고 이미 확인된 명세 행을 그대로 옮겼습니다.

| 항목 | 값 |
| --- | --- |
| 규칙 ID | `SERVC_INST_KAC_20260814_SOFTWARE_SME` |
| 기관 | 한국공항공사(B551178, 별칭 17개는 기존 KAC 규칙과 동일) |
| service_type | `SOFTWARE` |
| 시행일 | 2026-08-14 |
| 구간 | 2개(추정가격 5억원 미만 B 70, 5억원 이상 B 60) |
| 통과점수 | 88 (제10조 소프트웨어용역 중소기업자간 경쟁제품 대상) |
| 하한율 | 89.995% (두 구간 동일) |
| 표기 토큰 | `소프트웨어용역중소기업자간경쟁제품대상` |
| 정량평가 배점표 | 미확보라 `quant_table=False`(정량점수 직접 입력 유지) |
| DB 스키마·데이터 변경 | 없음 |

---

## 2. 등록 규칙

| 항목 | 값 |
| --- | --- |
| table_name | 한국공항공사 일반용역 적격심사 (소프트웨어용역 중소기업자간 경쟁제품 대상) |
| description | 한국공항공사 별표 3의 2 소프트웨어용역(중소기업자간 경쟁제품 대상) 2구간 |
| source | `docs/analysis/kac_annex_3_2_register_20261017.md:3` |
| patterns | `("소프트웨어용역중소기업자간경쟁제품대상",)` |
| quant_basis | `AGENCY_DOCUMENT_NOT_LOADED` |

- 배치 위치는 `INSTITUTION_RULES` 의 한국공항공사 `..._REPAIR`(별표 7) 규칙 뒤입니다.
  규칙 순서는 판정에 쓰이지 않고, 기관 축(수요기관 코드·이름)과 표기 토큰으로만 선택됩니다.

---

## 3. 구간 값

| 구간 | 추정가격 | B | k | 기준비율 | 통과점수 | 하한율 | 평탄 조건 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 별표 3의 2 소프트웨어용역(중소기업자간 경쟁제품 대상) · 5억원 미만 | 5억원 미만 | 70 | 4 | 93 | 88 | 89.995 | 예정가격의 96% 이상 |
| 별표 3의 2 소프트웨어용역(중소기업자간 경쟁제품 대상) · 5억원 이상 | 5억원 이상 | 60 | 4 | 93 | 88 | 89.995 | 예정가격의 96% 이상 |

- **구간이 둘인 이유**: 별표 3의 2 는 사업예산규모 표가 구간을 나누어 인쇄되지 않아 평점계수
  k=4 와 기준비율 93 이 단일하고, 배점한도 B 의 추정가격 5억원 경계만 구간을 만듭니다. 종전
  등록분의 별표 1·4·7(세 구간)과 달리 고시금액 경계가 없습니다.
- **하한율 계산**: `93 - (100 - 88) / 4 = 90` 이고, 90 을 소수 둘째 자리까지 버린 뒤 0.005 를
  빼면 89.995 입니다. 두 구간의 k·기준비율·통과점수가 같아 하한율도 같습니다.
- **평탄 조건**: 원문은 "예정가격의 96% 이상인 경우에는 예정가격의 96%인 경우의 점수로
  평가한다" 는 조건을 인쇄합니다. `기준비율 93 + (100 - 88) / 4 = 96` 이 그 조건과 일치해
  명세 `price_cap_rate` 에 96 을 적었고, 그 조건에서의 점수는 원문이 인쇄하지 않아
  `flat_score` 는 null 로 두었습니다(종전 한국공항공사 등록분과 같은 처리).
- **금액·점수 스케일**: 명세의 `base_ratio` 93 은 코드에서 0.93 으로 변환되고, 하한율·통과점수는
  인쇄값 그대로입니다.

---

## 4. patterns 근거

표기 토큰은 공고 낙찰방법명의 대상 표기를 그대로 담은
`소프트웨어용역중소기업자간경쟁제품대상` 하나입니다. 매칭은 낙찰방법명과 공고명을 공백·구두점
제거 후 대조하고 가장 긴 표기가 이기므로(`_institution_match_score`), `소프트웨어용역(중소기업자간
경쟁제품 대상) 적격심사 …` 는 이 토큰으로 잡힙니다.

`소프트웨어용역` 단독은 토큰으로 쓰지 않았습니다. 같은 별표 쌍의 별표 3(비대상, 통과점수 85)과
구분되지 않고, 공고명에 소프트웨어가 들어간 공고서참조 공고까지 별표 3의 2 로 끌어오기
때문입니다.

| 낙찰방법명 | 수요기관 표기 | 건수 |
| --- | --- | ---: |
| `적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만` | 한국공항공사 | 1 |
| `적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만` | 한국공항공사 김포공항 | 2 |
| `적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 이상` | 한국공항공사 | 2 |

- 조회(2026-10-17, `scripts/db_readonly_query.py` 읽기 전용):

```sql
SELECT dminstt_nm, JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS method, COUNT(*) AS cnt
FROM bid_announcements
WHERE dminstt_nm LIKE '%한국공항공사%' AND category = 'Servc'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%소프트웨어%'
GROUP BY dminstt_nm, method ORDER BY cnt DESC
```

- 대상 표기가 없는 소프트웨어 공고는 이 규칙으로 가지 않습니다. 아래는 공고명에만 소프트웨어가
  있고 낙찰방법명이 `공고서참조`·`수의시담` 인 공고들이며, 어느 것도 새 토큰과 일치하지
  않습니다.

| 공고명 | 낙찰방법명 | 건수 |
| --- | --- | ---: |
| 통합재난안전시스템 소프트웨어 기술지원 용역 | 공고서참조 | 5 |
| 출입증관리시스템 소프트웨어 기술지원 용역 | 공고서참조 | 3 |
| 인천 항공교통관제시스템 소프트웨어 유지보수 용역 | 공고서참조 | 2 |
| 글로벌 항공정보 종합관리망(SWIM) 소프트웨어 인증(DO-278A) 사업 | 공고서참조 | 1 |
| UAM 이착륙장(Vertiport) 모의 운용 시스템 구축을 위한 소프트웨어 개발 사업 | 공고서참조 | 1 |
| 항공정보처리시스템(AMHS) 소프트웨어 기술지원 용역 | 수의시담-수의시담 | 1 |
| 항공교통관제시스템 소프트웨어 기술지원 용역 | 수의시담-수의시담 | 1 |

---

## 5. 바꾸지 않은 것

| 항목 | 내용 |
| --- | --- |
| 기관 축 | 수요기관 코드 `B551178` 과 별칭 17개, 시행일 2026-08-14 를 기존 KAC 규칙과 같게 유지 |
| 확인 기관 수 | `status=confirmed` 12곳 그대로(한국공항공사는 이미 등록 기관) |
| 미등록 별표 | 별표 3(비대상), 별표 5·5의 2(육상운송용역), 별표 8(임대차용역), 별표 9(지정형 용역), 기술용역은 등록하지 않음 |
| 정량평가 배점표 | 심사항목 배점표 미확보라 `quant_table=False`, 정량점수 직접 입력 유지 |
| 다른 기관 규칙 | 값·구간 변경 없음 |
| 원장·현황 문서 | `data/reference/rule_coverage_ledger.yaml` 과 `docs/context/CURRENT_STATE.md` 는 수정하지 않음(원장은 병합 때 코디네이터가 코디네이터 브랜치에서 갱신) |
| DB | 스키마·데이터 변경 없음(읽기 전용 조회만 수행) |
| main 브랜치 | 직접 커밋 없음(작업 브랜치에서 커밋) |

### 5.1 후속 확인 대상(이번 범위에서 손대지 않음)

| 항목 | 내용 |
| --- | --- |
| `institution_rules_apply_20261013.md` 2절 규칙 수 | 인천국제공항공사 11·인천공항시설관리 12 로 적혀 있으나 실제 코드는 10·11 입니다(임대차 k=2·k=4 두 규칙을 고시금액 경계 한 규칙으로 합친 후속 변경이 문서에 반영되지 않음). 한국공항공사 행만 이번 등록분으로 갱신했고 나머지는 그대로 두었습니다. |
| 별표 3(비대상) | 비대상 표기 공고가 조회되지 않아 미등록입니다. 비대상 공고가 확인되면 별표 3(통과점수 85) 등록이 필요합니다. |

---

## 6. 검증

| 항목 | 명령 | 결과 |
| --- | --- | --- |
| 기관 규칙 시험 | `uv run pytest tests/test_institution_rules.py tests/test_evaluation_quant_institution.py -q -m 'not data_assets'` | 56 passed |
| 전량 시험 | `uv run pytest tests/ -q -m 'not data_assets'` | 7692 passed, 41 skipped, 3 deselected |
| 원장 정합 시험 | `uv run pytest tests/test_rule_coverage_ledger.py -q -m 'not data_assets'` | 21 passed(원장 미수정이라 그대로 통과) |
| 타입 | `uv run mypy src` | Success: no issues found in 135 source files |
| 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 21/21 건 |
| 구간 값 대조 | YAML 한국공항공사 band 와 코드 구간 대조(`test_confirmed_institution_band_values_match_yaml`, 구간 합계 159) | 통과 |
| 신규 단정 | 대상 표기 공고 -> 규칙 선택·하한율 89.995, 표기 없는 공고 -> 미선택 | 통과 |

- 신설·수정 시험: `test_kac_registers_general_service_tables_and_software_sme_rule`,
  `test_kac_software_sme_rule_bands_match_spec`,
  `test_kac_software_sme_announcement_selects_rule_both_bands`,
  `test_kac_software_token_without_sme_marker_does_not_select_rule`,
  구간 합계 단정 157 -> 159, 기관 정량표 미반영 규칙 목록에 신규 규칙 추가.

### 6.1 전량 시험 결과

```
$ uv run pytest tests/ -q -m 'not data_assets'
7692 passed, 41 skipped, 3 deselected in 278.65s (0:04:38)
```

---

## 7. 변경 파일

| 파일 | 내용 |
| --- | --- |
| `src/app/services/evaluation_rules.py` | `SERVC_INST_KAC_20260814_SOFTWARE_SME` 규칙과 구간 2개 추가, 미등록 별표 주석 갱신 |
| `data/reference/institution_rules_20261013.yaml` | 한국공항공사 항목에 별표 3의 2 band 2개(status confirmed), `service_types`·`note`·`sources` 갱신 |
| `tests/test_institution_rules.py` | 구간 합계 159, 별표 3의 2 규칙 값·선택·비선택 단정 |
| `tests/test_evaluation_quant_institution.py` | 기관 정량표 미반영 규칙 목록에 신규 규칙 추가 |
| `docs/analysis/institution_rules_apply_20261013.md` | 한국공항공사 행(6규칙·15구간)과 요약 수치, 별표 3의 2 등록 문장 갱신 |
| `docs/analysis/kac_annex_3_2_register_20261017.md` | 본 문서 |
