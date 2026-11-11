# 규칙 커버리지 원장 (rule_coverage_ledger)

> **updated_at**: 2026-11-11
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

### 3.1 재생성 기준값

2026-11-11 재생성(창 2025-11-11 ~ 2026-11-11, 업무구분 `Servc`, 낙찰방법 `낙030001`,
`min_announcements` 5) 값입니다. `uv run python scripts/report_rule_coverage.py` 로
`data/reference/rule_coverage_ledger.yaml` 을 다시 쓴 뒤 같은 조건의 `--check` 가
차이 0건임을 확인했습니다.

| 항목 | 값 |
| --- | ---: |
| `totals.announcements` | 27,791 |
| `totals.excluded_cancelled` | 3,603 |
| `totals.institutions` | 3,357 |
| `applied_scope.INSTITUTION` | 130 (0.004678) |
| `applied_scope.REGION` | 561 (0.020186) |
| `applied_scope.PPS_DEFAULT` | 18,376 (0.661221) |
| `applied_scope.BLOCKED` | 8,724 (0.313915) |
| `applied_scope.ERROR` | 0 |
| `blocked_breakdown.manual_input` | 8,552 |
| `blocked_breakdown.not_computable` | 172 |

취소 제외 전 31,394건 대비 -3,603건(-11.48%)입니다. 차단 코드별 값은
`MANUAL_EVALUATION` 8,466, `NON_PRED_PRICE` 166, `LOCAL_RULE_NOT_FOUND` 79,
`LOCAL_SERVICE_TYPE_UNRESOLVED` 7, `RULE_NOT_FOUND` 5, `RULE_REGIME_MISMATCH` 1 입니다.

### 3.2 2026-11-07 원장과의 비교

2026-11-07 원장(창 2025-11-07 ~ 2026-11-07)과 이번 재생성 값을 비교한 결과입니다.

| 항목 | 2026-11-07 | 2026-11-11 | 변화 |
| --- | ---: | ---: | ---: |
| `totals.announcements` | 27,723 | 27,791 | +68 |
| `totals.excluded_cancelled` | 3,602 | 3,603 | +1 |
| `totals.institutions` | 3,368 | 3,357 | -11 |
| `applied_scope.INSTITUTION` | 130 (0.004689) | 130 (0.004678) | 0 |
| `applied_scope.REGION` | 558 (0.020128) | 561 (0.020186) | +3 |
| `applied_scope.PPS_DEFAULT` | 18,347 (0.661797) | 18,376 (0.661221) | +29 |
| `applied_scope.BLOCKED` | 8,688 (0.313386) | 8,724 (0.313915) | +36 |
| `applied_scope.ERROR` | 0 | 0 | 0 |
| `blocked_breakdown.manual_input` | 8,513 | 8,552 | +39 |
| `blocked_breakdown.not_computable` | 175 | 172 | -3 |

기관 단위 변화는 목록 인덱스가 아니라 `dminstt_cd` 집합 차로 셉니다. 개별 항목이 있는
기관(공고 5건 이상)은 1,008곳에서 1,010곳으로 늘었고, 집합 차는 추가 11곳·삭제 9곳입니다.
`tail.institutions` 는 2,360곳에서 2,347곳으로 줄었습니다. 표본 10곳은 다음과 같습니다.

| 구분 | `dminstt_cd` | 기관명 | 공고 수 |
| --- | --- | --- | ---: |
| 추가 | `1400000` | 산림청 | 5 |
| 추가 | `1543087` | 농림축산식품부 농림축산검역본부 인천공항지역본부 | 5 |
| 추가 | `5670074` | 경상남도 창원시 상수도사업소 | 7 |
| 추가 | `5670123` | 경상남도 창원시 의창구 | 6 |
| 추가 | `5670788` | 창원시 문화시설사업소 | 8 |
| 삭제 | `1336429` | 경찰청 충청남도경찰청 | 5 |
| 삭제 | `4960000` | 전라남도 함평군 | 6 |
| 삭제 | `B552551` | 정보통신산업진흥원 | 5 |
| 삭제 | `D150185` | 한국농어촌공사 강원지역본부 강릉지사 | 5 |
| 삭제 | `Z006982` | 재단법인 대전테크노파크 | 6 |

산림청(`1400000`)은 이번 창에서 공고 5건이 되어 개별 항목에 새로 들어왔습니다. 이 행의
`investigation` 은 `data/reference/institution_rules_candidates_b_20261014.yaml` 의 산림청
기록(recommendation `add_to_registry`, status `confirmed`, 기준 문서·note)을 2026-10-14
조사 결과로 그대로 옮겨 채웠습니다. 생성기는 기존 원장의 `investigation` 만 보존하므로,
새로 목록에 들어온 행은 이렇게 한 번 채워 두면 다음 재생성부터 유지됩니다.

차이는 창 이동과 새 수집분이 섞여 있습니다. 창이 2025-11-07 에서 2025-11-11 로 4일
움직였고 그 사이 수집분이 들어와, 같은 기관이라도 경계에서 공고가 빠지면 공고 수가
5건 아래로 내려가 개별 항목에서 빠지고 `tail` 로 이동할 수 있습니다. 이번 회차에는
규칙 레지스트리나 판정 코드를 바꾸지 않았으므로 `applied_scope` 구성비 변화는 위 두
요인으로 설명합니다.

이전 3.1절은 파일이 아니라 메모리 재생성 값(기관 3,364, `INSTITUTION` 94, `REGION` 1,599,
`PPS_DEFAULT` 17,345)을 적어 커밋된 원장(3,368, 130, 558, 18,347)과 달랐습니다. 이번
절부터는 원장 파일에 실제로 기록된 값을 기준으로 삼습니다.

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
