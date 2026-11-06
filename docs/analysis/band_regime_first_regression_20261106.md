# 첨부 판별 갈래 우선 적용 전후 판정 회귀 (2026-11-06)

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_619f854e3edc` (builder), Run `run_8734173629f4`
> **정본 사양**: `.orca/capsules/task_619f854e3edc/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/regime-first`
> **선행 조사**: [`band_regime_vs_region_rule_priority_20261106.md`](band_regime_vs_region_rule_priority_20261106.md), `kwanbum217/prio21` 브랜치의 `docs/analysis/priority_21_citation_check_20261106.md`
> **범위**: `src/app/services/evaluation_rules.py` 의 해석 순서를 기관 규칙 -> 첨부 판별 -> 시·도 규칙 -> 조달청 기본으로 바꾼 뒤, 최근 12개월 Servc 31,348건의 판정을 수정 전과 비교합니다. 원장 파일은 쓰지 않았습니다.

---

## 1. 요약

| 항목 | 값 |
| --- | --- |
| 모집단 | 최근 12개월 Servc, 낙찰방법 코드 `낙030001`, 공고번호별 최신 차수 |
| 수정 전 판정 건수 | 31,348 |
| 수정 후 판정 건수 | 31,348 |
| 판정이 바뀐 공고 | **21건** (경기 12, 경남 8, 대구 1) |
| 21건 목록 밖 판정 변경 | **0건** |
| 경고 문구만 바뀐 공고 | 15건 (규칙·범위·하한율 불변) |
| 실제 적용 하한율이 바뀐 공고 | 0건 (21건 모두 80.495 유지) |
| 판정 | `candidate` |

- 바뀐 21건은 모두 `MOIS_ACADEMIC` 판별 + `2억미만 1억이상` 낙찰방법명 + 시·도 일반 별표가 함께 있던 공고입니다.
- 21건의 적용 규칙은 `SERVC_LOCAL_*` 에서 `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` 로 바뀌고, 범위는 `REGION` 에서 `ALL` 로 바뀝니다.
- 규칙 선언값은 경기·경남 B 90·k 20·T 95 에서 B 60·k 2·T 85 로, 대구 B 70·k 60·T 85 에서 B 60·k 2·T 85 로 바뀝니다. 공고 하한율 80.495 가 규칙 기본값을 덮어쓰므로 실제 적용 하한율은 그대로입니다.

---

## 2. 구현 변경

| 위치 | 변경 |
| --- | --- |
| `src/app/services/evaluation_rules.py` `resolve_evaluation_rule` | 첨부 판별 갈래를 시·도 분기 앞으로 옮기고, 기관 규칙 분기 뒤에 두었습니다. 순서는 기관 -> 첨부 -> 시·도 -> 조달청입니다. |
| 같은 함수 docstring | 첨부 판별이 기관 다음, 시·도보다 먼저 적용된다고 고쳤습니다. |
| `tests/test_band_regime_first_priority.py` | (a)~(e) 해석 순서 시험과 국가계약·시행일 가드 시험을 추가했습니다. |

첨부 갈래의 기존 가드는 그대로 유지했습니다.

- `attachment_regime` 이 `MOIS_ACADEMIC` 또는 `MOIS_TECH`
- 낙찰방법명에 `2억미만`·`1억이상` 표기가 모두 있음
- `contract_regime != "NATIONAL"`
- 조달청 기본 경로가 `RULE_NOT_FOUND`·`LOCAL_RULE_NOT_FOUND`·`LOCAL_SERVICE_TYPE_UNRESOLVED` 로 차단됨
- 첨부 규칙 시행일(2025-07-01) 이상 공고

시행일 가드에 걸리면 첨부 갈래를 쓰지 않고 종전처럼 시·도 분기로 내려갑니다.

---

## 3. 회귀 방법

- `scripts/report_rule_coverage.py` 의 `collect_records(months=12, category="Servc", method_code="낙030001")` 를 메모리에서 그대로 호출했습니다.
- 공고 식별자를 남기기 위해 `_to_record` 를 얇게 감싸 `bid_ntce_no`·`bid_ntce_ord` 만 덧붙였습니다. 판정 로직은 바꾸지 않았습니다.
- DB 세션은 `collect_records` 가 여는 `SET SESSION TRANSACTION READ ONLY` 만 사용했습니다. 원장 파일과 DB 에는 쓰지 않았습니다.
- 비교 필드는 `error_type`, `is_blocked`, `block_reason_code`, `rule_id`, `scope_stage`, `effective_lwlt_rate`, `rate_source` 입니다.
- 수정 전 스냅샷과 수정 후 스냅샷의 공고 키 집합이 같은지 먼저 확인했습니다.

---

## 4. 전후 규칙 ID 표 (21건)

| # | 공고번호-차수 | 수요기관 | 계약 법령 | 수정 전 규칙 | 수정 후 규칙 | 범위 | 적용 하한율 |
| ---: | --- | --- | --- | --- | --- | --- | ---: |
| 1 | R25BK01183253-000 | 경기도 광주시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 2 | R25BK01217261-001 | 경상남도 하동군 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 3 | R25BK01224070-000 | 경기도 용인시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 4 | R26BK01263688-000 | 경기도 광주시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 5 | R26BK01315683-000 | 경상남도 통영시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 6 | R26BK01316286-000 | 경상남도 김해시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 7 | R26BK01338990-000 | 경기도 김포시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 8 | R26BK01363389-000 | 경기도 남양주시 공원녹지관리사업소 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 9 | R26BK01393041-000 | 경기도 가평군 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 10 | R26BK01393864-000 | 경기도 평택시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 11 | R26BK01405797-000 | 경기도 용인시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 12 | R26BK01411268-000 | 경기도 가평군 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 13 | R26BK01435503-000 | 경기도 포천시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 14 | R26BK01444191-000 | 대구광역시 | LOCAL | `SERVC_LOCAL_DAEGU_20220930_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 15 | R26BK01456235-000 | 경상남도 밀양시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 16 | R26BK01467780-000 | 경기도 의정부시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 17 | R26BK01507413-000 | 경기도 성남시 | LOCAL | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 18 | R26BK01548846-000 | 경상남도 사천시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 19 | R26BK01555770-000 | 경상남도 남해군 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 20 | R26BK01662690-000 | 경상남도 양산시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |
| 21 | R26BK01737598-000 | 경상남도 진주시 | LOCAL | `SERVC_LOCAL_GN_20230105_ATTACH_01` | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | REGION -> ALL | 80.495 |

