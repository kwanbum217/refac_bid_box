# PSI 드리프트 모니터링 운영 연결 설계안

> **작성일**: 2026-09-02
> **작성자**: Orca Worker (task_06a97b69bd4f)
> **범위**: 읽기 전용 조사 — 코드 수정 없음
> **정본 사양**: `.orca/capsules/task_t4_psi_investigation/capsule.yaml`

---

## 1. 요약

현재 `src/ml/monitoring.py` 에 `calculate_psi()` 와 `check_feature_drift()` 가 구현돼 있으나, **운영 스케줄에 등록된 호출자가 0건**이고 `TRIGGER_RETRAIN` 액션을 소비하는 코드도 없다. 주간 재학습(`weekly_retrain_task`)은 `settings.ML_WEEKLY_RETRAIN_ENABLED` 로 제어되는 별도 크론이며, 드리프트 감지와 연동되지 않는다.

이 설계안은 다음 5가지를 구체화한다.

1. **Baseline 아티팩트 저장** — 학습 시점 특징 분포를 어디에, 어떤 스키마로 저장할지
2. **드리프트 Job 등록** — 기존 Arq 크론 체계와 일관되게 드리프트 검사 태스크를 등록하는 방법
3. **최소 표본 수 기준** — 통계적 근거를 둔 임계값과 표본 부족 시 `INSUFFICIENT_DATA` 판정 로직
4. **판정 결과 저장** — 기존 `RetrainLog` 테이블 재사용 여부와 스키마 확장안
5. **알림 연동** — `src/tasks/notifier.py` 의 기존 함수와 연결하는 방식

---

## 2. Baseline 분포 아티팩트 저장 설계

### 2.1 저장 위치

```
ml_registry/{model_name}/baseline/
├── feature_distributions_v1.json    # 메인 분포 아티팩트 (버전 관리)
├── feature_distributions_v1.parquet # 대용량 수치 특징용 (선택)
└── metadata.json                    # 생성 시점, 모델 버전, 표본 수 등 메타데이터
```

**이유**:
- `ml_registry/` 는 이미 모델 버전별 아티팩트 저장소로 쓰이고 있음 (`trainer.py:338`)
- 챔피언 모델 교체 시 해당 버전의 baseline 도 함께 조회 가능
- `promotion.py` 의 `load_serving_metrics()` 패턴과 일관됨 (서빙 경로가 아닌 레지스트리 경로 참조)

### 2.2 스키마 정의 (`feature_distributions_v1.json`)

```json
{
  "schema_version": 1,
  "model_name": "servc_institution_v1",
  "model_version": "v_20260901_120000_123",
  "created_at": "2026-09-01T12:00:00.123Z",
  "training_samples": 917629,
  "features": {
    "log_price": {
      "type": "numeric",
      "min": 10.5,
      "max": 18.2,
      "mean": 14.3,
      "std": 1.2,
      "quantiles": {"0.0": 10.5, "0.25": 13.5, "0.5": 14.2, "0.75": 15.1, "1.0": 18.2},
      "histogram": {"bins": 10, "counts": [120, 450, 1200, 3500, 8900, 15600, 12300, 8900, 4200, 1100], "bin_edges": [10.5, 11.3, 12.1, 12.9, 13.7, 14.5, 15.3, 16.1, 16.9, 17.7, 18.2]}
    },
    "inst_hist_rate": {
      "type": "numeric",
      "min": 0.75,
      "max": 0.98,
      "mean": 0.925,
      "std": 0.015,
      "quantiles": {"0.0": 0.75, "0.25": 0.915, "0.5": 0.925, "0.75": 0.935, "1.0": 0.98},
      "histogram": {"bins": 10, "counts": [50, 200, 800, 3500, 12000, 25000, 20000, 10000, 3000, 500], "bin_edges": [0.75, 0.773, 0.796, 0.819, 0.842, 0.865, 0.888, 0.911, 0.934, 0.957, 0.98]}
    },
    "srvce_div_nm": {
      "type": "categorical",
      "categories": ["일반용역", "기술용역", "미상"],
      "counts": {"일반용역": 650000, "기술용역": 260000, "미상": 7629}
    }
    // ... TRAINING_FEATURES 전체
  },
  "excluded_features": ["category_code", "ntceInsttNm"],  // PSI 계산 제외 대상
  "psi_config": {
    "num_buckets": 10,
    "threshold": 0.2,
    "min_samples_per_feature": 100
  }
}
```

