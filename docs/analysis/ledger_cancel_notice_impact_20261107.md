# 원장 취소공고·재공고 차수 혼입 영향 측정 (2026-11-07)

> **작성일**: 2026-11-07
> **측정 창**: 2025-11-07 ~ 2026-11-07 (12개월)
> **대상**: 업무구분 `Servc`, 낙찰방법 코드 `낙030001`
> **비교 기준**: [data/reference/rule_coverage_ledger.yaml](../../data/reference/rule_coverage_ledger.yaml) (2026-11-07 생성분)
> **원칙**: 코드와 원장은 고치지 않았습니다. 측정은 메모리에서만 했고 DB 세션은 `SET SESSION TRANSACTION READ ONLY` 로 열었습니다.

---

## 1. 요약

현행 원장은 같은 공고번호·업무구분에서 **최신 차수 행 하나**를 대표로 삼습니다. 최신 차수가 취소공고여도 그대로 판정하므로, 실제로 진행되지 않은 차수의 판정이 집계에 들어갑니다. 이 문서는 같은 행 집합에서 두 가지 대안을 메모리로 계산했습니다.

- **현행**: 최신 차수를 그대로 쓴다.
- **(가) 취소 제외**: 최신 차수가 `취소공고` 인 공고번호를 집계에서 뺀다.
- **(나) 마지막 유효 차수**: 취소공고 차수를 건너뛰고 마지막 비취소 차수로 판정한다. 비취소 차수가 없으면 뺀다.

현행 재계산 값은 원장 `totals` 와 정확히 일치했습니다(공고 31,325건, 차단 9,728건).

### 1.1 전체 및 적용 범위별 건수

| 적용 범위 | 현행 | (가) 취소 제외 | (나) 마지막 유효 차수 | (가) 차이 | (나) 차이 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `INSTITUTION` | 99 (0.003160) | 94 (0.003391) | 99 (0.003163) | -5 (-5.05%) | 0 |
| `REGION` | 1,813 (0.057877) | 1,599 (0.057678) | 1,812 (0.057897) | -214 (-11.80%) | -1 (-0.06%) |
| `PPS_DEFAULT` | 19,685 (0.628412) | 17,345 (0.625654) | 19,667 (0.628399) | -2,340 (-11.89%) | -18 (-0.09%) |
| `BLOCKED` | 9,728 (0.310551) | 8,685 (0.313278) | 9,719 (0.310541) | -1,043 (-10.72%) | -9 (-0.09%) |
| `ERROR` | 0 | 0 | 0 | 0 | 0 |
| **전체 공고** | **31,325** | **27,723** | **31,297** | **-3,602 (-11.50%)** | **-28 (-0.09%)** |

괄호는 전체 공고 대비 비율입니다.

### 1.2 차단 코드별 건수

| 갈래 | 차단 코드 | 현행 | (가) 취소 제외 | (나) 마지막 유효 차수 | (가) 차이 | (나) 차이 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `manual_input` | `MANUAL_EVALUATION` | 9,415 | 8,429 | 9,406 | -986 | -9 |
| `manual_input` | `LOCAL_RULE_NOT_FOUND` | 84 | 78 | 84 | -6 | 0 |
| `manual_input` | `LOCAL_SERVICE_TYPE_UNRESOLVED` | 9 | 4 | 9 | -5 | 0 |
| `not_computable` | `NON_PRED_PRICE` | 211 | 169 | 211 | -42 | 0 |
| `not_computable` | `RULE_NOT_FOUND` | 6 | 3 | 6 | -3 | 0 |
| `not_computable` | `RULE_REGIME_MISMATCH` | 3 | 2 | 3 | -1 | 0 |
| `manual_input` 소계 | | 9,508 | 8,511 | 9,499 | -997 | -9 |
| `not_computable` 소계 | | 220 | 174 | 220 | -46 | 0 |
| **차단 전체** | | **9,728** | **8,685** | **9,719** | **-1,043** | **-9** |

### 1.3 핵심 관찰