- 21건의 공고번호는 선행 조사 2.1절 목록과 같습니다. 목록 밖에서 규칙·차단·범위·하한율이 바뀐 공고는 없습니다.
- 21건 모두 공고 하한율 80.495 가 규칙 기본값을 덮어써 실제 적용 하한율은 수정 전후 80.495 로 같습니다. 가격점수 곡선(B·k)과 통과점수(T)만 바뀝니다.

---

## 5. 목록 밖 변화 점검

### 5.1 판정 변경 0건

- 31,348건 중 판정 필드가 바뀐 공고는 위 21건뿐입니다.
- `error_type` 이 바뀐 공고, 차단 코드가 바뀐 공고, `PPS`·`LOCAL` 판별에서 규칙이 바뀐 공고는 없습니다.

### 5.2 경고만 바뀐 15건

아래 15건은 규칙·범위·하한율이 그대로이고 경고 목록만 달라졌습니다. 수정 전에는 시·도 세부유형 후보 경고(`후보 별표: ...`)가 함께 남았는데, 첨부 갈래를 시·도 분기보다 먼저 보면서 그 경고가 사라졌습니다. 판정에는 영향이 없습니다.

| 공고번호-차수 | 수요기관 | 적용 규칙 |
| --- | --- | --- |
| `R25BK01242428-000` | 전북특별자치도 고창군 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01265973-000` | 강원특별자치도 화천군 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01271755-000` | 제주특별자치도 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01297162-000` | 제주특별자치도 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01299139-000` | 인천광역시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01333358-000` | 울산광역시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01379713-000` | 제주특별자치도 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01379750-000` | 제주특별자치도 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01477890-000` | 전북특별자치도 정읍시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01492327-000` | 충청북도 청주시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01522611-000` | 전북특별자치도 남원시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01668348-000` | 울산광역시 울주군 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01716123-000` | 경상북도 영천시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01716155-000` | 경상북도 영천시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |
| `R26BK01716198-000` | 경상북도 영천시 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` |

---

## 6. 검증 명령

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_band_regime_first_priority.py tests/test_band_regime_resolve.py tests/test_band_regime_lookup.py -q` | 27 passed |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'evaluation_rules or regime or local'` | 1156 passed, 9312 deselected |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10422 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 7. 남은 일과 제약

- 이 브랜치는 사용자 결정 대기 중인 선행 구현입니다. 병합하지 않았고 `main` 에 커밋하지 않았습니다.
- `data/reference/rule_coverage_ledger.yaml` 은 다시 쓰지 않았습니다. 원장의 출처 라벨(`REGION` -> `MOIS` 축) 정리는 별도 결정 사항입니다.
- `PPS` 판별의 `2억미만 1억이상` 띠는 여전히 풀 규칙이 없습니다. 이번 변경은 `MOIS_ACADEMIC`·`MOIS_TECH` 갈래만 다룹니다.
- 시·도 규칙이 하나로 확정되지 않아 차단되던 공고(15건)는 경고만 달라졌고 판정은 유지됩니다.
