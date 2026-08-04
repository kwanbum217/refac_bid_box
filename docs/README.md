# refac_bid_box 문서 인덱스

> **작성일**: 2026-07-31
> **정정일**: 2026-07-31
> **버전**: v1.1.0
> **상태**: Phase 0 완료 / Phase 1~3 진행 중
> **적용 범위**: `bid_box` (Django) → `refac_bid_box` (FastAPI + SSR/HTMX) 전환

---

## 문서 목록

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **리팩토링 설계서** | [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | 전체 리팩토링 청사진 |
| **프론트엔드 결정** | [`design/FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md) | SSR+HTMX 확정, React SPA 중단 |

---

## 폴더 구조

```
docs/
├── README.md
├── design/
├── migration/
├── ops/
├── handoff/
└── changelogs/
```

---

## 1. design/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 리팩토링 설계서 | [`REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | AS-IS/TO-BE, 로드맵 |
| 프론트엔드 결정 | [`FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md) | SSR+HTMX ADR, React 동결 및 노출 차단 |
| React 재현 설계 (기각) | [`frontend_react_reproduction_design.md`](design/frontend_react_reproduction_design.md) | 검토 후 기각. SSR 정본 유지 근거 |
| 용역 낙찰률 예측 모델 | [`servc_prediction_model_design.md`](design/servc_prediction_model_design.md) | 특징 설계, 절제 실험, 승격 기준 |
| G2B 전자입찰 제도 분석 | [`g2b_procurement_institution_analysis.md`](design/g2b_procurement_institution_analysis.md) | 예정가격·낙찰하한율 산식, 2026-05-26 제도 변경 |
| 용역 제도 가정 검증 보고 | [`servc_institution_verification_20260803.md`](design/servc_institution_verification_20260803.md) | V1~V7 데이터 검증 결과, 설계 정정 사항 |
| 용역 분리 모델 실험 | [`servc_segment_experiment_20260803.md`](design/servc_segment_experiment_20260803.md) | 분리 모델·하한율 절단 기각, 제도 특징 채택 |
| 용역 2025년 연도 홀드아웃 | [`servc_year_holdout_2025_20260803.md`](design/servc_year_holdout_2025_20260803.md) | 공고 건당 오차 분포, 연초 성능 저하 |
| 제한경쟁 진단과 난수 구조 | [`servc_restricted_competition_20260803.md`](design/servc_restricted_competition_20260803.md) | 참여업체 수·복수예가 난수 분해, 세부분류 특징 배선 |
| 손실함수와 반복 발주 이력 | [`servc_repeat_procurement_20260803.md`](design/servc_repeat_procurement_20260803.md) | Huber 채택, 재발주 이력 6종, 공고명 텍스트 기각 |
| 예측 구간 보정 측정 | [`servc_prediction_interval_20260804.md`](design/servc_prediction_interval_20260804.md) | 분위 회귀 피복률 실패, 등각예측 보정, 서빙 미착수 |

## 2. migration/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| DB 마이그레이션 | [`db_migration_runbook.md`](migration/db_migration_runbook.md) | 덤프/복원/검증 |
| ML/Chroma 검증 | [`ml_weights_verification.md`](migration/ml_weights_verification.md) | 체크섬·회귀 테스트 |

## 3. handoff/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 인수인계 (정정본) | [`2026-07-31_skill_system_handoff.md`](handoff/2026-07-31_skill_system_handoff.md) | 실제 진행 상태 |
| 원본 재현율 복원 | [`2026-07-31_parity_restoration_handoff.md`](handoff/2026-07-31_parity_restoration_handoff.md) | 데이터 유실 복구, 조작·결함 7건 수정, 스택 변경 |
| 백필 완료 | [`2026-08-03_backfill_complete.md`](handoff/2026-08-03_backfill_complete.md) | 과거 결손 복구 결과 |
| 용역 제도 특징 1차 | [`2026-08-03_servc_institution_handoff.md`](handoff/2026-08-03_servc_institution_handoff.md) | 제도 특징 배선 |
| 용역 모델 개선 2차 | [`2026-08-03_servc_model_tuning_handoff.md`](handoff/2026-08-03_servc_model_tuning_handoff.md) | R2 0.6968, MAE -15.6% |
| 용역 제도 분석 인수인계 | [`2026-08-03_servc_institution_handoff.md`](handoff/2026-08-03_servc_institution_handoff.md) | 제도 특징 배선, 세부분류 채택 |
| 용역 모델 튜닝 인수인계 | [`2026-08-03_servc_model_tuning_handoff.md`](handoff/2026-08-03_servc_model_tuning_handoff.md) | Huber, 재발주 이력, 기각 목록 |
| 서빙 배선 인수인계 | [`2026-08-04_servc_serving_handoff.md`](handoff/2026-08-04_servc_serving_handoff.md) | 특징 단일화, 승격 경로, 예측 구간 |

## 4. changelogs/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 작업 일지 | [`changelogs/work_log.md`](changelogs/work_log.md) | Phase별 누적 기록 |

---

## 권장 독해 순서

1. [`README.md`](../README.md)
2. [`AGENTS.md`](../AGENTS.md) / [`SKILLS.md`](../SKILLS.md)
3. [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md)
4. [`handoff/2026-07-31_parity_restoration_handoff.md`](handoff/2026-07-31_parity_restoration_handoff.md)
5. [`handoff/2026-07-31_skill_system_handoff.md`](handoff/2026-07-31_skill_system_handoff.md)
6. [`migration/ml_weights_verification.md`](migration/ml_weights_verification.md)

---

_본 인덱스는 살아있는 문서입니다._
