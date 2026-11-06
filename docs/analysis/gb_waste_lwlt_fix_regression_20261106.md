# 경북 폐기물(2026) 규칙 하한율 정정 회귀

> **작성일**: 2026-11-06
> **작업**: Orca worker `task_2cfdfecb983f`
> **대상 규칙**: `SERVC_LOCAL_GB_20260108_ATTACH_03`
> **근거**: [lwlt_region_rule_value_check_20261106.md](lwlt_region_rule_value_check_20261106.md) 1·2절 (리뷰 pass)
> **범위 경계**: 규칙 값과 시험, 이 문서만 바꿨습니다. DB 스키마·행 수, 다른 시·도 규칙 값, 판정 로직은 바꾸지 않았습니다.

---

## 1. 요약

1. 경북 폐기물(2026) 규칙은 `_local_rule` 에 대표값을 넘기지 않아 `WASTE` 기본값 **84.245%** 를 썼습니다. 원문 별표 3 에는 이 값이 없습니다.
2. 원문 별표 3 의 B(70/50)·k(20/4)·기준비율(88)·통과점수(95)와 평탄점으로 역산하면 **5억원 미만 87.745%**, **5억원 이상 86.745%** 입니다.
3. 구간 하한율 두 개를 `PriceBand.lwlt_rate` 에 등록하고 규칙 대표값을 87.745% 로 정정했습니다. `_LOCAL_LWLT_BY_SERVICE` 기본값은 그대로 두어 다른 폐기물 규칙 값은 바뀌지 않습니다.
4. 최근 12개월 Servc 31,348건 판정 회귀에서 **적용 규칙 ID 변화 0건, 차단 변화 0건**입니다. 하한율이 바뀐 57건은 모두 경북 폐기물이며, 공고값과 규칙값이 일치하는 건이 **0 → 22건(+22)** 입니다.

---

## 2. 정정 내용

### 2.1 값 비교

| 항목 | 정정 전 | 정정 후 | 근거 |
| --- | --- | --- | --- |
| 규칙 대표값 | 84.245 (서비스 기본값 폴백) | 87.745 (직접 선언) | 원문 5억원 미만 산식값 |
| 5억원 미만 구간 하한율 | 없음 | 87.745 | 70-20x\|88-투찰률\|=65 → 87.75% → 87.745% |
| 5억원 이상 구간 하한율 | 없음 | 86.745 | 50-4x\|88-투찰률\|=45 → 86.75% → 86.745% |
| B·k·기준비율 | 70·20 / 50·4 / 0.88 | 같음 | 원문 별표 3 (변경 없음) |
| 통과점수 | 95 | 95 | 원문 본문 제10조 (변경 없음) |

### 2.2 변경 위치

- [evaluation_rules_local.py](../../src/app/services/evaluation_rules_local.py:939) `SERVC_LOCAL_GB_20260108_ATTACH_03` 에 구간별 `lwlt_rate` 와 규칙 대표값을 추가했습니다.
- [evaluation_rules.py](../../src/app/services/evaluation_rules.py:2570) 의 `_band_lwlt_rate` 는 구간값을 먼저 찾고 없을 때만 대표값으로 돌아가는 공용 경로입니다. 이번 정정으로 구간값이 생겨 대표값 폴백이 쓰이지 않게 되며, **공용 함수 자체는 수정하지 않았습니다**.
- `evaluation_rules_local.py:394` 의 `_LOCAL_LWLT_BY_SERVICE["WASTE"]=84.245` 와 `:604` 의 `_local_rule` 폴백은 여러 규칙이 공유하므로 바꾸지 않았습니다. 이 규칙만 직접 값을 선언했습니다.

---

## 3. 판정 회귀

### 3.1 방법

`scripts/report_rule_coverage.py` 의 `collect_records` 와 같은 SQL·같은 판정 함수를 메모리에서 실행했습니다(읽기 전용 트랜잭션, `LIKE` 없음). 조건은 `--months 12 --category Servc --method-code 낙030001` 이며, 수정 전과 수정 후에 각각 실행해 공고번호·차수로 짝지었습니다.

### 3.2 결과

| 항목 | 수정 전 | 수정 후 | 변화 |
| --- | ---: | ---: | ---: |
| 대표 공고 | 31,348 | 31,348 | 0 |
| 차단 | 9,747 | 9,747 | 0 |
| 규칙 적용 | 21,604 | 21,604 | 0 |
| 적용 규칙 ID 가 바뀐 공고 | - | - | **0** |
| 하한율이 바뀐 공고 | - | - | **57** |
| 경북 폐기물 적용 공고 | 57 | 57 | 0 |
| 경북 공고값·규칙값 일치 | 0 | 22 | **+22** |

