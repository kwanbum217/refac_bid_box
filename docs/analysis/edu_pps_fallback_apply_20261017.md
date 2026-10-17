# 교육 계열 공고의 조달청 일반용역 적격심사 기준 대체 경로 적용

> **작성일**: 2026-10-17
> **작업**: Orca Task `task_0f12e3bc2766` (builder)
> **정본 사양**: `.orca/capsules/task_edu_pps_fallback_20261017/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/orca-edu-pps-fallback`
> **근거 조사 문서**: `docs/analysis/edu_local_rule_basis_20261017.md` (다른 브랜치 `kwanbum217/orca-edu-local-basis` 에 있어 이 워크트리에는 없다)
> **선행 조사 문서**: `docs/analysis/local_rule_gap_prep_20261015.md` (이 워크트리에 있음)
> **측정 DB**: 호스트 `127.0.0.1:3306` 의 Docker MySQL. 읽기 전용 질의만 사용.
> **범위**: 시·도를 산출하지 못한 교육 계열 용역 적격심사 공고만.

---

## 1. 목적과 결론

- 목적: 지방계약 교육 계열 기관(시·도교육청·교육지원청·공립 학교·유치원) 공고가 시·도 값을 산출하지 못해 `LOCAL_RULE_NOT_FOUND` 로 막힐 때만, 조달청 일반용역 적격심사 세부기준(기본 규칙) 매칭 결과로 계산하게 한다.
- 결론: `resolve_evaluation_rule` 과 `resolve_evaluation_rule_from_raw_data` 에 `education_institution` 인자를 더하고, LOCAL 분기의 시·도 규칙 선택이 실패한 경우 중 **교육 계열 + `region_code` 없음 + `LOCAL_RULE_NOT_FOUND`** 세 조건을 모두 만족할 때만 차단을 풀고 진입 직전의 조달청 매칭 결과를 그대로 쓴다. 조달청 별표에도 없으면 `RULE_NOT_FOUND` 로 남는다.
- 바꾸지 않은 것: 시·도 규칙으로 계산되던 공고(`region_code` 있음), `LOCAL_SERVICE_TYPE_UNRESOLVED`, 교육 계열이 아닌 지방계약 공고, 국가계약 공고, 기관 규칙 경로, 기술용역 분기, 시행일 대조(4장).
- 근거: 지방계약법 시행령 제42조 제4항의 시·도청 예규 적용 대상에 교육청이 없고, 조달청 일반용역 적격심사 세부기준(조달청공고 제2025-257호) 제3조가 시행령 제42조 제1항 일반용역을 심사대상으로 명시한다(`docs/analysis/edu_local_rule_basis_20261017.md`, 다른 브랜치).

---

## 2. 바꾼 위치

| 파일 | 위치 | 함수·상수 | 변경 |
| --- | --- | --- | --- |
| `src/app/services/demand_institutions.py` | 206 | `is_education_institution` | 신설. 대분류가 `교육행정조직`이고 중분류가 `시, 도교육청`·`지역교육청`·`시, 도교육청 직속기관`이거나, 대분류가 `초등학교`·`중학교`·`고등학교`·`특수학교`·`유치원`이고 소분류가 `공립`이면 True |
| `src/app/services/demand_institutions.py` | 232 | `classify_contract_regime` | 교육 판정을 `is_education_institution` 호출로 대체. 반환값은 바뀌지 않는다 |
| `src/app/services/evaluation_rules.py` | 5947 | `EDU_PPS_FALLBACK_WARNING` | 신설. 대체 경로로 풀린 결과에 붙이는 경고 문구 |
| `src/app/services/evaluation_rules.py` | 6264 | `_narrow_rule_scope` | 신설. 기존 조달청 경로의 축 재선택·범위(scope_stage) 확정 블록을 그대로 함수로 추출해 두 경로가 같은 코드를 쓴다 |
| `src/app/services/evaluation_rules.py` | 6369 | `resolve_evaluation_rule` | `education_institution: bool = False` 인자 추가, LOCAL 분기에 대체 경로 추가, 축 재선택 블록을 `_narrow_rule_scope` 호출로 교체 |
| `src/app/services/evaluation_rules.py` | 6827 | `resolve_evaluation_rule_from_raw_data` | `education_institution: bool = False` 인자를 받아 `resolve_evaluation_rule` 로 전달 |

