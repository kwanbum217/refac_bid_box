# 용역 제도 플래그 3종 특징 추가 — 홀드아웃 판정

> **작성일**: 2026-08-11
> **상태**: 세 분할 홀드아웃 측정 완료. 운영 쌍대 검정 미수행, 승격 없음. **특징 추가는 되돌렸습니다**
> **결론**: MAE 부호는 세 분할 모두 개선 방향이나 **평균 차이 -0.0068 이 분할 산포 0.0074 안**입니다. 승격 지표인 0.5%p 적중률은 부호가 갈립니다. 판정 기준상 **분할 변동**이며 개선으로 기록하지 않습니다
> **남긴 것**: 이 문서와 재현 스크립트 2개. `src/ml/` 변경은 되돌렸습니다
> **선행**: [`servc_unused_rawdata_field_audit_20260811.md`](servc_unused_rawdata_field_audit_20260811.md), [`servc_2025_source_regime_shift_20260811.md`](servc_2025_source_regime_shift_20260811.md), [`servc_split_variance_20260810.md`](servc_split_variance_20260810.md)

---

## 1. 대상과 제외

미사용 제도 플래그 5개 중 **2025-01 체제 전환이 없는 것으로 확인된 3개**만 넣었습니다.

| 필드 | 잔차 편향 폭 | 최대 t | 연도 재현 | 이번 처리 |
| --- | ---: | ---: | --- | --- |
| `indstrytyLmtYn` | 0.42%p | +19.4 | 3/3 | **추가** |
| `cmmnSpldmdMethdNm` | 0.34%p | -11.6 | 3/3 | **추가** |
| `dsgntCmptYn` | 0.21%p | -5.2 | 3/3 | **추가** |
| `rbidPermsnYn` | 0.23%p | +10.1 | 미확인 | 제외. 2025-01 전환(74.3% -> 47.9%) |
| `prdctClsfcLmtYn` | 0.15%p | +7.4 | 3/3 | 제외. 2025-01 전환(90.5% -> 22.5%) |

제외한 둘은 전환 전후의 같은 수준이 다른 것을 가리킵니다. 한 범주로 섞으면 2024년 이전의 `Y` 와 2025년 이후의 `Y` 가 한 코드로 학습됩니다. 체제 지시자 설계가 선행돼야 합니다.

---

## 2. 데이터 조달

운영 파생 parquet(`dataset_Servc.parquet`, 917,629행 28컬럼)에는 세 필드가 **없습니다.** 전량 재생성은 비용이 크고 원본을 덮을 위험이 있으므로 다음 경로를 썼습니다.

```bash
uv run python scripts/build_servc_flag_dataset.py \
    --parquet <운영 parquet> \
    --output data/feature_store_flag_experiment/dataset_Servc_flags.parquet
```

원본은 읽기 전용으로 열고, `bid_announcements.raw_data` 에서 뽑은 플래그를 공고번호로 왼쪽 조인해 **다른 경로**에 31컬럼 parquet 을 새로 썼습니다. 원본 parquet, DB, 서빙 `model.bin` 은 변경하지 않았습니다.

### 2.1 채움률과 차수 충돌

| 필드 | 채움률 | 차수 간 값 충돌 |
| --- | ---: | ---: |
| `dsgnt_cmpt_yn` | 99.98% | 0.0131% |
| `cmmn_spldmd_methd_nm` | 99.52% | 0.4586% |
| `indstrty_lmt_yn` | 60.39% | 0.0269% |

원본 parquet 에 차수 컬럼이 없어 공고번호로만 붙일 수 있습니다. 같은 공고번호의 차수 사이에서 값이 갈리는 공고는 **결측으로 두었습니다.** 잘못된 값을 학습에 넣지 않기 위함이며, 해당 비율은 위 표대로 0.5% 미만입니다.

`indstrty_lmt_yn` 의 채움률 60.39% 는 감사 문서의 인상보다 낮습니다. 감사는 최신 30,000건 표본이었고 학습 표본은 10년 전체라 과거 구간의 미채움이 반영된 결과입니다.

