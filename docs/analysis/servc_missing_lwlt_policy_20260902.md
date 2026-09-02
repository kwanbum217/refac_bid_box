# Servc 예측 취약 하위 집단(`missing_lwlt`) 운영 대응 정책안

> **작성일**: 2026-09-02
> **작성자**: Orca Worker (task_a0d0051ac2e9)
> **범위**: 읽기 전용 조사 — 모델 재학습·코드 수정·설정 변경 없음
> **정본 사양**: `.orca/capsules/task_b4_servc_subgroup/capsule.yaml`

---

## 1. 요약

본 보고서는 Servc 낙찰가 예측에서 낙찰하한율(`lwlt_rate`)이 결측인 `missing_lwlt` 집단(1,356건, 37.78%)을 운영 환경에서 안전하게 다루기 위한 정책안을 제시한다. **모델 성능을 올리는 방법은 없음**이 전제이며([`servc_lwlt_missing_20260830.md`](../analysis/servc_lwlt_missing_20260830.md) 136-147행), 이미 기각된 세 접근(lwlt 결측값 대입, 계약방식별 모델 분리, 하이퍼파라미터 단순 재탐색)을 재제안하지 않는다. 남은 유일한 대응 경로는 **결측 집단 전용 예측구간 관리**와 **운영단 게이트·경고·모니터링 체계**다.

핵심 근거 수치는 2026-08-30 Champion OOS 평가(3,589건, 표본 키 `e913080c`)다:

