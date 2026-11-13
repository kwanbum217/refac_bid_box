# 낙찰하한율 불일치 진단 지표 정의서

> **작성일**: 2026-11-07
> **재생성**: 2026-11-11 (창 2025-11-11 ~ 2026-11-11)
> **상태**: 확정 (Active)
> **결정**: D11 (A) 규칙 ID·판본별 불일치율 정기 집계, D30 (C) 불일치를 진단 지표로만 집계
> **대상 파일**:
> - [scripts/report_lwlt_mismatch.py](../../scripts/report_lwlt_mismatch.py)
> - [data/reference/lwlt_mismatch_metrics.yaml](../../data/reference/lwlt_mismatch_metrics.yaml)
> - [tests/test_report_lwlt_mismatch.py](../../tests/test_report_lwlt_mismatch.py)

---

## 1. 개요

본 문서는 공고의 낙찰하한율(`sucsfbidLwltRate`)과 서비스가 고른 적격심사 규칙의 하한율이
어긋나는 비율을 규칙 ID·판본(시행일)별로 집계하는 진단 지표의 정의를 고정합니다.

- 진단 전용입니다. 평가·추천 계산 경로([src/app/services/](../../src/app/services/))와
  워커 크론([src/tasks/](../../src/tasks/))을 고치지 않습니다. 지표를 만드는 스크립트가
  판정 함수를 호출하기만 하며, 계산 결과는 지표 생성 전후로 같습니다.
- 현행 코드는 공고 하한율이 있으면 규칙값보다 우선합니다
  ([src/app/services/evaluation_rules.py:3698](../../src/app/services/evaluation_rules.py)).
  따라서 여기의 불일치는 점수 계산 오류가 아니라 **규칙 선택, 규칙 기본값, 폴백 경로,
  경고 문구의 정합성**을 드러내는 값입니다. 공고 하한율이 결측이면 그때 규칙값이 실제
  계산에 쓰이므로, 이 지표는 결측 발생 시의 위험을 미리 보는 용도이기도 합니다.
- 모집단과 최신 차수 정의는 규칙 커버리지 원장
  ([scripts/report_rule_coverage.py](../../scripts/report_rule_coverage.py) →
  [data/reference/rule_coverage_ledger.yaml](../../data/reference/rule_coverage_ledger.yaml))과
  같습니다. 조회 SQL, 기관 기준정보 로더, 판정 함수, `(bid_ntce_no, category)` 별 최신
  `bid_ntce_ord` 선정을 그대로 재사용합니다.

---

## 2. 지표 정의

### 2.1 모집단

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 업무구분 | `Servc` | `--category` 로 변경 가능 |
| 기간 | 실행일 기준 최근 12개월 | `--months` 로 변경 가능. 창은 시작일 이상, 종료일 다음 날 미만 |
| 대표 공고 | `(bid_ntce_no, category)` 별 최신 `bid_ntce_ord` | `report_rule_coverage.collect_records` 와 같음 |
| 낙찰방법 필터 | 없음(`--method-code ""`) | 감사 문서 부록 B.2 와 같음. 코드를 주면 그 코드만 남김 |
| 규칙 적용 | 차단·판정 오류·규칙 없음 제외 | `RuleResolutionResult.is_blocked=False` 이고 `rule` 이 있는 건 |

### 2.2 공고값과 규칙값

| 값 | 정의 |
| --- | --- |
| 공고값 | `raw_data.sucsfbidLwltRate` 를 `Decimal` 로 읽은 값 |
| 규칙값 | 규칙에 인쇄된 구간 하한율이 있으면 추정가격(`presmpt_prce`)으로 고른 구간값, 없으면 규칙 대표값(`EvaluationRule.lwlt_rate`) |

규칙값 선택은 감사 문서 부록 A 의 `_rule_rates` 와 같습니다. 추정가격을 몰라 구간을
고르지 못하면 규칙 대표값으로 대체합니다.

### 2.3 비교 규칙

공고값과 규칙값을 각각 소수 3자리로 맞춘 뒤 뺍니다.

```text
diff = round3(공고값) - round3(규칙값)
```

- `diff == 0` 이면 일치, 그 밖이면 불일치입니다.
- 공고값이 없거나 0 이하이면 비교하지 않습니다.
- 규칙값이 없으면 비교하지 않습니다(기술용역·하한율 미인쇄 기관 규칙 등).