1. **최신 차수가 취소공고인 공고번호는 3,602건**입니다. 현행 집계는 이 3,602건을 모두 판정 대상으로 셉니다.
2. **최신 차수가 재공고인 공고번호는 1,628건**입니다. 재공고는 (가)·(나) 어느 쪽에서도 제외하지 않았습니다.
3. **(가)는 존재 자체를 지웁니다.** 전체가 11.50% 줄고, 적용 범위별로는 `REGION` -11.80%, `PPS_DEFAULT` -11.89%, `BLOCKED` -10.72% 가 빠집니다. 취소된 사업이 원장 모집단에서 사라지는 셈입니다.
4. **(나)는 거의 바뀌지 않습니다.** 전체 -28건(-0.09%)이며, 이는 비취소 차수가 아예 없는 28개 공고번호를 뺀 값입니다. 나머지 3,574개 공고번호는 대표 행이 바뀌어도 판정이 같습니다.
5. 대표 행이 바뀌어 **판정이 실제로 달라지는 경우는 19건**입니다. 그중 17건은 적용 범위는 `PPS_DEFAULT` 그대로이고 규칙 ID 만 바뀌며, 2건은 `BLOCKED`(`MANUAL_EVALUATION`)에서 `PPS_DEFAULT` 로 이동합니다. 나머지 3,555건은 규칙 ID 까지 같습니다.
6. **(가)의 차단 감소는 `MANUAL_EVALUATION` 이 대부분**입니다(-986). 이어서 `NON_PRED_PRICE` -42, `LOCAL_RULE_NOT_FOUND` -6, `LOCAL_SERVICE_TYPE_UNRESOLVED` -5, `RULE_NOT_FOUND` -3, `RULE_REGIME_MISMATCH` -1 입니다.
7. **(나)의 차단 감소는 전부 `MANUAL_EVALUATION`** 입니다(-9). 다른 코드는 변하지 않습니다.

### 1.4 재현 방법

`scripts/report_rule_coverage.py` 의 `ANNOUNCEMENT_SQL`, `_load_institutions`, `_as_dict`, `_ord_key`, `_to_record`, `classify_result`, `build_ledger` 를 그대로 import 해 메모리에서 실행했습니다. 파일 쓰기는 없습니다.

```python
from datetime import date, datetime, timedelta
from datetime import time as day_time

from sqlalchemy import text

from src.app.core.db import engine
from src.app.services.band_regime_lookup import (
    attachment_regime_key,
    lookup_attachment_regimes,
)
from scripts import report_rule_coverage as rrc

today = date(2026, 11, 7)
window_from = rrc._months_ago(today, 12)
window_end = today + timedelta(days=1)
cancel = "취소공고"

rows_by_key = {}
with engine.connect() as conn:
    conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
    institutions = rrc._load_institutions(conn)
    result = conn.execution_options(stream_results=True).execute(
        text(rrc.ANNOUNCEMENT_SQL),
        {
            "category": "Servc",
            "window_from": datetime.combine(window_from, day_time.min),
            "window_end": datetime.combine(window_end, day_time.min),
        },
    )
    for row in result:
        raw = rrc._as_dict(row.raw_data)
        if str(raw.get("sucsfbidMthdCd") or "").strip() != "낙030001":
            continue
        rows_by_key.setdefault((row.bid_ntce_no, row.category), []).append(row)

    current, exclude, last_valid = [], [], []
    for rows in rows_by_key.values():
        ordered = sorted(rows, key=lambda row: rrc._ord_key(row.bid_ntce_ord))
        best = ordered[-1]
        current.append(best)
        if str(rrc._as_dict(best.raw_data).get("ntceKindNm") or "").strip() != cancel:
            exclude.append(best)
        noncancel = [
            row
            for row in ordered
            if str(rrc._as_dict(row.raw_data).get("ntceKindNm") or "").strip() != cancel
        ]
        if noncancel:
            last_valid.append(noncancel[-1])

    regimes = lookup_attachment_regimes(
        conn,
        (
            attachment_regime_key(row)
            for row in current + exclude + last_valid
        ),
    )

# 각 선택 집합마다 아래처럼 레코드를 만들고 build_ledger 로 접습니다.
records = [
    rrc._to_record(row, institutions, regimes.get(attachment_regime_key(row)))
    for row in current  # 또는 exclude, last_valid
]
ledger = rrc.build_ledger(
    records,
    filter_meta={"months": 12, "category": "Servc", "method_code": "낙030001"},
    min_announcements=5,
    generated_at=today.isoformat(),
)
```

집계 전 행 수는 37,391행, 공고번호·업무구분 키 수는 31,325개였습니다.

---

## 2. 취소·정정 판별 필드와 값 분포

