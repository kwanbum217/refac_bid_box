# 띠 표기 학술연구 공고의 LOCAL_RULE_NOT_FOUND 구제 정합화 (2026-11-18)

> **작성일**: 2026-11-18 | **작업**: Orca Task `task_f34e42a39035` (builder, Run `run_b68a3b16b660`)
> **정본 사양**: `.orca/capsules/task_academic_band_local_nf_20261118/capsule.yaml`
> **작업 브랜치**: `kwanbum217/orca-band-lnf` | **기준 스냅숏**: `.orca/judge_main_83d0aeed.tsv` (51,387행)
> **DB 조회**: `uv run python scripts/db_readonly_query.py` 읽기 전용 질의만 사용했습니다.

---

## 1. 변경 요약

`src/app/services/evaluation_rules.py:4745-4774` 의 D25 구제 분기 한 곳만 고쳤습니다.

| 위치 | 변경 전 | 변경 후 |
| --- | --- | --- |
| `:4761-4769` | 띠 표기(`_is_band_only_method`)일 때 `block_reason_code == RULE_NOT_FOUND` 인 경우에만 `select_mois_academic_band_rule` 호출 | `LOCAL_RULE_NOT_FOUND` 도 같은 구제 대상에 포함. 단 이 코드는 시·도 별표 자체가 없으므로 행안부 띠 규칙이 공고일을 덮을 때만 적용 |

- 비대칭의 원인은 시·도 선택 실패가 두 갈래로 내려오기 때문입니다. 전남처럼 `_is_jeonnam_pps_fallback_announcement` 분기가 먼저 잡으면 결과가 `RULE_NOT_FOUND` 로 남아 D25 가 실행되지만, 충남·통합특별시·세종처럼 `else` 로 떨어지면 `LOCAL_RULE_NOT_FOUND` 가 붙어 D25 를 건너뛰었습니다.
- `select_mois_academic_band_rule` 의 D25 조건(띠 표기는 조달분류가 학술연구 계열일 때만)과 최종 시행일 대조는 그대로 두었습니다. 새 rule id·규칙 값은 만들지 않았습니다.
- `LOCAL_RULE_NOT_FOUND` 에는 `_rule_applies_to_announcement` 로 공고일이 2025-07-01 이후일 때만 적용합니다. 이 가드가 없으면 2025-07-01 이전 13건이 `LOCAL_RULE_NOT_FOUND` 에서 `RULE_REGIME_MISMATCH` 로 바뀌어 경계(묶음 16)를 위반합니다.
- 주석의 '세부유형 선택 대기(LOCAL_*)는 건드리지 않는다' 문구는 그대로 유효하며, 단순노무 단독 차단이 사용자 선택 대기라 대상이 아님을 함께 적었습니다.

---

## 2. 경계

| 경계 | 시험 | 결과 |
| --- | --- | --- |
| 국가계약 | `test_national_regime_is_not_rescued` | 행안부 띠 미적용, 차단 유지 |
| 대구 단순노무 단독 차단 | `test_daegu_simple_labor_only_block_is_unchanged` | `LOCAL_SERVICE_TYPE_UNRESOLVED` + `LOCAL_SIMPLE_LABOR_ONLY_REASON` 유지 |
| 세부유형 미확정(충북 일반 띠) | `test_local_service_type_unresolved_is_unchanged` | `LOCAL_SERVICE_TYPE_UNRESOLVED` 유지 |
| 학술이 아닌 띠 표기 | `test_non_academic_band_keeps_previous_block` | 충남·교육서비스 모두 `LOCAL_RULE_NOT_FOUND` 유지 |
| 전남 일반 띠 D24 | `test_jeonnam_general_band_path_is_unchanged` | 학술 띠 미적용, 종전 차단 유지 |
| 2025-07-01 이전 공고 | `test_before_mois_effective_date_keeps_local_rule_not_found` | 13건 `LOCAL_RULE_NOT_FOUND` 유지(시행일 가드) |
| 시·도 자체 별표 | `test_region_rule_is_not_overridden_by_mois_band` | 경기·경북·경남 규칙 그대로 |
| 띠가 아닌 표기 | `test_non_band_method_is_unchanged` | 1억미만 열 그대로 |

---

## 3. 판정 비교 (main 스냅숏 대비)

```sh
uv run python scripts/judge_snapshot_diff.py dump --months 24 --as-of 2026-11-18 --output <임시>/after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/judge_main_83d0aeed.tsv <임시>/after.tsv --expect <임시>/expect.txt
```

- before 51,387행, after 51,398행. 바뀐 공고 19건 = 판정 변경 8건 + after 만 11건.
- after 만 11건은 `R26BK01839586` 등 2026-11-18 신규 수집분이라 무시했습니다(캡슐 지시).
- 판정 변경 8건은 예상 목록(띠 표기 + 학술 조달분류 + `LOCAL_RULE_NOT_FOUND` + 공고일 2025-07-01 이후)과 **정확히 일치**했고, 예상 밖 `content_changed` 는 0건입니다.

| 공고번호 | 차수 | scope | rule_id | block_code |
| --- | --- | --- | --- | --- |
| R25BK00936613 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK00936619 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01004727 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01052873 | 001 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01052900 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01111217 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01115825 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |
| R25BK01130396 | 000 | BLOCKED → PPS_DEFAULT | - → `SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E` | `LOCAL_RULE_NOT_FOUND` → - |

---

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/test_academic_band_local_nf_20261118.py` | 21 passed |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/` | 11,264 passed, 36 skipped, 2 xfailed |
| `uv run mypy src` | Success (152 files) |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 5. 남은 것

- 2025-07-01 이전 13건(충남 8, 통합특별시 3, 세종 2)은 행안부 띠 구판본이 등록되지 않아 종전 `LOCAL_RULE_NOT_FOUND` 를 유지합니다(묶음 16). 원문 확보가 필요합니다.
- `R25BK00952544`·`R25BK01016608`·`R25BK01016737`(충남, 조달분류 교육서비스)은 학술연구 계열이 아니라 대상이 아니며 차단이 유지됩니다.