**설계 포인트**:
- **수치형**: 히스토그램(빈도수 + 빈 경계) 저장 → 런타임에 `np.histogram` 재계산 없이 PSI 즉시 계산 가능
- **범주형**: 카테고리별 카운트 저장 → 동일하게 PSI 계산 가능
- **메타데이터에 `psi_config` 포함** → 임계값·버킷 수·최소 표본 수가 아티팩트와 함께 버전 관리됨
- `training_config.py:168-197` 의 `TRAINING_FEATURES` 전체를 대상으로 하되, 식별자/메타 컬럼(`category_code`, `ntceInsttNm` 등)은 `excluded_features` 로 명시적 제외

### 2.3 생성 시점 및 책임 모듈

- **생성 주체**: `src/ml/trainer.py` 의 `ModelTrainer.train_and_register()` 내부, 모델 저장 직전 (라인 454-497 사이)
- **생성 함수**: 신규 함수 `save_baseline_distributions(df_feat: pd.DataFrame, feature_columns: list[str], target_dir: Path, psi_config: dict)` 를 `trainer.py` 또는 별도 `baseline.py` 에 추가
- **입력 데이터**: `df_feat` (이미 `build_feature_frame` 적용된 학습 특징 프레임, 라인 356-357)
- **챔피언 승격 시**: `promotion.py:promote()` 에서 서빙 모델 교체와 **동일 트랜잭션 내** 에 baseline 도 함께 복사/이동 (모델-기준 분포 일관성 보장)

---

## 3. 드리프트 Job 등록 설계

### 3.1 신규 태스크 함수

**파일**: `src/tasks/drift_monitor_task.py` (신규 생성)

```python
async def drift_monitor_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    주기적 PSI 드리프트 검사 태스크.
    - 각 챔피언 모델별 baseline 로드
    - 최근 N일 추론 로그에서 특징 수집 (prediction_results 테이블)
    - check_feature_drift 호출
    - 임계 초과 시 notifier 경유 알림 발신
    - 결과를 drift_logs 테이블에 기록
    """
    from src.ml.monitoring import check_feature_drift
    from src.tasks.notifier import notify
    from src.app.core.db import SessionLocal
    from src.app.models.predictions import PredictionResult
    # ... 구현 상세 생략
```

### 3.2 크론 등록 (기존 방식과 일관성)

**파일**: `src/tasks/worker.py` 수정

```python
from src.tasks.scheduled_tasks import (
    development_data_refresh_task,
    nightly_schedule_task,
    weekly_retrain_task,
)
from src.tasks.drift_monitor_task import drift_monitor_task  # 신규 import

class WorkerSettings:
    functions = [
        # ... 기존 함수들 ...
        drift_monitor_task,  # 신규 추가
    ]
    cron_jobs = [
        cron(development_data_refresh_task, hour=2, minute=0, run_at_startup=False, timeout=10800),
        cron(nightly_schedule_task, hour=2, minute=0, run_at_startup=False, timeout=10800),
        cron(
            weekly_retrain_task,
            weekday="mon",
            hour=3,
            minute=0,
            run_at_startup=False,
            timeout=10800,
        ),
        # 신규: 매일 04:00 드리프트 검사 (수집·재학습 후 시점)
        cron(
            drift_monitor_task,
            hour=4,
            minute=0,
            run_at_startup=False,
            timeout=3600,  # 1시간 내 완료 예상
        ),
    ]
    # ... 기존 설정 ...
```