`_narrow_rule_scope` 추출은 동작을 바꾸지 않는다. 기존 블록(후보 필터 → `INSTITUTION` → `REGION` → `ALL` 순 범위 선택 → 후보 없으면 `RULE_NOT_FOUND`, 같은 범위 복수 후보면 `RULE_SCOPE_AMBIGUOUS`)을 그대로 옮기고 두 호출부가 같은 함수를 쓰게 했다.

---

## 3. 대체 경로 조건

`src/app/services/evaluation_rules.py:6490` 의 조건을 모두 만족할 때만 적용한다. 하나라도 어긋나면 기존과 같이 차단한다.

| 조건 | 값 | 뜻 |
| --- | --- | --- |
| `education_institution` | True | 수요기관이 교육 계열이다 |
| `region_code` | None | 시·도 값이 산출되지 않았다 |
| `local_code` | `LOCAL_RULE_NOT_FOUND` | `_select_local_rule` 이 시·도 규칙을 고르지 못했다 |
| 진입 분기 | `contract_regime == "LOCAL"` | 지방계약 공고이고 기술용역 규칙이 아니다 |

적용 결과는 진입 직전의 조달청 매칭 `result` 이며, `_narrow_rule_scope` 로 조달청 기본 경로와 같은 축 재선택·`scope_stage` 를 거친다. 조달청 별표에도 없어 진입 `result` 가 `RULE_NOT_FOUND` 차단이면 그대로 `RULE_NOT_FOUND` 로 남고 경고를 붙이지 않는다.

### 3.1 경고 문구

`src/app/services/evaluation_rules.py:5947` 의 `EDU_PPS_FALLBACK_WARNING` 한 문장을 조달청 기준으로 풀린 결과의 경고 목록 끝에 붙인다. 새 범위 상수는 만들지 않고 `scope_stage` 는 기존 `RULE_SCOPE_*` 값을 쓴다.

```
교육청 공고: 시·도 규칙 대신 조달청 일반용역 적격심사 세부기준을 적용했습니다(지방계약법 시행령 제42조 제1항, 조달청 세부기준 제3조).
```

---

## 4. 호출부 다섯 곳

시·도를 넘기는 호출부 다섯 곳이 모두 `is_education_institution(institution)` 을 넘긴다. 화면, 예측, 커버리지 원장의 판정이 같아진다.

| 파일 | 행 | 호출 문맥 |
| --- | ---: | --- |
| `src/app/api/v1/evaluations.py` | 1703 | `_resolve_evaluation_inputs` (/analyze·/recommend 공용 규칙 판별) |
| `src/app/api/v1/evaluations.py` | 2107 | 분석 응답 스냅샷 저장용 규칙 문맥 |
| `src/app/api/v1/evaluations.py` | 2676 | 별표 메타 API 의 `matched_rule` 판별 |
| `src/app/api/v1/predictions.py` | 337 | 추천가 채점의 기준비율·가격 구간 판별 |
| `scripts/report_rule_coverage.py` | 388 | 커버리지 원장 재생성의 공고별 판정 |

`src/app/services/bid_queries.py:580` 과 `scripts/backtest_qualification_rules.py:380` 은 시·도를 넘기지 않으므로 고치지 않았다. 인자를 넘기지 않는 다른 호출부는 기본값 `False` 라 종전과 같다.

---

## 5. 시험

`tests/test_edu_pps_fallback.py` (신설) 가 다음을 단정한다.