### 2.2 학습 프레임에 실린 수준

| 필드 | 수준 수 | 상위 수준 |
| --- | ---: | --- |
| `indstrty_lmt_yn` | 3 | `Y` 500,393 / `미상` 363,459 / `N` 53,777 |
| `cmmn_spldmd_methd_nm` | 11 | `(없음)공동수급불허` 697,433 / `(전자)분담이행` 98,560 / `(전자)공동이행` 79,287 / `(전자)혼합방식` 30,883 / `미상` 4,428 |
| `dsgnt_cmpt_yn` | 3 | `N` 900,412 / `Y` 17,060 / `미상` 157 |

---

## 3. 구현 — 측정용으로 넣었다가 되돌렸습니다

측정 시점에는 `src/ml/` 에 실제로 넣고 학습을 돌렸습니다. 판정이 분할 변동으로 나온 뒤 그 변경을 되돌렸으므로 **현재 저장소에는 세 특징이 없습니다.** 어떻게 넣었는지를 남겨 두는 이유는 다시 열 근거가 생겼을 때 같은 설계를 반복하기 위함입니다.

### 3.1 인코딩은 기존 관례를 따랐습니다

세 필드 모두 **범주형**으로 넣었습니다. 새 인코딩 방식을 도입하지 않았고, 기존 `intrbid_yn`·`ppsw_gnrl_srvce_yn` 과 같은 처리입니다.

`*_missing` 지시자는 만들지 않았습니다. `lwlt_rate_missing` 이 필요한 이유는 수치형이 결측과 "값이 0" 을 구분하지 못하기 때문인데, 범주형은 결측을 `MISSING_CATEGORY`(`미상`) 라는 하나의 수준으로 이미 표현합니다. 여기에 0/1 지시자를 더하면 같은 정보를 두 번 넣게 됩니다.

### 3.2 학습과 추론이 같은 함수를 썼습니다

| 경로 | 진입점 | 확인 |
| --- | --- | --- |
| 학습 | `dataset.py` `INSTITUTION_FIELDS` -> parquet -> `features.build_default_feature_map` | 세 키를 `INSTITUTION_FIELDS` 단일 정의에 등록 |
| 추론 | `dataset.py` `announcement_feature_payload` -> `features.build_default_feature_map` | 같은 `INSTITUTION_FIELDS` 를 순회하므로 자동 반영 |

키 매핑이 한 곳에만 있어 train/serve skew 가 생길 자리가 없었습니다. 되돌리기 전 `tests/test_serving_feature_parity.py` 의 `test_announcement_payload_extracts_institution_fields` 와 `test_every_training_feature_is_servable` 이 두 경로를 각각 통과했습니다.

### 3.3 카테고리 격리

`features.py` 의 범주형 상수를 셋으로 나눴습니다.

| 상수 | 내용 |
| --- | --- |
| `BASE_CATEGORICAL_FEATURES` | 기존 11종. 전 카테고리 공통 |
| `SERVC_CATEGORICAL_FEATURES` | 이번 3종. 용역 전용 |
| `CATEGORICAL_FEATURES` | 위 둘의 합집합. dtype 복원과 `categorical_feature` 지정에 사용 |

`trainer.TRAINING_FEATURES` 는 기본 11종만 쓰고, 3종은 `SERVC_EXTRA_FEATURES` 로 용역에만 붙였습니다. 물품·건설 파생 parquet 은 구형 12컬럼이라 이 값이 없어, 공통으로 넣으면 상수 컬럼이 되면서 특징 계약만 바뀝니다.

### 3.4 되돌린 뒤의 재현 경로

`src/ml/` 을 원상 복구했으므로 `features.py` 는 세 플래그를 만들어 주지 않습니다. `scripts/eval_servc_flag_features.py` 가 그 자리를 대신합니다. parquet 에서 읽은 값을 `_coerce_category` 와 같은 규칙(결측·빈 문자열 -> `미상`)으로 접고, 수준을 정렬해 `apply_categorical_dtypes` 로 고정한 뒤 후보 특징 목록에만 더합니다. LightGBM 에 넘기는 `categorical_feature` 목록에도 포함시킵니다. 계산 자체는 되돌리기 전과 같습니다.

