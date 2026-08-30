# Servc Champion 유효 OOS 고정 평가 하네스 사양

> **작성일**: 2026-08-30
> **버전**: v1.0.0
> **구현 파일**: `scripts/eval_servc_oos_champion.py`
> **테스트 파일**: `tests/test_eval_servc_oos_champion.py`
> **관련 스크립트**: `scripts/eval_servc_api_path.py`, `scripts/eval_servc_interval_by_group.py`

---

## 개요

본 문서는 Servc 현 Champion 모델(기본값: `servc_institution_v1`)을 3,589건 유효
OOS(Out-of-Sample) 고정 표본으로 평가하는 하네스의 공식 사양입니다.

OOS 표본 집합의 정의, 행 키 결박 방식, 평가 지표 계산 정의, 판정 스키마를
코드와 함께 확정합니다.

**실측 평가 실행(서빙 모델 로드)은 이 하네스를 사용하는 측에서 수행합니다.**
이 Task에서 제공하는 것은 하네스 코드, OOS 표본 정의, 결과 스키마, 테스트입니다.

---

## 1. OOS 표본 집합 정의

### 1.1 컷오프 기준

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 컷오프 타임스탬프 | `2026-08-03 11:00:00` | feature store parquet 동결 시점 |
| 정본 표본 수 | **3,589건** | 컷오프 이후 필터 통과 실측 건수 |
| 업무구분 | `Servc` | 용역 업무구분 고정 |

컷오프는 학습 데이터(`data/feature_store/dataset_Servc.parquet`)가 마지막으로
갱신된 시각입니다. 이 시각 이후에 개찰된 건은 학습 표본에 포함되지 않습니다.

### 1.2 필터 단계 (S0~S5)

```
S0: category = 'Servc'  AND  rl_openg_dt > '2026-08-03 11:00:00'
S1: sucsf_bid_rate IS NOT NULL
S2: 70.0 <= sucsf_bid_rate <= 110.0
S3: sucsf_bid_amt IS NOT NULL
S4: bid_announcements 와 3-key 조인 성공
        (bid_ntce_no, lpad(bid_ntce_ord, 3, '0'), category)
S5: 100,000 <= presmpt_prce <= 1,000,000,000,000
```

**S0**: 컷오프 이후 개찰된 용역 결과만 포함합니다.

**S1 + S2**: 낙찰률 비결측 및 유효 범위 `[70, 110]`은 `src/ml/dataset.py`의
`MIN_WINNING_RATE` / `MAX_WINNING_RATE` 상수를 그대로 사용합니다. 학습 필터와
동일한 정의를 쓰는 것이 판정 목적(학습 범위 내 성능)이고, 전량 보고 목적으로는
이 필터를 뺀 값도 함께 제공합니다.

**S3**: 낙찰금액 비결측. 이 필드가 없으면 추정가격 비율 계산이 불가합니다.

**S4**: `bid_announcements`와 3개 키로 조인해야 특징 생성에 필요한 공고 정보가
붙습니다. 조인 실패 건은 OOS 표본에 포함하지 않습니다. 차수(`bid_ntce_ord`)는
`bid_results`에 2자리(`00`), `bid_announcements`에 3자리(`000`)로 저장되어
있으므로 정규화(`lpad`)가 필수입니다. (`src/ml/dataset.py:141` 동일 정의)

**S5**: 추정가격 유효 범위 `[100,000, 1,000,000,000,000]`은
`src/ml/dataset.py`의 `MIN_PRESMPT_PRCE` / `MAX_PRESMPT_PRCE` 상수와 동일합니다.

### 1.3 결과 정렬

```
ORDER BY rl_openg_dt ASC, bid_ntce_no ASC, bid_ntce_ord ASC
```

결과 정렬은 재현성을 위한 것이며, SHA-256 해시는 정렬과 무관하게 행 키 집합으로
계산됩니다.

---

## 2. 행 키 집합 SHA-256 결박

### 2.1 행 키 형식