| 시험 | 단정 |
| --- | --- |
| `test_education_without_sido_uses_pps_rule` | 교육청(`institution_sido` 가 `(None, None)`) + 조달청 별표 매칭 → 차단 해제, 조달청 경로와 같은 `rule_id`, `RULE_SCOPE_ALL`, 경고 문구 포함 |
| `test_education_school_without_sido_uses_pps_rule` | 공립 학교도 같은 경로로 풀린다 |
| `test_education_without_sido_keeps_rule_not_found_without_pps_rule` | 조달청 별표에도 없으면 `RULE_NOT_FOUND` 이고 경고가 없다 |
| `test_fallback_requires_education_flag` | `education_institution=False`(기본값) 는 `LOCAL_RULE_NOT_FOUND` 그대로 |
| `test_fallback_requires_local_regime` | 국가계약 경로에는 대체 경로가 끼어들지 않는다 |
| `test_raw_data_path_passes_education_flag` | 호출부가 쓰는 `resolve_evaluation_rule_from_raw_data` 경로도 같은 판정 |
| `test_education_with_sido_keeps_region_rule` | `region_code` 가 있는 교육 계열 공고는 시·도 규칙(`RULE_SCOPE_REGION`) 그대로 |
| `test_education_with_sido_unresolved_service_type_stays_blocked` | 세부유형 미확정(`LOCAL_SERVICE_TYPE_UNRESOLVED`) 차단 유지 |
| `test_local_education_tech_service_keeps_announcement_lwlt` | 기술용역 분기는 공고 하한율 경로 유지 |
| `test_non_education_local_announcement_is_unchanged` | 교육 계열이 아닌 지방계약 공고는 `LOCAL_RULE_NOT_FOUND` 그대로 |
| `test_education_classification_matches_regime` | 13개 기관 유형에서 `is_education_institution` 과 `classify_contract_regime` 의 교육 판정이 일치 |

`tests/test_rule_coverage_ledger.py::test_to_record_passes_education_flag` 는 원장 재생성 경로가 `education_institution` 을 실제로 넘기는지 확인한다. 그 밖의 파일은 고치지 않았다.

---

## 6. 이번 변경이 풀 수 있는 상한

### 6.1 조회 방식

`uv run python scripts/db_readonly_query.py --sql "<질의>"` 형태만 썼다. `docker exec`·`mysql` 직접 호출은 쓰지 않았고, 세션은 읽기 전용이다. 조회는 2026-10-17 에 수행했다.

- 창: 공고일 `2025-10-17` 이상, 업무구분 `Servc`, 낙찰방법 코드 `낙030001`(적격심사제), 최근 12개월.
- 교육 계열: `instt_ty_lrgclsfc_nm = '교육행정조직'` 이고 중분류가 `시, 도교육청`·`지역교육청`·`시, 도교육청 직속기관`이거나, 대분류가 `초등학교`·`중학교`·`고등학교`·`특수학교`·`유치원`이고 소분류가 `공립`. `is_education_institution` 과 같은 조건이다.
- 시·도 본청 값 없음: `institution_sido` 와 같게 `COALESCE(NULLIF(TRIM(toplyvl_instt_nm), ''), SUBSTRING_INDEX(TRIM(rgn_nm), ' ', 1), '')` 이 시·도 16개 명칭과 옛 명칭(강원도·전라북도·제주도·전라남도·광주광역시) 어디에도 들지 않는 경우. `toplvl_instt_nm`(시·도 본청)이 있으면 `rgn_nm` 첫 토큰은 쓰지 않는다.
- 공고 수요기관: `bid_announcements.raw_data->>'$.dminsttCd'` 로 `g2b_demand_institutions` 를 조인한다.

```sql
SELECT COUNT(*) AS rows_cnt,
       COUNT(DISTINCT a.bid_ntce_no) AS notices
FROM bid_announcements a
JOIN g2b_demand_institutions i ON i.dminstt_cd = a.raw_data->>'$.dminsttCd'
WHERE a.category = 'Servc'
  AND a.bid_ntce_dt >= '2025-10-17 00:00:00'
  AND a.raw_data->>'$.sucsfbidMthdCd' = '낙030001'
  AND ((i.instt_ty_lrgclsfc_nm = '교육행정조직'
        AND i.instt_ty_midclsfc_nm IN ('시, 도교육청','지역교육청','시, 도교육청 직속기관'))
    OR (i.instt_ty_lrgclsfc_nm IN ('초등학교','중학교','고등학교','특수학교','유치원')
        AND i.instt_ty_smlclsfc_nm = '공립'))
  AND COALESCE(NULLIF(TRIM(i.toplvl_instt_nm), ''),
               SUBSTRING_INDEX(TRIM(i.rgn_nm), ' ', 1), '')
      NOT IN ('서울특별시','부산광역시','대구광역시','인천광역시','대전광역시','울산광역시',
              '세종특별자치시','경기도','강원특별자치도','충청북도','충청남도','전북특별자치도',
              '전남광주통합특별시','경상북도','경상남도','제주특별자치도',
              '강원도','전라북도','제주도','전라남도','광주광역시')
```