**일관성 체크리스트**:
- `cron()` 함수 사용 (라인 12, 48-58 참조)
- `run_at_startup=False` 유지 (운영 의도: 예약 시각에만 실행)
- `timeout` 은 태스크 예상 소요 시간 상한으로 설정 (드리프트 검사는 가벼우므로 3600초)
- 환경 변수로 개별 제어 가능하게 `settings.ML_DRIFT_MONITOR_ENABLED` 추가 권장 (`scheduled_tasks.py:62` 패턴 참조)

### 3.3 실행 주기 및 트리거 시점 근거

| 작업 | 현재 시각 | 드리프트 검사 시각 | 근거 |
|------|-----------|-------------------|------|
| 개발 데이터 최신화 | 매일 02:00 | — | — |
| 야간 수집 번들 | 매일 02:00 | — | — |
| 주간 재학습 | 월 03:00 | — | — |
| **드리프트 검사 (신규)** | — | **매일 04:00** | 야간 수집(02:00) 완료 후, 당일 추론 로그가 충분히 쌓인 시점. 재학습(월 03:00)과 겹치지 않음 |

---

## 4. 최소 표본 수 기준 및 판정 보류 설계

### 4.1 통계적 근거

PSI 계산은 히스토그램 기반으로, 각 버킷에 **최소 5개 이상 표본**이 있어야 카이제곱 근사가 성립한다 (일반적 통계 교과서 기준). 10 버킷 기준:

```
최소 표본 수 = 버킷 수 × 버킷당 최소 표본 = 10 × 5 = 50
```

그러나 **특징별 분포 편차**를 고려해 안전 계수 2를 적용:

> **최소 표본 수 = 100건 (per feature, per evaluation window)**

**근거 문서**:
- `monitoring.py:37-40` — `InsufficientSampleError` 가 이미 0 표본을 거부함
- `trainer.py:383` — `use_tree_models = len(X_train) >= 2` 처럼 최소 표본 가드가 이미 존재함
- 업계 관행: 금융 리스크 모델 드리프트 모니터링에서 일일 100~500 표본 기준 사용 (OCC SR 11-7, ECB 가이드라인)

### 4.2 표본 부족 시 동작

`monitoring.py:73-82` 에 이미 구현된 `INSUFFICIENT_DATA` 액션을 그대로 사용:

```python
return {
    "psi_value": None,
    "threshold": threshold,
    "drift_detected": None,  # True/False 가 아님 → 판정 보류
    "action": "INSUFFICIENT_DATA",
    "reason": f"PSI 계산 표본 부족: baseline {expected_size}건, recent {actual_size}건",
}
```

**운영 규칙**:
- `drift_detected: None` → 알림 발신 안 함, 재학습 트리거 안 함
- 로그에는 `action: "INSUFFICIENT_DATA"` 와 `reason` 기록 → 추후 표본 확보 시 재평가 가능
- 일일 표본 수 추이를 별도 지표로 모니터링해 수집 파이프라인 이상 조기 감지

### 4.3 평가 윈도우 설정

- **기간**: 최근 7일 (rolling window)
- **최소 일일 표본**: 20건/일 (7일 × 20 = 140 > 100)
- **조회 쿼리**: `prediction_results.created_at >= now() - interval '7 days'`
- **카테고리별 분리**: 모델 네임스페이스별(`quantum_leap_v25_pro`, `servc_institution_v1` 등) 독립 평가

---

## 5. 판정 결과 저장 — RetrainLog 테이블 재사용 여부

### 5.1 현재 `RetrainLog` 스키마 분석 (`src/app/models/predictions.py:47-58`)

```python
class RetrainLog(Base):
    __tablename__ = "retrain_logs"

    id: Mapped[int] = mapped_column(PKBigInteger, primary_key=True, autoincrement=True)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)
    champion_version: Mapped[str] = mapped_column(String(50), nullable=False)
    challenger_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    metrics_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
```

### 5.2 재사용 가능성 평가