하한율 변화는 `84.245 → 87.745` 44건, `84.245 → 86.745` 13건입니다. 모두 경북 폐기물 규칙 적용 공고이며, 다른 규칙·다른 공고의 하한율은 바뀌지 않았습니다.

### 3.3 경북 57건 잔여 불일치

| 공고값 | 적용 규칙값 | 건수 | 판독 |
| --- | ---: | ---: | --- |
| 87.745 | 87.745 | 22 | 일치 (5억원 미만 원문 산식값) |
| 86.745 | 87.745 | 22 | 환경부 고시 2억~5억 구간 |
| 85.495 | 86.745 | 11 | 환경부 고시 5억~15억 구간 |
| 82.995 | 86.745 | 1 | 환경부 고시 15억~30억 구간 |
| 80.495 | 86.745 | 1 | 조달청 기준 |

정정 후 남는 35건은 모두 공고가 환경부 고시 또는 조달청 기준의 다른 구간을 적용한 건입니다(원 조사 문서 4.1절과 같은 분해).

---

## 4. 시험 변경

### 4.1 추가

- `tests/test_gb_waste_lwlt_fix.py`: 5억 미만/이상 구간 하한율, B·k·기준비율·통과점수, 공고 하한율 부재 시 적용값, 공고값 우선, 다른 시·도 폐기물 규칙 불변을 단언합니다.
- `tests/test_evaluation_rules_local.py`: `_LOCAL_LWLT_BY_SERVICE` 기본값과 그 폴백을 쓰는 규칙이 그대로임을 단언합니다.

### 4.2 갱신한 기존 단언

이 규칙의 동작 필드를 고정한 스냅샷 시험만 갱신했습니다. 84.245 를 직접 단언하던 기존 시험은 없었습니다.

| 파일 | 바꾼 줄 | 사유 |
| --- | --- | --- |
| `tests/test_local_lwlt_audit.py` | `UNCHANGED_RULE_IDS` 에서 `SERVC_LOCAL_GB_20260108_ATTACH_03` 제거, 주석에 정정 이력 추가 | 이제 정정 대상이므로 "비정정 규칙" 목록에서 제외 |
| `tests/test_local_lwlt_audit.py` | `UNCHANGED_RULES_DIGEST` `94645fa3…` → `06d57aa2…` | 위 목록 변경 반영 |
| `tests/test_local_regime_rules_wave2.py` | `EXISTING_RULES_DIGEST` `c35b6453…` → `35515bec…`, 주석 추가 | 규칙 동작 필드 변경 반영 |
| `tests/test_evaluation_rules_split_invariance.py` | `LOCAL_RULES` 지문 `ed46a9742ea23402` → `48d29a0c7a15e957` | 규칙 상수 값 변경 반영 |
| `tests/test_seoul_10eok_lwlt.py` | `LOCAL_RULES_EXCLUDING_SEOUL_DIGEST` `510c6d6b…` → `990fdee3…`, 주석 추가 | 규칙 동작 필드 변경 반영 |

다른 시험의 단언은 바꾸지 않았습니다.

---

## 5. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_gb_waste_lwlt_fix.py -q` | 11 passed |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'evaluation_rules or local'` | 955 passed, 9544 deselected |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10453 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |

---

## 6. 남은 일과 범위 밖

1. 경북 35건은 공고가 환경부 고시(또는 조달청) 기준을 인쇄한 건으로, 규칙 값 오류가 아닙니다. 공고 인용 기준을 별도 지표로 분리하는 일은 이번 범위 밖입니다.
2. 경북 별표 3 의 건설폐기물 제외 조항이 일반 표기 낙찰방법명에서 동작하지 않는 문제(원 조사 문서 4.4절)는 규칙 값과 별개이며 이번에 다루지 않았습니다.
3. 이번 정정은 공고에 하한율이 없는 경우의 기본값과 전수 점검의 규칙값 표시를 바꿉니다. 공고값이 있는 503건의 실제 점수 계산은 종전처럼 공고값 우선이라 바뀌지 않습니다.

---

## 부록 A. 재현 절차

저장소 루트에서 읽기 전용으로 실행했습니다. 임시 스크립트는 세션 스크래치패드에 두어 커밋하지 않았습니다.

```python
import importlib.util
from datetime import date

spec = importlib.util.spec_from_file_location(
    "report_rule_coverage", "scripts/report_rule_coverage.py"
)
rrc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rrc)

records = rrc.collect_records(months=12, category="Servc", method_code="낙030001")
for record in records:
    result = record["result"]
    if result is None or result.is_blocked or result.rule is None:
        continue
    rule_id = result.rule.rule_id
    band_rate, _label, _reason = rrc_er._band_lwlt_rate(result.rule, price)
    rate = band_rate if band_rate is not None else result.rule.lwlt_rate
```

수정 전후 스냅샷을 공고번호·차수로 짝지어 규칙 ID·차단·하한율 변화를 비교했습니다.
