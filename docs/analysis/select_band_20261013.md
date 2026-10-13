# 추정가격 구간으로 B·k 후보 하나를 고르는 select_band 로직

> **작성일**: 2026-10-13
> **작업 브랜치**: `kwanbum217/s2-select-band`
> **기준**: `main` (K1 `07a8c06b`, B1 `75b93233` 위)
> **대상 파일**: `scripts/extract_score_params.py`, `tests/test_extract_score_params.py`
> **표본**: 2015~2024년 용역 적격심사제(`낙030001`) 공고 500건 (연도별 50건, 시드 `h1pilot20261013`)
> **판정**: 구간 문구를 금액 항 목록으로 해석해 양 끝 구간을 판정하고, 후보가 하나로 좁혀지지 않으면 선택하지 않도록 `select_band` 를 보강했습니다. 합성 시험으로 고정했고, 같은 표본 재측정에서 회귀 0건입니다.

---

## 1. 질문과 배경

K1(`07a8c06b`)은 `scripts/extract_score_params.py` 에 `select_band` 를 넣었지만, B1(`75b93233`)과 H2 재측정 문서는 "같은 문서에 구간별 계산식이 여러 개 있어 후보가 `1|2|4` 처럼 나오며, 구간 확정은 `select_band` 의 별도 과제"로 남겨 두었습니다.

본 작업은 그 별도 과제입니다. 한 별표 안에서 k 후보가 여러 개 나올 때 **공고의 추정가격이 속하는 금액 구간의 B·k 하나를 고르는** 로직을 완성합니다. 구간을 해석할 수 없으면 추측하지 않고 후보를 그대로 두고 선택하지 않습니다.

기존 `band_matches` 는 라벨에서 **첫 번째 `N억` 만** 읽고 부등호 하나만 봤습니다. 그래서 `추정가격 5억원 이상 10억원 미만` 같은 양 끝 구간에서 15억이 "이상" 조건만 만족해 잘못 맞는 것으로 판정될 수 있었습니다. 또한 후보가 하나뿐이면 라벨이 추정가격을 명백히 배제해도 그 값을 골랐습니다. 이 둘이 review_checklist 의 `wrong_band` 위험입니다.

---

## 2. 수정 내용

### 2.1 구간 문구를 금액 항 목록으로 해석 (`parse_band_terms`)

`_BAND_TERM_RE` 가 금액마다 붙은 부등호를 함께 읽어 원 단위 `(금액, 부등호)` 항 목록을 만듭니다.

| 라벨 | 해석 |
| --- | --- |
| `추정가격 5억원 미만` | `(5억, 미만)` |
| `추정가격 5억원 이상 10억원 미만` | `(5억, 이상)`, `(10억, 미만)` |
| `추정가격 고시금액 이상` | 해석 항 없음 (고시금액은 연도별 고정값이라 문서만으로 계산 불가) |
| `추정가격 5억원` | 해석 항 없음 (부등호 없는 금액은 경계로 확정하지 않음) |

부등호 없는 금액과 `고시금액` 라벨은 항을 만들지 않아, 수치 비교로 추정하지 않습니다.

### 2.2 양 끝 구간 판정 (`band_matches`)

낙찰방법 문구(`sucsfbidMthdNm`)에 라벨이 그대로 있으면 K1 과 같이 그것을 정본으로 삼습니다. 그렇지 않으면 라벨의 **모든** 금액 항을 추정가격이 만족해야 맞는 것으로 봅니다. 양 끝 구간이면 아래·위 경계를 모두 검사합니다.

| 라벨 | 추정가격 | 판정 |
| --- | ---: | :---: |
| `추정가격 5억원 이상 10억원 미만` | 7억 | 맞음 |
| `추정가격 5억원 이상 10억원 미만` | 15억 | 아님 |
| `추정가격 5억원 이상 10억원 미만` | 4.9억 | 아님 |
| `추정가격 5억원 이상` | 5억 | 맞음 (이상은 경계 포함) |
| `추정가격 5억원 초과` | 5억 | 아님 |

### 2.3 확정 불가 시 선택하지 않음 (`select_band`)

맞는 후보가 정확히 하나면 그 값을 고릅니다. 후보가 하나뿐이어도 그 라벨이 **해석되는 구간**이고 추정가격이 구간 밖이면 고르지 않고 `None` 을 돌려줍니다. 라벨이 비어 있거나 `고시금액` 처럼 해석 항이 없어 구간을 알 수 없을 때만 후보 하나를 그대로 씁니다. 그 밖의 복수·불일치 상황은 모두 `None` 입니다.

---

## 3. 방법

### 3.1 합성 구간 표 시험

추정가격 구간이 3개(5억 미만 / 5억 이상 10억 미만 / 10억 이상)인 별표를 합성해, 배점한도 표와 구간별 평점 계산식에서 후보를 뽑고 추정가격으로 하나를 고르는 경로를 시험으로 고정했습니다. 실제 별표 9 픽스처(2구간)와 함께 양 끝 구간, 경계 포함 여부, 단일 후보 불일치를 각각 검사합니다.

### 3.2 표본 회귀

