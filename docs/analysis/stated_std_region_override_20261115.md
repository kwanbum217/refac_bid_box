# 지역 규칙 공고의 공고 명시 기준 우선 적용

> **작성일**: 2026-11-15
> **작업 브랜치**: `kwanbum217/stdreg` (기준 커밋 `5d2e4433`)
> **정본**: `.orca/capsules/task_stated_std_region_override_20261115/capsule.yaml`
> **입력 자료**: `.orca/capsules/task_stated_std_region_override_20261115/judge_5d2e4433_appstd.tsv`(27,638행), 같은 디렉터리 `expect551.txt`(551건)
> **판정**: candidate

---

## 1. 요약

- 시·도 규칙(scope REGION)으로 계산되던 공고 가운데 낙찰방법 적용 기준(`raw_data.sucsfbidMthdAppStd`)이 조달청 일반용역 적격심사 세부기준을 명시하면 조달청 매칭 결과로, 건설폐기물처리용역 적격업체 평가기준을 명시하면 환경부고시 `MOE_CDW_RULES` 의 띠 규칙으로 계산하도록 분기를 추가했습니다.
- 판정 비교 결과 바뀐 공고는 정확히 551건이며 `expect551.txt` 와 같습니다. 범위 밖에서 바뀐 공고는 0건입니다.
- 바뀐 551건은 유형별로 같은 세부유형 별표가 있던 227건, 시·도 일반 별표로 폴백하던 125건, 건설폐기물 명시 199건입니다.
- `expect551.txt` 중 바뀌지 않은 공고는 0건입니다. 범위 밖 15건(명시 없음 3, 학술연구 명시 11, 지역 규칙 시행일 불일치로 이미 차단 1)은 종전 판정을 유지합니다.

---

## 2. 결정과 범위

### 2.1 근거

- 사용자 결정(2026-11-15, 코디네이터 권장안 승인): 공고가 적용 기준을 명시하면 그 기준을 시·도 규칙보다 우선합니다.
- 기존 결정 D13(B, 공고가 조달청 기준을 명시하면 조달청 규칙 우선, `docs/analysis/decision_backlog_20261107.md:80`)의 적용 범위를 육상운송에서 REGION 전체로 넓힌 것입니다.
- 선행 조사 `docs/analysis/appstd_vs_local_rules_20261115.md` 1절·4절 질문 1~3의 대상 551건(조달청 352, 건설폐기물 199)입니다.

### 2.2 대상과 비대상

| 구분 | 건수 | 처리 |
| --- | ---: | --- |
| REGION · 조달청 일반용역 적격심사 세부기준 명시 | 352 | 조달청 매칭 결과로 계산 |
| REGION · 건설폐기물처리용역 적격업체 평가기준 명시 | 199 | 환경부고시 띠 규칙으로 계산 |
| REGION · 학술연구용역 적격심사 세부기준 명시 | 11 | 종전 시·도 규칙 유지(이번 범위 아님) |
| REGION · 명시 없음 | 3 | 종전 시·도 규칙 유지 |
| INSTITUTION · BLOCKED · PPS_DEFAULT | 26,522 | 분기 대상 아님. 기관 규칙 우선·차단 순서는 그대로 |

- 학술연구용역 적격심사 세부기준은 발행기관(조달청 [별표 1] 또는 행안부 예규 [별표 4])이 문자열에 드러나지 않아 이번 결정에서 제외했습니다.
- 기관 규칙(INSTITUTION)은 시·도 규칙보다 먼저 확정되는 기존 순서를 유지합니다. 이번 분기는 시·도 규칙을 확정한 뒤에만 실행됩니다.

---

## 3. 구현

### 3.1 분기 위치

