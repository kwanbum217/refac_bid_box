# Drift Baseline 출처와 버전 결정용 조사 보고서 (R-14 착수 조건)

> **작성일**: 2026-09-06
> **Task**: task_c6c02b30d313 (조사 전용, 코드·설정·ml_registry 변경 없음, 학습·승격 없음)
> **정본**: `.orca/capsules/task_c6c02b30d313/capsule.yaml`
> **산출물**: 본 문서 1건 (`docs/analysis/drift_baseline_source_survey_20260906.md`)

---

## 1. 현재 baseline 부재 상태의 실체 (코드 근거)

### 1.1 baseline은 학습 성공 경로에서만 생성되는 구조입니다

- 정의: `src/ml/monitoring.py:130-137`의 `save_baseline_distributions`가 `target_dir/feature_distributions_v1.json`과 `target_dir/metadata.json`을 저장합니다. payload에는 `schema_version, model_name, model_version, created_at, training_samples, features, excluded_features, psi_config`가 들어가고, `lwlt_rate_missing` 컬럼이 있으면 `by_lwlt_missing` 키로 `0.0`/`1.0` 집단 분리 분포가 추가됩니다(`src/ml/monitoring.py:157-185`).
- 유일하게 배선된 호출자(허용 범위 내 전수 확인): `src/ml/trainer.py:511-517`의 `ModelTrainer.train_and_register` 내부 staging 저장이며, 이후 `shutil.move`와 `_update_baseline_atomically`(`src/ml/trainer.py:519-551`)로 `ml_registry/{model_name}/baseline/`에 원자 반영됩니다.
- 호출자 전수 확인 방법: 허용 범위 파일 전체에 `rg "save_baseline_distributions|load_baseline_distributions|feature_distributions_v1"`를 실행한 결과, 정의(`monitoring.py`)와 호출(`trainer.py:511`) 외의 배선된 호출자는 없습니다. 허용 범위 밖(CLI, 스크립트, Arq 태스크 등)에 외부 진입점이 있는지는 **미확인**입니다.

### 1.2 현재 baseline이 하나도 없는 것이 실측으로 확인됩니다

- `rg --files ml_registry` 전체 목록에 `baseline/` 디렉터리와 `feature_distributions_v1.json`이 0건입니다.
- Servc 현 Champion 디렉터리 `ml_registry/servc_institution_v1/v_20260807_110637_435/`에는 `paired_verdict.json` 1건만 있고, baseline 아티팩트도 모델 `metadata.json`도 없습니다. 즉 현 Champion은 baseline 저장 로직이 생기기 전에 학습된 모델이라는 확정 사실과 일치합니다.
- Thng 쪽(`ml_registry/quantum_leap_v25_pro/`) 역시 버전 디렉터리 어디에도 baseline이 없습니다.

### 1.3 drift job이 꺼져 있는 것은 설계된 상태입니다

- `src/app/core/config.py:72-74`에서 `ML_DRIFT_MONITOR_ENABLED: bool = False`이며, 주석에 "초기 기동 시 baseline 분포 아티팩트 부재로 인한 오경보를 방지하기 위해 기본값은 비활성"이라고 명시되어 있습니다.
- `docs/context/current_state_facts.yaml`의 `drift_job` 사실(blocked)은 "baseline이 생길 때까지 꺼져 있으며 재학습 후 활성화를 대기"로 같은 판정입니다.
- `load_baseline_distributions`는 파일이 없으면 `None`을 반환합니다(`src/ml/monitoring.py:208-217`). baseline이 `None`일 때 drift 태스크가 어떻게 동작하는지는 허용 범위(스케줄 태스크 파일) 밖에 있어 **미확인**입니다.

### 1.4 조사 시점의 확인 한계 (미확인으로 기록)

- 격리 워크트리에서 DB 접속이 불가합니다. 읽기 전용 실행기로 승인된 형태 그대로 1건을 전면에서 실행한 결과 `Can't connect to MySQL server on '127.0.0.1'`로 실패했습니다. 따라서 레짐 전환 이후 실제 적재 행 수(선택지 2의 표본 충분성 판단에 필요)는 **미확인**입니다.
- 같은 이유로 Champion의 학습 구간·표본 수·범주 수준(`category_levels`) 소재도 **미확인**입니다. Servc 버전 디렉터리에 `metadata.json`이 없어 워크트리 내에서는 복원 가능 여부를 판정할 수 없습니다.