---

## 4. 홀드아웃 측정

`measure_servc_split_variance.py` 와 같은 운영 3단계 학습 경로입니다. 시간순 80/20 분할 -> 조기 종료로 트리 수 결정 -> 전량 재적합. champion 설정(`quantile(0.5)`, `num_leaves` 255)을 그대로 씁니다.

```bash
uv run python scripts/eval_servc_flag_features.py
```

기준은 특징 35종, 후보는 38종입니다. 시드는 42 고정이며 분할만 바꿉니다.

### 4.1 분할별 결과

| 검증연도 | 학습행 | 검증행 | 기준 MAE | 후보 MAE | MAE 차이 | 기준 적중% | 후보 적중% | 적중 차이 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | 570,693 | 98,714 | 1.2759 | 1.2582 | **-0.0177** | 63.2534 | 63.4044 | +0.1509 |
| 2024 | 669,407 | 95,743 | 1.2393 | 1.2387 | -0.0006 | 62.7931 | 62.9602 | +0.1671 |
| 2025 | 765,150 | 96,141 | 1.2416 | 1.2394 | -0.0022 | 62.3033 | 62.2086 | **-0.0947** |

편향은 2023 -0.1761 -> -0.1837, 2024 -0.1276 -> -0.1324, 2025 -0.0460 -> -0.0427 입니다.

### 4.2 산포

| 값 | 결과 |
| --- | ---: |
| MAE 차이 평균 | **-0.0068** |
| MAE 차이 표준편차 | **0.0094** |
| 적중 차이 평균 | +0.0745%p |
| MAE 부호 일관 | 예 (3/3 개선 방향) |
| 적중 부호 일관 | **아니오** |

---

## 5. 판정

판정 기준은 `docs/servc_model_status.md` 5장이며 측정 전에 고정했습니다.

| 기준 | 이번 결과 | 판정 |
| --- | --- | --- |
| 홀드아웃 차이가 0.0074 이내면 분할 변동 | 평균 -0.0068 | **걸림** |
| 분할마다 부호가 갈리면 기각 | MAE 일관, **적중률 갈림** | **걸림** |
| 통과해도 이번 Task 에서 승격 금지 | - | 승격 없음 |

**분할 변동입니다. 개선이라 쓰지 않습니다.**

두 가지를 함께 봐야 합니다.

첫째, **평균 차이보다 산포가 큽니다.** 표준편차 0.0094 가 |평균| 0.0068 을 넘습니다. `servc_split_variance_20260810.md` 의 표현대로 이 크기의 홀드아웃 이득은 읽을 수 없습니다.

둘째, **평균을 만든 것은 2023 분할 하나입니다.** -0.0177 하나가 끌었고 2024·2025 는 -0.0006 과 -0.0022 로 시드 산포 0.0010 수준입니다. 최근 두 분할에서 기여가 사실상 0 이라는 것이 더 중요한 사실입니다. 운영이 겨냥하는 구간은 최근이기 때문입니다.

셋째, **승격 지표에서 부호가 갈립니다.** 승격 판정은 0.5%p 적중률로 하는데 2023·2024 는 +0.15%p 대이고 2025 는 -0.09%p 입니다. 네 칸 중 "MAE 개선 x 적중 악화" 가 최근 분할에서 나왔습니다.

### 5.1 왜 잔차 편향이 MAE 로 오지 않았는가

감사 문서 4.1 이 잰 것은 **집단 평균 잔차**입니다. 이번에 확인된 것은 그 편향이 재현성이 높아도 MAE 로 옮겨지지는 않는다는 사실이며, 이는 잔차 후처리 다섯 축이 닫힌 것과 같은 형태입니다. 편향 폭 0.1~0.31%p 를 트리가 교정해도 개별 행의 절대오차는 그만큼 줄지 않습니다. 감사 문서 5장 유보 1번이 그대로 확인된 셈입니다.

