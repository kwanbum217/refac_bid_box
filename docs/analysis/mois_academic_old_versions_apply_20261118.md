# 행안부 학술 띠 구판 등록 및 GENERAL 폴백 정정

> **작성일**: 2026-11-18
> **작업**: Orca Task `task_4f1b54d9e6e3`
> **근거**: `.orca/mois_academic_band_old_versions_20261118.md`, `docs/analysis/academic_general_table_audit_20261118.md`, `docs/analysis/academic_scope_survey_a_20261118.md`
> **범위**: 예규 제283호 [별표 4] 구판 3종 등록 및 서울·인천·대전 학술 띠 GENERAL 폴백 정정

## 1. 변경 요약

행안부 예규 제283호(시행 2024-07-01, 제325호 시행 전일인 2025-06-30까지)의 학술연구용역 띠 규칙 3종을 별도 `MOIS_ACADEMIC_BAND_RULES_283` 에 등록했습니다. 1억미만·2억미만 1억이상·2억이상 규칙은 각각 배점 65·60·30, 계수 2, 기준비율 0.88, 통과점수 85, 낙찰하한율 80.495%를 사용합니다.

`select_mois_academic_band_rule` 은 공고일에 맞춰 제283호와 2025-07-01 이후 판본을 선택합니다. 2024-07-01 전 공고는 제283호로 소급 적용하지 않습니다. 2억미만 1억이상 규칙은 현재 판의 첨부 전용 상수를 유지하고, 학술 조달분류가 확인된 띠 경로에서만 판본별 규칙을 선택합니다.

일반용역 정의에서 학술용역을 제외하고 GENERAL 별표로 계산되던 서울(11)·인천(28)·대전(30)의 학술 조달분류 띠 공고는 시·도 GENERAL 후보로 폴백하기 전에 `LOCAL_RULE_NOT_FOUND` 로 넘겨 행안부 학술 띠 규칙을 적용합니다. 범위는 감사로 확인한 세 지역과 해당 띠·학술 조달분류·`PROCUREMENT_CLASS` 근거로 제한했습니다. 기존 대구 코드 `LOCAL_ACADEMIC_SCOPE_EXCLUDED_SIDO_CODES={"27"}` 는 그대로입니다.

## 2. 경계 및 회귀 시험

- 제283호 적용 시작일은 2024-07-01이며 2024-06-30 공고는 계속 차단됩니다.
- 2025-07-01 공고부터는 현행 세 규칙을 선택합니다.
- 국가계약, 학술 이외 조달분류, 직접 지정한 `local_service_type` 은 기존 분기를 유지합니다.
- 학술 GENERAL 폴백 차단 코드는 원문에서 학술 제외가 확인되고 실제 GENERAL 오계산이 발생한 서울·인천·대전만 포함합니다.
- 학술 띠가 아니거나 지역 ACADEMIC 규칙이 존재하는 경우에는 새 차단 조건을 적용하지 않습니다.

기존 시험의 기대값은 코디네이터 승인에 따라 아래 다섯 항목만 새 동작에 맞게 갱신했습니다.

| 시험 파일 | 갱신한 시험 |
| --- | --- |
| `tests/test_academic_band_local_nf_20261118.py` | `test_283_effective_date_resolves_previous_local_rule_not_found` (세 지역 매개변수 사례) |
| `tests/test_daegu_academic_scope_20261118.py` | `test_daegu_academic_283_rule_resolves_before_20250701` |
| `tests/test_unblock_rules_13_20261115.py` | `test_daejeon_academic_band_uses_mois_academic_rule` |

## 3. 판정 스냅숏 비교

기준 스냅숏은 `.orca/judge_main_ee0a8536.tsv` 입니다. 출력 스냅숏은 임시 경로 `/tmp/mois-academic-apply.q3WMt0/final-after.tsv` 에 두었으며 저장소에 추가하지 않았습니다.

```sh
uv run python scripts/judge_snapshot_diff.py dump --months 24 --as-of 2026-11-18 --output /tmp/mois-academic-apply.q3WMt0/final-after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/judge_main_ee0a8536.tsv /tmp/mois-academic-apply.q3WMt0/final-after.tsv
```

덤프는 기준일 2026-11-18, 최근 24개월, `Servc` 51,398건입니다. `content_changed=53`, `only_before=0`, `only_after=0` 이었습니다. 제283호 규칙별 변경은 1억미만 21건, 2억미만 1억이상 19건, 2억이상 12건으로 총 52건이며, 2025-07-01 현행 2억미만 1억이상 규칙 변경은 1건입니다.

감사 오계산 5건은 모두 의도한 행안부 학술 띠 규칙으로 바뀌었습니다: `R25BK00633539`, `R25BK00825399`, `R25BK00880281`, `R25BK00934697`, `R26BK01402983`. 이 중 제283호가 4건, 현행판이 1건입니다. 나머지 48건은 제283호 시행 구간에 있던 행안부 학술 띠 공고의 판정 차단 해소입니다. diff의 53건 전부가 이 두 대상 묶음에 속하며 예상 밖 변경은 0건입니다.

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/test_mois_academic_old_versions_20261118.py tests/test_mois_academic_band_1e2e.py tests/test_evaluation_rules_split_invariance.py tests/test_academic_band_local_nf_20261118.py tests/test_daegu_academic_scope_20261118.py tests/test_unblock_rules_13_20261115.py tests/test_band_regime_first_priority.py tests/test_band_regime_resolve.py` | 96 passed |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/` | 11,277 passed, 36 skipped, 35 deselected, 2 xfailed |
| `uv run mypy src` | 152 source files, 성공 |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