- `src/app/services/evaluation_rules.py:4160`~`:4215` 의 `resolve_evaluation_rule` 안, `_select_local_rule` 이 시·도 규칙을 확정한 `else` 블록입니다.
- 시·도 규칙을 덮어쓰기 전의 조달청 매칭 결과를 `src/app/services/evaluation_rules.py:4002` 에서 `pps_match_result` 로 붙잡아 둡니다.
- 분기 뒤에는 기존 종료 검사(별표 시행일 대조, `src/app/services/evaluation_rules.py:4337`~`:4363`)가 그대로 적용됩니다.

### 3.2 조달청 기준 명시

- 표지: `src/app/services/evaluation_rules.py:3105` 의 `_PPS_STATED_MARKER = "조달청일반용역적격심사세부기준"`. 기존 통합특별시·대구·충남 분기가 쓰던 표지를 이름만 일반화해 함께 씁니다(동작 변경 없음).
- 조건: 공백을 제거한 `app_std` 에 표지가 있고, 낙찰방법명이 환경부고시 띠 6종에 맞지 않으며, 조달청 매칭 결과가 차단이 아니고 규칙이 있을 때입니다.
- 처리: `_narrow_rule_scope` 로 공고일 판본의 같은 세부유형 규칙을 고르고, 하한율 경고를 다시 맞춘 뒤 `JNGJ_STATED_PPS_WARNING` 을 붙입니다. 결과 범위는 조달청 기본 경로와 같은 `RULE_SCOPE_ALL` 입니다.
- `_narrow_rule_scope` 가 후보를 찾지 못하면 시·도 판정을 유지합니다.

### 3.3 건설폐기물 기준 명시

- 표지·경고: `src/app/services/evaluation_rules.py:1375`~`:1379` 의 `MOE_CDW_STATED_MARKER`, `MOE_CDW_STATED_WARNING`.
- 조건: 공백을 제거한 `app_std` 에 `건설폐기물처리용역적격업체평가기준` 이 있을 때입니다.
- 처리: `select_moe_cdw_rule(method_name)` 이 고른 `MOE_CDW_RULES` 규칙을 `_apply_rule_lwlt` 로 적용하고 `MOE_CDW_STATED_WARNING` 을 붙입니다. 낙찰방법명이 고시 띠 6종에 맞지 않아 규칙을 고르지 못하면 시·도 판정을 유지합니다.
- 기존 환경부고시 대체 경로(`src/app/services/evaluation_rules.py:4285` 부근, `_is_moe_cdw_fallback_target`)는 차단·띠 규칙에만 걸리므로 이번 분기와 겹치지 않습니다.

### 3.4 기존 판정을 유지하는 조건

- `local_applies = announced is None or announced >= selected.effective_date` (`src/app/services/evaluation_rules.py:4177`): 시·도 규칙 시행일이 공고일보다 늦어 종전에 `RULE_REGIME_MISMATCH` 로 막히던 공고는 공고 명시로 풀지 않습니다. 이 조건이 없으면 `R26BK01375736` 1건이 차단에서 조달청 규칙으로 바뀌어 범위를 벗어납니다(4.5절).
- 조달청 매칭 결과가 차단(`pps_match_result.is_blocked`)이면 매칭 결과가 없는 것으로 보고 시·도 판정을 유지합니다.
- 명시 없음, 학술연구용역 명시, 기관 규칙 확정, 차단 공고는 분기 자체에 걸리지 않습니다.
- 낙찰방법명의 화물->여객 교정(`correct_passenger_method_name`)은 종전처럼 조달청 경로에서만 동작합니다. 별도 육상운송 분기를 만들지 않았고, D13 원칙은 이 일반 분기로 함께 적용됩니다. 대상 352건 중 화물 표기 6건은 조달청 화물 별표(`SERVC_QUAL_PRE_20250901_ATTACH_10`·`ATTACH_11`)로 이동했습니다.

---

## 4. 판정 비교

### 4.1 방법

수정 전후에 같은 창의 판정을 떠서 공고 키로 비교했습니다. DB 조회는 `scripts/judge_snapshot_diff.py` 와 `scripts/db_readonly_query.py` 만 사용했습니다.