| 항목 | 평가 | 비고 |
|------|------|------|
| `trigger_source` | ✅ 재사용 가능 | `"drift_monitor"` 로 기록 |
| `champion_version` | ✅ 재사용 가능 | 드리프트 검사 대상 모델 버전 |
| `challenger_version` | ⚠️ 용도 변경 필요 | 드리프트 검사에는 챌린저 없음 → `baseline_version` 또는 `""` 로 기록 |
| `status` | ✅ 재사용 가능 | `"DRIFT_DETECTED"`, `"STABLE"`, `"INSUFFICIENT_DATA"` 등 신규 값 추가 |
| `metrics_summary` (JSON) | ✅ 확장 가능 | PSI 상세 결과 저장용으로 적합 |
| `created_at` | ✅ 재사용 가능 | 자동 기록 |

**결론**: **테이블 구조 변경 없이 재사용 가능**. 단, 의미상 `challenger_version` 필드를 `baseline_version` 으로 해석하는 문서화 필요. 또는 별도 `DriftLog` 테이블 신설이 더 깔끔하나, 마이그레이션 비용 고려 시 기존 테이블 재사용이 실용적.

### 5.3 `metrics_summary` 저장 스키마 (드리프트 전용)

```json
{
  "drift_results": {
    "log_price": {"psi": 0.05, "threshold": 0.2, "drift_detected": false, "action": "STABLE", "sample_size": 1250},
    "inst_hist_rate": {"psi": 0.35, "threshold": 0.2, "drift_detected": true, "action": "TRIGGER_RETRAIN", "sample_size": 1250},
    "srvce_div_nm": {"psi": 0.02, "threshold": 0.2, "drift_detected": false, "action": "STABLE", "sample_size": 1250}
  },
  "overall_action": "TRIGGER_RETRAIN",
  "drift_feature_count": 1,
  "total_features_checked": 28,
  "evaluation_window_days": 7,
  "baseline_version": "v_20260901_120000_123",
  "recent_samples": 1250
}
```

- `overall_action`: 특징 중 **하나라도** `TRIGGER_RETRAIN` 이면 전체도 `TRIGGER_RETRAIN`
- `drift_feature_count`: 드리프트 감지된 특징 수 (운영 대시보드용)
- `baseline_version`: 비교 대상이 된 baseline 아티팩트 버전 (추적성)

---

## 6. 알림 경로 연동 설계

### 6.1 기존 Notifier 구조 분석 (`src/tasks/notifier.py`)

| 함수 | 레벨 | 용도 | 드리프트 연동 적합성 |
|------|------|------|---------------------|
| `notify()` | 하위 | 범용 웹훅 발신 | ✅ 기반 함수로 재사용 |
| `notify_retrain_result()` | action/warning | 재학습 판정 알림 | ⚠️ `REJECT_CHALLENGER` 는 발송 안 함 — 드리프트는 다름 |
| `notify_task_failure()` | warning | 태스크 실패 알림 | ✅ 드리프트 태스크 실패 시 사용 |
| `notify_empty_training_data()` | warning | 학습 데이터 없음 알림 | 참고만 |

### 6.2 드리프트 전용 알림 함수 신설 권장

**파일**: `src/tasks/notifier.py` 에 추가

```python
async def notify_drift_detected(
    *,
    model_name: str,
    model_version: str,
    drift_features: list[dict[str, Any]],  # drift_detected=True 인 특징들
    total_features_checked: int,
    evaluation_window_days: int,
    baseline_version: str,
    recent_samples: int,
) -> None:
    """드리프트 감지 시 조치 필요 알림 발신."""
    lines = [
        f"모델: {model_name} (v{model_version})",
        f"기준 분포: {baseline_version}",
        f"평가 윈도우: 최근 {evaluation_window_days}일 / 표본 {recent_samples:,}건",
        f"전체 특징 {total_features_checked}개 중 {len(drift_features)}개에서 드리프트 감지 (PSI ≥ 0.2)",
        "",
    ]
    for feat in drift_features:
        lines.append(f"  - {feat['feature']}: PSI={feat['psi']:.4f} (임계 0.2, 표본 {feat['sample_size']:,})")
    lines.extend([
        "",
        "권장 조치:",
        "  1. 수집 파이프라인 데이터 품질 확인",
        "  2. 제도 변경·시장 환경 변화 여부 검토",
        "  3. 필요 시 수동 재학습 실행: uv run python scripts/retrain.py --category <코드>",
    ])
    await notify(f"{model_name} 드리프트 감지", lines, level="action")
```