```
{bid_ntce_no}:{bid_ntce_ord_3digits}:{category}
```

- `bid_ntce_ord`는 3자리 zero-padding 후 사용합니다 (`"1"` -> `"001"`).
- 구분자는 `:`(콜론)입니다.

### 2.2 해시 계산 방식

```python
def compute_sample_keys_sha256(sample_keys: list[str]) -> str:
    sorted_keys = sorted(str(k).strip() for k in sample_keys if str(k).strip())
    digest = hashlib.sha256()
    for key in sorted_keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
```

- 키 목록을 **사전순 정렬** 후 연결하여 해시를 계산합니다.
- 입력 순서와 무관하게 동일한 행 집합이면 항상 동일한 해시가 생성됩니다.
- 각 키는 UTF-8 인코딩 후 `\n`을 구분자로 추가합니다.

### 2.3 사용 목적

| 목적 | 설명 |
| --- | --- |
| 표본 고정 확인 | 실행마다 SHA-256이 다르면 표본이 변경된 것입니다 |
| 정본 검증 | 정본 SHA-256과 일치하면 동일한 표본입니다 |
| 감사 추적 | 결과 JSON에 해시를 기록하여 나중에 검증 가능합니다 |

---

## 3. 평가 지표 정의

### 3.1 기본 오차 지표

| 지표 | 정의 | 단위 | 출처 |
| --- | --- | --- | --- |
| MAE | `mean(|pred - actual|)` | %p | `scripts/eval_servc_api_path.py:166` |
| RMSE | `sqrt(mean((pred - actual)^2))` | %p | 같은 파일 :167 |
| Bias | `mean(pred - actual)` | %p | 같은 파일 :168 |
| Median AE | `median(|pred - actual|)` | %p | 같은 파일 :169 |
| hit_rate_05 | `mean(|pred - actual| <= 0.5)` | 비율 | 같은 파일 :170 |

### 3.2 오차 밴드 비율

```
ERROR_BANDS = (0.5, 1.0, 2.0, 3.0, 5.0)
```

각 밴드 `b`에 대해:
- `count`: `|pred - actual| <= b` 인 행 수
- `ratio`: count / 전체 행 수

키 이름: `within_{b}_pct` (예: `within_0.5_pct`, `within_1.0_pct`)

### 3.3 예측구간 지표

| 지표 | 정의 | 단위 |
| --- | --- | --- |
| coverage | `mean(low <= actual <= high)` | 비율 (명목 90%) |
| coverage_gap | `coverage - 0.90` | 비율 |
| median_interval_width | `median(high - low)` | %p |

`low`/`high` 컬럼이 없으면 세 지표 모두 `null`로 반환합니다.

---

## 4. 집단별 세부 지표

하한율(`lwlt_rate`) 보유/결측 집단으로 분리하여 지표를 계산합니다.

| 집단 키 | 조건 |
| --- | --- |
| `with_lwlt` | `is_lwlt_missing == False` |
| `missing_lwlt` | `is_lwlt_missing == True` |

`is_lwlt_missing` 판정: `announcement_feature_payload()` 에서 추출한
`lwlt_rate`가 `None`, `""`, `0`, `"0"` 중 하나이면 결측으로 판정합니다.

**참고**: 결측 집단의 낙찰률 IQR은 보유 집단의 약 14배(9.682 대 0.705)이므로
집단 간 MAE를 직접 비교하지 않습니다. 집단별 편향 방향과 피복률이 주요 관심사입니다.

---

## 5. 결과 스키마 (ORCA_SERVC_OOS_EVAL_V1)