---

## 2. 학습 없이 baseline을 만들 수 있는지 판정 (함수 시그니처 근거)

대상 함수 시그니처 (`src/ml/monitoring.py:130-137`):

```python
def save_baseline_distributions(
    df_feat: pd.DataFrame,
    feature_columns: list[str],
    target_dir: Path | str,
    model_name: str,
    model_version: str,
    psi_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

판정은 다음과 같습니다.

- **함수 자체는 학습 상태에 의존하지 않습니다.** 인자는 특징 프레임(`df_feat`), 특징 목록, 저장 경로, 모델명, 버전 문자열, 선택적 PSI 설정뿐이며, `ModelTrainer` 인스턴스나 학습 산출물을 요구하지 않습니다. `build_feature_frame`으로 만든 프레임만 있으면 파이썬 한 줄로 직접 호출이 기술적으로 가능합니다.
- **그러나 허용 범위 내에 배선된 학습 외 호출 경로는 없습니다.** 확정된 호출 경로는 `trainer.py:511` 학습 성공 경로 하나뿐입니다. 즉 "학습 없이 baseline을 만드는 승인된 경로"는 코드에 존재하지 않습니다.
- 직접 호출을 택한다면 호출자가 직접 책임져야 할 것은 (a) `src/ml/dataset.py:152-174`의 `build_training_dataset` 구간 조회 + `build_feature_frame` + `apply_categorical_dtypes`로 Champion 학습 때와 동일한 프레임 재현, (b) `model_version` 스탬프 값 결정(존재하지 않는 버전을 찍으면 provenance가 깨집니다), (c) `ml_registry/{model_name}/baseline/` 반영 시 원자성(`_update_baseline_atomically` 상당)입니다. (a)의 Champion 범주 수준 소재는 1.4절과 같이 **미확인**입니다.

---

## 3. 세 선택지별 분석

공통 전제(재조사 없이 확정 사실로 사용): 2026-05-26 낙찰하한율 2%p 일괄 인상 레짐 전환이 있었고 현 학습 데이터는 전부 구 제도 기준입니다. 낙찰하한율은 낙찰률과 Spearman 0.71로 가장 강한 신호이며(`src/ml/dataset.py` 주석), `features.py:32`의 `REGIME_SHIFT_DATE`와 `is_post_regime_shift` 특징(`src/ml/features.py:272`)이 코드에 이미 있습니다.

감시 수치 공통 조건: 기본 임계값 0.2, 결측 집단 완화 임계값 0.25, 집단별 최소 표본 100건(`src/ml/psi.py:14-16`, `src/ml/monitoring.py:53-61`), 평가 윈도우 7일(`src/ml/monitoring.py:381`, `docs/ops/psi_drift_monitoring.md` 2장).

| 선택지 | 필요 조건 | 사용 코드 경로 | 위험 | 오탐 상시 발화 가능성 | 레짐 전환의 영향 |
| --- | --- | --- | --- | --- | --- |
| 1) 현 Champion 학습 구간으로 사후 생성 | Champion 학습 구간 재현용 데이터 접근, Champion 범주 수준 확보, 스탬프할 버전 결정, 코디네이터 승인 | `save_baseline_distributions` 직접 호출 + `build_training_dataset` 구간 조회 + `build_feature_frame` | 승인되지 않은 우회 경로로 provenance가 깨짐. baseline_version을 무엇을 찍을지(존재하지 않는 버전이면 거짓 이력) 결정 필요 | **높음.** baseline 자체가 구 제도 분포이므로, 신 제도 하의 정상 데이터가 들어오는 즉시 `lwlt_rate`·`is_post_regime_shift` 등에서 PSI가 임계를 넘어 DRIFT_DETECTED가 상시 발화할 가능성이 큼 | 레짐 전환을 감지해야 할 신호가 오히려 baseline 오염으로 전락. 전환 이후의 정상이 전부 이상으로 판정됨 |
| 2) 레짐 전환 이후 구간만으로 생성 | 전환 이후(2026-05-26 이후) 구간의 충분한 표본(집단별·특징별 100건 이상, 7일 윈도우 기준), 스탬프 버전 결정, 코디네이터 승인 | 선택지 1과 같은 직접 호출 경로에 `start_at="2026-05-26"` 구간 필터(`src/ml/dataset.py` 지원)를 적용 | 전환 이후 표본이 얇으면 집단별 `INSUFFICIENT_DATA`가 지속되어 감시가 사실상 불능. 현 Champion(구 제도 학습)과 baseline(신 제도)의 기준 불일치로 Champion 성능 저하와 분포 드리프트 신호가 뒤섞임 | **낮음(표본이 충분하다는 전제 하).** baseline이 신 제도 기준이므로 정상 운영 데이터는 STABLE에 머물 가능성이 큼. 단 표본 부족 시에는 오탐이 아니라 감시 불능 | 레짐에 정합한 선택. 다만 Champion 자체가 구 제도로 학습된 모델이므로, 분포는 STABLE이어도 예측값은 편향될 수 있음. 분포 감시와 모델 성능 감시는 다른 축임을 구분해야 함 |
| 3) 다음 재학습까지 대기 | 재학습 실행 결정(별도 Task). baseline 승인 절차는 학습 산출물 승인에 통합 | 기존 배선 그대로: `train_and_register` → staging baseline → `_update_baseline_atomically` → `ML_DRIFT_MONITOR_ENABLED` 활성화 | 드리프트 가시성 공백이 재학습 때까지 지속. 재학습 데이터가 여전히 구 제도 위주라면 선택지 1의 문제가 학습 산출물로 고착됨 | **없음(감시 자체가 꺼져 있으므로).** 대신 실제 드리프트를 놓치는 미탐 비용이 있음 | 재학습 데이터 구간 정책과 함께 결정해야 함. 신 제도 데이터가 충분히 쌓인 뒤 재학습하면 baseline도 자연히 신 제도 기준이 되어 선택지 2의 효과를 정식 경로로 얻음 |

### 3.1 옛 baseline 호환 분기의 의미

`check_dataset_drift`는 baseline에 `by_lwlt_missing` 키가 있으면 집단 분리 평가를, 없으면 단일 집단 평가로 폴백합니다(`src/ml/monitoring.py:406-410`, `542-561`). 따라서 사후 생성(선택지 1·2) 시 `lwlt_rate_missing` 컬럼을 포함한 프레임으로 만들면 신 형식, 제외하면 구 형식 baseline이 됩니다. Servc는 결측 집단이 별도 모집단임이 기각 판정으로 확정되어 있으므로(`current_state_facts.yaml`의 `servc_lwlt_imputation` rejected), Servc baseline에는 분리 형식을 쓰는 것이 정합합니다.

---

## 4. 권고안 (실행하지 않음)

**권고: 선택지 3(다음 재학습까지 대기)을 채택하고, 재학습 데이터 구간 정책과 함께 baseline 출처·버전을 승인하십시오.**

권고 근거(코드와 확정 사실のみ):

1. 선택지 1은 baseline에 구 제도 분포를 새기는 것으로, 2%p 인상 이후 정상 유입을 상시 DRIFT_DETECTED로 만들 가능성이 큽니다. 오탐이 상시 발화하는 감시는 운영자가 알림을 무시하게 되어 감시 공백과 같은 결과에 이릅니다.
2. 선택지 2는 방향은 맞으나 두 가지가 미해결입니다. 전환 이후 표본 충분성이 DB 접속 불가로 **미확인**이며, Champion 범주 수준 소재가 **미확인**이라 프레임을 Champion과 동일하게 재현할 수 있다는 보장이 없습니다.
3. 선택지 3은 이미 설계된 대기 상태입니다. `ML_DRIFT_MONITOR_ENABLED=False` 기본값과 그 주석(`src/app/core/config.py:72-74`), `drift_job` blocked 사실이 "baseline이 생길 때까지 꺼둔다"는 설계를 가리키고 있습니다. 대기 자체가 장애가 아니라 정합 상태입니다.
4. 단, 재학습 시 데이터 구간이 여전히 구 제도 위주라면 선택지 1의 문제가 정식 산출물로 고착되므로, 재학습 착수 조건에 "신 제도 구간 최소 표본 기준"을 함께 두는 것을 권고합니다. 기준 수치(집단별 100건)는 코드 상수에서 가져오되, 최종 승인 수치는 코디네이터 결정 사항으로 남깁니다.

위 권고의 전제 중 미확인 사항: 전환 이후 실제 적재 행 수, Champion 학습 구간·표본 수, Champion 범주 수준 소재, baseline이 `None`일 때 drift 태스크의 동작.

---

## 5. `missing_lwlt_intervals` 과제와의 묶음·분리 판단

**판단: 분리하십시오. 단 집단 정의(`lwlt_rate_missing` 0.0/1.0 키)는 공유하십시오.**

근거:

- `missing_lwlt_intervals`는 예측구간(Conformal interval) 품질 과제입니다. 구간 학습은 `trainer.py:468-477`의 `_train_quantile_models` 경로이며, baseline 결정은 입력 분포 참조점(`monitoring.py`) 문제입니다. 코드 경로와 승인 기준(acceptance)이 다릅니다. 한 Task로 묶으면 baseline 버전 결정이 지연될 때 구간 품질 작업까지 함께 막히고, 역도 마찬가지입니다.
- 분리하되 연결점은 유지합니다. `current_state_facts.yaml`에서 `missing_lwlt_intervals`는 active(MAE 2.0943, 결측 집단 전용 예측구간 관리 추진)이며, `servc_lwlt_imputation`은 rejected(결측 집단은 별도 모집단)입니다. baseline 쪽의 `by_lwlt_missing` 분리 평가(`SUBGROUP_KEY_WITH_LWLT="0.0"`, `SUBGROUP_KEY_MISSING_LWLT="1.0"`, 임계값 0.2/0.25)는 같은 "별도 모집단" 인식을 공유하므로, 두 Task는 집단 키 정의와 임계값을 공통으로 쓰되 실행·승인은 분리하는 것이 정합합니다.
- drift 감시에서 `missing_lwlt_only` 라벨(`src/ml/monitoring.py:504-505`)이 붙는 조건과 예측구간 품질 저하 조건은 서로의 트리거가 될 수 있으나, 자동 연결(드리프트→재학습→구간 재생성)은 인간 개입 원칙(`docs/ops/psi_drift_monitoring.md` 6장: 자동 재학습·승격 금지)에 따라 두지 마십시오.

---

## 6. 미확인 항목 목록

1. 허용 범위 밖(CLI, 스크립트, Arq 태스크)에 `save_baseline_distributions`의 학습 외 진입점이 있는지.
2. baseline이 `None`일 때 drift 태스크의 동작(건너뜀/경고/실패).
3. 2026-05-26 이후 실제 적재 행 수와 집단별 표본 규모(DB 접속 불가로 미측정).
4. 현 Champion의 학습 구간·표본 수·범주 수준 소재(Servc 버전 디렉터리에 `metadata.json` 없음).
5. 다음 재학습 예정 시점과 데이터 구간 정책(R-14 상위 계획 사항으로 본 조사 범위 밖).

---

## 7. 실행한 확인 명령 (읽기 전용, 변경 없음)

- `rg -n "save_baseline_distributions|load_baseline_distributions|feature_distributions_v1|check_dataset_drift|ML_DRIFT_MONITOR_ENABLED|drift_monitor" <허용 범위 파일들>`: 호출자는 `trainer.py:511` 1건, 정의는 `monitoring.py`, 설정 기본값 OFF는 `config.py:74`를 확인.
- `rg --files ml_registry`: `baseline/` 디렉터리와 `feature_distributions_v1.json` 0건을 확인. Servc 버전 디렉터리에는 `paired_verdict.json`만 존재.
- `uv run python scripts/db_readonly_query.py --sql "SELECT category, ... FROM bid_results GROUP BY category"`: 승인된 읽기 전용 형태 그대로 실행, MySQL 접속 거부로 실패. 표본 규모는 미확인으로 기록.
- `python3 scripts/validate_agent_rules.py --quiet`: 결과는 worker_done.json의 verification에 기록.