### 2.1 판별 필드

취소 여부는 `bid_announcements.raw_data` 의 **`ntceKindNm`** 으로 판별합니다. `raw_data` 최상위 키이며, 같은 의미의 컬럼은 별도로 두지 않습니다. 값은 다음 네 가지입니다.

| 값 | 의미 | 이번 측정 처리 |
| --- | --- | --- |
| `등록공고` | 최초 등록 공고 | 유효 차수로 센다 |
| `재공고` | 재공고 | 유효 차수로 센다. (가)·(나) 모두 제외하지 않음 |
| `취소공고` | 취소 공고 | (가)는 공고번호 전체를 빼고, (나)는 이 차수만 건너뛴다 |
| `변경공고` | 변경 공고 | 유효 차수로 센다 |

`변경공고` 는 정정이지만 취소가 아니므로 제외하지 않았습니다. `scripts/backtest_qualification_rules.py` 의 `is_cancelled_kind` 도 `취소공고` 만 취소로 봅니다.

### 2.2 실제 질의 결과

`category` 와 `bid_ntce_dt` 범위로 좁힌 `JSON_EXTRACT` 집계입니다. `scripts/db_readonly_query.py` 로 실행했습니다.

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.ntceKindNm')) AS kind,
       COUNT(*) AS cnt
FROM bid_announcements
WHERE category='Servc'
  AND bid_ntce_dt >= '2025-11-07'
  AND bid_ntce_dt < '2026-11-08'
GROUP BY kind
ORDER BY cnt DESC
```

| `ntceKindNm` | Servc 전체 | `낙030001` 만 |
| --- | ---: | ---: |
| `등록공고` | 166,263 | 29,511 |
| `재공고` | 25,557 | 1,742 |
| `취소공고` | 12,578 | 3,603 |
| `변경공고` | 12,536 | 2,535 |

낙찰방법 필터까지 적용한 두 번째 열이 이번 측정의 모집단입니다. 취소공고 행 3,603건 가운데 최신 차수가 취소공고인 공고번호는 3,602개입니다. 즉 대표 행 기준 취소공고는 공고번호 3,602개를 덮습니다.

### 2.3 "자동 계산 불가 9건"의 정확한 뜻

Capsule 이 말한 자동 계산 불가 9건은 **`RULE_NOT_FOUND` 6건 + `RULE_REGIME_MISMATCH` 3건**입니다. 이 9건의 공고 종류는 취소공고 4건, 재공고 1건, 변경공고 1건, 등록공고 3건입니다. 즉 "4건이 취소공고, 1건이 재공고"라는 전제와 일치합니다.

`LOCAL_SERVICE_TYPE_UNRESOLVED` 9건은 사용자 입력 필요(`manual_input`) 갈래이며 위 9건과 별개입니다. 이 9건은 취소공고 5건, 등록공고 4건입니다.

---

## 3. 차이가 나는 공고 예시

### 3.1 판정이 달라지는 19건 중 10건

현행 대표가 취소공고이고, 마지막 비취소 차수로 바꾸면 판정이 달라지는 사례입니다. `(가)` 는 이 공고번호들을 아예 빼므로 별도 판정이 없습니다.

| 공고번호 | 기관 | 현행 차수·종류 | 현행 판정 | (나) 차수·종류 | (나) 판정 | 차이 |
| --- | --- | --- | --- | --- | --- | --- |
| `R26BK01273210` | 서울특별시 도시기반시설본부 | 001 취소공고 | `BLOCKED` / `MANUAL_EVALUATION` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 차단 해소 |
| `R26BK01300002` | 경상남도진주교육청 사봉초등학교 | 001 취소공고 | `BLOCKED` / `MANUAL_EVALUATION` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_QUAL_PRE_20250901_ATTACH_03` | 차단 해소 |
| `R26BK01495106` | 인천국제공항공사 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01496139` | 전남광주통합특별시 강진군 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01499457` | 서울특별시 영등포구 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01526125` | 경기도 여주시 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01531008` | 경기도 안산시 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01531104` | 울산광역시 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |
| `R26BK01531899` | 해양환경공단 평택지사 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_QUAL_POST_20260526_ATTACH_16` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_QUAL_PRE_20250901_ATTACH_15` | 규칙 ID 변경 |
| `R26BK01533766` | 인천광역시교육청 | 001 취소공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT` | 000 등록공고 | `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` | 규칙 ID 변경 |