```json
{
  "schema": "ORCA_SERVC_OOS_EVAL_V1",
  "version": "1.0.0",
  "evaluated_at": "<ISO 8601 UTC>",
  "dry_run": false,
  "canonical": true,
  "expected_sample_count": 3589,
  "actual_sample_count": 3589,
  "sample_count_diff": 0,
  "sample_keys_sha256": "<64-char hex>",
  "model_provenance": {
    "model_id": "servc_institution_v1",
    "model_dir": "<절대경로>",
    "weights_path": "<절대경로>/model.bin",
    "weights_sha256": "<64-char hex>",
    "weights_exist": true,
    "model_version": "<버전 또는 타임스탬프>",
    "objective": "quantile(0.5)"
  },
  "overall_metrics": {
    "sample_count": 3589,
    "mae": null,
    "rmse": null,
    "bias": null,
    "median_abs_err": null,
    "hit_rate_05": null,
    "accuracy_bands": {
      "within_0.5_pct": {"count": 0, "ratio": 0.0},
      "within_1.0_pct": {"count": 0, "ratio": 0.0},
      "within_2.0_pct": {"count": 0, "ratio": 0.0},
      "within_3.0_pct": {"count": 0, "ratio": 0.0},
      "within_5.0_pct": {"count": 0, "ratio": 0.0}
    },
    "coverage": null,
    "coverage_gap": null,
    "median_interval_width": null
  },
  "group_metrics": {
    "with_lwlt": { "<overall_metrics 동일 구조>" },
    "missing_lwlt": { "<overall_metrics 동일 구조>" }
  },
  "skipped_count": 0,
  "sample_definition": "Servc bids with openg_dt > '2026-08-03 11:00:00', winning_rate in [70, 110], presmpt_prce in [100k, 1T], matched to bid_announcements"
}
```

### 5.1 판정 필드 의미

| 필드 | 의미 |
| --- | --- |
| `canonical` | `actual_sample_count == 3589` 이면 `true`. 표본 수가 다르면 `false`이고 차이값을 `sample_count_diff`에 표기 |
| `dry_run` | `true`이면 모델 로드 없이 표본 수집 및 해시 계산만 수행 |
| `sample_count_diff` | `actual - expected`. 양수는 더 많은 건수, 음수는 더 적은 건수 |

---

## 6. 승격 판정 통합 기준

본 하네스의 OOS 지표는 Champion/Challenger 비교에서 **운영 쌍대 검정 전** 보조 지표로
사용합니다. 단독으로 승격 판정에 쓰지 않습니다.

| 비교 구분 | 기준 |
| --- | --- |
| OOS MAE 차이 <= 0.0074 | 분할 산포 이내. 유의하지 않음 (`servc_split_variance_20260810.md`) |
| OOS MAE 차이 > 0.0074이고 3개 분할 일관 | 운영 쌍대 검정으로 진행 |
| 집단별 MAE가 한 집단에서 악화 | 회귀 가중 합산으로 판정 (건수 비중 고려) |

**두 지표(MAE, hit_rate_05)가 반대 방향으로 움직이는 경우는 실패가 아니라
중앙부-꼬리 맞바꿈의 발견입니다.** 판정 기준을 사전에 양방향으로 작성합니다.

---

## 7. 사용법

```bash
# 하네스 검증 (dry-run): 모델 없이 표본 수집/키 해시 검증
.venv/bin/python scripts/eval_servc_oos_champion.py --dry-run

# 정식 평가 실행: 서빙 모델 로드 후 결과 JSON 저장
.venv/bin/python scripts/eval_servc_oos_champion.py \
    --output data/benchmarks/servc_oos_champion_eval.json \
    --model-id servc_institution_v1
```

`--dry-run`은 DB 접속과 모델 파일이 없어도 표본 수 및 SHA-256 해시 검증을 수행합니다.
모델을 로드하는 실제 평가 실행은 주 저장소(main)에서 수행합니다.

---

## 8. 구현 파일 위치

| 파일 | 역할 |
| --- | --- |
| `scripts/eval_servc_oos_champion.py` | OOS 평가 하네스 메인 스크립트 |
| `tests/test_eval_servc_oos_champion.py` | 단위 테스트 (41개, DB/모델 불필요) |
| `docs/design/servc_oos_harness_spec.md` | 본 문서 (사양 정본) |