이 비교 방식은 감사 문서
[docs/analysis/lwlt_notice_vs_rule_audit_20261106.md](../analysis/lwlt_notice_vs_rule_audit_20261106.md)
부록 A 와 같습니다.

### 2.4 집계 항목

| 항목 | 의미 |
| --- | --- |
| `rule_applied` | 규칙이 적용된 공고 수 |
| `compared` | 공고값과 규칙값을 모두 알 수 있어 비교한 공고 수 |
| `match` | 비교한 공고 중 소수 3자리까지 일치한 수 |
| `mismatch` | 비교한 공고 중 일치하지 않은 수 |
| `mismatch_ratio` | `mismatch / compared`. 비교 가능이 0 이면 `0.0` |

불일치율의 분모는 `rule_applied` 가 아니라 `compared` 입니다. 규칙값이 없는 건을 분모에
넣으면 규칙 값의 정합성이 아니라 규칙의 하한율 인쇄 여부가 비율을 흔듭니다.

---

## 3. 출력 구조

[data/reference/lwlt_mismatch_metrics.yaml](../../data/reference/lwlt_mismatch_metrics.yaml)
한 파일에 다음 구조로 남깁니다.

```yaml
schema: LWLT_MISMATCH_METRICS_V1
generated_at: "2026-11-11"
generated_by: scripts/report_lwlt_mismatch.py
window:
  from: "2025-11-11"
  to: "2026-11-11"
totals:
  rule_applied: 21624
  compared: 9968
  match: 9132
  mismatch: 836
  mismatch_ratio: 0.083868
by_scope:
  REGION: { ... }        # 시·도 규칙
  ALL: { ... }           # 조달청 기본 규칙
  INSTITUTION: { ... }   # 기관 규칙
by_rule:
  SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4:
    rule_id: SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4
    edition: "2023-03-02"     # 규칙 시행일(판본)
    scope: REGION
    declared_rate: "85.495"   # 규칙 대표값. 구간값과 다를 수 있음
    rule_applied: 138
    compared: 138
    match: 1
    mismatch: 137
    mismatch_ratio: 0.992754
    top_diffs:
    - diff: 2.5
      count: 137
```

### 3.1 `by_scope`

`REGION`, `ALL`, `INSTITUTION` 세 축을 항상 모두 남깁니다. 각 축의 항목은 `totals` 와
같은 다섯 값입니다. 한 축도 없으면 0 으로 채웁니다.

### 3.2 `by_rule`

- 키는 규칙 ID 입니다. `edition` 에 규칙 시행일을 함께 남겨 어느 판본인지 드러냅니다.
- `mismatch` 가 5건 이상인 규칙만 남깁니다(`--min-rule-mismatch`). 5건 미만 규칙은
  우연 변동과 실제 결함을 구분하기 어려워 목록에서 뺍니다. 따라서 `by_rule` 의 불일치
  합계는 `totals.mismatch` 보다 작을 수 있습니다.
- `top_diffs` 는 불일치 차이값 상위 3개입니다. 건수 내림차순, 같으면 차이값 오름차순이며
  `diff` 는 공고값 - 규칙값(%p), `count` 는 그 차이의 건수입니다.
- 정렬은 `mismatch` 내림차순, 같으면 규칙 ID 오름차순입니다.

---

## 4. 실행과 갱신

### 4.1 수동 실행

```sh
# 기본: 최근 12개월, Servc, 낙찰방법 필터 없음
uv run python scripts/report_lwlt_mismatch.py

# 조회 조건 바꾸기
uv run python scripts/report_lwlt_mismatch.py --months 6 --category Servc
uv run python scripts/report_lwlt_mismatch.py --method-code 낙030001

# 파일을 쓰지 않고 기존 지표와 비교만
uv run python scripts/report_lwlt_mismatch.py --check

# 점검 기준일을 지표를 만든 날로 고정
uv run python scripts/report_lwlt_mismatch.py --check --as-of 2026-11-11
```

`--check` 는 기존 YAML 과 새 집계가 다르면 종료 코드 `1`, 같으면 `0` 입니다. 비교에서
`generated_at` 과 `window.from`, `window.to` 는 제외합니다.
기준일은 `--as-of YYYY-MM-DD` 가 있으면 그 값, 없으면 기존 지표의 `window.to`,
그것도 없으면 오늘입니다. `--check` 없이 다시 만들 때는 지금처럼 오늘 기준입니다.