B1·H2 와 동일한 SQL·동일 시드(`h1pilot20261013`)로 500건을 뽑고 첨부 529건을 나라장터에서 다시 받았습니다(요청 간 1초). `scripts/pilot_past_notice_method_extract.py` 는 `parse_price_formula`/`parse_price_limit` 의 후보를 그대로 집계하며 `select_band` 를 호출하지 않습니다. 즉 이번 변경(선택 단계)은 이 집계 경로에 영향을 주지 않으므로, 재측정은 표본 동일성과 기준선 재현을 확인하는 절차입니다.

---

## 4. 결과

### 4.1 합성 시험

`tests/test_extract_score_params.py` 에 다음을 추가했습니다.

| 시험 | 확인 내용 |
| --- | --- |
| `test_parse_band_terms_reads_both_ends` | 양 끝 구간 문구에서 두 금액 항 추출 |
| `test_parse_band_terms_reads_single_bound_and_absence` | 단일 경계, 부등호 없는 금액·고시금액 라벨은 항 없음 |
| `test_band_matches_two_sided_range` | 7억은 맞음, 4.9억·15억은 아님 |
| `test_band_matches_boundary_operators` | 이상/초과/이하/미만 경계 포함 판정 |
| `test_select_band_picks_b_from_synthetic_three_band_table` | 3구간 표에서 7억 → B 65(5억 이상 10억 미만) |
| `test_select_band_picks_k_from_synthetic_three_band_table` | 3구간 표에서 15억 → k 1(10억 이상) |
| `test_select_band_rejects_contradicting_single_candidate` | 단일 후보가 추정가격과 어긋나면 None |
| `test_select_band_keeps_uninterpretable_single_candidate` | 라벨 없는 단일 후보는 유지 |

### 4.2 표본 재측정 (수정 후)

| 지표 | 수치 |
| --- | ---: |
| 판독 가능 431건 기준 B | 25 |
| k | 23 |
| B·k 동시 | 23 |
| T | 164 |
| T·B·k 전량 | 17 |

결과 분류는 전량추출 17, 부분추출 155, 표해석실패 259, 첨부없음 61, 판독불가형식 6, 스캔PDF 2 입니다.

---

## 5. 회귀 검증

B1(`bk_extract_improve_20261013.md`)의 수정 후 수치와 이번 재측정이 **전 항목 동일**합니다.

| 지표 | B1(수정 후) | 이번 작업 | 증감 |
| --- | ---: | ---: | ---: |
| 판독 가능 | 431 | 431 | 0 |
| 기준명 | 248 | 248 | 0 |
| T | 164 | 164 | 0 |
| B | 25 | 25 | 0 |
| k | 23 | 23 | 0 |
| B·k 동시 | 23 | 23 | 0 |
| T·B·k 전량 | 17 | 17 | 0 |

- 후보 생성 함수(`parse_price_formula`, `parse_price_limit`)는 손대지 않았습니다. 표본 CSV 는 같은 후보 집합에서 재계산됩니다.
- 선택 단계(`select_band`)는 표본 집계 경로가 아니라 API 추출기(`_apply_documents`)가 쓰는 값이며, 이번 변경은 합성 시험으로 고정했습니다.
- 표본 재측정은 표본·첨부가 B1 과 동일함을 확인하고 기준선을 재현하는 절차로, B·k·T 어느 지표도 실패로 바뀌지 않았습니다.

---

## 6. 한계

1. **고시금액 라벨**: `추정가격 고시금액 이상/미만` 은 연도별 고정금액이라 문서만으로 수치 비교를 하지 않습니다. 이 경우 낙찰방법 문구 일치에만 의존하며, 문구가 없으면 선택하지 않습니다.
2. **라벨 부재**: 바이너리 HWP 에서 구간 라벨 행이 복원되지 않으면 B·k 후보 라벨이 비어, 선택은 후보 하나일 때만 가능합니다. 이는 표 파서 영역입니다.
3. **문구 축 불일치**: 기준비율 라벨(고시금액 기준)과 배점한도 라벨(5억원 기준)의 축이 다를 수 있어, 확정 불가 시 `None` 과 후보·사유를 남기는 K1 정책을 유지합니다.

---

## 7. 검증 및 재현

```sh
uv run pytest tests/test_extract_score_params.py tests/test_pilot_past_notice_method_extract.py -q
uv run pytest tests/ -q -m 'not data_assets'
uv run mypy src
python3 scripts/validate_agent_rules.py --quiet
```

표본 재현(첨부는 커밋하지 않음):

```sh
uv run python scripts/db_readonly_query.py \
    --sql-file .cache/past_notice_pilot/sample.sql --format json --limit 500 \
    > .cache/past_notice_pilot/sample_raw.json
uv run python scripts/pilot_past_notice_method_extract.py \
    --sample .cache/past_notice_pilot/sample_raw.json --out-dir .cache/past_notice_pilot
```

수치는 결과 CSV 에서 재계산합니다.

```sh
uv run python - <<'PY'
import csv
rows = list(csv.DictReader(open('.cache/past_notice_pilot/sample_extract_results.csv', encoding='utf-8')))
print('판독 가능', sum(1 for r in rows if int(r['readable_count']) > 0))
print('B', sum(1 for r in rows if r['max_price_score']))
print('k', sum(1 for r in rows if r['multiplier']))
print('B·k 동시', sum(1 for r in rows if r['max_price_score'] and r['multiplier']))
print('T·B·k', sum(1 for r in rows if r['pass_threshold'] and r['max_price_score'] and r['multiplier']))
PY
```