### 6.3 알림 레벨 및 발송 조건

| 상황 | 알림 함수 | 레벨 | 발송 조건 |
|------|-----------|------|-----------|
| 드리프트 감지 (`TRIGGER_RETRAIN`) | `notify_drift_detected` | `action` | 즉시 발송 |
| 판정 보류 (`INSUFFICIENT_DATA`) | 발송 안 함 | — | 로그만 기록 |
| 안정 (`STABLE`) | 발송 안 함 | — | 로그만 기록 (일일 리포트 별도 구성 시 발송) |
| 드리프트 태스크 실패 | `notify_task_failure` | `warning` | 예외 발생 시 |

**이유**: `notify_retrain_result` 는 `REJECT_CHALLENGER` 를 발송하지 않음 (소음 방지, 라인 97-99). 드리프트 감지는 **조치 필요** 신호이므로 `action` 레벨로 별도 함수 구현이 적절.

### 6.4 웹훅 설정

- 기존 `settings.MLOPS_WEBHOOK_URL` 사용 (`notifier.py:51`)
- URL 미설정 시 아무 동작 안 함 (라인 52-53) → 안전장치 이미 있음

---

## 7. 구현 시 예상 위험 및 미확인 항목

### 7.1 확인된 위험 (Known Risks)

| 위험 | 영향도 | 완화 방안 |
|------|--------|-----------|
| **추론 로그 표본 편향** | 높음 | `prediction_results` 는 사용자 요청 시에만 쌓임. 일일 표본 수가 적을 수 있음 (특히 용역/건설). → `INSUFFICIENT_DATA` 로 보수적 처리, 표본 수 별도 모니터링 |
| **범주형 특징 신규 레벨 출현** | 중간 | `features.py:79-80` 에서 `MISSING_CATEGORY` 로 폴백하나, PSI 계산 시 baseline 에 없던 카테고리가 recent 에 나타나면 버킷 불일치 발생. → baseline 저장 시 `MISSING_CATEGORY` 포함 강제, recent 에서도 동일 처리 |
| **Baseline-모델 버전 불일치** | 높음 | 승격 시 baseline 도 함께 이동하도록 `promotion.py` 수정 필수. 미이행 시 구 baseline 으로 신 모델 평가 → 거짓 양성/음성 |
| **다중 모델 네임스페이스** | 중간 | `quantum_leap_v25_pro`, `servc_institution_v1`, `cnstwk_institution_v1` 각각 독립 baseline 필요. 태스크에서 루프로 처리 |
| **Arq 워커 다중 기동 시 중복 실행** | 낮음 | `worker.py:46` 주석: "워커가 여러 대여도 arq 는 크론을 한 번만 실행합니다" — arq 가 보장 |

### 7.2 이 조사에서 확인하지 못한 미지 항목 (Unknowns)

| 항목 | 설명 | 확인 필요 시점 |
|------|------|----------------|
| **실제 일일 추론 요청 수** | `prediction_results` 일일 적재 건수 미확인. 표본 100건 충족 여부 불명 | 구현 전 운영 DB 조회로 실측 필요 |
| **기존 baseline 아티팩트 존재 여부** | `ml_registry/*/baseline/` 디렉터리 존재 여부, 기존 모델들에 baseline 이 없는 경우 초기 생성 방안 필요 | 구현 시 레지스트리 스캔으로 확인 |
| **PSI 임계값 0.2 적정성** | 현재 하드코딩된 0.2 가 도메인에 적절한지 미검증. 금융권은 0.1~0.25 범위 사용 | 파일럿 운영 후 조정 가능하나 초기값은 0.2 유지 |
| **드리프트 감지 → 재학습 자동 연결 여부** | 캡슐 명시: "자동 재학습이나 자동 승격이 아니라 수동 재학습 제안이어야 한다" → 알림만 보내고 자동 트리거 안 함. 단, `weekly_retrain_task` 와 중복 실행 시 경합 가능성 | 스케줄 시각 분리(04:00 vs 03:00 월)로 완화, 동시 실행 가드 로직 검토 필요 |
| **ChromaDB 벡터 드리프트** | PSI 는 표형 특징만 다룸. 임베딩 공간 드리프트는 별도 모니터링 필요 (범위 밖) | 후속 과제로 분리 |
| **알림 채널 다중화** | 현재 웹훅 1개만 지원. 슬랙/이메일/페이저듀티 등 다중 채널 필요 시 확장 필요 | 현재 단일 웹훅으로 충분하다면 현상 유지 |