---

## 6. 처리와 다음 단계

**특징 추가는 되돌렸습니다.** 판정 기준을 세워 둔 이유가 이 크기의 이득을 걸러 내기 위해서입니다. 되돌리지 않고 병합했다면 다음 정기 재학습에서 세 특징이 쌍대 검정 없이 운영 모델에 실렸을 것입니다.

| 대상 | 처리 |
| --- | --- |
| `src/ml/features.py`, `src/ml/dataset.py`, `src/ml/trainer.py` | **되돌림** |
| `tests/test_serving_feature_parity.py`, `tests/test_retrain_pipeline_e2e.py` | **되돌림** |
| 이 문서, `scripts/build_servc_flag_dataset.py`, `scripts/eval_servc_flag_features.py` | 남김 |
| 운영 쌍대 검정 | **보내지 않습니다.** 판정 기준 1 에 걸렸습니다 |

남은 축입니다.

| 축 | 상태 |
| --- | --- |
| `rbidPermsnYn`, `prdctClsfcLmtYn` | 다른 섹션의 2025-01 체제 지시자 판정이 선행돼야 합니다 |
| 이 세 플래그 재시도 | 새 근거 없이 다시 열지 마십시오. 3.4 의 경로로 같은 측정을 반복할 수 있습니다 |

### 6.1 다시 열 조건

두 가지 중 하나가 성립할 때만 가치가 있습니다.

1. **최근 분할에서 기여가 커질 때.** 지금은 2024 -0.0006, 2025 -0.0022 로 시드 산포 0.0010 수준입니다. `indstrty_lmt_yn` 채움률이 과거 구간 때문에 60.39% 인데, 최근 구간만으로 학습 표본이 채워지면 달라질 수 있습니다
2. **다른 형태로 넣을 때.** 무조건부 범주가 아니라 체제 지시자나 다른 특징과의 상호작용으로 넣는 설계는 이번 측정이 다루지 않았습니다

---

## 7. 검증

특징을 넣은 상태와 되돌린 상태에서 각각 돌렸습니다.

| 항목 | 명령 | 넣은 상태 | 되돌린 상태 |
| --- | --- | --- | --- |
| 테스트 전량 | `uv run pytest tests/ -q` | 823 passed, 4 skipped, 2 failed | 823 passed, 4 skipped, 2 failed |
| 린터 | `uv run ruff check .` | All checks passed | All checks passed |
| 규칙 정합성 | `uv run python scripts/validate_agent_rules.py` | 6/6 통과 | 6/6 통과 |

실패한 둘은 `test_model_bin_files_exist` 와 `test_chroma_db_exists` 입니다. 격리 작업 트리에는 `data/model_files/*/model.bin` 과 `chroma_db` 가 없어 **정상적으로 실패하는 항목**이며 이번 작업과 무관합니다.

| 항목 | 결과 |
| --- | --- |
| 원본 parquet 변경 | 없음. 읽기 전용 |
| DB 변경 | 없음. `SELECT` 만 실행 |
| 서빙 `model.bin` 변경 | 없음 |
| 승격 | 없음 |
| `src/ml/` 최종 상태 | 되돌림. 병합해도 운영 경로가 바뀌지 않습니다 |
| 신규 Python 라이브러리 | 없음 |
| 운영 쌍대 검정 | **미수행.** 판정 기준 1 에 걸려 보내지 않았습니다 |

---

## 8. 재현

```bash
DATABASE_URL=... uv run python scripts/build_servc_flag_dataset.py \
    --parquet data/feature_store/dataset_Servc.parquet \
    --output data/feature_store_flag_experiment/dataset_Servc_flags.parquet

uv run python scripts/eval_servc_flag_features.py \
    --parquet data/feature_store_flag_experiment/dataset_Servc_flags.parquet
```

플래그 조회는 약 219초, 특징 프레임 생성은 약 351초, 학습 6회는 약 258초입니다.
