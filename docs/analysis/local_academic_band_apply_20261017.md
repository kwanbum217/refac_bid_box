# 학술연구용역 띠 표기 공고의 행안부 예규 제2장의2 [별표 4] 적용

> **작성일**: 2026-10-17
> **작업**: Orca Task `task_fb6fd7d1c955` (builder), Run `run_e176c7341827`, Dispatch `ctx_eddbb30babad`
> **정본 사양**: `.orca/capsules/task_local_academic_band_20261017/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/orca-local-academic-band`
> **선행 조사**: `docs/analysis/band_only_basis_20261017.md` (표기별 기준 문서 확인), `docs/analysis/rule_not_found_rest_20261017.md` (차단 갈래)
> **범위**: 낙찰방법명이 `적격심사제-추정가격 1억미만` 또는 `적격심사제-추정가격 2억이상` 띠만 적은 용역 적격심사 공고의 입찰가격 배점(B)·평점계수(k)·기준비율·적격통과점수를 행정안전부 예규 제2장의2 [별표 4] 학술연구용역 평가기준의 해당 열 값으로 확정하고, 그 값으로 계산되게 규칙을 등록합니다. `적격심사제-추정가격 2억미만 1억이상` 은 공고마다 기준 문서가 갈려 범위에서 제외합니다.

---

## 1. 요약과 판정

| 항목 | 값 |
| --- | --- |
| 등록 규칙 | `SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E`, `SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E` (2종) |
| 확정 값 | 1억미만 열 B=65, 2억이상 열 B=30, 두 열 모두 k=2·기준비율 88·적격통과점수 85·낙찰하한율 80.495% |
| 판정 | `candidate` |
| 시·도 규칙 우선 | 시·도 자체 별표가 표기를 세부유형으로 풀어 규칙을 확정한 공고는 그 판정을 그대로 두고, 시·도 규칙이 규칙을 내지 못한 공고에만 등록 규칙을 씁니다(`src/app/services/evaluation_rules.py:resolve_evaluation_rule`). |
| 변경 전 → 후 (최근 12개월, 최신 차수 89건) | 계산 15 → 88, 차단 74 → 1 |

---

## 2. 원문 값 표 (행정안전부 예규 제2장의2 [별표 4] 학술연구용역 평가기준)

문서: 「지방자치단체 입찰시 낙찰자 결정기준」 [시행 2026. 7. 1.] [행정안전부 예규 제373호, 2026. 6. 29. 일부개정]. 출처는 국가법령정보센터(law.go.kr) 행정규칙이며, 내려받은 본문 추출본은 이 워크트리의 `.orca/capsules/task_4bc835ecb826/external/mois/mois373_body.txt` 에 있습니다(커밋하지 않음).

| 추정가격 열 | 입찰가격 배점한도 B | 평점계수 k | 기준비율 | 적격통과점수 T | 낙찰하한율 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 추정가격 2억이상 | 30 | 2 | 88 | 85 | 80.495% |
| 추정가격 2억미만 1억이상 (범위 밖) | 60 | 2 | 88 | 85 | 80.495% |
| 추정가격 1억미만 | 65 | 2 | 88 | 85 | 80.495% |

원문 인용입니다.

- 배점한도([별표 4] 심사분야 2. 입찰가격, 추출본 `:9091-9093`): `○입찰가격 평점산식 참조` 의 배점한도가 열 순서대로 `30` · `60` · `65` 입니다.
- 평점산식([별표 4] 2. 가., 추출본 `:9319-9343`): `평점(점) = 배점한도 - 2×( 88 − 입찰가격/예정가격 × 100 )` 이고, 주에 `※ 입찰가격이 예정가격이하로서 예정가격의 100분의 95.5 이상인 경우 평점은 추정가격 2억 원 이상인 경우 15점, 추정가격 2억 원 미만 1억 원 이상인 경우 45점, 추정가격 1억 원 미만인 경우 50점으로 평가한다.`, `※ ｜｜는 절대값 표시임.`, `다. 최저평점은 2점으로 한다.` 가 있습니다. 배점한도·단서·최저평점이 모두 기준비율 88과 계수 2로 닫힙니다(예: 1억미만 열 65 − 2×|88 − 95.5| = 50점).
- 적격통과점수(제2장의2 제5절 낙찰자 결정 1., 추출본 `:7273`): `계약담당자는 예정가격 이하로서 최저가 입찰자부터 순서대로 심사한 결과 기술용역은 종합평점이 추정가격 10억원 이상인 용역은 92점 … 이상, 추정가격이 10억 원 미만인 용역은 95점 이상인 자, 학술연구용역의 경우 85점 이상인 자를 낙찰자로 결정한다.`
- 낙찰하한율: [별표 4] 는 낙찰하한율을 괄호로 인쇄하지 않습니다. 비가격 배점한도가 `100 − B` 이고 종합평점이 T 이상이어야 하므로 `하한율 = 88 − (100 − T)/k = 88 − (100 − 85)/2 = 80.5` 이며, 저장소 관행 표기(`.995`)로 80.495% 입니다. 선행 조사 4.2절이 인용한 공고문도 1억미만·2억이상 두 표기 모두 `낙찰하한율 80.495%`·`종합평점 85점` 을 적어 이 값과 일치합니다.