```sh
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_before.tsv
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/tmp/judge_before.tsv .orca/tmp/judge_after.tsv --expect .orca/tmp/changed.txt
```

`.orca/tmp/changed.txt` 는 `expect551.txt` 와 같은 551건입니다.

### 4.2 결과

| 항목 | 값 |
| --- | ---: |
| before 행 수 | 27,638 |
| after 행 수 | 27,638 |
| 판정 변경 | 551 |
| before 에만 있는 공고 | 0 |
| after 에만 있는 공고 | 0 |
| `--expect` 일치 | 551/551, 종료 코드 0 |

바뀐 551건은 모두 `block_code` 가 비어 있고, 적용 범위는 `PPS_DEFAULT` 입니다. 환경부고시 규칙도 `PPS_DEFAULT` 로 분류되는 규칙 선언(전국 공통)이기 때문입니다.

### 4.3 유형별 바뀐 건수

| 유형 | 건수 | 내용 |
| --- | ---: | --- |
| 조달청 명시 · 같은 세부유형 별표 있음 | 227 | `SERVC_LOCAL_*` -> 조달청 동일 세부유형 |
| 조달청 명시 · 시·도 일반 별표 폴백 | 125 | `SERVC_LOCAL_*_ATTACH_01` 등 일반 별표 -> 조달청 동일 세부유형 |
| 건설폐기물 명시 | 199 | 지역 WASTE·GENERAL 별표 -> `SERVC_QUAL_MOE_CDW_*` |
| 합계 | 551 | |

- 적용 후 조달청 규칙 판본은 `SERVC_QUAL_PRE_20250901_*` 312건, `SERVC_QUAL_POST_20260526_*` 40건, `SERVC_QUAL_MOE_CDW_*` 199건입니다.
- 같은 세부유형·일반 폴백 구분은 입력 판정 덤프의 `rule_id` 와 `src/app/services/evaluation_rules_local.py` 의 규칙 선언 `service_type`, `src/app/services/evaluation_rules.py` 의 조달청 규칙 `service_type` 을 대조해 셌습니다.

### 4.4 대표 공고 5건

| 공고번호 | 수요기관 | 낙찰방법명 | 변경 전 rule_id | 변경 후 rule_id | 유형 |
| --- | --- | --- | --- | --- | --- |
| R25BK01165663 | 서울특별시 용산구 | 보험용역 5억원이상 | SERVC_LOCAL_SEOUL_20240812_ATTACH_01_5 | SERVC_QUAL_PRE_20250901_ATTACH_02 | 같은 세부유형 |
| R25BK01179833 | 전남광주통합특별시교육청 전남광주통합특별시목포교육지원청 | 여객 육상운송용역 5억원미만 | SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4 | SERVC_QUAL_PRE_20250901_ATTACH_03 | 같은 세부유형 |
| R25BK01164662 | 강원특별자치도 화천군 | 여객 육상운송용역 5억원이상 | SERVC_LOCAL_GANGWON_20230611_ATTACH_01 | SERVC_QUAL_PRE_20250901_ATTACH_03 | 일반 별표 폴백 |
| R25BK01173082 | 전남광주통합특별시 고흥군 | 추정가격 5억원 미만 2억원 이상 | SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4 | SERVC_QUAL_MOE_CDW_ATTACH_03 | 건설폐기물 |
| R25BK01209434 | 경기도 오산시 | 추정가격 5억원 미만 2억원 이상 | SERVC_LOCAL_GG_20250808_ATTACH_1_6 | SERVC_QUAL_MOE_CDW_ATTACH_03 | 건설폐기물 + 일반 폴백 |

### 4.5 바뀌지 않은 대상의 사유

#### 4.5.1 expect551.txt