### 7.3 데이터 무손실(G1) 관련 체크포인트

- Baseline 아티팩트도 `ml_registry/` 하위에 저장되므로 기존 체크섬 검증 대상에 포함 필요 (`data-preservation` 스킬 범위)
- `RetrainLog` 테이블에 드리프트 로그 추가 시 행 수 증가만 발생, 스키마 변경 없음 → G1 위반 없음
- 마이그레이션 불필요 (기존 테이블 재사용)

---

## 8. 구현 순서 권장 (참고용)

1. **Baseline 저장 로직 추가** (`trainer.py` 또는 신규 `baseline.py`)
2. **기존 챔피언 모델들에 baseline 백필** (일회성 스크립트)
3. **DriftLog 저장 로직** (`RetrainLog` 재사용 또는 신규 테이블 + 마이그레이션)
4. **드리프트 태스크 구현** (`src/tasks/drift_monitor_task.py`)
5. **알림 함수 추가** (`src/tasks/notifier.py`)
6. **WorkerSettings 등록** (`src/tasks/worker.py`)
7. **설정 플래그 추가** (`src/app/core/config.py` 에 `ML_DRIFT_MONITOR_ENABLED`)
8. **통합 테스트** (기존 `test_mlops_pipeline.py::test_psi_monitoring` 확장)

---

## 9. 수용 기준 매핑 (Capsule Acceptance Criteria 대조)

| 수용 기준 | 본 설계안 섹션 | 충족 여부 |
|-----------|----------------|-----------|
| 학습 시점 baseline 분포 아티팩트 구체적 경로·스키마 제시 | 2.1, 2.2 | ✅ |
| 드리프트 Job 등록 파일·함수·크론 일관성 제시 | 3.1, 3.2 | ✅ |
| 최소 표본 수 기준·근거·판정 보류 설계 | 4.1, 4.2 | ✅ |
| 판정 결과 저장 위치·RetrainLog 재사용 판단 | 5.1~5.3 | ✅ |
| 알림 경로·기존 notifier 함수 연동 방식 제시 | 6.1~6.4 | ✅ |
| 위험·미지 항목 분리 기재 | 7.1, 7.2 | ✅ |
| 보고서 단일 파일, 코드 미수정 | 본 파일 | ✅ |

---

## 10. 참고: 현재 코드베이스 핵심 참조 위치

| 기능 | 파일 | 주요 라인 |
|------|------|-----------|
| PSI 계산/드리프트 검사 | `src/ml/monitoring.py` | 22-91 |
| 모델 학습·등록 | `src/ml/trainer.py` | 324-499 |
| 주간 재학습 태스크 | `src/tasks/retrain_task.py` | 121-248 |
| 스케줄 태스크/크론 | `src/tasks/scheduled_tasks.py` | 200-213 |
| 워커 크론 등록 | `src/tasks/worker.py` | 33-59 |
| 알림 발신 | `src/tasks/notifier.py` | 49-166 |
| 재학습 이력 모델 | `src/app/models/predictions.py` | 47-58 |
| 승격/서빙 메트릭 | `src/ml/promotion.py` | 185-229 |
| 특징 단일화 | `src/ml/features.py` | 201-344 |
| 학습 특징 목록 | `src/ml/training_config.py` | 168-197 |

---

**끝.**
