# 규칙 커버리지 원장 (rule_coverage_ledger)

> **updated_at**: 2026-11-07
> **generator**: `scripts/report_rule_coverage.py`
> **output**: `data/reference/rule_coverage_ledger.yaml`
> **schema**: `RULE_COVERAGE_LEDGER_V1`
> 최근 N개월 공고에 실제 판정 함수를 돌린 결과를 수요기관별로 접은 원장입니다. 값의 판정 근거는 생성기 코드와 이 문서이며, YAML 은 재생성되는 산출물입니다.

---

## 1. 생성과 확인

```sh
uv run python scripts/report_rule_coverage.py
uv run python scripts/report_rule_coverage.py --months 12 --category Servc
uv run python scripts/report_rule_coverage.py --check
```

`--check` 는 파일을 쓰지 않고 기존 원장과 다시 계산한 원장의 구조·값 차이만 출력합니다.
`generated_at`, 조회 창, 사람이 채우는 `investigation` 은 차이에서 제외합니다.

## 2. 파일 구조

| 키 | 내용 |
| --- | --- |
| `schema`, `generated_at`, `generated_by`, `filter` | 원장 식별자, 생성 시점, 조회 조건 |
| `totals` | 집계 대상 공고 수, 취소공고 제외 수, 기관 수, `applied_scope` 비중, `blocked_breakdown` |
| `tail` | `min_announcements` 미만이라 개별 항목을 만들지 않은 기관 합계 |
| `regions` | 지역 규칙 적용 합계 |
| `institutions` | 기준 공고 수를 넘긴 기관별 규칙·차단·명세 상태 |

`applied_scope` 는 `INSTITUTION`, `REGION`, `PPS_DEFAULT`, `BLOCKED`, `ERROR` 다섯 축이며
기관 항목의 `scope_counts` 도 같은 축을 씁니다. 기존 필드의 이름과 값 의미는 바꾸지 않습니다.

## 3. 취소공고 제외

같은 공고번호·업무구분의 **최신 차수** `raw_data.ntceKindNm` 이 `취소공고` 면 그 공고번호를
집계에서 뺍니다. 판별 필드는 `bid_announcements.raw_data` 최상위의 `ntceKindNm` 하나이며,
`등록공고`·`재공고`·`변경공고` 는 취소가 아니므로 최신 차수를 그대로 집계합니다. 이전 차수만
취소공고이고 최신 차수가 정상 공고면 최신 차수를 집계합니다.

뺀 건수는 `totals.excluded_cancelled` 에 남깁니다. `totals.announcements` 는 제외 후 집계
대상 수이므로, 합계가 줄어든 이유는 이 필드로 확인합니다. 제외한 공고는
`applied_scope`·`blocked_breakdown`·기관 항목 어디에도 세지 않습니다.

근거는 `docs/analysis/ledger_cancel_notice_impact_20261107.md` 1절·2절입니다.

### 3.1 재생성 회귀 값

2026-11-07 창(2025-11-07 ~ 2026-11-07, 업무구분 `Servc`, 낙찰방법 `낙030001`,
`min_announcements` 5)에서 메모리로 재생성한 값입니다. 파일 쓰기 없이 `collect_records` 와
`build_ledger` 를 직접 호출했습니다.

| 항목 | 값 |
| --- | ---: |
| `totals.announcements` | 27,723 |
| `totals.excluded_cancelled` | 3,602 |
| `totals.institutions` | 3,364 |
| `applied_scope.INSTITUTION` | 94 (0.003391) |
| `applied_scope.REGION` | 1,599 (0.057678) |
| `applied_scope.PPS_DEFAULT` | 17,345 (0.625654) |
| `applied_scope.BLOCKED` | 8,685 (0.313278) |
| `applied_scope.ERROR` | 0 |
| `blocked_breakdown.manual_input` | 8,511 |
| `blocked_breakdown.not_computable` | 174 |