### 4.2 정기 실행

현재는 수동 실행 또는 CI 잡에서 실행합니다. 워커 크론(`src/tasks/`)에는 넣지 않습니다
(D11·D30 결정 범위 밖). CI 에 붙일 때는 `--check` 를 사용해 지표 파일이 낡았는지
검사하고, 갱신 커밋은 규칙 변경과 같은 작업 브랜치에서 남깁니다.

### 4.3 갱신 절차

1. 규칙 레지스트리나 판정 경로를 바꾼 작업 브랜치에서 생성기를 다시 돌립니다.
2. `git diff data/reference/lwlt_mismatch_metrics.yaml` 로 규칙별 변화를 확인합니다.
3. 값 변화의 원인을 커밋 메시지나 관련 문서에 적습니다.
4. `uv run pytest tests/test_report_lwlt_mismatch.py -q` 를 통과시킵니다.

---

## 5. 현재 기준값과 이전 지표의 차이

### 5.1 2026-11-11 기준값

2026-11-11 재생성(창 2025-11-11 ~ 2026-11-11) 값입니다.
`uv run python scripts/report_lwlt_mismatch.py` 로 파일을 다시 쓴 뒤 `--check` 가
차이 0건, 종료 코드 `0` 임을 확인했습니다.

| 항목 | 2026-11-07 | 2026-11-11 | 변화 |
| --- | ---: | ---: | ---: |
| 규칙 적용 | 21,594 | 21,624 | +30 |
| 비교 가능 | 9,968 | 9,968 | 0 |
| 일치 | 9,130 | 9,132 | +2 |
| 불일치 | 838 | 836 | -2 |
| 불일치율 | 8.4069% | 8.3868% | -0.0201%p |

| 적용 범위 | 2026-11-07 적용/비교/불일치 (율) | 2026-11-11 적용/비교/불일치 (율) |
| --- | --- | --- |
| `REGION` | 642 / 642 / 455 (70.87%) | 645 / 645 / 457 (70.85%) |
| `ALL` | 20,816 / 9,206 / 382 (4.15%) | 20,843 / 9,202 / 378 (4.11%) |
| `INSTITUTION` | 136 / 120 / 1 (0.83%) | 136 / 121 / 1 (0.83%) |

### 5.2 규칙별 비교 건수 상위 변화 10개

`by_rule` 의 `compared` 변화가 큰 규칙 10개입니다. `mismatch` 가 5건 미만인 규칙은
`by_rule` 에 들어오지 않으므로 두 회차 모두 목록에 있는 규칙만 비교합니다.

| 규칙 ID | `compared` 11-07 -> 11-11 | `mismatch` 11-07 -> 11-11 |
| --- | ---: | ---: |
| `SERVC_QUAL_PRE_20250901_ATTACH_01` | 1,287 -> 1,265 (-22) | 35 -> 33 (-2) |
| `SERVC_QUAL_PRE_20250901_ATTACH_03` | 1,101 -> 1,086 (-15) | 52 -> 51 (-1) |
| `SERVC_QUAL_POST_20260526_ATTACH_01` | 377 -> 390 (+13) | 17 -> 17 (0) |
| `SERVC_QUAL_POST_20260526_ATTACH_06` | 114 -> 123 (+9) | 6 -> 6 (0) |
| `SERVC_QUAL_PRE_20250901_ATTACH_08` | 329 -> 323 (-6) | 12 -> 12 (0) |
| `SERVC_QUAL_POST_20260526_ATTACH_08` | 130 -> 136 (+6) | 7 -> 7 (0) |
| `SERVC_QUAL_PRE_20250901_ATTACH_16` | 184 -> 181 (-3) | 56 -> 54 (-2) |
| `SERVC_QUAL_PRE_20250901_ATTACH_05` | 101 -> 98 (-3) | 22 -> 22 (0) |
| `SERVC_QUAL_POST_20260526_ATTACH_17` | 135 -> 138 (+3) | 12 -> 12 (0) |
| `SERVC_QUAL_PRE_20250901_ATTACH_15` | 276 -> 274 (-2) | 79 -> 79 (0) |

`by_rule` 항목 수는 29개로 같고, 새로 들어오거나 빠진 규칙 ID 는 없습니다.

### 5.3 해석