### 2.1 판(version)별 값 대조

창 안(2025-10-17 ~ 2026-10-16)에 시행된 판은 제325호(시행 2025-07-01)와 제373호(시행 2026-07-01)입니다.

- 제373호 [별표 4] 원문에서 위 값을 직접 확정했습니다.
- 제325호(시행 2025-07-01)를 인용한 공고문(함안지방공사 `R25BK01167849`)과 그 이전 판 제283호를 인용한 공고문(경상남도 함양군 `R25BK01114109`)이 모두 `낙찰하한율 80.495%`·`종합평점 85점` 을 적습니다(`docs/analysis/band_only_basis_20261017.md` 4.2절 인용). 통과점수가 같고 낙찰하한율 인쇄값도 같아, 두 판의 배점·계수·기준비율도 같다고 보고 한 규칙으로 담았습니다.
- 규칙 시행일은 창 안 공고를 모두 덮는 앞 판 시행일 `2025-07-01` 로 둡니다. 이 날짜 이전 공고는 시행일 대조(`RULE_REGIME_MISMATCH`)로 차단됩니다.

한계: 제325호·제283호 [별표 4] 원문 자체는 이번 작업에서 확보하지 못했습니다(외부 접속 불가). 값 대조는 나라장터 공고 첨부 인용으로만 했습니다.

---

## 3. 등록 규칙

| rule_id | 열 | patterns | B | k | 기준비율 | T | 낙찰하한율 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E` | 추정가격 1억미만 | `추정가격 1억미만`, `추정가격 1억 미만` | 65 | 2 | 0.88 | 85 | 80.495 |
| `SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E` | 추정가격 2억이상 | `추정가격 2억이상`, `추정가격 2억 이상` | 30 | 2 | 0.88 | 85 | 80.495 |

- 두 규칙은 `service_type=ACADEMIC`, `institution_scope=ALL`, `contract_regime=None`, `quant_basis=AGENCY_DOCUMENT_NOT_LOADED` 입니다. 정량 배점표는 이번 범위가 아니므로 종전 LOCAL 규칙과 같이 정량점수 직접 입력을 요구합니다.
- `MOIS_ACADEMIC_BAND_RULES` 로 `LOCAL_RULES` 와 분리해 선언합니다. `LOCAL_RULES` 는 시·도(REGION) 규칙만 담는 계약을 그대로 유지합니다(`tests/test_local_regime_rules.py::test_local_registry_has_regional_rules_only_without_mois_default`).
- 매칭 함수는 `select_mois_academic_band_rule` 이며, `2억미만`·`1억이상` 이 표기에 있으면 `None` 을 돌려 `2억미만 1억이상` 을 배제합니다.

---

## 4. 판정 순서와 회귀 방지

`resolve_evaluation_rule` 의 기존 순서(조달청 별표 매칭 → 기관 규칙 → 시·도 규칙)를 그대로 둔 뒤, **차단으로 끝난 경우에만** 등록 규칙을 적용합니다.

| 단계 | 등록 규칙 적용 여부 |
| --- | --- |
| 조달청 별표가 표기를 매칭 | 적용 안 함 |
| 기관 규칙(INSTITUTION) 확정 | 적용 안 함 |
| 시·도 규칙(REGION) 확정 | 적용 안 함 |
| `RULE_NOT_FOUND`·`LOCAL_RULE_NOT_FOUND`·`LOCAL_SERVICE_TYPE_UNRESOLVED` 로 차단 | 등록 규칙 적용 |
| `RULE_REGIME_MISMATCH` 등 그 밖의 차단 | 적용 안 함 |

- 시·도 규칙으로 계산되던 공고는 규칙이 확정돼 위 첫 세 줄에서 끝나므로 등록 규칙이 끼어들지 않습니다. 그래서 최근 12개월 표기 89건 가운데 경상남도·경기도·대구광역시 규칙으로 풀리던 15건과 대구광역시 시행일 대조 차단 1건의 판정은 바뀌지 않습니다.
- `2억미만 1억이상` 은 patterns 에 없고 배제 표기 검사를 함께 둬, 등록 규칙이 매칭하지 않습니다.
- 세부유형 미확정(`LOCAL_SERVICE_TYPE_UNRESOLVED`)으로 사용자 선택을 안내하던 표기도 등록 규칙으로 자동 확정됩니다. 낙찰방법명이 [별표 4] 의 열 이름을 그대로 옮긴 표기라 시·도 일반 별표의 단순노무·일반 갈림보다 적용 기준이 특정적이기 때문입니다.

---

## 5. 풀리는 건수

조회 조건: 최근 12개월(2025-10-17 ~ 2026-10-16) · 업무구분 `Servc` · `JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm'))` 가 `1억미만` 또는 `2억이상` 을 포함 · 같은 공고번호의 최신 차수만.

