# PPS '2억미만 1억이상' 띠 구제 분기 회귀

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_3c0c9840ef73` (builder), Run `run_8734173629f4`
> **정본 사양**: `.orca/capsules/task_3c0c9840ef73/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/pps-rescue`
> **판정**: candidate

---

## 1. 요약

조달청 일반용역 적격심사 세부기준 원문에 없는 `추정가격 2억미만 1억이상` 띠를, 첨부 판별이 `PPS` 로 확정하고 첨부가 [별표 1] 학술연구용역을 지목한 공고에 한해 공고일 판본의 조달청 학술연구용역 고시금액 미만 규칙으로 계산하는 구제 분기를 추가했습니다. 최근 12개월 Servc 31,348건을 수정 전후로 같은 프로세스에서 판정해 비교한 결과, 판정이 바뀐 공고는 문서 3절의 대상 3건뿐입니다. 새 규칙 값은 만들지 않았고 기존 `EvaluationRule` 객체를 그대로 골라 씁니다.

### 1.1 변경 전후 집계

| 항목 | 변경 전 | 변경 후 | 차이 |
| --- | ---: | ---: | ---: |
| 판정 공고 수 | 31,348 | 31,348 | 0 |
| 차단 합계 | 9,747 | 9,744 | -3 |
| `RULE_NOT_FOUND` | 9 | 6 | -3 |
| `LOCAL_RULE_NOT_FOUND` | 91 | 91 | 0 |
| `LOCAL_SERVICE_TYPE_UNRESOLVED` | 9 | 9 | 0 |
| `RULE_REGIME_MISMATCH` | 3 | 3 | 0 |
| `MANUAL_EVALUATION` | 9,424 | 9,424 | 0 |
| `NON_PRED_PRICE` | 211 | 211 | 0 |

---

## 2. 변경 요지

| 파일 | 내용 |
| --- | --- |
| `src/app/services/evaluation_rules.py` | `attachment_regime == "PPS"`, 낙찰방법명의 `2억미만`·`1억이상` 표기, `RULE_NOT_FOUND` 차단, 학술연구 별표 신호를 모두 만족할 때만 `attachment_band` 구제를 적용합니다. 규칙은 `_rules_for_announcement_date` 가 고른 공고일 판본에서 `service_type="ACADEMIC"`·`고시금액 미만` 규칙을 재사용합니다. |
| `tests/test_pps_band_rescue.py` | 대상 3건의 공고일 판본, 학술연구 신호 5종, 별표 미확인·비PPS·띠 없음·다른 차단 코드 가드, MOIS_ACADEMIC 우선 유지, 공고 하한율 우선을 검증합니다. |

학술연구 별표 신호는 `matched_rules` 의 `R7`, `evidence` 의 학술연구 표기, 공고의 `sucsfbidMthdAppStd`, `bidNtceNm` 순으로 확인합니다. 대상 3건은 모두 `sucsfbidMthdAppStd` 가 `학술연구용역 적격심사 세부기준` 이고 판별 근거에도 `R6,R7` 이 있습니다.

---

## 3. 판정이 바뀐 공고

| 공고번호(차수) | 수요기관 | 공고일 | 추정가격(원) | 변경 전 | 변경 후 규칙 | B·k·T | 적용 하한율 |
| --- | --- | --- | ---: | --- | --- | --- | ---: |
| R25BK01248793(000) | 양평군 신활력 추진단 | 2025-12-24 | 154,545,455 | `RULE_NOT_FOUND` | `SERVC_QUAL_PRE_20250901_ATTACH_06` | 70·4·85 | 88 (공고값) |
| R25BK01255918(000) | 강원특별자치도영월의료원 | 2025-12-31 | 113,103,994 | `RULE_NOT_FOUND` | `SERVC_QUAL_PRE_20250901_ATTACH_06` | 70·4·85 | 80.495 (공고값) |
| R26BK01270299(000) | 부산광역시교육청 | 2026-01-15 | 109,272,727 | `RULE_NOT_FOUND` | `SERVC_QUAL_PRE_20250901_ATTACH_06` | 70·4·85 | 84.245 (공고값) |

세 건 모두 `scope_stage` 가 `ALL` 로 바뀌었고 하한율 출처는 `ANNOUNCEMENT` 입니다. R25BK01255918 의 공고 인쇄값 80.495% 는 원문 고시금액 미만 산식값 84.245% 와 다르지만, 사용자 결정대로 공고값 우선을 유지했습니다.

---

## 4. 목록 밖 변화

목록 밖에서 판정이 바뀐 공고는 0건입니다. 수정 후 남은 `RULE_NOT_FOUND` 6건은 모두 첨부 판별이 `PPS` 가 아닙니다.

| 공고번호(차수) | 첨부 판별 | 비고 |
| --- | --- | --- |
| R25BK01139979(001) | `MOIS_OTHER` | 구제 대상 아님 |
| R25BK01197545(001) | `NO_ATTACH` | 구제 대상 아님 |
| R26BK01310604(001) | `NO_ATTACH` | 구제 대상 아님 |
| R26BK01345718(001) | `NO_ATTACH` | 구제 대상 아님 |
| R26BK01560778(000) | `MOIS_OTHER` | 구제 대상 아님 |
| R26BK01577453(000) | `MOIS_OTHER` | 구제 대상 아님 |

---

## 5. 재현 방법

`scripts/report_rule_coverage.py` 의 `collect_records(months=12, category="Servc", method_code="낙030001")` 를 메모리에서 실행하고, `_to_record` 를 감싸 공고번호·차수를 붙여 공고별 `block_reason_code`·`rule_id`·`effective_lwlt_rate`·`rate_source`·`scope_stage` 를 비교했습니다. DB 는 읽기 전용 세션(`SET SESSION TRANSACTION READ ONLY`)만 사용했고 원장 파일과 `docs/context/` 는 커밋하지 않습니다.

---

## 6. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_pps_band_rescue.py tests/test_band_regime_first_priority.py tests/test_band_regime_resolve.py -q` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'evaluation_rules or regime'` | 758 passed |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 7. 참고

- [pps_band_1e2e_check_20261106.md](pps_band_1e2e_check_20261106.md): 대상 3건과 조달청 원문 띠 부재 근거
- [local_academic_band_apply_20261017.md](local_academic_band_apply_20261017.md): 행안부 학술연구 띠 규칙의 등록 경위와 배제 이유