불일치율은 8.4069% 에서 8.3868% 로 0.0201%p 내렸지만, 이 하락을 계산 동작 개선으로
읽지 않습니다. 현행 코드는 공고 하한율이 있으면 규칙값보다 공고값을 먼저 쓰므로
([src/app/services/evaluation_rules.py:3698](../../src/app/services/evaluation_rules.py)),
이 지표의 불일치는 계산 오류가 아니라 규칙 선택·규칙 기본값·폴백 경로의 정합성입니다.
두 회차의 차이는 창이 2025-11-07 에서 2025-11-11 로 4일 움직이면서 경계 공고가
빠지고 새 수집분이 들어온 결과이며, 규칙 레지스트리나 판정 코드는 바뀌지 않았습니다.

### 5.4 감사 문서와의 차이

2026-11-06 전수 감사 문서와 비교하면 다음과 같습니다. 감사 문서 수치는 정본이 아니며,
같은 스크립트로 다시 잰 값이 정본입니다.

| 항목 | 현재 지표(2026-11-11) | 감사 문서(2026-11-06) | 차이 |
| --- | ---: | ---: | ---: |
| 규칙 적용 | 21,624 | 21,546 | +78 |
| 비교 가능 | 9,968 | 9,904 | +64 |
| 일치 | 9,132 | 8,720 | +412 |
| 불일치 | 836 | 1,184 | -348 |
| 불일치율 | 8.3868% | 11.95% | -3.56%p |

| 적용 범위 | 현재 적용/비교/불일치 | 감사 문서 적용/비교/불일치 |
| --- | --- | --- |
| `REGION` | 645 / 645 / 457 (70.85%) | 1,855 / 1,855 / 772 (41.62%) |
| `ALL` | 20,843 / 9,202 / 378 (4.11%) | 19,609 / 7,983 / 399 (5.00%) |
| `INSTITUTION` | 136 / 121 / 1 (0.83%) | 82 / 66 / 13 (19.70%) |

차이는 두 가지에서 납니다.

1. **창이 다릅니다.** 감사 문서는 2025-11-06 부터, 이 지표는 실행일 기준 12개월이라
   2025-11-11 부터 봅니다. 실행일이 달라지면 창과 값이 함께 움직입니다.
2. **그 뒤 규칙 레지스트리가 바뀌었습니다.** `REGION` 적용이 크게 줄고 `ALL` 적용이 늘어난
   것은 시·도 규칙 적용 건이 조달청 기본 규칙 쪽으로 이동한 결과입니다. `INSTITUTION`
   적용이 82건에서 136건으로 늘어난 것은 기관 규칙 등록이 늘어난 결과입니다.

감사 문서 값과의 차이는 규칙 변경 이력으로 설명합니다.

---

## 6. 한계

1. **규칙값은 대입 산출값일 수 있습니다.** 기관 별표는 낙찰하한율을 인쇄하지 않고 계수와
   평탄 문장만 두는 경우가 있습니다. 그때는 코드에 등록된 대표값을 씁니다.
2. **구간형 규칙은 불일치가 과대 계상될 수 있습니다.** 추정가격으로 구간을 고르지 못하면
   대표값으로 대체하므로, 구간마다 하한율이 다른 규칙에서 실제 적용값과 다를 수 있습니다.
3. **공고값 우선 원칙 때문에 불일치가 곧 오적용은 아닙니다.** 공고 하한율이 있으면 계산에는
   공고값이 쓰입니다. 이 지표는 규칙 쪽 정합성을 보는 값입니다.
4. **시·도 귀속은 본청명 기준입니다.** 통합 전후로 같은 기관이 다른 시·도명으로 나뉠 수
   있습니다.
5. **규칙 ID가 곧 판본입니다.** 현행 구조는 판본마다 규칙 ID를 따로 두므로, `edition` 은
   같은 규칙 ID의 시행일을 확인하는 보조 표기입니다.

---

## 7. 관련 문서

- 결정 원장: [docs/analysis/decision_backlog_20261107.md](../analysis/decision_backlog_20261107.md)
- 최초 전수 감사: [docs/analysis/lwlt_notice_vs_rule_audit_20261106.md](../analysis/lwlt_notice_vs_rule_audit_20261106.md)
- 기관 규칙 판본 조사: [docs/analysis/inst_band_mismatch_13_20261107.md](../analysis/inst_band_mismatch_13_20261107.md)
- 규칙 커버리지 원장 생성기: [scripts/report_rule_coverage.py](../../scripts/report_rule_coverage.py)