취소 제외 전 31,325건 대비 -3,602건(-11.50%)입니다. 차단 코드별 값은
`MANUAL_EVALUATION` 8,429, `NON_PRED_PRICE` 169, `LOCAL_RULE_NOT_FOUND` 78,
`LOCAL_SERVICE_TYPE_UNRESOLVED` 4, `RULE_NOT_FOUND` 3, `RULE_REGIME_MISMATCH` 2 입니다.

## 4. 차단 분리 집계 (`blocked_breakdown`)

`BLOCKED` 는 사용자 입력이 있어야 계산되는 차단과, 사용자 입력과 무관하게 자동 계산이
불가능한 차단으로 나눠 셉니다. 분리 값은 `totals.blocked_breakdown` 과 기관 항목의
`blocked_breakdown` 에 같은 모양으로 들어갑니다.

```yaml
blocked_breakdown:
  manual_input:
    announcements: 0
    codes: {}
  not_computable:
    announcements: 0
    codes: {}
```

| 갈래 | 의미 | 해당 코드 |
| --- | --- | --- |
| `manual_input` | 사용자가 값을 넣으면 판정이 계산되는 차단 | `MANUAL_EVALUATION`, `LOCAL_RULE_NOT_FOUND`, `LOCAL_SERVICE_TYPE_UNRESOLVED` |
| `not_computable` | 사용자 입력으로 풀리지 않는 차단 | `NON_PRED_PRICE`, `RULE_NOT_FOUND`, `RULE_REGIME_MISMATCH` 등 나머지 전체 |

사용자 입력 경로 코드 집합은 `src/app/api/v1/evaluations.py` 의 사용자 입력 처리
(약 1862행·1892행)를 근거로 생성기의 `MANUAL_INPUT_BLOCK_CODES` 상수에 둡니다.
집합에 없는 코드는 모두 `not_computable` 로 셉니다.

### 집계 규칙

- `announcements` 는 그 갈래에 속한 차단 공고 수이고 `codes` 는 차단 코드별 건수입니다.
- `ERROR` 축(판정 중 예외)은 차단이 아니므로 `blocked_breakdown` 에 넣지 않습니다.
- `block_reason_code` 가 비어 있는 차단은 기존 `block_codes` 와 같은 기준으로 제외합니다.
- `totals.blocked_breakdown` 은 `tail` 기관의 차단까지 포함하므로 `totals.applied_scope.BLOCKED` 와 비교해야 합니다.
- 기관 항목의 `blocked_breakdown` 은 그 기관 행의 차단만 세므로 `scope_counts.BLOCKED` 와 비교해야 합니다.

## 5. 변경 이력

| 날짜 | 변경 | 이유 |
| --- | --- | --- |
| 2026-11-07 | 최신 차수가 취소공고인 공고번호를 집계에서 제외하고 `totals.excluded_cancelled` 를 추가 | 취소된 사업의 판정까지 모집단에 들어가 적용 범위 비율을 낮추던 문제를 없앰 |

### 5.1 시험 단언 변경

| 시험 | 고친 단언 | 이유 |
| --- | --- | --- |
| `tests/test_rule_coverage_ledger.py::test_check_does_not_write` | `collect_records` monkeypatch 대역이 `[]` 대신 `ledger_script.CollectedRecords()` 를 돌려줌 | `collect_records` 반환형이 레코드 목록에서 `CollectedRecords`(레코드 목록 + 취소공고 제외 수)로 바뀜 |
| `tests/test_report_rule_coverage_cancel.py` | 신규 시험 (a) 최신 차수 취소공고 제외, (b) 이전 차수만 취소공고면 최신 차수 집계, (c) `totals.excluded_cancelled` 기록 | 취소 제외 규칙 자체를 고정하던 시험이 없었음 |

`tests/test_rule_coverage_ledger.py` 의 커밋된 원장 정합 시험과
`tests/test_report_rule_coverage_split.py` 의 차단 분리 시험은 단언을 바꾸지 않았습니다.
두 시험은 `31,325` 같은 절대값을 고정하지 않고 합계 자기 일관성과 갈래 분류만 봅니다.