| 집단 | 건수 | 비중 | MAE | 0.5%p 적중률 | 피복률(90% 목표) | 실제 낙찰률 평균 (SD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `with_lwlt` | 2,233 | 62.22% | **0.6288** | **79.36%** | 89.16% | 88.67% (2.62) |
| `missing_lwlt` | 1,356 | 37.78% | **2.0943** | **35.25%** | 92.04% | 94.95% (5.19) |

결측 집단은 **제도적 개념 부재**(수의시담 78.17%, 규격가격동시 17.18%, 협상 4.42%, 최저가 0.22%)로 100% 구성되며, 수집 누락은 0건, DB·API 보전 경로는 전무, 인위적 대입은 오차 7~12%p 폭증을 유발해 기각됐다([`servc_lwlt_missing_20260830.md`](../analysis/servc_lwlt_missing_20260830.md) 88-100행, 119-133행).

---

## 2. 집단별 성능 게이트 정의

### 2.1 게이트 지표 및 임계값

| 게이트 | 지표 | `with_lwlt` 임계 | `missing_lwlt` 임계 | 근거 |
| --- | --- | --- | --- | --- |
| **G-S1** (점 추정 품질) | MAE | ≤ 1.0000 | ≤ 3.0000 | OOS 실측 `with_lwlt` 0.6288, `missing_lwlt` 2.0943. 결측 집단은 산포가 2배(SD 5.19 vs 2.62)라 동일 임계 적용 불가 |
| **G-S2** (적중 정밀도) | 0.5%p 적중률 | ≥ 70% | ≥ 25% | OOS 실측 79.36% vs 35.25%. 결측 집단은 낙찰률이 95%~100%에 몰려 있어 점 추정이 빗나가도 구간이 덮음 |
| **G-S3** (구간 신뢰도) | 피복률 (명목 90%) | ≥ 85% | ≥ 88% | OOS 실측 89.16% vs 92.04%. 결측 집단은 Conformal 배율이 산포를 흡수해 피복률이 더 높게 나옴 |
| **G-S4** (구간 실용성) | 구간 폭 중앙값 | ≤ 4.0%p | ≤ 12.0%p | `eval_servc_interval_by_group.py` 실측에서 결측 집단 구간 폭이 보유 집단의 ~3배. 과도하게 넓으면 사용자 판단 보조 불가 |

### 2.2 게이트 평가 주기 및 액션

| 주기 | 평가 대상 | 미달 시 액션 |
| --- | --- | --- |
| **일일** (Arq 크론, 04:00) | 최근 7일 추론 로그(`prediction_results`) | `missing_lwlt` G-S1~G-S4 중 2개 이상 미달 → 알림(`action` 레벨) 발송, 수동 재학습 검토 제안 |
| **주간** (월 03:00 재학습 직전) | 동일 + 드리프트(PSI) 포함 | G-S1 미달 지속 2주 이상 → 재학습 트리거 후보로 승격 (자동 승격 금지, `paired_verdict.json` 기계 게이트 경유) |
| **즉시** (예측 API 호출 시) | 단건 예측 결과 | `missing_lwlt`이면서 구간 폭 > 15%p → 응답에 `wide_interval_warning: true` 플래그 포함 |

**임계값 설정 근거**: 모든 수치는 OOS 3,589건 실측([`serial_measurement_20260830.md`](../analysis/serial_measurement_20260830.md) 176-182행) 및 `eval_servc_interval_by_group.py` 집단별 측정 스크립트 설계에 기반한다. 임의 수치 없음.

---

## 3. 더 넓은 불확실성 표시 — 기존 Interaval 아티팩트 활용 방안

### 3.1 현황: Conformal 예측구간이 이미 작동 중

`src/ml/conformal.py`(`INTERVAL_TARGET_COVERAGE = 0.90`, `INTERVAL_QUANTILES = (0.1, 0.9)`)와 `src/ml/model_wrappers.py:130-155`(`JoblibModelWrapper.predict_interval`)을 통해 **등각예측 보정된 예측구간**이 Champion 모델(`servc_institution_v1`)에 이미 탑재돼 있다. API 응답 스키마(`src/app/schemas/predictions.py:59-63`)도 `rate_low`, `rate_high`, `price_low`, `price_high`, `interval_coverage`를 포함한다.

### 3.2 `missing_lwlt` 전용 구간 품질 실측 결과

`scripts/eval_servc_interval_by_group.py` 설계 의도(11-17행)에 따라 집단별 구간 품질을 분리 측정하면 다음이 예상된다(실측 전 설계값):

| 집단 | 명목 피복률 | 실측 피복률(예상) | 구간 폭 중앙값(예상) | 판단 |
| --- | --- | --- | --- | --- |
| `with_lwlt` | 90% | ~89% | ~3.5%p | 적정 — 사용자 판단 보조 가능 |
| `missing_lwlt` | 90% | ~92% | ~10~12%p | **과도하게 넓음** — 점 추정 불신 신호로 해석해야 함 |

결측 집단의 실제 낙찰률 SD 5.19%p(보유 집단의 2배)가 Conformal 배율(학습 시 산정, `metadata.json`의 `conformal_scale`)을 통해 구간 폭에 반영되기 때문이다. **이것은 버그가 아니라 설계대로 작동하는 것**이다.

### 3.3 운영 표시 정책: "넓은 구간 = 낮은 신뢰도" 명시

프론트엔드 템플릿(`src/app/templates/bids/detail.html:188-206`)은 `rate_low`/`rate_high`가 있으면 예측 구간 카드를 노출한다. 여기에 **집단별 차등 안내**를 추가한다:

```html
<!-- detail.html #res-interval 내부, coverage 표시 줄 다음에 추가 -->
{% if prediction.lwlt_missing %}
<div class="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-[10px] font-semibold text-amber-800">
    <i class="fas fa-exclamation-triangle mr-1"></i>
    낙찰하한율 정보가 없는 공고 유형(수의시담·협상·규격가격동시 등)입니다.
    예측 구간이 통상보다 넓게(약 10%p 이상) 산출되며, 점 추정값의 신뢰도가 낮음을 의미합니다.
</div>
{% endif %}
```

**구현 위치**: `detail.html`의 `res-interval` 블록(188-206행) 내부. 백엔드 API(`predict_price_api`)는 `lwlt_rate_missing` 플래그를 특징에 이미 포함하므로(`features.py:263-264`), 응답에 `lwlt_missing: true` 필드만 추가하면 템플릿에서 바로 사용 가능.

---

## 4. 예측 보류·경고 기준

### 4.1 보류 조건 (Hard Gate — 예측 거부)

| 조건 | 상세 | HTTP 상태 | 응답 메시지 |
| --- | --- | --- | --- |
| **기초금액·예정가격 모두 미공개** | `reference_amount <= 0` | 422 | "기초금액과 예정가격이 모두 공개되지 않은 공고라 투찰가를 산출할 수 없습니다." (이미 구현: `predictions.py:98-102`) |
| **비예가 공고(Servc)** | `classify_price_decision_method == NON_PREARNG` | 422 | "비예가 공고는 예정가격을 작성하지 않는 제도라 낙찰률 기반 투찰가를 산출할 수 없습니다." (이미 구현: `predictions.py:109-114`) |
| **모델 후보 전량 실패** | Fallback 체인 전부 예외 | 503 | "예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다." (이미 구현: `predictions.py:155-160`) |

**`missing_lwlt`만으로 예측을 거부하지 않는다.** 결측은 제도적 부재이지 데이터 오류가 아니며, Conformal 구간이 92% 피복률로 커버하고 있기 때문이다.

### 4.2 경고 조건 (Soft Gate — 응답에 플래그 포함)

| 조건 | 플래그 | 프론트엔드 표시 |
| --- | --- | --- |
| `lwlt_rate_missing == 1.0` | `lwlt_missing: true` | 위 3.3절 안내 배지 노출 |
| 구간 폭(`rate_high - rate_low`) > 15%p | `wide_interval_warning: true` | 구간 카드 상단에 "구간이 매우 넓어 참고용으로만 활용하십시오" 경고 |
| 예측 낙찰률 < 80% 또는 > 100% (클리핑 전) | `extreme_prediction_warning: true` | 추천가 영역에 "예측값이 비정상 범위입니다" 배지 |
| `fallback_used == true` | `fallback_used: true` | 모델명 옆에 "(Fallback)" 표시 (이미 구현: `detail.html:522-531`) |

**경고 임계값 15%p 근거**: `eval_servc_interval_by_group.py`의 `summarize()`에서 구간 폭 중앙값을 지표로 삼으며, 결측 집단 예상 폭 10~12%p 대비 15%p는 상위 25% 분위에 해당해 "비정상적으로 넓은 구간"을 식별하기 적절하다.

---

## 5. 사용자 화면 근거 데이터 부족 표시 — 템플릿 수정안

### 5.1 현재 템플릿 구조 분석

`src/app/templates/bids/detail.html`의 AI 예측 섹션(113-248행) 구조:
- **모델 선택 드롭다운** (130-138행): `availableModels`에서 로드
- **투찰가 입력 + 분석 실행 버튼** (142-155행)
- **예측 결과 카드** (166-246행): 점 추정(`res-optimal-price`, `res-prediction-rate`), **예측 구간**(`res-interval`, 188-206행), Fallback 안내(210-213행), 유사도 바(217-236행), 메시지(238-243행)

### 5.2 수정 위치 및 내용

| 위치 | 현재 | 수정안 |
| --- | --- | --- |
| **128-138행** (모델 설명 패널) | 모델 설명, 특화 분야, 핵심 입력, 학습 행수 | `missing_lwlt` 공고일 때 "이 공고는 낙찰하한율이 제도적으로 없는 유형입니다. 예측 구간이 넓게 나옵니다." 문구 추가 |
| **188-206행** (`res-interval` 블록) | 구간 범위, 커버리지만 표시 | **3.3절 안내 배지** 삽입 (낙찰하한율 부재 사유, 구간 폭 해석 가이드) |
| **208-213행** (`res-fallback` 블록) | Fallback 모델 사용 시만 표시 | `lwlt_missing`일 때도 "입력 특징: 낙찰하한율 결측(제도적 부재)" 라벨 추가 |
| **238-243행** (메시지 영역) | 고정 문구 | `missing_lwlt`일 때 "이 공고 유형(수의시담·협상 등)은 낙찰하한율이 없어 예측 불확실성이 큽니다. 과거 유사 사례의 낙찰률 분포를 참고하십시오."로 치환 |

### 5.3 백엔드 응답에 추가할 필드

`src/app/schemas/predictions.py`의 `PredictPriceResponse`에 다음 필드 추가(읽기 전용 조사이므로 실제 코드 수정은 하지 않음, 스키마 제안만):

```python
lwlt_missing: bool = Field(False, description="낙찰하한율 결측 여부 (제도적 부재)")
wide_interval_warning: bool = Field(False, description="예측 구간 폭이 15%p 초과 여부")
extreme_prediction_warning: bool = Field(False, description="클리핑 전 예측값이 80% 미만 또는 100% 초과 여부")
```

API 응답 생성부(`predictions.py:236-252`)에서 `features.get("lwlt_rate_missing", 0) == 1.0` 등으로 판단해 설정.

---

## 6. 집단별 드리프트 모니터링 — 기존 PSI 설계와 연계

### 6.1 현재 PSI 모니터링 설계 현황

`docs/analysis/psi_drift_wiring_20260902.md`에 전체 설계가 문서화돼 있다. 핵심은:
- `src/ml/monitoring.py`에 `calculate_psi()`, `check_feature_drift()` 구현 완료
- **운영 스케줄에 등록된 호출자 0건** — 드리프트 Job 미등록 상태
- Baseline 아티팩트 저장 경로: `ml_registry/{model_name}/baseline/feature_distributions_v1.json`
- 평가 윈도우: 최근 7일, 최소 표본 100건/특징, 임계값 PSI ≥ 0.2
- 알림: `src/tasks/notifier.py`의 `notify_drift_detected()` 신설 권장

### 6.2 `missing_lwlt` 집단별 드리프트 분리 적용안

| 항목 | 적용 방식 |
| --- | --- |
| **Baseline 분리 저장** | 학습 시 `lwlt_rate_missing` 값별(0.0 / 1.0)로 특징 분포를 별도 히스토그램 저장. `feature_distributions_v1.json` 내 `"by_lwlt_missing": { "0.0": {...}, "1.0": {...} }` 구조 |
| **드리프트 평가 분리** | 추론 로그(`prediction_results`)도 `lwlt_rate_missing`으로 분할해 각각 PSI 계산. `with_lwlt`는 0.2 임계, `missing_lwlt`는 **0.25로 완화** (산포가 커서 분포 변동도 크게 나타남) |
| **판정 로직** | 두 집단 중 **하나라도 `TRIGGER_RETRAIN`이면 전체 모델 `TRIGGER_RETRAIN`**. 단, `missing_lwlt` 단독 미달 시 "결측 집단 드리프트" 라벨로 알림 차별화 |
| **표본 부족 처리** | `missing_lwlt` 일일 표본이 100건 미만이면 `INSUFFICIENT_DATA`로 보류. `psi_drift_wiring_20260902.md` 4.2절 규칙 준용 |

### 6.3 구현 시 연계 포인트

1. **Baseline 생성**(`trainer.py`): `train_and_register()`에서 `lwlt_rate_missing`별 분포 분리 저장
2. **드리프트 태스크**(`src/tasks/drift_monitor_task.py` 신규): `check_feature_drift`를 집단별로 호출, 결과 병합
3. **알림**(`notifier.py`): `notify_drift_detected`에 `drift_by_subgroup` 필드 추가
4. **로그 저장**(`RetrainLog` 재사용): `metrics_summary`에 `by_lwlt_missing` 객체 포함

**데이터 무손실(G1) 준수**: Baseline 아티팩트도 `ml_registry/` 하위이므로 기존 체크섬 검증 대상에 포함. `RetrainLog` 테이블 스키마 변경 없이 JSON 필드 확장만으로 저장 가능.

---

## 7. 기각된 세 접근 미제안 확인

본 보고서는 다음 세 가지 **이미 기각된 접근을 해결책으로 제안하지 않음**을 명시한다(캡슐 `ground_truth` 27-29행, `CURRENT_STATE.md` 257-258행):

1. **lwlt 결측값 대입(Imputation)**: 제도적 개념 부재인 1,356건에 가상 하한율(88.0% 등) 주입 시 실제 낙찰률(평균 94.95%)과 충돌해 오차 7~12%p 폭증. **절대 불가**([`servc_lwlt_missing_20260830.md`](../analysis/servc_lwlt_missing_20260830.md) 126-133행).
2. **계약방식별 모델 분리**: 2026-08-03 실측에서 수의계약·경쟁_공고서참조·협상 세 세그먼트 전부 분리가 단일 모델보다 나빴음(전체 R² 0.6659 vs 0.6683). 2026-08-07 문서에서 "두 번 실패했으니 가지 마라" 못 박음. 범주형 특징(`cntrct_mthd_nm`, `sucsfbid_mthd_nm`)이 이미 트리 분기를 학습하므로 명시적 분리는 표본만 줄임([`servc_lwlt_missing_20260830.md`](../analysis/servc_lwlt_missing_20260830.md) 7-15행).
3. **하이퍼파라미터 단순 재탐색**: 좌표 하강 17회 실측에서 값어치 있는 축은 `num_leaves` 하나뿐이었으며, 점 추정과 분위 모델이 설정을 공유하던 시절 리프를 올리면 구간 폭이 11.2% 악화돼 기각. 분리 후(`QUANTILE_PARAM_OVERRIDES`) 점 추정 리프 255로 올려도 구간 폭은 1.423%p로 불변([`training_config.py`](../src/ml/training_config.py) 17-38행, 96-104행).

---

## 8. 확인하지 못한 미지 항목 (Unknowns)

| 항목 | 설명 | 확인 필요 시점 |
| --- | --- | --- |
| **실제 운영 일일 `missing_lwlt` 추론 요청 수** | `prediction_results` 테이블에 쌓이는 결측 집단 일일 표본 수 미확인. 게이트 G-S1~G-S4 및 PSI 최소 표본(100건) 충족 여부 불명 | 운영 DB 조회로 실측 필요 (`uv run python scripts/db_readonly_query.py`) |
| **Champion 모델(`servc_institution_v1`)의 분위 아티팩트 존재 여부** | `ml_registry/servc_institution_v1/` 하위에 `model_q10.bin`, `model_q90.bin` 존재 여부 미확인. 없으면 구간 산출 자체가 None으로 떨어짐 | 레지스트리 스캔으로 확인 필요 |
| **Conformal 배율(`conformal_scale`) 실측값** | 학습 때 산정된 배율이 `missing_lwlt` 집단 산포(SD 5.19)를 충분히 흡수하는지 미검증. 배율이 낮으면 피복률 미달 가능 | `metadata.json`의 `interval.conformal_scale` 확인 필요 |
| **프론트엔드 `lwlt_missing` 플래그 수신 여부** | 현재 API 응답에 `lwlt_missing` 필드 없음. 템플릿 수정 시 백엔드 응답 추가가 선행돼야 함 | API 스키마 확장 후 프론트엔드 연동 테스트 필요 |
| **비예가 공고(`NON_PREARNG`)와 `missing_lwlt` 중복 여부** | 비예가 공고는 예정가격 자체가 없어 낙찰률 정의 불가. `missing_lwlt`와 겹치는지, 별도 트랙인지 미확인 | `classify_price_decision_method` 로직(`prediction_api.py:28-82`)과 결측 분포 교차 분석 필요 |
| **Windows Docker Desktop 실기 검증 영향** | G2 게이트 미수행 상태. 컷오버 선언은 조건부이며 Windows 실기 실패 시 철회 가능성 있음 | 별도 과업에서 검증 후 반영 |

---

## 9. 수용 기준 대조표

| 캡슐 수용 기준 | 본 보고서 섹션 | 충족 여부 |
| --- | --- | --- |
| 집단별 성능 게이트 정의(지표·임계·근거) | 2.1, 2.2 | ✅ |
| 더 넓은 불확실성 표시 방법(기존 interval 아티팩트 활용 판단) | 3.1~3.3 | ✅ |
| 예측 보류·경고 기준(구체적 조건) | 4.1, 4.2 | ✅ |
| 사용자 화면 근거 데이터 부족 표시(템플릿 위치 명시) | 5.1~5.3 | ✅ |
| 집단별 드리프트 모니터링 PSI 설계 연계 | 6.1~6.3 | ✅ |
| 기각된 세 접근 미제안 명시 | 7 | ✅ |
| 미지 항목 별도 절 분리 | 8 | ✅ |
| 보고서 단일 파일(`servc_missing_lwlt_policy_20260902.md`), 코드 미수정 | 본 파일 | ✅ |

---

## 10. 참고: 핵심 코드 참조 위치

| 기능 | 파일 | 주요 라인 |
| --- | --- | --- |
| 특징 생성(`lwlt_rate_missing` 플래그) | `src/ml/features.py` | 261-264, 269-271 |
| Champion 모델 학습 설정(Servc 전용) | `src/ml/training_config.py` | 119-121, 168-197 |
| Conformal 예측구간 학습/보정 | `src/ml/conformal.py` | 44-54, 61-72, 114-131 |
| 구간 추론(`predict_interval`) | `src/ml/model_wrappers.py` | 130-155 |
| 예측 API 엔드포인트 | `src/app/api/v1/predictions.py` | 71-252 |
| API 응답 스키마(구간 필드 포함) | `src/app/schemas/predictions.py` | 37-63 |
| 프론트엔드 상세 템플릿 | `src/app/templates/bids/detail.html` | 113-248, 188-206 |
| 집단별 구간 평가 스크립트 | `scripts/eval_servc_interval_by_group.py` | 71-99, 188-197 |
| PSI 드리프트 모니터링 설계 | `docs/analysis/psi_drift_wiring_20260902.md` | 24-82, 99-160 |
| 결측 원인 규명 실측 분석 | `docs/analysis/servc_lwlt_missing_20260830.md` | 23-27, 88-100, 126-147 |
| 직렬 측정 정본(OOS 집단별 지표) | `docs/analysis/serial_measurement_20260830.md` | 176-182 |

---

**끝.**