- 바뀌지 않은 공고는 0건입니다. 551건 전부가 조달청 또는 환경부고시 규칙으로 확정됐고, 매칭 결과가 없어 시·도 판정으로 남은 대상은 없습니다.

#### 4.5.2 범위 밖에서 유지한 공고

| 사유 | 건수 | 공고번호 |
| --- | ---: | --- |
| `app_std` 없음 | 3 | R25BK01156702, R25BK01157722, R25BK01160305 |
| 학술연구용역 적격심사 세부기준 명시 | 11 | R25BK01166585, R25BK01167849, R25BK01210104, R26BK01271227, R26BK01355344, R26BK01402983, R26BK01413076, R26BK01458565, R26BK01548986, R26BK01627433, R26BK01716319 |
| 지역 규칙 시행일 불일치로 이미 차단 | 1 | R26BK01375736 |

- `R26BK01375736`(전남광주통합특별시교육청 전남광주통합특별시교육청AI교육원, 2026-03-06, 여객 5억원미만, `app_std` 조달청 일반용역 적격심사 세부기준)은 통합특별시 육상운송 별표 시행일(2026-07-16)보다 공고일이 앞서 종전에 `RULE_REGIME_MISMATCH` 로 차단된 공고입니다. 지역 규칙으로 계산되던 공고가 아니므로 이번 결정의 대상이 아니며, 3.4절 `local_applies` 조건이 종전 차단을 유지합니다.
- 위 15건은 수정 후 판정 덤프에서 before 와 after 가 같습니다.

---

## 5. 시험

### 5.1 신규 시험

`tests/test_stated_std_region_override_20261115.py` 에 DB·Redis 없이 대표 `raw_data` 로 다음을 검사합니다.

| 시험 | 검사 내용 |
| --- | --- |
| `test_stated_pps_uses_pps_same_subtype` | (a) 서울 보험: 시·도 같은 세부유형 별표가 있어도 조달청 명시면 `SERVC_QUAL_PRE_20250901_ATTACH_02` 와 경고 |
| `test_stated_pps_replaces_local_general_fallback` | (b) 경남 보험: 시·도 일반 별표 폴백 공고도 조달청 동일 세부유형과 경고 |
| `test_stated_moe_cdw_uses_environment_rule` | (c) 전남 건설폐기물: `SERVC_QUAL_MOE_CDW_ATTACH_03`, 하한율 86.745, 경고 |
| `test_missing_stated_standard_keeps_local_rule` | (d) 명시 없음: 서울 자체 별표 유지 |
| `test_other_stated_standard_keeps_local_rule` | (d) 학술연구·다른 기준 명시: 서울 자체 별표 유지 |
| `test_stated_pps_without_pps_match_keeps_local_rule` | (e) 조달청 매칭 없음(전남광주 어장정화): 지침 별표 유지 |
| `test_stated_moe_without_moe_match_keeps_local_rule` | (e) 환경부고시 매칭 없음(서울 보험): 시·도 별표 유지 |
| `test_local_regime_mismatch_is_not_overridden` | 시·도 규칙 시행일 불일치 차단 유지 |

### 5.2 기존 시험 4건의 기대 변경

새 결정은 "같은 세부유형 별표가 있어도 공고 명시를 우선"하므로, 시·도 자체 별표 유지를 단언하던 시험 4건의 기대를 조달청 규칙과 `JNGJ_STATED_PPS_WARNING` 으로 바꿨습니다. 코디네이터 승인(2026-11-15)을 받았고, 그 밖의 단언은 바꾸지 않았습니다.