같은 19건의 구성은 `BLOCKED` 에서 `PPS_DEFAULT` 로 이동한 2건과, 적용 범위는 `PPS_DEFAULT` 그대로이면서 규칙 ID 만 바뀐 17건입니다. 표에는 그중 10건(차단 해소 2건, 규칙 ID 변경 8건)을 실었습니다.

### 3.2 그 밖의 대표 사례

- **비취소 차수가 없어 (나)에서도 빠지는 28건**: `R25BK00999996`(기후에너지환경부 한강유역환경청, 001 취소공고), `R25BK01097655`(통일부, 001 취소공고), `R25BK01098369`(서울주택도시개발공사, 002 취소공고) 등입니다.
- **대표가 바뀌어도 판정이 같은 3,555건**: `R25BK01000291`(경기도 광주시)은 002 취소공고와 001 변경공고가 모두 `PPS_DEFAULT` / `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 입니다.

### 3.3 자동 계산 불가 9건의 공고 종류

| 공고번호 | 차수 | 종류 | 기관 | 차단 코드 |
| --- | --- | --- | --- | --- |
| `R25BK01139979` | 001 | 변경공고 | 강원도원주의료원 | `RULE_NOT_FOUND` |
| `R25BK01197545` | 001 | 취소공고 | 대구의료원 | `RULE_NOT_FOUND` |
| `R26BK01310604` | 001 | 취소공고 | 전남광주통합특별시 강진군 | `RULE_NOT_FOUND` |
| `R26BK01345718` | 001 | 취소공고 | 전북특별자치도 남원의료원 | `RULE_NOT_FOUND` |
| `R26BK01560778` | 000 | 등록공고 | 전라남도순천의료원 | `RULE_NOT_FOUND` |
| `R26BK01577453` | 000 | 재공고 | 전라남도순천의료원 | `RULE_NOT_FOUND` |
| `R25BK01166116` | 000 | 등록공고 | 한국지역난방공사 | `RULE_REGIME_MISMATCH` |
| `R26BK01372508` | 001 | 취소공고 | 전남광주통합특별시교육청 전남광주통합특별시교육청AI교육원 | `RULE_REGIME_MISMATCH` |
| `R26BK01375736` | 000 | 등록공고 | 전남광주통합특별시교육청 전남광주통합특별시교육청AI교육원 | `RULE_REGIME_MISMATCH` |

(가)를 적용하면 이 9건 중 취소공고 4건이 빠져 5건이 남습니다. (나)를 적용하면 4건 모두 마지막 비취소 차수에서 같은 차단 코드가 나와 9건이 그대로 유지됩니다.

---

## 4. 원장 정의를 바꿀 때의 영향

이 절은 목록만 남기고 고치지 않았습니다. `31,325`·`9,728` 같은 수치를 고정하거나 같은 수집 방식을 전제하는 곳입니다.

| 위치 | 고정하는 내용 | 정의 변경 시 필요한 조치 |
| --- | --- | --- |
| [scripts/report_rule_coverage.py](../../scripts/report_rule_coverage.py) | `collect_records` 가 최신 차수만 남깁니다. `_ord_key` 비교로 대표를 고릅니다 | (가)·(나)를 쓰려면 대표 선정 루프를 바꾸고 `ntceKindNm` 판별을 추가해야 합니다 |
| [data/reference/rule_coverage_ledger.yaml](../../data/reference/rule_coverage_ledger.yaml) | `totals.announcements: 31325`, `applied_scope.BLOCKED: 9728` 등 | 재생성 산출물입니다. 이 Task 에서는 커밋하지 않았습니다 |
| [docs/ops/rule_coverage_ledger.md](../ops/rule_coverage_ledger.md) | `announcements` 의 뜻과 `applied_scope`·`blocked_breakdown` 집계 규칙 | 취소 차수 처리 규칙을 이 문서에 먼저 추가해야 합니다 |
| [docs/context/CURRENT_STATE.md](../context/CURRENT_STATE.md) | 31,325건 중 지역 1,813·전국 19,685·기관 99, 차단 9,728·사용자 입력 9,508 | 정의를 바꾸면 `rule_coverage` 문장의 수치와 비율을 함께 갱신해야 합니다 |
| [docs/analysis/local_entity_a_route_regression_20261106.md](local_entity_a_route_regression_20261106.md) | 31,325건 기준 비교표와 19,685·1,813·9,728 | 이 회귀 문서의 기준선이 다른 모집단이 됩니다 |
| [docs/analysis/local_entity_pps_route_regression_20261106.md](local_entity_pps_route_regression_20261106.md) | 31,348건(하루 앞선 창) 기준 비교 | 창과 모집단이 함께 달라져 직접 비교가 어긋납니다 |
| [docs/analysis/blocked_reason_breakdown_20261106.md](blocked_reason_breakdown_20261106.md) | 같은 `collect_records`·최신 차수 방식, 차단 9,811건 복원 | 사유 복원 모집단도 같은 취소 차수를 포함합니다 |
| [docs/analysis/rule_not_found_32_fix_regression_20261106.md](rule_not_found_32_fix_regression_20261106.md) | 같은 측정 창·최신 차수 방식의 32건 회귀 | 취소 차수를 빼면 비교 기준선이 바뀝니다 |
| [docs/analysis/gb_waste_lwlt_fix_regression_20261106.md](gb_waste_lwlt_fix_regression_20261106.md) | `collect_records` 를 그대로 실행한 전후 비교 | 같은 영향 범위입니다 |
| [docs/handoff/handoff_20261017_coverage_unblock_close.md](../handoff/handoff_20261017_coverage_unblock_close.md) | 지역 규칙 1,813건(5.8%) | 과거 시점 수치이므로 그대로 두고, 새 정의와 다르다는 각주가 필요합니다 |
| [docs/handoff/handoff_20261018_close.md](../handoff/handoff_20261018_close.md) | 지역 규칙 적용 1,813건 | 같은 과거 기준선입니다 |
| [tests/test_rule_coverage_ledger.py](../../tests/test_rule_coverage_ledger.py) | `totals` 합계의 자기 일관성(`applied_scope` 합 = 전체, 기관+지역+꼬리 = 전체) | 31,325 같은 절대값은 고정하지 않으므로 정의가 바뀌어도 통과합니다. 대신 취소 규칙 자체를 검증하는 시험은 없습니다 |
| [tests/test_report_rule_coverage_split.py](../../tests/test_report_rule_coverage_split.py) | `blocked_breakdown` 갈래 분류 | 취소와 무관하므로 영향이 없습니다 |

`grep` 결과, `31,325` 를 직접 고정하는 시험은 없었습니다. `tests/test_rule_coverage_ledger.py` 는 커밋된 YAML 의 합계가 서로 맞는지만 확인합니다.

---

## 5. 사용자 결정 항목

1. **정책 선택**: 현행 유지, (가) 취소 제외, (나) 마지막 유효 차수 중 무엇을 원장 정의로 삼을지 정해야 합니다.
   - 현행은 취소된 사업까지 모집단에 넣어 적용 범위 비율을 낮춥니다.
   - (가)는 취소 사업을 모집단에서 완전히 지워 전체 건수가 11.50% 줄고, 과거 문서의 31,325 기준선과 직접 비교할 수 없게 됩니다.
   - (나)는 원 공고의 판정을 살리면서 취소 차수만 건너뜁니다. 전체 변화가 -28건(-0.09%)이라 기존 기준선과 거의 이어집니다.
2. **재공고 처리**: 재공고를 독립된 유효 공고로 볼지, 원 공고에 합칠지 정해야 합니다. 이번 측정은 재공고를 제외하지 않았고 최신 차수가 재공고인 1,628건이 그대로 남아 있습니다.
3. **변경공고 처리**: `변경공고` 를 유효 차수로 인정할지 정해야 합니다. 이번 측정은 취소가 아니므로 유효로 셌습니다.
4. **취소 사업의 표시 방식**: (가)처럼 빼면 "취소된 사업이 몇 건이었는지"가 원장에서 사라집니다. `cancelled` 같은 별도 축이나 `excluded` 집계를 둘지 결정이 필요합니다.
5. **비취소 차수가 없는 28건**: (나)에서 이 28건을 뺄지, 취소 상태로 남겨 별도 표시할지 정해야 합니다.
6. **문서 갱신 범위**: 정의를 바꾸면 4절의 `CURRENT_STATE`·회귀 문서·원장 운영 문서를 함께 갱신할지, 과거 문서는 시점 기준선으로 보존하고 새 문서에만 새 정의를 적용할지 정해야 합니다.