### 6.2 결과

| 구분 | 행 | 고유 공고번호 |
| --- | ---: | ---: |
| 교육 계열 + 시·도 미산출 (상한) | 2,498 | 2,227 |
| 위 중 비예가·수기심사·협상·기술용역 분기를 뺀 값 | 1,089 | 962 |

선행 문서(`docs/analysis/local_rule_gap_prep_20261015.md` 2절·4절)의 `LOCAL_RULE_NOT_FOUND` 시·도 미산출 991건 중 교육 계열 964건과 두 번째 줄의 962건은 차수 중복 제거 방식 차이 범위 안에서 일치한다. 대체 경로가 실제로 푸는 건수는 이 962건 중 진입 시점에 조달청 별표가 매칭되는 공고로 더 좁혀진다.

유형별 분포(두 번째 줄, 고유 공고번호 기준). 학교·유치원 행은 소분류가 모두 `공립`이며 중분류(과정)별로 나누지 않고 합쳤다.

| 대분류 | 중분류·소분류 | 고유 공고번호 |
| --- | --- | ---: |
| 교육행정조직 | 지역교육청 | 427 |
| 교육행정조직 | 시, 도교육청 직속기관 | 129 |
| 교육행정조직 | 시, 도교육청 | 112 |
| 초등학교 | 공립 | 145 |
| 유치원 | 공립 | 47 |
| 고등학교 | 공립 | 50 |
| 중학교 | 공립 | 27 |
| 특수학교 | 공립 | 25 |

### 6.3 한계

- 위 수치는 차단 코드를 보지 않은 SQL 상한이다. 같은 조건의 공고라도 낙찰방법명이 조달청 별표 14종 어디에도 매칭되지 않으면 변경 후에도 `RULE_NOT_FOUND` 로 남으므로, 실제로 풀리는 건수는 이보다 작다.
- 낙찰방법명과 조달청 별표 식별 문자열의 매칭은 SQL 로 재현하지 않았다. 판정 함수만이 정본이다.
- 차수(재공고) 중복을 제거하지 않은 행 수(2,498 / 1,089)와 고유 공고번호(2,227 / 962)를 함께 적었다. 선행 문서는 최신 차수만 남기므로 정확히 같은 기준이 아니다.
- 조회 시점 스냅샷이다. 이후 수집분은 반영되지 않는다.

---

## 7. 바꾸지 않은 것

| 대상 | 이유 |
| --- | --- |
| `region_code` 가 있는 교육 계열 공고 | 시·도 규칙으로 풀리거나 세부유형 불일치로 막히던 판정을 그대로 둔다 |
| `LOCAL_SERVICE_TYPE_UNRESOLVED` | 세부유형 미확정은 사용자 선택 문제라 조달청 기준으로 대체하지 않는다 |
| 교육 계열이 아닌 지방계약 공고 | 시·도 규칙 부재 차단(`LOCAL_RULE_NOT_FOUND`) 그대로 |
| 국가계약 공고 | LOCAL 분기 밖이다 |
| 기관 규칙 경로(`INSTITUTION_RULES`) | 기관 > 시·도 > 조달청 순서 그대로 |
| 기술용역 분기 | 공고 하한율 경로 그대로 |
| 시행일 대조(`RULE_REGIME_MISMATCH`) | 조달청 별표에도 같은 대조를 적용한다 |
| `data/reference/rule_coverage_ledger.yaml`, `docs/context/CURRENT_STATE.md` | 원장은 병합 뒤 코디네이터가 재생성한다 |
| `src/app/services/bid_queries.py`, `scripts/backtest_qualification_rules.py` | 시·도를 넘기지 않는 호출부다 |

---

## 8. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_edu_pps_fallback.py tests/test_local_regime_rules.py tests/test_rule_coverage_ledger.py -q -m 'not data_assets'` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| `uv run mypy src` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |

격리 워크트리라 `data/model_files`·`chroma_db` 부재에 따른 `tests/test_data_preservation.py` 2건은 `-m 'not data_assets'` 로 제외한다(정상).