| 파일 · 시험 | 변경 전 기대 | 변경 후 기대 | 이유 |
| --- | --- | --- | --- |
| `tests/test_jngj_pps_stated_20261115.py` · `test_own_annex_type_is_not_intercepted` -> `test_stated_pps_uses_pps_rule_even_with_own_annex_type` | `SERVC_LOCAL_JNGJ_20260716_ATTACH_03`, 경고 없음 | `SERVC_QUAL_POST_20260526_ATTACH_08`, 경고 있음 | 지침 별표 3(폐기물)이 있어도 공고가 조달청 기준을 명시했으므로 조달청 별표 우선 |
| `tests/test_dgcn_pps_stated_20261115.py` · `test_other_region_keeps_own_local_rule` -> `test_other_region_stated_pps_uses_pps_rule` | `SERVC_LOCAL_SEOUL_*`, 경고 없음 | `SERVC_QUAL_PRE_20250901_ATTACH_02`, 경고 있음 | 다른 지역(서울)도 같은 원칙 적용 |
| `tests/test_dgcn_revised_pps_stated_20261115.py` · `test_daegu_revised_own_annex_type_is_not_intercepted` -> `test_daegu_revised_stated_pps_uses_pps_waste_rule` | `SERVC_LOCAL_DAEGU_20260511_ATTACH_04`, 경고 없음 | `SERVC_QUAL_POST_20260526_ATTACH_08`, 경고 있음 | 대구 예규 제238호 폐기물 별표가 있어도 공고 명시 우선 |
| `tests/test_dgcn_revised_pps_stated_20261115.py` · `test_chungnam_revised_own_annex_type_is_not_intercepted` -> `test_chungnam_revised_stated_pps_uses_pps_waste_rule` | `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03`, 경고 없음 | `SERVC_QUAL_POST_20260526_ATTACH_08`, 경고 있음 | 충남 공고 제2026-1235호 폐기물 별표가 있어도 공고 명시 우선 |

- 명시가 없으면 시·도 자체 별표를 유지한다는 확인은 `tests/test_stated_std_region_override_20261115.py::test_missing_stated_standard_keeps_local_rule` 과 세 시험 파일에 추가한 무명시 시험(`test_other_region_without_stated_standard_keeps_local_rule`, `test_daegu_revised_without_stated_standard_keeps_local_rule`, `test_missing_stated_standard_keeps_own_annex_type`)에 남겼습니다.

### 5.3 시험 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_stated_std_region_override_20261115.py -q` | 8 passed |
| `uv run pytest tests/test_jngj_pps_stated_20261115.py tests/test_dgcn_pps_stated_20261115.py tests/test_dgcn_revised_pps_stated_20261115.py tests/test_stated_std_region_override_20261115.py -q` | 45 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 11,023 passed, 41 skipped, 3 deselected, 2 xfailed |

---

## 6. 검증 명령

| 명령 | 결과 |
| --- | --- |
| `uv run python scripts/judge_snapshot_diff.py diff .orca/tmp/judge_before.tsv .orca/tmp/judge_after.tsv --expect .orca/tmp/changed.txt` | 종료 코드 0, `[expect] 일치: 551건` |
| `uv run pytest tests/test_stated_std_region_override_20261115.py -q` | 8 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 11,023 passed, 41 skipped, 3 deselected, 2 xfailed |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 7. 남은 일과 한계

- 이번 판정 비교는 2026-11-15 기준 최근 12개월 `Servc` 공고 27,638건 창입니다. 입력 자료의 551건 목록을 기준으로 했고 더 넓은 창은 다시 뜨지 않았습니다.
- 환경부고시 규칙은 규칙 선언상 전국 공통이라 판정 덤프의 적용 범위가 `PPS_DEFAULT` 로 표시됩니다. 시·도 규칙에서 고시 규칙으로 바뀐 사실은 `rule_id` 로 확인합니다.
- 공고 원문·첨부를 새로 열람하지 않았습니다. 산식 값은 기존 규칙 선언과 선행 분석 문서의 원문 인용만 사용했고, 새 값을 만들지 않았습니다.
- 구현 후 판정에서 `expect551.txt` 밖 변경은 0건입니다. 후속으로 전체 REGION 565건의 명시 기준 분포가 바뀌지 않았는지는 위 덤프 비교가 전부를 포함합니다.