| 구분 | 1억미만 | 2억이상 | 합계 |
| --- | ---: | ---: | ---: |
| 모집단(최신 차수) | 47 | 42 | 89 |
| 변경 전 계산 | 10 | 5 | 15 |
| 변경 전 차단 | 37 | 37 | 74 |
| 변경 후 등록 규칙으로 계산 | +36 | +37 | +73 |
| 변경 후 시·도 규칙 계산 유지 | 10 | 5 | 15 |
| 변경 후 차단 유지 | 1 | 0 | 1 |

- 차단 갈래(변경 전): `LOCAL_SERVICE_TYPE_UNRESOLVED` 47, `LOCAL_RULE_NOT_FOUND` 14, `RULE_NOT_FOUND` 12, `RULE_REGIME_MISMATCH` 1. 차단 유지 1건은 대구광역시 중구 공고로, 대구광역시 단순노무 별표가 매칭된 뒤 시행일(2026-05-11) 대조에 걸린 건입니다.
- 측정은 서비스 판정 함수(`classify_contract_regime`·`institution_sido`·`resolve_evaluation_rule_from_raw_data`)를 그대로 돌렸고, DB 조회는 읽기 전용 조회기(`scripts/db_readonly_query.py`)로 받은 결과만 사용했습니다. 측정 스크립트와 원시 조회 결과는 `.cache/local_academic_band/` 아래에만 두고 커밋하지 않습니다.

---

## 6. 기대 실패 (범위 밖 시험)

이 작업에서 고칠 수 없는 범위 밖 시험 하나가 등록 규칙 추가로 기대값이 바뀝니다. 코디네이터가 병합 브랜치에서 고쳐야 합니다.

| 시험 노드 | 원인 |
| --- | --- |
| `tests/test_evaluation_rules_pre.py::TestPreRegimeResolution::test_pre_period_subdivided_band_is_rule_not_found` | `SUBDIVIDED_BAND_METHODS` 에 `1억미만`·`2억이상` 이 들어 있어 등록 규칙 적용 후에도 `RULE_NOT_FOUND`·`rule is None` 을 단정합니다. 이 표기가 이제 등록 규칙으로 풀리는 것이 이 작업의 목적이므로 단정 갱신이 필요합니다. |

그 밖의 전량 시험은 통과해야 합니다. 실패가 나오면 이 원인이 아닙니다.

---

## 7. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_local_academic_band.py tests/test_local_regime_rules.py -q -m 'not data_assets'` | `170 passed` |
| `uv run pytest tests/ -q -m 'not data_assets'` | 아래 8절 |
| `uv run mypy src` | `Success: no issues found in 135 source files` |
| `python3 scripts/validate_agent_rules.py --quiet` | `검증 통과: 21/21 건.` |
| `python3 scripts/validate_doc_links.py --quiet` | 아래 8절 |

---

## 8. 전량 시험 결과와 변경 파일

전량 시험과 문서 링크 검증의 실제 출력은 작업 완료 보고(`.orca/capsules/task_fb6fd7d1c955/worker_done.json`)에 실패 노드 ID와 함께 그대로 적었습니다.

변경 파일은 다음 셋입니다.

| 파일 | 내용 |
| --- | --- |
| `src/app/services/evaluation_rules.py` | `MOIS_ACADEMIC_BAND_RULES`·`select_mois_academic_band_rule`·`MOIS_ACADEMIC_BAND_WARNING` 추가, `resolve_evaluation_rule` 차단 해소 분기 추가 |
| `tests/test_local_academic_band.py` | 원문 값·두 표기 매칭·`2억미만 1억이상` 제외·시·도 규칙 불변 단정 16건 |
| `docs/analysis/local_academic_band_apply_20261017.md` | 이 문서 |

`data/reference/rule_coverage_ledger.yaml` 과 `docs/context/CURRENT_STATE.md` 는 고치지 않았습니다.

---

## 9. 출처

- 국가법령정보센터 행정규칙 「지방자치단체 입찰시 낙찰자 결정기준」 [시행 2026. 7. 1.] [행정안전부 예규 제373호, 2026. 6. 29. 일부개정] 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 4] 학술연구용역 평가기준·제5절 낙찰자 결정
- 나라장터 공고 첨부 인용(제325호·제283호 값 대조): `docs/analysis/band_only_basis_20261017.md` 4.2절 (함안지방공사 `R25BK01167849`, 경상남도 함양군 `R25BK01114109`, 인천교통공사 `R26BK01651767`, 화성도시공사 `R25BK01156702`)
- 표기별 모집단·수요기관: `docs/analysis/band_only_basis_20261017.md` 3.2절
- 차단 갈래: `docs/analysis/rule_not_found_rest_20261017.md` 4·5절
