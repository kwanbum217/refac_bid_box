# Servc 취약 집단 missing_lwlt 운영 대응 구현 보고서

> **작성일**: 2026-09-02
> **작성자**: Orca Worker (task_323bfebce1e9)
> **정본 사양**: `.orca/capsules/task_c3_servc_missing_lwlt_impl/capsule.yaml`
> **선행 정책 정본**: [`servc_missing_lwlt_policy_20260902.md`](servc_missing_lwlt_policy_20260902.md)

---

## 1. 개요 및 배경

본 과업은 Servc 낙찰가 예측 모델에서 낙찰하한율(`lwlt_rate`)이 제도적으로 부재한 `missing_lwlt` 취약 집단(OOS 1,356건, 37.8%)의 안전한 운영 대응을 서빙 및 UI 단에 구현한 작업입니다.

[`servc_missing_lwlt_policy_20260902.md`](servc_missing_lwlt_policy_20260902.md) 2절부터 5절의 정책을 바탕으로 다음을 구현했습니다:
1. 예측 응답 스키마(`PredictPriceResponse`)에 결측 여부, 결측 사유, 불확실성 경고 필드 추가 (기존 계약 100% 보존).
2. 예측 API(`predict_price_api`)에서 [`features.py`](../../src/ml/features.py)의 단일 특징(`lwlt_rate_missing`)을 통한 결측 판정 및 운영 경고 생성.
3. 운영 경고 임계값(구간 폭 15%p, 극단 낙찰률 80%~100%)을 모듈 상수로 일원화하고 실측 근거 주석 명시.
4. 사용자 상세 화면([`detail.html`](../../src/app/templates/bids/detail.html))에 근거 데이터 부족 안내 배지 및 넓은 구간 경고 배지 연동.
5. 예측 거부(하드 차단) 없는 안정적 서빙 유지.

---

## 2. 세부 구현 내역

### 2.1 API 응답 스키마 확장 ([`predictions.py`](../../src/app/schemas/predictions.py))

기존 `PredictPriceResponse`의 모든 필드명과 타입을 보존하면서, 불확실성 및 결측 정보를 전달하기 위한 필드를 추가했습니다:

```python
# missing_lwlt 취약 집단 및 불확실성 경고 필드 (docs/analysis/servc_missing_lwlt_policy_20260902.md)
lwlt_missing: bool = Field(False, description="낙찰하한율 결측 여부 (제도적 부재)")
lwlt_missing_reason: str | None = Field(
    None, description="낙찰하한율 결측 사유 (제도적 부재 구분)"
)
wide_interval_warning: bool = Field(
    False, description="예측 구간 폭이 임계값(15%p) 초과 여부"
)
extreme_prediction_warning: bool = Field(
    False, description="클리핑 전 예측 낙찰률이 정상 범위(80%~100%) 이탈 여부"
)
uncertainty_warning: str | None = Field(
    None, description="불확실성 안내 및 경고 메시지"
)
```

### 2.2 서빙 엔드포인트 및 경고 임계값 일원화 ([`predictions.py`](../../src/app/api/v1/predictions.py))

임계값을 모듈 상단에 일원화하고 OOS 3,589건 실측 근거를 명시했습니다:

- `WIDE_INTERVAL_THRESHOLD_PERCENT = 15.0`: 결측 집단 구간 폭 중앙값(~10-12%p) 대비 상위 25% 분위에 해당하여 비정상적으로 넓은 구간 식별.
- `EXTREME_RATE_MIN_PERCENT = 80.0`, `EXTREME_RATE_MAX_PERCENT = 100.0`: 정상 조달 낙찰률 범위를 벗어나는 극단 예측값 경고.
- `_classify_lwlt_missing_reason`: [`features.py`](../../src/ml/features.py)가 생성한 계약/입찰 방식 특징을 기반으로 수의계약, 협상, 규격가격동시 등 제도적 사유를 분류.
- 단일 특징 공급원 준수: 결측 판정은 `features.get("lwlt_rate_missing", 0.0) == 1.0`을 직접 사용하여 학습/추론 일치 보장.

### 2.3 프론트엔드 상세 템플릿 연동 ([`detail.html`](../../src/app/templates/bids/detail.html))

- `res-interval` 카드 내부에 `res-lwlt-missing`(근거 데이터 부족 배지) 및 `res-wide-interval`(넓은 구간 경고 배지) 추가.
- 컴파일된 Tailwind CSS(`src/app/static/css/tailwind.css`)에 존재하는 클래스(`bg-amber-50`, `border-amber-200`, `text-amber-700`, `font-bold` 등)만 사용하여 스타일 깨짐 방지.
- JavaScript `$.ajax` 응답 핸들러에서 `data.lwlt_missing` 및 `data.wide_interval_warning` 상태에 따라 배지 노출을 제어.

---

## 3. 기각된 3대 접근 미구현 확인

본 작업은 다음 세 가지 기각된 접근을 일체 포함하지 않았습니다:
1. **lwlt 결측값 대입 (Imputation)**: 가상 하한율 주입 시 오차 폭증 위험으로 배제.
2. **계약방식별 모델 분리**: 단일 모델 대비 성능 열세로 배제.
3. **하이퍼파라미터 단순 재탐색**: 구간 폭 개선 효과 없음으로 배제.

또한 `src/ml/` 및 `src/tasks/` 하위 파일은 전혀 수정하지 않아 다른 병행 작업과의 충돌을 원천 차단했습니다.

---

## 4. 검증 결과

### 4.1 단위 및 통합 테스트 (`tests/test_missing_lwlt_serving.py`)
- `TestPredictPriceResponseSchema`: 신규 필드 및 기존 14개 필드 계약 보존 검증 통과.
- `TestMissingLwltServing`: 수의계약 결측 공고(200 OK, 경고 부착) 및 일반경쟁 정상 공고(200 OK, 경고 미부착) 서빙 검증 통과.
- `TestUncertaintyAndWarningThresholds`: 구간 폭 15%p 초과 및 극단 예측값(75%, 102%) 경고 트리거 검증 통과.
- `TestMissingReasonClassification`: 수의, 협상, 규격가격동시 등 결측 사유 분류 검증 통과.
- `TestDetailTemplateElements`: 템플릿 배지 및 자바스크립트 바인딩 검증 통과.

### 4.2 Tailwind 빌드 정합성 테스트 (`tests/test_tailwind_build.py`)
- `test_template_tailwind_utilities_exist_in_build_css` 포함 6개 테스트 전량 통과.

---

## 5. 변경 파일 목록

| 파일 경로 | 작업 내용 |
| --- | --- |
| `src/app/schemas/predictions.py` | `PredictPriceResponse`에 결측/불확실성 필드 5종 추가 |
| `src/app/api/v1/predictions.py` | 경고 임계값 상수화, 결측 사유 분류기, `predict_price_api` 응답 구성 |
| `src/app/templates/bids/detail.html` | 예측 구간 카드 내 근거 데이터 부족 및 넓은 구간 경고 배지/JS 추가 |
| `tests/test_missing_lwlt_serving.py` | missing_lwlt 서빙, 임계값, 스키마, 템플릿 검증 신규 테스트 (13건) |
| `docs/analysis/task_323bfebce1e9.md` | 본 작업 분석 및 검증 완료 보고서 |
